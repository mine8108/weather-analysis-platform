# weather_app 结构性重构路线图

> **For agentic workers:** 本文件用于排期与验收。批次 0 的逐任务执行细则见 `2026-10-18-batch0-stop-the-bleeding.md`。执行前先读本文件的 Global Constraints 与批次依赖图。

**Goal:** 在不更换技术栈、默认不改变用户可见行为的前提下，把 weather_app 从「同一语义多真相源、状态无作用域、渲染即计算」收敛为「语义单出口、状态显式分层、数据契约先行」的结构。

**Architecture:** 六个批次。批次 0 止血，修掉会直接产出错误结论、成本失控、点击无效的缺陷。批次 1 建状态层，批次 2 建数据契约，批次 3 收敛语义真相源，批次 4 切分上帝模块，批次 5 把测试从锁实现位置改为锁行为。

**Tech Stack:** Python 3.12 / Streamlit 1.59.1 / pandas 3.0.3 / Plotly 6.8 / Supabase PostgREST + RLS / pytest

**Spec:** `research/audit-code.md`（819 行）、`research/audit-ia.md`（936 行）、`research/audit-runtime.md`（982 行）

---

## Global Constraints

- 技术栈固定为 Streamlit + Supabase，不做前后端分离，不迁移部署平台。
- 默认零可见变化。确需改变用户可见行为的项集中列在「四、可见变更清单」，逐项确认后才实施。
- 每个批次结束时必须满足：现有 412 条 `test_*` 全部通过；新增回归先失败后通过；`git status` 只包含该批次声明过的文件。
- 不新增运行时依赖。`requirements-dev.txt` 可增测试工具。
- 不改动已加固的 Supabase 边界。`sql/schema.sql` 除批次 0 的读图预算字段外不新增策略。
- 一个任务一个 commit，commit message 前缀 `refactor:` / `fix:` / `test:`。
- Python 3.12；所有新模块必须能在无 `streamlit` 进程上下文时被 import，便于纯函数测试。

---

## 一、诊断

三份审计共记录 9 + 6 + 3 条 S1、12 + 12 + 11 条 S2，逐条带 `file:line`。这里只保留跨层反复出现的五个放大机制。它们互相咬合，单独修任何一条都会被其余四条重新长回来。

### R1 真相源增殖，且没有机器可校验的绑定

同一个语义存在 3 到 4 份实现，旧源以「兼容」名义保留，新源继续增长。

| 语义 | 真相源数量 | 证据 |
|---|---|---|
| 预警阈值 | 4 份 | `config.py:212-311`（真相源）、`modules/analyzer.py:66-108`（读 config 并叠加自定义）、`modules/nwp_forecast.py:976-1050`（硬编码 35/37/40，不读 config 也不读自定义）、`app.py:541-597`（侧边栏默认值再抄一遍） |
| 预警等级串 | 2 套 | `config.py` 用 `Ⅰ/Ⅱ/Ⅲ/Ⅳ`，`nwp_forecast.py` 用 `I/II/III`，两套都会经 `reporter.py` 进入 Word 报告 |
| WMO 天气码 | 1 张死表 + 5 处活实现 | `config.WMO_WEATHER_CODES` 无调用者；`nwp_forecast`、`data_loader`、`codec`、`reporter`、`weather_wall` 各写一份映射 |
| 配色 | 3 套 | `modules/design_tokens.py`（声称唯一真相源）、`config.py::COLORS`（37 个 hex）、`.streamlit/config.toml`（4 个色值） |
| 读图配额 | 2 层 | `sql/schema.sql:735-783` 服务端每日配额、`modules/chart_reader.py:384-403` 会话级 5 次 |
| 错误契约 | 5 套 | `db.safe_error_text` / `db.save_error_message` / `st.error` 直写 / 异常上抛 / `st.stop`（见 `research/audit-runtime.md` S2-1） |

机制解释。每次扩展都选了「复制一份最省事」的路径，旧实现保留做兼容，没有注册表、代码生成或一致性测试把新源绑定回旧源。`research/` 下已有 `check_py_vars.py`、`check_chart_colors.py` 等检查脚本，但都不在 CI 门禁里。

