# 运行时与部署结构审计（C 组）

范围：`app.py`、`auth.py`、`db.py`、`utils.py`、`config.py`、`modules/supabase_backend.py`、`modules/gfs_cache.py`、`modules/chart_reader.py`、`modules/ai_narrative.py`、`modules/nwp_forecast.py`、`modules/city_prefs.py`、`modules/theme_aether.py`、`modules/analyzer.py`、`sql/schema.sql`、`.streamlit/`、`.github/workflows/`、`requirements.txt`、`runtime.txt`。

方法：只读代码审计，逐条给出 `file:line` 与 ≤15 行片段；未连接线上库，未执行任何 Streamlit/Supabase 运行时（本机解释器无 `streamlit`/`supabase` 包），涉及平台行为的结论标注了来源与未验证项。

基线文档（已读，已修复项不重复）：`SECURITY.md`、`research/supabase-体检-2026-10-18.md`（S1–S18 及批次 1–4）、`research/内部不一致清单-2026-09-13.md`、`docs/superpowers/plans/2026-10-18-supabase-hardening.md`。

---

## 一句话结论

**RLS、函数授权、缓存写入收口这一层已经扎实；剩下的裂口几乎全部在「应用进程」这一侧：配额在依赖故障时放行为 0 成本、token 维度不是硬上限、进程级全局状态把单个用户的设置扩散到全部会话，而会话、内存、发布与观测都没有为「多用户 + 单进程 + 免费层」这个真实运行环境设计。**

---

## 0. 覆盖矩阵（任务 10 项 → 结论编号）

| 任务项 | 结论 | 编号 |
|---|---|---|
| 1 数据访问分层与多套客户端/错误处理 | 一个 anon 客户端工厂，但错误处理有 5 套契约，失败被当空结果缓存 | S2-1、S2-2 |
| 2 service_role 边界 | 边界成立，客户端无触达路径；缺统一出口、无调用审计、轮换无运行手册 | 边界图、S3-1、S3-2 |
| 3 缓存结构（键/失效/写入/投毒） | 写入单点、投毒面已关；残留为读路径不校验形状、键可枚举、无单飞 | S2-3、S2-4、S2-5 |
| 4 配额结构（原子性/失败计费/刷新/双维度） | 次数维度原子且刷新不可绕；故障放行与 token 非硬上限是真裂口 | S1-1、S1-2、S3-7、S3-10 |
| 5 会话与凭据 | 每会话客户端正确；失效处理下沉数据层、判定靠字符串、刷新即回登录页 | S2-2、S2-9 |
| 6 Streamlit 运行模型 | 单进程 + 每会话两个客户端 + 上传内存无上限 → 有明确内存天花板；进程级全局状态跨用户 | S2-7、S2-8、S1-3、S3-5 |
| 7 外部依赖失败隔离 | 页面隔离做得不错；GFS 无单飞、共享出口 IP、空气质量契约冲突、LLM 无熔断 | S2-5、S2-6 |
| 8 日志与可观测性 | 没有日志配置、没有指标、没有请求追踪，管理员面板是唯一仪表盘 | S2-11、S3-9 |
| 9 依赖与发布 | 主依赖已锁；两个直接依赖是范围；CI 门禁不含 app 启动；schema 与代码无联动 | S2-10、S3-4 |
| 10 Streamlit Cloud 限制 | config.toml 的部分开关被平台覆盖；文件系统持久化是假象；内存与单进程约束未在代码里体现 | S2-7、S2-8、S3-3 |

---

## 1. 信任边界图（文字版）

```
浏览器（Streamlit 前端）
  │  WebSocket 上行：只发控件事件；服务端返回 HTML/Delta
  │  本地无 token、无 cookie、无 localStorage（登录态只在服务端 session_state）
  ▼
Streamlit Cloud 单进程（所有会话共享 1 个 Python 进程、1 份模块全局、1 个 $HOME）
  ├─ 会话 A ── anon 客户端(每会话新建, 携带 A 的 JWT) ──┐
  ├─ 会话 B ── anon 客户端(每会话新建, 携带 B 的 JWT) ──┤
  ├─ 会话 A ── service_role 客户端(按需新建, 仅服务端) ─┤
  ├─ 会话 B ── service_role 客户端(按需新建, 仅服务端) ─┤
  │                                                     ▼
  │                                        Supabase（唯一信任边界）
  │                                        RLS + SECURITY DEFINER + EXECUTE 授权
  │                                        anon key 公开，service_role key 只在 Secrets
  │
  ├─ 进程级全局：CUSTOM_THRESHOLDS、_ADMIN_FAILS/_ADMIN_LOCKED_UNTIL、
  │              st.cache_data 全局缓存、$HOME/.aether_theme.json、
  │              $HOME/.weather_wall_cities.json
  │              ↑ 会话隔离不覆盖这里
  │
  └─ 对外同步调用（共用一个容器出口 IP）：
        api.open-meteo.com / archive-api / air-quality-api   ← 免费配额按 IP 计
        LLM 多模态服务（部署方 API Key 计费，失败也计费）
        fonts.googleapis.com（前端加载，不影响后端）
        CDS/ERA5：仅生成脚本，运行期不调用
```

信任边界有三层，实际只有一层是硬的：浏览器→Streamlit 由 Streamlit 自身会话隔离；Streamlit 进程内→Supabase 由 RLS 承担；**Streamlit 进程内部没有第二道墙**，任何模块都能 `from auth import get_supabase_admin` 拿 service_role 客户端，进程级全局对全部会话可见。

---

## 2. 已修复 / 已裁决项（本次不重复）

| 体检编号 | 状态 | 本次审计的增量结论 |
|---|---|---|
| S1 信任边界不可自证 | 已加 `security_selfcheck()` | 自检仍只在管理员解锁时跑；普通请求没有任何 schema 版本校验，见 S2-10 |
| S2 缓存一小时永久失效 | 已改 `updated_at` | 已成立；会话内第一层缓存反而永不过期，见 S3-5 |
| S3 缓存投毒/占键 | 写入收口到 service_role | 用户侧投毒路径关闭；读路径不校验数据形状，见 S2-3 |
| S4 存储配额绕过 | 已修 | 未发现回退 |
| S5 会话过期静默降级 | 已加 `is_session_error`/`expire_session` | 修法本身分层错误且在缓存内，见 S2-2、S2-9 |
| S6 异常静默 | 已加 logging | 只有 `warning` 落到 Streamlit 日志，无格式、无指标，见 S2-11 |
| S7 rerun 三个同步 RPC | 已加 30 秒缓存 | 读图页的 `get_vision_quota` 仍未缓存，每次 rerun 一个 RPC，见 S3-7 |
| S8 键精度 | 已归一到 0.01° | 未加进程内共享缓存，见 S2-5 |
| S9 邀请码强度 | 已 128 bit | 未发现问题 |
| S10 管理员双轨 | 已加审计表 | 审计只记成功、无操作者，见 S3-8 |
| S11 迁移无版本 | 已加 `schema_version` | 版本号与代码无联动，见 S2-10 |
| S12 保活与备份 | 已 ping Supabase | 备份仍无（本次不展开，属运维流程） |
| S13 缓存可枚举 | 表级 select 已收回 | 键可预测，RPC 仍是一个枚举 oracle，见 S2-4 |
| S14 用户分页 | 已修 | 未发现问题 |
| S15 缺档案行 | 已补行 | 未发现问题 |
| S16 CHECK 约束 | 已加 16 条 | 未发现问题 |
| S17 依赖未锁 | 已锁 supabase | `Pillow`/`markdown-it-py` 仍是范围，见 S3-4 |
| S18 目录改名 | 已改 `sql/` | 未发现问题 |

---

## 3. S1 结构性（会导致数据不一致、越权、不可恢复故障或容量天花板）

### S1-1 配额服务故障时整体放行，成本约束退化为「刷新即重置」

**证据 1** `modules/chart_reader.py:217-224`（故障 → 放行）

```python
def quota_allows(state):
    """(是否放行, 提示文本)。state 为 None 表示配额服务不可用。"""
    if not state:
        return True, ("⚠️ 配额服务不可用（若刚升级版本，请先重跑 "
                      "sql/schema.sql），本次按会话级限制放行。")
    if state.get("allowed"):
        return True, ""
    return False, str(state.get("message") or "今日读图配额已用完。")
```

**证据 2** `modules/chart_reader.py:384-403`（放行后只受会话级 5 次/60 秒约束）

```python
    now = time.time()
    last = float(st.session_state.get("chart_reader_last_gen", 0) or 0)
    if now - last < MIN_INTERVAL_SECONDS:
        st.warning("生成过于频繁，请 %d 秒后再试。" ...)
        return
    count = int(st.session_state.get("chart_reader_gen_count", 0) or 0)
    if count >= MAX_GENERATIONS_PER_SESSION:
        ...
        return
    quota_state = begin_vision_call()
    allowed, notice = quota_allows(quota_state)
    ...
    budget = quota_budget(quota_state, VISION_MAX_TOKENS)
```

