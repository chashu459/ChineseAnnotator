"""Polyphone (多音字) disambiguation using the lightweight g2pM neural model.

The annotation pipeline (see AnnotationView.annotate in api/views/views.py)
segments text with a Trie and annotates each phrase with the pinyin of the
lowest-priority dictionary entry. That works well when a multi-character phrase
is in the dictionary, but a single character with several readings (a 多音字)
always gets the same default reading regardless of context.

This module adds an optional contextual disambiguation step on top of that
pipeline:

- g2pM (https://github.com/kakaobrain/g2pM, Apache-2.0) is a single-layer
  BiLSTM (~1.7MB, numpy-only, no GPU needed) trained specifically for Mandarin
  polyphone disambiguation. It scores 97.31% on the CPP benchmark, close to a
  full Chinese BERT (97.85%) at a fraction of the size.
- We run it once per annotation request over the full input text. With
  char_split=True it returns exactly one pinyin per input character, so the
  output aligns 1:1 with the input text.
- For a single-character phrase whose dictionary entries disagree on the
  reading, the contextual prediction wins -- but ONLY when the predicted
  reading is one of the dictionary's known candidates. This keeps the change
  conservative: g2pM re-ranks existing candidates, it never invents new
  readings.

If g2pM is unavailable (not installed, model fails to load, prediction fails),
every function here degrades gracefully and the caller falls back to the
existing priority-list behavior, so annotation never breaks.
"""

import re
import threading

# g2pM emits ASCII pinyin with a tone digit, e.g. 'hong2', 'le5', 'r5'.
# (The repo's parsePinyin in api/utils.py converts this to toned Unicode.)
_PINYIN_RE = re.compile(r"^[a-zA-Z\xfc\xdc:]+[1-5]$")

# Provenance of a character's pinyin, exposed to the frontend so it can
# highlight where each reading came from (dev mode only).
SOURCE_DICT = "dict"        # dictionary / priority-list reading used
SOURCE_G2PM = "g2pm"        # g2pM's contextual prediction overrode the dictionary
SOURCE_CONFLICT = "conflict"  # g2pM disagreed but its reading isn't a known
                              # candidate, so the dictionary reading was kept

_model = None
_model_failed = False

# --- toned -> ASCII pinyin -------------------------------------------------
# The API exposes toned Unicode pinyin (e.g. 'háng'); the curation endpoints
# below accept either form and normalize back to ASCII ('hang2').

_TONED_VOWELS = {
    "ā": ("a", "1"), "á": ("a", "2"), "ǎ": ("a", "3"), "à": ("a", "4"),
    "ē": ("e", "1"), "é": ("e", "2"), "ě": ("e", "3"), "è": ("e", "4"),
    "ī": ("i", "1"), "í": ("i", "2"), "ǐ": ("i", "3"), "ì": ("i", "4"),
    "ō": ("o", "1"), "ó": ("o", "2"), "ǒ": ("o", "3"), "ò": ("o", "4"),
    "ū": ("u", "1"), "ú": ("u", "2"), "ǔ": ("u", "3"), "ù": ("u", "4"),
    "ǖ": ("u:", "1"), "ǘ": ("u:", "2"), "ǚ": ("u:", "3"), "ǜ": ("u:", "4"),
    "ü": ("u:", "5"),
    "Ā": ("A", "1"), "Á": ("A", "2"), "Ǎ": ("A", "3"), "À": ("A", "4"),
    "Ē": ("E", "1"), "É": ("E", "2"), "Ě": ("E", "3"), "È": ("E", "4"),
    "Ī": ("I", "1"), "Í": ("I", "2"), "Ǐ": ("I", "3"), "Ì": ("I", "4"),
    "Ō": ("O", "1"), "Ó": ("O", "2"), "Ǒ": ("O", "3"), "Ò": ("O", "4"),
    "Ū": ("U", "1"), "Ú": ("U", "2"), "Ǔ": ("U", "3"), "Ù": ("U", "4"),
    "Ǖ": ("U:", "1"), "Ǘ": ("U:", "2"), "Ǚ": ("U:", "3"), "Ǜ": ("U:", "4"),
    "Ü": ("U:", "5"),
}


