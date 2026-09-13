-- weave remote transport backing store.
-- One row per (remote_url, name): the raw Claude Code session JSONL transcript,
-- pushed/pulled verbatim by server.py. remote_url is the logical remote
-- namespace from .weave/config, so a single Supabase project can host many
-- remotes.

create extension if not exists "pgcrypto";

create table if not exists public.weave_sessions (
    id          uuid        primary key default gen_random_uuid(),
    remote_url  text        not null,
    name        text        not null,
    transcript  text        not null,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now(),
    unique (remote_url, name)
);

create index if not exists weave_sessions_remote_url_idx
    on public.weave_sessions (remote_url);

-- Keep updated_at fresh on every upsert/update.
create or replace function public.weave_sessions_set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists weave_sessions_set_updated_at on public.weave_sessions;
create trigger weave_sessions_set_updated_at
    before update on public.weave_sessions
    for each row
    execute function public.weave_sessions_set_updated_at();

-- RLS on: access is via the service-role key from server.py, which bypasses RLS.
-- No anon/public policies are granted, so the table is closed by default.
alter table public.weave_sessions enable row level security;
