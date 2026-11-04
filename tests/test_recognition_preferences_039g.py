"""Recognition preferences never widen targets, negations, or ambiguous triggers."""
from pathlib import Path
import tempfile
import unittest

from luxai.command_registry import CommandRegistry, checked_command


class RecognitionPreferences039gTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.registry = CommandRegistry(Path(folder.name) / "commands.json")
        # Isolate personal trigger examples from shipped preset aliases.
        self.registry.deleted_builtins.update(item["id"] for item in self.registry.entries())

    def add(self, identifier, phrase, **fields):
        return self.registry.save_command(checked_command({
            "id": identifier, "title": identifier, "action": "time", "target": "",
            "phrases": [phrase], **fields,
        }))

    def test_sensitivity_controls_one_pronunciation_typo_and_zero_is_exact(self):
        self.add("open_daily", "open daily report")
        self.assertIsNone(self.registry.match("opne daily report", sensitivity=0))
        self.assertIsNone(self.registry.match("opne daily report", sensitivity=50))
        self.assertEqual(self.registry.match("opne daily report", sensitivity=100)["id"], "open_daily")
        self.assertEqual(self.registry.match("Jarvis, OPEN DAILY REPORT!", sensitivity=0)["id"], "open_daily")

    def test_fuzzy_never_changes_target_word_number_order_or_single_word(self):
        self.add("open_daily", "open daily report 2")
        self.add("single", "calculator")
        self.add("close_daily", "close daily report")
        for spoken in (
            "open daily report 3", "open daily reports 2", "open dairy report 2",
            "daily open report 2", "opne report 2", "calculater", "clone daily report",
            "do not open daily report 2", "не open daily report 2", "nu open daily report 2",
        ):
            with self.subTest(spoken=spoken):
                self.assertIsNone(self.registry.match(spoken, sensitivity=100, paraphrases=True))

    def test_bounded_paraphrases_accept_known_verbs_and_polite_forms_in_three_languages(self):
        examples = (
            ("english", "open daily report", "could you please launch daily report"),
            ("russian", "открой ежедневный отчёт", "пожалуйста запусти ежедневный отчёт"),
            ("romanian", "deschide raportul zilnic", "ai putea să pornește raportul zilnic te rog"),
        )
        for identifier, phrase, spoken in examples:
            self.add(identifier, phrase)
            with self.subTest(language=identifier):
                self.assertIsNone(self.registry.match(spoken, sensitivity=0, paraphrases=False))
                self.assertEqual(self.registry.match(spoken, sensitivity=0, paraphrases=True)["id"], identifier)
        for spoken in ("open the report from yesterday", "tell me about the daily report", "close daily report"):
            self.assertIsNone(self.registry.match(spoken, sensitivity=100, paraphrases=True))

    def test_exact_personal_phrase_wins_before_any_approximate_match(self):
        self.add("approximate", "open daily report")
        self.add("exact", "opne daily report")
        self.assertEqual(self.registry.match("opne daily report", sensitivity=100)["id"], "exact")

    def test_ambiguous_typo_and_lexical_paraphrase_are_rejected(self):
        self.add("second", "send daily report")
        self.add("third", "tend daily report")
        self.assertIsNone(self.registry.match("bend daily report", sensitivity=100))
        self.add("first", "open project archive")
        self.add("other", "launch project archive")
        self.assertIsNone(self.registry.match("start project archive", sensitivity=0, paraphrases=True))
        # An exact alias retains the longstanding exact priority.
        self.assertEqual(self.registry.match("launch project archive", paraphrases=True)["id"], "other")

    def test_disabled_or_manual_only_commands_block_fuzzy_and_paraphrase_fallback(self):
        self.add("disabled", "open daily report", enabled=False)
        self.add("manual", "show weekly report", voice_enabled=False)
        for spoken in ("opne daily report", "please launch daily report", "display weekly report"):
            with self.subTest(spoken=spoken):
                self.assertIsNone(self.registry.match(spoken, sensitivity=100, paraphrases=True))
                self.assertTrue(self.registry.disabled_match(spoken, sensitivity=100, paraphrases=True))
        self.assertFalse(self.registry.disabled_match("please launch daily report", sensitivity=0, paraphrases=False))
        self.assertEqual(self.registry.match("show weekly report", source="manual")["id"], "manual")

    def test_deleted_presets_and_replaced_aliases_cannot_be_restored(self):
        self.assertIsNone(self.registry.match("opne telegram", sensitivity=100))
        self.assertTrue(self.registry.disabled_match("opne telegram", sensitivity=100))
        self.assertTrue(self.registry.disabled_match("please launch telegram", paraphrases=True))
        replacement = self.add("replacement", "please launch telegram")
        self.assertEqual(self.registry.match("please launch telegram", paraphrases=True)["id"], replacement["id"])
        self.assertFalse(self.registry.disabled_match("please launch telegram", paraphrases=True))

    def test_optional_edges_and_chain_opt_out_keep_preferences(self):
        self.add("first", "open daily report", optional_words=["helper"], allow_chaining=False)
        self.add("second", "show weekly report")
        self.assertEqual(self.registry.match("helper opne daily report", sensitivity=100)["id"], "first")
        spoken = "please launch daily report потом display weekly report"
        self.assertTrue(self.registry.chain_blocked(spoken, paraphrases=True))
        self.assertEqual(self.registry.match_chain(spoken, paraphrases=True), [])
        self.registry.set_enabled("first", False)
        self.assertEqual(self.registry.match_chain(spoken, paraphrases=True), [])


if __name__ == "__main__":
    unittest.main()
