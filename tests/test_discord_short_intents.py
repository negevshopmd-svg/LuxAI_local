"""Local Discord intent regressions; no desktop, network or account access."""
from __future__ import annotations

import unittest

from luxai import macro_planner
from luxai.voice_desktop import (
    discord_mic_visual_mode,
    wants_discord_mic_mute,
    wants_discord_mic_visual_click,
)


SPOKEN_REQUEST = "А ты можешь написать в дискорде пользователю Hanzo привет."
DETAILED_REQUEST = (
    "Открой Discord, найди пользователя Hanzo, "
    "напиши сообщение «привет» и нажми Enter"
)


def send_proposal(recipient: str = "Hanzo", message: str = "привет") -> dict:
    return {"steps": [{
        "action": "discord_send_text", "target": f"{recipient}||{message}",
    }]}


class DiscordShortMessageIntentTests(unittest.TestCase):
    def assert_complete_request(self, phrase, recipient, message):
        self.assertTrue(macro_planner.is_discord_message_request(phrase))
        self.assertEqual(
            macro_planner.discord_message_details(phrase),
            {
                "recipient": recipient, "message": message,
                "missing": [], "cancelled": False,
            },
        )
        self.assertEqual(
            macro_planner.detect_discord_text_request(phrase),
            (recipient, message),
        )

    def test_actual_short_spoken_request_preserves_recipient_and_content(self):
        self.assert_complete_request(SPOKEN_REQUEST, "Hanzo", "привет")

    def test_concise_requests_work_without_contact_role_words(self):
        examples = (
            ("Напиши Hanzo в Discord привет", "привет"),
            ("Can you message Hanzo on Discord hello", "hello"),
            ("Scrie-i lui Hanzo în Discord salut", "salut"),
        )
        for phrase, message in examples:
            with self.subTest(phrase=phrase):
                self.assert_complete_request(phrase, "Hanzo", message)

    def test_english_discord_message_label_after_recipient_is_instruction(self):
        phrase = "Send Hanzo a Discord message: hello"
        self.assert_complete_request(phrase, "Hanzo", "hello")
        self.assertIsNotNone(macro_planner.validate_generated_macro(send_proposal("Hanzo", "hello"), phrase))

    def test_english_discord_message_label_before_recipient_is_instruction(self):
        phrase = "Send a Discord message to Hanzo: hello"
        self.assert_complete_request(phrase, "Hanzo", "hello")
        self.assertIsNotNone(macro_planner.validate_generated_macro(send_proposal("Hanzo", "hello"), phrase))

    def test_quoted_message_and_multiword_name_are_preserved_exactly(self):
        self.assert_complete_request(
            "Напиши в Discord пользователю Старый Бог сообщение «Привет, как дела?»",
            "Старый Бог", "Привет, как дела?",
        )

    def test_detailed_workflow_and_short_request_have_the_same_atomic_intent(self):
        self.assert_complete_request(DETAILED_REQUEST, "Hanzo", "привет")
        self.assertEqual(
            macro_planner.detect_discord_text_request(DETAILED_REQUEST),
            macro_planner.detect_discord_text_request(SPOKEN_REQUEST),
        )

    def test_unspecified_friend_requires_a_recipient(self):
        phrase = "Напиши другу в Discord сообщение «привет»"
        self.assertTrue(macro_planner.is_discord_message_request(phrase))
        details = macro_planner.discord_message_details(phrase)
        self.assertIsNotNone(details)
        self.assertEqual(details["recipient"], "")
        self.assertEqual(details["message"], "привет")
        self.assertEqual(details["missing"], ["recipient"])
        self.assertFalse(details["cancelled"])
        self.assertIsNone(macro_planner.detect_discord_text_request(phrase))

    def test_named_recipient_without_content_requires_a_message(self):
        for phrase in (
            "Напиши в Discord пользователю Hanzo",
            "Напиши Hanzo в Discord",
        ):
            with self.subTest(phrase=phrase):
                self.assertTrue(macro_planner.is_discord_message_request(phrase))
                details = macro_planner.discord_message_details(phrase)
                self.assertIsNotNone(details)
                self.assertEqual(details["recipient"], "Hanzo")
                self.assertEqual(details["message"], "")
                self.assertEqual(details["missing"], ["message"])
                self.assertFalse(details["cancelled"])
                self.assertIsNone(macro_planner.detect_discord_text_request(phrase))

    def test_how_to_and_reading_requests_are_not_send_commands(self):
        phrases = (
            "Как написать пользователю Hanzo в Discord сообщение «привет»?",
            "How can I send Hanzo a message on Discord?",
            "Прочитай сообщение пользователя Hanzo в Discord",
            "Read Hanzo's message on Discord",
        )
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                self.assertFalse(macro_planner.is_discord_message_request(phrase))
                self.assertIsNone(macro_planner.discord_message_details(phrase))
                self.assertIsNone(macro_planner.detect_discord_text_request(phrase))

    def test_negated_send_is_cancelled(self):
        phrase = "Не пиши Hanzo в Discord привет"
        details = macro_planner.discord_message_details(phrase)
        self.assertIsNotNone(details)
        self.assertTrue(details["cancelled"])
        self.assertIsNone(macro_planner.detect_discord_text_request(phrase))

    def test_negation_inside_quoted_message_is_literal_content(self):
        self.assert_complete_request(
            "Напиши в Discord пользователю Hanzo сообщение «не пиши сюда»",
            "Hanzo", "не пиши сюда",
        )

    def test_workflow_words_inside_literal_message_do_not_change_the_action(self):
        phrase = "Открой Discord и напиши пользователю Hanzo сообщение «Выключи микрофон и найди информацию про Марс»"
        literal = "Выключи микрофон и найди информацию про Марс"
        self.assert_complete_request(phrase, "Hanzo", literal)
        plan = macro_planner.validate_generated_macro(send_proposal("Hanzo", literal), phrase)
        self.assertIsNotNone(plan)
        self.assertEqual(plan["steps"][0]["action"], "discord_send_text")

    def test_unquoted_message_keeps_its_discord_mention(self):
        phrase = "Напиши Hanzo в Discord: выключи микрофон в Discord"
        self.assert_complete_request(phrase, "Hanzo", "выключи микрофон в Discord")

    def test_enter_to_send_tail_is_an_instruction_not_message_content(self):
        phrase = "Зайти в дискорд и напиши пользователю старый бог привет и нажми enter чтобы отправить."
        self.assert_complete_request(phrase, "старый бог", "привет")
        self.assertIsNotNone(macro_planner.validate_generated_macro(send_proposal("старый бог", "привет"), phrase))

    def test_discord_and_send_words_only_inside_read_message_are_not_authority(self):
        for phrase in (
            "Прочитай сообщение пользователя Hanzo в Discord «напиши привет»",
            "Напиши пользователю Hanzo в Telegram сообщение «Discord привет»",
        ):
            with self.subTest(phrase=phrase):
                self.assertFalse(macro_planner.is_discord_message_request(phrase))
                self.assertIsNone(macro_planner.detect_discord_text_request(phrase))

    def test_extra_action_after_quoted_body_cannot_be_silently_discarded(self):
        phrase = "Напиши в Discord пользователю Hanzo «привет» потом закрой приложение"
        self.assertTrue(macro_planner.is_discord_message_request(phrase))
        self.assertIsNone(macro_planner.detect_discord_text_request(phrase))
        self.assertIsNone(macro_planner.validate_generated_macro(send_proposal(), phrase))