**证据 3** `db.py:211-229`（任何异常都折叠成 `None`，与「配额用完」共用同一个空值通道）

```python
    try:
        res = sb.rpc(name, params or {}).execute()
        data = res.data if hasattr(res, "data") else res
        if isinstance(data, list):
            data = data[0] if data else None
        if isinstance(data, dict) and data.get("ok"):
            return data
        return None
    except Exception as exc:
        _LOG.warning("读图配额 RPC %s 失败", name, exc_info=True)
        if is_session_error(exc):
            expire_session()
        return None
```

**证据 4** `auth.py:257-264`（Supabase 不可达时保留登录态，用户仍能进入读图页）

```python
    except Exception as exc:
        if is_session_error(exc):
            expire_session()
        else:
            _LOG.warning("会话校验失败，保留当前登录态", exc_info=True)
        return
```

三条链路叠加后，故障期间的状态是：用户仍是登录态 → 读图页照常渲染 → `begin_vision_call()` 返回 `None` → 页面明确提示「本次按会话级限制放行」 → 用户刷新即再得 5 次，间隔 60 秒可无限续。

**a) 根因**
配额的硬状态与鉴权、存储放在同一个数据库依赖上，而失败语义被设计成「放行」；替代约束放在 `st.session_state`，属于用户可重置的客户端级状态。进程内没有任何跨会话的兜底计数器。

**b) 不修的长期代价与触发条件**
读图调用用部署方 API Key 计费，失守的是真金白银。触发条件都已存在：
1. Supabase Free 计划长期无活动被暂停（`keep-alive.yml` 每 6 小时 ping 一次，只能降低概率）；
2. 发布新代码后忘记重跑 `schema.sql`（`SECURITY.md:28` 自己把这条写成已知故障模式）；
3. Supabase 区域故障或 PostgREST 5xx。
这三种情况下 `begin_vision_call` 全部返回 `None`，而 LLM 服务是独立供应商，通常仍可用。按单次 2 万输出 token 计，一个以 60 秒间隔刷新并生成的会话每小时约 60 次调用，一天理论上可到约 2900 万 token（实际还受供应商速率限制与人工操作速度约束），账单在月底才会暴露，期间没有任何告警。

**c) 最小修复切口**
`chart_reader.py` 一个文件、约 15 行：用模块级字典 `_LOCAL_QUOTA = {"day": date, "calls": 0}` 做进程级兜底（单进程部署下它就是全局限流），`quota_state is None` 时走它，超阈值直接 `st.stop()` 或禁用按钮并提示「配额服务不可用，请稍后重试」。不引入新依赖，不改 schema。

**d) 保留现状的理由（对抗性）**
放行是刻意的，`tests/test_vision_quota.py:189-197` 专门锁定了「放行 + 明确提示」这个契约；用户体验上，一次数据库抖动不该把读图功能整体锁死。当前用户来自邀请码，人数少，恶意刷新的动机弱。
反向意见：同一份审计文档已经把「故障诱导的绕过」列为 S5/S6，说明故障态不是罕见态；手册第 9 章又把每日配额写成「硬约束」。一个在故障时静默失效的硬约束，比一开始就声明「次数是硬约束、token 是软约束」更危险。最低成本是在故障态把会话次数从 5 次降到 1 次，而不是完全放行。

---

### S1-2 token 维度不是硬上限，真实成本上限是「次数 × 单次上限」

**证据 1** `sql/schema.sql:753-774`（准入只卡次数，token 只读不预留，然后只给 calls +1）

```sql
    if v_used_c >= v_calls then
        return jsonb_build_object('ok', true, 'allowed', false, 'reason', 'calls', ...);
    end if;
    if v_used_t >= v_tokens then
        return jsonb_build_object('ok', true, 'allowed', false, 'reason', 'tokens', ...);
    end if;

    insert into public.vision_usage (user_id, day, calls)
    values (v_uid, v_day, 1)
    on conflict (user_id, day) do update
        set calls = public.vision_usage.calls + 1,
            updated_at = now();
```

**证据 2** `modules/chart_reader.py:403`（预算取单次上限，不看剩余 token）

```python
    budget = quota_budget(quota_state, VISION_MAX_TOKENS)
```

**证据 3** `modules/chart_reader.py:361-375`（token 记账在调用之后，写失败只提示）

```python
def _record_usage(usage):
    ...
    if not record_vision_usage(usage):
        st.caption("⚠️ 本次用量未能写入服务端配额，管理员看到的今日用量可能偏低。")
```

**证据 4** `auth.py:710-725`（管理员可把次数调到 200，token 上限可到 1 亿，单次上限可到 32000）

```python
            with vc1:
                calls_day = st.number_input(
                    "每日次数", min_value=0, max_value=200, step=1,
                    value=int(prof_row.get("vision_calls_per_day", 5) or 0),
                    key="vq_calls")
```

**a) 根因**
准入控制只对次数做原子预留，token 采用「先调用后补记」的后付费模型，没有任何预留或结算机制；单次输出预算独立于当日剩余额度。默认配置（5 次 × 20000）恰好等于 10 万 token 上限，掩盖了结构问题。

**b) 不修的长期代价与触发条件**
触发条件是一次完全正常的运营操作：管理员为某个重度用户把「每日次数」从 5 调到 50 或 200，token 上限没动。此时真实可消耗量变成 `calls × (max_tokens_per_call + prompt_tokens)`，50 次 × 2.2 万 ≈ 110 万 token，是声明额度的 11 倍；200 次时约 44 倍。另一种触发是用户在调用中途关闭标签页，脚本线程中断，`record_vision_usage` 不再执行，token 已经花掉但不入账，token 维度永久偏低。
长期代价是「配额面板显示的剩余额度」与「实际可发生的支出」脱钩，管理员基于错误数字做成本决策；手册 `docs/用户使用手册.md:452` 明确写「token 用尽后生成按钮直接禁用」「token 是硬约束」，这条承诺在管理员改过配置后即不成立。

**c) 最小修复切口**
`begin_vision_call` 返回 `per_call_budget = least(v_max_call, greatest(v_tokens - v_used_t - 2000, 0))`，剩余不足 2000 时直接返回 `allowed=false`；`chart_reader._generate` 用返回值里的预算覆盖 `quota_budget`。SQL 改 3 行，Python 改 2 行，不需要新增表。

**d) 保留现状的理由（对抗性）**
默认配置下次数与 token 两个维度刚好自洽，绝大多数用户每天 5 次、每次几千 token，永远碰不到 token 线；把 token 做成硬上限会在已经很少的调用里多一次拒绝。管理员面板本身是受 `ADMIN_PASSWORD` 保护的可信路径。
反向意见：这个「刚好自洽」只依赖默认值，`auth.py:712-725` 允许的配置空间已经越界；而「失败也计费」的设计使 token 记账比次数更容易漏。最小切口不改默认行为，只在管理员改配置时保持两个维度一致，代价接近零。

---

### S1-3 进程级全局阈值把单个用户的分析口径扩散到所有会话

**证据 1** `modules/analyzer.py:24-31`

```python
# 可配置的事件检测规则（用户可在侧边栏自定义覆盖）
CUSTOM_THRESHOLDS = {}


def set_custom_thresholds(custom):
    global CUSTOM_THRESHOLDS
    CUSTOM_THRESHOLDS = custom
```

**证据 2** `app.py:599-601`（任意登录用户的点击直接改模块全局）

```python
        if st.button("[OK] 应用自定义阈值", use_container_width=True):
            set_custom_thresholds(custom)
            st.success("自定义阈值已应用！")
```

**证据 3** `modules/analyzer.py:68`、`136`、`187`、`223`、`256`、`301`、`335`、`379`（8 个检测函数都读同一个全局）

```python
    custom = CUSTOM_THRESHOLDS.get("high_temp", {})
```

**证据 4** `docs/用户使用手册.md:802`（已知且已披露）

> 关于作用域：界面上的说明写的是「仅影响当前会话」，实现上阈值存放在分析模块的进程级全局变量中，因此它会一直生效到你再次点击「应用自定义阈值」覆盖，且同一服务进程内的其他会话也会看到同一套阈值。

**a) 根因**
多租户进程里用了模块级可变状态。Streamlit 的 `st.session_state` 才是会话作用域，模块全局是进程作用域；单进程部署把「进程」放大成「全部在线用户」。

