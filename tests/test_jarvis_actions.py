import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import jarvis_pc
import jarvis_screen
import jarvis_services
import jarvis_whatsapp
from jarvis_action_policy import (
    describe_action,
    is_approval_text,
    is_cancel_text,
    is_danger_confirmation_text,
    is_destructive,
    is_sensitive,
    requires_approval,
    requires_screen_confirmation,
    shell_command_is_destructive,
)


class ActionPolicyTests(unittest.TestCase):
    def test_sensitive_and_approval_actions(self):
        self.assertTrue(requires_approval({"do": "whatsapp"}))
        self.assertTrue(requires_approval({"do": "email", "action": "send"}))
        self.assertFalse(requires_approval({"do": "email", "action": "draft"}))
        self.assertFalse(requires_approval({"do": "open", "target": "chrome"}))

    def test_destructive_commands_are_flagged(self):
        self.assertTrue(shell_command_is_destructive("Remove-Item C:\\Temp -Recurse -Force"))
        self.assertTrue(shell_command_is_destructive("format d: /q"))
        self.assertTrue(shell_command_is_destructive("shutdown /s /t 0"))
        self.assertFalse(shell_command_is_destructive("ipconfig"))
        self.assertFalse(shell_command_is_destructive("Get-ChildItem C:\\Users"))
        self.assertTrue(is_destructive({"do": "system", "action": "shutdown"}))
        self.assertFalse(is_destructive({"do": "system", "action": "lock"}))

    def test_approval_and_cancel_language(self):
        for text in ("yes", "send it", "approve", "go ahead", "do it"):
            self.assertTrue(is_approval_text(text), text)
        for text in ("no", "cancel", "stop", "never mind", "not now"):
            self.assertTrue(is_cancel_text(text), text)
        self.assertFalse(is_cancel_text("send it"))
        self.assertTrue(is_danger_confirmation_text("confirm dangerous"))
        self.assertFalse(is_danger_confirmation_text("yes"))

    def test_action_descriptions(self):
        self.assertIn("search for weather", describe_action({"do": "search", "query": "weather"}))
        self.assertIn("send an email to Alex", describe_action({"do": "email", "action": "send", "to": "Alex"}))
        self.assertIn("WhatsApp", describe_action({"do": "whatsapp", "to": "Mom"}))
        self.assertIn("read the file notes.txt", describe_action({"do": "file", "action": "read", "target": "notes.txt"}))
        self.assertIn("WhatsApp", describe_action({"do": "message", "app": "whatsapp", "action": "read"}))
        self.assertIn("act on your screen", describe_action({"do": "screen", "action": "act", "instruction": "click Send"}))

    def test_message_and_screen_policy(self):
        self.assertTrue(is_sensitive({"do": "message", "app": "whatsapp", "action": "read"}))
        self.assertTrue(is_sensitive({"do": "screen", "action": "look"}))
        self.assertFalse(is_sensitive({"do": "maximize"}))
        self.assertTrue(
            requires_approval(
                {"do": "message", "app": "whatsapp", "action": "reply", "to": "Srija"}
            )
        )
        self.assertTrue(
            requires_approval(
                {"do": "message", "app": "gmail", "action": "reply", "to": "Alex"}
            )
        )
        self.assertFalse(
            requires_approval({"do": "message", "app": "whatsapp", "action": "read"})
        )
        self.assertTrue(
            requires_screen_confirmation({"do": "screen", "action": "act"})
        )
        self.assertFalse(
            requires_screen_confirmation({"do": "screen", "action": "look"})
        )


