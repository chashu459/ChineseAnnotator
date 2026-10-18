from django.test import TestCase

from api.polyphone import select_pinyin


class PolyphoneSelectPinyinTest(TestCase):
    """Unit tests for the g2pM candidate re-ranking in api/polyphone.py."""

    def _entries(self, *pinyins):
        return [{"pinyin": p} for p in pinyins]

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

    def test_match_is_case_insensitive(self):
        entries = self._entries("xing2", "hang2")
        self.assertEqual(select_pinyin("\u884c", entries, "HANG2"), "hang2")