**b) 不修的长期代价与触发条件**
触发条件是任意用户点一次「应用自定义阈值」，影响是即时的、静默的、持久的：之后所有会话的高温、寒潮、大风、雾、暴雨、霜冻、雷暴、霾 8 类检测全部按 A 的阈值执行，B 的分析结论、`quality_score`、导出的 Word 报告里的预警章节都基于别人的口径，直到进程重启或下一个人再点一次。这类错误不会报错、不会留痕，比崩溃更难发现。
长期代价是分析结果不可复现、不可追责，且两个用户同时看同一份数据会得到不同的告警结论；一旦线上被人截图对比，平台的可信度直接受损。

**c) 最小修复切口**
`analyzer` 增加 `def current_thresholds():`，优先读 `st.session_state.get("_custom_thresholds")`，取不到再退回模块全局（保证测试直跑）；`app.py` 的按钮改写 session_state；8 个读点各改一行。约 30 行，不动检测算法。

**d) 保留现状的理由（对抗性）**
手册已经披露；部署形态是「个人分析平台」，邀请码制、用户数少，真正常用的可能只有部署者本人；阈值是低频操作。改动会碰 8 个检测函数和它们的测试，回归面比收益大。
反向意见：这个应用已经把数据集、配额、读图用量全部按用户隔离，说明多用户是设计目标；阈值是唯一一个「看起来会话级、实际全局」的状态，留着它就是留一个会静默产出错误报告的开关。最小切口只加一个取值函数，检测函数体不改。

---

## 4. S2 局部但会扩散

### S2-1 数据访问层五套错误契约，失败被当作空结果缓存 30 秒

**证据 1** `db.py:82-97`（统一返回默认值，异常吞掉后记录日志）

```python
def _scalar_rpc(name: str, default: int, uid: str | None = None) -> int:
    """调用返回单个整数的 RPC；未登录、客户端缺失或异常一律返回默认值。"""
    uid = uid or _user_id()
    if uid is None:
        return default
    sb = get_supabase()
    if sb is None:
        return default
    try:
        res = sb.rpc(name, {"p_user_id": uid}).execute()
        return int(res.data or default)
    except Exception as exc:
        _LOG.warning("存储 RPC %s 失败", name, exc_info=True)
```

**证据 2** `db.py:100-113`（默认值结果进入全局缓存，30 秒内所有 rerun 都看到「失败 = 空」）

```python
@st.cache_data(ttl=30, show_spinner=False)
def get_storage_usage_bytes(uid: str) -> int:
    """返回指定用户已用存储字节数（30 秒缓存，按 uid 隔离）。"""
    return _scalar_rpc("get_storage_usage", 0, uid)
```

**证据 3** `db.py:112-133`（失败返回 `[]` 并被缓存）；同类契约还有 `auth.py:42-52`（secrets 异常静默返回空串）、`modules/gfs_cache.py:45-47`（读缓存异常返回 None）、`modules/nwp_forecast.py:152-181`（缓存读写异常只记日志）、`utils.py:162-175`（错误文本默认脱敏成一句通用话）

```python
@st.cache_data(ttl=30, show_spinner=False)
def list_datasets(uid: str):
    ...
    except Exception as exc:
        _LOG.warning("列出数据集失败", exc_info=True)
        if is_session_error(exc):
            expire_session()
        return []
```

**a) 根因**
每个调用点各自决定「失败时返回什么」：`0`、`[]`、`False`、`None`、`st.stop()`、`st.error()`、静默。没有统一的 `Result` 或异常分类；同时读路径用 `st.cache_data` 缓存「吞掉异常后的默认值」，把瞬时故障固化成一个 30 秒的错误事实。

**b) 不修的长期代价与触发条件**
触发条件是任意一次 Supabase 抖动（5xx、连接超时、PostgREST 重启）。后果分三层：侧边栏显示「云存储 0.0 / 10 MB」「暂无数据」；读图页显示「配额服务不可用」；GFS 缓存静默回退实时请求。用户已在页面上做了后续操作（比如以为数据丢了又保存一次），30 秒后缓存过期，页面突然变成真实数字，产生「数据自己变了」的观感。排障时日志里只有一条中文 warning，没有 uid、没有请求 id、没有次数。

**c) 最小修复切口**
`db.py` 增加一个内部 `_call(fn, default)`，返回 `(ok, value)`，失败时**不把结果写进缓存**（在外面包一层：`res = _call(...); if not ok: return default` 仍会被缓存，因此更简单的做法是让缓存函数在失败时抛一个可识别的 `BackendUnavailable`，由 `app.py` 侧捕获并显示一次性的「云端暂不可用」横幅）。改动集中在 `db.py` 的 5 个函数与 `app.py` 的调用点，约 60 行。

**d) 保留现状的理由（对抗性）**
现有降级策略保证页面不会因为后端抖动而白屏，这在演示场景里是优点；真正的修复需要引入异常类型并在 UI 层统一处理，会碰到 `app.py`、`db.py` 和测试。当前用户数少，30 秒的错误缓存窗口影响有限。
反向意见：错误缓存的窗口不长，但「失败 = 空数据」这个语义会被后续功能继承；每新增一个读接口就多一套默认值。把「后端不可用」做成一个可识别状态，是后续所有可观测性工作的前提。

---

### S2-2 会话失效处理下沉到数据层，且被包在 `st.cache_data` 里

**证据 1** `db.py:13`、`db.py:86-97`（数据层直接改会话并触发重跑）

```python
from auth import expire_session, get_supabase, is_session_error
...
    except Exception as exc:
        _LOG.warning("存储 RPC %s 失败", name, exc_info=True)
        if is_session_error(exc):
            expire_session()
        return default
```

**证据 2** `auth.py:231-235`（`expire_session` 里做 UI 状态机）

```python
def expire_session():
    """会话失效：清空本会话并回到登录页。"""
    sign_out_user()
    st.session_state["auth_error"] = "登录已过期，请重新登录。"
    st.rerun()
```

**证据 3** `research/supabase-体检-2026-10-18.md:250`（上一轮审计已经提出过相反的建议）

> 注意不要在 `db.py` 里直接 `st.rerun()`，数据层不应该依赖 UI 状态机。

**a) 根因**
修复 S5 时选择了「就地处理」而非「上抛统一处理」。`expire_session` 被 `db.py` 的 6 个函数、`auth.ensure_session` 共同调用；其中 `get_storage_usage_bytes`、`get_storage_quota_bytes`、`list_datasets` 三个函数带 `@st.cache_data(ttl=30)`，函数体在缓存命中时根本不执行，于是「由 401 发现会话过期」这条路径在 30 秒窗口内不可达。

**b) 不修的长期代价与触发条件**
触发条件是 JWT 过期（Supabase 默认 1 小时）后用户只做侧边栏操作。页面先显示 30 秒的旧缓存，然后某个 miss 触发 `expire_session`，在 RPC 调用栈里执行 `st.rerun()`。副作用是会话清理发生在缓存函数内部：一旦未来把 `expire_session` 换成抛异常或写日志，行为会随缓存命中率变化，测试无法在纯数据层覆盖。更好的问题表述是：会话状态机没有唯一入口，`ensure_session` 只在 app 启动时跑一次，其余 6 处各自为政。

**c) 最小修复切口**
删除 `db.py` 里 6 处 `expire_session()`，改为抛 `SessionExpired`；`app.py` 在 `ensure_session()` 之后包一个 `try: render... except SessionExpired: expire_session()`。约 40 行，行为等价，分层正确。若不想动，至少在 `app.py` 增加一个「本会话已提示过期」的一次性标记，避免缓存窗口内的沉默。

**d) 保留现状的理由（对抗性）**
现在的行为在大多数情况下是对的：401 出现就会跳登录页，用户能看懂。改成异常传播会碰 6 个函数、`app.py` 主流程和 `tests/test_auth_session.py` 的一组 AppTest，回归成本不低；而 Streamlit 的 rerun 语义在缓存函数里实际能工作（异常会中断当前脚本）。
反向意见：这条的价值不在当前故障率，而在后续维护成本。数据层一旦依赖 `st.rerun`，任何后台任务、脚本化测试、批量校验都无法直接复用它。最小切口可以只做一半：把 `expire_session` 调用换成 `raise SessionExpired`，在 `app.py` 一处兜底。

---

### S2-3 GFS 缓存读取不校验数据形状，写入端只校验 `timestamp` 存在

**证据 1** `sql/schema.sql:485-492`（写入校验只要求是对象且有 timestamp）

```sql
    if exists (
        select 1
          from jsonb_array_elements(p_data) as elem(value)
         where jsonb_typeof(elem.value) <> 'object'
            or elem.value ->> 'timestamp' is null
    ) then
        return false;
    end if;
```

**证据 2** `modules/nwp_forecast.py:116-126`（读路径直接信任缓存内容建 DataFrame）

```python
def _gfs_records_to_df(records):
    """list[dict] -> DataFrame（timestamp 转回 datetime）"""
    df = pd.DataFrame(records)
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df
```

