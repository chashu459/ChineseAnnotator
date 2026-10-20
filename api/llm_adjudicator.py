"""LLM-based polyphone (多音字) adjudication.

A third disambiguation model alongside g2pM and g2pW, selectable as
model="llm" on the dev-only /annotate/provenance endpoint (and recorded on
/annotate/curate). Where g2pM/g2pW predict a reading for every character,
the LLM only adjudicates: for a character the dictionary already lists 2+
readings for, it picks one of those candidates based on the surrounding
sentence. The dictionary constrains the answer, so the LLM never invents a
reading -- it just chooses from the short list, which is a much easier
problem than open-ended G2P and works well even with a small local model.

The adjudicator talks to an Ollama-compatible server
(http://localhost:11434 by default; override with the LLM_ADJUDICATOR_URL
environment variable / Django setting). Any chat model works; a small
instruct model such as qwen2.5:1.5b (LLM_ADJUDICATOR_MODEL) is plenty --
install Ollama, then `ollama pull qwen2.5:1.5b`. No new Python dependencies:
the client is stdlib urllib only.

Behavior notes:
- Only polyphonic characters (2+ dictionary candidates) trigger an LLM
  call, and results are cached per (char, candidates, sentence, neighbors),
  so re-annotating the same text is free.
- If the server is unreachable or the reply doesn't parse to one of the
  candidates, adjudicate() returns None and the caller keeps the dictionary
  reading -- annotation never breaks.
- Set LLM_ADJUDICATOR_DEBUG=1 to log every (character, candidates, raw
  reply, parsed choice) triple to stdout for accuracy debugging.
- Like the other models this runs in advisory mode by default: a
  disagreement is flagged as SOURCE_CONFLICT for dictionary curation rather
  than overriding the reading.
"""

import json
import re
import time
import urllib.request
import urllib.error

from api import polyphone

# Cap the adjudication cache; a novel re-annotated repeatedly would
# otherwise grow it without bound. Simple FIFO eviction.
_CACHE_MAX = 4096
_cache = {}
_cache_order = []

# Brief memoization of server reachability so the dev legend's 503 check
# doesn't pay a connection timeout on every provenance request.
_available = None
_available_at = 0.0
_AVAILABLE_TTL = 60.0


def _setting(name, default):
    try:
        from django.conf import settings
        return getattr(settings, name, default)
    except Exception:
        import os
        return os.environ.get(name, default)


def base_url():
    return str(_setting("LLM_ADJUDICATOR_URL",
                        "http://localhost:11434")).rstrip("/")


def model_name():
    return str(_setting("LLM_ADJUDICATOR_MODEL", "qwen2.5:1.5b"))


def timeout():
    try:
        return float(_setting("LLM_ADJUDICATOR_TIMEOUT", 30))
    except (TypeError, ValueError):
        return 30.0


def _debug():
    """Whether to log every prompt/reply/choice (LLM_ADJUDICATOR_DEBUG)."""
    val = _setting("LLM_ADJUDICATOR_DEBUG", False)
    if isinstance(val, str):
        return val.strip().lower() not in ("", "0", "false", "no", "off")
    return bool(val)


def clear_cache():
    """Forget cached adjudications and the reachability memo (for tests)."""
    global _available, _available_at
    _cache.clear()
    _cache_order.clear()
    _available = None
    _available_at = 0.0


def available():
    """Whether an Ollama-compatible server answers. Memoized for 60s."""
    global _available, _available_at
    now = time.monotonic()
    if _available is not None and now - _available_at < _AVAILABLE_TTL:
        return _available
    _available = _ping()
    _available_at = now
    return _available