长期代价。改一个阈值要同步 4 个文件，漏一处不报错，只让页面之间互相矛盾。加一种灾害要在两个模块各写一遍判定。用户改了侧边栏阈值去预报页发现不生效。

### R2 状态没有作用域分层

项目实际混用了三种作用域，代码里没有区分。

| 作用域 | 承载物 | 证据 |
|---|---|---|
| 进程级 | `analyzer.CUSTOM_THRESHOLDS`、`auth._ADMIN_FAILS`、`st.cache_data` | `modules/analyzer.py:24-31`、`auth.py:487-491` |
| 会话级 | `st.session_state` 73 个唯一键 / 352 次引用，另有 153 个字面 widget key | `app.py` 143 处，`data_loader.py` 52 处 |
| 用户持久 | `$HOME` 下两个 JSON 文件、Supabase `profiles` | `modules/theme_aether.py:105-122`、`modules/city_prefs.py:72-110` |

三个已经成立的后果。

1. 任意用户点一次「应用自定义阈值」，8 类检测对全部在线会话生效，其他人的分析结论与 Word 报告静默改变（`analyzer.py:24-31`、`app.py:599-601`）。
2. 登录态只活在 `session_state`，浏览器刷新即回到登录页，而手册与界面三处把「刷新页面」写成恢复手段。
3. 错误边界里的重置按钮把 `_sb_client` 删掉却保留 `auth_user`（`app.py:87-96` 的 keep 集合不含 `auth.py:38-39` 的两个客户端键），下一轮 `get_supabase()` 新建无 JWT 客户端，RLS 拒绝一切读写；同时 `_auto_load_done` 被删，`app.py:476-482` 又把云端数据自动载回。用户点「重置会话并回到首页」，得到的是登录态损坏加数据复活。

根因是状态清单与写入点之间没有关联。`_RESET_KEYS_BY_TAB`（`app.py:103-117`）、`_safe_reset` 的 keep 集合、`auth._LOGOUT_KEEP` 三份清单全靠手写，新增一个键时没有任何机制要求登记。

### R3 渲染即计算

Streamlit 的重跑模型把「渲染页面」和「计算派生数据」绑在一起，项目没有派生层承接，于是跨 Tab 契约退化成「先渲染过没有」。

| 现象 | 证据 | 后果 |
|---|---|---|
| 8 类预警检测只在 `active_tab == 3`（AI 读图）时计算 | `app.py:890-910` | 导入数据后直接去导出，Word 报告的事件检测章节为空，读者理解为「未触发预警」 |
| `quality_score` 在侧边栏载入数据集路径不计算 | `app.py:517-519` | 报告质量评分为 0 |
| 导入向导把「渲染一次」当「提交一次」 | `modules/data_loader.py:526-535` + `app.py:753-766` | 手动录入在返回上一步后重复合并进 `df` |
| 按钮渲染在另一个按钮的点击分支里 | `modules/codec.py:343`、`data_loader.py:711/718/762/769` | 内层按钮在非点击轮次不存在，点击事件永远打不中 |
| 预报 Tab 每次 rerun 重算分析与生活指数 | `modules/nwp_forecast.py:1814` | 交互变钝，且生活指数读 widget 键而非传入数据 |
| 摘要卡时间筛选只作用于可视化 | `app.py:389-405` | 导出、报告、预警仍用全量数据 |

### R4 失败语义折叠与依赖方向反转

`db.py` 把异常折叠成 `None`、`[]` 或默认值（`db.py:82-97`、`112-133`、`211-229`），再用 `@st.cache_data(ttl=30)` 把失败结果缓存 30 秒。后端不可用时，界面显示的是「你没有数据」。配额服务不可用时 `chart_reader.quota_allows` 明确放行（`chart_reader.py:217-224`），替代约束放在可被刷新重置的 `session_state` 里，部署方 LLM 账单失去上限。

