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

-- 安全修复（P0-3）：撤销用户对自己 profiles 行的更新权限。
-- 原策略 with check 只锁了 role，未锁 storage_quota_bytes，登录用户可直接
-- UPDATE 把自己配额改成任意值，从而架空 save_dataset 里的服务端配额强制。
drop policy if exists "profiles_update_self" on public.profiles;
revoke update on public.profiles from authenticated, anon;
grant update on public.profiles to service_role;

-- 服务角色（触发器/管理员）插入：with check(true) 让触发器可写入
-- 安全修复（P2-1）：策略限定 to service_role，避免匿名/登录角色也能插行
drop policy if exists "profiles_insert_service" on public.profiles;
create policy "profiles_insert_service"
    on public.profiles for insert
    to service_role
    with check (true);

-- ============================================================
-- 3. invite_codes：邀请码表（默认对所有客户端隐藏）
--    安全修复（R-22）：code 列存的是 SHA-256 十六进制摘要，不是明文邀请码。
--    应用侧写入与校验前都会先哈希，因此直接读库看不到任何可用邀请码。
--    迁移前遗留的明文码不再匹配，需删除后由管理员重新生成：
--        delete from public.invite_codes where used_by is null;
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
    -- 修复 R-20：原来 here 用 `when others then null` 静默吞掉失败，
    -- 迁移没生效也无从察觉；改为发出 warning，可重复执行的性质不变。
    when others then
        raise warning '邀请码外键迁移未完成（可忽略，若外键已正确则无需处理）：%', sqlerrm;
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
-- 5. 邀请码校验 / 认领 / 核销函数（SECURITY DEFINER）
-- ============================================================
-- 仅判断某码当前是否可用（不泄露任何码内容）。
-- used_at 在本设计中同时充当「认领时间戳」：认领后 used_at 被写入而 used_by
-- 仍为空，此时该码对其他人不可用；超过 15 分钟未核销则视为认领失效。
create or replace function public.is_invite_code_valid(p_code text)
returns boolean
language sql
security definer
set search_path = public
as $$
    select exists (
        select 1 from public.invite_codes
        where code = p_code
          and used_by is null
          and (used_at is null or used_at < now() - interval '15 minutes')
    );
$$;

-- 原子认领：安全修复（P1-1）。
-- 原注册流程是「只读验码 → 建号 → 核销」三步非原子，并发持同一邀请码的两个
-- 请求可双双通过验码、各建一个账号（一码多账号）。认领用单条 UPDATE 的行锁
-- 完成，并发只有一个请求能成功，其余拿到 false。
create or replace function public.claim_invite_code(p_code text)
returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare
    v_count int;
begin
    if p_code is null or length(p_code) = 0 then
        return false;
    end if;
    update public.invite_codes
       set used_at = now()
     where code = p_code
       and used_by is null
       and (used_at is null or used_at < now() - interval '15 minutes');
    get diagnostics v_count = row_count;
    return v_count > 0;
end;
$$;

-- 释放认领：建号失败时回滚，让码立即可再次使用（仅 service_role 有效）。
create or replace function public.release_invite_code(p_code text)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
    if auth.role() <> 'service_role' then
        return;
    end if;
    update public.invite_codes
       set used_at = null
     where code = p_code and used_by is null;
end;
$$;

-- 核销邀请码：把已认领的码绑定到新用户，返回是否成功。
-- 安全修复（P-04）：调用者身份绑定——service_role 放行；
-- 已登录用户必须 p_user_id = auth.uid()（防止匿名核销任意码、防止替他人消费）。
-- 兼容性说明：不要求 used_at 非空，以便尚未升级的客户端（只调 is_valid +
-- consume、不走 claim）仍能正常核销；原子性由 claim_invite_code 保证。
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
       set used_by = p_user_id
     where code = p_code
       and used_by is null;
    get diagnostics v_count = row_count;
    return v_count > 0;
end;
$$;

-- 安全修复（P2-2）：Postgres 函数默认对 PUBLIC 授 EXECUTE，只 grant 不会收回
-- 既有权限，因此显式 revoke 后再按需 grant，让声明与真实权限一致。
revoke execute on function public.is_invite_code_valid(text) from public;
revoke execute on function public.claim_invite_code(text) from public;
revoke execute on function public.consume_invite_code(text, uuid) from public;
revoke execute on function public.release_invite_code(text) from public;

