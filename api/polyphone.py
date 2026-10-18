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

_model = None
_model_failed = False


def is_enabled():
    """Whether the g2pM disambiguation step should run.

    Controlled by the G2PM_ENABLED Django setting (default True), which itself
    can be set via the G2PM_ENABLED environment variable.
    """
    try:
        from django.conf import settings
        return bool(getattr(settings, "G2PM_ENABLED", True))
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


def _looks_like_pinyin(token):
    return isinstance(token, str) and bool(_PINYIN_RE.match(token))


def select_pinyin(phrase, entries, g2pm_pinyin):
    """Choose the ASCII pinyin for a single-character phrase.

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

    if not g2pm_pinyin or not _looks_like_pinyin(g2pm_pinyin):
        return default_pinyin

    # Collect the distinct known readings, in priority order.
    candidates = []
    for entry in entries:
        for p in entry["pinyin"].split(" "):
            if p == "-" or p in candidates:
                continue
            candidates.append(p)
    if len(candidates) < 2:
        # Not actually polyphonic in our dictionary; nothing to disambiguate.
        return default_pinyin

    wanted = g2pm_pinyin.lower()
    for candidate in candidates:
        if candidate.lower() == wanted:
            return candidate
    # g2pM predicted a reading our dictionary doesn't know; keep the default.
    return default_pinyin
