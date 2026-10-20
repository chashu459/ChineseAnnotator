from django.test import TestCase, override_settings

from api.polyphone import (
    SOURCE_CONFLICT,
    SOURCE_DICT,
    SOURCE_G2PM,
    is_dismissed,
    resolve_pinyin,
    select_pinyin,
    unparse_pinyin,
)


class PolyphoneSelectPinyinTest(TestCase):
    """Unit tests for the g2pM candidate re-ranking in api/polyphone.py."""

    def _entries(self, *pinyins):
        return [{"pinyin": p} for p in pinyins]

    @override_settings(G2PM_ADVISORY_MODE=False)
    def test_g2pm_prediction_wins_when_it_matches_a_candidate(self):
        entries = self._entries("xing2", "hang2")
        self.assertEqual(select_pinyin("\u884c", entries, "hang2"), "hang2")

    def test_falls_back_to_priority_when_prediction_is_unknown(self):
        entries = self._entries("xing2", "hang2")
        self.assertEqual(select_pinyin("\u884c", entries, "heng2"), "xing2")

    def test_falls_back_to_priority_when_no_prediction(self):
        entries = self._entries("xing2", "hang2")
        self.assertEqual(select_pinyin("\u884c", entries, None), "xing2")

    def test_falls_back_when_prediction_is_not_pinyin(self):
        entries = self._entries("xing2", "hang2")
        self.assertEqual(select_pinyin("\u884c", entries, "@"), "xing2")

    def test_monophonic_character_ignores_prediction(self):
        entries = self._entries("ni3")
        self.assertEqual(select_pinyin("\u4f60", entries, "na3"), "ni3")

    @override_settings(G2PM_ADVISORY_MODE=False)
    def test_match_is_case_insensitive(self):
        entries = self._entries("xing2", "hang2")
        self.assertEqual(select_pinyin("\u884c", entries, "HANG2"), "hang2")


class PolyphoneResolvePinyinTest(TestCase):
    """Provenance tests for api/polyphone.resolve_pinyin."""

    def _entries(self, *pinyins):
        return [{"pinyin": p} for p in pinyins]

    def test_agreement_reports_dict_source(self):
        entries = self._entries("xing2", "hang2")
        pinyin, source = resolve_pinyin("\u884c", "xing2", entries, "xing2")
        self.assertEqual((pinyin, source), ("xing2", SOURCE_DICT))

    def test_override_in_advisory_mode_reports_conflict_and_keeps_default(self):
        # Advisory mode (default): the model never overrides; the dictionary
        # reading is kept and the disagreement is flagged for curation.
        entries = self._entries("xing2", "hang2")
        pinyin, source = resolve_pinyin("\u884c", "xing2", entries, "hang2")
        self.assertEqual((pinyin, source), ("xing2", SOURCE_CONFLICT))

    @override_settings(G2PM_ADVISORY_MODE=False)
    def test_override_when_advisory_disabled_reports_g2pm_source(self):
        entries = self._entries("xing2", "hang2")
        pinyin, source = resolve_pinyin("\u884c", "xing2", entries, "hang2")
        self.assertEqual((pinyin, source), ("hang2", SOURCE_G2PM))

    def test_unknown_prediction_reports_conflict_and_keeps_default(self):
        entries = self._entries("xing2", "hang2")
        pinyin, source = resolve_pinyin("\u884c", "xing2", entries, "heng2")
        self.assertEqual((pinyin, source), ("xing2", SOURCE_CONFLICT))

    def test_missing_prediction_reports_dict_source(self):
        entries = self._entries("xing2", "hang2")
        pinyin, source = resolve_pinyin("\u884c", "xing2", entries, None)
        self.assertEqual((pinyin, source), ("xing2", SOURCE_DICT))

    def test_monophonic_character_reports_dict_source(self):
        entries = self._entries("ni3")
        pinyin, source = resolve_pinyin("\u4f60", "ni3", entries, "na3")
        self.assertEqual((pinyin, source), ("ni3", SOURCE_DICT))


class PolyphoneUnparseTest(TestCase):
    """unparse_pinyin: toned/ASCII -> ASCII + tone digit."""

    def test_ascii_passes_through_lowercased(self):
        self.assertEqual(unparse_pinyin("HANG2"), "hang2")

    def test_toned_to_ascii(self):
        self.assertEqual(unparse_pinyin("háng"), "hang2")
        self.assertEqual(unparse_pinyin("xíng"), "xing2")
        self.assertEqual(unparse_pinyin("zhǎng"), "zhang3")

    def test_umlaut(self):
        self.assertEqual(unparse_pinyin("lǜ"), "lu:4")
        self.assertEqual(unparse_pinyin("lü"), "lu:5")

    def test_toneless_is_neutral(self):
        self.assertEqual(unparse_pinyin("de"), "de5")

    def test_empty(self):
        self.assertEqual(unparse_pinyin(""), "")

    def test_garbage_is_not_blessed(self):
        # No vowel: returned unchanged so looks_like_pinyin rejects it.
        self.assertEqual(unparse_pinyin("zzz"), "zzz")


