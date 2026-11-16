-- Chat memory schema for server/chat_memory.py.
-- Run once in a new Supabase project: Dashboard -> SQL Editor -> paste -> Run.
--
-- Four tiers:
--   1. key_facts       durable key/value facts
--   2. rolling_summary compressed narrative of older conversation
--   3. chat_memory     embedded overflow turns (vector(768), HNSW) + match_memory RPC
--   4. recent_turns    short sliding window of latest turns
--
-- RLS is enabled with no policies: the server uses the secret/service_role key,
-- which bypasses RLS, while publishable/anon keys can read nothing.

create extension if not exists vector with schema extensions;

-- 1. key_facts
create table if not exists public.key_facts (
  id bigint generated always as identity primary key,
  fact_key text not null unique,
  fact_value text not null,
  updated_at timestamptz not null default now()
);

-- 2. rolling_summary (code reads/updates the row with the highest id)
create table if not exists public.rolling_summary (
  id bigint generated always as identity primary key,
  summary text not null default '',
  turn_count integer not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- 3. chat_memory (768-d to match text-embedding-3-small with dimensions=768)
create table if not exists public.chat_memory (
  id bigint generated always as identity primary key,
  speaker text not null,
  content text not null,
  embedding extensions.vector(768) not null,
  created_at timestamptz not null default now()
);

create index if not exists chat_memory_embedding_hnsw
  on public.chat_memory
  using hnsw (embedding extensions.vector_cosine_ops);

-- 4. recent_turns
create table if not exists public.recent_turns (
  id bigint generated always as identity primary key,
  speaker text not null,
  content text not null,
  created_at timestamptz not null default now()
);

create index if not exists recent_turns_created_at_idx
  on public.recent_turns (created_at desc);

-- Semantic search used by chat_memory.retrieve_relevant().
create or replace function public.match_memory(
  query_embedding extensions.vector(768),
  match_count integer default 5
)
returns table (
  id bigint,
  speaker text,
  content text,
  created_at timestamptz,
  similarity double precision
)
language sql
stable
set search_path = public, extensions
as $$
  select
    m.id,
    m.speaker,
    m.content,
    m.created_at,
    1 - (m.embedding <=> query_embedding) as similarity
  from public.chat_memory m
  order by m.embedding <=> query_embedding
  limit match_count;
$$;

alter table public.key_facts enable row level security;
alter table public.rolling_summary enable row level security;
alter table public.chat_memory enable row level security;
alter table public.recent_turns enable row level security;
