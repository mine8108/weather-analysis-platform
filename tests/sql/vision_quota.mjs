// Real PostgreSQL SQL execution, emulated Auth claims, no production connection.
import { PGlite } from '@electric-sql/pglite';
import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
const db = new PGlite();
await db.exec(`
create role anon; create role authenticated; create role service_role bypassrls;
grant usage on schema public to anon, authenticated, service_role;
alter default privileges in schema public grant all on tables to anon, authenticated, service_role;
alter default privileges in schema public grant all on sequences to anon, authenticated, service_role;
alter default privileges in schema public grant execute on functions to anon, authenticated, service_role;
create schema auth; grant usage on schema auth to anon, authenticated, service_role;
create table auth.users (id uuid primary key);
create function auth.uid() returns uuid language sql stable as
$$select nullif(current_setting('review.uid', true), '')::uuid$$;
create function auth.role() returns text language sql stable as
$$select coalesce(nullif(current_setting('review.role', true), ''), 'authenticated')$$;
`);
const schema = readFileSync(new URL('../../sql/schema.sql', import.meta.url), 'utf8');
await db.exec(schema);
const uid = '00000000-0000-0000-0000-000000000001';
const uid2 = '00000000-0000-0000-0000-000000000002';
await db.exec(`insert into auth.users values ('${uid}'), ('${uid2}');
select set_config('review.uid', '${uid}', false); set role authenticated;`);
const call = async (sql, args=[]) => (await db.query(sql, args)).rows[0].r;
const first = await call('select public.begin_vision_call() as r');
assert.equal(first.allowed, true);
assert.equal(first.reserved_tokens, 80000);
const second = await call('select public.begin_vision_call() as r');
assert.equal(second.allowed, false);
assert.equal(second.reason, 'tokens');
assert.equal((await call('select public.get_vision_quota() as r')).tokens_remaining, 0);
console.log('PASS: interleaved starts cannot spend the same budget twice');

await assert.rejects(db.query('select public.settle_vision_call($1,0,0,0,0)', [first.call_id]), /permission denied/);
await assert.rejects(db.query('select public.record_vision_usage(0,0,0,0)'), /permission denied/);
await assert.rejects(db.query('update public.vision_calls set settled=true'), /permission denied/);
console.log('PASS: authenticated callers cannot forge settlement or release reservations');

await db.exec("reset role; set role service_role; select set_config('review.role','service_role',false);");
const settle = (id, total) => call('select public.settle_vision_call($1,0,0,0,$2) as r', [id, total]);
await settle(first.call_id, 72000);
assert.equal((await settle(first.call_id, 72000)).already_settled, true);
await db.exec("reset role; set role authenticated; select set_config('review.role','authenticated',false);");
const third = await call('select public.begin_vision_call() as r');
assert.equal(third.reserved_tokens, 8000);
await db.exec("reset role; set role service_role; select set_config('review.role','service_role',false);");
await settle(third.call_id, null); // unknown usage conservatively consumes the full reservation
await db.exec("reset role; set role authenticated; select set_config('review.role','authenticated',false);");
const quota = await call('select public.get_vision_quota() as r');
assert.equal(quota.tokens_used, 80000);
assert.equal(quota.tokens_remaining, 0);
assert.equal(quota.tokens_reserved, 0);
console.log('PASS: idempotent settlement, unused-budget release, unknown-usage accounting');

await db.exec(`reset role; update public.profiles set vision_calls_per_day=2 where user_id='${uid}'; set role authenticated;`);
const denied = await call('select public.begin_vision_call() as r');
assert.equal(denied.allowed, false);
assert.equal(denied.reason, 'calls');
assert.match(denied.message, /2 次/);
console.log('PASS: exhausted calls return a denial without format exceptions');

// Cross-day settlement must change the call's original day, not today's counter.
await db.exec(`reset role; select set_config('review.uid','${uid2}',false); set role authenticated;`);
const old = await call('select public.begin_vision_call() as r');
await db.exec(`reset role;
update public.vision_usage set day=day-1 where user_id='${uid2}';
update public.vision_calls set day=day-1 where id='${old.call_id}';
set role service_role; select set_config('review.role','service_role',false);`);
await settle(old.call_id, 1000);
const previous = (await db.query('select total_tokens,reserved_tokens from public.vision_usage where user_id=$1',[uid2])).rows[0];
assert.equal(previous.total_tokens, 1000);
assert.equal(previous.reserved_tokens, 0);
await db.exec("reset role; set role authenticated; select set_config('review.role','authenticated',false);");
assert.equal((await call('select public.get_vision_quota() as r')).tokens_remaining, 80000);
console.log('PASS: cross-day settlement preserves the original accounting day');

await db.exec(`reset role; update public.profiles set vision_calls_per_day=5, vision_tokens_per_day=100000 where user_id='${uid2}';`);
await db.exec(schema);
const profile = (await db.query('select vision_calls_per_day,vision_tokens_per_day from public.profiles where user_id=$1',[uid2])).rows[0];
assert.equal(profile.vision_calls_per_day, 5);
assert.equal(profile.vision_tokens_per_day, 100000);
await db.exec(`insert into public.datasets(user_id,name,csv_text) values ('${uid}','one','x'),('${uid2}','two','x');
select set_config('review.uid','${uid}',false); set role authenticated;`);
assert.deepEqual((await db.query('select name from public.datasets')).rows, [{name:'one'}]);
console.log('PASS: schema rerun preserves custom quotas and dataset RLS isolation');
await db.close();