-- 验码与认领必须允许未登录用户调用（注册发生在登录之前）
grant execute on function public.is_invite_code_valid(text) to anon, authenticated, service_role;
grant execute on function public.claim_invite_code(text) to anon, authenticated, service_role;
-- 核销仅登录用户 / 服务端可调；释放仅服务端可调（函数内另有身份校验）
grant execute on function public.consume_invite_code(text, uuid) to authenticated, service_role;
grant execute on function public.release_invite_code(text) to service_role;

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

-- 安全修复（P2-2）：先收回默认的 PUBLIC 执行权，再按需授予
revoke execute on function public.get_storage_usage(uuid) from public;
revoke execute on function public.get_storage_quota(uuid) from public;
grant execute on function public.get_storage_usage(uuid) to authenticated, service_role;
grant execute on function public.get_storage_quota(uuid) to authenticated, service_role;

-- ============================================================
-- 7. gfs_cache：GFS 预报跨用户 / 跨重启共享缓存
--    目的：多人查同一坐标时只打一次 Open-Meteo，降低 429 限流概率。
--    该表为共享缓存层（非敏感数据）。
--    安全修复（P-01）：写收紧为仅登录用户，且 data_json 单行大小受限（100KB）。
--    安全修复（P2-3）：读不再对匿名开放；写入与更新限定为「自己创建的行」，
--    防止任一登录用户覆盖他人缓存（投毒）；新增 24 小时过期行清理策略。
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

-- 归属列：记录写入者，用于「只能改自己那行」的策略
alter table public.gfs_cache
    add column if not exists created_by uuid default auth.uid();

create index if not exists gfs_cache_created_idx on public.gfs_cache (created_at);

alter table public.gfs_cache enable row level security;

-- 读：仅登录用户可读，避免匿名访客拿到他人查询过的经纬度
drop policy if exists "gfs_cache_public_read" on public.gfs_cache;
drop policy if exists "gfs_cache_auth_read" on public.gfs_cache;
create policy "gfs_cache_auth_read"
    on public.gfs_cache for select
    to authenticated
    using (true);

-- 写：仅 authenticated 可插入，且 created_by 必须是自己；行大小上限 100KB
drop policy if exists "gfs_cache_auth_write" on public.gfs_cache;
create policy "gfs_cache_auth_write"
    on public.gfs_cache for insert
    to authenticated
    with check (
        created_by = auth.uid()
        and octet_length(data_json::text) <= 100000
    );

-- 更新：只能更新自己创建的行（配合 cache_key 的小时桶轮换，
-- 他人旧行不会被阻塞刷新，因为新窗口使用新的 key）
drop policy if exists "gfs_cache_auth_update" on public.gfs_cache;
create policy "gfs_cache_auth_update"
    on public.gfs_cache for update
    to authenticated
    using (created_by = auth.uid())
    with check (
        created_by = auth.uid()
        and octet_length(data_json::text) <= 100000
    );

-- 过期清理：登录用户可删除 24 小时前的缓存行（key 每小时轮换，旧行不再被读）
drop policy if exists "gfs_cache_prune" on public.gfs_cache;
create policy "gfs_cache_prune"
    on public.gfs_cache for delete
    to authenticated
    using (created_at < now() - interval '24 hours');

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
    -- 安全修复（P2-4）：锁住本用户的 profiles 行，串行化并发保存，
    -- 避免两个请求同时通过配额校验后各自写入、最终超出配额
    select storage_quota_bytes into v_quota
      from public.profiles where user_id = v_uid
       for update;
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

-- 安全修复（P2-2）：先收回默认的 PUBLIC 执行权，再按需授予
revoke execute on function public.save_dataset(uuid, text, text) from public;
grant execute on function public.save_dataset(uuid, text, text) to authenticated, service_role;

-- 配额强制的关键：撤销 authenticated 对 datasets 的直插/直改权限
-- （保留 select/delete 的 RLS 策略；写入一律经 save_dataset 函数）
revoke insert, update on public.datasets from authenticated;