def unparse_pinyin(pinyin):
    """Normalize a pinyin string to ASCII + tone digit ('háng' -> 'hang2').

    Accepts ASCII form already ('hang2' passes through, lowercased) and toned
    Unicode. A toneless syllable is treated as neutral tone ('de' -> 'de5'),
    mirroring parsePinyin's 'r5' -> 'r' special case in reverse.
    """
    if not pinyin:
        return pinyin
    if looks_like_pinyin(pinyin):
        return pinyin.lower()
    for i, ch in enumerate(pinyin):
        if ch in _TONED_VOWELS:
            base, tone = _TONED_VOWELS[ch]
            return (pinyin[:i] + base + pinyin[i + 1:]).lower() + tone
    # No tone mark: treat as neutral tone only if it looks like a syllable
    # (contains a vowel). Otherwise return it unchanged so the caller's
    # looks_like_pinyin check rejects it instead of blessing garbage.
    lowered = pinyin.lower()
    if any(v in lowered for v in "aoeiuv\u00fc"):
        return lowered + "5"
    return pinyin


def normalize_pinyin(pinyin):
    """Canonicalize a pinyin syllable to the dictionary convention.

    unparse_pinyin() first (toned Unicode -> ASCII + tone digit), then
    unify the ü spellings: 'v' (g2pW's output, e.g. 'nv3'), 'ü'/'Ü', and
    the toned-ü forms all become 'u:' (the dictionary's spelling, e.g.
    'nu:3'), so equivalent readings compare equal.
    """
    p = unparse_pinyin(pinyin)
    if not isinstance(p, str):
        return p
    return (p.replace("v", "u:").replace("V", "u:")
             .replace("\u00fc", "u:").replace("\u00dc", "u:"))


# --- dismissed suggestions -------------------------------------------------
# "Mark as wrong" records (character, dictionary reading, g2pM suggestion)
# triples in data/g2pm_dismissed.json. A dismissed triple never flags a
# Dismissed suggestions: data/g2pm_dismissed.json is a list of rows
# {char, dict_pinyin, suggested_pinyin, prev_char, next_char}. The key
# captures "where the dictionary reads this char as X in the context of
# <prev><char><next>, don't bother me when the model says Y" -- context
# matters because the same suggestion can be wrong in one word and right in
# another. prev_char/next_char are the character's immediate neighbors
# within its phrase ("" at phrase edges). Rows written before context
# existed load with "" neighbors and therefore only match empty context.

_dismissed = None


def _dismissed_path():
    try:
        from django.conf import settings
        return str(settings.BASE_DIR / "data" / "g2pm_dismissed.json")
    except Exception:
        import os
        return os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "data",
            "g2pm_dismissed.json")


def _load_dismissed():
    """Lazily load the dismissed-suggestion set. Never raises."""
    global _dismissed
    if _dismissed is not None:
        return _dismissed
    _dismissed = set()
    try:
        import json
        with open(_dismissed_path()) as f:
            for row in json.load(f):
                _dismissed.add((row["char"], row["dict_pinyin"],
                                row["suggested_pinyin"],
                                row.get("prev_char", ""),
                                row.get("next_char", "")))
    except Exception:
        pass
    return _dismissed


def clear_dismissed_cache():
    """Forget the cached dismissal set so the next lookup re-reads the file."""
    global _dismissed
    _dismissed = None


def is_dismissed(char, dict_pinyin, suggested_pinyin, prev_char="",
                 next_char=""):
    """Whether this suggestion was marked wrong in this context.

    Matches the (char, prev_char, next_char, dict reading -> model
    suggestion) tuple; neighbors default to "" (phrase edges, or rows
    written before context existed).
    """
    return (char, unparse_pinyin(dict_pinyin), unparse_pinyin(suggested_pinyin),
            prev_char or "", next_char or "") in _load_dismissed()


