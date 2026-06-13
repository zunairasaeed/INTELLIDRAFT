-- Supabase / Postgres schema for the LaTeX editor service.
--
-- This DDL mirrors the columns produced by ``InMemoryDbClient`` (see
-- ``app/core/in_memory_db.py``) and consumed by ``SupabaseDbClient``
-- (see ``app/core/supabase_db.py``). Run it via the Supabase SQL
-- editor (or ``psql``) once per project.

create extension if not exists "pgcrypto";

-- chat_sessions ──────────────────────────────────────────────────────────
create table if not exists chat_sessions (
    id              uuid primary key default gen_random_uuid(),
    user_id         uuid not null,
    title           text not null default 'LaTeX Editor',
    feature         text not null default 'latex_editor',
    workspace_id    uuid,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);

create index if not exists chat_sessions_user_id_idx
    on chat_sessions (user_id);

-- workspaces ─────────────────────────────────────────────────────────────
create table if not exists workspaces (
    id                  uuid primary key default gen_random_uuid(),
    session_id          uuid not null references chat_sessions (id) on delete cascade,
    user_id             uuid not null,
    tex_path            text,
    bib_path            text,
    doc_class           text,
    doc_mode            text,
    current_revision    integer not null default 0,
    lock_version        integer not null default 0,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now()
);

create index if not exists workspaces_session_id_idx
    on workspaces (session_id);

-- Link a session to its workspace once the workspace is provisioned.
alter table chat_sessions
    drop constraint if exists chat_sessions_workspace_id_fkey;
alter table chat_sessions
    add constraint chat_sessions_workspace_id_fkey
        foreign key (workspace_id) references workspaces (id) on delete set null;

-- edit_history ───────────────────────────────────────────────────────────
create table if not exists edit_history (
    id              uuid primary key default gen_random_uuid(),
    session_id      uuid not null references chat_sessions (id) on delete cascade,
    workspace_id    uuid not null references workspaces (id) on delete cascade,
    user_id         uuid not null,
    intent          text not null,
    summary         text,
    created_at      timestamptz not null default now()
);

create index if not exists edit_history_session_id_idx
    on edit_history (session_id);
create index if not exists edit_history_workspace_id_idx
    on edit_history (workspace_id);