-- ============================================================
-- 8. 读图配额：按用户、按天的次数与 token 双维度限制
--    背景：读图调用使用部署方的 API 密钥，任何被邀请用户的每次调用都计费在
--    部署方账上。此前只有浏览器会话级的计数，刷新即归零，既不能作为成本控制，
--    也没有对象可供管理员按用户调配。
--    安全要求（重要）：
--      1. 三个函数内部一律以 auth.uid() 判定身份，**不接受调用方传入 user_id**，
--         否则可以伪造或清空他人计数；
--      2. token 增量钳到非负，否则登录用户传负数即可把自己的用量改回去；
--      3. 计数只能经这三个函数改动，表的直插/直改权限对客户端全部撤销。
--    时区：以 Asia/Shanghai 划分自然日，与用户的直觉一致（UTC 会在早上 8 点翻篇）。
-- ============================================================

alter table public.profiles
    add column if not exists vision_calls_per_day       integer not null default 5,
    add column if not exists vision_tokens_per_day      bigint  not null default 100000,
    add column if not exists vision_max_tokens_per_call integer not null default 20000;

create table if not exists public.vision_usage (
    user_id           uuid    not null references auth.users(id) on delete cascade,
    day               date    not null default ((now() at time zone 'Asia/Shanghai')::date),
    calls             integer not null default 0,
    prompt_tokens     bigint  not null default 0,
    completion_tokens bigint  not null default 0,
    reasoning_tokens  bigint  not null default 0,
    total_tokens      bigint  not null default 0,
    updated_at        timestamptz not null default now(),
    primary key (user_id, day)
);

create index if not exists vision_usage_day_idx on public.vision_usage (day);

alter table public.vision_usage enable row level security;

-- 只读自己那行；写入一律经函数，故不建 insert/update 策略
drop policy if exists "vision_usage_select_self" on public.vision_usage;
create policy "vision_usage_select_self"
    on public.vision_usage for select
    to authenticated
    using (auth.uid() = user_id);

revoke insert, update, delete on public.vision_usage from authenticated, anon;

-- 8.1 查询今日配额状态（只读，不改计数）
create or replace function public.get_vision_quota()
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
    v_uid      uuid := auth.uid();
    v_day      date := (now() at time zone 'Asia/Shanghai')::date;
    v_calls    integer;
    v_tokens   bigint;
    v_max_call integer;
    v_used_c   integer := 0;
    v_used_t   bigint := 0;
begin
    if v_uid is null then
        return jsonb_build_object('ok', false, 'error', '未登录');
    end if;
    select vision_calls_per_day, vision_tokens_per_day, vision_max_tokens_per_call
      into v_calls, v_tokens, v_max_call
      from public.profiles where user_id = v_uid;
    v_calls    := coalesce(v_calls, 5);
    v_tokens   := coalesce(v_tokens, 100000);
    v_max_call := coalesce(v_max_call, 20000);

    select calls, total_tokens into v_used_c, v_used_t
      from public.vision_usage where user_id = v_uid and day = v_day;
    v_used_c := coalesce(v_used_c, 0);
    v_used_t := coalesce(v_used_t, 0);

    return jsonb_build_object(
        'ok', true,
        'calls_limit', v_calls,
        'calls_used', v_used_c,
        'calls_remaining', greatest(v_calls - v_used_c, 0),
        'tokens_limit', v_tokens,
        'tokens_used', v_used_t,
        'tokens_remaining', greatest(v_tokens - v_used_t, 0),
        'max_tokens_per_call', v_max_call,
        'day', v_day
    );
end;
$$;

-- 8.2 开始一次调用：原子地检查并占用一次次数（先占后用，防并发穿透）
--     token 的实际用量由调用返回后的 record_vision_usage 补记。
create or replace function public.begin_vision_call()
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
    v_uid      uuid := auth.uid();
    v_day      date := (now() at time zone 'Asia/Shanghai')::date;
    v_calls    integer;
    v_tokens   bigint;
    v_max_call integer;
    v_used_c   integer;
    v_used_t   bigint;