def is_enabled():
    """Whether the polyphone disambiguation step should run at all.

    Master kill switch for both models. Controlled by the G2PM_ENABLED
    Django setting (default True), which itself can be set via the
    G2PM_ENABLED environment variable.
    """
    try:
        from django.conf import settings
        return bool(getattr(settings, "G2PM_ENABLED", True))
    except Exception:
        # Standalone (no Django settings configured): stay enabled so the
        # pure logic remains testable.
        return True


# Available disambiguation models. "g2pm" is the default lightweight BiLSTM;
# "g2pw" is the BERT-based alternative (99.08% vs 97.31% on the CPP
# benchmark) for A/B testing. "g2pc" is a user fine-tuned g2pM: the same
# BiLSTM architecture, but with custom weights loaded from G2PC_CKPT_PATH
# (default data/models/g2pc/np_ckpt.pkl) -- the numpy checkpoint format the
# g2pM package itself uses (see G2pM.load_variable). Selected via the
# G2P_MODEL Django setting / environment variable, or per-request by the
# dev-only provenance endpoint.
G2P_MODEL_G2PM = "g2pm"
G2P_MODEL_G2PW = "g2pw"
G2P_MODEL_G2PC = "g2pc"
G2P_MODEL_LLM = "llm"
G2P_MODELS = (G2P_MODEL_G2PM, G2P_MODEL_G2PW, G2P_MODEL_G2PC, G2P_MODEL_LLM)

MODEL_LABELS = {
    G2P_MODEL_G2PM: "g2pM",
    G2P_MODEL_G2PW: "g2pW",
    G2P_MODEL_G2PC: "g2pC",
    G2P_MODEL_LLM: "LLM",
}


def active_model():
    """Which disambiguation model to use (default "g2pm")."""
    try:
        from django.conf import settings
        name = str(getattr(settings, "G2P_MODEL", G2P_MODEL_G2PM)).lower()
    except Exception:
        name = G2P_MODEL_G2PM
    return name if name in G2P_MODELS else G2P_MODEL_G2PM


def model_label(model=None):
    """Display label for a model name ("g2pM", "g2pW", "LLM")."""
    return MODEL_LABELS.get(model or active_model(),
                            MODEL_LABELS[G2P_MODEL_G2PM])


def distinct_readings(entries):
    """Distinct known readings across entries, in priority order.

    In-memory entries carry toned pinyin (see api/EntryManager); readings
    are normalized to ASCII + tone digit here because this feeds the model
    comparison path (g2pM/g2pW/LLM all emit ASCII).
    """
    return ([normalize_pinyin(c) for c in _distinct_readings(entries)]
            if entries else [])


def model_available(model=None):
    """Whether the given model is installed and loadable.

    Unlike predict_with_confidence (which silently falls back to None),
    this is for callers that want to fail loudly, e.g. the dev-only
    provenance endpoint. The load result is cached, so repeated calls are
    cheap. Note: the first g2pW check kicks off a background download of
    the ~590MB model file (see g2pw_status); it returns False until the
    model is ready.
    """
    if not is_enabled():
        return False
    name = model or active_model()
    if name == G2P_MODEL_LLM:
        from api import llm_adjudicator
        return llm_adjudicator.available()
    if name == G2P_MODEL_G2PW:
        return get_g2pw_converter() is not None
    if name == G2P_MODEL_G2PC:
        return get_g2pc_model() is not None
    return get_model() is not None


def advisory_mode():
    """Whether g2pM may only flag disagreements, never override (default True).

    In advisory mode the dictionary reading is always kept; a g2pM
    disagreement is reported as SOURCE_CONFLICT for dictionary curation
    instead of overriding the reading. Controlled by the G2PM_ADVISORY_MODE
    Django setting / environment variable.
    """
    try:
        from django.conf import settings
        return bool(getattr(settings, "G2PM_ADVISORY_MODE", True))
    except Exception:
        return True
    except Exception:
        return True