**证据 3** `modules/nwp_forecast.py:81-110`（列集合变更只靠手工改版本号，与 SQL 正则绑定）

```python
# 数据 schema 版本：列集合变化时递增，使旧缓存（如缺 wind_direction 列）失效强制重拉
_GFS_FC_SCHEMA_VERSION = "v3"
...
    return (f"gfs_fc_cache_{_GFS_FC_SCHEMA_VERSION}_{cache_lat:.4f}_"
            f"{cache_lon:.4f}_{wpart}_{model_part}")
```

**a) 根因**
缓存键里带版本号，但版本号是人工纪律而非运行时不变量；写入端和读取端都不校验列集合。缓存被当作可信数据源，而它的生产者是上游 API 的响应结构。

**b) 不修的长期代价与触发条件**
两个触发条件都会发生：开发时改了 `_FC_HOURLY` 却忘记改版本号；Open-Meteo 某次响应缺列或改名（该 API 有过字段调整历史）。后果是：一行缺列的数据被写入后，1 小时内所有落到同一 0.01° 网格的用户都会拿到缺列的 DataFrame，下游 `h["wind_direction_10m"]` 之类的读取抛 `KeyError`，被 `app.py:78-84` 的 tab 边界捕获成「页面加载出现异常」——用户看到的是整块功能消失，日志里只有一行 warning。缓存过期后自愈，所以这类故障会以「时好时坏」的形式反复出现。

**c) 最小修复切口**
`put_gfs_cache` 增加列集合校验（`p_data -> 0 ? 'temperature'` 等 9 个必需键），或 `_gfs_records_to_df` 在返回前检查必需列，缺列按 miss 处理并记一条 warning（改 10 行，不动 SQL 也可）。同时在 `fetch_gfs_forecast` 写入前用同一份列清单断言，避免写入坏数据。

**d) 保留现状的理由（对抗性）**
上游字段很稳定，版本号机制已经覆盖了已知的一次列变更；校验会增加每次写入的 SQL 复杂度和一次全表扫描式的 JSON 检查（实际是单行，成本可忽略）。现网数据量小，坏行 1 小时就过期。
反向意见：这个故障的表现是「整个 Tab 报错」，用户无法自助判断，而且只影响同坐标的用户，最难排查的一类。读侧加 10 行列检查的收益/成本比很高。

---

### S2-4 `get_gfs_cache` 仍是一个坐标枚举 oracle，与 SECURITY.md 的声明不符

**证据 1** `SECURITY.md:22`

> `gfs_cache`：读只经 `get_gfs_cache(key)` RPC，按精确 key 返回一行，客户端对表没有 select 权限，因此无法枚举他人查询过的坐标

**证据 2** `sql/schema.sql:519-535`（按精确 key 返回，且对所有登录用户开放）

```sql
create or replace function public.get_gfs_cache(p_key text)
returns jsonb
language sql
security definer
set search_path = public
as $$
    select data_json
      from public.gfs_cache
     where cache_key = p_key
       and left(p_key, 13) = 'gfs_fc_cache_'
       and updated_at >= now() - interval '1 hour'
     limit 1;
$$;

revoke execute on function public.get_gfs_cache(text) from public, anon;
grant execute on function public.get_gfs_cache(text)
    to authenticated, service_role;
```

**证据 3** `modules/nwp_forecast.py:97-110`（键完全由公开参数决定）

```python
def _gfs_forecast_cache_key(lat, lon, days, model, window=None):
    model_part = model if model else "blend"
    wpart = window if window else f"d{int(days)}"
    cache_lat, cache_lon = _gfs_cache_coords(lat, lon)
    return (f"gfs_fc_cache_{_GFS_FC_SCHEMA_VERSION}_{cache_lat:.4f}_"
            f"{cache_lon:.4f}_{wpart}_{model_part}")
```

**a) 根因**
把「不能 select 整表」误当成「不能枚举」。键的构造规则写在前端可见的源码里（公开仓库），模型名只有 5 个选项、天数 1–16、经纬度 0.01° 网格，因此任何登录用户都能对任意坐标构造键并观察命中/未命中。`data_json` 本身是公开天气预报，`created_by` 也已被隐藏，所以泄露的是「最近一小时内有人查过这个网格」这一事实。

**b) 不修的长期代价与触发条件**
触发条件：任何拿到邀请码的用户写一个循环，对全国城市网格逐个调用 `get_gfs_cache`，得到「哪些地方最近被查询过」的时间序列。对气象分析场景，查询位置（尤其是个人定位添加的城市）本身可能是敏感信息；这与手册对「按账号隔离」的表述相冲突。当前用户少、动机弱，所以是 S2 而非 S1。

**c) 最小修复切口**
在键里加入一个只有服务端知道的值：`key = HMAC(secret, lat|lon|days|model|window)` 的输出片段，客户端只把参数发给一个 `get_or_fetch_gfs(参数)` RPC（服务端拼键、读缓存、返回），客户端从此拿不到键。这是「体检 S3」里已经预留的方向（「让 key 由数据库根据参数生成」），按当前代码约 60 行 SQL + 20 行 Python。或者最小化：给 `get_gfs_cache` 加一个按 `auth.uid()` 的每小时调用计数表，枚举成本从「免费」变成「计入配额」。
**d) 保留现状的理由（对抗性）**
泄露的是「某个网格被查过」，不是「谁查的」，也不是敏感业务数据；gfs_cache 的数据本身公开。为这个 oracle 引入 HMAC 会同时改键格式、SQL 正则、写入校验和测试，回滚成本高；当前用户来自邀请码，可信度较高。建议登记为「隐私声明与实现对齐」事项，修文档（说清「按精确键读取，键可被猜测」）比改架构便宜。

---

### S2-5 GFS 没有单飞与进程内共享缓存，Open-Meteo 免费配额由全部用户共享同一个出口 IP

**证据 1** `modules/nwp_forecast.py:205-215`（第一层是会话级，第二层是数据库，没有进程级）

```python
    cache_key = _gfs_forecast_cache_key(lat, lon, _days_key, model, window)
    cache_lat, cache_lon = _gfs_cache_coords(lat, lon)
    # 第一层：同一会话内同参数直接命中
    cached = st.session_state.get(cache_key)
    if cached is not None:
        return cached, None
    # 第二层：Supabase 跨用户 / 跨重启共享缓存
    sb_df = _load_gfs_from_cache(cache_key)
    if sb_df is not None:
        st.session_state[cache_key] = sb_df
        return sb_df, None
```

**证据 2** `utils.py:98-113`（失败时的退避全部是同步 sleep，重试在用户会话线程里排队）

```python
                    if attempt < max_retries:
                        if is_429 and retry_after:
                            delay = min(retry_after, max_delay)
                        else:
                            delay = min(base_delay * (backoff_factor ** (attempt - 1)), max_delay)
                        ...
                        time.sleep(delay)
```

**证据 3** Streamlit 官方文档：Community Cloud 的出口 IP 是固定的一组地址（`https://docs.streamlit.io/deploy/streamlit-community-cloud/status`），Open-Meteo 的免费额度按 IP 计。

**a) 根因**
缓存的三层设计里缺了最有效的一层：进程级共享。`st.cache_data` 在 `geocode`、`weather_wall`、`_fetch_gfs_current` 上都用了，唯独最贵的 `fetch_gfs_forecast` 没用。多个会话同时请求同一网格时，每个会话都要先走一次 Supabase RPC，未命中就各自打 Open-Meteo，写入端也是各写各的。

**b) 不修的长期代价与触发条件**
触发条件：一次 429 之后，N 个会话同时重试，退避时间随尝试次数增长（3、6、12 秒），线程被占用，用户看到「请求过于频繁」的红色错误。天气墙有 `st.cache_data(ttl=600)` 保护，数值预报页没有。Open-Meteo 免费配额是共享的，一个用户反复换坐标就能把所有人的额度耗掉，代价由全部用户承担。
长期看，随着用户数增加，命中率下降与 429 上升会同时出现，而 gfs_cache 的 1 小时 TTL 只能挡住「同网格重复请求」，挡不住「首轮并发」。

**c) 最小修复切口**
给 `fetch_gfs_forecast` 的「读」路径加一个模块级 `@st.cache_data(ttl=3600, show_spinner=False)` 包装（键为归一化坐标 + 天数 + 模型），把「从 Supabase 或 Open-Meteo 取」整个包进去；写缓存保持现状。约 20 行，命中时连 Supabase RPC 都省掉。这正是上一轮审计 `S8` 建议过但没有落地的部分。

