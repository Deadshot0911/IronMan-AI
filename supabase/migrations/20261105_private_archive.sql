alter table public.jarvis_sessions
    add column if not exists archived boolean not null default false;