依赖方向也是反的。`db.py:13` 顶层 import `auth.py`（877 行，登录页 UI 加管理员面板），数据层依赖会话 UI。`weather_wall.py:225` 从 `nwp_forecast` 私有导入 `_compute_cn_aqi`。`config → chart_theme → design_tokens → config` 存在一条靠函数内 import 维持不炸的环（`config.py:723`、`chart_theme.py:25`、`design_tokens.py:420/435`）。项目内 60 条依赖边里有 17 条是函数内 import，掩盖了真实方向。

### R5 测试锁在实现位置，构成重构阻力

412 个 `test_*` 函数，33 处直接读源码字符串做断言，5 处按代码行切片。CI 只跑 11 个脚本，`pytest tests -q` 是 `continue-on-error`（`.github/workflows/tests.yml:56-64`），`test_smoke.py` 的 AppTest 启动冒烟不阻断。`data_loader`、`reporter`、`visualizer`、`nwp_forecast` 除少量私有函数外没有专用测试文件。

这意味着任何重构都会先撞测试。测试里既有应当保留的用户可见文案契约，也有把代码结构钉死的实现位置断言，两者混在一起，第一批必须先做区分，否则后面每批都在改测试而不是改结构。

### 1.2 因果图

```
R1 真相源增殖 ──┐
                ├──> 改一处漏三处 ──> 页面之间互相矛盾 ──> 报告不可复现
R3 渲染即计算 ──┤
                ├──> 派生数据没有归属 ──> 跨 Tab 契约靠渲染顺序
R2 状态无作用域 ┘

R4 失败折叠 ──> 故障显示为「没有数据」──> 用户误操作 ──> 错误边界 ──> 重置自伤
                                                    │
R5 测试锁实现位置 ──> 重构先改测试 ──> 结构问题被保留 ──┘
```

### 1.3 对抗性结论，以下不是问题

- 文件体积不是根因。`nwp_forecast.py` 1935 行、最长函数 292 行是症状，真正的问题是逻辑与渲染不可分。先切片再补状态层，会切出六个互相 import 的碎片。
- Streamlit 选型不是根因。换栈会把「复制真相源、状态无作用域」一起搬走，还会丢掉 412 条测试与现有部署。只有在出现「需要长连接推送、需要多页面深链、需要真正的前端权限控制」这三类需求之一时，才值得重新评估。
- Supabase 安全层已经扎实。RLS、函数授权、缓存写入收口、CHECK 约束这四层比多数同类项目强，不要动。运行时审计的 S1 全部在应用进程一侧。
- 明暗主题链路正常。对比度探针 0 项不合规，图表重绘与持久化可用，重构时不要碰配色。
- 六个 Tab 是既有契约，整体重排收益低于误伤成本。先改入口位置、提示条与状态归属。
- 现有六份计划文档已覆盖大量内容（schema_version、缓存收口、AQI 统一等），不要把已完成项当新发现。

---

## 二、批次路线

```
批次 0 止血
   │
   ├──> 批次 5 测试与 CI 治理（持续，与批 0 同时起步）
   │
   ▼
批次 1 状态地基
   │
   ▼
批次 2 数据契约 ──────┐
   │                  │
   ▼                  ▼
批次 3 语义收敛 ──> 批次 4 大模块切片
```

批次 2 与批次 3 可在批次 1 完成后并行，但两者都会改 `nwp_forecast.py`，必须错开写域，先 3 后 2 或先 2 后 3，同一时间只允许一个在跑。批次 4 必须等 1、2、3 全部完成。