**d) 保留现状的理由（对抗性）**
`st.cache_data` 在进程内共享，对多用户是好事，但会把「不同用户的请求」合并成一次，如果将来按用户做差异化配额或审计，会掩盖归属；另外 1 小时的内存缓存会占用进程内存（168 行 DataFrame，量很小）。当前用户少、命中率低的问题不突出。
反向意见：这是唯一一个「加一个装饰器就能显著降低外部依赖压力和延迟」的改动，风险是缓存正确性（键必须包含 days/model 与版本号）。已经有 `_gfs_forecast_cache_key` 可直接复用。

---

### S2-6 外部依赖失败语义混入业务返回值：空气质量有缺失字段时整批被当失败丢弃，LLM 失败无熔断

**证据 1** `modules/data_loader.py:614-643`（成功时第二返回值是「缺失字段列表」，失败时是错误字符串，两种语义共用一个位置）

```python
    except requests.exceptions.Timeout:
        return None, "⚠️ API 请求超时，请重试"
    ...
    return df, (missing if missing else None)
```

**证据 2** `modules/data_loader.py:745-751`（`if err:` 先吃掉列表，`elif` 分支里的第二个 `if err` 是死代码）

```python
                    df, err = fetch_open_meteo_air_quality(lat_aq, lon_aq, start_str, end_str)
                if err:
                    st.error(err)
                elif df is not None:
                    st.success(f"[OK] 空气数据: {len(df)} 条记录")
                    if err:
                        st.info(f"部分字段无数据: {', '.join(err)}")
```

**证据 3** `modules/ai_narrative.py:187-204`（LLM 调用 90 秒超时、无重试、无熔断）

```python
    resp = requests.post(
        base_url + "/chat/completions",
        ...
        timeout=VISION_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
```

**a) 根因**
两处都是「把失败信息塞进业务返回值」，缺少统一的失败类型。空气质量的 `missing` 列表在页面侧被当成错误，`elif` 之后的成功分支永远不会在有缺失字段时执行，导致「部分字段无数据」这一正常降级被渲染成整批失败，数据被丢弃。LLM 侧则在供应商故障时每次都等满 90 秒，失败仍先占用了一次日配额。

**b) 不修的长期代价与触发条件**
空气质量触发条件：Open-Meteo 对某个区域或某个时段返回 `null` 列（例如 PM2.5 缺测），`missing` 非空，导入页直接 `st.error(list)` 并且不写入 `session_state`。用户以为接口坏了，实际上数据可用。这是确定性复现，不是偶发。
LLM 触发条件：供应商 5xx 或超时。每次失败最多等满 90 秒、扣一次日配额、`usage` 为空，且没有重试。连续故障时页面看起来「卡住」，用户会连续点击，把当天 5 次配额在几分钟内耗光。

**c) 最小修复切口**
空气质量：把返回值改成 `(df, error)` 三元组或 `(df, missing)` 明确契约，页面去掉 `if err: st.error` 的死分支，改成 `if missing: st.info(...)`。约 10 行。LLM：把 `requests.post` 包一层 1 次重试（仅对 5xx/timeout），并在 `_generate` 失败路径先检查配额是否属于「本次失败应退还」，或至少把失败明确计为一次尝试但不扣 token（当前已是这样，补提示即可）。约 20 行。

**d) 保留现状的理由（对抗性）**
空气质量缺字段的情况少；LLM 供应商整体可用性尚可，90 秒超时比无超时好得多，重试会加剧故障时的负载。用户手册已经把「失败也计费」写成明确预期。
反向意见：空气质量的死分支是一个低成本高确定性的 bug，应该先修；LLM 熔断属于优化，可以延后到有真实故障数据再决定。

---

### S2-7 Streamlit 运行模型下的内存天花板与每会话资源

**证据 1** `auth.py:147-171`（每会话两个客户端，且从不显式关闭）

```python
def _session_client(key_name: str, session_key: str, *, fatal: bool):
    """按会话缓存一个 Supabase 客户端；创建失败返回 None。"""
    cached = st.session_state.get(session_key)
    if cached is not None:
        return cached
    client = _create_client(key_name, fatal=fatal)
    if client is not None:
        st.session_state[session_key] = client
    return client
...
def get_supabase_admin():
    return _session_client(
        "SUPABASE_SERVICE_ROLE_KEY", _SESSION_ADMIN_KEY, fatal=False
    )
```

**证据 2** `modules/chart_reader.py:23-29`、`104-107`（上限在应用层，读取早就发生了）

```python
MAX_IMAGES = 3
MAX_RAW_BYTES = 20 * 1024 * 1024      # 原始字节硬上限，超过直接拒绝，不解码
...
    if len(raw) > MAX_RAW_BYTES:
        return _fail(name, "文件过大（原始 %.2f MB，上限 %.0f MB）..." ...)
```

**证据 3** `.streamlit/config.toml:1-7`（没有 `maxUploadSize`，Cloud 默认允许 200 MB，整份内容先进入内存）

```toml
[server]
headless = true
port = 8501
enableCORS = true
enableXsrfProtection = true
```

**证据 4** `app.py:475-482`（每个新会话自动拉取该用户最近一次保存的完整 CSV）

```python
if st.session_state.get("df") is None and not st.session_state.get("_auto_load_done"):
    st.session_state["_auto_load_done"] = True
    from db import load_latest_dataset
    _auto_df, _auto_name = load_latest_dataset()
```

**a) 根因**
单进程部署下，内存预算要同时容纳「全部会话的客户端对象 + 全部会话的 session_state（含完整数据集与上传图片）+ 全局 `st.cache_data` + PIL 解码峰值」。代码里没有任何总量控制：上传上限只在上传完成之后检查，会话数据没有清理策略，客户端不关闭。

**b) 不修的长期代价与触发条件**
粗算：一个读图会话持有 3 张图 × 最多 20 MB 原始字节 + 处理后字节，PIL 解码阶段单图峰值可达数百 MB（`MAX_PIXELS = 5000 万`，RGB 约 150 MB，加上 resize 副本）；一个导入会话持有完整 DataFrame（10 MB CSV 展开后可达数十到上百 MB）。5–10 个并发重度会话就可能触到免费层的容器内存上限（平台未在文档中承诺具体数值，社区报告为 GB 量级，需在控制台确认），进程被重启，**全部会话同时丢失工作数据，进行中的 LLM 调用仍会被计费**。触发条件是一次集中演示或几个用户同时上传大图。
另一个确定性问题：`maxUploadSize` 未设置时，用户上传 200 MB 文件，Streamlit 先把整份内容读进内存，随后 `chart_reader` 才因超过 20 MB 拒绝。

**c) 最小修复切口**
1) `config.toml` 加 `[server] maxUploadSize = 25`（不改代码，立刻把最坏输入砍到 1/8）；
2) `MAX_PIXELS` 从 5000 万降到 1200 万（1600 px 长边重编码后的实际需求远小于此）；
3) 生成完成后把 `chart_reader_images` 里的 `data_bytes` 清掉，只留元信息（导出用 `cached_report_images` 已单独保存）。
三项合计约 20 行，能显著抬高并发上限。

**d) 保留现状的理由（对抗性）**
当前是邀请制小规模部署，并发上限远未触及；降低 `MAX_PIXELS` 会影响「原图很大时仍能读」的体验；清掉 `data_bytes` 会影响「再次导出同一批图」的能力（已有 `cached_report_images` 兜底，实际不影响）。
反向意见：`maxUploadSize` 是免费保险，没有取舍；其余两项可以等第一次 OOM 后再做，但要先把「OOM 会静默重启全部会话」写进运维文档。

---

### S2-8 单进程下的其它共享可变状态：管理员锁定与 `$HOME` 偏好文件

**证据 1** `auth.py:487-518`（失败计数是模块全局，锁对所有人生效）

```python
_ADMIN_FAILS = 0
_ADMIN_LOCKED_UNTIL = 0.0
...
def _try_admin_unlock(admin_pw: str, pw: str) -> None:
    global _ADMIN_FAILS, _ADMIN_LOCKED_UNTIL
    now = _t.time()
    if now < _ADMIN_LOCKED_UNTIL:
        st.error(f"尝试次数过多，请 {int(_ADMIN_LOCKED_UNTIL - now)} 秒后再试。")
        return
```

**证据 2** `auth.py:529-545`（管理员入口挂在公开登录页，任何匿名访客都能提交密码）

```python
def _render_admin_panel():
    admin_pw = str(st.secrets.get("ADMIN_PASSWORD", "")).strip()

    with st.expander("🔧 管理员入口", expanded=False):
        ...
        if not st.session_state.get("admin_unlocked"):
            pw = st.text_input("管理员密码", type="password", key="admin_pw")
            if st.button("解锁", key="admin_unlock_btn"):
                _try_admin_unlock(admin_pw, pw)
```

**证据 3** `modules/city_prefs.py:20`、`modules/theme_aether.py:57`

```python
_PREF_FILE = Path.home() / ".weather_wall_cities.json"
...
_PREF_FILE = Path.home() / ".aether_theme.json"
```