class WhatsAppParsingTests(unittest.TestCase):
    def test_unread_prefix_and_preview(self):
        chat = jarvis_whatsapp.parse_chat_item(
            "3 unread messages EatSure Yesterday ₹101 has been credited to your wallet"
        )
        self.assertEqual(chat["name"], "EatSure")
        self.assertEqual(chat["unread"], 3)
        self.assertTrue(chat["preview"].startswith("₹101"))

    def test_unread_in_the_middle(self):
        chat = jarvis_whatsapp.parse_chat_item(
            "BLA Aikyataan 2027-28 Yesterday 2,113 unread messages "
            "BLA INFORMAL ~Souradeep Nayak : Guys, cab anyone?"
        )
        self.assertEqual(chat["name"], "BLA Aikyataan 2027-28")
        self.assertEqual(chat["unread"], 2113)
        self.assertTrue(chat["preview"].startswith("BLA INFORMAL"))

    def test_single_unread_and_read_chat(self):
        chat = jarvis_whatsapp.parse_chat_item(
            "1 unread message Aashika (Srija Roommate) Yesterday Yes yes"
        )
        self.assertEqual(chat["name"], "Aashika (Srija Roommate)")
        self.assertEqual(chat["unread"], 1)
        self.assertEqual(chat["preview"], "Yes yes")

        read_chat = jarvis_whatsapp.parse_chat_item(
            "+91 85849 10737 (You) Wednesday Photo Pinned chat"
        )
        self.assertEqual(read_chat["unread"], 0)
        self.assertEqual(read_chat["name"], "+91 85849 10737 (You)")
        self.assertEqual(read_chat["preview"], "Photo")
        self.assertTrue(read_chat["pinned"])

    def test_unread_format_asks_about_replies(self):
        text = jarvis_whatsapp.format_unread_chats(
            {
                "chats": [
                    {"name": "Srija", "unread": 2, "preview": "Call me"},
                ],
                "count": 1,
                "unread_total": 2,
            }
        )
        self.assertIn("Srija", text)
        self.assertIn("2 unread", text)
        self.assertIn("draft a reply", text)
        self.assertIn("no unread", jarvis_whatsapp.format_unread_chats({}).lower())


class ScreenPlanTests(unittest.TestCase):
    def test_plan_coordinates_are_scaled(self):
        plan = jarvis_screen.normalize_plan(
            {
                "summary": "Click then type",
                "actions": [
                    {"type": "click", "x": 500, "y": 500, "description": "click field"},
                    {"type": "type", "text": "hello"},
                ],
            },
            1000,
            500,
        )
        self.assertEqual(plan["actions"][0]["x"], 500)
        self.assertEqual(plan["actions"][0]["y"], 250)
        self.assertEqual(plan["actions"][1]["text"], "hello")
        self.assertTrue(plan["summary"])

    def test_plan_rejects_bad_values(self):
        with self.assertRaises(jarvis_screen.ActionError):
            jarvis_screen.normalize_plan(
                {"actions": [{"type": "click", "x": 1200, "y": 10}]}
            )
        with self.assertRaises(jarvis_screen.ActionError):
            jarvis_screen.normalize_plan(
                {"actions": [{"type": "launch_missiles"}]}
            )
        with self.assertRaises(jarvis_screen.ActionError):
            jarvis_screen.normalize_plan(
                {"actions": [{"type": "wait"}] * (jarvis_screen.MAX_STEPS + 1)}
            )

    def test_plan_description_lists_steps(self):
        described = jarvis_screen.describe_plan(
            {
                "summary": "Open settings",
                "actions": [
                    {"type": "click", "description": "click the gear"},
                    {"type": "press", "description": "press Enter"},
                ],
            }
        )
        self.assertIn("Open settings", described)
        self.assertIn("click the gear", described)
        self.assertIn("press Enter", described)