def get_model():
    """Lazily load and cache the g2pM model. Returns None if unavailable."""
    global _model, _model_failed
    if _model is not None:
        return _model
    if _model_failed:
        return None
    try:
        from g2pM import G2pM
        _model = G2pM()
        return _model
    except Exception as exc:
        print(f"[polyphone] g2pM unavailable, falling back to priority list: {exc}")
        _model_failed = True
        return None


_g2pc_model = None
_g2pc_failed = False


def _g2pc_ckpt_path():
    """Filesystem path of the user's fine-tuned g2pM checkpoint."""
    try:
        from django.conf import settings
        custom = getattr(settings, "G2PC_CKPT_PATH", None)
        if custom:
            return str(custom)
        return str(settings.BASE_DIR / "data" / "models" / "g2pc" / "np_ckpt.pkl")
    except Exception:
        import os
        return os.path.join(os.getcwd(), "data", "models", "g2pc", "np_ckpt.pkl")


def get_g2pc_model():
    """Lazily load the user's fine-tuned g2pM weights. Returns None when the
    checkpoint file doesn't exist (yet) or fails to load.

    The checkpoint is the numpy pickle format g2pM itself uses: a dict with
    keys like "embedding.weight", "lstm.weight_ih_l0", "logit_layer.0.weight"
    (see G2pM.load_variable). A missing file is *not* cached as a failure,
    so dropping the weights in later is picked up without a restart; a
    corrupt file is cached as failed.
    """
    global _g2pc_model, _g2pc_failed
    if _g2pc_model is not None:
        return _g2pc_model
    if _g2pc_failed:
        return None
    import os
    ckpt_path = _g2pc_ckpt_path()
    if not os.path.exists(ckpt_path):
        return None
    try:
        import pickle
        from g2pM import G2pM
        with open(ckpt_path, "rb") as f:
            state_dict = pickle.load(f)
        _g2pc_model = G2pM()
        _g2pc_model.load_variable(state_dict)
        print(f"[polyphone] g2pC loaded from {ckpt_path}")
        return _g2pc_model
    except Exception as exc:
        print(f"[polyphone] g2pC unavailable, falling back to priority list: {exc}")
        _g2pc_failed = True
        return None


def clear_g2pc_cache():
    """Forget the cached g2pC model (e.g. after replacing the checkpoint)."""
    global _g2pc_model, _g2pc_failed
    _g2pc_model = None
    _g2pc_failed = False


_g2pw_converter = None
_g2pw_failed = False
_g2pw_provisioning = False
_g2pw_lock = threading.Lock()

G2PW_READY = "ready"
G2PW_PROVISIONING = "provisioning"
G2PW_UNAVAILABLE = "unavailable"


def _g2pw_model_dir():
    """Where the g2pW ONNX model lives (downloaded on first use)."""
    try:
        from django.conf import settings
        custom = getattr(settings, "G2PW_MODEL_DIR", None)
        if custom:
            return str(custom)
        return str(settings.BASE_DIR / "data" / "models" / "g2pw")
    except Exception:
        import os
        return os.path.join(os.getcwd(), "G2PWModel")


def g2pw_status():
    """Current g2pW state: 'ready', 'provisioning', or 'unavailable'.

    'provisioning' means a background thread is downloading/loading the
    model; callers should treat it as retryable, not failed.
    """
    with _g2pw_lock:
        if _g2pw_converter is not None:
            return G2PW_READY
        if _g2pw_failed:
            return G2PW_UNAVAILABLE
        if _g2pw_provisioning:
            return G2PW_PROVISIONING
        return G2PW_UNAVAILABLE


