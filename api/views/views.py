import json
import os
import re
from collections import namedtuple
from datetime import datetime, timezone
from pprint import pprint
import timeit

from django.conf import settings
from django.core.cache.backends.base import DEFAULT_TIMEOUT

from django.db.models import Q, query
from django.db.models.manager import BaseManager
from django.http import HttpResponse
from django.shortcuts import render
from rest_framework import filters, generics, serializers, status
from rest_framework.exceptions import bad_request
from rest_framework.response import Response
from rest_framework.views import APIView
from api.EntryManager import EntryManager


from api.models import (BlacklistEntry, ChineseEntry, Entry, EditEntry, Fragment, Memory,
                        PhraseEntry)
from api.serializers import (AnnotationSerializer, BlacklistEntrySerializer,
                             ChineseEntrySerializer, CleanMemorySerializer, CreateEntrySerializer,
                             EntrySerializer, FragmentSerializer,
                             MemoryCreateSerializer, MemorySerializer,
                             PhraseEntrySerializer, ReloadEntrySerializer,
                             UpdateEntrySerializer,EditEntrySerializer)
from api.Trie import (Trie, TradTrie)
from api import polyphone
from api.utils import (BLACKLIST, CUSTOM, DICT, PRIORITY, DEFAULT_OWNER, DEFAULT_PRIORITY, MAIN_PRIORITY, MAX_PRIORITY, NBSP, SESSIONS,
                       OwnerOrDefault, USER_PRIORITY, isChinese, parsePinyin,
                       reloadCEDict, openChapterText, listNovels,
                       setupPriorityEntries, setupCustomEntries)

# CACHE_TTL = getattr(settings, 'CACHE_TTL', DEFAULT_TIMEOUT)

# import redis
import json
from django.conf import settings
# import redis
from rest_framework.decorators import api_view
from rest_framework import status
from rest_framework.response import Response
from django.core.cache import cache

# cache = redis.StrictRedis(host=settings.REDIS_HOST,
#                                   port=settings.REDIS_PORT, db=0)

# @api_view(['POST'])
# def manage_item(request, *args, **kwargs):
#     # if request.method == 'GET':
#     data = request.data
#     if data['key']:
#         value = cache.get(data['key'])
#         if value:
#             response = {
#                 'key': data['key'],
#                 'value': value,
#                 'msg': 'success'
#             }
#             return Response(response, status=200)
#         else:
#             response = {
#                 'key': data['key'],
#                 'value': None,
#                 'msg': 'Not found'
#             }
#             return Response(response, status=404)
#     # return Response(response, status=405)


class BlacklistEntryView(generics.ListCreateAPIView):
    queryset = BlacklistEntry.objects.all()
    serializer_class = BlacklistEntrySerializer


# class EntryView(generics.ListAPIView):
#     # class DynamicSearchFilter(filters.SearchFilter):
#     #     def get_search_fields(self, view, request):
#     #         return request.GET.getlist('search_fields', ['simplified', 'traditional', 'english'])

#     # search_fields = ['simplified', 'traditional']
#     # filter_backends = (filters.SearchFilter, )
#     # filter_backends = (DynamicSearchFilter, )
#     serializer_class = EntrySerializer

@api_view(['GET'])
def getEntry(request):
    if not request.session.exists(request.session.session_key):
        request.session.create()

    phrase = request.query_params.get('phrase')
    if phrase is None:
        return Response({'Bad Request': 'Invalid data...'}, status=status.HTTP_400_BAD_REQUEST)

    # TODO: DNE check
    # memory = Memory.objects.get(code=code)
    # data = {
    #     "code": code,
    #     "fragment": FragmentSerializer(Memory.objects.get(code=code).fragments.all(), many=True).data
    # }

    #TODO: use trad to simp map.
    entries = EntryManager.get(phrase)

    # if entries is None:
        # entries = TradEntryManager.get(phrase)
        # pass
    
    
    if entries is None:    
        return Response({'Not Found': f'phrase {phrase} not found'}, status=status.HTTP_404_NOT_FOUND)

    responseData = [EntrySerializer(entry).data for entry in entries if entry['priority'] < MAX_PRIORITY]
    return Response(responseData, status=status.HTTP_200_OK)

# @api_view(['GET'])
# def getTradEntry(request):
#     if not request.session.exists(request.session.session_key):
#         request.session.create()

#     phrase = request.query_params.get('phrase')
#     if phrase is None:
#         return Response({'Bad Request': 'Invalid data...'}, status=status.HTTP_400_BAD_REQUEST)

#     # TODO: DNE check
#     # memory = Memory.objects.get(code=code)
#     # data = {
#     #     "code": code,
#     #     "fragment": FragmentSerializer(Memory.objects.get(code=code).fragments.all(), many=True).data
#     # }

#     entries = TradEntryManager.get(phrase)

    # if entries is None:
    #     return Response({'Not Found': f'phrase {phrase} not found'}, status=status.HTTP_404_NOT_FOUND)

    # responseData = [EntrySerializer(entry).data for entry in entries if entry['priority'] < MAX_PRIORITY]
    # return Response(responseData, status=status.HTTP_200_OK)

    # def get_queryset(self):
    #     """
    #     Restricts the entries fetched by the user
    #     by filtering against a `phrase` query parameter in the URL.

    #     Ex. http://127.0.0.1:8000/api/home?phrase=您

    #     If no phrase is specified, then an empty list is returned.
    #     """
    #     queryset = Entry.objects.all()
    #     phrase = self.request.query_params.get('phrase')
    #     # individualChars = self.request.query_params.get('individualChars')
    #     if phrase is not None:
    #         queryset = queryset.filter(
    #             Q(simplified=phrase) | Q(traditional=phrase)).order_by("priority")
    #         # if individualChars is not None:
    #         #     # queryset = None
    #         #     unionset = None
    #         #     item = queryset.first()
    #         #     for cchar in phrase:
    #         #         subset = queryset.filter(
    #         #             Q(simplified=cchar) | Q(traditional=cchar)).order_by("priority")
    #         #     unionset = subset if unionset is None else unionset.union(subset)
    #         #     return unionset

    #         return queryset
    #     if self.request.query_params.get('search') is not None:
    #         return queryset

    #     return Entry.objects.filter(id=0)


@api_view(['GET'])
def getNovel(request):
    if not request.session.exists(request.session.session_key):
        request.session.create()

    novelName = request.query_params.get('novelName')
    chapter = request.query_params.get('chapter')
    if novelName is None:
        return Response({'Bad Request': 'Invalid data...'}, status=status.HTTP_400_BAD_REQUEST)
    if chapter is None:
        return Response({'Bad Request': 'Invalid data...'}, status=status.HTTP_400_BAD_REQUEST)

    request.session["latest_novel_name"] = novelName
    request.session["latest_chapter"] = chapter

    # TODO: DNE check
    text = openChapterText(novelName, chapter)

    responseData = { "text": text }
    return Response(responseData, status=status.HTTP_200_OK)

