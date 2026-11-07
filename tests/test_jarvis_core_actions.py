import unittest
from unittest.mock import patch

import jarvis_core


class PendingActionTests(unittest.TestCase):
    def setUp(self):
        self.original_user = jarvis_core.active_user
        jarvis_core.pending_action = None

    def tearDown(self):
        jarvis_core.pending_action = None
        jarvis_core.active_user = self.original_user

    def test_non_admin_search_keeps_speak_for_later(self):
        jarvis_core.active_user = {"id": 2, "username": "Guest", "role": "user"}
        note = jarvis_core.run_actions(
            [{"do": "search", "query": "weather", "open": False}],
            "text",
            speak=True,
        )
        self.assertIn("administrator approval", note)
        pending = jarvis_core.pending_action
        self.assertEqual(pending["stage"], "admin_pin")
        self.assertEqual(pending["actions"][0]["do"], "search")
        self.assertTrue(pending["speak"])

    def test_admin_email_waits_for_confirmation(self):
        jarvis_core.active_user = {"id": 1, "username": "Sunrit", "role": "admin"}
        note = jarvis_core.run_actions(
            [
                {
                    "do": "email",
                    "action": "send",
                    "to": "alex@example.com",
                    "subject": "Hi",
                    "body": "Hello there.",
                }
            ],
            "text",
        )
        self.assertIn("draft", note.lower())
        self.assertEqual(jarvis_core.pending_action["stage"], "confirm_send")
        self.assertEqual(
            jarvis_core.pending_action["draft"]["to"], "alex@example.com"
        )

    def test_destructive_shell_needs_extra_confirmation(self):
        jarvis_core.active_user = {"id": 1, "username": "Sunrit", "role": "admin"}
        note = jarvis_core.run_actions(
            [{"do": "shell", "command": "shutdown /s /t 0"}], "text"
        )
        self.assertIn("destructive", note.lower())
        self.assertEqual(jarvis_core.pending_action["stage"], "danger_confirm")

    def test_cancel_clears_pending(self):
        jarvis_core.active_user = {"id": 2, "username": "Guest", "role": "user"}
        jarvis_core.run_actions(
            [{"do": "search", "query": "weather", "open": False}], "text"
        )
        self.assertIsNotNone(jarvis_core.pending_action)
        jarvis_core.cancel_pending_action()
        self.assertIsNone(jarvis_core.pending_action)

    def test_non_admin_message_read_waits_for_admin_pin(self):
        jarvis_core.active_user = {"id": 2, "username": "Guest", "role": "user"}
        note = jarvis_core.run_actions(
            [{"do": "message", "app": "whatsapp", "action": "read"}], "text"
        )
        self.assertIn("administrator approval", note)
        self.assertEqual(jarvis_core.pending_action["stage"], "admin_pin")
        self.assertEqual(jarvis_core.pending_action["actions"][0]["do"], "message")

    def test_admin_screen_action_is_planned_before_it_runs(self):
        jarvis_core.active_user = {"id": 1, "username": "Sunrit", "role": "admin"}
        plan = {
            "summary": "Click OK",
            "actions": [{"type": "click", "x": 100, "y": 100}],
            "instruction": "click OK",
            "screenshot": "screen.png",
        }
        with patch.object(
            jarvis_core.jarvis_screen,
            "prepare_screen_action",
            return_value=plan,
        ):
            note = jarvis_core.run_actions(
                [{"do": "screen", "action": "act", "instruction": "click OK"}],
                "text",
            )
        self.assertIn("prepared", note)
        self.assertEqual(jarvis_core.pending_action["stage"], "confirm_screen")
        self.assertEqual(jarvis_core.pending_action["screen_plan"]["summary"], "Click OK")

        with patch.object(
            jarvis_core.jarvis_screen, "execute_plan", return_value="Done."
        ) as execute:
            jarvis_core.confirm_pending_action()
        execute.assert_called_once()
        self.assertIsNone(jarvis_core.pending_action)


class ComputerRequestTriggerTests(unittest.TestCase):
    def test_common_laptop_phrases_route_to_the_router(self):
        phrases = (
            "open my email",
            "open Gmail",
            "open the tax report.pdf",
            "send a WhatsApp to Mom saying I'm late",
            "send an email to Alex",
            "what's on my calendar today",
            "open Chrome and search the weather",
            "take a screenshot",
            "lock my laptop",
            "switch to the Chrome window",
            "do I have any new WhatsApp messages",
            "read my unread email",
            "reply to Srija saying I'll call later",
            "what's on my screen",
            "click the Compose button and type hello",
            "read the file notes.txt",
            "list my Downloads folder",
        )
        for phrase in phrases:
            self.assertTrue(jarvis_core.COMPUTER_REQUEST.search(phrase), phrase)

    def test_plain_conversation_does_not_trigger(self):
        for phrase in ("tell me a joke", "explain gravity", "how are you"):
            self.assertFalse(jarvis_core.COMPUTER_REQUEST.search(phrase), phrase)


if __name__ == "__main__":
    unittest.main()
