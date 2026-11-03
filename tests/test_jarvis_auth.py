from contextlib import closing
import tempfile
import unittest
from pathlib import Path
import sqlite3

from jarvis_auth import AuthStore, AuthenticationError

TEST_PIN = "1234"


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


if __name__ == "__main__":
    unittest.main()