@api_view(['GET'])
def getNovelsAndChapters(request):
    if not request.session.exists(request.session.session_key):
        request.session.create()

    # TODO: DNE check
    
    # TODO: march 22, 2024: surface the summary stored in the dictionary.
    novels = listNovels()
    # responseData = json.dumps(novels)
    # print(responseData)
    return Response(novels, status=status.HTTP_200_OK)

    # def get_queryset(self):
    #     """
    #     Restricts the entries fetched by the user
    #     by filtering against a `phrase` query parameter in the URL.

    #     Ex. http://127.0.0.1:8000/api/home?phrase=您

    #     If no phrase is specified, then an empty list is returned.
    #     """
    #     queryset = Entry.objects.all()
    #     phrase = self.request.query_params.get('phrase')
    #     # individualChars = self.request.query_params.get('individualChars')
    #     if phrase is not None:
    #         queryset = queryset.filter(
    #             Q(simplified=phrase) | Q(traditional=phrase)).order_by("priority")
    #         # if individualChars is not None:
    #         #     # queryset = None
    #         #     unionset = None
    #         #     item = queryset.first()
    #         #     for cchar in phrase:
    #         #         subset = queryset.filter(
    #         #             Q(simplified=cchar) | Q(traditional=cchar)).order_by("priority")
    #         #     unionset = subset if unionset is None else unionset.union(subset)
    #         #     return unionset

    #         return queryset
    #     if self.request.query_params.get('search') is not None:
    #         return queryset

    #     return Entry.objects.filter(id=0)


class AnnotationView(APIView):
    queryset = Entry.objects.all()
    serializer_class = AnnotationSerializer

    def split(self, lines, separator):
        lst = list()
        for line in lines:
            verses = line.split(separator)
            for i in range(len(verses) - 1):
                verses[i] += separator

            lst.extend(verses)

        return lst

    def _resolve_phrase_pinyins(self, phrase, entries, poly_pinyins, pos, trad,
                              confidences=None):
        """Resolve per-character pinyin and provenance for a phrase.

        Starts from the top-priority entry's readings, then lets g2pM's
        contextual predictions override individual characters -- for
        single-character phrases and for phrase-internal ambiguities like
        长长 (e.g. 头发长长了 -> zhang3 chang2)
        alike -- constrained to known dictionary readings (see
        api/polyphone.py). Returns a list of (pinyin, source, suggested,
        confidence) tuples, one per character: the ASCII pinyin to use, its
        provenance ('dict' | 'g2pm' | 'conflict'), g2pM's proposed reading
        when the source is 'conflict' (None otherwise), and the model's
        softmax confidence (0..1) for its prediction when one was made
        (None otherwise).
        """
        confidences = confidences or {}
        default_pinyins = [p for p in entries[0]['pinyin'].split(" ") if p != "-"]
        resolved_chars = []
        for i, ch in enumerate(phrase):
            if i >= len(default_pinyins):
                break
            dict_pinyin = default_pinyins[i]
            g2pm_pinyin = None
            if (poly_pinyins is not None and isChinese(ch)
                    and pos + i < len(poly_pinyins)):
                candidate = poly_pinyins[pos + i]
                if (polyphone.looks_like_pinyin(candidate)
                        and candidate.lower() != dict_pinyin.lower()):
                    g2pm_pinyin = candidate
            if g2pm_pinyin is None:
                resolved_chars.append(
                    (dict_pinyin, polyphone.SOURCE_DICT, None, None))
                continue
            # The model disagrees with the dictionary on this character;
            # only let it win when its reading is a known reading of the
            # character on its own.
            char_entries = EntryManager.get(ch, trad=trad)
            # Dismissals are scoped to the character's immediate neighbors
            # within the phrase, so marking a suggestion wrong in one word
            # doesn't suppress it in others.
            prev_char = phrase[i - 1] if i > 0 else ""
            next_char = phrase[i + 1] if i < len(phrase) - 1 else ""
            resolved, source = polyphone.resolve_pinyin(
                ch, dict_pinyin, char_entries, g2pm_pinyin,
                prev_char=prev_char, next_char=next_char)
            suggested = g2pm_pinyin if source == polyphone.SOURCE_CONFLICT else None
            confidence = confidences.get(pos + i)
            resolved_chars.append((resolved, source, suggested, confidence))
        return resolved_chars

    def annotate(self, owner: str, text: str, with_provenance=False, model=None):
        """Annotate text with pinyin.

        with_provenance: run the disambiguation model to compute
            per-character pinyin provenance ('dict' | 'g2pm' | 'conflict').
            In advisory mode (the default) the model never changes a reading,
            so the fast path (with_provenance=False) skips it entirely; the
            frontend calls /annotate/provenance in the background for
            dev-mode highlighting.
        model: "g2pm" or "g2pw"; defaults to polyphone.active_model().
        """
        print("===============================")
        print(text)
        # TODO: return only simplified?
        # TODO: march 14, 2024 - Currently there's no support for 'phrases' with latin alphabet: etc: X光
        owner = "default"
        trie = Trie.getTrie(owner)
        tradTrie = TradTrie.getTrie(owner)
        if not trie.contains('你'):
            test = EntryManager.get("你")
            if not test:
                EntryManager.reload()

            Trie.loadTrie(owner)

        # print(trie)
        
        if not tradTrie.contains('妳'):
            # test = TradEntryManager.get("妳")
            # if not test:
            #     TradEntryManager.reload()

            TradTrie.loadTrie(owner)

        # print(tradTrie)

        fragments = [text]
        separators = "。：？!,、“”，）（ )(!?:.,\"\'\n"
        for separator in separators:
            fragments = self.split(fragments, separator)

        print(fragments)
        
        # g2pM polyphone (多音字) disambiguation: one contextual pinyin
        # prediction per character of the original text. char_split=True
        # guarantees the predictions align 1:1 with text. See api/polyphone.py.
        # In advisory mode the model never overrides a reading, so the fast
        # path skips it entirely (all sources stay 'dict'); the provenance
        # endpoint runs it in the background for dev-mode highlighting.
        run_g2pm = with_provenance or not polyphone.advisory_mode()
        poly_pinyins = None
        poly_confidences = {}
        if run_g2pm:
            poly_pinyins, poly_confidences = polyphone.predict_with_confidence(
                text, model=model)

        # fragments concatenate back to text in order; record each
        # fragment's start offset so single-character phrases can look up
        # their g2pM prediction by absolute character index.
        frag_start = 0
        frag_starts = []
        for fragment in fragments:
            frag_starts.append(frag_start)
            frag_start += len(fragment)

        lst = list()
        for frag_index, fragment in enumerate(fragments):
            pos = frag_starts[frag_index]
            remaining = fragment
            # print(remaining)
            while remaining:
                firstCChar = 0
                # print("remaininglength: " + str(len(remaining)))
                # print(f"remaininglength: {firstCChar < len(remaining)}")
                # print(f"remaininglength: {firstCChar}<{len(remaining)}")
                while firstCChar < len(remaining) and not isChinese(remaining[firstCChar]):
                    firstCChar += 1
                # print("++++++++++++++++++++++++")
                # print("remainingStart: " + remaining)
                # print("index of first chinese: " + str(firstCChar))

                if firstCChar != 0:
                    # print("adding:" + remaining[:firstCChar])
                    lst.append(
                        ChineseEntry(NBSP, remaining[:firstCChar])
                    )

                    # remove non chinese cahrs
                    remaining = remaining[firstCChar:]
                    pos += firstCChar
                    # print("remainingAfterRemoval: '" + remaining + "'")
                else:
                    # findBest is simply greedy algo, find the longest
                    phrase = trie.findBest(remaining)
                    tradPhrase = tradTrie.findBest(remaining)
                    trad = False
                    if(len(tradPhrase) > len(phrase)):
                        trad = True
                        phrase = tradPhrase
                        # print("phrase: '" + phrase + "'")
                    if not phrase:
                        remaining = remaining[1:]
                        pos += 1
                        # Unknown, so put dummy entry.
                        phraselst = [ChineseEntry("zzz", "@")]
                        lst.append(PhraseEntry(phraselst))
                    else:
                        # found something in trie, remove phrase from remaining
                        remaining = remaining[len(phrase):]

                        # TODO: fetch pinyin
                        # entry = ownerQueryset.filter(
                        #     Q(simplified=phrase)
                        #     | Q(traditional=phrase), Q(priority__lte=MAX_PRIORITY)).order_by("priority").values_list("pinyin", "english").first()    
                        # print(trad)
                        # print(phrase)
                        entries = EntryManager.get(phrase, trad=trad)
                        # print(entries)
                        if(entries):
                            resolved_chars = self._resolve_phrase_pinyins(
                                phrase, entries, poly_pinyins, pos, trad,
                                confidences=poly_confidences)
                            # print("entry: '" +  + "'")
                            # pprint(entry)

                            # print(pinyins.query)

                            # Note: entry here is a tuple, (pinyin, english)
                            # pinyin = entry[0].split(" ")
                            # english = entry[1]

                            # english = entry['english']

                            # print(pinyin)
                            # pinyin = dict.getPinYin(self.phrase).split(" ")
                            if len(phrase) != len(resolved_chars):
                                print(
                                    "pinyin and phrase have different lengths O.o")
                                print(f"phrase: {phrase}")
                                print(f"pinyin: {[c[0] for c in resolved_chars]}")
                                raise "pinyin and phrase have different lengths O.o"

                            # push all phrases
                            phraselst = []
                            for i in range(len(phrase)):
                                pinyin, source, suggested, confidence = \
                                    resolved_chars[i]
                                phraselst.append(
                                    ChineseEntry(
                                        parsePinyin(pinyin), phrase[i],
                                        source=source,
                                        suggested_pinyin=(parsePinyin(suggested)
                                                          if suggested else None),
                                        confidence=confidence,
                                    )
                                )
                            lst.append(PhraseEntry(phraselst))
                        else:
                            #Note: If this appears, it means Trie and EntryManagers are out of sync. Probablyj ust need to reloadCEDict
                            print(f"ERROR: Unable to find entry {phrase}")
                        pos += len(phrase)
        return lst

    def post(self, request, format=None):
        if not self.request.session.exists(self.request.session.session_key):
            self.request.session.create()

        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            text = serializer.data.get('text')
            # owner = DEFAULT_OWNER
            # if SESSIONS:
            owner = self.request.session.session_key

            # Fetch owner's dictionary
            # ownerQueryset = Entry.objects.filter(
            #     OwnerOrDefault(owner))
            # if not ownerQueryset.exists():
            #     return Response({'Bad Request': 'Dictionary is unavailable at the moment. Please contact an administrator'}, status=status.HTTP_400_BAD_REQUEST)

            # chineseEntries = {
            #     "annotations":
            # }
            # print(chineseEntries)
            data = self.annotate(owner, text)
            # pprint(data)

            # pprint(data)
            # [print(namedtuple("PhraseEntry", phrase.keys())(*phrase.values()).english) if isinstance(
            #     phrase, PhraseEntry) else ChineseEntrySerializer(phrase).data for phrase in data]
            responseData = [PhraseEntrySerializer(phrase).data if isinstance(phrase, PhraseEntry)
                            else ChineseEntrySerializer(phrase).data for phrase in data]
            # responseData = [[ChineseEntrySerializer(entry).data] if isinstance(entry,ChineseEntry) else [PhraseEntrySerializer(phrase).data for phrase in entry] for entry in data]

            return Response(responseData, status=status.HTTP_200_OK)

        return Response({'Bad Request': 'Invalid data...'}, status=status.HTTP_400_BAD_REQUEST)