class DiscordSendProposalValidationTests(unittest.TestCase):
    def test_locally_parsed_atomic_send_is_accepted(self):
        for phrase in (SPOKEN_REQUEST, DETAILED_REQUEST):
            with self.subTest(phrase=phrase):
                result = macro_planner.validate_generated_macro(send_proposal(), phrase)
                self.assertIsNotNone(result)
                self.assertEqual(len(result["steps"]), 1)
                self.assertEqual(result["steps"][0]["action"], "discord_send_text")
                self.assertEqual(result["steps"][0]["target"], "Hanzo||привет")

    def test_model_cannot_invent_or_shorten_recipient_and_message(self):
        for recipient, message in (
            ("someoneelse", "привет"),
            ("Han", "привет"),
            ("Hanzo", "пока"),
            ("Hanzo", "при"),
        ):
            with self.subTest(recipient=recipient, message=message):
                self.assertIsNone(macro_planner.validate_generated_macro(
                    send_proposal(recipient, message), SPOKEN_REQUEST,
                ))

    def test_quoted_literal_negation_still_authorizes_exact_message(self):
        result = macro_planner.validate_generated_macro(
            send_proposal("Hanzo", "не пиши сюда"),
            "Напиши в Discord пользователю Hanzo сообщение «не пиши сюда»",
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["steps"][0]["target"], "Hanzo||не пиши сюда")

    def test_send_cannot_degrade_to_partial_or_blind_keyboard_steps(self):
        proposals = (
            {"steps": [{"action": "open_app", "target": "discord"}]},
            {"steps": [
                {"action": "open_app", "target": "discord"},
                {"action": "type_text", "target": "привет"},
                {"action": "press_enter"},
            ]},
            {"steps": [
                {"action": "discord_send_text", "target": "Hanzo||привет"},
                {"action": "press_enter"},
            ]},
        )
        for proposal in proposals:
            with self.subTest(proposal=proposal):
                self.assertIsNone(macro_planner.validate_generated_macro(
                    proposal, SPOKEN_REQUEST,
                ))

    def test_missing_cancelled_and_informational_requests_cannot_authorize_send(self):
        phrases = (
            "Напиши другу в Discord сообщение «привет»",
            "Напиши в Discord пользователю Hanzo",
            "Не пиши Hanzo в Discord привет",
            "Как написать пользователю Hanzo в Discord сообщение «привет»?",
            "Прочитай сообщение пользователя Hanzo в Discord",
        )
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                self.assertIsNone(macro_planner.validate_generated_macro(
                    send_proposal(), phrase,
                ))


