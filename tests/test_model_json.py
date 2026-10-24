"""Strict model proposal parsing and screenshot-verifier regressions, offline."""
from __future__ import annotations

import json
import unittest
from unittest import mock

from luxai.model_json import ModelJSONError, parse_model_json
from luxai.online_agent import OnlinePlanner
from luxai.visual_click import VisualCapture, VISUAL_SYSTEM, validate_visual_point
from luxai.visual_reasoner import _choose, _verify_goal
from luxai.visual_reasoner import run_visual_reasoner, MAX_ACTIONS


class ModelJSONTests(unittest.TestCase):
    def test_optional_bare_key_repair_is_string_aware_and_preserves_types(self):
        from luxai.online_agent import OnlinePlanner
        text = 'Sure: {action:"click",target:"literal {x:1}, target: stays",nested:{verified:true},values:[{x:2}],number:3}'
        expected = {"action": "click", "target": "literal {x:1}, target: stays", "nested": {"verified": True}, "values": [{"x": 2}], "number": 3}
        with self.assertRaises(ModelJSONError):
            parse_model_json(text)
        self.assertEqual(parse_model_json(text, quote_bare_keys=True), expected)
        self.assertEqual(OnlinePlanner._read_json_content('Sure: {action:"click",target:"Store"}'),
                         {"action": "click", "target": "Store"})

    def test_bare_key_repair_does_not_accept_code_python_or_ambiguous_values(self):
        for value in ('{action:click}', "{'action':'click'}", '{action:True}',
                      '{action:"click",}', '{action:"click", "action":"stop"}',
                      'const x = {action:"click"};', '{action:"click"} {action:"stop"}',
                      '{action:__import__("os")}', '{value:NaN}'):
            with self.subTest(value=value), self.assertRaises(ModelJSONError):
                parse_model_json(value, quote_bare_keys=True)

    def test_plain_json_keeps_real_types_and_unicode(self):
        result = parse_model_json('{"verified":false,"x":12.5,"note":"ș ț Привет","count":2,"optional":null}')
        self.assertIs(result["verified"], False)
        self.assertIs(type(result["x"]), float)
        self.assertIs(type(result["count"]), int)
        self.assertIsNone(result["optional"])
        self.assertEqual(result["note"], "ș ț Привет")

    def test_json_fences_and_surrounding_prose_are_presentation_only(self):
        for text in (
            '```json\n{"verified":true}\n```',
            '```JSON\r\n{"verified":true}\r\n```',
            '```\n{"verified":true}\n```',
            'Here is the result:\n{"verified":true}\nThe visible header matches.',
            'Result:\n```json\n{"verified":true}\n```\nThe check is complete.',
            '\ufeff {"verified":true}',
        ):
            with self.subTest(text=text):
                self.assertEqual(parse_model_json(text), {"verified": True})

    def test_braces_quotes_backslashes_and_markdown_inside_strings_are_not_wrappers(self):
        expected = {"note": 'literal {x} [1], a "quote", \\path and ```json', "steps": [{"action": "reply"}]}
        payload = json.dumps(expected)
        self.assertEqual(parse_model_json(payload), expected)
        self.assertEqual(parse_model_json("Result: " + payload), expected)
        self.assertEqual(parse_model_json("```json\n" + payload + "\n```"), expected)

    def test_provider_text_blocks_are_joined_without_coercion(self):
        blocks = [
            {"type": "text", "text": '{"verified":'},
            {"type": "image", "data": "not JSON"},
            {"type": "text", "text": "false}"},
        ]
        self.assertEqual(OnlinePlanner._read_json_content(blocks), {"verified": False})
        with self.assertRaises(ModelJSONError):
            parse_model_json([{"type": "text", "text": {"verified": True}}])

    def test_invalid_pseudo_json_is_never_repaired_or_executed(self):
        for payload in (
            '{verified:true}', '{"verified":True}', "{'verified': True}",
            '{"verified":true,}', '{"verified":true|false}',
            'const result = {"verified":true};', 'return {"verified":true};',
            '```python\n{"verified":true}\n```',
            '```javascript\n{"verified":true}\n```',
            '__import__("os").system("anything")',
        ):
            with self.subTest(payload=payload), self.assertRaises(ModelJSONError):
                parse_model_json(payload)

    def test_ambiguous_or_incomplete_results_do_not_yield_inner_success(self):
        for payload in (
            '{"verified":false} {"verified":true}',
            'First {"verified":false}, then {"verified":true}',
            '```json\n{"verified":false}\n```\n```json\n{"verified":true}\n```',
            '{"outer": {"verified":true}',
            '```json\n{"verified":true}',
            '[{"verified":true}]',
            'null\n{"verified":true}',
            '{"verified":true}\nfalse',
            '"{\\"verified\\":true}"',
        ):
            with self.subTest(payload=payload), self.assertRaises(ModelJSONError):
                parse_model_json(payload)

    def test_duplicate_keys_and_nonfinite_numbers_are_rejected(self):
        for payload in (
            '{"verified":false,"verified":true}',
            '{"steps":[{"action":"reply","action":"open_app"}]}',
            '{"x":NaN}', '{"x":Infinity}', '{"x":-Infinity}',
            '{"steps":[{"x":1e9999}]}',
        ):
            with self.subTest(payload=payload), self.assertRaises(ModelJSONError):
                parse_model_json(payload)

    def test_size_depth_and_block_limits_bound_untrusted_output(self):
        for payload in (
            '{"value":"' + "x" * 65_536 + '"}',
            '{"value":' + "[" * 40 + "0" + "]" * 40 + "}",
            [{"type": "text", "text": ""}] * 129,
        ):
            with self.subTest(kind=type(payload).__name__), self.assertRaises(ModelJSONError):
                parse_model_json(payload)
        with self.assertRaises(ModelJSONError):
            parse_model_json('{"value":"long"}', max_chars=10)

    def test_errors_do_not_echo_private_response_text(self):
        with self.assertRaises(ModelJSONError) as error:
            parse_model_json('{"private":"private-message-content",broken}')
        self.assertNotIn("private-message-content", str(error.exception))

    def test_parsing_never_substitutes_for_action_or_coordinate_validation(self):
        self.assertIsNone(OnlinePlanner._validate(parse_model_json('{"action":"open_shell","target":"cmd"}')))
        capture = screenshot()
        for payload in ('{"found":"true","x":500,"y":500}',
                        '{"found":true,"x":"500","y":500}',
                        '{"found":true,"x":true,"y":500}'):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                validate_visual_point(parse_model_json(payload), capture)