| 批次 | 工期 | 文件域（写） | 验收标准 | 主要风险 | 回滚 |
|---|---|---|---|---|---|
| 0 止血 | 2-3 天 | `app.py`、`modules/analyzer.py`、`modules/chart_reader.py`、`modules/codec.py`、`tests/*`、`.github/workflows/tests.yml`、`docs/用户使用手册.md` | 7 条新增回归先红后绿；412 条现有测试全绿；CI 含 AppTest 启动冒烟且阻断；`reset_session` 单测覆盖三个后果 | 极低，单任务不超过 60 行 | 每任务独立 commit，单点 revert |
| 1 状态地基 | 4-6 天 | 新建 `modules/app_state.py`；改 `app.py`、`auth.py`、`db.py`、`modules/city_prefs.py`、`theme_aether.py` | 三份手工清单删除；键注册表覆盖 73 个键；未注册键让 CI 失败；AppTest 两会话隔离用例通过 | 中，会话键迁移期漏迁会导致行为回退 | 按「一个键簇一个 commit」，可单独回滚 |
| 2 数据契约 | 5-7 天 | 新建 `modules/dataset.py`；改 `data_loader.py`、`db.py`、`app.py`、`reporter.py`、`nwp_forecast.py`（只改入口） | `pm25` 与 `pm2_5` 归一到唯一列名；云端 CSV 往返 dtype 与 `schema_version` 有断言；`db` 读接口返回 Result 而非默认值 | 中高，涉及云端已存数据 | 读侧兼容旧 CSV，写侧加版本号后可共存 |
| 3 语义收敛 | 6-9 天 | 新建 `modules/warn_rules.py`；改 `analyzer.py`、`nwp_forecast.py`、`app.py`、`config.py`、`modules/aqi.py` | 阈值只剩一份；等级串只剩一套；`config.COLORS` 删除且全仓无直接引用；AQI 只有一个出口 | 中，Word 报告文案会变 | 每语义一项独立 commit |
| 4 大模块切片 | 10-15 天 | `nwp_forecast.py`、`reporter.py`、`auth.py`、`theme_css.py` 及新建 `modules/nwp/`、`modules/report/`、`modules/admin/` | 每个切片模块可无 Streamlit 导入；纯逻辑层测试覆盖率 ≥ 60%；文件不超过 600 行 | 高，回归面最大 | 按切片回滚，保留对外函数名不变 |
| 5 测试治理 | 持续 | `tests/*`、`.github/workflows/tests.yml`、`research/check_*.py` | 源码字符串断言从 33 处降到 10 处以内且只保留用户可见文案；CI 跑全量 pytest；`research/` 两个检查脚本进门禁 | 中，可能暴露既有缺陷 | CI 改动可单独回退 |

---

## 三、批次 1 到 5 的结构目标

### 批次 1，状态地基

新建 `modules/app_state.py`，提供 `KEYS` 注册表，每个键声明 `scope`（process / session / user）、`owner`（哪个模块写）、`reset_policy`（clear / keep / per_tab）、`widget`（是否 Streamlit widget key）。`_safe_reset`、`_reset_current_tab`、`sign_out_user` 三处从注册表派生，不再手写清单。CI 增加一条检查，遍历源码里所有 `session_state[...]` 与 `key=` 字面量，未注册即失败。

### 批次 2，数据契约

新建 `modules/dataset.py`，定义 `Dataset`，字段为 `df`、`schema_version`、`source`、`units`、`quality_score`、`warnings`、`created_at`。导入端是唯一归一入口，输出 `Dataset`。云端保存写 CSV 时同时落 `schema_version`，读回时按版本迁移。`db.py` 的读接口返回 `Result(value, error)`，故障与空结果分开。

### 批次 3，语义收敛

新建 `modules/warn_rules.py`，提供 `resolve_thresholds(custom)`、`level_of(kind, value)`、`level_label(kind, level)`。`analyzer` 与 `nwp_forecast` 都调用它。`modules/aqi.py` 成为 AQI 唯一出口，`weather_wall` 不再借 `nwp_forecast._compute_cn_aqi`。删除 `config.COLORS` 与 `COLOR_KEY_TO_TOKEN` 的 fallback 分支。错误契约收敛为 `db.Result` 一种。

### 批次 4，大模块切片

`nwp_forecast.py` 拆为 `modules/nwp/fetch.py`（外部调用与缓存）、`calc.py`（纯计算）、`charts.py`（Plotly 构造）、`page.py`（Streamlit 渲染）。`reporter.py` 按「专业版 / 通俗版 / 公共排版」拆文件。`auth.py` 的 212 行管理员面板移到 `modules/admin/panel.py`。`theme_css.py` 的 700 行 CSS 字符串移到独立 `.css` 资源，Python 只负责拼装。对外函数名保持不变，先做 re-export 再迁移调用点。