class DiscordShortMicrophoneIntentTests(unittest.TestCase):
    def test_mic_explanations_and_negative_requests_never_toggle(self):
        for phrase in (
            "Как выключить микрофон в Discord?",
            "How can I turn off Discord microphone?",
            "Cum pot opri microfonul în Discord?",
            "Не закрывай микрофон в Discord",
            "Don't turn off the microphone in Discord",
            "Nu opri microfonul în Discord",
        ):
            with self.subTest(phrase=phrase):
                self.assertIsNone(discord_mic_visual_mode(phrase))
                self.assertFalse(wants_discord_mic_mute(phrase))

    def test_literal_message_about_a_microphone_does_not_toggle_my_microphone(self):
        for phrase in (
            "А ты можешь написать в Discord пользователю Hanzo «закрой микрофон»",
            "Can you write Hanzo on Discord 'mute the microphone'",
            "Scrie-i lui Hanzo în Discord «oprește microfonul»",
        ):
            with self.subTest(phrase=phrase):
                self.assertTrue(macro_planner.is_discord_message_request(phrase))
                self.assertIsNone(discord_mic_visual_mode(phrase))
                self.assertFalse(wants_discord_mic_mute(phrase))

    def test_close_microphone_means_verified_mute(self):
        phrase = "Закрой микрофон в дискорде"
        self.assertEqual(discord_mic_visual_mode(phrase), "mute")
        self.assertTrue(wants_discord_mic_visual_click(phrase))
        self.assertFalse(wants_discord_mic_mute(phrase))

    def test_english_and_romanian_desired_states_use_visual_verification(self):
        examples = (
            ("Mute my microphone in Discord", "mute"),
            ("Unmute my microphone in Discord", "unmute"),
            ("Oprește microfonul în Discord", "mute"),
            ("Pornește microfonul în Discord", "unmute"),
        )
        for phrase, mode in examples:
            with self.subTest(phrase=phrase):
                self.assertEqual(discord_mic_visual_mode(phrase), mode)
                self.assertTrue(wants_discord_mic_visual_click(phrase))
                self.assertFalse(wants_discord_mic_mute(phrase))


if __name__ == "__main__":
    unittest.main()
