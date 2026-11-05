import argparse
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from dotenv import load_dotenv

from jarvis_auth import SupabaseAuthStore


ROOT = Path(__file__).resolve().parent
LOCAL_DATABASE = ROOT / "jarvis_users.sqlite3"


def read_local_database(path):
    uri = f"file:{path.as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        required = {"users", "sessions", "messages"}
        if not required.issubset(tables):
            raise RuntimeError("The local Jarvis database is missing auth/history tables.")
        users = [dict(row) for row in connection.execute("SELECT * FROM users")]
        sessions = [dict(row) for row in connection.execute("SELECT * FROM sessions")]
        messages = [dict(row) for row in connection.execute("SELECT * FROM messages")]
        return {"users": users, "sessions": sessions, "messages": messages}


def remove_local_database(path):
    for candidate in (
        path,
        Path(f"{path}-wal"),
        Path(f"{path}-shm"),
    ):
        if candidate.exists():
            candidate.unlink()


def main():
    parser = argparse.ArgumentParser(
        description="Migrate Jarvis account and conversation data to Supabase."
    )
    parser.add_argument(
        "--delete-local-after-verification",
        action="store_true",
        help="After matching cloud counts, ask before deleting the local auth database.",
    )
    args = parser.parse_args()

    if not LOCAL_DATABASE.is_file():
        raise RuntimeError(f"No local Jarvis database was found at {LOCAL_DATABASE}.")
    load_dotenv(ROOT / ".env")
    cloud = SupabaseAuthStore()
    legacy = read_local_database(LOCAL_DATABASE)
    expected = {name: len(rows) for name, rows in legacy.items()}
    print(
        "Migrating counts:",
        ", ".join(f"{name}={count}" for name, count in expected.items()),
    )

    if args.delete_local_after_verification:
        verified = cloud.verify_counts()
    else:
        verified = cloud.import_legacy_data(legacy)
    if verified != expected:
        raise RuntimeError(
            f"Cloud verification failed. Expected {expected}, received {verified}. "
            "The local database was preserved."
        )
    print("Cloud row counts match the local source.")

    if args.delete_local_after_verification:
        confirmation = input(
            "Type DELETE LOCAL DATA to remove jarvis_users.sqlite3 and its WAL files: "
        )
        if confirmation != "DELETE LOCAL DATA":
            print("Local database retained.")
            return
        remove_local_database(LOCAL_DATABASE)
        print("Verified local authentication database removed.")
    else:
        print(
            "Local database retained. Rerun with "
            "--delete-local-after-verification to remove it after confirmation."
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Cloud migration failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