class PolyphoneDismissTest(TestCase):
    """A dismissed suggestion never flags again -- in its own context."""

    def _entries(self, *pinyins):
        return [{"pinyin": p} for p in pinyins]

    def test_dismissed_suggestion_returns_dict_source(self):
        import api.polyphone as polyphone
        polyphone._dismissed = {("行", "xing2", "hang2", "银", "长")}
        try:
            pinyin, source = resolve_pinyin(
                "行", "xing2", self._entries("xing2", "hang2"), "hang2",
                prev_char="银", next_char="长")
            self.assertEqual((pinyin, source), ("xing2", SOURCE_DICT))
        finally:
            polyphone.clear_dismissed_cache()

    def test_same_suggestion_other_context_still_conflicts(self):
        # The dismissal is scoped to (prev, char, next): the same
        # suggestion in a different word still flags.
        import api.polyphone as polyphone
        polyphone._dismissed = {("行", "xing2", "hang2", "银", "长")}
        try:
            _pinyin, source = resolve_pinyin(
                "行", "xing2", self._entries("xing2", "hang2"), "hang2",
                prev_char="独", next_char="侠")
            self.assertEqual(source, SOURCE_CONFLICT)
        finally:
            polyphone.clear_dismissed_cache()

    def test_legacy_row_without_context_matches_empty_context_only(self):
        # Rows written before context existed load with "" neighbors.
        import api.polyphone as polyphone
        polyphone._dismissed = {("行", "xing2", "hang2", "", "")}
        try:
            _pinyin, source = resolve_pinyin(
                "行", "xing2", self._entries("xing2", "hang2"), "hang2")
            self.assertEqual(source, SOURCE_DICT)
            _pinyin, source = resolve_pinyin(
                "行", "xing2", self._entries("xing2", "hang2"), "hang2",
                prev_char="银", next_char="长")
            self.assertEqual(source, SOURCE_CONFLICT)
        finally:
            polyphone.clear_dismissed_cache()

    def test_non_dismissed_still_conflicts(self):
        import api.polyphone as polyphone
        polyphone._dismissed = set()
        try:
            pinyin, source = resolve_pinyin(
                "长", "chang2",
                self._entries("chang2", "zhang3"), "zhang3")
            self.assertEqual(source, SOURCE_CONFLICT)
        finally:
            polyphone.clear_dismissed_cache()


class PolyphoneConfidenceTest(TestCase):
    """predict_with_confidence returns 1:1 pinyins plus softmax confidences.

    These need the real g2pM + numpy installed; they skip otherwise so the
    suite stays green without the model.
    """

    def test_pinyins_align_and_confidences_in_range(self):
        import api.polyphone as polyphone
        text = "他是银行的行长"
        pinyins, confidences = polyphone.predict_with_confidence(text)
        if pinyins is None:
            self.skipTest("g2pM not installed")
        self.assertEqual(len(pinyins), len(text))
        self.assertTrue(confidences, "expected polyphonic chars in text")
        for pos, conf in confidences.items():
            self.assertIsInstance(pos, int)
            self.assertTrue(0 <= pos < len(text))
            self.assertTrue(0.0 <= conf <= 1.0,
                            "confidence %r out of range" % (conf,))

    def test_wrapper_returns_same_pinyins(self):
        import api.polyphone as polyphone
        text = "头发很长"
        pinyins, _confidences = polyphone.predict_with_confidence(text)
        if pinyins is None:
            self.skipTest("g2pM not installed")
        self.assertEqual(polyphone.predict_char_pinyins(text), pinyins)

    def test_no_polyphonic_chars_gives_empty_confidences(self):
        import api.polyphone as polyphone
        text = "白天黑夜"  # monophonic in g2pM's cedict
        pinyins, confidences = polyphone.predict_with_confidence(text)
        if pinyins is None:
            self.skipTest("g2pM not installed")
        self.assertEqual(len(pinyins), len(text))
        self.assertEqual(confidences, {})

    def test_empty_text_returns_none_and_empty(self):
        import api.polyphone as polyphone
        pinyins, confidences = polyphone.predict_with_confidence("")
        self.assertIsNone(pinyins)
        self.assertEqual(confidences, {})