class ProvenanceView(APIView):
    """Dev-only background pass: re-annotate text with model provenance.

    The main /annotate endpoint skips the model for speed (in advisory mode
    the model never changes a reading anyway). The frontend calls this
    endpoint in the background when ?dev=1 is set and swaps the result in to
    highlight model/dictionary disagreements.

    POST {text, model?}: model is "g2pm" (default) or "g2pw" for A/B
    testing the disambiguation models against each other.
    """
    def post(self, request, format=None):
        data = request.data if isinstance(request.data, dict) else {}
        text = data.get('text', '')
        if not isinstance(text, str) or not text.strip():
            return Response([], status=status.HTTP_200_OK)
        model = data.get('model') or polyphone.active_model()
        if model not in polyphone.G2P_MODELS:
            return Response({"detail": "model must be 'g2pm' or 'g2pw'"},
                            status=status.HTTP_400_BAD_REQUEST)
        # Fail loudly (dev-only endpoint): silently returning all-dict would
        # make missing-model deployments indistinguishable from "no conflicts".
        # g2pW provisions in the background; report that distinctly so the
        # frontend can show progress instead of an error.
        if not polyphone.model_available(model):
            if (model == polyphone.G2P_MODEL_G2PW
                    and polyphone.g2pw_status() == polyphone.G2PW_PROVISIONING):
                return Response({"detail": "g2pW model still provisioning",
                                 "status": polyphone.G2PW_PROVISIONING},
                                status=status.HTTP_503_SERVICE_UNAVAILABLE)
            return Response({"detail": f"{model} model unavailable"},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        data = AnnotationView().annotate("default", text, with_provenance=True,
                                         model=model)
        responseData = [PhraseEntrySerializer(phrase).data if isinstance(phrase, PhraseEntry)
                        else ChineseEntrySerializer(phrase).data for phrase in data]
        return Response(responseData, status=status.HTTP_200_OK)


def _read_json_list(path):
    """Read a JSON list file; return [] when it does not exist yet."""
    try:
        with open(path) as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except FileNotFoundError:
        return []


def _data_path(filename):
    return os.path.join(str(settings.BASE_DIR / "data"), filename)


def _log_training_example(context, context_index, char, pinyin, label, model):
    """Append a labeled example for g2pM fine-tuning to data/g2pm_training.jsonl.

    context: the paragraph text the model saw; context_index: the judged
    character's offset within it; pinyin: the correct reading (ASCII, e.g.
    'de5'); label: 'accept' (user confirmed the suggestion) or 'dismiss'
    (user rejected it, keeping the dictionary reading); model: 'g2pm'/'g2pw'.

    Logging must never break curation: invalid input is skipped silently and
    unexpected errors are printed, not raised.
    """
    try:
        if not isinstance(context, str) or not context:
            return
        try:
            idx = int(context_index)
        except (TypeError, ValueError):
            return
        if not (0 <= idx < len(context)):
            return
        if not isinstance(char, str) or len(char) != 1:
            return
        if context[idx] != char:
            # Misaligned -- do not record a wrong example.
            return
        pinyin = polyphone.unparse_pinyin(pinyin)
        if not polyphone.looks_like_pinyin(pinyin):
            return
        if label not in ("accept", "dismiss"):
            return
        path = _data_path("g2pm_training.jsonl")
        row = {
            "text": context,
            "index": idx,
            "char": char,
            "pinyin": pinyin,
            "label": label,
            "model": model,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as exc:
        print(f"[training] log failed: {exc}")


class CuratePriorityView(APIView):
    """One-tap curation: make g2pM's suggested reading win for a phrase.

    POST {phrase, char_index, suggested_pinyin}: takes the phrase's current
    top-priority entry, swaps the reading at char_index for the suggestion,
    and persists it so the suggestion becomes the displayed reading:
    - if a dictionary entry with the corrected pinyin already exists, a
      priority.json entry boosts that entry (carrying its own traditional
      form and definition, not the top entry's) to USER_PRIORITY;
    - otherwise a custom.json entry adds the new reading (CUSTOM_PRIORITY),
      with the english copied from the top entry as a fallback.
    The datamap is rebuilt and EntryManager reloaded, so the change is live
    immediately. suggested_pinyin may be toned ('háng') or ASCII ('hang2').
    """
    def post(self, request, format=None):
        data = request.data if isinstance(request.data, dict) else {}
        phrase = data.get("phrase", "")
        suggested = polyphone.unparse_pinyin(data.get("suggested_pinyin", ""))
        try:
            char_index = int(data.get("char_index", 0))
        except (TypeError, ValueError):
            return Response({"detail": "char_index must be an integer"},
                            status=status.HTTP_400_BAD_REQUEST)

        if not isinstance(phrase, str) or not phrase.strip():
            return Response({"detail": "phrase is required"},
                            status=status.HTTP_400_BAD_REQUEST)
        if not 0 <= char_index < len(phrase):
            return Response({"detail": "char_index out of range"},
                            status=status.HTTP_400_BAD_REQUEST)
        if not polyphone.looks_like_pinyin(suggested):
            return Response({"detail": "suggested_pinyin is not valid pinyin"},
                            status=status.HTTP_400_BAD_REQUEST)
        model = data.get("model") or polyphone.active_model()
        if model not in polyphone.G2P_MODELS:
            return Response({"detail": "model must be 'g2pm' or 'g2pw'"},
                            status=status.HTTP_400_BAD_REQUEST)
        model_label = "g2pW" if model == polyphone.G2P_MODEL_G2PW else "g2pM"

        entries = EntryManager.get(phrase)
        if not entries:
            return Response({"detail": "phrase not in dictionary"},
                            status=status.HTTP_404_NOT_FOUND)
        top = entries[0]
        parts = [p for p in top["pinyin"].split(" ") if p]
        if char_index >= len(parts):
            return Response({"detail": "pinyin/character length mismatch"},
                            status=status.HTTP_400_BAD_REQUEST)
        parts[char_index] = suggested
        corrected = " ".join(parts)

        match = next((e for e in entries if e.get("pinyin") == corrected),
                     None)
        if match is not None:
            # The reading already exists in the dictionary: boost the entry
            # that actually carries it -- with its own traditional form and
            # definition -- rather than the top entry's.
            path = _data_path("priority.json")
            rows = _read_json_list(path)
            want = {
                "traditional": match["traditional"],
                "simplified": match["simplified"],
                "pinyin": corrected,
                "english": match.get("english", ""),
            }
            row = next((r for r in rows
                        if r.get("simplified") == want["simplified"]
                        and r.get("pinyin") == want["pinyin"]), None)
            if row is None:
                row = dict(want, reason=f"{model_label} curation")
                rows.append(row)
                changed = True
            else:
                # A row for this reading already exists: refresh any stale
                # fields (rows written before the definition/traditional fix
                # carry the top entry's values). A hand-written reason is
                # left alone.
                changed = False
                for key, value in want.items():
                    if row.get(key) != value:
                        row[key] = value
                        changed = True
            if changed:
                with open(path, "w") as f:
                    json.dump(rows, f, ensure_ascii=False, indent=2)
                setupPriorityEntries()
                EntryManager.reloadPriorities()
            _log_training_example(data.get("context"), data.get("context_index"),
                                  phrase[char_index], suggested,
                                  "accept", model)
            return Response({"ok": True, "via": "priority",
                             "pinyin": corrected, "already": not changed},
                            status=status.HTTP_200_OK)

        # New reading; add it via custom.json.
        path = _data_path("custom.json")
        rows = _read_json_list(path)
        done = any(r.get("simplified") == top["simplified"]
                   and r.get("pinyin") == corrected for r in rows)
        if not done:
            rows.append({
                "traditional": top["traditional"],
                "simplified": top["simplified"],
                "pinyin": corrected,
                "english": top.get("english", ""),
            })
            with open(path, "w") as f:
                json.dump(rows, f, ensure_ascii=False, indent=2)
            setupCustomEntries()
            EntryManager.reloadCustoms()
        _log_training_example(data.get("context"), data.get("context_index"),
                              phrase[char_index], suggested,
                              "accept", model)
        return Response({"ok": True, "via": "custom",
                         "pinyin": corrected, "already": done},
                        status=status.HTTP_200_OK)


class AddCustomPhraseView(APIView):
    """Add a custom phrase: writes to data/custom.json (live in annotation)
    and logs an EditEntry record (type='custom') for review, as the "Add
    custom phrase" modal previously did via /entry/edit alone.

    POST {simplified, traditional?, pinyin, english?, notes?}: appends a
    custom.json row (deduped on simplified+pinyin), rebuilds the custom
    datamap and reloads it so the phrase annotates immediately. Pinyin is
    space-separated readings, e.g. "ni3 hao3"; toned Unicode ("nǐ hǎo")
    and ü spellings ("nü3"/"nv3") are normalized to numbered ASCII
    ("ni3 hao3", "nu:3") on save.
    """

    def post(self, request, format=None):
        data = request.data if isinstance(request.data, dict) else {}
        simplified = (data.get("simplified") or "").strip()
        traditional = (data.get("traditional") or "").strip() or simplified
        pinyin = " ".join(
            polyphone.normalize_pinyin(p)
            for p in (data.get("pinyin") or "").strip().split()
        )
        english = (data.get("english") or "").strip()
        notes = (data.get("notes") or "").strip()

        if not simplified:
            return Response({"detail": "simplified is required"},
                            status=status.HTTP_400_BAD_REQUEST)
        parts = [p for p in pinyin.split(" ") if p]
        if not parts or not all(polyphone.looks_like_pinyin(p) for p in parts):
            return Response({"detail": "pinyin is not valid"},
                            status=status.HTTP_400_BAD_REQUEST)

        # 1. custom.json -- this is what makes the phrase live in annotation.
        path = _data_path("custom.json")
        rows = _read_json_list(path)
        done = any(r.get("simplified") == simplified
                   and r.get("pinyin") == pinyin for r in rows)
        if not done:
            rows.append({
                "traditional": traditional,
                "simplified": simplified,
                "pinyin": pinyin,
                "english": english,
            })
            with open(path, "w") as f:
                json.dump(rows, f, ensure_ascii=False, indent=2)
            setupCustomEntries()
            EntryManager.reloadCustoms()

        # 2. EditEntry log, as the modal previously did via /entry/edit.
        serializer = EditEntrySerializer(data={
            "type": "custom",
            "simplified": simplified,
            "traditional": traditional,
            "pinyin": pinyin,
            "english": english,
            **({"notes": notes} if notes else {}),
        })
        if serializer.is_valid():
            serializer.save()

        return Response({"ok": True, "already": done},
                        status=status.HTTP_200_OK)


class DismissSuggestionView(APIView):
    """Mark a g2pM suggestion as wrong in its context.

    POST {char, dict_pinyin, suggested_pinyin, prev_char?, next_char?}:
    records the tuple in data/g2pm_dismissed.json so resolve_pinyin never
    flags that (character, dictionary reading -> model suggestion) direction
    again *in that context* -- the character's immediate neighbors within
    its phrase ("" at phrase edges). The same suggestion can still flag in
    other contexts. Pinyin may be toned or ASCII.
    """
    def post(self, request, format=None):
        data = request.data if isinstance(request.data, dict) else {}
        char = data.get("char", "")
        dict_pinyin = polyphone.unparse_pinyin(data.get("dict_pinyin", ""))
        suggested = polyphone.unparse_pinyin(data.get("suggested_pinyin", ""))
        prev_char = data.get("prev_char", "") or ""
        next_char = data.get("next_char", "") or ""

        if not (isinstance(char, str) and len(char.strip()) == 1
                and isChinese(char.strip())):
            return Response({"detail": "char must be a single Chinese character"},
                            status=status.HTTP_400_BAD_REQUEST)
        if not polyphone.looks_like_pinyin(dict_pinyin):
            return Response({"detail": "dict_pinyin is not valid pinyin"},
                            status=status.HTTP_400_BAD_REQUEST)
        if not polyphone.looks_like_pinyin(suggested):
            return Response({"detail": "suggested_pinyin is not valid pinyin"},
                            status=status.HTTP_400_BAD_REQUEST)
        for name, value in (("prev_char", prev_char), ("next_char", next_char)):
            if not (isinstance(value, str) and len(value) <= 1
                    and (value == "" or isChinese(value))):
                return Response(
                    {"detail": f"{name} must be a single Chinese character or empty"},
                    status=status.HTTP_400_BAD_REQUEST)

        path = _data_path("g2pm_dismissed.json")
        rows = _read_json_list(path)
        row = {"char": char.strip(), "dict_pinyin": dict_pinyin,
               "suggested_pinyin": suggested,
               "prev_char": prev_char, "next_char": next_char}
        done = any(r.get("char") == row["char"]
                   and r.get("dict_pinyin") == row["dict_pinyin"]
                   and r.get("suggested_pinyin") == row["suggested_pinyin"]
                   and r.get("prev_char", "") == row["prev_char"]
                   and r.get("next_char", "") == row["next_char"]
                   for r in rows)
        if not done:
            rows.append(row)
            with open(path, "w") as f:
                json.dump(rows, f, ensure_ascii=False, indent=2)
        polyphone.clear_dismissed_cache()
        # The user judged the dictionary reading correct here: log it as a
        # training example (label 'dismiss', pinyin = the kept reading).
        _log_training_example(data.get("context"), data.get("context_index"),
                              char.strip(), dict_pinyin,
                              "dismiss", data.get("model") or "g2pm")
        return Response({"ok": True, "already": done},
                        status=status.HTTP_200_OK)


class ReloadCEDictView(APIView):

    def post(self, request, format=None):
        if not self.request.session.exists(self.request.session.session_key):
            self.request.session.create()
        # print(request.data)

        lenA, lenB, lenTradToSimpMap = reloadCEDict()
        EntryManager.reload()
        Trie.clearTries()
        # TradEntryManager.reload()
        return Response({"OK": "Done reloaded CEDict", "lenA": lenA, "lenB": lenB, "lenTradToSimpMap": lenTradToSimpMap}, status=status.HTTP_200_OK)

class ClearRAMView(APIView):

    def post(self, request, format=None):
        if not self.request.session.exists(self.request.session.session_key):
            self.request.session.create()
        # print(request.data)

        Trie.clearTries()
        return Response({"OK": "Cleared Tries"}, status=status.HTTP_200_OK)

class EditEntryView(APIView):
    queryset = EditEntry.objects.all()
    serializer_class = EditEntrySerializer
    
    def get(self, request, format=None):
        if not self.request.session.exists(self.request.session.session_key):
            self.request.session.create()

        type = self.request.query_params.get('type')
        if type is None:
            # get all
            editEntries = EditEntry.objects.all()
        else:
            editEntries = EditEntry.objects.filter(type=type)
        
        return Response(EditEntrySerializer(editEntries, many=True).data, status=status.HTTP_200_OK)

    def post(self, request, format=None):
        if not self.request.session.exists(self.request.session.session_key):
            self.request.session.create()
        print(request.data)
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            editEntry = serializer.validated_data
            print(editEntry)
            serializer.save()
                        
            # if 'code' in request.data.keys():
            #     code = request.data['code']
            #     # This is for updating the Memories. it shouldn't be used by the frontend.
            #     memory = Memory.objects.get(code=code)
            #     memory.fragments.clear()
            #     for frag in fragments:
            #         # TODO: make this atomic
            #         fragment, created = Fragment.objects.get_or_create(
            #             pinyin=frag['pinyin'],
            #             cchar=frag['cchar'])
            #         memory.f.add(fragment)
            #     memory.save()
            return Response(EditEntrySerializer(editEntry).data, status=status.HTTP_200_OK)
            # else:
            #     latest = Memory.objects.order_by('-code').first()
            #     code = 0
            #     if latest is not None:
            #         code = latest.code + 1

            #     memory = Memory(code=code)
            #     memory.save()
            #     for frag in fragments:
            #         fragment, created = Fragment.objects.get_or_create(
            #             pinyin=frag['pinyin'],
            #             cchar=frag['cchar'])
            #         memory.fragments.add(fragment)
            #     memory.save()
            # return Response(EditEntrySerializer(editEntry).data, status=status.HTTP_201_CREATED)

        return Response({'Bad Request': 'Invalid data...'}, status=status.HTTP_400_BAD_REQUEST)


class CleanEditEntryView(APIView):
    
    def get(self, request, format=None):
        if not self.request.session.exists(self.request.session.session_key):
            self.request.session.create()
        print(request.data)

        # editEntries = Memory.objects.values_list("code", flat=True)
        # countCodes = editEntries.count()
        # return Response({"OK": "counted and list current memory codes", "count": count, "data": memory}, status=status.HTTP_200_OK)

        response = {"OK": "Previewing memory status - Send POST to clean"}
        for choice in EditEntry.EditEntryType.values:
            print(choice)
            editEntries = EditEntry.objects.filter(type=choice).values_list("simplified", flat=True)
            count = editEntries.count()
            response[choice] = {
                "count" : count,
                "entries" : editEntries
            }
        return Response(response, status=status.HTTP_200_OK)
        
    def post(self, request, format=None):
        if not self.request.session.exists(self.request.session.session_key):
            self.request.session.create()

        editEntries = EditEntry.objects.all()
        count = editEntries.count()
        editEntries.delete()
        return Response({"OK": "Successfully cleaned up all edit entries", "count": count}, status=status.HTTP_200_OK)

# class CreateEntryView(APIView):
#     serializer_class = CreateEntrySerializer

#     def post(self, request, format=None):
#         if not self.request.session.exists(self.request.session.session_key):
#             self.request.session.create()

#         serializer = self.serializer_class(data=request.data, partial=True)
#         if serializer.is_valid():
#             traditional = serializer.data.get('traditional')
#             simplified = serializer.data.get('simplified')
#             pinyin = serializer.data.get('pinyin')
#             english = serializer.data.get('english')
#             owner = serializer.data.get('owner')
#             priority = serializer.data.get('priority')
#             if priority is None:
#                 priority = USER_PRIORITY
#             # owner = DEFAULT_OWNER
#             # if SESSIONS:
#             # owner = self.request.session.session_key

#             # Fetch/Create owner's dictionary
#             # queryset = Entry.objects.filter(owner=owner)
#             # if not queryset.exists():
#             #     # loadDefaultDictionary()
#             #     queryset = Entry.objects.filter(owner=owner)
#             #     if not queryset.exists():
#             #         return Response({'Bad Request': 'New user session, but unable to create default dictionary entries'}, status=status.HTTP_400_BAD_REQUEST)

#             # if(traditional == ""):
#             #     # TODO: fetch traditional from dictionary
#             #     # traditional = ...
#             #     pass

#             queryset = Entry.objects.filter(traditional=traditional,
#                                             simplified=simplified, pinyin=pinyin)
#             if(queryset.exists()):
#                 return Response({'Bad Request': 'Entry already exists', 'data': EntrySerializer(queryset, many=True).data}, status=status.HTTP_400_BAD_REQUEST)

#             else:
#                 entry = Entry(owner=owner, traditional=traditional,
#                               simplified=simplified, pinyin=pinyin, english=english, priority=priority)
#                 entry.save()

#             return Response(EntrySerializer(entry).data, status=status.HTTP_200_OK)

#         return Response({'Bad Request': 'Invalid data...'}, status=status.HTTP_400_BAD_REQUEST)


# class UpdateEntryView(generics.RetrieveUpdateDestroyAPIView):
#     # queryset = Entry.objects.all()
#     queryset = Entry.objects.all()
#     serializer_class = UpdateEntrySerializer
    # lookup_field = 'simplified'

    # def put(self, request, format=None):
    #     if not self.request.session.exists(self.request.session.session_key):
    #         self.request.session.create()

    #     serializer = self.serializer_class(data=request.data, partial=True)
    #     if serializer.is_valid():
    #         traditional = serializer.data.get('traditional')
    #         simplified = serializer.data.get('simplified')
    #         pinyin = serializer.data.get('pinyin')
    #         english = serializer.data.get('english')
    #         owner = serializer.data.get('owner')
    #         priority = serializer.data.get('priority')
    #         if priority is None:
    #             priority = 999
    #         # owner = DEFAULT_OWNER
    #         # if SESSIONS:
    #         # owner = self.request.session.session_key

    #         # Fetch/Create owner's dictionary
    #         # queryset = Entry.objects.filter(owner=owner)
    #         # if not queryset.exists():
    #         #     # loadDefaultDictionary()
    #         #     queryset = Entry.objects.filter(owner=owner)
    #         #     if not queryset.exists():
    #         #         return Response({'Bad Request': 'New user session, but unable to create default dictionary entries'}, status=status.HTTP_400_BAD_REQUEST)

    #         # if(traditional == ""):
    #         #     # TODO: fetch traditional from dictionary
    #         #     # traditional = ...
    #         #     pass

    #         queryset = Entry.objects.filter(owner=owner, traditional=traditional,
    #                                         simplified=simplified, pinyin=pinyin)
    #         if(queryset.exists()):
    #             res = EntrySerializer(queryset, many=True).data
    #             res['Bad Request'] = 'Entry already exists'
    #             Response(res, status=status.HTTP_400_BAD_REQUEST)
    #         else:
    #             entry = Entry(owner=owner, traditional=traditional,
    #                           simplified=simplified, pinyin=pinyin, english=english, priority=priority)
    #             entry.save()

    #         return Response(EntrySerializer(entry).data, status=status.HTTP_200_OK)

    #     return Response({'Bad Request': 'Invalid data...'}, status=status.HTTP_400_BAD_REQUEST)

# @api_view(['DELETE'])
# def clearCache(request):
#     # EntryView.queryset.delete()
#     cache.clear()
#     Trie.clearTries()
#     return Response({'OK': 'Deleted everything!!...', 'count': len([key for key in cache.iter_keys("*")])}, status=status.HTTP_200_OK)

# class ReloadEntryView(APIView):

#     def post(self, request, format=None):
#         if not self.request.session.exists(self.request.session.session_key):
#             self.request.session.create()

#         # serializer = self.serializer_class(data=request.data)
#         # if serializer.is_valid():
#         owner = DEFAULT_OWNER
#         # if(request.data['owner']):
#         #     owner = request.data.owner

#         # if SESSIONS:
#         #     owner = self.request.session.session_key

#         # Fetch/Create owner's dictionary
#         # queryset = Entry.objects.filter(owner=owner).delete()
#         # queryset = Entry.objects.filter(owner=owner)
#         print("deleted")
#         # if queryset.exists():
#         #     return Response({'Bad Request': 'Unable to delete entries for current owner'}, status=status.HTTP_400_BAD_REQUEST)
#         cache.clear()
#         loadDefaultDictionary()
#         print("created new entries")
#         # queryset = Entry.objects.filter(owner=owner)
#         # if not queryset.exists():
#         #     return Response({'Bad Request': 'Deleted entries but unable to create default dictionary entries'}, status=status.HTTP_400_BAD_REQUEST)

#         Trie.clearTries()
#         return Response({'OK': 'Reloaded default dictionary entries', 'count': len(cache.iter_keys("*"))}, status=status.HTTP_200_OK)

#     def delete(self, request, format=None):
#         # EntryView.queryset.delete()

#         cache.clear()

#         Trie.clearTries()
#         return Response({'OK': 'Deleted everything!!...'}, status=status.HTTP_200_OK)


# class ReloadBlacklistEntryView(APIView):

#     def post(self, request, format=None):
#         if not self.request.session.exists(self.request.session.session_key):
#             self.request.session.create()

#         owner = DEFAULT_OWNER

#         # Fetch/Create owner's dictionary
#         queryset = BlacklistEntry.objects.filter(owner=owner).delete()
#         queryset = BlacklistEntry.objects.filter(owner=owner)
#         print("deleted")
#         if queryset.exists():
#             return Response({'Bad Request': 'Unable to delete Blacklist Entries for current owner', 'owner': owner, }, status=status.HTTP_400_BAD_REQUEST)
#         # if(owner == DEFAULT_OWNER):
#         loadDefaultBlacklist()
#         updateBlacklistPriorities()
#         print("created new Blacklist entries")
#         queryset = BlacklistEntry.objects.filter(owner=owner)
#         if not queryset.exists():
#             return Response({'Bad Request': 'Deleted blacklist entries but unable to create default blacklist entries'}, status=status.HTTP_400_BAD_REQUEST)

#         Trie.clearTries()
#         return Response({'OK': 'Reloaded default blacklist entries', 'count': len(queryset)}, status=status.HTTP_200_OK)
#         # else:
#         #     return Response({'Bad Request': 'You must specify the "owner" in the body of your request. If you want to reload the default entries, your body must be {"owner"="defualt"} '}, status=status.HTTP_400_BAD_REQUEST)

#     def delete(self, request, format=None):
#         EntryView.queryset.delete()

#         return Response({'OK': 'Deleted everything!!...'}, status=status.HTTP_200_OK)


# class CountEntryView(APIView):

#     serializer_class = ReloadEntrySerializer

#     def get(self, request, format=None):
#         if not self.request.session.exists(self.request.session.session_key):
#             self.request.session.create()

#         owner = DEFAULT_OWNER
#         if 'owner' in request.data.keys():
#             owner = request.data['owner']

#         # if SESSIONS:
#         #     owner = self.request.session.session_key

#         # Fetch/Create owner's dictionary
#         queryset = Entry.objects.filter(owner=owner)

#         return Response({'OK': 'able to fetch default dict', 'count': len(queryset)}, status=status.HTTP_200_OK)


# class FragmentView(generics.ListCreateAPIView):
#     queryset = Fragment.objects.all()
#     serializer_class = FragmentSerializer


# class MemoryView(generics.ListCreateAPIView):
#     queryset = Memory.objects.all()
#     serializer_class = MemorySerializer


# class FetchMemoryView(APIView):
#     # queryset = Entry.objects.all()
#     serializer_class = MemorySerializer

#     def get(self, request, format=None):
#         if not self.request.session.exists(self.request.session.session_key):
#             self.request.session.create()

#         code = self.request.query_params.get('code')
#         if code is None:
#             code = 0

#         # TODO: DNE check
#         memory = Memory.objects.get(code=code)
#         # data = {
#         #     "code": code,
#         #     "fragment": FragmentSerializer(Memory.objects.get(code=code).fragments.all(), many=True).data
#         # }

#         return Response(MemorySerializer(memory).data, status=status.HTTP_200_OK)

#         # return Response({'Bad Request': 'Invalid data...'}, status=status.HTTP_400_BAD_REQUEST)


# class CreateMemoryView(APIView):

#     serializer_class = MemoryCreateSerializer

#     def post(self, request, format=None):
#         if not self.request.session.exists(self.request.session.session_key):
#             self.request.session.create()
#         print(request.data)
#         serializer = self.serializer_class(data=request.data)
#         if serializer.is_valid():
#             fragments = serializer.data.get('fragments')
#             if 'code' in request.data.keys():
#                 code = request.data['code']
#                 # This is for updating the Memories. it shouldn't be used by the frontend.
#                 memory = Memory.objects.get(code=code)
#                 memory.fragments.clear()
#                 for frag in fragments:
#                     # TODO: make this atomic
#                     fragment, created = Fragment.objects.get_or_create(
#                         pinyin=frag['pinyin'],
#                         cchar=frag['cchar'])
#                     memory.f.add(fragment)
#                 memory.save()
#                 return Response(MemorySerializer(memory).data, status=status.HTTP_200_OK)
#             else:
#                 latest = Memory.objects.order_by('-code').first()
#                 code = 0
#                 if latest is not None:
#                     code = latest.code + 1

#                 memory = Memory(code=code)
#                 memory.save()
#                 for frag in fragments:
#                     fragment, created = Fragment.objects.get_or_create(
#                         pinyin=frag['pinyin'],
#                         cchar=frag['cchar'])
#                     memory.fragments.add(fragment)
#                 memory.save()

#             # memory.fragments.add(*fragments)

#             return Response(MemorySerializer(memory).data, status=status.HTTP_201_CREATED)

#         return Response({'Bad Request': 'Invalid data...'}, status=status.HTTP_400_BAD_REQUEST)


# class DestroyMemoryView(generics.RetrieveDestroyAPIView):
#     queryset = Memory.objects.all()
#     serializer_class = MemorySerializer
#     lookup_field = "code"


# class CleanMemoryView(APIView):

#     serializer_class = CleanMemorySerializer

#     def get(self, request, format=None):
#         if not self.request.session.exists(self.request.session.session_key):
#             self.request.session.create()
#         print(request.data)

#         memoryCodes = Memory.objects.values_list("code", flat=True)
#         countCodes = memoryCodes.count()
#         # return Response({"OK": "counted and list current memory codes", "count": count, "data": memory}, status=status.HTTP_200_OK)

#         # memory = Memory.objects.filter(code__in=codes)
#         memoryEmpty = Memory.objects.filter(fragments=None).exclude(
#             code=0).values_list("code", flat=True)
#         countEmpty = memoryEmpty.count()
#         # memory.delete()
#         return Response({
#             "OK": "Previewing memory status",
#             "empty memories": {
#                 "count": countEmpty,
#                 "codes": memoryEmpty
#             },
#             "total": {
#                 "count": countCodes,
#                 "codes": memoryCodes
#             }
#         }, status=status.HTTP_200_OK)

#     def post(self, request, format=None):
#         if not self.request.session.exists(self.request.session.session_key):
#             self.request.session.create()
#         print(request.data)

#         serializer = self.serializer_class(data=request.data)
#         if serializer.is_valid():
#             codes = serializer.data.get('codes')
#             memory = Memory.objects.filter(code__in=codes)
#             count = memory.count()
#             memory.delete()
#             return Response({"OK": "Successfully cleaned up memories",
#                              "memories recycled": count}, status=status.HTTP_200_OK)

#         # memory = Memory.objects.filter(code__in=codes)
#         memory = Memory.objects.filter(fragments=None).exclude(code=0)
#         count = memory.count()
#         memory.delete()
#         return Response({"OK": "Successfully cleaned up empty memories", "count": count}, status=status.HTTP_200_OK)

#     # NOTE: this isn't proper convention... but it's here just to help debug
#     # def delete(self, request, format=None):
#     #     if not self.request.session.exists(self.request.session.session_key):
#     #         self.request.session.create()
#     #     # codes = [17, 18, 19, 20, 21, 22, 23, 24, 25,
#     #     #          26, 27, 28, 29, 30, 31, 32, 33, 34, 35]
#     #     codes = []
#     #     if codes:
#     #         memory = Memory.objects.filter(code__in=codes)
#     #         memory.delete()
#     #         return Response({"OK": "cleaned up specified memories", "data": MemorySerializer(memory, many=True).data}, status=status.HTTP_200_OK)

#     #     memory = Memory.objects.filter(fragments=None).exclude(code=0)
#     #     memory.delete()
#     #     return Response({"OK": "cleaned up empty memories", "data": MemorySerializer(memory, many=True).data}, status=status.HTTP_200_OK)


# class CacheView(APIView):

#     # def get(self, request, format=None):
#     # count = len([x for x in cache.iter_keys("*")])
#     # dictCount = len([x for x in cache.iter_keys("dict::*")])
#     # blacklistCount = len([x for x in cache.iter_keys("black::*")])
#     # customCount = len([x for x in cache.iter_keys("custom::*")])
#     # priorityCount = len([x for x in cache.iter_keys("priority::*")])

#     # return Response({"OK": "Fetched count", "count": count, "dictCount": dictCount,
#     #  "blacklistCount": blacklistCount,
#     #  "customCount": customCount,
#     #  "priorityCount": priorityCount, }, status=status.HTTP_200_OK)

#     def post(self, request, format=None):

#         rType = None
#         method = None
#         id = None

#         if 'type' in request.data:
#             rType = request.data['type']

#         if 'id' in request.data:
#             id = request.data['id']

#         if 'method' in request.data:
#             method = request.data['method']

#         if method == 'reload':
#             print("we got inside")
#             if(rType):
#                 if(rType == DICT):
#                     EntryManager.reloadDictionary()
#                 elif(rType == CUSTOM):
#                     EntryManager.reloadCustom()
#                 elif(rType == PRIORITY):
#                     EntryManager.reloadPriorities()
#                 elif(rType == BLACKLIST):
#                     EntryManager.reloadBlacklist()
#                 else:
#                     return Response({"Bad Request": "Invalid Type", "type": rType, "method": method, "id": id}, status=status.HTTP_400_BAD_REQUEST)
#             else:
#                 EntryManager.reload()
#             Trie.clearTries()
#         else:
#             if(rType):
#                 if(rType == DICT):
#                     EntryManager.loadDictionary(id)
#                     # Trie.loadTrie(id)
#                 elif(rType == CUSTOM):
#                     EntryManager.loadCustom()
#                 elif(rType == PRIORITY):
#                     EntryManager.loadPriorities()
#                 elif(rType == BLACKLIST):
#                     EntryManager.loadBlacklist()
#                 else:
#                     return Response({"Bad Request": "Invalid Type", "type": rType, "method": method, "id": id}, status=status.HTTP_400_BAD_REQUEST)
#             else:
#                 EntryManager.load()

#         return Response({"OK": "Reloaded Entries", "type": rType, "method": method, "id": id}, status=status.HTTP_200_OK)

#     def delete(self, request, format=None):

#         rType = None

#         if 'type' in request.data:
#             rType = request.data['type']

#         if(rType):
#             if(rType == DICT):
#                 EntryManager.clearDictionary()
#             elif(rType == CUSTOM):
#                 EntryManager.clearCustom()
#             elif(rType == PRIORITY):
#                 EntryManager.clearPriorities()
#             elif(rType == BLACKLIST):
#                 EntryManager.clearBlacklist()
#             else:
#                 return Response({"Bad Request": "Invalid Type", "type": rType, "method": method, "id": id}, status=status.HTTP_400_BAD_REQUEST)
#         else:
#             EntryManager.clear()

#         Trie.clearTries()
#         return Response({"OK": "Deleted Entries", "type": rType}, status=status.HTTP_200_OK)


# class PriorityView(APIView):

#     def post(self, request, format=None):
#         if not self.request.session.exists(self.request.session.session_key):
#             self.request.session.create()
#         print(request.data)

#         countBefore = Entry.objects.filter(priority=MAIN_PRIORITY).count()

#         (success, message, data) = updateDefaultPriorities()

#         countUpdated = Entry.objects.filter(priority=MAIN_PRIORITY).count()

#         if success:
#             return Response({"OK": message, "countBefore": countBefore, "countUpdated": countUpdated}, status=status.HTTP_200_OK)
#         else:
#             return Response({"Service Unavailable": message, "data": data}, status=status.HTTP_503_SERVICE_UNAVAILABLE)


# class ReloadCustomEntryView(APIView):

#     # serializer_class = ReloadEntrySerializer

#     def post(self, request, format=None):
#         if not self.request.session.exists(self.request.session.session_key):
#             self.request.session.create()

#         # serializer = self.serializer_class(data=request.data)
#         # if serializer.is_valid():
#         owner = "custom"
#         # if(request.data['owner']):
#         #     owner = request.data.owner

#         # if SESSIONS:
#         #     owner = self.request.session.session_key

#         # Fetch/Create owner's dictionary
#         queryset = Entry.objects.filter(owner=owner).delete()
#         queryset = Entry.objects.filter(owner=owner)
#         print("deleted")
#         if queryset.exists():
#             return Response({'Bad Request': 'Unable to delete custom entries'}, status=status.HTTP_400_BAD_REQUEST)

#         loadCustomEntries()
#         updateCustomPriorities()

#         print("created new custom entries")
#         queryset = Entry.objects.filter(owner=owner)
#         if not queryset.exists():
#             return Response({'Bad Request': 'Deleted entries but unable to create custom dictionary entries'}, status=status.HTTP_400_BAD_REQUEST)

#         Trie.clearTries()
#         return Response({'OK': 'Reloaded custom dictionary entries', 'count': len(queryset)}, status=status.HTTP_200_OK)

#     def delete(self, request, format=None):
#         owner = "custom"
#         queryset = Entry.objects.filter(owner=owner).delete()
#         Trie.clearTries()
#         return Response({'OK': 'Deleted everything!!...'}, status=status.HTTP_200_OK)


# class ReloadAllView(APIView):

#     def post(self, request, format=None):
#         if not self.request.session.exists(self.request.session.session_key):
#             self.request.session.create()

#         # Entry.objects.filter(
#         #     Q(owner=DEFAULT_OWNER) | Q(owner="custom")).delete()
#         # queryset = Entry.objects.filter(
#         #     Q(owner=DEFAULT_OWNER) | Q(owner="custom"))
#         print("deleted default and custom")
#         # if queryset.exists():
#         #     return Response({'Bad Request': 'Unable to delete default and custom entries'}, status=status.HTTP_400_BAD_REQUEST)
#         cache.clear()

#         loadDefaultDictionary()
#         updateDefaultPriorities()

#         print("created new default")

#         # queryset = Entry.objects.filter(owner=DEFAULT_OWNER)
#         # if not queryset.exists():
#         #     return Response({'Bad Request': 'Deleted default and custom entries but unable to create default entries'}, status=status.HTTP_400_BAD_REQUEST)

#         # defaultcount = queryset.count()

#         loadCustomEntries()
#         updateCustomPriorities()

#         print("created new custom")

#         # queryset = Entry.objects.filter(owner="custom")
#         # if not queryset.exists():
#         #     return Response({'Bad Request': 'Deleted default and custom entries but unable to create custom entries'}, status=status.HTTP_400_BAD_REQUEST)

#         # customcount = queryset.count()

#         # Fetch/Create owner's dictionary
#         # BlacklistEntry.objects.filter(owner=DEFAULT_OWNER).delete()
#         # queryset = BlacklistEntry.objects.filter(owner=DEFAULT_OWNER)
#         # if queryset.exists():
#         #     return Response({'Bad Request': 'Unable to delete default blacklist entries'}, status=status.HTTP_400_BAD_REQUEST)

#         loadDefaultBlacklist()
#         updateBlacklistPriorities()

#         print("created new blacklist")
#         # queryset = BlacklistEntry.objects.filter(owner=DEFAULT_OWNER)
#         # if not queryset.exists():
#         #     return Response({'Bad Request': 'Deleted blacklist entries but unable to create default blacklist entries'}, status=status.HTTP_400_BAD_REQUEST)

#         # blacklistcount = queryset.count()

#         Trie.clearTries()
#         return Response({'OK': 'Reloaded all dictionary entries', 'counts': {
#             # "default": defaultcount,
#             # "custom": customcount,
#             # "blacklist": blacklistcount
#         }}, status=status.HTTP_200_OK)

# @api_view(['GET', 'POST'])
# def manage_items(request, *args, **kwargs):
#     if request.method == 'GET':
#         items = {}
#         count = 0
#         for key in cache.keys("*"):
#             items[key.decode("utf-8")] = cache.get(key)
#             count += 1
#         response = {
#             'count': count,
#             'msg': f"Found {count} items.",
#             'items': items
#         }
#         return Response(response, status=200)
#     elif request.method == 'POST':
#         item = json.loads(request.body)
#         key = list(item.keys())[0]
#         value = item[key]
#         cache.set(key, value)
#         response = {
#             'msg': f"{key} successfully set to {value}"
#         }
#         return Response(response, 201)
