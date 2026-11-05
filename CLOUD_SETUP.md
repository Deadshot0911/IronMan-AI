# Jarvis cloud storage setup

Jarvis stores account credentials, profile preferences, discussion metadata, and
chat messages in Supabase. The Python backend uses the server-only service role
key; the browser UI never receives it. There is no local database fallback.

## Configure Supabase

1. Create a Supabase project and open its SQL Editor.
2. Run the SQL in `supabase/schema.sql`.
3. Copy `.env.example` to `.env` in the repository root.
4. In the Supabase project settings, copy the Project URL and the legacy
   `service_role` API key into `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`.
   Keep this key private. Never put it in `jarvis-ui`, commit it, or send it in
   chat.

The schema enables row-level security and grants no table access to browser
roles. Only the Python server's service key can access these tables.

If you already created the initial schema, run
`supabase/migrations/20261105_private_archive.sql` in the SQL Editor before
starting this version. This adds the archive flag used by hidden discussions.

## Migrate existing accounts and conversations

With Supabase configured, run this once from the repository root:

```powershell
.\.venv\Scripts\python.exe .\migrate_jarvis_cloud.py
```

The migration refuses to merge into non-empty cloud tables and checks cloud
row counts against the local source. It preserves PIN hashes and salts, user
profiles, conversation sessions, and messages. The local database is retained
if upload or verification fails.

After confirming the migration counts, remove the local database and its SQLite
WAL files by running:

```powershell
.\.venv\Scripts\python.exe .\migrate_jarvis_cloud.py --delete-local-after-verification
```

The script requires the exact confirmation `DELETE LOCAL DATA` before deleting
the local auth database. Once configured, Jarvis itself reads and writes auth
and conversation data only through Supabase.

If a Supabase request fails, Jarvis reports the cloud error and does not fall
back to local persistence.

## Private discussions and history controls

The **Private · Local** control starts a local-only discussion saved in
`jarvis_private_chats.sqlite3`; its messages are not sent to Supabase. Private
discussions remain on this computer across Jarvis restarts and are separated by
signed-in user. Keep the computer account protected because this local database
is not encrypted by Jarvis. Private mode controls conversation storage only:
unless you select the local Ollama engine, prompts may still be sent to the
configured cloud AI provider to generate responses.

**Archive history** hides all of the signed-in user's cloud and private
discussions from the main sidebar while retaining them. Open **Archived** to
view and restore a discussion. **Permanently delete** requires confirmation and
removes that user's conversations, local private discussions, and saved Jarvis
memory; it does not delete the user's account.

The migrated `jarvis_users.sqlite3` account database is no longer needed after
the cloud migration is verified. It is separate from the new local-only
`jarvis_private_chats.sqlite3` database.