def _provision_g2pw():
    """Download + load the g2pW model. Runs on a daemon thread."""
    global _g2pw_converter, _g2pw_failed, _g2pw_provisioning
    try:
        from g2pw import G2PWConverter
        print("[polyphone] provisioning g2pW in background "
              "(first use downloads ~590MB model)...")
        converter = G2PWConverter(
            model_dir=_g2pw_model_dir(),
            style="pinyin",
            enable_non_tradional_chinese=True,
        )
        with _g2pw_lock:
            _g2pw_converter = converter
        print("[polyphone] g2pW ready")
    except Exception as exc:
        print(f"[polyphone] g2pW unavailable: {exc}")
        with _g2pw_lock:
            _g2pw_failed = True
    finally:
        with _g2pw_lock:
            _g2pw_provisioning = False


def get_g2pw_converter():
    """Return the cached g2pW converter, or kick off background provisioning.

    Never blocks the request thread: on first use it spawns a daemon
    thread to download/load the ~590MB model and returns None. Callers
    should check g2pw_status() to distinguish 'provisioning' (retryable)
    from 'unavailable' (failed).

    g2pW (GitYCC/g2pW, Apache-2.0) is a BERT-based Mandarin G2P model served
    via ONNX -- no torch needed for inference, but the g2pw package imports
    torch at module level, so a torch install (CPU-only is fine) is still
    required. enable_non_tradional_chinese converts simplified input to
    traditional for the model (it was trained on traditional text); the
    conversion is 1:1 so output alignment is preserved.
    """
    global _g2pw_provisioning
    with _g2pw_lock:
        if _g2pw_converter is not None:
            return _g2pw_converter
        if _g2pw_failed or _g2pw_provisioning:
            return None
        _g2pw_provisioning = True
    thread = threading.Thread(target=_provision_g2pw, daemon=True,
                              name="g2pw-provision")
    thread.start()
    return None


def _predict_g2pw(text):
    """Run g2pW over the text.

    Returns (pinyins, confidences) like predict_with_confidence: one ASCII
    pinyin per character of `text` (characters g2pW has no reading for are
    echoed back, so the list aligns 1:1 and downstream logic ignores them
    via looks_like_pinyin), or (None, {}) when g2pW is unavailable or the
    output doesn't line up. Confidences are always {} -- g2pW computes them
    internally but its public API discards them.
    """
    converter = get_g2pw_converter()
    if converter is None:
        return None, {}
    try:
        results = converter([text])
    except Exception as exc:
        print(f"[polyphone] g2pW prediction failed: {exc}")
        return None, {}
    if (not results or not isinstance(results[0], list)
            or len(results[0]) != len(text)):
        print("[polyphone] g2pW output length mismatch")
        return None, {}
    pinyins = [normalize_pinyin(pred)
               if isinstance(pred, str) and looks_like_pinyin(pred)
               else ch
               for ch, pred in zip(text, results[0])]
    return pinyins, {}


