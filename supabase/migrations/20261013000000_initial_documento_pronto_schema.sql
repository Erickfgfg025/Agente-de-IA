-- Initial schema for DOCUMENTO PRONTO.
-- This migration records the schema already applied to the linked Supabase project.
-- RLS is enabled without public policies intentionally: access is server-side only.

create table if not exists public.bot_users (
  id uuid primary key default gen_random_uuid(),
  telegram_user_id bigint not null unique,
  plan text not null default 'free' check (plan in ('free','premium')),
  is_blocked boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.processing_jobs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.bot_users(id) on delete cascade,
  operation text not null,
  source_filename text,
  source_format text,
  target_format text,
  status text not null default 'queued' check (status in ('queued','processing','completed','failed','expired')),
  file_size_bytes bigint check (file_size_bytes is null or file_size_bytes >= 0),
  error_code text,
  created_at timestamptz not null default now(),
  completed_at timestamptz,
  expires_at timestamptz
);

create table if not exists public.usage_daily (
  user_id uuid not null references public.bot_users(id) on delete cascade,
  usage_date date not null default current_date,
  jobs_count integer not null default 0 check (jobs_count >= 0),
  bytes_processed bigint not null default 0 check (bytes_processed >= 0),
  primary key (user_id, usage_date)
);

create index if not exists idx_processing_jobs_user_created on public.processing_jobs(user_id, created_at desc);
create index if not exists idx_processing_jobs_status_created on public.processing_jobs(status, created_at);
create index if not exists idx_processing_jobs_expiry on public.processing_jobs(expires_at) where expires_at is not null;

alter table public.bot_users enable row level security;
alter table public.processing_jobs enable row level security;
alter table public.usage_daily enable row level security;

comment on table public.bot_users is 'Telegram bot users and subscription tier. Access through trusted server only.';
comment on table public.processing_jobs is 'Metadata for conversion/document tasks; do not store file contents here.';
comment on table public.usage_daily is 'Daily usage counters for Free and Premium quotas.';