**证据 4** `modules/theme_aether.py:89-94`（写失败静默）

```python
def _save_pref_local(theme: str) -> None:
    try:
        _PREF_FILE.write_text(json.dumps({"theme": theme}), encoding="utf-8")
    except Exception:
        pass
```

**a) 根因**
三处都把「进程」当成「用户」。管理员锁的全局计数本意是防暴力破解（这个方向正确），副作用是任意访客可用 5 次错误把管理员入口锁死 5 分钟，循环提交即可永久锁死；`$HOME` 下的两个 JSON 在单容器内是全体会话共享的文件，而代码把它们当作「本地偏好」。

**b) 不修的长期代价与触发条件**
管理员锁：触发成本是每 5 分钟 5 次匿名提交。后果是管理员无法生成邀请码、无法调整配额、无法作废泄露的码。真实发薪日或新用户注册窗口被卡住时，运维没有任何旁路（只能重启应用或改 secrets）。失败尝试也没有日志与告警。
`$HOME` 文件：容器重建或重新部署后文件消失，手册 `docs/用户使用手册.md:810` 的「重启后保持」对未登录用户不成立；并发写可能互相覆盖，写坏时被 `except: pass` 吞掉；登录页的暗色主题会继承上一个用户的选择。对已登录用户，云端的 `user_metadata` 才是有效通道，本地文件实际上只在「登录前」和「云端写失败」时起作用，价值很低。

**c) 最小修复切口**
管理员锁：把全局计数改成「按浏览器会话计数 + 全局冷却只用于跨会话的连续失败」，或把锁定改成「锁定后仍允许用 secrets 里的应急密码进入」。最小做法是给锁定加一个上限（例如全局只允许锁定 15 分钟，随后必须放行一次尝试）。约 20 行。
偏好文件：删掉本地文件通道（登录门禁之后所有用户都是已登录状态，云端通道足够），`theme_aether.init_theme` 直接返回默认值。约 30 行删除。

**d) 保留现状的理由（对抗性）**
管理员锁的全局设计在单人运维下是有效的（防止有人用 cookie 重置绕过限流，`auth.py:487-489` 的注释说明了这个动机）；攻击者需要主动去点管理员入口，属于主动 DoS，不是常见威胁。
偏好文件通道是「未登录也能记住主题」的需求遗留；删掉会影响登录页首次渲染的主题，属纯美观。
反向意见：管理员锁的 DoS 成本极低而恢复手段为零（只能改 secrets 或重启），值得加一个上界；偏好文件与「登录后才能用」的现实冲突，保留它只是保留一个跨用户可写点。

---

### S2-9 会话与凭据模型：登录态只在内存，刷新即回登录页；过期判定靠字符串

**证据 1** `auth.py:177-179`（登录态只看 session_state）

```python
def is_authenticated() -> bool:
    """当前会话是否已登录"""
    return bool(st.session_state.get("auth_user"))
```

**证据 2** `app.py:437-442`（未登录直接进登录页，没有 cookie 恢复路径）

```python
if not is_authenticated():
    render_auth_page()
    st.stop()

# 已登录页面的 rerun 入口：会话过期或刷新失败时回到登录页。
ensure_session()
```

**证据 3** `auth.py:212-228`（用字符串子串判断会话失效）

```python
_SESSION_ERROR_MARKERS = (
    "jwt expired",
    "invalid jwt",
    "token is expired",
    "token has expired",
    "invalid claim",
    "session missing",
    "refresh token",
    "401",
    "pgrst301",
)
...
def is_session_error(exc) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _SESSION_ERROR_MARKERS)
```

**a) 根因**
Streamlit 的 session_state 只存在于服务端内存，随 WebSocket 会话生灭；代码没有做任何 cookie/localStorage 持久化，也没有「会话即将过期」的提示。`ensure_session()` 调用 `get_session()`，这只是本地对象查询，真正的服务端校验发生在后续 RPC 失败时，因此失效检测是滞后的、依赖错误文案的。

**b) 不修的长期代价与触发条件**
触发条件：浏览器刷新、标签页关闭后重开、网络切换导致 WebSocket 重建、平台重启容器。后果是按一次登录算一个工作单元的用户会频繁重输密码；更严重的是刷新会丢掉 session_state 里的全部工作数据（导入的 DataFrame、生成中的报告、读图缓存），而用户手册 `docs/用户使用手册.md:780` 只承诺「重新登录会自动载入最近一次保存的数据集」，未保存的导入数据直接丢失。
字符串匹配的触发条件：任何包含 `401` 子串的异常文本（例如错误信息里带一个以 401 开头的 UUID 或 token 计数）都会被误判为会话过期，把用户踢回登录页，且日志里只会留下「退出登录」的痕迹。

**c) 最小修复切口**
最小可行：在 `app.py` 的已登录分支加一个「本会话已保持 N 分钟」的提示与一次性 `st.warning`，并在 `safe_error_text` 的调试模式里记录被误判的异常。真正解决需要持久化会话（把 Supabase 的 refresh token 写进签名 cookie，Streamlit 需要用 `st.context.cookies` + 组件或自建反向代理），成本高，不建议现在做。
字符串匹配：换成检查异常对象的 `code`/`status` 属性（PostgREST 的 `PGRST301`、HTTP 401），保留文本匹配作为兜底。约 15 行。

**d) 保留现状的理由（对抗性）**
Streamlit 的多会话模型天然这样，官方也没有提供登录态持久化能力；对一个内部工具来说，刷新重登可以接受。cookie 方案要引入组件或第三方库，超出「不新增依赖」的约束。
反向意见：真正值得现在修的是 `"401"` 子串匹配与「无即将过期提示」，这两项都便宜；持久化登录登记为已知限制即可。

---

### S2-10 发布面：CI 门禁不覆盖应用启动，schema 版本与代码版本没有联动

**证据 1** `.github/workflows/tests.yml:56-64`（门禁是 11 个脚本直跑；全量 pytest 失败不阻断）

```yaml
      - name: Supabase 后端契约（自检/缓存 RPC/配额）
        run: python -B tests/test_supabase_backend.py

      - name: 发布面契约（版本/依赖/Secrets/CI）
        run: python -B tests/test_release_surface.py

      # 其余 pytest 用例（含天气墙）作为补充信号，失败不阻断门禁
      - name: pytest 全量收集
        continue-on-error: true
        run: python -m pytest tests -q
```

**证据 2** `tests/test_smoke.py` 不在门禁列表里（它是唯一用 AppTest 启动 `app.py` 的用例）

```python
    at = AppTest.from_file(os.path.join(APP_DIR, "app.py"), default_timeout=60)
```

**证据 3** `sql/schema.sql:185-189`（schema 版本只是一个日期字符串）与 `config.py:626`（应用版本是另一个字符串）

```sql
insert into public.schema_version (id, version)
values (1, '2026-10-18')
on conflict (id) do update
    set version = excluded.version,
        applied_at = now();
```

**证据 4** `SECURITY.md:28`（代码先于 SQL 发布时的后果已经写明）

> 升级到 2.3.7 及以后必须重跑一次『schema.sql』……否则管理员面板会提示「无法执行数据库安全自检」，GFS 二级缓存会静默回退到实时请求。

**a) 根因**
发布链路有三段彼此不知情的事实：代码版本（`config.py`）、数据库版本（`schema_version` 表）、线上容器实际运行的 commit。CI 只验证「脚本级契约」，不验证「应用能否启动」；应用启动时不检查 schema 版本；`README:184-191` 明确说线上是否重建容器需要肉眼核对页脚版本号。

**b) 不修的长期代价与触发条件**
触发条件 1：某次提交破坏了 import 或 `set_page_config` 之前的初始化，11 个门禁脚本全绿，pytest 的 AppTest 失败但 `continue-on-error` 放行，合并后线上白屏。触发条件 2：发布只推代码不重跑 SQL，读图配额与 GFS 缓存静默降级（`SECURITY.md:28` 已描述），直到管理员偶然解锁面板才发现。
长期代价是「发布」这个动作没有原子性保证，回滚也只能靠 git revert + 平台重启，没有版本号可以断言「线上是哪一个」。

**c) 最小修复切口**
1) 把 `test_smoke.py` 加进门禁（它已经存在，只需一行 YAML）；
2) `app.py` 启动时（登录后、主区之前）用 service_role 或 anon 调一次 `security_selfcheck`，把 `schema_version` 与 `config.py` 里新增的 `REQUIRED_SCHEMA_VERSION` 比较，不一致就在页面顶部显示红色横幅并禁用读图/缓存相关按钮（一次 RPC，可用 `st.cache_data(ttl=600)`）；约 30 行。
3) 发布 checklist 里把「页脚版本号 + 自检横幅」作为验收项（已在 README，但只是建议）。