class PolyphoneG2PWTest(TestCase):
    """g2pW provider: dispatch, output mapping, and graceful fallback.

    Uses a fake `g2pw` module so no model download is needed.
    """

    def _install_fake_g2pw(self, outputs=None, fail=False):
        import sys
        import types
        fake = types.ModuleType("g2pw")

        class FakeConverter:
            init_kwargs = None

            def __init__(self, **kwargs):
                if fail:
                    raise RuntimeError("no model")
                FakeConverter.init_kwargs = kwargs

            def __call__(self, sentences):
                return outputs

        fake.G2PWConverter = FakeConverter
        sys.modules["g2pw"] = fake
        return FakeConverter

    def tearDown(self):
        import sys
        import api.polyphone as polyphone
        sys.modules.pop("g2pw", None)
        polyphone._g2pw_converter = None
        polyphone._g2pw_failed = False

    def test_g2pw_predictions_pass_through(self):
        import api.polyphone as polyphone
        fake_cls = self._install_fake_g2pw(outputs=[["yin2", "hang2"]])
        pinyins, confidences = polyphone.predict_with_confidence(
            "银行", model="g2pw")
        self.assertEqual(pinyins, ["yin2", "hang2"])
        self.assertEqual(confidences, {})
        # Simplified input is converted for the traditional-trained model.
        self.assertTrue(fake_cls.init_kwargs["enable_non_tradional_chinese"])
        self.assertEqual(fake_cls.init_kwargs["style"], "pinyin")

    def test_g2pw_none_predictions_echo_characters(self):
        import api.polyphone as polyphone
        self._install_fake_g2pw(outputs=[[None, "hang2", "，"]])
        pinyins, _conf = polyphone.predict_with_confidence(
            "银行，", model="g2pw")
        # Unknown chars are echoed so the list stays 1:1; downstream logic
        # ignores non-pinyin tokens via looks_like_pinyin.
        self.assertEqual(pinyins, ["银", "hang2", "，"])

    def test_g2pw_length_mismatch_returns_none(self):
        import api.polyphone as polyphone
        self._install_fake_g2pw(outputs=[["yin2"]])
        pinyins, confidences = polyphone.predict_with_confidence(
            "银行", model="g2pw")
        self.assertIsNone(pinyins)
        self.assertEqual(confidences, {})

    def test_g2pw_load_failure_returns_none(self):
        import api.polyphone as polyphone
        self._install_fake_g2pw(fail=True)
        pinyins, confidences = polyphone.predict_with_confidence(
            "银行", model="g2pw")
        self.assertIsNone(pinyins)
        self.assertEqual(confidences, {})
        self.assertFalse(polyphone.model_available("g2pw"))

    def test_model_available_with_fake_converter(self):
        import api.polyphone as polyphone
        self._install_fake_g2pw(outputs=[["yin2", "hang2"]])
        self.assertTrue(polyphone.model_available("g2pw"))

    def test_active_model_defaults_to_g2pm(self):
        import api.polyphone as polyphone
        self.assertEqual(polyphone.active_model(), "g2pm")

    def test_active_model_rejects_unknown_names(self):
        import sys
        import types
        from types import SimpleNamespace
        import api.polyphone as polyphone
        old_django = sys.modules.get("django")
        old_conf = sys.modules.get("django.conf")
        django = types.ModuleType("django")
        dconf = types.ModuleType("django.conf")
        dconf.settings = SimpleNamespace(G2P_MODEL="bert")
        django.conf = dconf
        sys.modules["django"] = django
        sys.modules["django.conf"] = dconf
        try:
            self.assertEqual(polyphone.active_model(), "g2pm")
            dconf.settings.G2P_MODEL = "G2PW"
            self.assertEqual(polyphone.active_model(), "g2pw")
        finally:
            # Restore the surrounding django stub; other tests depend on it.
            if old_django is not None:
                sys.modules["django"] = old_django
            else:
                sys.modules.pop("django", None)
            if old_conf is not None:
                sys.modules["django.conf"] = old_conf
            else:
                sys.modules.pop("django.conf", None)


