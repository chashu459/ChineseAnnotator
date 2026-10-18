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


# --- dismissed suggestions -------------------------------------------------
# "Mark as wrong" records (character, dictionary reading, g2pM suggestion)
# triples in data/g2pm_dismissed.json. A dismissed triple never flags a
# conflict again: the key captures "where the dictionary reads this char as
# X, don't bother me when the model says Y".

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
                                row["suggested_pinyin"]))
    except Exception:
        pass
    return _dismissed


def clear_dismissed_cache():
    """Forget the cached dismissal set so the next lookup re-reads the file."""
    global _dismissed
    _dismissed = None


def is_dismissed(char, dict_pinyin, suggested_pinyin):
    """Whether this (char, dict reading -> model suggestion) was marked wrong."""
    return (char, unparse_pinyin(dict_pinyin), unparse_pinyin(suggested_pinyin)) \
        in _load_dismissed()


def is_enabled():
    """Whether the g2pM disambiguation step should run.

    Controlled by the G2PM_ENABLED Django setting (default True), which itself
    can be set via the G2PM_ENABLED environment variable.
    """
    try:
        from django.conf import settings
        return bool(getattr(settings, "G2PM_ENABLED", True))
    except Exception:
        # Standalone (no Django settings configured): stay enabled so the
        # pure logic remains testable.
        return True


def model_available():
    """Whether the g2pM model is installed and loadable.

    Unlike predict_char_pinyins (which silently falls back to None), this is
    for callers that want to fail loudly, e.g. the dev-only provenance
    endpoint. The load result is cached, so repeated calls are cheap.
    """
    if not is_enabled():
        return False
    return _get_model() is not None


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


def predict_char_pinyins(text):
    """Run g2pM over the full text.

    Args:
        text: the raw input string passed to AnnotationView.annotate.

    Returns:
        A list with one ASCII pinyin (e.g. 'hong2') per character of `text`
        (char_split=True guarantees 1:1 alignment), or None when g2pM is
        disabled/unavailable or the output doesn't line up with the input.
        Non-Chinese characters are echoed back as-is in their slots.
    """
    if not text or not is_enabled():
        return None
    model = get_model()
    if model is None:
        return None
    try:
        pinyins = model(text, tone=True, char_split=True)
    except Exception as exc:
        print(f"[polyphone] g2pM prediction failed, falling back: {exc}")
        return None
    if not isinstance(pinyins, list) or len(pinyins) != len(text):
        print("[polyphone] g2pM output length mismatch, falling back to priority list")
        return None
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


def resolve_pinyin(char, dict_pinyin, char_entries, g2pm_pinyin):
    """Resolve one character's pinyin and its provenance.

    Args:
        char: the Chinese character being annotated.
        dict_pinyin: the reading from the phrase's top-priority dictionary
            entry (ASCII, e.g. 'chang2').
        char_entries: EntryManager entries for the single character, used to
            validate the g2pM prediction against known readings; may be None.
        g2pm_pinyin: g2pM's contextual prediction for this character
            (e.g. 'zhang3'), or None.

    Returns:
        (pinyin, source): the ASCII pinyin to use and where it came from --
        SOURCE_DICT, SOURCE_G2PM or SOURCE_CONFLICT.
    """
    if not g2pm_pinyin or not looks_like_pinyin(g2pm_pinyin):
        return dict_pinyin, SOURCE_DICT
    if g2pm_pinyin.lower() == dict_pinyin.lower():
        # The model agrees with the dictionary; nothing to highlight.
        return dict_pinyin, SOURCE_DICT
    if is_dismissed(char, dict_pinyin, g2pm_pinyin):
        # The user marked this suggestion wrong; never flag it again.
        return dict_pinyin, SOURCE_DICT
    candidates = _distinct_readings(char_entries) if char_entries else []
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