def _forward_with_confidence(model, text):
    """Run g2pM's forward pass, returning (pinyins, confidences).

    G2pM.__call__ discards the softmax logits (argmax only), so this mirrors
    its input prep and predict() forward pass using the model's own public
    sub-methods to recover per-character prediction confidence.

    Args:
        model: a loaded G2pM instance.
        text: the raw input string.

    Returns:
        (pinyins, confidences): pinyins is the same per-character list
        G2pM.__call__(text, tone=True, char_split=True) would return (ASCII
        pinyin per char, non-Chinese echoed); confidences maps the 0-based
        character position of each polyphonic character to the model's
        softmax confidence (0..1) for its prediction. Non-polyphonic
        characters have no entry.
    """
    import numpy as np
    from g2pM.g2pM import UNK_TOKEN, BOS_TOKEN, EOS_TOKEN, SPLIT_TOKEN
    char2idx = model.char2idx
    cedict = model.cedict
    input_ids = []
    poly_indices = []
    pros = []
    for idx, ch in enumerate(text):
        input_ids.append(char2idx.get(ch, char2idx[UNK_TOKEN]))
        prons = cedict.get(ch)
        if prons and len(prons) > 1:
            poly_indices.append(idx)
            pros.append(SPLIT_TOKEN)
        elif prons:
            pros.append(prons[0])
        else:
            pros.append(ch)
    if not poly_indices:
        return pros, {}
    # +1 on the indices for the BOS insert, mirroring G2pM.__call__.
    input_ids = [char2idx[BOS_TOKEN]] + input_ids + [char2idx[EOS_TOKEN]]
    target_idx = [i + 1 for i in poly_indices]
    arr = np.array(input_ids, dtype=np.int32)[np.newaxis, :]
    lengths = np.sum(np.sign(arr), axis=1)
    max_length = int(np.max(lengths))
    fw_emb = model.get_embedding(arr)
    bw_emb = model.get_embedding(model.reverse_sequence(arr, lengths))
    fw_states = bw_states = None
    fw_hs, bw_hs = [], []
    for i in range(max_length):
        fw_states = model.fw_lstm_cell(fw_emb[:, i, :], fw_states)
        bw_states = model.bw_lstm_cell(bw_emb[:, i, :], bw_states)
        fw_hs.append(fw_states[0])
        bw_hs.append(bw_states[0])
    outputs = np.concatenate(
        [np.stack(fw_hs, axis=1),
         model.reverse_sequence(np.stack(bw_hs, axis=1), lengths)], axis=2)
    logits = model.fc_layer(outputs[0, target_idx])
    shifted = logits - logits.max(axis=1, keepdims=True)
    exp = np.exp(shifted)
    probs = exp / exp.sum(axis=1, keepdims=True)
    best = probs.argmax(axis=1)
    for k, pos in enumerate(poly_indices):
        pros[pos] = model.idx2class[best[k]]
    confidences = {pos: float(probs[k].max())
                   for k, pos in enumerate(poly_indices)}
    return pros, confidences


def predict_with_confidence(text, model=None):
    """Run the active disambiguation model over the full text.

    Args:
        text: the raw input string passed to AnnotationView.annotate.
        model: "g2pm", "g2pw", "g2pc" or "llm"; defaults to active_model().
            "llm" has no whole-text prediction -- it adjudicates each
            polyphonic character at resolve time (see
            api/llm_adjudicator.py), so this returns (None, {}) for it
            and the caller branches before calling.

    Returns:
        (pinyins, confidences): pinyins is a list with one ASCII pinyin
        (e.g. 'hong2') per character of `text` (1:1 alignment, non-Chinese
        echoed), or None when the model is disabled/unavailable or the
        output doesn't line up with the input; confidences maps 0-based
        character positions to the model's softmax confidence (0..1), {}
        when pinyins is None (g2pW never reports confidences).
    """
    if not text or not is_enabled():
        return None, {}
    name = model or active_model()
    if name == G2P_MODEL_LLM:
        return None, {}
    if name == G2P_MODEL_G2PW:
        return _predict_g2pw(text)
    if name == G2P_MODEL_G2PC:
        model_obj = get_g2pc_model()
    else:
        model_obj = get_model()
    if model_obj is None:
        return None, {}
    try:
        pinyins, confidences = _forward_with_confidence(model_obj, text)
    except Exception as exc:
        print(f"[polyphone] g2pM prediction failed, falling back: {exc}")
        return None, {}
    if not isinstance(pinyins, list) or len(pinyins) != len(text):
        print("[polyphone] g2pM output length mismatch, falling back to priority list")
        return None, {}
    return pinyins, confidences


def predict_char_pinyins(text):
    """Run g2pM over the full text.

    Backwards-compatible wrapper around predict_with_confidence returning
    just the per-character pinyin list (or None). Prefer
    predict_with_confidence for new code.
    """
    pinyins, _confidences = predict_with_confidence(text)
    return pinyins


def looks_like_pinyin(token):
    """Whether a g2pM output token looks like an ASCII pinyin reading."""
    return isinstance(token, str) and bool(_PINYIN_RE.match(token))


def _distinct_readings(entries):
    """Distinct known readings across entries, in priority order."""
    readings = []
    for entry in entries:
        for p in entry["pinyin"].split(" "):
            if p == "-" or p in readings:
                continue
            readings.append(p)
    return readings


