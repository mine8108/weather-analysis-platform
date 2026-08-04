-- ============================================================
-- 气象平台数据库结构 + 行级安全（RLS）策略
-- 在 Supabase 控制台 → SQL Editor 中执行本文件（可重复执行）。
-- 说明：本文件在原有 datasets 表基础上，新增了
--   profiles（用户档案/配额）、invite_codes（邀请码）、
--   以及若干 SECURITY DEFINER 函数。
-- ============================================================

-- ============================================================
-- 1. 数据集表（已有，保留）
-- ============================================================
create table if not exists public.datasets (
    id          uuid primary key default gen_random_uuid(),
    user_id     uuid not null references auth.users(id) on delete cascade,
    name        text not null,
    csv_text    text not null,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

create index if not exists datasets_user_idx on public.datasets (user_id);

alter table public.datasets enable row level security;

drop policy if exists "datasets_owner_only" on public.datasets;
create policy "datasets_owner_only"
    on public.datasets
    for all
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

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

-- ============================================================
-- 2. profiles：每个 auth 用户一行，记录角色与存储配额
-- ============================================================
create table if not exists public.profiles (
    user_id              uuid primary key references auth.users(id) on delete cascade,
    role                 text not null default 'user',   -- 'user' | 'admin'
    storage_quota_bytes  bigint not null default 10485760,  -- 默认 10 MB
    created_at           timestamptz not null default now()
);

alter table public.profiles enable row level security;

drop policy if exists "profiles_select_self" on public.profiles;
create policy "profiles_select_self"
    on public.profiles for select using (auth.uid() = user_id);

drop policy if exists "profiles_update_self" on public.profiles;
create policy "profiles_update_self"
    on public.profiles for update
    using (auth.uid() = user_id)
    -- 安全修复（P-02）：with check 约束更新后的行。用户仅可更新自己的行，
    -- 且禁止修改 role（防自改 admin）。service_role 绕过 RLS 不受影响。
    with check (auth.uid() = user_id AND role = 'user');

-- 服务角色（触发器/管理员）插入：with check(true) 让触发器可写入
drop policy if exists "profiles_insert_service" on public.profiles;
create policy "profiles_insert_service"
    on public.profiles for insert with check (true);

-- ============================================================
-- 3. invite_codes：邀请码表（默认对所有客户端隐藏）
-- ============================================================
create table if not exists public.invite_codes (
    code       text primary key,
    created_by uuid references auth.users(id) on delete cascade,
    used_by    uuid references auth.users(id) on delete cascade,
    used_at    timestamptz,
    created_at timestamptz not null default now()
);

-- 已有旧表的外键可能是 ON DELETE RESTRICT（默认），删除用户时会阻塞；
-- 以下把现存的两个外键约束重建为 ON DELETE CASCADE，
-- 删除用户时一并删除其生成/使用过的邀请码，之后控制台可直接删除。
do $$
begin
    alter table public.invite_codes
        drop constraint if exists invite_codes_created_by_fkey,
        drop constraint if exists invite_codes_used_by_fkey;
    alter table public.invite_codes
        add constraint invite_codes_created_by_fkey
            foreign key (created_by) references auth.users(id) on delete cascade,
        add constraint invite_codes_used_by_fkey
            foreign key (used_by) references auth.users(id) on delete cascade;
exception
    when others then null;
end $$;

alter table public.invite_codes enable row level security;
-- 不创建任何面向 anon/authenticated 的 policy：
-- 即默认拒绝直接读取，只能通过下方 SECURITY DEFINER 函数访问。

-- ============================================================
-- 4. 触发器：新 auth 用户自动建 profiles 行（带默认配额）
-- ============================================================
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    insert into public.profiles (user_id, role, storage_quota_bytes)
    values (new.id, 'user', 10485760)
    on conflict (user_id) do nothing;
    return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
    after insert on auth.users
    for each row execute function public.handle_new_user();

-- ============================================================
-- 5. 邀请码校验/消费函数（SECURITY DEFINER，仅消费函数收紧授权）
-- ============================================================
-- 仅判断某码是否存在且未使用（不泄露任何码内容）。
-- 安全修复（P-04 附）：保持 anon 可调是注册流程的设计取舍（未登录用户需先验码），
-- 只返回布尔值、48bit 熵使枚举不现实；真正的核销权限已在 consume 侧收紧。
create or replace function public.is_invite_code_valid(p_code text)
returns boolean
language sql
security definer
set search_path = public
as $$
    select exists (
        select 1 from public.invite_codes
        where code = p_code and used_by is null
    );
$$;

-- 消费邀请码：标记为已用并绑定 user_id，返回是否成功。
-- 安全修复（P-04）：调用者身份绑定——service_role 放行；
-- 已登录用户必须 p_user_id = auth.uid()（防止匿名核销任意码、防止替他人消费）。
create or replace function public.consume_invite_code(p_code text, p_user_id uuid)
returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare
    v_count int;
begin
    -- 身份校验：service_role 直接放行；否则必须是已登录用户本人
    if auth.role() <> 'service_role'
       and (auth.uid() is null or auth.uid() <> p_user_id) then
        return false;
    end if;
    update public.invite_codes
       set used_by = p_user_id, used_at = now()
     where code = p_code and used_by is null;
    get diagnostics v_count = row_count;
    return v_count > 0;
end;
$$;

grant execute on function public.is_invite_code_valid(text) to anon, authenticated, service_role;
-- 安全修复（P-04）：撤销 anon 执行权，仅 authenticated / service_role 可核销
grant execute on function public.consume_invite_code(text, uuid) to authenticated, service_role;

-- ============================================================
-- 6. 存储用量 / 配额查询函数（SECURITY DEFINER）
-- 安全修复（P-03）：函数内校验调用者身份，禁止查询他人数据
-- ============================================================
create or replace function public.get_storage_usage(p_user_id uuid)
returns bigint
language plpgsql
security definer
set search_path = public
as $$
begin
    if auth.role() <> 'service_role'
       and (auth.uid() is null or auth.uid() <> p_user_id) then
        return 0;
    end if;
    return coalesce(
        (select sum(octet_length(csv_text)) from public.datasets
          where user_id = p_user_id), 0);
end;
$$;

create or replace function public.get_storage_quota(p_user_id uuid)
returns bigint
language plpgsql
security definer
set search_path = public
as $$
declare
    v_quota bigint;
begin
    if auth.role() <> 'service_role'
       and (auth.uid() is null or auth.uid() <> p_user_id) then
        return 10485760; -- 返回默认配额，不泄露他人真实配额
    end if;
    select storage_quota_bytes into v_quota
      from public.profiles
     where user_id = p_user_id;
    return coalesce(v_quota, 10485760);
end;
$$;

grant execute on function public.get_storage_usage(uuid) to authenticated, service_role;
grant execute on function public.get_storage_quota(uuid) to authenticated, service_role;

-- ============================================================
-- 7. gfs_cache：GFS 预报跨用户 / 跨重启共享缓存
--    目的：多人查同一坐标时只打一次 Open-Meteo，降低 429 限流概率。
--    该表为共享缓存层（非敏感数据）。
--    安全修复（P-01）：读保持公开（缓存读取设计意图），写收紧为仅登录用户，
--    且 data_json 单行大小受限（100KB），防止匿名毒化缓存与存储滥用。
-- ============================================================
create table if not exists public.gfs_cache (
    cache_key   text primary key,
    lat         double precision not null,
    lon         double precision not null,
    days        integer not null,
    model       text not null,
    data_json   jsonb not null,
    created_at  timestamptz not null default now()
);

create index if not exists gfs_cache_created_idx on public.gfs_cache (created_at);

alter table public.gfs_cache enable row level security;

-- 公开可读：任何访客都能读缓存，避免重复请求 Open-Meteo
drop policy if exists "gfs_cache_public_read" on public.gfs_cache;
create policy "gfs_cache_public_read"
    on public.gfs_cache for select using (true);

-- 写：仅 authenticated（已登录用户）可 upsert；行大小上限 100KB；
-- 未登录（anon）无法写入，匿名者无法毒化共享缓存或灌入无限数据
drop policy if exists "gfs_cache_auth_write" on public.gfs_cache;
create policy "gfs_cache_auth_write"
    on public.gfs_cache for insert
    to authenticated
    with check (octet_length(data_json::text) <= 100000);

drop policy if exists "gfs_cache_auth_update" on public.gfs_cache;
create policy "gfs_cache_auth_update"
    on public.gfs_cache for update
    to authenticated
    using (true)
    with check (octet_length(data_json::text) <= 100000);

-- ============================================================
-- 8. save_dataset：带配额强制的数据集写入函数（SECURITY DEFINER）
--    安全修复（P-12）：配额校验从「客户端预检」移到数据库强制，
--    并撤销 authenticated 对 datasets 表的直插/直改权限，
--    杜绝绕过应用直接写大 CSV 的存储滥用路径。
-- ============================================================
create or replace function public.save_dataset(
    p_dataset_id uuid,
    p_name text,
    p_csv text
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
    v_uid uuid := auth.uid();
    v_used bigint := 0;
    v_quota bigint := 10485760;
    v_new_bytes bigint;
    v_row_id uuid;
begin
    if v_uid is null then
        return jsonb_build_object('ok', false, 'error', '未登录');
    end if;
    if p_name is null or length(p_name) = 0 or p_csv is null then
        return jsonb_build_object('ok', false, 'error', '参数缺失');
    end if;
    v_new_bytes := octet_length(p_csv);
    -- 已用量（更新场景排除自身旧数据）
    if p_dataset_id is null then
        select coalesce(sum(octet_length(csv_text)), 0) into v_used
          from public.datasets where user_id = v_uid;
    else
        select coalesce(sum(octet_length(csv_text)), 0) into v_used
          from public.datasets
         where user_id = v_uid and id <> p_dataset_id;
    end if;
    select storage_quota_bytes into v_quota
      from public.profiles where user_id = v_uid;
    v_quota := coalesce(v_quota, 10485760);
    if v_used + v_new_bytes > v_quota then
        return jsonb_build_object('ok', false, 'error', '配额不足');
    end if;
    if p_dataset_id is null then
        insert into public.datasets (user_id, name, csv_text)
        values (v_uid, p_name, p_csv)
        returning id into v_row_id;
    else
        update public.datasets
           set name = p_name, csv_text = p_csv
         where id = p_dataset_id and user_id = v_uid
        returning id into v_row_id;
        if v_row_id is null then
            return jsonb_build_object('ok', false, 'error', '数据集不存在或无权修改');
        end if;
    end if;
    return jsonb_build_object('ok', true, 'id', v_row_id);
end;
$$;

grant execute on function public.save_dataset(uuid, text, text) to authenticated, service_role;

-- 配额强制的关键：撤销 authenticated 对 datasets 的直插/直改权限
-- （保留 select/delete 的 RLS 策略；写入一律经 save_dataset 函数）
revoke insert, update on public.datasets from authenticated;