class PolyphoneLLMTest(TestCase):
    """LLM adjudicator: reply parsing, caching, and graceful fallback.

    _chat is stubbed so no Ollama server is needed.
    """

    def setUp(self):
        from api import llm_adjudicator
        llm_adjudicator.clear_cache()
        self._replies = []
        self._calls = 0

        def fake_chat(prompt):
            self._calls += 1
            reply = self._replies.pop(0) if self._replies else ""
            if isinstance(reply, Exception):
                raise reply
            return reply

        import unittest.mock as mock
        self._patcher = mock.patch.object(llm_adjudicator, "_chat", fake_chat)
        self._patcher.start()

    def tearDown(self):
        from api import llm_adjudicator
        self._patcher.stop()
        llm_adjudicator.clear_cache()

    def _adjudicate(self, reply, **kwargs):
        from api import llm_adjudicator
        self._replies.append(reply)
        params = dict(char="行", candidates=["hang2", "xing2"],
                      sentence="他一个人走在银行前面。", phrase="银行",
                      char_index=1)
        params.update(kwargs)
        return llm_adjudicator.adjudicate(**params)

    def test_toned_reply_maps_to_candidate(self):
        self.assertEqual(self._adjudicate("háng"), "hang2")

    def test_ascii_reply_maps_to_candidate(self):
        self.assertEqual(self._adjudicate("xing2"), "xing2")

    def test_garbage_reply_returns_none(self):
        self.assertIsNone(self._adjudicate("我不知道"))

    def test_empty_reply_returns_none(self):
        self.assertIsNone(self._adjudicate(""))

    def test_chat_failure_returns_none_and_never_raises(self):
        self.assertIsNone(
            self._adjudicate(ConnectionError("server down")))

    def test_result_is_cached(self):
        from api import llm_adjudicator
        self._replies.append("háng")
        first = llm_adjudicator.adjudicate(
            "行", ["hang2", "xing2"], "他一个人走在银行前面。")
        second = llm_adjudicator.adjudicate(
            "行", ["hang2", "xing2"], "他一个人走在银行前面。")
        self.assertEqual(first, "hang2")
        self.assertEqual(second, "hang2")
        self.assertEqual(self._calls, 1)

    def test_different_context_triggers_new_call(self):
        from api import llm_adjudicator
        self._replies.extend(["háng", "xíng"])
        llm_adjudicator.adjudicate("行", ["hang2", "xing2"], "句子一。")
        llm_adjudicator.adjudicate("行", ["hang2", "xing2"], "句子二。")
        self.assertEqual(self._calls, 2)

    def test_multi_mention_reply_returns_none(self):
        from api import llm_adjudicator
        # Reply names both readings: resolving to the first-listed
        # candidate would be a coin flip with a systematic bias, so this
        # is unparseable (no conflict flagged) instead of a guess.
        self.assertIsNone(
            llm_adjudicator._match_candidate(
                "不是 xíng，而是 háng", ["hang2", "xing2"]))
        self.assertIsNone(
            llm_adjudicator._match_candidate(
                "hang2 or xing2?", ["hang2", "xing2"]))

    def test_single_verbatim_mention_returns_candidate(self):
        from api import llm_adjudicator
        self.assertEqual(
            llm_adjudicator._match_candidate(
                "我觉得是 xíng2 吧", ["hang2", "xing2"]),
            "xing2")

    def test_debug_logs_reply_and_choice(self):
        import io
        from contextlib import redirect_stdout
        from django.test import override_settings
        from api import llm_adjudicator
        self._replies.append("háng")
        buf = io.StringIO()
        with override_settings(LLM_ADJUDICATOR_DEBUG=True):
            with redirect_stdout(buf):
                choice = llm_adjudicator.adjudicate(
                    "行", ["hang2", "xing2"], "他一个人走在银行前面。")
        self.assertEqual(choice, "hang2")
        logged = buf.getvalue()
        self.assertIn("char=行", logged)
        self.assertIn("reply='háng'", logged)
        self.assertIn("choice=hang2", logged)

    def test_model_available_reflects_ping(self):
        import unittest.mock as mock
        import api.polyphone as polyphone
        from api import llm_adjudicator
        with mock.patch.object(llm_adjudicator, "_ping", return_value=True):
            llm_adjudicator.clear_cache()
            self.assertTrue(polyphone.model_available("llm"))
        with mock.patch.object(llm_adjudicator, "_ping", return_value=False):
            llm_adjudicator.clear_cache()
            self.assertFalse(polyphone.model_available("llm"))

    def test_predict_with_confidence_returns_none_for_llm(self):
        import api.polyphone as polyphone
        pinyins, confidences = polyphone.predict_with_confidence(
            "银行", model="llm")
        self.assertIsNone(pinyins)
        self.assertEqual(confidences, {})

    def test_model_label(self):
        import api.polyphone as polyphone
        self.assertEqual(polyphone.model_label("llm"), "LLM")
        self.assertEqual(polyphone.model_label("g2pm"), "g2pM")
        self.assertEqual(polyphone.model_label("g2pw"), "g2pW")

    def test_llm_in_g2p_models(self):
        import api.polyphone as polyphone
        self.assertIn("llm", polyphone.G2P_MODELS)
