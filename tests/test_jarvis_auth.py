from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
import sqlite3

from jarvis_auth import (
    AuthStore,
    AuthenticationError,
    LocalChatStore,
    SupabaseAuthStore,
    normalize_gender,
    normalize_login_username,
    normalize_spoken_username,
    username_from_spelling,
)

TEST_PIN = "1234"


class UsernameNormalizationTests(unittest.TestCase):
    def test_spoken_names_and_spelled_letters_are_normalized(self):
        self.assertEqual(normalize_spoken_username("  my name is SUNRIT "), "SUNRIT")
        self.assertEqual(normalize_spoken_username("S. U. N. R. I. T."), "sunrit")
        self.assertEqual(normalize_spoken_username("s-u-n-r-i-t"), "sunrit")
        self.assertEqual(normalize_spoken_username("jay oh aitch en"), "john")
        self.assertEqual(normalize_spoken_username("double you eye el el"), "will")
        self.assertEqual(normalize_spoken_username("admin").casefold(), "admin")
        self.assertEqual(normalize_login_username("A D M I N"), "Sunrit")
        self.assertEqual(normalize_login_username("s u n r i t").casefold(), "sunrit")
        self.assertEqual(normalize_gender("I am a woman"), "female")
        self.assertEqual(normalize_gender("non-binary"), "non_binary")
        self.assertEqual(normalize_gender("prefer not to say"), "prefer_not_to_say")

    def test_spelling_is_authoritative_and_preserves_a_matching_display_name(self):
        self.assertEqual(
            username_from_spelling("sunrit", "S U N R I T"),
            "sunrit",
        )
        self.assertEqual(
            username_from_spelling("jon", "J O H N"),
            "John",
        )
        with self.assertRaisesRegex(AuthenticationError, "spell"):
            username_from_spelling("Alex", "")


class AuthStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = AuthStore(Path(self.temp_dir.name) / "users.sqlite3")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_bootstrap_and_authenticate_admin(self):
        self.assertFalse(self.store.has_admin())
        admin = self.store.bootstrap_admin(TEST_PIN)
        self.assertEqual(admin["username"], "Sunrit")
        self.assertEqual(self.store.authenticate("sunrit", TEST_PIN)["role"], "admin")
        self.assertTrue(self.store.has_admin())

    def test_invalid_pins_and_duplicate_bootstrap_are_rejected(self):
        with self.assertRaises(AuthenticationError):
            self.store.bootstrap_admin("91")
        self.store.bootstrap_admin(TEST_PIN)
        with self.assertRaises(AuthenticationError):
            self.store.bootstrap_admin(TEST_PIN)
        with self.assertRaises(AuthenticationError):
            self.store.authenticate("Sunrit", "1111")

    def test_pin_is_stored_as_a_hash_and_attempts_are_rate_limited(self):
        self.store.bootstrap_admin(TEST_PIN)
        with closing(sqlite3.connect(self.store.path)) as connection:
            salt, pin_hash = connection.execute(
                "SELECT pin_salt, pin_hash FROM users WHERE role = 'admin'"
            ).fetchone()
        self.assertEqual(len(salt), 16)
        self.assertEqual(len(pin_hash), 32)
        self.assertNotIn(TEST_PIN.encode(), pin_hash)
        for _ in range(5):
            with self.assertRaises(AuthenticationError):
                self.store.authenticate("Sunrit", "1111")
        with self.assertRaisesRegex(AuthenticationError, "Too many attempts"):
            self.store.authenticate("Sunrit", TEST_PIN)

    def test_regular_user_cannot_manage_accounts_or_take_admin_role(self):
        admin = self.store.bootstrap_admin(TEST_PIN)
        user = self.store.add_user(admin["id"], "Alex", "1234")
        with self.assertRaises(AuthenticationError):
            self.store.authenticate("Alex", "1234", require_admin=True)
        with self.assertRaises(AuthenticationError):
            self.store.add_user(user["id"], "Casey", "5678")
        with self.assertRaises(AuthenticationError):
            self.store.disable_user(user["id"], user["id"])

    def test_new_user_gender_is_saved_and_username_lookup_ignores_case(self):
        admin = self.store.bootstrap_admin(TEST_PIN)
        user = self.store.add_user(admin["id"], "Alex", "1234", gender="female")
        self.assertEqual(user["gender"], "female")
        self.assertEqual(self.store.authenticate("aLeX", "1234")["id"], user["id"])

    def test_user_disable_enable_and_permanent_delete_are_distinct(self):
        admin = self.store.bootstrap_admin(TEST_PIN)
        user = self.store.add_user(admin["id"], "Alex", TEST_PIN)
        self.store.disable_user(admin["id"], user["id"])
        self.assertEqual(self.store.get_user(user["id"])["active"], False)
        self.store.enable_user(admin["id"], user["id"])
        self.assertEqual(self.store.get_user(user["id"])["active"], True)
        self.store.delete_user(admin["id"], user["id"])
        self.assertIsNone(self.store.get_user(user["id"]))
        self.assertEqual(
            [event["action"] for event in self.store.list_user_events()],
            ["deleted", "enabled", "disabled"],
        )

    def test_disabling_user_preserves_history_and_blocks_login(self):
        admin = self.store.bootstrap_admin(TEST_PIN)
        user = self.store.add_user(admin["id"], "Alex", "1234")
        session_id = self.store.start_session(user["id"])
        self.store.save_message(user["id"], session_id, "one", "user", "Private question")
        self.store.disable_user(admin["id"], user["id"])
        self.assertEqual(self.store.recent_messages(user["id"])[0]["text"], "Private question")
        with self.assertRaises(AuthenticationError):
            self.store.authenticate("Alex", "1234")
        with self.assertRaises(AuthenticationError):
            self.store.disable_user(admin["id"], admin["id"])

    def test_message_updates_and_memories_are_account_scoped(self):
        admin = self.store.bootstrap_admin(TEST_PIN)
        first = self.store.add_user(admin["id"], "Alex", "1234")
        second = self.store.add_user(admin["id"], "Casey", "5678")
        first_session = self.store.start_session(first["id"])
        second_session = self.store.start_session(second["id"])
        self.store.save_message(first["id"], first_session, "stream", "assistant", "Hello")
        self.store.save_message(first["id"], first_session, "stream", "assistant", "Hello there")
        self.assertEqual(self.store.recent_messages(first["id"])[0]["text"], "Hello there")
        self.assertEqual(self.store.recent_messages(second["id"]), [])
        self.store.save_profile(first["id"], True, '[{"role":"user","content":"remember"}]')
        self.assertEqual(
            self.store.load_profile(first["id"]),
            (True, '[{"role":"user","content":"remember"}]'),
        )
        self.assertEqual(self.store.load_profile(second["id"]), (False, "[]"))

    def test_gender_is_persisted_per_user(self):
        admin = self.store.bootstrap_admin(TEST_PIN)
        self.assertIsNone(admin["gender"])
        self.store.set_gender(admin["id"], "female")
        self.assertEqual(self.store.get_user(admin["id"])["gender"], "female")
        with self.assertRaises(AuthenticationError):
            self.store.set_gender(admin["id"], "invalid")

    def test_discussions_are_isolated_and_can_be_reopened(self):
        admin = self.store.bootstrap_admin(TEST_PIN)
        first = self.store.start_session(admin["id"])
        self.store.save_message(admin["id"], first, "first", "user", "First topic")
        second = self.store.start_session(admin["id"])
        self.store.save_message(admin["id"], second, "second", "user", "Second topic")

        self.assertEqual(
            [item["title"] for item in self.store.list_conversations(admin["id"])],
            ["Second topic", "First topic"],
        )
        self.assertEqual(
            self.store.recent_messages(admin["id"], session_id=first)[0]["text"],
            "First topic",
        )
        self.store.activate_session(admin["id"], first)
        self.assertTrue(self.store.list_conversations(admin["id"])[1]["active"])
        with self.assertRaises(AuthenticationError):
            self.store.activate_session(admin["id"], 9999)


class LocalChatStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "private.sqlite3"
        self.store = LocalChatStore(self.path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_private_history_persists_and_is_isolated_by_user(self):
        session_id = self.store.start_session(1)
        self.store.save_message(1, session_id, "one", "user", "Private question")
        restored_store = LocalChatStore(self.path)
        self.assertEqual(
            restored_store.recent_messages(1, session_id=session_id)[0]["text"],
            "Private question",
        )
        self.assertEqual(restored_store.list_conversations(2), [])

    def test_private_history_can_be_archived_restored_and_permanently_deleted(self):
        first = self.store.start_session(1)
        second = self.store.start_session(1)
        self.store.save_message(1, first, "first", "user", "First topic")
        self.store.archive_all_conversations(1)
        self.assertEqual(self.store.list_conversations(1), [])
        self.assertEqual(len(self.store.list_conversations(1, archived=True)), 2)

        self.store.set_conversation_archived(1, first, False)
        self.assertEqual(self.store.list_conversations(1)[0]["id"], f"private:{first}")
        self.store.delete_all_conversations(1)
        self.assertEqual(self.store.list_conversations(1), [])
        self.assertEqual(self.store.recent_messages(1), [])


class SupabaseAuthStoreTests(unittest.TestCase):
    def test_cloud_store_requires_https_and_server_credentials(self):
        with self.assertRaisesRegex(RuntimeError, "SUPABASE_URL"):
            SupabaseAuthStore(url="", service_role_key="")
        with self.assertRaisesRegex(RuntimeError, "HTTPS"):
            SupabaseAuthStore(url="http://example.test", service_role_key="secret")

    def test_cloud_user_maps_only_public_profile_fields(self):
        user = SupabaseAuthStore._user({
            "id": 5,
            "username": "Alex",
            "role": "user",
            "active": True,
            "memory_enabled": False,
            "gender": "non_binary",
            "pin_salt": "\\x1234",
            "pin_hash": "\\xabcd",
        })
        self.assertEqual(user, {
            "id": 5,
            "username": "Alex",
            "role": "user",
            "active": True,
            "memory_enabled": False,
            "gender": "non_binary",
        })

    def test_cloud_requests_use_server_bearer_credentials(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b"[]"
        response.headers = {}
        store = SupabaseAuthStore(
            url="https://example.supabase.co",
            service_role_key="server-secret",
        )

        with patch("jarvis_auth.urlopen", return_value=response) as urlopen:
            store._request("GET", "jarvis_users")

        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer server-secret")
        self.assertEqual(request.get_header("Apikey"), "server-secret")

    def test_permanent_cloud_deletion_removes_messages_sessions_and_memory(self):
        store = SupabaseAuthStore(
            url="https://example.supabase.co",
            service_role_key="server-secret",
        )
        with patch.object(store, "_request") as request:
            store.delete_all_conversations(5)

        self.assertEqual([call.args[:2] for call in request.call_args_list], [
            ("DELETE", "jarvis_messages"),
            ("DELETE", "jarvis_sessions"),
            ("PATCH", "jarvis_users"),
        ])
        self.assertEqual(request.call_args_list[-1].args[3], {
            "memory_enabled": False,
            "memory_json": [],
        })

    def test_cloud_account_actions_check_audit_table_before_mutating(self):
        store = SupabaseAuthStore(
            url="https://example.supabase.co",
            service_role_key="server-secret",
        )
        for action, target_active in (
            (store.disable_user, True),
            (store.enable_user, False),
            (store.delete_user, True),
        ):
            with self.subTest(action=action.__name__):
                admin = {"id": 1, "role": "admin", "active": True}
                target = {
                    "id": 2,
                    "role": "user",
                    "active": target_active,
                    "username": "Alex",
                }
                with (
                    patch.object(store, "get_user", side_effect=[admin, target]),
                    patch.object(
                        store,
                        "list_user_events",
                        side_effect=RuntimeError("audit table missing"),
                    ),
                    patch.object(store, "_request") as request,
                ):
                    with self.assertRaisesRegex(RuntimeError, "audit table missing"):
                        action(1, 2)
                    request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