**d) 保留现状的理由（对抗性）**
AppTest 在 CI 里依赖 Streamlit 版本与临时目录，社区云环境与实际运行环境的差异较大，加进门禁可能带来偶发红；应用启动时的 schema 检查会增加一次网络往返，且当 Supabase 不可用时会造成新的「启动失败」路径（需要设计成非阻断横幅）。
反向意见：`test_smoke.py` 已经存在且被排除，加进去的边际成本几乎为零；schema 横幅用非阻断方式实现，收益是让「代码/数据库不同步」从静默变成可见。

---

### S2-11 可观测性：没有日志配置、没有指标、没有请求追踪

**证据 1** 全仓库没有 `logging.basicConfig`（grep 结果只有 `getLogger`），模块级 logger 全部依赖 root logger 的默认行为

```python
# auth.py:27
_LOG = logging.getLogger(__name__)
# db.py:16
_LOG = logging.getLogger(__name__)
# modules/nwp_forecast.py:42
_LOG = logging.getLogger(__name__)
```

**证据 2** 日志内容不带 uid、耗时、缓存命中与配额拒绝计数，典型如 `db.py:94`

```python
        _LOG.warning("存储 RPC %s 失败", name, exc_info=True)
```

**证据 3** `modules/gfs_cache.py:46`（键在日志里，但没有命中/未命中/写入成功的计数）

```python
    except Exception:
        LOG.warning("读取 GFS 缓存失败 key=%s", cache_key, exc_info=True)
```

**a) 根因**
上一轮审计 S6 补了 `logging`，但只补到「有 warning 可看」，没有补「可聚合」。Streamlit Cloud 的日志是流式的、随容器重启清空；没有结构化字段就无法在平台上做聚合查询，也没有任何计数器能回答「缓存命中率多少」「今天拒绝了多少次配额」「Open-Meteo 429 几次」。

**b) 不修的长期代价与触发条件**
触发条件：任何一次线上异常（读图失败率升高、GFS 变慢、429 风暴）。现在的排查路径是用户截图 + 管理员凭记忆复现 + 在 Cloud 日志面板里翻中文 warning，缺少时间、用户、请求维度，无法判断是「普遍故障」还是「单用户问题」。`research/supabase-体检-2026-10-18.md` 的「未覆盖」第 4 条已经把「缓存命中率与 429 次数需要上线后用日志验证」列为待办，但代码里没有产生这些数据的计数器。

**c) 最小修复切口**
`app.py` 顶部加 `logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")`；`db.py` 与 `gfs_cache.py` 各加一个模块级 `collections.Counter`（cache_hit/cache_miss/quota_denied/rpc_error），管理员面板新增一行展示（进程内累计，重启清零，够用）。约 50 行，不新增依赖。

**d) 保留现状的理由（对抗性）**
单人运维、用户少，用户反馈 + 日志面板已经能定位大多数问题；结构化日志与指标在 Streamlit Cloud 上也无法做长期留存，投入产出比一般。
反向意见：计数器比日志便宜且直接回答运营问题（缓存到底有没有用、配额是否在挡人），而且这次审计里多条结论（GFS 命中率、配额故障时长）都依赖这些数据才能验证。

---

## 5. S3 表面问题

| 编号 | 问题 | 证据 | 根因 | 最小切口 | 保留现状的理由 |
|---|---|---|---|---|---|
| S3-1 | service_role 操作没有统一出口与调用日志：`auth.py`、`nwp_forecast.py` 直接从 `auth` 拿特权客户端；没有 allowlist 或包装层 | `auth.py:163-171`、`modules/nwp_forecast.py:129-143`、`auth.py:608-610`、`auth.py:667-669` | 特权能力以函数形式暴露给全进程 | `auth.get_supabase_admin(purpose)` 增加 `purpose` 白名单并记 info 日志，约 15 行 | 当前无越权路径，自检也覆盖了函数授权；新增功能时靠 review 即可 |
| S3-2 | service_role/anon 密钥轮换没有运行手册与重叠窗口：轮换后旧会话持有的客户端立刻失效，需重启应用 | `SECURITY.md:38`、`auth.py:147-155` | 密钥只在建客户端时读取，会话内缓存 | README 增加「轮换步骤：先在 Supabase 建新 key → 更新 Secrets → Reboot app → 删除旧 key」 | 单人部署，轮换频率以年计；重启成本可接受 |
| S3-3 | `.streamlit/config.toml` 的部分配置在 Cloud 被平台覆盖：`[browser] gatherUsageStats=false` 不生效（平台强制 true），`[client] showErrorDetails=false`、`[runner] fastReruns=true` 也是平台值 | `.streamlit/config.toml:4-17`、Streamlit 官方 status 页（Platform 覆盖列表） | 平台级配置优先于仓库配置 | 删掉不生效的配置项，改为 README 说明「由平台面板设置」 | 不影响功能；gatherUsageStats 是平台级遥测，仓库改不了 |
| S3-4 | 依赖固定不完整：`Pillow>=10.0`、`markdown-it-py>=3.0` 无上界，CI 与线上可能解析到不同版本；没有 lock/hash | `requirements.txt:13-14` | 传递依赖转直接依赖时只加了范围 | 锁到当前 CI 实际验证过的具体版本，发布面测试同步断言 | 这两个库 API 稳定，范围依赖的风险低于维护成本的收益 |
| S3-5 | 会话内 GFS 缓存永不过期：`st.session_state[cache_key]` 命中后不再检查 `updated_at`，长会话会一直看到首拉取时的预报 | `modules/nwp_forecast.py:207-210` | 第一层缓存没有 TTL | 存 `(df, fetched_at)`，超过 1 小时按 miss 处理，约 8 行 | 会话通常在一次分析内结束；Streamlit 会话本身也会随刷新重建 |
| S3-6 | `retry_with_backoff` 的「上次缓存」可能回退到一个失败元组：成功分支才写缓存，但函数本身可能返回 `(None, msg)` 被当作成功写入 | `utils.py:79-83`、`modules/data_loader.py:570-571` | 把「业务失败返回值」当成「调用成功」 | 只在返回第一项非 None 时写缓存，约 3 行 | 回退到 `(None, msg)` 与本次失败结果相同，用户观感一致 |
| S3-7 | 读图页每次 rerun 一次 `get_vision_quota` RPC（未走 30 秒缓存），滑块拖动会放大请求量 | `modules/chart_reader.py:501-502` | S7 只给侧边栏三个读数加了缓存 | 包一层 `@st.cache_data(ttl=30)` 或只在按钮事件后刷新，约 10 行 | 单页请求量小；且展示实时配额本身是设计意图 |
| S3-8 | 管理员审计只记录成功操作，没有操作者身份，失败尝试不记录 | `auth.py:743-754`、`sql/schema.sql:192-198` | 审计表没有 actor 列；`_audit_admin` 在异常分支不调用 | 审计表加 `actor_note` 列并在失败分支也写一条；或至少记录失败尝试到日志 | 只有一个管理员密码；审计用于追忆操作而非追责 |
| S3-9 | 调试模式对所有登录用户开放，开启后 `st.exception` 会展示完整堆栈（含本地路径、内部函数名、部分 SQL） | `app.py:64-75`、`config.py:698-704` | 调试开关是面向部署者的，但暴露给了每个用户 | 用 secrets 里的 `DEBUG_MODE` 控制，或仅对管理员邮箱开放 | 邀请制用户，且堆栈只在用户自己浏览器里显示，不跨用户泄露 |
| S3-10 | `.streamlit/secrets.toml.example` 的输出预算注释写「默认 16000」，代码与页面是 20000 | `.streamlit/secrets.toml.example:27-32`、`modules/ai_narrative.py:31`、`modules/chart_reader.py:403` | 版本升级时注释未同步 | 注释改为 20000；发布面测试加断言 | 纯文档漂移，用户按注释配置也能工作 |
| S3-11 | 首次部署缺少 secrets 时，登录页在 `_render_admin_panel` 处直接抛异常，README 承诺的「停在登录页并提示如何配置」不成立 | `auth.py:531`、`README.md:226`、`auth.py:45-48` 的注释已经证明 `st.secrets.get` 会抛异常 | 该处没有走 `_secrets_get` 包装 | 改成 `_secrets_get("ADMIN_PASSWORD")`，一行 | 线上 Secrets 已配置，生产路径不受影响；但公开仓库的 fork/本地首跑会遇到 |

---

## 6. 触发条件表（现象 → 条件 → 影响）

