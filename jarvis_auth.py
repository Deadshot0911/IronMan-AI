import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_ADMIN_NAME = "Sunrit"
PIN_PATTERN = re.compile(r"^\d{4,8}$")
NAME_PREFIX_PATTERN = re.compile(
    r"^(?:(?:my name is|i am|i'm|this is|spell(?: out)?|the spelling is|"
    r"it's spelled|it is spelled)\s+)",
    re.IGNORECASE,
)
PBKDF2_ITERATIONS = 240_000
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 60


def normalize_spoken_username(value):
    if not isinstance(value, str):
        return ""
    name = " ".join(value.strip().split())
    name = NAME_PREFIX_PATTERN.sub("", name).strip()
    name = name.strip(" \t\r\n.,!?;:")
    tokens = re.findall(r"[^\W\d_]+", name.casefold(), flags=re.UNICODE)
    letter_names = {
        "ay": "a", "a": "a", "bee": "b", "be": "b", "b": "b",
        "see": "c", "sea": "c", "cee": "c", "c": "c", "dee": "d", "d": "d",
        "ee": "e", "e": "e", "ef": "f", "eff": "f", "f": "f",
        "gee": "g", "g": "g", "aitch": "h", "h": "h",
        "eye": "i", "i": "i", "jay": "j", "j": "j", "kay": "k", "k": "k",
        "el": "l", "ell": "l", "l": "l", "em": "m", "m": "m",
        "en": "n", "n": "n", "oh": "o", "o": "o", "pee": "p", "p": "p",
        "cue": "q", "queue": "q", "q": "q", "are": "r", "ar": "r", "r": "r",
        "ess": "s", "s": "s", "tee": "t", "t": "t", "you": "u", "u": "u",
        "vee": "v", "v": "v", "double": "", "w": "w", "ex": "x", "x": "x",
        "why": "y", "y": "y", "zee": "z", "zed": "z", "z": "z",
    }
    spelled_tokens = []
    index = 0
    while index < len(tokens):
        if tokens[index:index + 2] == ["double", "you"]:
            spelled_tokens.append("w")
            index += 2
        else:
            spelled_tokens.append(tokens[index])
            index += 1
    tokens = spelled_tokens
    if len(tokens) > 1 and all(token in letter_names for token in tokens):
        return "".join(letter_names[token] for token in tokens)
    return name


def normalize_login_username(value, admin_name=DEFAULT_ADMIN_NAME):
    username = normalize_spoken_username(value)
    if username.casefold() == "admin":
        return admin_name
    return username


def normalize_gender(value):
    normalized = normalize_spoken_username(value).casefold().replace("-", " ")
    normalized = re.sub(r"^(?:a|an)\s+", "", normalized)
    normalized = " ".join(normalized.split())
    choices = {
        "male": ("male", "man", "boy", "masculine", "he", "him"),
        "female": ("female", "woman", "girl", "feminine", "she", "her"),
        "non_binary": ("non binary", "nonbinary", "they", "them"),
        "prefer_not_to_say": (
            "prefer not to say",
            "rather not say",
            "skip",
            "no preference",
        ),
    }
    for gender, aliases in choices.items():
        if normalized == gender.replace("_", " ") or normalized in aliases:
            return gender
    raise AuthenticationError(
        "Choose male, female, non-binary, or prefer not to say."
    )