def screenshot():
    return VisualCapture(42, 100, "Discord", 0, 0, 1200, 800, 1200, 800, b"image")


class VisualJSONIntegrationTests(unittest.TestCase):
    def planner(self, content):
        planner = mock.Mock()
        planner.config = {"online_model": "gpt-4.1-mini"}
        planner.enabled.return_value = True
        planner._provider.return_value = "openai"
        planner._read_json_content = OnlinePlanner._read_json_content
        planner._extract_text = OnlinePlanner._extract_text
        planner._request.return_value = {"choices": [{"message": {"content": content}}]}
        return planner

    def test_verifier_accepts_wrapped_json_and_requests_valid_boolean_examples(self):
        planner = self.planner('Result:\n```json\n{"verified":true}\n```')
        with mock.patch("luxai.secure_keys.get_api_key", return_value="fake-key"):
            self.assertTrue(_verify_goal(planner, "Open the settings window", screenshot()))
        messages = planner._request.call_args.args[3]
        self.assertIn('{"verified":true}', messages[0]["content"])
        self.assertIn('{"verified":false}', messages[0]["content"])
        self.assertNotIn("{verified:", str(messages))

    def test_false_wrong_type_and_malformed_verification_are_all_unverified(self):
        for content in ('{"verified":false}', '{verified:True}',
                        '{"verified":"true"}', '{"verified":1}', 'not JSON'):
            planner = self.planner(content)
            with self.subTest(content=content), \
                    mock.patch("luxai.secure_keys.get_api_key", return_value="fake-key"):
                self.assertFalse(_verify_goal(planner, "Open a chat", screenshot()))

    def test_safe_bare_key_repair_preserves_boolean_verification(self):
        planner = self.planner('{verified:true}')
        with mock.patch("luxai.secure_keys.get_api_key", return_value="fake-key"):
            self.assertTrue(_verify_goal(planner, "Open a chat", screenshot()))

    def test_invalid_decision_format_is_retried_once_without_desktop_effects(self):
        planner = self.planner('invalid JSON')
        planner._request.side_effect = [
            {"choices": [{"message": {"content": 'invalid JSON'}}]},
            {"choices": [{"message": {"content": '{action:"click",target:"Store"}'}}]},
        ]
        with (
            mock.patch("luxai.secure_keys.get_api_key", return_value="fake-key"),
            mock.patch("luxai.visual_reasoner.click_visual_target") as click,
        ):
            decision = _choose(planner, "Click Steam Store", screenshot())
        self.assertEqual(decision, {"action": "click", "target": "Store"})
        self.assertEqual(planner._request.call_count, 2)
        click.assert_not_called()

    def test_visual_decision_uses_the_same_strict_parser(self):
        planner = self.planner('Next step: {"action":"click","target":"Settings","reason":"visible gear"}')
        with mock.patch("luxai.secure_keys.get_api_key", return_value="fake-key"):
            decision = _choose(planner, "Open settings", screenshot())
        self.assertEqual(decision["action"], "click")
        self.assertEqual(decision["target"], "Settings")
        planner._request.return_value = {"choices": [{"message": {"content": '{"action":"run_code"}'}}]}
        with mock.patch("luxai.secure_keys.get_api_key", return_value="fake-key"), self.assertRaises(ValueError):
            _choose(planner, "Open settings", screenshot())

    def test_locator_example_itself_is_valid_json(self):
        self.assertIn('{"found":true,"x":500,"y":350}', VISUAL_SYSTEM)
        self.assertNotIn('"x":number', VISUAL_SYSTEM)