| # | 现象（用户/运维看到） | 引爆条件 | 结构影响 |
|---|---|---|---|
| 1 | 读图页提示「配额服务不可用，本次按会话级限制放行」，刷新后可继续生成 | Supabase 暂停/故障，或发布代码后未重跑 `schema.sql` | S1-1，部署方 API Key 支出失去上限 |
| 2 | 管理员把「每日次数」调大后，token 配额很快被击穿 | 管理员在原面板把次数从 5 调到 50/200 | S1-2，成本上限变为次数的倍数 |
| 3 | 用户 A 改了阈值后，用户 B 的预警结论和导出报告随之改变 | 任意用户点击「应用自定义阈值」 | S1-3，跨用户分析口径污染 |
| 4 | 侧边栏显示「云存储 0.0 MB / 10 MB」「暂无数据集」，30 秒后恢复 | 一次 Supabase 5xx/超时 | S2-1，失败被缓存，用户误判数据丢失 |
| 5 | 点侧边栏按钮时偶发跳回登录页，或点了几次没反应 | JWT 过期 + 30 秒缓存窗口 | S2-2，过期检测滞后且行为随缓存命中率变化 |
| 6 | 数值预报页某块突然显示「页面加载出现异常」，换坐标或等 1 小时又正常 | 同网格缓存的列集合与代码不一致 | S2-3，单行坏数据污染一个网格的全部用户 |
| 7 | 某个登录用户能判断「最近一小时有没有人查过某坐标」 | 用公开源码构造键，循环调用 `get_gfs_cache` | S2-4，位置隐私泄露，与 SECURITY 声明不符 |
| 8 | 多人同时查同一城市时集体出现「请求过于频繁（429）」 | 首轮并发 + 共享出口 IP + 无进程内缓存 | S2-5，Open-Meteo 免费额度被单点耗尽 |
| 9 | 导入空气质量数据时，只要有一项缺测就整批报错，数据不落表 | 上游某列全为 null（区域性缺测） | S2-6，确定性数据丢失，用户以为接口坏了 |
| 10 | 集中演示或多人同时上传大图时应用整体重启，所有会话回到登录页 | 并发重度会话触到容器内存上限；或上传 200 MB 文件 | S2-7，单进程 OOM 等于全员断线，进行中的 LLM 调用仍计费 |
| 11 | 管理员入口一直提示「尝试次数过多」，无法生成邀请码或改配额 | 匿名访客每 5 分钟提交 5 次错误密码 | S2-8，管理面被低成本 DoS，且无旁路 |
| 12 | 浏览器刷新后要重新登录，未保存的导入数据消失 | 刷新/重连/容器重启 | S2-9，会话模型限制，工作数据无持久化 |
| 13 | 一次提交破坏了应用初始化，CI 全绿但线上白屏 | 11 个门禁脚本不覆盖 `app.py` 启动 | S2-10，发布门禁存在盲区 |
| 14 | 线上故障只能靠用户截图定位，无法回答「缓存有没有用、429 几次」 | 任意故障后的复盘 | S2-11，可观测性不足，多条优化无法验证 |
| 15 | 首次 fork/本地运行未配 secrets 时，登录页直接报异常而非配置指引 | 新部署或本地开发 | S3-11，首跑路径与 README 承诺不符 |
| 16 | 登录页主题跟随上一个用户的选择 | 上一个用户切换过暗色并写入本地文件 | S2-8，跨用户偏好外溢（非敏感） |

---

## 7. 建议批次

**批次 A（先做，S1，估计 1–2 天）**
1. S1-1 配额故障兜底：进程级当日计数 + 故障态把会话上限降到 1 次，或直接失败关闭并给明确文案。
2. S1-2 token 预算按余额下发：`begin_vision_call` 返回本次可用预算，剩余不足时拒绝。
3. S1-3 阈值移入 `st.session_state`：新增 `analyzer.current_thresholds()`，8 个读点各改一行。
4. 顺手修 S3-11（一行）与 S3-10（注释）。

**批次 B（下一次发布，S2 中成本低、收益高的）**
5. S2-10：`test_smoke.py` 加进 CI 门禁；`app.py` 启动时做一次 schema 版本比对（非阻断横幅）。
6. S2-7：`maxUploadSize = 25`；降低 `MAX_PIXELS`；生成后释放上传字节。
7. S2-6：修空气质量的 `elif` 死分支。
8. S2-1：统一后端不可用语义，至少停止缓存「失败后的默认值」。
9. S2-11：`logging.basicConfig` + 四个进程内计数器 + 管理员面板展示。

**批次 C（结构性重构，排期另定）**
10. S2-2：`SessionExpired` 上抛，`app.py` 单点处理。
11. S2-3、S2-5：GFS 读侧列校验 + `st.cache_data` 进程级缓存。
12. S2-8：管理员锁加上界；删除 `$HOME` 偏好文件通道。
13. S2-4：键服务端生成（HMAC）或把枚举计入配额；在此之前先改 SECURITY.md 的措辞。
14. S2-9：会话持久化（成本高，可只登记为已知限制 + 加过期提示）。
15. S3-1、S3-2：service_role 统一出口与轮换手册。

**不建议现在做的**
- 为了「更安全」更换数据库或部署平台：当前 RLS 层已经扎实，换平台会把已经验证的边界全部推倒重来。
- 引入完整的迁移框架（Supabase CLI / migrations）：单人项目，`schema_version` + 启动横幅已经覆盖主要风险。
- 给缓存加 HMAC 签名（体检 S3 已论证过，签名者与写库者同进程时无额外收益）。

---

## 8. 未验证项 / 需在控制台确认

1. 本机未安装 `streamlit` / `supabase`，所有运行时行为（`st.cache_data` 与 `st.rerun` 的交互、`get_session()` 是否真的自动刷新）均为代码审阅结论，未实测。建议用 AppTest 加一条「JWT 过期后侧边栏操作」的用例验证 S2-2。
2. Streamlit Community Cloud 免费层的具体内存上限官方文档未给出明确数值，本文按「GB 量级」估算；20 万像素级图片与 10 MB 数据集的峰值内存需在线上用 `st.memory` 或日志实测。
3. Community Cloud 容器重建后 `$HOME` 下的文件是否丢失、是否与下一次部署共享，需要在控制台做一次「写文件 → Reboot app → 读文件」的验证。
4. Supabase 控制台的「允许新用户注册」开关、JWT 有效期、`pg_cron` 可用性仍无法从仓库确认（`research/supabase-体检-2026-10-18.md` 的控制台清单仍然有效）。
5. 管理员锁的 DoS 需要在线上验证：匿名会话提交 5 次错误密码后，管理员会话是否确实被锁。
6. 配额故障放行的实际成本影响，取决于 LLM 供应商的速率限制与单次实际 token 消耗，未做压测。

---

## 9. 主要证据索引

| 文件 | 行 | 说明 |
|---|---|---|
| `modules/chart_reader.py` | 38-42、217-224、361-375、384-403、501-502 | 会话级限制、故障放行、token 记账、预算下发 |
| `db.py` | 13、82-97、100-113、211-229、246-257 | 错误契约、缓存、配额 RPC |
| `auth.py` | 42-52、147-171、177-179、212-235、238-264、487-518、529-545、710-725 | secrets、每会话客户端、登录态、过期处理、管理员锁、配额输入 |
| `sql/schema.sql` | 185-189、485-492、519-535、640-643、753-783、787-818 | schema 版本、缓存校验、缓存读 RPC、默认配额、准入、记账 |
| `modules/nwp_forecast.py` | 81-110、116-126、205-215、236-260 | 缓存键、读形状、三层缓存、写入 |
| `modules/gfs_cache.py` | 30-47、50-69 | 读 RPC、写 RPC |
| `modules/analyzer.py` | 24-31、68、136、187、223、256、301、335、379 | 进程级阈值 |
| `modules/data_loader.py` | 540-567、591-643、745-751 | Open-Meteo 重试、空气质量契约、页面死分支 |
| `utils.py` | 71-133、162-175 | 退避重试、错误脱敏 |
| `modules/ai_narrative.py` | 25-31、187-204 | 超时与预算 |
| `modules/theme_aether.py` | 57、89-94、105-122 | 本地文件通道 |
| `modules/city_prefs.py` | 20、72-80、90-110 | 本地文件通道、云端通道 |
| `app.py` | 48-53、64-84、437-442、475-482、497-503、599-601 | 主题初始化、错误边界、登录门禁、自动载入、侧边栏 RPC、阈值 |
| `.github/workflows/tests.yml` | 56-64 | CI 门禁 |
| `config.py` | 626、698-704 | 版本、调试模式 |
| `.streamlit/config.toml` | 1-17 | 平台覆盖项、maxUploadSize |
| `requirements.txt` | 13-14 | 范围依赖 |
| `docs/用户使用手册.md` | 444-456、516、802、810 | 已知限制的官方表述 |
| `SECURITY.md` | 22、28、38 | 声明与已知故障模式 |
| `README.md` | 184-191、226 | 发布核对与首跑承诺 |