def _ping():
    try:
        req = urllib.request.Request(base_url() + "/api/tags",
                                     method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def _cache_put(key, value):
    if key in _cache:
        return
    if len(_cache_order) >= _CACHE_MAX:
        oldest = _cache_order.pop(0)
        _cache.pop(oldest, None)
    _cache[key] = value
    _cache_order.append(key)


def _prompt(char, phrase, char_index, candidates, sentence):
    """Build the constrained-choice prompt.

    candidates are ASCII pinyin ('hang2'); show them toned ('háng') too so
    the model reads them naturally, and require a bare-pinyin answer.
    """
    shown = ", ".join(
        "%s (%s)" % (_toned(c), c) for c in candidates)
    return (
        "你是中文多音字注音助手。根据上下文，为目标汉字选择正确读音。\n"
        "句子：%s\n"
        "词语“%s”中的第 %d 个字是“%s”，它是多音字。\n"
        "候选读音：%s\n"
        "要求：只回答其中一个候选读音（带声调的拼音形式），不要解释，不要输出其他任何内容。"
        % (sentence, phrase, char_index + 1, char, shown)
    )


def _toned(ascii_pinyin):
    """Best-effort ASCII ('hang2') -> toned ('háng') for prompt display."""
    try:
        from api.utils import parsePinyin
        return parsePinyin(ascii_pinyin)
    except Exception:
        return ascii_pinyin


def _chat(prompt):
    """One non-streaming Ollama /api/chat call. Returns the reply text."""
    payload = json.dumps({
        "model": model_name(),
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0},
    }).encode("utf-8")
    req = urllib.request.Request(
        base_url() + "/api/chat", data=payload, method="POST",
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout()) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    message = (body.get("message") or {}).get("content", "")
    return message.strip() if isinstance(message, str) else ""


_PUNCT = re.compile(r"^[\s\"'“”‘’（）()\[\]【】:：,，。.!！?？;；]+|"
                    r"[\s\"'“”‘’（）()\[\]【】:：,，。.!！?？;；]+$")


def _match_candidate(reply, candidates):
    """Map a free-form model reply onto one of the ASCII candidates.

    Tries, in order: exact ASCII match after toned->ASCII normalization;
    a candidate appearing verbatim in the reply; a unique toneless-base
    match (the model sometimes drops the tone despite instructions).
    Returns the ASCII candidate or None.
    """
    cleaned = _PUNCT.sub("", reply.strip())
    if not cleaned:
        return None
    lowered = {c.lower(): c for c in candidates}
    # 1. Normalized exact match ('háng' -> 'hang2').
    normalized = polyphone.unparse_pinyin(cleaned)
    if isinstance(normalized, str) and normalized.lower() in lowered:
        return lowered[normalized.lower()]
    # 2. Exactly one candidate mentioned verbatim in the reply. A reply
    #    that names several readings ("不是 háng，而是 xíng") must not
    #    resolve to whichever candidate happens to be listed first --
    #    treat it as unparseable instead of guessing wrong.
    mentioned = [c for c in candidates
                 if c.lower() in reply.lower() or _toned(c) in reply]
    if len(mentioned) == 1:
        return mentioned[0]
    if len(mentioned) > 1:
        return None
    # 3. Unique toneless-base match.
    base = re.sub(r"[1-5]$", "", normalized.lower()) \
        if isinstance(normalized, str) else ""
    if base:
        hits = [c for c in candidates
                if re.sub(r"[1-5]$", "", c.lower()) == base]
        if len(hits) == 1:
            return hits[0]
    return None


def adjudicate(char, candidates, sentence, phrase="", char_index=0,
               prev_char="", next_char=""):
    """Ask the LLM to pick one reading for a polyphonic character.

    Args:
        char: the Chinese character.
        candidates: its known ASCII readings (e.g. ['hang2', 'xing2']).
        sentence: surrounding sentence for context.
        phrase / char_index: the word the char appears in (prompt context).
        prev_char / next_char: neighbors within the phrase (cache key only).

    Returns:
        The chosen ASCII pinyin, or None when the server is unreachable,
        the call fails, or the reply doesn't map to a candidate. Never
        raises.
    """
    if not candidates or len(char.strip()) != 1:
        return None
    key = (char, tuple(candidates), sentence, phrase, char_index,
           prev_char, next_char)
    # Membership check (not .get): None is a valid cached value (the model
    # failed or its reply didn't parse -- don't retry it every time).
    if key in _cache:
        return _cache[key]
    reply = None
    try:
        reply = _chat(_prompt(char, phrase or char, char_index,
                              candidates, sentence))
        choice = _match_candidate(reply, candidates)
    except Exception as exc:
        print("[llm_adjudicator] adjudication failed: %s" % exc)
        choice = None
    if _debug():
        print("[llm_adjudicator] char=%s candidates=%s reply=%r choice=%s"
              % (char, candidates, reply, choice))
    _cache_put(key, choice)
    return choice
