-- Run this in the Supabase SQL editor.
-- The API connects with the server-side secret key, which bypasses RLS.

create table if not exists public.rotations (
    slug text primary key,
    name text not null,
    description text,
    definition jsonb not null,
    seasons integer not null default 0,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.rotation_results (
    slug text primary key references public.rotations (slug) on delete cascade,
    years integer not null default 0,
    model_version text,
    computed_at timestamptz not null default now(),
    result jsonb not null
);

create index if not exists rotations_name_idx on public.rotations (name);

alter table public.rotations enable row level security;
alter table public.rotation_results enable row level security;

-- Intentionally no policies: only the secret key (server-side) can access
-- these tables. Do not expose the secret key to the browser.
