-- 气象平台用户数据集表 + 行级安全（RLS）策略
-- 在 Supabase 控制台 → SQL Editor 中执行本文件。

-- 1. 数据集表：每位用户可拥有多条，csv_text 存 DataFrame 的 CSV 文本
create table if not exists public.datasets (
    id          uuid primary key default gen_random_uuid(),
    user_id     uuid not null references auth.users(id) on delete cascade,
    name        text not null,
    csv_text    text not null,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

create index if not exists datasets_user_idx on public.datasets (user_id);

-- 2. 开启行级安全：默认拒绝一切访问，仅下方策略放行
alter table public.datasets enable row level security;

-- 3. 策略：仅允许访问属于自己的行（增删改查都受此约束）
drop policy if exists "datasets_owner_only" on public.datasets;
create policy "datasets_owner_only"
    on public.datasets
    for all
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

-- 4. （可选）更新时间自动维护
create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists datasets_set_updated_at on public.datasets;
create trigger datasets_set_updated_at
    before update on public.datasets
    for each row execute function public.set_updated_at();
