import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


DEFAULT_ADMIN_NAME = "Sunrit"
PIN_PATTERN = re.compile(r"^\d{4,8}$")
PBKDF2_ITERATIONS = 240_000
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 60


class AuthenticationError(Exception):
    pass


class AuthStore:
    def __init__(self, path=None, admin_name=DEFAULT_ADMIN_NAME):
        self.path = str(path or Path(__file__).with_name("jarvis_users.sqlite3"))
        self.admin_name = admin_name
        self.initialize()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self):
        parent = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(parent, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    role TEXT NOT NULL CHECK (role IN ('admin', 'user')),
                    pin_salt BLOB NOT NULL,
                    pin_hash BLOB NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
                    failed_attempts INTEGER NOT NULL DEFAULT 0,
                    locked_until REAL NOT NULL DEFAULT 0,
                    memory_enabled INTEGER NOT NULL DEFAULT 0 CHECK (memory_enabled IN (0, 1)),
                    memory_json TEXT NOT NULL DEFAULT '[]',
                    gender TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    ended_at TEXT
                );
                CREATE INDEX IF NOT EXISTS sessions_user_id ON sessions(user_id, id);
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    session_id INTEGER NOT NULL REFERENCES sessions(id),
                    message_key TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(session_id, message_key)
                );
                CREATE INDEX IF NOT EXISTS messages_user_id ON messages(user_id, id);
                """
            )
            user_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(users)").fetchall()
            }
            if "gender" not in user_columns:
                connection.execute("ALTER TABLE users ADD COLUMN gender TEXT")

    @staticmethod
    def validate_pin(pin):
        if not isinstance(pin, str) or not PIN_PATTERN.fullmatch(pin):
            raise AuthenticationError("PIN must contain 4 to 8 digits.")

    @staticmethod
    def _derive_pin(pin, salt):
        return hashlib.pbkdf2_hmac(
            "sha256", pin.encode("utf-8"), salt, PBKDF2_ITERATIONS
        )

    @staticmethod
    def _user(row):
        if row is None:
            return None
        return {
            "id": row["id"],
            "username": row["username"],
            "role": row["role"],
            "active": bool(row["active"]),
            "memory_enabled": bool(row["memory_enabled"]),
            "gender": row["gender"],
        }

    def has_admin(self):
        with self._connect() as connection:
            return connection.execute(
                "SELECT 1 FROM users WHERE role = 'admin' LIMIT 1"
            ).fetchone() is not None

    def bootstrap_admin(self, pin):
        self.validate_pin(pin)
        salt = secrets.token_bytes(16)
        pin_hash = self._derive_pin(pin, salt)
        with self._connect() as connection:
            if connection.execute(
                "SELECT 1 FROM users WHERE role = 'admin' LIMIT 1"
            ).fetchone():
                raise AuthenticationError("The administrator account is already set up.")
            cursor = connection.execute(
                "INSERT INTO users (username, role, pin_salt, pin_hash) "
                "VALUES (?, 'admin', ?, ?)",
                (self.admin_name, salt, pin_hash),
            )
            return {
                "id": cursor.lastrowid,
                "username": self.admin_name,
                "role": "admin",
                "active": True,
                "memory_enabled": False,
                "gender": None,
            }

    def get_user(self, user_id):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, username, role, active, memory_enabled, gender FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            return self._user(row)

    def authenticate(self, username, pin, require_admin=False):
        name = username.strip() if isinstance(username, str) else ""
        if not name or not isinstance(pin, str):
            raise AuthenticationError("Enter a username and PIN.")

        failure = None
        user = None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE username = ? COLLATE NOCASE AND active = 1",
                (name,),
            ).fetchone()
            if row is None:
                failure = "Username or PIN is incorrect."
            elif row["locked_until"] > time.time():
                remaining = max(1, int(row["locked_until"] - time.time()))
                failure = f"Too many attempts. Try again in {remaining} seconds."
            elif not (
                PIN_PATTERN.fullmatch(pin)
                and hmac.compare_digest(
                    self._derive_pin(pin, row["pin_salt"]), row["pin_hash"]
                )
            ):
                failures = row["failed_attempts"] + 1
                locked_until = time.time() + LOCKOUT_SECONDS if failures >= MAX_FAILED_ATTEMPTS else 0
                connection.execute(
                    "UPDATE users SET failed_attempts = ?, locked_until = ? WHERE id = ?",
                    (0 if locked_until else failures, locked_until, row["id"]),
                )
                failure = (
                    f"Too many attempts. Sign-in is locked for {LOCKOUT_SECONDS} seconds."
                    if locked_until
                    else "Username or PIN is incorrect."
                )
            elif require_admin and row["role"] != "admin":
                failure = "Administrator PIN required."
            else:
                connection.execute(
                    "UPDATE users SET failed_attempts = 0, locked_until = 0 WHERE id = ?",
                    (row["id"],),
                )
                user = self._user(row)
        if failure:
            raise AuthenticationError(failure)
        return user

    def add_user(self, actor_id, username, pin):
        name = username.strip() if isinstance(username, str) else ""
        if not name or len(name) > 60:
            raise AuthenticationError("Enter a name between 1 and 60 characters.")
        if any(ord(char) < 32 for char in name):
            raise AuthenticationError("The username contains unsupported characters.")
        self.validate_pin(pin)

        salt = secrets.token_bytes(16)
        pin_hash = self._derive_pin(pin, salt)
        with self._connect() as connection:
            actor = connection.execute(
                "SELECT role, active FROM users WHERE id = ?", (actor_id,)
            ).fetchone()
            if actor is None or actor["role"] != "admin" or not actor["active"]:
                raise AuthenticationError("Only the signed-in administrator can add users.")
            try:
                cursor = connection.execute(
                    "INSERT INTO users (username, role, pin_salt, pin_hash) "
                    "VALUES (?, 'user', ?, ?)",
                    (name, salt, pin_hash),
                )
            except sqlite3.IntegrityError as error:
                raise AuthenticationError("That username is already in use.") from error
            row = connection.execute(
                "SELECT id, username, role, active, memory_enabled, gender FROM users WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
            return self._user(row)

    def disable_user(self, actor_id, target_id):
        with self._connect() as connection:
            actor = connection.execute(
                "SELECT role, active FROM users WHERE id = ?", (actor_id,)
            ).fetchone()
            if actor is None or actor["role"] != "admin" or not actor["active"]:
                raise AuthenticationError("Only the signed-in administrator can manage users.")
            target = connection.execute(
                "SELECT id, role, active FROM users WHERE id = ?", (target_id,)
            ).fetchone()
            if target is None or not target["active"]:
                raise AuthenticationError("That active user was not found.")
            if target["role"] == "admin":
                raise AuthenticationError("The administrator account cannot be disabled.")
            connection.execute(
                "UPDATE users SET active = 0 WHERE id = ?", (target_id,)
            )

    def list_users(self):
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, username, role, active, memory_enabled, gender "
                "FROM users WHERE active = 1 ORDER BY role DESC, username COLLATE NOCASE"
            ).fetchall()
            return [self._user(row) for row in rows]

    def set_gender(self, user_id, gender):
        if gender not in ("male", "female", "non_binary", "prefer_not_to_say"):
            raise AuthenticationError("Choose one of the available gender options.")
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE users SET gender = ? WHERE id = ? AND active = 1",
                (gender, user_id),
            )
            if cursor.rowcount != 1:
                raise AuthenticationError("This account is no longer active.")

    def start_session(self, user_id):
        with self._connect() as connection:
            connection.execute(
                "UPDATE sessions SET ended_at = CURRENT_TIMESTAMP "
                "WHERE user_id = ? AND ended_at IS NULL",
                (user_id,),
            )
            cursor = connection.execute(
                "INSERT INTO sessions (user_id) VALUES (?)", (user_id,)
            )
            return cursor.lastrowid

    def end_session(self, session_id):
        if session_id is None:
            return
        with self._connect() as connection:
            connection.execute(
                "UPDATE sessions SET ended_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND ended_at IS NULL",
                (session_id,),
            )

    def recent_messages(self, user_id, limit=80):
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT message_key, role, content FROM messages "
                "WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
            return [
                {
                    "id": row["message_key"],
                    "from": "you" if row["role"] == "user" else "jarvis",
                    "text": row["content"],
                }
                for row in reversed(rows)
            ]

    def save_message(self, user_id, session_id, key, role, content):
        if role not in ("user", "assistant"):
            raise ValueError(f"Unsupported conversation role: {role}")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO messages (user_id, session_id, message_key, role, content)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id, message_key) DO UPDATE SET
                    content = excluded.content,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, session_id, str(key), role, str(content)),
            )

    def load_profile(self, user_id):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT memory_enabled, memory_json FROM users WHERE id = ? AND active = 1",
                (user_id,),
            ).fetchone()
            if row is None:
                raise AuthenticationError("This account is no longer active.")
            return bool(row["memory_enabled"]), row["memory_json"]

    def save_profile(self, user_id, memory_enabled, memory_json):
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE users SET memory_enabled = ?, memory_json = ? "
                "WHERE id = ? AND active = 1",
                (bool(memory_enabled), memory_json, user_id),
            )
            if cursor.rowcount != 1:
                raise AuthenticationError("This account is no longer active.")