### 批次 5，测试治理

把 33 处源码字符串断言分类。用户可见文案契约保留并集中到 `tests/test_copy_contract.py`。代码结构位置断言全部改为行为断言或删除。CI 改为 `python -m pytest tests -q` 阻断，`test_smoke.py` 必须通过。`research/check_py_vars.py` 与 `check_chart_colors.py` 进 CI。

---

## 四、可见变更清单（需确认）

| 编号 | 变更 | 理由 | 风险 | 回滚 |
|---|---|---|---|---|
| V1 | 报文解码「添加到手动录入区」按钮开始可用 | 当前永久不可点（`codec.py:343` 嵌在解码按钮分支内） | 低 | 单行 |
| V2 | 数据就绪后摘要卡显示「检出 N 个预警事件」 | 预警计算从读图 Tab 提前到数据就绪，导出不再漏报 | 低，多一次计算 | 可加开关 |
| V3 | 重置按钮文案改为「已清空本地会话，云端数据不受影响」 | 现有文案与行为不符 | 低 | 文案 |
| V4 | 无数据时导出 Tab 显示空态而非生成空报告 | 当前能导出一份写着「没有数据」的报告 | 低 | 单函数 |
| V5 | 天气墙空态提供「一键添加示例城市」 | 登录后首屏是空墙，手册与测试却声称预置 34 城 | 低 | 单文件 |
| V6 | 登录页注册区给出邀请码获取路径说明 | 邀请码无获取入口，管理员工具长在登录页 | 极低 | 文案 |
| V7 | 预报页脚注说明自定义阈值的适用范围，或让阈值在预报侧生效 | 当前改了阈值在预报页无效且无提示 | 低，二选一 | 文案或一处取值 |

批次 0 只做 V1 与 V3，其余留到对应批次。

---

## 五、明确不做

- 不换前端框架，不做 FastAPI 加 React 的分离。
- 不引入迁移框架（Supabase CLI migrations）。单人项目，`schema_version` 加启动横幅已经够用。
- 不重写 AQI、预警判定等已有测试覆盖的算法。只统一它们的真相源。
- 不为缓存加 HMAC 签名。签名者与写库者同进程，没有额外收益。
- 不动 RLS 策略、函数授权、CHECK 约束。

---

## 六、执行前置与交接