def resolve_pinyin(char, dict_pinyin, char_entries, g2pm_pinyin, prev_char="",
                 next_char=""):
    """Resolve one character's pinyin and its provenance.

    Args:
        char: the Chinese character being annotated.
        dict_pinyin: the reading from the phrase's top-priority dictionary
            entry (ASCII, e.g. 'chang2').
        char_entries: EntryManager entries for the single character, used to
            validate the g2pM prediction against known readings; may be None.
        g2pm_pinyin: g2pM's contextual prediction for this character
            (e.g. 'zhang3'), or None.
        prev_char / next_char: the character's immediate neighbors within
            its phrase ("" at phrase edges), used to scope dismissals to
            their context.

    Returns:
        (pinyin, source): the ASCII pinyin to use and where it came from --
        SOURCE_DICT, SOURCE_G2PM or SOURCE_CONFLICT.
    """
    # In-memory entries carry toned pinyin; the whole comparison path
    # works in ASCII (models emit ASCII), so normalize on entry.
    dict_pinyin = normalize_pinyin(dict_pinyin)
    if not g2pm_pinyin or not looks_like_pinyin(g2pm_pinyin):
        return dict_pinyin, SOURCE_DICT
    if g2pm_pinyin.lower() == dict_pinyin.lower():
        # The model agrees with the dictionary; nothing to highlight.
        return dict_pinyin, SOURCE_DICT
    if (prev_char or next_char) and dict_pinyin.endswith("5"):
        # Neutral-tone grammatical particles (de5, le5, men5, zi5, ...) in
        # multi-character phrases: if the model only differs by assigning a
        # full tone to the same syllable, it's not a real polyphone ambiguity
        # -- the neutral tone is grammatical. Silently keep the dictionary
        # reading instead of flagging noise.
        dict_base = dict_pinyin[:-1].lower()
        model_base = g2pm_pinyin[:-1].lower()
        if dict_base == model_base and g2pm_pinyin[-1] in "1234":
            return dict_pinyin, SOURCE_DICT
    if is_dismissed(char, dict_pinyin, g2pm_pinyin, prev_char, next_char):
        # The user marked this suggestion wrong in this context; never flag
        # it again here (it can still flag in other contexts).
        return dict_pinyin, SOURCE_DICT
    candidates = distinct_readings(char_entries)
    if len(candidates) < 2:
        # Not actually polyphonic in our dictionary; nothing to disambiguate.
        return dict_pinyin, SOURCE_DICT
    wanted = g2pm_pinyin.lower()
    for candidate in candidates:
        if candidate.lower() == wanted:
            if advisory_mode():
                # Advisory mode: the model doesn't get to override; flag
                # the disagreement for dictionary curation instead.
                return dict_pinyin, SOURCE_CONFLICT
            return candidate, SOURCE_G2PM
    # g2pM disagreed with the dictionary but its reading isn't a known
    # candidate for this character, so keep the dictionary reading and flag
    # the conflict for dictionary curation.
    return dict_pinyin, SOURCE_CONFLICT


def select_pinyin(phrase, entries, g2pm_pinyin):
    """Choose the ASCII pinyin for a single-character phrase.

    Backwards-compatible wrapper around resolve_pinyin returning just the
    pinyin (drops the provenance). Prefer resolve_pinyin for new code.

    Args:
        phrase: single Chinese character the Trie segmented.
        entries: dictionary entries for the phrase, sorted by priority
            (lowest number = most preferred), each a dict with a 'pinyin'
            key in CEDict ASCII format (e.g. 'xing2').
        g2pm_pinyin: g2pM's contextual prediction for this character
            (e.g. 'hang2'), or None.

    Returns:
        The ASCII pinyin string to annotate the character with.
    """
    default = [p for p in entries[0]["pinyin"].split(" ") if p != "-"]
    default_pinyin = default[0] if default else entries[0]["pinyin"]
    pinyin, _source = resolve_pinyin(phrase, default_pinyin, entries, g2pm_pinyin)
    return pinyin