begin
    if v_uid is null then
        return jsonb_build_object('ok', false, 'allowed', false, 'message', '未登录');
    end if;
    -- 锁住本用户的 profiles 行，串行化并发调用（与 save_dataset 同法）
    select vision_calls_per_day, vision_tokens_per_day, vision_max_tokens_per_call
      into v_calls, v_tokens, v_max_call
      from public.profiles where user_id = v_uid
       for update;
    v_calls    := coalesce(v_calls, 5);
    v_tokens   := coalesce(v_tokens, 100000);
    v_max_call := coalesce(v_max_call, 20000);

    select calls, total_tokens into v_used_c, v_used_t
      from public.vision_usage where user_id = v_uid and day = v_day
       for update;
    v_used_c := coalesce(v_used_c, 0);
    v_used_t := coalesce(v_used_t, 0);

    if v_used_c >= v_calls then
        return jsonb_build_object('ok', true, 'allowed', false, 'reason', 'calls',
            'message', format('今日读图次数已用完（%d 次）。次日重置，或请管理员调整配额。', v_calls),
            'calls_limit', v_calls, 'calls_used', v_used_c, 'calls_remaining', 0,
            'tokens_limit', v_tokens, 'tokens_used', v_used_t,
            'tokens_remaining', greatest(v_tokens - v_used_t, 0),
            'max_tokens_per_call', v_max_call, 'day', v_day);
    end if;
    if v_used_t >= v_tokens then
        return jsonb_build_object('ok', true, 'allowed', false, 'reason', 'tokens',
            'message', format('今日读图 token 配额已用完（%s）。次日重置，或请管理员调整配额。', v_tokens),
            'calls_limit', v_calls, 'calls_used', v_used_c,
            'calls_remaining', greatest(v_calls - v_used_c, 0),
            'tokens_limit', v_tokens, 'tokens_used', v_used_t, 'tokens_remaining', 0,
            'max_tokens_per_call', v_max_call, 'day', v_day);
    end if;

    insert into public.vision_usage (user_id, day, calls)
    values (v_uid, v_day, 1)
    on conflict (user_id, day) do update
        set calls = public.vision_usage.calls + 1,
            updated_at = now();

    return jsonb_build_object('ok', true, 'allowed', true, 'message', '',
        'calls_limit', v_calls, 'calls_used', v_used_c + 1,
        'calls_remaining', greatest(v_calls - v_used_c - 1, 0),
        'tokens_limit', v_tokens, 'tokens_used', v_used_t,
        'tokens_remaining', greatest(v_tokens - v_used_t, 0),
        'max_tokens_per_call', v_max_call, 'day', v_day);
end;
$$;

-- 8.3 调用返回后补记实际用量。成功与失败都要记——失败同样被服务商计费。
--     负数一律钳到 0（安全要求 2），否则可反向冲销自己的用量。
create or replace function public.record_vision_usage(
    p_prompt bigint, p_completion bigint, p_reasoning bigint, p_total bigint)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
    v_uid uuid := auth.uid();
    v_day date := (now() at time zone 'Asia/Shanghai')::date;
    v_p   bigint := greatest(coalesce(p_prompt, 0), 0);
    v_c   bigint := greatest(coalesce(p_completion, 0), 0);
    v_r   bigint := greatest(coalesce(p_reasoning, 0), 0);
    v_t   bigint := greatest(coalesce(p_total, 0), 0);
begin
    if v_uid is null then
        return jsonb_build_object('ok', false, 'error', '未登录');
    end if;
    if v_t = 0 then
        v_t := v_p + v_c;
    end if;
    insert into public.vision_usage
        (user_id, day, prompt_tokens, completion_tokens, reasoning_tokens, total_tokens)
    values (v_uid, v_day, v_p, v_c, v_r, v_t)
    on conflict (user_id, day) do update
        set prompt_tokens     = public.vision_usage.prompt_tokens + excluded.prompt_tokens,
            completion_tokens = public.vision_usage.completion_tokens + excluded.completion_tokens,
            reasoning_tokens  = public.vision_usage.reasoning_tokens + excluded.reasoning_tokens,
            total_tokens      = public.vision_usage.total_tokens + excluded.total_tokens,
            updated_at        = now();
    return public.get_vision_quota();
end;
$$;

-- 安全修复（沿用 P2-2 的做法）：先收回默认的 PUBLIC 执行权，再按需授予
revoke execute on function public.get_vision_quota() from public;
revoke execute on function public.begin_vision_call() from public;
revoke execute on function public.record_vision_usage(bigint, bigint, bigint, bigint) from public;
grant execute on function public.get_vision_quota() to authenticated, service_role;
grant execute on function public.begin_vision_call() to authenticated, service_role;
grant execute on function public.record_vision_usage(bigint, bigint, bigint, bigint)
    to authenticated, service_role;

-- 管理员按用户调配额：profiles 的 update 权限此前已从 authenticated 撤销
-- （见第 2 节的 P0-3 修复），因此只有 service_role（管理员面板）能改这三列。