class PcHelperTests(unittest.TestCase):
    def test_url_detection(self):
        self.assertTrue(jarvis_pc.looks_like_url("https://example.com"))
        self.assertTrue(jarvis_pc.looks_like_url("example.com/path"))
        self.assertTrue(jarvis_pc.looks_like_url("localhost:3000"))
        self.assertFalse(jarvis_pc.looks_like_url("open chrome"))
        self.assertFalse(jarvis_pc.looks_like_url("tax return.pdf"))

    def test_normalize_url_adds_scheme_and_rejects_javascript(self):
        self.assertEqual(jarvis_pc.normalize_url("example.com"), "https://example.com")
        with self.assertRaises(jarvis_pc.ActionError):
            jarvis_pc.normalize_url("javascript:alert(1)")

    def test_resolve_path_finds_file_in_common_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "quarterly report.pdf"
            target.write_text("data", encoding="utf-8")
            with patch.object(jarvis_pc, "_common_dirs", return_value=[Path(temp_dir)]):
                found = jarvis_pc.resolve_path("quarterly report.pdf")
            self.assertEqual(found, target.resolve())

    def test_search_and_shell_formatting(self):
        outcome = {
            "query": "weather",
            "results": [
                {"title": "Sunny", "snippet": "It will be sunny.", "url": "https://example.com"},
            ],
        }
        self.assertIn("1. Sunny", jarvis_pc.format_search_results(outcome))
        self.assertIn("sunny", jarvis_pc.summarize_search_results(outcome).lower())
        result = {"returncode": 0, "stdout": "Windows IP Configuration", "stderr": ""}
        self.assertIn("Windows IP", jarvis_pc.format_shell_result(result))
        failed = {"returncode": 1, "stdout": "", "stderr": "bad command"}
        self.assertIn("exited with code 1", jarvis_pc.format_shell_result(failed))

    def test_file_read_write_list_and_find(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            target = folder / "notes.txt"
            jarvis_pc.write_file(str(target), "first line\n")
            jarvis_pc.write_file(str(target), "second line\n", append=True)
            contents = jarvis_pc.read_file(str(target))
            self.assertIn("first line", contents)
            self.assertIn("second line", contents)

            listing = jarvis_pc.list_directory(str(folder))
            self.assertIn("notes.txt", listing)

            other = folder / "quarterly report.pdf"
            other.write_text("data", encoding="utf-8")
            with patch.object(jarvis_pc, "_common_dirs", return_value=[folder]):
                found = jarvis_pc.find_files("quarterly")
            self.assertIn("quarterly report.pdf", found)

    def test_write_path_resolves_common_folder_names(self):
        resolved = jarvis_pc.resolve_write_path("Desktop/jarvis-notes.txt")
        self.assertEqual(resolved, jarvis_pc.HOME / "Desktop" / "jarvis-notes.txt")


class ServiceHelperTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.contacts = Path(self.temp_dir.name) / "contacts.json"
        self.contacts.write_text(
            json.dumps(
                {
                    "Mom": {"email": "mom@example.com", "phone": "+919876543210"},
                    "Alex": {"email": "alex@example.com"},
                }
            ),
            encoding="utf-8",
        )
        self.patch = patch.object(jarvis_services, "CONTACTS_FILE", self.contacts)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp_dir.cleanup()

    def test_contacts_resolve_by_name(self):
        self.assertEqual(jarvis_services.resolve_email("mom"), "mom@example.com")
        self.assertEqual(jarvis_services.resolve_phone("MOM"), "+919876543210")
        with self.assertRaises(jarvis_services.ActionError):
            jarvis_services.resolve_phone("Alex")

    def test_email_draft_validation(self):
        draft = jarvis_services.build_email_draft("Mom", "Dinner", "I'll be late.")
        self.assertEqual(draft["to"], "mom@example.com")
        self.assertEqual(draft["subject"], "Dinner")
        with self.assertRaises(jarvis_services.ActionError):
            jarvis_services.build_email_draft("not-an-email", "Hi", "Body")
        with self.assertRaises(jarvis_services.ActionError):
            jarvis_services.build_email_draft("Mom", "Hi", "   ")

    def test_email_to_me_uses_configured_sender(self):
        with patch.dict(
            "os.environ",
            {"JARVIS_EMAIL_FROM": "owner@example.com"},
            clear=False,
        ):
            self.assertEqual(jarvis_services.resolve_email("me"), "owner@example.com")
        with patch.dict(
            "os.environ",
            {"JARVIS_EMAIL_FROM": "", "JARVIS_SMTP_USER": ""},
            clear=False,
        ):
            with self.assertRaises(jarvis_services.ActionError):
                jarvis_services.resolve_email("myself")

    def test_whatsapp_draft_uses_phone(self):
        draft = jarvis_services.build_whatsapp_draft("Mom", "On my way")
        self.assertEqual(draft["phone"], "+919876543210")
        self.assertEqual(draft["message"], "On my way")

    def test_calendar_datetime_parsing(self):
        parsed = jarvis_services.parse_datetime("2026-11-07T15:00:00")
        self.assertEqual(parsed.hour, 15)
        relative = jarvis_services.parse_datetime("tomorrow at 3pm")
        self.assertGreater(relative, datetime.now().astimezone())
        self.assertEqual(relative.hour, 15)

    def test_whatsapp_chat_draft_needs_no_phone(self):
        draft = jarvis_services.build_whatsapp_chat_draft("Srija", "On my way")
        self.assertEqual(draft["chat"], "Srija")
        self.assertEqual(draft["phone"], "")
        self.assertEqual(draft["kind"], "whatsapp")

    def test_unread_email_format(self):
        text = jarvis_services.format_unread_email(
            [
                {
                    "from": "Alex <alex@example.com>",
                    "subject": "Dinner",
                    "date": "today",
                    "snippet": "Are you free tonight?",
                }
            ]
        )
        self.assertIn("Alex", text)
        self.assertIn("Dinner", text)
        self.assertIn("reply", text.lower())
        self.assertIn(
            "no unread email",
            jarvis_services.format_unread_email([]).lower(),
        )


if __name__ == "__main__":
    unittest.main()