本机（当前工作区）没有安装 `streamlit` / `pandas` / `pytest`，任何执行批次前先建虚拟环境。

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest tests -q
```

批次 0 可以直接开始。执行方式二选一。

1. 子代理驱动，每个任务派一个全新子代理，任务间由 Lead 复核。
2. 本会话内逐任务执行，每个任务后跑一次全量测试。

## 七、实施记录

### 批次 0（2026-10-18，已完成）

- 依赖装在仓库内 `.venv`（Tsinghua 镜像），全量回归从 427 项增长到 446 项，全部通过。
- 七项修复全部落地，两个提交：`704f646` 会话与阈值作用域，`f992ae9` 配额、解码、导入与 CI。
- 新增测试：`test_app_state.py`(4)、`test_codec_render.py`(3)、`test_import_merge.py`(6)。
- CI 的 `pytest` 步骤从 `continue-on-error` 改为阻断，并保留 11 个脚本门禁。
- 批次 0 的可见变更只做了 V1（解码按钮恢复可用）与 V3（重置文案）。

### 批次 1（2026-10-18，已完成）

- `modules/app_state.py` 升级为注册表：66 个会话键 + 129 个 widget key + 6 条动态前缀规则。
- `app.py` 删除 `_RESET_KEYS_BY_TAB`，`_reset_current_tab` 改用 `reset_tab`；`_safe_reset` 改用注册表 keep 策略。
- `auth.py` 的 `_LOGOUT_KEEP` 改为从注册表导入，三份手写清单归一。
- `research/check_state_registry.py` 接入 CI，未登记的字面量键直接失败。
- 新增测试：`test_state_registry.py`(5)、`test_session_isolation.py`(2)，全量 453 项通过。

### 批次 2（2026-10-18，已完成）

- 新增 `modules/dataset.py`：`Dataset` 契约、`canonicalize` 归一、版本化序列化（注释头 + CSV）、v1 历史数据自动迁移。
- `app.py` 新增 `_adopt_dataset`，文件 / 手动 / API / 云端载入四条路径统一走它，`df` 的写入点只剩这一处与显式清空。
- `db.py` 保存改用 `dataset.to_text`，读回识别版本；新增 `load_dataset_result`、`list_datasets_result`，故障与空结果分离，自动载入失败只记日志不再伪装成「没有数据」。
- 新增测试：`test_dataset.py`(9)，含 db 级保存读回往返；全量 462 项通过。
- 残留：`get_storage_usage_bytes` 等标量 RPC 仍以默认值兜底，留到批次 3 的错误契约收敛一并处理。

### 批次 3（2026-10-18，已完成）

- 新增 `modules/warn_rules.py`：`high_temp_levels` / `gale_levels` / `fog_levels` / `frost_levels` / `haze_levels` / `rainstorm_levels` / `cold_wave_levels` / `thunder_window_hours` 与 `default_custom()`，自定义阈值在观测侧与预报侧读同一份。
- `config.py` 的八张预警表不再手写等级串，由 `LEVEL_LABELS` 在 import 期注入；新增 `level_label()` 作为唯一生成方式。analyzer 与 nwp_forecast 的 `level_num` 全部改为调用它，ASCII 的 I/II/III 写法消失。
- `nwp_forecast._analyze_forecast` 的高温、暴雨、大风阈值改读 `warn_rules`，侧边栏默认值由 `default_custom()` 派生，app 里不再有第三份数字。
- 天气墙 AQI 改走 `modules.aqi.comprehensive_aqi` + `design_tokens.aqi_color`，不再从 `nwp_forecast` 私有导入。
- 删除 `config.COLORS`（37 个 hex）与 `design_tokens` 的兼容回退分支；`config.toml` 只剩 Streamlit 自身主题占位。
- 新增测试：`test_warn_rules.py`(7)，全量 469 项通过。
- 已知：`test_weather_wall.py` 单文件运行存在既有的测试顺序依赖（需要全量运行），留到批次 5。

### 批次 4（进行中）

切片 1 完成：`nwp_forecast` 纯计算层抽出。

- 新增 `modules/nwp/calc.py`（493 行）：`heat_index`、`_calc_ssd`、`_get_now_row`、`_calc_life_indices`、`_analyze_forecast`。模块导入不拉入 Streamlit，已用子进程断言。
- `_calc_life_indices` 改为接收显式 `current` 参数，不再读 `st.session_state`、不再内部联网；实时观测由 `render_forecast_tab` 取好后传入。
- 抽层过程中修掉一个真实崩溃：连续 3 天高温时 `hot_streak_dates` 是 `datetime.date`，直接 `join` 抛 `TypeError`，此前被顶层错误边界吞成「页面异常」。现在先转字符串。
- `nwp_forecast.py` 从 1935 行降到 1480 行，对外函数名保持不变。
- 新增测试：`test_nwp_calc.py`(7)，全量 476 项通过。
- 待做切片：`auth.py` 管理员面板拆到 `modules/admin/`、`reporter.py` 按报告类型拆、`theme_css.py` 的 CSS 字符串外置。

切片 2 完成：`auth.py` 管理员面板拆出。

- 新增 `modules/admin/panel.py`（393 行），承载邀请码生成/核销、用户分页、配额调整、安全自检与审计写入；`auth.py` 从 877 行降到 539 行，只保留鉴权与会话。
- `auth` 与 `admin` 之间保持单向惰性依赖：`render_auth_page` 在渲染时导入面板，面板在顶层导入 auth 的客户端工厂与摘要函数。
- 邀请码摘要与 schema 错误文案仍留在 auth，因为注册流程也使用它们。
- `test_supabase_backend.py` 的面板用例改指 `modules.admin.panel`。
- CI 增加三条静态检查：CSS 变量引用完整性、图表颜色、Plotly CSS 变量，全部阻断。
- 全量 476 项通过。