class VisualOutcomeTests(unittest.TestCase):
    GOAL = "Open the application and click the settings menu"

    def run_session(self, decisions, *, verified=False, outcome=None):
        with (
            mock.patch("luxai.visual_reasoner.sys.platform", "win32"),
            mock.patch("luxai.visual_reasoner._select_window", return_value=42),
            mock.patch("luxai.visual_reasoner.capture_window", return_value=screenshot()) as capture,
            mock.patch("luxai.visual_reasoner._choose", side_effect=decisions) as choose,
            mock.patch("luxai.visual_reasoner.find_visual_target", return_value=(300, 400)),
            mock.patch("luxai.visual_reasoner.click_visual_target") as click,
            mock.patch("luxai.visual_reasoner._verify_goal", return_value=verified) as verify,
            mock.patch("luxai.visual_reasoner.time.sleep"),
        ):
            summary = run_visual_reasoner(mock.Mock(), self.GOAL, result_sink=outcome)
        return summary, click, verify, choose, capture

    def test_failed_post_click_verification_preserves_progress_without_repeating_toggle(self):
        outcome = {}
        summary, click, verify, choose, _ = self.run_session([
            {"action": "click", "target": "Settings"},
            {"action": "done"},
            {"action": "click", "target": "Different name for same toggle"},
        ], outcome=outcome)
        click.assert_called_once()
        verify.assert_called_once()
        self.assertEqual(choose.call_count, 2)
        self.assertTrue(outcome["ok"])
        self.assertFalse(outcome["verified"])
        self.assertEqual(outcome["actions"], 1)
        self.assertEqual(outcome["summary"], summary)
        self.assertIn("не подтверждён", summary)
        self.assertEqual(len(outcome["evidence"]), 1)

    def test_final_allowed_action_gets_fresh_observation_and_verification(self):
        outcome = {}
        decisions = [{"action": "click", "target": f"Page {index}"} for index in range(MAX_ACTIONS)]
        decisions.append({"action": "done", "reason": "Requested page is visible"})
        _, click, verify, _, capture = self.run_session(decisions, verified=True, outcome=outcome)
        self.assertEqual(click.call_count, MAX_ACTIONS)
        self.assertEqual(capture.call_count, MAX_ACTIONS + 1)
        verify.assert_called_once()
        self.assertEqual(outcome["actions"], MAX_ACTIONS)
        self.assertTrue(outcome["ok"])
        self.assertTrue(outcome["verified"])

    def test_action_budget_blocks_seventh_click_after_observing_the_result(self):
        outcome = {}
        decisions = [{"action": "click", "target": f"Page {index}"} for index in range(MAX_ACTIONS + 1)]
        summary, click, verify, _, capture = self.run_session(decisions, outcome=outcome)
        self.assertEqual(click.call_count, MAX_ACTIONS)
        self.assertEqual(capture.call_count, MAX_ACTIONS + 1)
        verify.assert_not_called()
        self.assertFalse(outcome["verified"])
        self.assertEqual(outcome["actions"], MAX_ACTIONS)
        self.assertIn("лимит действий", summary)

    def test_model_error_after_a_real_click_retains_structured_unverified_progress(self):
        outcome = {}
        with self.assertRaises(ModelJSONError):
            self.run_session([
                {"action": "click", "target": "Settings"},
                ModelJSONError("Model returned invalid JSON syntax"),
            ], outcome=outcome)
        self.assertTrue(outcome["ok"])
        self.assertFalse(outcome["verified"])
        self.assertEqual(outcome["actions"], 1)
        self.assertIn("Итог не подтверждён", outcome["summary"])

    def test_pre_action_model_error_has_no_executed_progress(self):
        outcome = {}
        with self.assertRaises(ModelJSONError):
            self.run_session([ModelJSONError("Invalid decision")], outcome=outcome)
        self.assertFalse(outcome["ok"])
        self.assertFalse(outcome["verified"])
        self.assertEqual(outcome["actions"], 0)


if __name__ == "__main__":
    unittest.main()