def username_from_spelling(name, spelling):
    initial_name = normalize_spoken_username(name)
    spelled_name = normalize_spoken_username(spelling)
    if not spelled_name:
        raise AuthenticationError("Please spell the new user's name.")

    def compact(value):
        return "".join(character for character in value.casefold() if character.isalnum())

    if initial_name and compact(initial_name) == compact(spelled_name):
        return initial_name
    return spelled_name.title()


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
                CREATE TABLE IF NOT EXISTS user_events (
                    id INTEGER PRIMARY KEY,
                    username TEXT NOT NULL,
                    action TEXT NOT NULL CHECK (action IN ('disabled', 'enabled', 'deleted')),
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

    def add_user(self, actor_id, username, pin, gender=None):
        name = username.strip() if isinstance(username, str) else ""
        if not name or len(name) > 60:
            raise AuthenticationError("Enter a name between 1 and 60 characters.")
        if any(ord(char) < 32 for char in name):
            raise AuthenticationError("The username contains unsupported characters.")
        if gender is not None and gender not in (
            "male",
            "female",
            "non_binary",
            "prefer_not_to_say",
        ):
            raise AuthenticationError("Choose one of the available gender options.")
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
                    "INSERT INTO users (username, role, pin_salt, pin_hash, gender) "
                    "VALUES (?, 'user', ?, ?, ?)",
                    (name, salt, pin_hash, gender),
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
                "SELECT id, username, role, active FROM users WHERE id = ?", (target_id,)
            ).fetchone()
            if target is None or not target["active"]:
                raise AuthenticationError("That active user was not found.")
            if target["role"] == "admin":
                raise AuthenticationError("The administrator account cannot be disabled.")
            connection.execute(
                "UPDATE users SET active = 0 WHERE id = ?", (target_id,)
            )
            connection.execute(
                "INSERT INTO user_events (username, action) VALUES (?, 'disabled')",
                (target["username"],),
            )

    def enable_user(self, actor_id, target_id):
        with self._connect() as connection:
            actor = connection.execute(
                "SELECT role, active FROM users WHERE id = ?", (actor_id,)
            ).fetchone()
            target = connection.execute(
                "SELECT id, username, role, active FROM users WHERE id = ?", (target_id,)
            ).fetchone()
            if actor is None or actor["role"] != "admin" or not actor["active"]:
                raise AuthenticationError("Only the signed-in administrator can manage users.")
            if target is None or target["role"] != "user":
                raise AuthenticationError("That user was not found.")
            if target["active"]:
                raise AuthenticationError("That user is already enabled.")
            connection.execute("UPDATE users SET active = 1 WHERE id = ?", (target_id,))
            connection.execute(
                "INSERT INTO user_events (username, action) VALUES (?, 'enabled')",
                (target["username"],),
            )

    def delete_user(self, actor_id, target_id):
        with self._connect() as connection:
            actor = connection.execute(
                "SELECT role, active FROM users WHERE id = ?", (actor_id,)
            ).fetchone()
            target = connection.execute(
                "SELECT id, username, role FROM users WHERE id = ?", (target_id,)
            ).fetchone()
            if actor is None or actor["role"] != "admin" or not actor["active"]:
                raise AuthenticationError("Only the signed-in administrator can manage users.")
            if target is None or target["role"] != "user":
                raise AuthenticationError("That user was not found.")
            connection.execute(
                "INSERT INTO user_events (username, action) VALUES (?, 'deleted')",
                (target["username"],),
            )
            connection.execute("DELETE FROM messages WHERE user_id = ?", (target_id,))
            connection.execute("DELETE FROM sessions WHERE user_id = ?", (target_id,))
            connection.execute("DELETE FROM users WHERE id = ?", (target_id,))

    def list_users(self):
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, username, role, active, memory_enabled, gender "
                "FROM users ORDER BY role DESC, username COLLATE NOCASE"
            ).fetchall()
            return [self._user(row) for row in rows]

    def list_user_events(self):
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT username, action, created_at FROM user_events ORDER BY id DESC LIMIT 100"
            ).fetchall()
            return [dict(row) for row in rows]

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

    def activate_session(self, user_id, session_id):
        with self._connect() as connection:
            session = connection.execute(
                "SELECT id FROM sessions WHERE id = ? AND user_id = ?",
                (session_id, user_id),
            ).fetchone()
            if session is None:
                raise AuthenticationError("That discussion was not found.")
            connection.execute(
                "UPDATE sessions SET ended_at = CURRENT_TIMESTAMP "
                "WHERE user_id = ? AND ended_at IS NULL",
                (user_id,),
            )
            connection.execute(
                "UPDATE sessions SET ended_at = NULL WHERE id = ? AND user_id = ?",
                (session_id, user_id),
            )

    def list_conversations(self, user_id, limit=50):
        with self._connect() as connection:
            sessions = connection.execute(
                "SELECT id, started_at, ended_at FROM sessions "
                "WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
            conversations = []
            for session in sessions:
                first_message = connection.execute(
                    "SELECT content FROM messages WHERE session_id = ? AND role = 'user' "
                    "ORDER BY id LIMIT 1",
                    (session["id"],),
                ).fetchone()
                title = first_message["content"] if first_message else "New discussion"
                conversations.append({
                    "id": session["id"],
                    "title": title[:72],
                    "started_at": session["started_at"],
                    "active": session["ended_at"] is None,
                })
            return conversations

    def recent_messages(self, user_id, limit=80, session_id=None):
        with self._connect() as connection:
            if session_id is None:
                rows = connection.execute(
                    "SELECT message_key, role, content FROM messages "
                    "WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                    (user_id, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT message_key, role, content FROM messages "
                    "WHERE user_id = ? AND session_id = ? ORDER BY id DESC LIMIT ?",
                    (user_id, session_id, limit),
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

    def export_for_migration(self):
        with self._connect() as connection:
            return {
                table: [
                    dict(row)
                    for row in connection.execute(f"SELECT * FROM {table}").fetchall()
                ]
                for table in ("users", "sessions", "messages")
            }


class SupabaseAuthStore:
    def __init__(self, url=None, service_role_key=None, timeout=15):
        self.url = (url or os.getenv("SUPABASE_URL", "")).rstrip("/")
        self.service_role_key = service_role_key or os.getenv(
            "SUPABASE_SERVICE_ROLE_KEY", ""
        )
        self.timeout = timeout
        if not self.url or not self.service_role_key:
            raise RuntimeError(
                "Cloud storage is not configured. Set SUPABASE_URL and "
                "SUPABASE_SERVICE_ROLE_KEY in the root .env file."
            )
        if not self.url.startswith("https://"):
            raise RuntimeError("SUPABASE_URL must use HTTPS.")

    @staticmethod
    def _decode_bytea(value):
        if isinstance(value, bytes):
            return value
        if isinstance(value, str) and value.startswith("\\x"):
            return bytes.fromhex(value[2:])
        raise RuntimeError("Supabase returned an invalid credential field.")

    @staticmethod
    def _user(row):
        if row is None:
            return None
        return {
            "id": int(row["id"]),
            "username": row["username"],
            "role": row["role"],
            "active": bool(row["active"]),
            "memory_enabled": bool(row["memory_enabled"]),
            "gender": row.get("gender"),
        }

    def _request(self, method, table, params=None, body=None, prefer=None):
        query = f"?{urlencode(params or [], doseq=True)}" if params else ""
        url = f"{self.url}/rest/v1/{table}{query}"
        headers = {
            "apikey": self.service_role_key,
            "Authorization": f"Bearer {self.service_role_key}",
            "Accept": "application/json",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        if prefer:
            headers["Prefer"] = prefer
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        request = Request(url, data=payload, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                content = response.read()
                data = json.loads(content) if content else None
                return data, response.headers
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            if (
                table == "jarvis_user_events"
                and error.code == 404
                and ("PGRST205" in detail or "Could not find the table" in detail)
            ):
                raise RuntimeError(
                    "Cloud user-change history is not set up. Apply "
                    "supabase/migrations/20261105_user_management_audit.sql "
                    "in the Supabase SQL Editor."
                ) from error
            raise RuntimeError(
                f"Cloud database request failed ({error.code}): {detail[:500]}"
            ) from error
        except (URLError, TimeoutError) as error:
            raise RuntimeError(f"Cloud database is unavailable: {error}") from error

    def _get_one(self, table, params):
        rows, _ = self._request(
            "GET", table, [*params, ("limit", "1")]
        )
        return rows[0] if rows else None

    def _insert_one(self, table, row):
        rows, _ = self._request(
            "POST", table, body=row, prefer="return=representation"
        )
        if not rows:
            raise RuntimeError(f"Cloud database did not return the inserted {table} row.")
        return rows[0]

    def has_admin(self):
        return self._get_one(
            "jarvis_users", [("select", "id"), ("role", "eq.admin")]
        ) is not None

    def bootstrap_admin(self, pin):
        AuthStore.validate_pin(pin)
        salt = secrets.token_bytes(16)
        try:
            row = self._insert_one(
                "jarvis_users",
                {
                    "username": DEFAULT_ADMIN_NAME,
                    "username_key": DEFAULT_ADMIN_NAME.casefold(),
                    "role": "admin",
                    "pin_salt": "\\x" + salt.hex(),
                    "pin_hash": "\\x" + AuthStore._derive_pin(pin, salt).hex(),
                },
            )
        except RuntimeError as error:
            if "23505" in str(error):
                raise AuthenticationError(
                    "The administrator account is already set up."
                ) from error
            raise
        return self._user(row)

    def get_user(self, user_id):
        row = self._get_one(
            "jarvis_users",
            [("select", "*"), ("id", f"eq.{int(user_id)}")],
        )
        return self._user(row)

    def authenticate(self, username, pin, require_admin=False):
        name = username.strip() if isinstance(username, str) else ""
        if not name or not isinstance(pin, str):
            raise AuthenticationError("Enter a username and PIN.")
        row = self._get_one(
            "jarvis_users",
            [
                ("select", "*"),
                ("username_key", f"eq.{name.casefold()}"),
                ("active", "eq.true"),
            ],
        )
        if row is None:
            raise AuthenticationError("Username or PIN is incorrect.")
        if row["locked_until"] > time.time():
            remaining = max(1, int(row["locked_until"] - time.time()))
            raise AuthenticationError(
                f"Too many attempts. Try again in {remaining} seconds."
            )
        salt = self._decode_bytea(row["pin_salt"])
        pin_hash = self._decode_bytea(row["pin_hash"])
        if not (
            PIN_PATTERN.fullmatch(pin)
            and hmac.compare_digest(AuthStore._derive_pin(pin, salt), pin_hash)
        ):
            failures = int(row["failed_attempts"]) + 1
            locked_until = (
                time.time() + LOCKOUT_SECONDS if failures >= MAX_FAILED_ATTEMPTS else 0
            )
            self._request(
                "PATCH",
                "jarvis_users",
                [("id", f"eq.{row['id']}")],
                {
                    "failed_attempts": 0 if locked_until else failures,
                    "locked_until": locked_until,
                },
                "return=minimal",
            )
            if locked_until:
                raise AuthenticationError(
                    f"Too many attempts. Sign-in is locked for {LOCKOUT_SECONDS} seconds."
                )
            raise AuthenticationError("Username or PIN is incorrect.")
        if require_admin and row["role"] != "admin":
            raise AuthenticationError("Administrator PIN required.")
        self._request(
            "PATCH",
            "jarvis_users",
            [("id", f"eq.{row['id']}")],
            {"failed_attempts": 0, "locked_until": 0},
            "return=minimal",
        )
        return self._user(row)

    def add_user(self, actor_id, username, pin, gender=None):
        name = username.strip() if isinstance(username, str) else ""
        if not name or len(name) > 60:
            raise AuthenticationError("Enter a name between 1 and 60 characters.")
        if any(ord(char) < 32 for char in name):
            raise AuthenticationError("The username contains unsupported characters.")
        if gender is not None and gender not in (
            "male",
            "female",
            "non_binary",
            "prefer_not_to_say",
        ):
            raise AuthenticationError("Choose one of the available gender options.")
        AuthStore.validate_pin(pin)
        actor = self.get_user(actor_id)
        if not actor or actor["role"] != "admin" or not actor["active"]:
            raise AuthenticationError("Only the signed-in administrator can add users.")
        salt = secrets.token_bytes(16)
        try:
            row = self._insert_one(
                "jarvis_users",
                {
                    "username": name,
                    "username_key": name.casefold(),
                    "role": "user",
                    "pin_salt": "\\x" + salt.hex(),
                    "pin_hash": "\\x" + AuthStore._derive_pin(pin, salt).hex(),
                    "gender": gender,
                },
            )
        except RuntimeError as error:
            if "23505" in str(error):
                raise AuthenticationError("That username is already in use.") from error
            raise
        return self._user(row)

    def disable_user(self, actor_id, target_id):
        actor = self.get_user(actor_id)
        if not actor or actor["role"] != "admin" or not actor["active"]:
            raise AuthenticationError("Only the signed-in administrator can manage users.")
        target = self.get_user(target_id)
        if not target or not target["active"]:
            raise AuthenticationError("That active user was not found.")
        if target["role"] == "admin":
            raise AuthenticationError("The administrator account cannot be disabled.")
        self.list_user_events()
        self._request(
            "PATCH",
            "jarvis_users",
            [
                ("id", f"eq.{int(target_id)}"),
                ("role", "eq.user"),
            ],
            {"active": False},
            "return=minimal",
        )
        self._request(
            "POST",
            "jarvis_user_events",
            body={"username": target["username"], "action": "disabled"},
            prefer="return=minimal",
        )

    def enable_user(self, actor_id, target_id):
        actor = self.get_user(actor_id)
        if not actor or actor["role"] != "admin" or not actor["active"]:
            raise AuthenticationError("Only the signed-in administrator can manage users.")
        target = self.get_user(target_id)
        if not target or target["role"] != "user":
            raise AuthenticationError("That user was not found.")
        if target["active"]:
            raise AuthenticationError("That user is already enabled.")
        self.list_user_events()
        self._request(
            "PATCH",
            "jarvis_users",
            [("id", f"eq.{int(target_id)}"), ("role", "eq.user")],
            {"active": True},
            "return=minimal",
        )
        self._request(
            "POST",
            "jarvis_user_events",
            body={"username": target["username"], "action": "enabled"},
            prefer="return=minimal",
        )

    def delete_user(self, actor_id, target_id):
        actor = self.get_user(actor_id)
        if not actor or actor["role"] != "admin" or not actor["active"]:
            raise AuthenticationError("Only the signed-in administrator can manage users.")
        target = self.get_user(target_id)
        if not target or target["role"] != "user":
            raise AuthenticationError("That user was not found.")
        self.list_user_events()
        user_filter = [("user_id", f"eq.{int(target_id)}")]
        self._request(
            "POST",
            "jarvis_user_events",
            body={"username": target["username"], "action": "deleted"},
            prefer="return=minimal",
        )
        self._request("DELETE", "jarvis_messages", user_filter, prefer="return=minimal")
        self._request("DELETE", "jarvis_sessions", user_filter, prefer="return=minimal")
        self._request(
            "DELETE",
            "jarvis_users",
            [("id", f"eq.{int(target_id)}"), ("role", "eq.user")],
            prefer="return=minimal",
        )

    def list_users(self):
        rows, _ = self._request(
            "GET",
            "jarvis_users",
            [
                ("select", "id,username,role,active,memory_enabled,gender"),
                ("order", "role.desc,username_key.asc"),
            ],
        )
        return [self._user(row) for row in rows]

    def list_user_events(self):
        rows, _ = self._request(
            "GET",
            "jarvis_user_events",
            [
                ("select", "username,action,created_at"),
                ("order", "created_at.desc"),
                ("limit", "100"),
            ],
        )
        return rows

    def set_gender(self, user_id, gender):
        if gender not in ("male", "female", "non_binary", "prefer_not_to_say"):
            raise AuthenticationError("Choose one of the available gender options.")
        self._request(
            "PATCH",
            "jarvis_users",
            [("id", f"eq.{int(user_id)}"), ("active", "eq.true")],
            {"gender": gender},
            "return=minimal",
        )

    def start_session(self, user_id):
        self._request(
            "PATCH",
            "jarvis_sessions",
            [
                ("user_id", f"eq.{int(user_id)}"),
                ("ended_at", "is.null"),
            ],
            {"ended_at": datetime_now()},
            "return=minimal",
        )
        row = self._insert_one(
            "jarvis_sessions", {"user_id": int(user_id)}
        )
        return int(row["id"])

    def activate_session(self, user_id, session_id):
        row = self._get_one(
            "jarvis_sessions",
            [
                ("select", "id"),
                ("id", f"eq.{int(session_id)}"),
                ("user_id", f"eq.{int(user_id)}"),
            ],
        )
        if row is None:
            raise AuthenticationError("That discussion was not found.")
        self._request(
            "PATCH",
            "jarvis_sessions",
            [
                ("user_id", f"eq.{int(user_id)}"),
                ("ended_at", "is.null"),
            ],
            {"ended_at": datetime_now()},
            "return=minimal",
        )
        self._request(
            "PATCH",
            "jarvis_sessions",
            [
                ("id", f"eq.{int(session_id)}"),
                ("user_id", f"eq.{int(user_id)}"),
            ],
            {"ended_at": None},
            "return=minimal",
        )

    def end_session(self, session_id):
        if session_id is not None:
            self._request(
                "PATCH",
                "jarvis_sessions",
                [("id", f"eq.{int(session_id)}"), ("ended_at", "is.null")],
                {"ended_at": datetime_now()},
                "return=minimal",
            )

    def list_conversations(self, user_id, limit=50, archived=False):
        rows, _ = self._request(
            "GET",
            "jarvis_sessions",
            [
                ("select", "id,started_at,ended_at,archived,jarvis_messages(content,role,id)"),
                ("user_id", f"eq.{int(user_id)}"),
                ("archived", f"eq.{str(bool(archived)).lower()}"),
                ("order", "started_at.desc"),
                ("limit", str(limit)),
                ("jarvis_messages.order", "id.asc"),
                ("jarvis_messages.limit", "1"),
            ],
        )
        return [
            {
                "id": int(row["id"]),
                "title": next(
                    (
                        message["content"][:72]
                        for message in row.get("jarvis_messages", [])
                        if message["role"] == "user"
                    ),
                    "New discussion",
                ),
                "started_at": row["started_at"],
                "active": row["ended_at"] is None,
                "archived": bool(row.get("archived", False)),
            }
            for row in rows
        ]

    def archive_all_conversations(self, user_id):
        self._request(
            "PATCH",
            "jarvis_sessions",
            [("user_id", f"eq.{int(user_id)}"), ("archived", "eq.false")],
            {"archived": True, "ended_at": datetime_now()},
            "return=minimal",
        )

    def set_conversation_archived(self, user_id, session_id, archived):
        row = self._get_one(
            "jarvis_sessions",
            [
                ("select", "id"),
                ("id", f"eq.{int(session_id)}"),
                ("user_id", f"eq.{int(user_id)}"),
            ],
        )
        if row is None:
            raise AuthenticationError("That discussion was not found.")
        self._request(
            "PATCH",
            "jarvis_sessions",
            [
                ("id", f"eq.{int(session_id)}"),
                ("user_id", f"eq.{int(user_id)}"),
            ],
            {"archived": bool(archived)},
            "return=minimal",
        )

    def delete_all_conversations(self, user_id):
        user_filter = [("user_id", f"eq.{int(user_id)}")]
        self._request(
            "DELETE", "jarvis_messages", user_filter, prefer="return=minimal"
        )
        self._request(
            "DELETE", "jarvis_sessions", user_filter, prefer="return=minimal"
        )
        self._request(
            "PATCH",
            "jarvis_users",
            [("id", f"eq.{int(user_id)}"), ("active", "eq.true")],
            {"memory_enabled": False, "memory_json": []},
            "return=minimal",
        )

    def recent_messages(self, user_id, limit=80, session_id=None):
        params = [
            ("select", "message_key,role,content"),
            ("user_id", f"eq.{int(user_id)}"),
            ("order", "id.desc"),
            ("limit", str(limit)),
        ]
        if session_id is not None:
            params.append(("session_id", f"eq.{int(session_id)}"))
        rows, _ = self._request("GET", "jarvis_messages", params)
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
        self._request(
            "POST",
            "jarvis_messages",
            [("on_conflict", "session_id,message_key")],
            {
                "user_id": int(user_id),
                "session_id": int(session_id),
                "message_key": str(key),
                "role": role,
                "content": str(content),
            },
            "resolution=merge-duplicates,return=minimal",
        )

    def load_profile(self, user_id):
        row = self._get_one(
            "jarvis_users",
            [
                ("select", "memory_enabled,memory_json"),
                ("id", f"eq.{int(user_id)}"),
                ("active", "eq.true"),
            ],
        )
        if row is None:
            raise AuthenticationError("This account is no longer active.")
        return bool(row["memory_enabled"]), json.dumps(row["memory_json"])

    def save_profile(self, user_id, memory_enabled, memory_json):
        try:
            decoded_memory = json.loads(memory_json)
        except json.JSONDecodeError as error:
            raise ValueError("Saved user memory must be valid JSON.") from error
        self._request(
            "PATCH",
            "jarvis_users",
            [("id", f"eq.{int(user_id)}"), ("active", "eq.true")],
            {
                "memory_enabled": bool(memory_enabled),
                "memory_json": decoded_memory,
            },
            "return=minimal",
        )

    def import_legacy_data(self, legacy_data):
        for table in ("jarvis_users", "jarvis_sessions", "jarvis_messages"):
            existing, _ = self._request(
                "GET",
                table,
                [("select", "id"), ("limit", "1")],
            )
            if existing:
                raise RuntimeError(
                    f"Cloud table {table} is not empty; refusing to merge a local migration."
                )

        user_ids = {}
        for row in legacy_data["users"]:
            cloud_user = self._insert_one(
                "jarvis_users",
                {
                    "username": row["username"],
                    "username_key": row["username"].casefold(),
                    "role": row["role"],
                    "pin_salt": "\\x" + bytes(row["pin_salt"]).hex(),
                    "pin_hash": "\\x" + bytes(row["pin_hash"]).hex(),
                    "active": bool(row["active"]),
                    "failed_attempts": int(row["failed_attempts"]),
                    "locked_until": float(row["locked_until"]),
                    "memory_enabled": bool(row["memory_enabled"]),
                    "memory_json": json.loads(row["memory_json"]),
                    "gender": row.get("gender"),
                    "created_at": row["created_at"],
                },
            )
            user_ids[row["id"]] = cloud_user["id"]

        session_ids = {}
        for row in legacy_data["sessions"]:
            cloud_session = self._insert_one(
                "jarvis_sessions",
                {
                    "user_id": user_ids[row["user_id"]],
                    "started_at": row["started_at"],
                    "ended_at": row["ended_at"],
                },
            )
            session_ids[row["id"]] = cloud_session["id"]

        for offset in range(0, len(legacy_data["messages"]), 500):
            batch = [
                {
                    "user_id": user_ids[row["user_id"]],
                    "session_id": session_ids[row["session_id"]],
                    "message_key": row["message_key"],
                    "role": row["role"],
                    "content": row["content"],
                    "updated_at": row["updated_at"],
                }
                for row in legacy_data["messages"][offset:offset + 500]
            ]
            if batch:
                self._request(
                    "POST",
                    "jarvis_messages",
                    body=batch,
                    prefer="return=minimal",
                )

        return self.verify_counts()

    def verify_counts(self):
        return {
            "users": self._count_rows("jarvis_users"),
            "sessions": self._count_rows("jarvis_sessions"),
            "messages": self._count_rows("jarvis_messages"),
        }

    def _count_rows(self, table):
        _, headers = self._request(
            "GET",
            table,
            [("select", "id"), ("limit", "1")],
            prefer="count=exact",
        )
        content_range = headers.get("Content-Range", "")
        try:
            return int(content_range.rsplit("/", 1)[1])
        except (IndexError, ValueError) as error:
            raise RuntimeError(
                f"Cloud database did not return a row count for {table}."
            ) from error


def datetime_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class LocalChatStore:
    def __init__(self, path=None):
        self.path = str(path or Path(__file__).with_name("jarvis_private_chats.sqlite3"))
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    ended_at TEXT,
                    archived INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS private_sessions_user_started
                    ON sessions (user_id, started_at DESC);
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    message_key TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (session_id, message_key)
                );
                """
            )

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

    def start_session(self, user_id):
        with self._connect() as connection:
            connection.execute(
                "UPDATE sessions SET ended_at = CURRENT_TIMESTAMP "
                "WHERE user_id = ? AND ended_at IS NULL",
                (int(user_id),),
            )
            cursor = connection.execute(
                "INSERT INTO sessions (user_id) VALUES (?)", (int(user_id),)
            )
            return int(cursor.lastrowid)

    def end_session(self, session_id):
        if session_id is None:
            return
        with self._connect() as connection:
            connection.execute(
                "UPDATE sessions SET ended_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND ended_at IS NULL",
                (int(session_id),),
            )

    def activate_session(self, user_id, session_id):
        with self._connect() as connection:
            session = connection.execute(
                "SELECT id FROM sessions WHERE id = ? AND user_id = ?",
                (int(session_id), int(user_id)),
            ).fetchone()
            if session is None:
                raise AuthenticationError("That private discussion was not found.")
            connection.execute(
                "UPDATE sessions SET ended_at = CURRENT_TIMESTAMP "
                "WHERE user_id = ? AND ended_at IS NULL",
                (int(user_id),),
            )
            connection.execute(
                "UPDATE sessions SET ended_at = NULL WHERE id = ? AND user_id = ?",
                (int(session_id), int(user_id)),
            )

    def list_conversations(self, user_id, limit=50, archived=False):
        with self._connect() as connection:
            sessions = connection.execute(
                "SELECT id, started_at, ended_at, archived FROM sessions "
                "WHERE user_id = ? AND archived = ? "
                "ORDER BY id DESC LIMIT ?",
                (int(user_id), bool(archived), int(limit)),
            ).fetchall()
            conversations = []
            for session in sessions:
                first_message = connection.execute(
                    "SELECT content FROM messages WHERE session_id = ? AND role = 'user' "
                    "ORDER BY id LIMIT 1",
                    (session["id"],),
                ).fetchone()
                title = first_message["content"] if first_message else "New private discussion"
                conversations.append({
                    "id": f"private:{session['id']}",
                    "title": title[:72],
                    "started_at": session["started_at"],
                    "active": session["ended_at"] is None,
                    "private": True,
                    "archived": bool(session["archived"]),
                })
            return conversations

    def recent_messages(self, user_id, limit=80, session_id=None):
        with self._connect() as connection:
            if session_id is None:
                rows = connection.execute(
                    "SELECT message_key, role, content FROM messages "
                    "WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                    (int(user_id), int(limit)),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT message_key, role, content FROM messages "
                    "WHERE user_id = ? AND session_id = ? ORDER BY id DESC LIMIT ?",
                    (int(user_id), int(session_id), int(limit)),
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
                (int(user_id), int(session_id), str(key), role, str(content)),
            )

    def archive_all_conversations(self, user_id):
        with self._connect() as connection:
            connection.execute(
                "UPDATE sessions SET archived = 1, ended_at = "
                "COALESCE(ended_at, CURRENT_TIMESTAMP) WHERE user_id = ?",
                (int(user_id),),
            )

    def set_conversation_archived(self, user_id, session_id, archived):
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE sessions SET archived = ? WHERE id = ? AND user_id = ?",
                (bool(archived), int(session_id), int(user_id)),
            )
            if cursor.rowcount != 1:
                raise AuthenticationError("That private discussion was not found.")

    def delete_all_conversations(self, user_id):
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM sessions WHERE user_id = ?", (int(user_id),)
            )
