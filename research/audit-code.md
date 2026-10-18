# 代码与工程架构审计（A 号审计员）

- 审计对象：`C:\Users\ASUS\Desktop\24024115 郑昊\气象网站\weather_app`（Python 3.12 + Streamlit 1.59.1 单体应用）
- 审计性质：**只读**。未修改、未格式化、未移动任何源码文件。
- 取证方式：全仓 AST 导入图、`grep`/正则统计、逐文件阅读、对既有计划与 `research/` 文档先读后写。
- 环境限制：审计机未安装 `streamlit / pytest / pandas / python-docx / plotly`，**未能执行测试与应用**。凡依赖运行时行为的判断（如 Streamlit 会话语义、客户端会话存储）在条目内标注「推断」，并在文末给出复现确认清单。
- 先读材料：`docs/superpowers/plans/`（2026-09-13 五份 + 2026-10-18 一份）、`research/内部不一致清单-2026-09-13.md`、`research/supabase-体检-2026-10-18.md`、`README.md`、`SECURITY.md`。**本报告不重复这些文档已记录并处置的事项**（边界见第 8 节）。

---

## 一、一句话结论

> 这套代码真正的结构性风险不在「某个文件太大」，而在于**同一个语义存在三个以上的真相源，而真相源之间没有机器可校验的绑定**：预警阈值有 4 份（config / analyzer 读 config / nwp 硬编码 / 侧边栏默认值）、WMO 天气码有 1 张死表 + 5 处活实现、配色有 3 套（design_tokens / config.COLORS / config.toml）、会话状态有 73 个键 + 3 份手工 keep 清单。半年后最先烂掉的是三类改动——改一个阈值、加一个数据源、加一个 Tab——每次都要在 3~5 个文件里同步，漏一处不报错，只让页面之间互相矛盾；而唯一能拦住它的测试层锁的恰恰是源码字符串（`if st.session_state["active_tab"] == 3:` 这类），重构每动一次结构先得改测试。

---

## 二、数据画像（先看数字，结论从数字来）

| 指标 | 数值 | 取证方式 |
|---|---|---|
| 全部 `.py` 行数 | 21,634（应用代码 14,876，不含 tests/research/示例数据） | 逐文件行数 |
| `modules/` | 24 个模块 + `__init__.py` | 目录枚举 |
| 入口 `app.py` | 929 行；`st.*` 调用 154 处；`st.session_state` 引用 143 处 | 正则统计 |
| 最大模块 | `nwp_forecast.py` 1,935 行 / 36 函数；`reporter.py` 1,219；`visualizer.py` 936；`auth.py` 877；`data_loader.py` 844；`theme_css.py` 834；`weather_wall.py` 779 | AST |
| 最长函数 | `_analyze_forecast` 292 行（nwp:924）；`dark_extra_css` 233；`_render_admin_panel` 212；`render_visualization_tab` 158；`render_api_section` 157 | AST |
| 同时含 UI 调用与业务逻辑的模块 | data_loader(92 处 st.*)、nwp_forecast(84)、auth(81)、visualizer(57)、era5_guide(34)、chart_reader(27)、reporter(21)、weather_wall(20) | 正则统计 |
| `st.session_state` | **73 个唯一键 / 352 次引用**；另有 **153 个字面 widget key**（163 次）+ 10 处动态 key → 会话命名空间约 226 键，无注册表 | 正则统计 |
| `st.rerun` / `st.stop` | 52 / 12 处，散布 10 个文件；`app.py` 独占 23 处 rerun | 正则统计 |
| `try/except` | 131 处 `except`；`st.error/warning/info/exception/toast` 共 110 处 | 正则统计 |
| 项目内 import 边 | 顶层 43 条 + 函数内 17 条；被依赖最多：`utils` 9、`config` 8（+1 懒加载）、`design_tokens` 6 | AST |
| 测试 | 15 个文件、**412 个 `test_*` 函数**；其中 **44 处 `_source/_read/read_text` 引用（含 4 个辅助定义）**；13 个文件自带 `__main__` 直跑样板 | 正则统计 |
| 测试未覆盖的核心模块 | `data_loader` / `reporter` / `visualizer` / `nwp_forecast`（除 AQI 私有函数）/ `config` 无专用测试文件 | tests 目录枚举 |
| CSS 体量 | `theme_css.py` 834 行（约 700 行是 CSS 字符串内容），约 199 个选择器块、249 处 `data-testid`、242 处 `var(--)` | 正则统计 |
| 硬编码颜色残留 | 全仓 276 个 `#rrggbb`：design_tokens 166、config 37、nwp 21、manual 15、theme_css 10、chart_theme 8、weather_wall 7、visualizer 5、verify 5 | 正则统计 |

> 这些数字的含义：**"分层"主要写在 docstring 里，实际按"谁先写谁就实现一份"运行**。下面所有条目均以这些数字或具体行号为据。

---

## 三、文字版模块依赖图

```
                        ┌──────────────── app.py (929) ────────────────┐
                        │ 48 init_theme()  432 inject_theme()          │
                        │ 437 登录门禁  441 ensure_session()            │
                        │ 684 radio 导航 → 6 个 if dispatch             │
                        └──┬───────┬───────┬───────┬───────┬───────┬──┘
                           │       │       │       │       │       │
              ┌────────────┘       │       │       │       │       └─────────────┐
              ▼                    ▼       ▼       ▼       ▼                     ▼
        auth.py(877)          data_loader  data_    visualizer reporter      nwp_forecast
        ├ supabase_backend    (844)        quality  (936)      (1219)        (1935)
        ├ utils               ├ era5_guide  (200)    │            │            ├ aqi.py(170)
        │                     │   └ era5_script_pack  │            │            ├ verify.py
        │                     ├ config            (767)│            │            ├ design_tokens
        └─(lazy) theme_aether ├ utils                  │            │            └ gfs_cache
             + city_prefs     └ utils                   └ design_tokens
                                      │
                                      ▼
                              chart_reader(540) ─► ai_narrative(389)
                                      ├(lazy) db.py(257) ─►(顶层) auth.py  ← 反向依赖
                                      └(lazy) ai_narrative

        weather_wall(779) ─┬ geocode / geolocate / city_prefs
                           └(lazy private) nwp_forecast:_compute_cn_aqi
        codec / manual / theme_css / chart_theme / design_tokens ─ 展示层/工具

  持久化与外部：Supabase（auth/db/gfs_cache/chart_reader 配额）、Open-Meteo（data_loader/
  weather_wall/nwp_forecast）、LLM（ai_narrative/chart_reader）、CDS 脚本包（era5_*）
```

读图要点：

1. **`config` 是被依赖最多的"配置"模块，但它同时是渲染模块**（`safe_chart` 定义在 config.py:707，内部懒加载 `chart_theme`，config.py:723）。config 与 `design_tokens` 之间靠**函数内 import** 维持不炸的循环：`design_tokens.py:420/435` 懒加载 `config.COLORS`，`config.py:723` 懒加载 `chart_theme`，而 `chart_theme.py:25` 顶层 import `design_tokens`。顶层图无环，合并懒加载后存在环 `config → chart_theme → design_tokens → config`。
2. **`db.py` 顶层 import `auth.py`（db.py:13）**，而 `auth.py` 是登录页 UI + 管理员面板 + 安全自检（877 行、81 处 `st.*`）。数据层反向依赖 UI/会话模块，导致任何 `db` 使用都连带 Streamlit 与登录逻辑。
3. **`weather_wall.py:225` 从 `nwp_forecast` 私有导入 `_compute_cn_aqi`**：AQI 的公共实现已在 `modules/aqi.py`，但"四元组 + 具体色值"的适配器留在 nwp，天气墙只能借私有函数。
4. `app.py` 顶层 import 17 个项目模块（含全部 6 个 Tab），首次加载即拉起 requests/plotly/python-docx；函数体内另有 9 处 `from db import ...` / `from modules.manual import ...` 等懒加载（app.py:52,136,252,447,478,497,506,527,636），风格不一致且掩盖了依赖方向。

**import 期副作用清单**（第 8 项要求）：

| 位置 | 副作用 | 评价 |
|---|---|---|
| `app.py:48` | `theme_aether.init_theme()` 在模块级执行，写 `session_state["dark_mode"]` | 入口脚本可接受；但"import app.py = 执行整个应用"，测试只能走 AppTest |
| `app.py:51-53, 60-61` | 模块级读写 `session_state["_wall_show"] / ["_nav_stack"]`，发生在登录门禁之前 | 未登录会话也进入状态初始化 |
| `app.py:421,432` | 模块级 `st.set_page_config` + `inject_theme()` | 正常 |
| `chart_theme.py:108` | 模块级 `register()` 注册 Plotly 模板并改全局 `pio.templates.default` | 注释已说明时序理由（:105-107），可接受；但属于 import 即改全局 |
| `design_tokens.py:457` | 模块级 `_parity_guard()`，不一致直接 `AssertionError` | 纯校验，可接受 |
| `weather_wall.py:23-92` | `CITY_LIBRARY`（66 条城市）+ `_BY_ZH` 在 import 期构建 | 数据内嵌在 UI 模块 |
| `era5_guide.py:28-260` | ERA5 catalogue（4 产品 / 8 分组）在 import 期构建 | 同上；真相源还与 `research/era5_variable_enums_2026-09-13.json` 快照绑定 |
| `nwp_forecast.py:785` | 模块级 `_WS_COLORS = [css_var(...)]` | 纯函数，无 session 依赖，可接受 |

---

## 四、S1 清单（结构性：不修会持续恶化）

> S1 判定口径：新增同类功能的成本随规模递增，或存在一致性/并发隐患，且现有测试不会拦。

### S1-1 预警检测有 4 份阈值与 2 套等级字符串，用户自定义阈值只对观测侧生效

**证据**

```python
# modules/nwp_forecast.py:976-984（预报侧硬编码阈值与 ASCII 等级）
    if len(hot) > 0:
        peak = hot.max()
        peak_date = str(hot.idxmax())
        if peak >= 40:
            level, lv_num, icon_ = "红色", "I级", "[红]"
        elif peak >= 37:
            level, lv_num, icon_ = "橙色", "II级", "[橙]"
        else:
            level, lv_num, icon_ = "黄色", "III级", "[黄]"
```

```python
# config.py:212-215（真相源，等级用全角罗马数字）
HIGH_TEMP_WARNING = {
    "黄色": {"condition": "连续3天日最高气温≥35℃", "temp": 35, "days": 3, "level": "Ⅲ级", "icon": "[晴]"},
    "橙色": {"condition": "24h内最高气温≥37℃", "temp": 37, "hours": 24, "level": "Ⅱ级", "icon": "[火]"},
    "红色": {"condition": "24h内最高气温≥40℃", "temp": 40, "hours": 24, "level": "Ⅰ级", "icon": "[红]"},
```

- 观测侧：`modules/analyzer.py:66-108` 读 `config.HIGH_TEMP_WARNING` 并叠加 `CUSTOM_THRESHOLDS`。
- 预报侧：`nwp_forecast.py:960-1050` 自己写死 `35/40/37`、`25/50/75/100`、`10.8/17.2/24.5`，**不读 config，也不读用户自定义阈值**。
- 第三份：`app.py:541-597` 侧边栏 `number_input` 的 `value=` 把 config 里的数字再抄一遍（35/37/40、10.8/17.2/24.5/32.7、500/200/50、50/50/50/100、0/-5/-3、3000/2000、6h）；config 改阈值，UI 默认值不会跟。
- 两套等级字符串：config 用 `Ⅰ/Ⅱ/Ⅲ/Ⅳ`，nwp 用 `I/II/III`，两者都会进 Word 报告（reporter 直接渲染 `warn["level_num"]`）。

a) **根因**：预报 Tab 是后期加的，数据结构不同（未来逐时 → 日聚合 vs 过去逐时），团队选择"复制一份判定"而不是把判定层与数据粒度解耦；侧边栏又是第三个消费者，直接把数字当 UI 默认值。config 只被当成"阈值字典"，没有提供"判定函数"这个公共出口，于是每次都要就地重写。

b) **不修的长期代价**：下次调整国家标准（例如高温黄色改为 35℃ 且连续 2 天）要改 config + app 侧边栏 + nwp 三处，漏 nwp 就是"同一个平台两个页面给不同预警"；新增一种灾害（例如道路结冰）要在 analyzer 和 nwp 各写一遍；用户改了侧边栏阈值后去预报页，发现没有生效——这是产品承诺层面的不一致。

c) **最小修复切口**：不要求"全面统一"，只做两件小事，1 个新文件 + 2 个改动点：
   - 在 `analyzer.py` 旁新增 `modules/warn_rules.py`：提供 `resolve_thresholds(custom)` 与 `level_of(kind, value)`，把"阈值读取 + 等级字符串"从两个实现里抽出来；
   - `nwp_forecast._analyze_forecast` 的 3 处硬编码改为调用它；app.py 侧边栏 `value=` 改为从 config 读取默认值。
   预计改动 `nwp_forecast.py` 约 40 行、`analyzer.py` 约 30 行、`app.py` 约 60 行（纯替换）。

d) **对抗性审查——保留现状的理由**：预报判定口径是"未来 N 天日聚合"，观测是"过去 24/48h 窗口"，语义真的不同（例如连续高温天数、过程累计降水），强行合并会把两套判定揉成一个参数爆炸的函数。**因此第一步只统一"阈值数值 + 等级标签 + 自定义阈值可见性"，不合并判定算法**。若产品明确"预报页不需要自定义阈值"，则至少要在侧边栏文案里写明作用范围，否则用户会认为改了没生效。

---

### S1-2 同一语义多个实现（重复矩阵），其中 WMO 天气码的"官方表"是死代码

**证据（死表）**

```python
# config.py:665-669（全仓 0 引用；grep WMO_WEATHER_CODES 只命中定义行）
WMO_WEATHER_CODES = {
    0: "晴/无重要天气",
    1: "云量减少",
    2: "云量无变化",
    3: "云量增加",
```

**证据（活的 5 处实现，各写各的映射）**

```python
# modules/nwp_forecast.py:634-641
        def _wet_prob(c):
            if c in range(0, 20): return 0.10
            if c in range(20, 50): return 0.50
            ...
# modules/nwp_forecast.py:1554（生活指数）
    rain_codes = set(range(50, 70)) | set(range(80, 87)) | set(range(95, 100))
# modules/weather_wall.py:271（场景）
def map_scene(code, is_day=1) -> str:
# modules/codec.py:234-238（报文本地映射）
                    weather_map = {"TS": 95, "RA": 60, "SN": 70, ...}
# modules/analyzer.py:329（雷暴判定直接判 95-99 区间）
```

完整重复矩阵（每条都可用 `grep` 复核）：

| 语义 | 实现/真相源 | 计数 | 漂移现状 |
|---|---|---|---|
| 暗色判断 | `config._is_dark:351`、`design_tokens.is_dark:369`、`theme_aether.is_dark:156`、`chart_theme._is_dark:142` | 4 | 读同一个键，行为一致，但改键名要改 4 处 |
| WMO 天气码 | `config.WMO_WEATHER_CODES:665`（死）+ `nwp._wet_prob:634` + `nwp._calc_life_indices:1554/1595` + `weather_wall.map_scene:271` + `codec:234` + `analyzer.check_thunderstorm:329` | 1 死 + 5 活 | 同一码在"场景/概率/生活指数/雷暴/报文"里含义不同 |
| AQI 等级区间 | `config.AQI_LEVELS:562`、`nwp._AQ_LEVELS:314`、`design_tokens._AQI_TOKEN:332`、`aqi.level_of:148` | 2 份区间 + 2 份映射 | nwp 的末档是 `301~99999`，config 是 `301~500`；现有测试按"截到 500"比对锁死不漂移（test_aqi.py:225-233） |
| 热指数 | `analyzer.heat_index_celsius:33`（°F 回归再换回） vs `nwp.heat_index:557`（℃ 系数 + NaN 掩码） | 2 | 同名不同式、不同前置条件，结果不可比 |
| 风玫瑰 | `visualizer.wind_rose_chart:82`（频次、9 档、静风单列） vs `nwp._wind_rose_stats:790/_wind_rose_chart:819`（频率 %、8 档、静风不入柱） | 2 | 已有 caption 补丁（visualizer:821-822），口径仍不同 |
| 蒲福分档 | `config.BEAUFORT_SCALE:316`、`nwp._WS_BINS:779/_WS_LABELS:780`、`visualizer.speed_bins:109-119` | 3 | 边界值抄三遍，改一档要改三处 |
| 字段标签/单位 | `config.FIELD_LABELS:338`、`reporter:1206-1210`、`visualizer.ts_config:867-879`、`codec.field_config:322-332`、`app.weather_fields:181-183` | 5 | 单位串（℃/hPa/μg·m⁻³）各写一份 |
| 字段别名 | `config.FIELD_ALIASES:9`（172 行） vs `reporter._FIELD_ALIAS_REPORT:35-42` | 2 | reporter 只认 6 个别名，其余靠 `_resolve_field` 兜底 |
| 异常→中文 | `config.safe_chart` 内 `_FRIENDLY_MAP:748-755` vs `config.ERROR_TRANSLATIONS:773-786`（**0 引用**） | 2（1 死） | 死表有 12 键，活表只有 6 键 |
| 等级排序 | `config.WARN_LEVEL_ORDER:348`；reporter 在 :449 与 :1016 两次函数内 import | 1 源 + 2 处 import | 尚一致 |

a) **根因**：没有 domain 层。`config.py` 被当成杂物间（见 S2-2），谁需要常量就近加；"就近实现"在 6 个 Tab 各自独立开发的节奏下是理性选择，但缺少一个"新增语义时必须先查重"的机制（没有 lint、没有 CI 静态检查，`research/` 下的检查脚本不进门禁，见 S1-9/阻力清单）。

b) **不修的长期代价**：改动会"半生效"——例如把 AQI 六级颜色调深，设计页变了、报告图没变；把高温黄色改 2 天，观测页变了、预报页没变。这类不一致不会抛异常，只会被用户发现"页面互相矛盾"。新功能开发时，工程师需要先花时间判断"这个语义现在有几份、该改哪份"，正是"新增功能成本递增"。

c) **最小修复切口**（按语义逐项，一次一项，不搞大爆炸）：
   - 第一步只做 **WMO 码**：新建 `modules/weather_code.py`（纯函数：`label(code)`、`rain_probability(code)`、`is_rain(code)`、`scene(code, is_day)`），把 nwp/weather_wall/codec 三处映射搬进去，config 的死表删除或在 `weather_code.py` 里成为唯一数据源；预计改 4 个文件、净减少约 60 行。
   - 第二步做**热指数**：让 nwp 直接调用 `analyzer.heat_index_celsius`（或反向），保留一个公式。
   - 每完成一项，用 `research/check_py_vars.py` 同款"AST 扫描"模式加一条 CI 检查：禁止同一语义出现第二个常量表。

d) **对抗性审查——保留现状的理由**：WMO 码的 5 处用途确实不同（场景要 `is_day`、生活指数要"是否下雨"、读图概率要连续值、报文要反向码），合成一个函数容易变成"参数开关堆"。合理边界是：**数据表（码 → 语义属性）必须一份，取用函数可以多个**。风玫瑰的"频次 vs 频率"已有 caption 明确说明，属于有意的口径差异，可以保留；但蒲福边界值必须单源。

---

### S1-3 "单一真相源"是复制粘贴出来的：config.COLORS 与 config.toml 仍在和 design_tokens 并行

**证据**

```python
# config.py:495-523（注释声称"与 design_tokens 同源"，实现是手抄 hex）
COLORS = {
    ...
    # 预警颜色（与 design_tokens 的 warn-4/3/2/1 同源）
    "warn_blue": "#1f5c9e",
    "warn_yellow": "#8a6410",
    "warn_orange": "#a8561f",
    "warn_red": "#a82c22",
    # 图表色系（与 design_tokens 的 temp/pres/humid/wind/vis/rain 同源）
    "temp_color": "#c0392b",
```

```toml
# .streamlit/config.toml:10-15（第四套浅色）
[theme]
primaryColor = "#2563eb"
backgroundColor = "#ffffff"
secondaryBackgroundColor = "#f8fafc"
textColor = "#0f172a"
```

- `design_tokens.LIGHT_TOKENS` 的 accent 是 `#2f61a8`（:59），surface 是 `#fffdfb`（:43），与 config.toml 的 `#2563eb / #ffffff` **不同**；`design_tokens` 顶部 docstring 说"改造前三套配色"，实际仍有第三套在 `.streamlit/config.toml` 里生效（Streamlit 原生组件用它，自定义 CSS 用 token）。
- `config.COLORS` 与 `design_tokens` 的桥是 `COLOR_KEY_TO_TOKEN`（design_tokens:386-407），只映射键名；`color_value()` 在未登记键时**直接返回 config.COLORS 的 hex**（`design_tokens.py:435-437`），等于给"旧 hex"留了永久后门。
- `config.WARN_STYLES:596-601` 与 `LIGHT_TOKENS["warn-4..1"]:112-115` 是同一语义的第二份（含 `bg` 色）。
- 现存 276 个硬编码 hex 中，nwp 21、verify 5、visualizer 5、chart_theme 8 个是"token 化之后新长出来的"（如 `nwp_forecast.py:627` 的 `#e67e22`、`:692` 的 `#475569`），说明没有机制阻止新硬编码。

a) **根因**：token 化改造选择了"兼容旧调用点"的路径——保留 `config.COLORS` 的键名与 hex 作为 fallback，只在 `design_tokens` 里做映射，没有删除旧源。旧源一旦还在，就永远会有人继续往里面加。

b) **不修的长期代价**：改品牌色需要同步 3 个文件 4 张表；图表（Plotly 要 hex）与 HTML（要 var()）之间的取值路径继续分叉；暗色模式下 fallback 会返回亮色 hex，出现"某个图例在深色页面上是浅色"——这类 bug 已经发生过（design_tokens 注释、theme_css 注释里都有记录），还会再发生。新增一个图表颜色需要同时登记 `COLORS` + `COLOR_KEY_TO_TOKEN` + 可选 token，三处漏一处就静默不跟随主题。

c) **最小修复切口**：
   - `config.COLORS` 改为从 `design_tokens` **派生**（`{k: token_value(v) for k, v in COLOR_KEY_TO_TOKEN.items()}` + 保留极少数非 token 键），删除 37 个 hex 中的大部分；
   - `.streamlit/config.toml` 的 `[theme]` 与 `LIGHT_TOKENS` 对齐（或加一条启动断言：两者 accent/surface 相等），并在 `theme_aether.inject_theme` 里注释说明"config.toml 只服务原生组件"；
   - 增加 CI 检查：`modules/` 下新增 `#rrggbb` 字面量必须出现在 design_tokens 或白名单文件（`research/check_chart_colors.py` 已有雏形）。
   预计改 `config.py` 20 行、`design_tokens.py` 10 行、`.streamlit/config.toml` 4 行。

d) **对抗性审查——保留现状的理由**：`config.toml` 的 `[theme]` 是进程级的，Streamlit 明确不支持按会话切换，因此它**必须**存在（theme_css docstring 已解释）。只要它的值与亮色 token 一致，就不算"第四套配色"，只是"原生组件的基线"。`COLORS` 的旧键名被 10+ 文件引用，一次性删除是高风险动作，保留 fallback 在过渡期是合理的——但必须把 fallback 从"返回旧 hex"改成"返回当前主题的 token 值"，否则它永远跟随不了主题。

---

### S1-4 会话状态没有 schema：73 个键、3 份手工 keep 清单，错误恢复按钮会自伤登录态

**证据**

```python
# app.py:87-96（错误恢复路径：保留 auth_user，但没有保留 _sb_client）
def _safe_reset():
    """错误恢复：清除应用数据，保留导航默认值和登录态，回到导入页。"""
    keep = {"active_tab", "import_step", "import_method", "_nav_stack", "auth_user"}
    keep |= {k for k in st.session_state if k.startswith(("auth_", "invite_", "admin_"))}
    for _k in list(st.session_state.keys()):
        if _k not in keep:
            del st.session_state[_k]
    st.session_state["active_tab"] = 0
```

```python
# auth.py:38-39 / 246-251（客户端键名不在任何 keep 前缀里；缺客户端时不登出）
_SESSION_CLIENT_KEY = "_sb_client"
_SESSION_ADMIN_KEY = "_sb_admin_client"
...
    sb = st.session_state.get(_SESSION_CLIENT_KEY)
    if sb is None:
        # 测试桩或极端残缺状态下可能只有 auth_user 没有客户端；不在这里
        # 强制登出，避免把一次内部状态不完整误判成会话过期。
        _LOG.warning("已登录但缺少会话客户端，跳过会话校验")
        return
```

- 三份 keep 清单：`app._safe_reset:89`（5 键 + 3 前缀）、`app._RESET_KEYS_BY_TAB:103-117`（按中文 Tab 名分组的 27 键）、`auth._LOGOUT_KEEP:183`（仅 `_nav_stack`）。73 个键靠人肉维护。
- `_RESET_KEYS_BY_TAB` 已经漂移：`nwp_air_quality_for_analysis`（nwp:1870/1874 写入）、`chart_reader_usage_last/_total`、`_wall_fallback/_wall_aqi_fallback`、`gfs_fc_cache_*`、`aq_cache_*` 都不在任何清单里；`nwp_combined` 在清单里但全仓从未写入（死键）。
- 自动载入会"复活"被重置的数据：`_safe_reset` 删掉 `_auto_load_done`（:477 每次会话只尝试一次），下一轮 rerun 时 `app.py:476-482` 重新执行并载入云端最近数据集。
- 同时 `_safe_reset` 不 `st.rerun()`（对比 `_reset_current_tab` 有 rerun），在同一个 run 内继续渲染，已实例化的 widget key（如 `wall_show_toggle`、`debug_mode`、`ht_y`）被删除。

a) **根因**：Streamlit 官方没有状态分层（"数据/UI widget/导航/登录"没有原生区分），项目用"清单"补；清单从一开始就是手写的，没有和键的实际写入点建立任何自动关联，也没有测试断言"所有写过的键都在清单里"。`_safe_reset` 的 keep 集合又是在修 P-06 时补的，补的时候只想到"登录态"，没想到"登录态依赖两个客户端对象"。

b) **不修的长期代价**：每加一个状态键（这个应用每做一个功能平均 +3 个键）都要记得改 1~3 处清单，漏了不会报错；错误恢复是**用户最后一次自救机会**，在这里破坏会话会让"重置会话并回到首页"从救命按钮变成第二个故障点；`_sb_client` 被删后，按代码路径推断，用户仍是 `is_authenticated()==True`，但云端读写用的是没有登录态的新客户端（`get_supabase()` 会新建，auth.py:147-155），保存会失败、列表会变空，而 `ensure_session` 对"有用户无客户端"是显式跳过（上引 :246-251），没有自愈路径。**此条须在部署环境复现确认**（步骤见文末）。

c) **最小修复切口**（1 个新文件 + 3 处调用替换）：
   - 新建 `modules/app_state.py`：`STATE_DEFAULTS: dict[str, Any]`（键 → 默认值）+ `SCOPE: dict[str, Literal["session","data","tab","auth"]]`，提供 `reset_data()` / `reset_tab(name)` / `logout_keep() -> set[str]`；
   - `_safe_reset` 改为 `keep = app_state.auth_scope()`（含 `auth_user`、`_sb_client`、`_sb_admin_client` 与前缀），并在重置后写 `st.session_state["df"]=None` + 设一个 `"_auto_load_blocked": True` 让自动载入跳过本会话；
   - `_RESET_KEYS_BY_TAB` 改为由注册表按 scope 生成（`data`/`tab` 两类），删除 `nwp_combined` 死键。
   预计改 `app.py` 约 60 行、`auth.py` 10 行、新增 1 文件。

d) **对抗性审查——保留现状的理由**：如果部署运行模式是"每个会话独立进程"（Streamlit Cloud 不是，但某些自托管配置可以做到），模块全局与客户端对象的问题会弱化；如果团队只有 1~2 人且状态规模不再增长，手写清单的成本确实可控。**但 73 键已经在增长（读图配额、天气墙、ERA5 预设都是后加的），且清单已证明会漏**；这不是"风格问题"，是"下一次功能变更必踩"的问题。

---

### S1-5 跨 Tab 契约靠"渲染顺序 + 键名"：预警只在读图 Tab 里算，导出 Tab 直接读

**证据**

```python
# app.py:889-908（"读图解析"分支里做观测数据预警检测）
# ---- Tab 3: AI 读图解析 ----
if st.session_state["active_tab"] == 3:
    # 数据指纹缓存：数据未变化时跳过重复检测
    if st.session_state["df"] is not None:
        fp = _df_fingerprint(st.session_state["df"])
        if st.session_state.get("_warn_fp") != fp:
            all_w = []
            checks = [
                ("高温", check_high_temperature), ("寒潮", check_cold_wave),
                ...
            ]
            for name, fn in checks:
                try:
                    all_w += fn(st.session_state["df"])
                except Exception as e:
                    st.warning(f"{name}检测因数据问题跳过: {e}")
            st.session_state["warnings_list"] = all_w
```

```python
# app.py:913-921（导出 Tab 只读结果，没有"是否已算过"的判断）
if st.session_state["active_tab"] == 4:
    _safe_render(
        "报告导出", render_export_tab,
        st.session_state["df"],
        st.session_state.get("warnings_list", []),
        st.session_state.get("quality_score", 0.0),
```

- `warnings_list` 的唯一生产点在 `active_tab == 3`；用户从导入直接去导出（或从侧边栏「我的数据集」载入数据后直接去导出，app.py:513-519），报告里事件检测为空/是上一份数据的旧结果。
- 同类键还有：`quality_score`（只在导入向导 Step 2 或"跳过向导"分支写，app.py:807-809/876-879；侧边栏载入数据集不写）、`fc_analysis`/`life_indices`（只在预报 Tab 渲染时写，nwp:1921-1926）、`_filter_date_range`（只被 `_get_filtered_df` 用于可视化，app.py:403-405，导出/分析都用未过滤的 `df`）。
- 计划中的"Tab 顺序已互换"（可视化 index 1、预报 index 2）进一步说明顺序是隐式契约：注释 `app.py:236`、`:815` 都在解释序号，而不是用枚举。

a) **根因**：Streamlit 的 rerun 模型让"渲染时顺便计算"成为最省事的写法；写代码时只有一个 Tab 需要这个结果，后来导出 Tab 需要，就"直接读 session_state"。没有人定义"派生数据（warnings/quality/analysis）在 dispatch 之前统一计算"这一层。

b) **不修的长期代价**：新增第 7 个 Tab（例如"气候统计"）时，无法判断该在哪个环节拿数据；调整 Tab 顺序或把渲染拆成 `st.tabs`（惰性渲染）会静默改变数据可见性；导出结果依赖用户的点击路径——这是最难受的一类 bug，因为测试很难覆盖所有路径，用户也无法描述清楚。质量评分字段已经出现过一次"恒为 0"（app.py:804-806 注释记录了原 bug），同类问题还会出现在 `quality_score` 的直接载入路径上。

c) **最小修复切口**：
   - 在 `app.py` 的 Tab dispatch 之前加一个 `_ensure_derived()`（约 30 行）：用 `df_fingerprint` 做缓存键，统一算 `warnings_list` / `quality_score`，写入 session_state；Tab 3、Tab 4、进度条都只读；
   - 把 `_filter_date_range` 的作用范围在 UI 上写明（"仅影响图表"）或让导出也走 `_get_filtered_df`（二选一，不能维持"看起来生效实际不生效"）。
   预计只改 `app.py`（可复用 `utils.df_fingerprint` 与 `data_quality.render_quality_report` 的纯函数部分）。

d) **对抗性审查——保留现状的理由**：如果产品明确"必须按 导入→质控→图表→读图→导出 的顺序使用"，那么当前路径是自洽的，且 6 个 Tab 的固定顺序短期内不会变；`_render_next_step_hint`（app.py:313-345）确实在引导用户按顺序走。**但侧边栏「我的数据集」和「跳过向导」提供了两条跳过路径，它们不经过 Step 2/读图 Tab，契约已经被产品自己打破了**。要么在 UI 上阻断跳转（禁用导出按钮直到派生数据就绪），要么把派生数据前移——不能两者都不做。

---

### S1-6 数据流契约只在导入端做一次，污染列名有两套，云端 CSV 往返丢 dtype/无版本

**证据**

```python
# modules/data_loader.py:631-637（观测/API 路径：标准列名 pm25 / nox）
        df = pd.DataFrame({
            "timestamp": pd.to_datetime(hourly["time"]),
            "pm25": hourly.get("pm2_5", [None]*n),
            "pm10": hourly.get("pm10", [None]*n),
            "so2": hourly.get("sulphur_dioxide", [None]*n),
            "nox": hourly.get("nitrogen_dioxide", [None]*n),
        })
# modules/nwp_forecast.py:380-388（预报路径：原始列名 pm2_5 / no2 / co / o3）
        df = pd.DataFrame({
            "timestamp": pd.to_datetime(h["time"]),
            "pm2_5": h.get("pm2_5"),
            "pm10": h.get("pm10"),
            "co": h.get("carbon_monoxide"),
            "no2": h.get("nitrogen_dioxide"),
            "so2": h.get("sulphur_dioxide"),
            "o3": h.get("ozone"),
        })
```

- `config.STANDARD_FIELDS:182-187` 里是 `so2/nox/tsp/pm25/pm10`，不含 `pm2_5/no2/co/o3`；同一污染物在两条数据链上列名不同，任何"拿到一个空气质量 DataFrame"的下游代码必须先知道它来自哪条链。
- 无 schema 版本、无 dtype 规范化：`data_quality.py:10-16` 的注释自己写着"导入链路从不保证数值列 dtype"；消费端用 **38 处 `"x" in df.columns` 守卫 + 12 处 `pd.to_numeric`** 各自兜底（analyzer 8 处、app 2、nwp 1、data_quality 1）。
- 云端持久化是 CSV 往返：`db.py:59` `df.to_csv(index=False)`；`db.py:161-165` 读回时只恢复 `timestamp`，其余 dtype、列集合、单位约定都不校验，也没有 schema 版本字段。
- 单位换算靠注释与手工：CO 的 μg/m³ → mg/m³ 在 `nwp_forecast.py:390-400` 与 `weather_wall.py:218/237` 各写一次；ERA5 的 K→℃、m→mm、Pa→hPa 在生成脚本里另有一份（见 S2-9）。

a) **根因**：产品定位是"用户上传任意 CSV，尽力解析"（`data_loader.parse_timestamp` 的 L1-L5 五级猜测、字段别名 172 行都说明这一点），所以入口选择了"宽松归一 + 不拒绝"；但宽松之后没有"归一结果声明"这一层——列名、单位、dtype、必需列都没有被显式表达，下游只能各自猜。

b) **不修的长期代价**：加一个新数据源（气象站、ERA5、CMIP、用户历史库）时，每条链都要重新决定列名映射与单位换算，且新旧链的数据不能直接 merge（污染物列名已经不同）；云端旧数据集在列改名后载入，缺列不会被发现，报告里静默少一节；`save_dataset` 的 CSV 往返会让 `station_id="007"` 变成 `7`、时区信息丢失，这类问题只在用户回读时暴露。

c) **最小修复切口**（1 新文件 + 4 个入口接线）：
   - 新建 `modules/schema.py`：`STANDARD_FIELDS` + `DTYPES` + `UNITS` + `REQUIRED_FOR`（各分析所需的列），提供 `validate(df) -> (df, issues)`（只标注/转换，不拒绝）与 `standardize_air_quality(df)`（`pm2_5→pm25`、`no2→nox`）；
   - 四个入口调用它：`data_loader.render_file_upload_section`、`render_api_section`、`db.load_dataset`、`nwp.fetch_*` 的返回处；
   - `db.save_dataset` 增加 `schema_version`（写进数据集名称或新增列，或至少在 `load_dataset` 里跑 `validate` 并给出缺失列提示）。
   预计新增 1 文件（约 120 行），改 4 个文件各 5~15 行。

d) **对抗性审查——保留现状的理由**："严格 schema 会拒绝合法用户数据"是真实风险，本报告也不建议拒绝；建议的是**声明 + 标注**：归一化后把 issues 显示在质控页（该页已有 issues 列表，data_quality.py:189-198）。此外，如果产品未来只服务"自己的模板 CSV"一个来源，当前宽松解析反而够用；但代码里已经有 4 个来源（文件/手动/API/GFS/云端），这个前提不成立。

---

### S1-7 错误边界把失败变成"页面异常"，恢复按钮本身破坏会话，失败不可诊断

**证据**

```python
# app.py:78-84（所有 Tab 的唯一出口）
def _safe_render(name, fn, *args, **kwargs):
    """包裹 tab 渲染调用，异常时走 _tab_error 而非抛出白屏。"""
    try:
        return fn(*args, **kwargs)
    except Exception as _exc:
        _tab_error(name, _exc)
        return None

# app.py:886-887（第一个失败后，第二个调用仍用 None 继续）
    _viz_df = _safe_render("可视化-数据", _get_filtered_df)
    _safe_render("可视化", render_visualization_tab, _viz_df)
```

- `_safe_render` 有 16 个调用点（app.py:746/747/754/768/807/845/849/851/863/876/886/887/910/914/925/929），其中 **5 处包的是数据函数而不是渲染函数**（`_get_filtered_df`、`render_quality_report`），错误被统一描述成"「可视化-数据」页面加载出现异常"，用户看不到"筛选条件有问题"这层信息。
- `_tab_error`（app.py:64-75）默认只显示一句"已隔离处理"，堆栈只在 `get_debug_mode()` 时展示；错误信息不进日志、不进任何持久通道（全仓没有 `logging` 到文件的配置，`_LOG.warning` 只在少数地方用），线上用户截图也无法定位。
- 失败后状态是"半个"：`warnings_list` 可能保持旧值（app.py:903-907 的循环里单个检测失败只 warning 并继续，见上一条证据），`quality_score` 保持旧值，`df` 保持旧值；没有任何"本次渲染不完整"的标记。
- 恢复按钮调 `_safe_reset`（S1-4），即"诊断失败"的路径本身会破坏会话。

a) **根因**：错误边界是作为"防止整页白屏"的安全补丁加进来的（P-06），设计目标是"用户不看到堆栈"，没有同时设计"开发者如何看到堆栈"。Streamlit 的异常会终止脚本且不落日志，团队就默认"开 debug 开关复现"是唯一通道。

b) **不修的长期代价**：线上问题的平均定位时间随模块数线性上升——用户只知道"某个 Tab 加载异常"，而 131 处 `except` 里大量是 `pass`/统一文案（`safe_error_text` 只在 debug 时附 200 字摘要，utils.py:162-175），错误在传到边界时上下文已经丢失。新增功能越多，越可能"偶发一次、无法复现"。

c) **最小修复切口**（1 个文件 + 1 个小改动）：
   - 在 `app.py` 增加失败记录 sink：`_safe_render` 捕获时把 `{tab, time, df_fingerprint, exc_type, str(exc)[:200], traceback尾3行}` 追加到 `st.session_state["_error_log"]`（环形 20 条），侧边栏加一个"最近错误"expander（仅登录用户、无堆栈、含时间与 Tab）；
   - `_tab_error` 里"重置会话"按钮改为调用修复后的 `_safe_reset`（S1-4），并在按钮 help 写明"会清空当前数据"。
   预计改 `app.py` 约 40 行，不动其他模块。

d) **对抗性审查——保留现状的理由**：对普通用户隐藏堆栈是明确的安全要求（P-06），不能退回去；debug 开关已经提供了完整堆栈通道，如果线上问题都能让管理员开 debug 复现，当前方案够用。**但"复现"对天气类应用并不便宜**：需要特定数据 + 特定路径，而失败现场（哪份数据、哪个指纹、哪个 Tab）一旦丢失就找不回。记录 20 条摘要的成本极低，收益是把"无法复现"变成"可对照"。

---

### S1-8 上帝模块里逻辑与渲染无法分离；唯一被提炼的纯逻辑层（chart_reader）反证了可行性

**证据（"纯计算"函数直接读 widget 状态）**

```python
# modules/nwp_forecast.py:1492-1502
def _calc_life_indices(fdf):
    """计算 7 项生活指标，返回 dict。优先用 Open-Meteo current= 真实时数据。"""
    if fdf is None or fdf.empty:
        return {}

    # 真实时实测(独立 API 调用,不依赖服务器时钟)
    lat = st.session_state.get("fc_lat")
    lon = st.session_state.get("fc_lon")
    model_label = st.session_state.get("fc_model", "GFS 无缝混合 (gfs_seamless)")
    model_value = GFS_MODELS.get(model_label, "gfs_seamless")
    cur = _fetch_gfs_current(lat, lon, model_value) if (lat is not None and lon is not None) else None
```

- 该函数被描述为"计算"，却依赖三个 widget key：用户在输入框改了经纬度但没点"获取预报"时，`fdf` 还是旧坐标的数据，生活指数会按新坐标去取实时值——两份数据来自不同坐标，页面不会提示。
- `nwp_forecast.py` 1,935 行 / 36 函数，职责横跨：HTTP 拉取（:184-261）、三级缓存（:129-180）、AQI 图表（:429-556）、预报图表（:589-923）、292 行分析（:924-1215）、生活指数（:1492-1636）、渲染（:1218-1935）。同文件里 `safe_chart` 与 `pd.DataFrame` 交替出现，无法只 import 分析部分。
- 同类问题：`reporter.py` 1,219 行（docx 排版 + 业务文案 + 表格数据拼装）、`theme_css.py` 834 行（697 行非注释代码几乎全是字符串）、`weather_wall.py` 779 行（城市数据 66 条 + HTTP + AQI + CSS + 卡片 HTML + session 处理）、`visualizer.py` 936 行（图表 + 7 个面板渲染）。
- 反证：`chart_reader.py` 前 330 行是纯逻辑（图片校验/编码/prompt/配额纯函数），渲染集中在 `render_chart_reader_tab:437`，因此它有 41 条测试且多为行为断言；`analyzer.py` 甚至只做了纯逻辑（465 行、0 处 `st.*`）、`aqi.py` 170 行纯逻辑。**同一个团队有能力做分层，问题在于哪些模块做了、哪些没做。**

a) **根因**：Streamlit 的单脚本模型鼓励"拿到数据就地渲染"；`nwp_forecast` 是在原"智能分析 Tab"上连续加功能长出来的（高温面板、AQI、风玫瑰、生活指数、预报验证），每次都在同一个文件里加一节，没有人负责在文件超过阈值时做切片；`analyzer` 之所以纯，是因为它从第一天就只被"检测"一个职责使用。

b) **不修的长期代价**：任何 UI 改动都要承担"碰到分析逻辑"的风险；`_analyze_forecast`（292 行）和 `_calc_life_indices`（140 行）无法被单测直接覆盖（CI 里 AppTest 是 `continue-on-error`，见 S1-9），修改阈值/算法只能靠肉眼；`nwp` 的 import 成本（requests+plotly+全部分析）落在每个新会话首次加载上，Streamlit Cloud 冷启动变慢。

c) **最小修复切口**（一次只切一块，优先收益最高的）：
   - 新建 `modules/forecast_analysis.py`：把 `_analyze_forecast`（:924-1215）、`heat_index`（:557-583）、`_calc_life_indices`（:1492-1636）、`_calc_ssd`（:1481-1489）搬过去，输入显式参数（`fdf, custom_thresholds, current_obs`），**不 import streamlit**；`nwp_forecast` 只保留取数与渲染，调 `forecast_analysis.analyze(fdf)`。
   - 同步修正 `_calc_life_indices` 的隐式依赖：`current_obs` 由调用方（渲染层）传入，函数不再读 `st.session_state`。
   预计新增 1 文件（约 600 行搬迁），改 `nwp_forecast.py` 约 80 行（删除 + 接线）。

d) **对抗性审查——保留现状的理由**：nwp 的分析与渲染共享大量中间变量（`dmax_t`、`windy`、`precip_cats`），拆分需要设计一个 20+ 字段的返回结构，短期风险（改出 bug）大于收益（可测试性）。**因此切口要选"整块搬迁 + 零逻辑改动"**：搬过去后先保证输出 dict 完全一致（用现有 `test_aqi` 之外新增对 `_analyze_forecast` 的黄金样本测试），再谈优化。如果预报功能进入冻结期，可以只在新增功能时不再往 nwp 里加代码，而不是主动搬迁。

---

### S1-9 测试锁的是源码字符串与私有符号；CI 门禁只跑 11 个文件，集成测试不拦

**证据**

```python
# tests/test_chart_reader.py:367-370（按源码文本切片断言）
    source = _source("app.py")
    start = source.index('if st.session_state["active_tab"] == 3:')
    end = source.index("# ---- Tab 4", start)
    block = source[start:end]
```

```python
# tests/test_aqi.py:278-282（测试明确要求保留重复常量）
    """_AQ_LEVELS 是图表色带的数据源，必须保留。"""
    assert hasattr(nwp_forecast, "_AQ_LEVELS")
    assert len(nwp_forecast._AQ_LEVELS) == 6
```

```yaml
# .github/workflows/tests.yml:61-64（全量 pytest 不阻断）
      # 其余 pytest 用例（含天气墙）作为补充信号，失败不阻断门禁
      - name: pytest 全量收集
        continue-on-error: true
```

- 44 处 `_source/_read/read_text` 引用（含 4 个辅助定义，实际读取源码 40 处）；`test_chart_reader.py` 至少 5 处按"代码必须长这样"断言（:349-357、:367-370、:397-406、:421-423）；`test_manual.py` 有 `test_app_wires_manual_entry_and_interception`、`test_app_manual_entry_is_in_sidebar_block` 等依赖 app.py 结构的断言。
- 测试读私有符号：`test_aqi.py:225/244`（`_AQ_LEVELS`、`_compute_cn_aqi`）、`test_era5_guide.py:273`（`_HELP_GET_DATA`）、`test_weather_wall.py:50`（`_clean_city_name`）。
- 13 个测试文件各自带 ~15 行 `__main__` 直跑样板（合计约 200 行重复）；`test_analyzer.py:77` 明确"不使用 pytest fixture / 参数化 / monkeypatch"，导致 1,134 行手写辅助。README 却写"其中十一个可直接运行"（README.md:142），实际 13 个——文档计数本身也已漂移。
- CI 门禁显式列出 11 个文件；`test_weather_wall.py`（41 条，AppTest 驱动完整 `app.py`）、`test_ai_narrative.py`（27）、`test_era5_script_pack.py`（29）、`test_smoke.py`（2 条，AppTest 启动 `app.py`）不在门禁内，只在 `continue-on-error` 的 pytest 里跑。`test_auth_session.py` 虽然也用 `AppTest.from_function`，但已在门禁内——说明团队区分了"片段级 AppTest（稳定，可门禁）"与"整应用 AppTest（不稳，仅参考）"，而恰恰是后者覆盖 `_safe_reset`/跨 Tab 路径。
- 存在"为防漂移而锁字面量"的测试：`test_release_surface.py:29-31`（`APP_VERSION == "2.3.8"`）、`:49-64`（README 的逐文件用例条数必须等于实际 `def test_` 个数）。这两类测试让"发布"和"加/删测试"都必须先改测试文件。

a) **根因**：这套测试是从"文档/实现说谎"的历史事故里长出来的——`test_chart_reader.py:398-406` 断言"不能出现 check_against_extremes / HJ 633-2026"、`test_release_surface.py:138-179` 断言"用户可见文案不得声称标准年份"，这些曾经真的抓到问题（`内部不一致清单` 第 1/3/4/5 项）。团队因此把"grep 源码"当成通用回归手段，越用越顺手；没有区分"用户可见文案契约"（该保留）与"代码结构位置契约"（会挡重构）。

b) **不修的长期代价**：任何一次结构调整（拆分 nwp、改 Tab dispatch、把 `_analyze_forecast` 搬走、把 `active_tab` 换成枚举）都要先改一批测试，重构成本从"改代码"变成"改代码 + 改测试 + 说服自己测试没变弱"；更糟的是**真正的集成路径不在门禁**——天气墙的 AppTest 和全量 pytest 都是"参考信号"，一次真实回归（例如 `_safe_reset` 破坏登录态）不会被 CI 拦住。

c) **最小修复切口**（与第 0/5 批并行，1~2 天可起步）：
   - 新建 `tests/support/`：把 13 份 `__main__` 样板收成 1 个 `run_standalone(tests)`，把 AppTest 构造收成 `make_app(...)`（现在在 `test_weather_wall.py:376-408` 里）；
   - 把 `test_chart_reader.py` 的 5 处"源码切片"改为 AppTest 行为断言（`at.run()` 后断言 Tab 内容/按钮存在），保留 `test_release_surface` 的"用户可见文案"类断言；
   - CI 里把 `pytest tests -q` 从 `continue-on-error` 改为阻断（或至少把 `test_weather_wall.py` 的 3 条冒烟单独提出来阻断）。
   预计改 `tests/` 下 6~8 个文件、`.github/workflows/tests.yml` 1 个文件，不动应用代码。

d) **对抗性审查——保留现状的理由**：源码断言确实抓到过"页面说谎"（HJ 633-2026 案例），全部删除会失去文档一致性保护；`continue-on-error` 是有意的策略——AppTest 在 CI 的 headless 环境下可能因 Streamlit 内部时序不稳定，设为硬门禁会造成假红。**合理边界**：只把"用户可见文案/标准标注/版本号"留在源码断言，把"某一行必须在某个位置"全部换掉；AppTest 冒烟先跑 3 条稳定的（封面占位、导入后摘要卡、Tab 可切换），不稳定再退回非阻断。这不是"测试写得不好"，是"测试的失败模式已经和重构目标对齐错了"。

---

## 五、S2 清单（局部但会扩散）

> 格式压缩：每条给证据、根因、代价、切口、保留理由各一句，避免与 S1 重复展开。

### S2-1 配置真相源混装：`config.py` 786 行里 8 类内容，且含 3 个死常量

- **证据**：`FIELD_ALIASES`（:9，172 行数据映射）、`FIELD_RANGES`（:190，校验规则）、7 张预警阈值（:212-311，业务规则）、`BEAUFORT_SCALE`（:316，标准数据）、`PUBLIC_ADVICE/AGRI_ADVICE`（:392-468，内容文案）、`LIFE_INDEX_META`（:475，UI 元数据）、`COLORS`（:495，设计）、`AQI_*`（:534-593，标准）、`WMO_WEATHER_CODES`（:665，死）、`ONBOARDING_STEPS`（:638，死）、`ERROR_TRANSLATIONS`（:773，死）、`safe_chart`（:707，渲染）。`grep` 三个死常量各只命中定义行。
- **根因**：`config` 是历史目录，任何人加常量都放这里，没有"domain data / framework config / content"的划分。
- **代价**：找"某常量在哪"要先扫 786 行；删除某个功能时不知道哪些常量为它服务；新人会继续往里加。
- **切口**：按 S1-2/S1-3 的批次逐步搬出（`content.py`/`standards.py`/`theme`），不一次性重构；先删 3 个死常量（各 1 行）。
- **保留理由**：如果团队只有 1~2 人且 config 的查找成本可接受，混装不会直接导致 bug；真正的风险是"往里面加第二份语义"，那由 S1-2 解决。

### S2-2 缓存有四套机制、键格式与 SQL 正则靠注释绑定

- **证据**：① `st.cache_data` 10 处（geocode 3、nwp 1、weather_wall 2、auth 1、db 3）；② session_state 动态键（`gfs_fc_cache_*` nwp:205/208/214/257、`aq_cache_*` nwp:357-358/423、`_api_cache_*` utils:81/126、`_template_cache` data_loader:831-834、`_wall_fallback` weather_wall:171/244）；③ Supabase `gfs_cache` 表；④ `retry_with_backoff` 在成功/失败时自行写缓存（utils.py:80-82/126-131）。GFS 键格式与 `sql/schema.sql` 的正则绑定，docstring 明写"改动键格式时必须同步改 SQL，否则缓存写入会被服务端拒绝"（nwp:102-104）。
- **根因**：缓存是逐功能加的，没有"缓存策略"层；写缓存最简单的方式就是往 session_state 塞一个键。
- **代价**：修改键格式需要同时改 Python + SQL + 测试（test_supabase_backend 里还有静态契约）；session_state 动态键无上限增长，一个会话多换几次坐标就会积累几十个 `aq_cache_*`/`gfs_fc_cache_*`，且 `_safe_reset`/`_reset_current_tab` 都不清（S1-4）。
- **切口**：短期只在 `_reset_current_tab` 里加前缀清理（`gfs_fc_cache_`、`aq_cache_`、`_api_cache_`）；中期把 GFS 键格式的"正则契约"提成一份共享常量（Python + SQL 生成），让 test 断言两边同源。
- **保留理由**：多层缓存在 Streamlit Cloud 的免费额度下是**必要设计**（跨用户共享 GFS 结果），不能砍；且 Supabase 侧细节归 C 号审计（`research/supabase-体检-2026-10-18.md` 已覆盖 S2/S3），本报告只指出"键格式契约靠注释"这一结构问题。

### S2-3 导航栈三处实现、app 内 9 处函数内 import、1 个死导入

- **证据**：`app._navigate_to:145-156`；`utils.go_back:140-149` + `render_back_button:151-156`（后者 0 引用）；`visualizer.py:784-788` 自己 pop 栈；`app.py:40` `from utils import ... go_back as _go_back` 后全文未用。`app.py` 内函数级 import：:52、:136、:252、:447、:478、:497、:506、:527、:636。
- **根因**：导航最初只有 app.py 一个入口，模块化后各模块为了"返回上一页"就地实现；惰性 import 是复制粘贴的遗留。
- **代价**：`_nav_stack` 的语义（深度上限 10、是否清空）分散在多处；改导航模型要改 3 个文件；`_go_back` 死导入让读者误以为有统一入口。
- **切口**：把 `_navigate_to/go_back` 收进 `utils`（或 `app_state`），visualizer 改调公共函数；删除死导入与 `render_back_button`。
- **保留理由**：如果产品确定"返回按钮只在可视化空态用一次"，就地实现也无害；真正的问题是 `_go_back` 死导入与三处 `active_tab` 赋值可能不同步（例如 visualizer 的 pop 不检查栈深）。

### S2-4 预报 Tab 每次 rerun 重算分析与生活指数；生活指数读 widget 键而非传入数据

- **证据**：`nwp_forecast.py:1867`（每次 rerun 调 `fetch_air_quality`，内部走 session 缓存）、`:1920-1926`（每次 rerun 重算 `_analyze_forecast` 与 `_calc_life_indices` 并写 session_state）、`:1498-1502`（读 `fc_lat/fc_lon/fc_model`）。
- **根因**：渲染函数即计算入口；没有"数据版本 → 派生结果"的缓存键。
- **代价**：任何控件交互（拖滑块、切报告风格）都触发 292 行分析 + 一次实时 API 调用；改坐标不重取也能算出"新坐标的生活指数"，是错误结果而非性能问题。
- **切口**：给 `fc_analysis`/`life_indices` 加 `(df_fingerprint, lat, lon, model)` 缓存键；`_calc_life_indices(fdf, current_obs)` 显式传参（与 S1-8 的搬迁合并做）。
- **保留理由**：分析耗时在毫秒级（纯 pandas），当前 Tab 交互频率不高；但"坐标和数据不一致"是正确性问题，必须修。

### S2-5 Tab 序号与名称两套映射，索引硬编码散落

- **证据**：`_TAB_NAMES:100`（`["导入","可视化","数值预报","读图解析","报告导出","报文解码"]`）与 `tab_labels:671-678`（带 `[导入]` 等前缀）是两份；索引硬编码：`:237-244`（1/3/4）、`:384`（0）、`:704/885/890/913/924/928`（0/1/3/4/5/2），注释 `:236`、`:815` 解释"可视化已互换至 index 1"；`config.ONBOARDING_STEPS:638-660` 还保存了第三份 `tab_idx`（死代码）。
- **根因**：Tab 顺序改过一次（可视化与预报互换），当时用"改数字 + 加注释"完成。
- **代价**：再加一个 Tab 或在中间插入，所有硬编码序号与 `_RESET_KEYS_BY_TAB` 的键名都要人工同步；`_TAB_NAMES` 与 `tab_labels` 已经不同步（后者带装饰前缀），靠"名字用于查表、标签用于显示"的默契维持。
- **切口**：定义 `TAB_IDS = ("import","viz","nwp","reader","export","codec")` + 标签表，dispatch 改 `match`；`_RESET_KEYS_BY_TAB` 用 id 做键。
- **保留理由**：6 个 Tab 的固定顺序是产品现状，短期不改；但一旦要加"气候统计/中长期"这类 Tab（README 已在讨论能力扩展），当前结构必改。

### S2-6 主题层：每次 rerun 重注入 ~40KB CSS；249 个 `data-testid` 与 Streamlit 版本绑定；`chart_theme` 导入即注册；手册导出 HTML 自带第二套配色

- **证据**：`theme_css.py` 834 行、199 个选择器块、249 处 `data-testid`；`theme_aether.inject_theme:215-241` 在每次 rerun 用 `st.markdown(<style>…)` 重发整段；`chart_theme.py:108` 模块级 `register()`；`manual.py:29-67` 导出 HTML 的 15 个 hex 色（`#1f6feb/#123a6b/...`）独立于 token。
- **根因**：Streamlit 没有"按会话换主题"的官方能力，只能 CSS 覆盖；CSS 覆盖又只能跟随 DOM 变化，于是选择"每次全量重发"保证正确性（代码注释已说明这是为了对抗回弹）。
- **代价**：每次交互多传 ~40KB + 一个 script 标签；Streamlit 升级时 249 个 testid 可能静默失效（requirements 钉死 1.59.1，升级成为高风险动作）；手册导出件与站内主题不一致，用户截图/打印时观感不同。
- **切口**：把 CSS 从 Python 字符串移到 `modules/theme.css` 文件（`importlib.resources` 读取），至少让 CSS 可被编辑器/lint 处理；`data-testid` 加"选择器清单"测试（升级时跑，报告哪些选择器在当前版本不存在）；手册导出的 CSS 复用 token 的静态快照。
- **保留理由**：CSS 内联进 Python 是"单文件部署"的合理取舍（Streamlit Cloud 不保证能带静态资源目录，但仓库里其实可以）；如果近期不升级 Streamlit、也不改手册视觉，这三条只是维护成本而非故障源。

### S2-7 数据质量阈值两份，且"突跳阈值"不在 config

- **证据**：`app.py:788-800`（Step 2 的疑似异常值：温度 `>55 或 <-50`、湿度 `<0 或 >100`）与 `data_quality.range_check:19-44`（读 `config.FIELD_RANGES`）重复；`data_quality.temporal_consistency_check:68-73` 写死 `8.0/10.0/30.0`（温度/气压/湿度 1h 突跳），config 里没有这组阈值。
- **根因**：Step 2 的指标是"给用户看三个数"，直接写了简单判断；质控页是后来补齐的。
- **代价**：两处对"异常值"的定义不同（Step 2 只看温度和湿度，质控页看全部 14 个字段），用户看到两个不一致的计数；突跳阈值无法通过侧边栏/配置调整。
- **切口**：Step 2 改为调用 `data_quality.range_check` 的计数结果；把 8/10/30 提进 `FIELD_SPIKE_RULES`。
- **保留理由**：Step 2 是"预览"，指标口径粗一点可接受；但两处同时显示"异常值"数量时，用户会困惑，至少应统一口径或标注差异。

### S2-8 生活指数 `score` 语义不统一，报告表格把它们放进同一列

- **证据**：`nwp_forecast.py:1541-1551`（穿衣：5=最冷，0=最热）vs `:1586-1593`（运动：100=最适宜）vs `:1564-1575`（舒适度：SSD 数值 15-19 舒适）vs `:1599`（紫外线：4="很强"）；`reporter.py:725-743` 在同一张表里把四类 `score` 都渲染到"评分"列（`score_text` 只做 int/float 区分）。
- **根因**：7 项指数分批实现，每项自己定义分制；`LIFE_INDEX_META` 只存图标和名字，没有分制元数据。
- **代价**：报告里"穿衣 3 / 运动 78 / 舒适 26 / 紫外线 4"并列，读者无法比较；如果未来统一分制，消费端（nwp 卡片、reporter 表格、手册）要一起改。
- **切口**：给每项指数加 `score_kind`（`level|percent|index`）或统一成 0-100 的"适宜度"（同时保留原值），reporter 按 kind 渲染或在表头注明。
- **保留理由**：各指数的原始分制在气象业务上是"原样呈现"（SSD 就是 15-19 舒适），强行归一会损失信息；可行的折中是"不改算法，只在报告表头/列名上标明分制"，让读者不误读。

### S2-9 ERA5：catalogue 在 UI 模块、真相源在 research 快照、单位换算在生成脚本里再实现一遍

- **证据**：`era5_guide.py:28-260`（4 产品 catalogue 数据）；`era5_guide.py:16-23` 的 `SCALES` 只是"人类可读说明"（用于 UI 提示，`:460-461`）；真正的换算实现在 `era5_script_pack._SCRIPT_TEMPLATE`（`:133` `v-273.15`、`:138` `v*1000.0`、`:153` `v/9.80665`、`:184-229` `SCALE_BY_VARIABLE` + 分支）；测试对 catalogue 与 `research/era5_variable_enums_2026-09-13.json` 快照做一致性断言（`test_era5_guide.py:18/257-300`）。
- **根因**：交付物是"给用户的脚本包"，脚本必须自包含；catalogue 的真相源又是外部快照（CDS constraints 实测），三者无法直接共享代码。
- **代价**：改一个变量的换算（例如新增 FRAC2PCT）要同时改 catalogue 的 `scale` 字段与脚本模板的分支，漏一处就是"生成的脚本算错单位"；快照 JSON 与线上 CDS 会继续漂移（计划文档已记录一次实测修正）。
- **切口**：把 `SCALE_BY_VARIABLE` 与 `SCALES` 的映射键统一成同一份常量（`era5_units.py`），脚本模板从该常量生成分支；`test_era5_script_pack` 增加"每个 SCALES 键都有脚本分支"的断言。
- **保留理由**：脚本包是"离线交付物"，自包含是硬要求；如果 ERA5 变量集冻结（计划已完成一次全量核对），漂移风险低。真正要防的是"新增变量时两边不同步"。

### S2-10 死代码与死状态键：功能已删，入口还在

- **证据**（`grep` 计数等于定义行数，即 0 引用）：`app._render_progress_bar:265`、`utils.tab_fingerprint_match:56`、`utils.render_back_button:151`、`app` 的 `_go_back` 导入、`config.ONBOARDING_STEPS:638`、`config.WMO_WEATHER_CODES:665`、`config.ERROR_TRANSLATIONS:773`；死状态键：`nwp_combined`（只在 `app.py:110` 重置清单里）、`nwp_air_quality_for_analysis`（只在 nwp:1870/1874 写入，无读者，也不在重置清单）；`analyzer.py:10-11` 自述 `multi_factor_coupling`/`generate_advice` 无生产调用者，仅由测试覆盖。
- **根因**：功能迭代时"先留着以后可能用"，没有删除纪律；测试的存在让"无生产调用者"看起来像"公共 API"。
- **代价**：读者要花时间判断哪些是活的；死键会误导后续维护（`nwp_combined` 被当作"需要清理的键"，实际从来没写过）；死表 `WMO_WEATHER_CODES` 会诱导新人以为它是真相源。
- **切口**：一次性删除（7 个符号 + 2 个死键），`multi_factor_coupling/generate_advice` 二选一（要么接入，要么删测试）。
- **保留理由**：`multi_factor_coupling` 在 `tests/test_analyzer.py` 里有大量测试（全仓 45 处引用，绝大多数在测试），删除会减少覆盖面；如果产品计划恢复"耦合分析"面板，保留可接受——但应在 README 标注"未接线"。

### S2-11 data_loader 的职责边界：解析函数写 session_state，render 函数返回三种形态

- **证据**：`parse_timestamp:111/349` 写 `st.session_state["_date_is_synthetic"]`；`_show_time_report:386-413` 渲染 UI；`render_file_upload_section` 返回 `(df, source)`，`render_manual_input_section` 返回 `DataFrame | None`（:535），`render_api_section` 返回 `(df, source)` 且中途写 6 个 `api_*` 状态键（:671-818）；`_merge_weather_pollution:646-659` 在纯合并函数里 `st.warning`。
- **根因**：导入流程需要一个"向导"，向导的状态与解析结果混在同一个模块里；`render_*` 命名掩盖了"它同时是数据源"。
- **代价**：想复用 `parse_timestamp`（例如在 GFS 数据上）会连带写 UI 状态；测试 `data_loader` 需要 Streamlit 运行时（当前没有 test_data_loader.py）；`api_df` 与 `app.df` 双通道（`api_df` 只在 data_loader 内部中转），多一处可能不一致的状态。
- **切口**：把纯函数（`load_csv/load_excel/normalize_columns/parse_timestamp`）的 session 写入改为返回值（`(df, report)`），由 `app.py` 写状态；`_date_is_synthetic` 作为 report 字段返回。
- **保留理由**：Streamlit 的惯用写法就是"解析时就地提示"，改成返回值会多一层传参；如果导入流程近期不变、也不复用解析函数，当前写法能工作。但 GFS/ERA5 数据接入已经在复用 `normalize_columns/parse_timestamp`（nwp:1761-1762），跨模块副作用已经发生。

### S2-12 用户手册与 README 的升级指令/计数已漂移

- **证据**：`docs/用户使用手册.md:113` 写"重跑一次 `supabase/schema.sql`"，全仓其余 20+ 处（`README.md:259`、`SECURITY.md:16`、`auth.py:568/580/588/866` 等）都是 `sql/schema.sql`；仓库只有 `sql/schema.sql`（42KB，4 张表 + 8 个函数）。另：`README.md:142` 称"其中十一个可直接运行"，实际 13 个测试文件带 `__main__`。
- **根因**：早期目录可能叫过 `supabase/`，改名后手册正文漏改（手册是"唯一真相源"，由 `modules/manual.py` 运行时读取）；README 的计数是手写的，加测试时未同步。
- **代价**：用户按升级提示找不到文件，直接卡在 2.3.7→2.3.8 的升级路径上；计数漂移让"文档说 11、实际 13"这类小谎累积，削弱 README 作为事实来源的可信度。这类"文档路径/计数错"不会被任何测试发现（现有测试只锁手册章节结构与少数关键词）。
- **切口**：改 2 行；在 `test_manual.py` 增加"手册中的 `*.sql` 路径必须存在"的断言，在 `test_release_surface.py` 增加"README 的 `可直接运行` 计数 = 实际 `__main__` 文件数"的断言（两条通用保护，不只这一处）。
- **保留理由**：无。这是纯错误，只是影响面小，所以放 S2 而非 S1。

---

## 六、Streamlit 重跑模型专项观察（任务第 10 项）

Streamlit 的"整脚本重跑 + session_state 持久化 + widget 状态隐式同步"是上述结构问题的放大器。集中列出交互点，便于批次设计时一起考虑：

1. **重跑即重建**：`app.py` 每个交互重跑 929 行，其中包含登录门禁、`init_theme`、~40KB CSS 注入、`_render_data_summary_card`（含 `_df_fingerprint`）、封面天气墙（`render_wall`）、6 个 Tab 的 dispatch。缓存只覆盖了 API（`st.cache_data` 10 处），**派生分析（warnings/quality/analysis）没有统一缓存**，所以 S1-5 的"渲染顺序依赖"在每次 rerun 都在被重新确认。
2. **状态写入与 widget 实例化顺序**：`_safe_reset` 在 Tab 渲染中途删除已实例化的 widget key（S1-4）；`visualizer`/`weather_wall` 用 `on_click` 回调写 widget key（weather_wall:588/600/614）是正确的，但同一模式在 `_safe_reset` 里被破坏。**推断**：在 Streamlit 1.59 下删除已实例化 widget key 是否抛异常需运行时确认（见文末复现清单），但"不 rerun 就继续渲染"本身已让状态处于半提交态。
3. **`st.rerun` 密集**：52 处，主要集中在 app（23）、auth（11）、data_loader（8）。`_navigate_to`、`_reset_current_tab`、`set_theme` 都是"写状态 + rerun"；`_safe_reset` 是唯一"写状态不 rerun"的恢复路径，不一致。
4. **模块全局 vs 会话**：`analyzer.CUSTOM_THRESHOLDS`（analyzer.py:25-30）是模块级可变全局，被 `app.py:599-601` 的按钮写入。Streamlit Cloud 单进程多会话，**推断：用户 A 的自定义阈值会影响同一进程内用户 B**，且登出/新会话不会复位。这是 S1-1 之外独立的一条：`set_custom_thresholds` 应该写 session_state（或进程级只读配置），而不是模块全局。复现：两个浏览器会话，A 改高温黄色为 30℃ 并应用，B（新会话）在观测数据上检测高温，会看到 30℃ 就报黄。
5. **本地文件是"跨会话通道"**：`theme_aether._PREF_FILE = Path.home()/".aether_theme.json"`（:57）、`city_prefs._PREF_FILE = Path.home()/".weather_wall_cities.json"`（:20）。在 Streamlit Cloud 的单容器里 `$HOME` 是所有会话共享的：`init_theme()` 在登录门禁之前读它（app.py:48），**推断：用户 A 的暗色偏好会成为用户 B 的初始主题**；`city_prefs` 的读-改-写（`save_cities:116-120` 先 `_load_local` 再写）在多会话并发下是 last-write-wins。登录后云端值会覆盖本地（auth.py:267-280），所以影响主要是"首屏偏好泄漏"与并发写，不是数据泄漏；但城市列表若未来改成未登录可用，就是跨用户数据泄漏。
6. **缓存装饰器的 key 是参数值**：`db.get_storage_usage_bytes(uid)` 用 uid 做 key（30s TTL），隔离正确；`utils.retry_with_backoff` 却把缓存写进 `session_state["_api_cache_<func>"]`（utils.py:81-82/126-131），意味着同一个函数在不同会话各自缓存、永不清理，且"失败时回退上次缓存"的语义只在本会话有效。缓存策略应在 `app_state` 层统一声明，而不是由装饰器顺手写 session。

> 结论：重跑模型本身不是问题，问题是**没有"状态层"来承接重跑**。批次 1（app_state）就是为这一条设计的；如果只做一件事，它应该和批次 0 一起先落地。

---

## 七、重构阻力清单（动之前必须知道的成本）

### R-1 测试层：源码断言与私有符号

- 44 处读源码（含 4 个辅助定义）、至少 5 处按代码位置切片（`test_chart_reader.py:367-370`）、私有符号 import（`_AQ_LEVELS`、`_compute_cn_aqi`、`_HELP_GET_DATA`、`_clean_city_name`）、`APP_VERSION` 与 README 计数锁（`test_release_surface.py:29-31/49-64`）。
- **阻力表现**：拆 `nwp_forecast`、改 Tab dispatch、把 `_analyze_forecast` 搬走、把 `_AQ_LEVELS` 合并进 `config.AQI_LEVELS`，都会先让 3~10 条测试变红，且变红的原因不是行为变了。
- **缓解**：批次 5 把"结构位置断言"改行为断言；迁移期允许测试与代码同 PR 修改，但禁止降低行为覆盖。

### R-2 文档层：手册是运行时加载的真相源，且被 25 条内容契约测试锁着

- `modules/manual.py:21-24` 运行时读 `docs/用户使用手册.md`；`test_manual.py` 25 条断言章节数（14）、章节标题、每章 ≥300 字、无占位符、无失效 Tab 引用等。
- **阻力表现**：任何用户可见的 UI 文案/流程改动（例如 S1-5 的筛选范围说明、S2-7 的异常值口径、阈值改动）都要同步手册，否则测试红或文档说谎；手册第 12 章还逐条描述侧边栏阈值（对应 app.py:541-597），S1-1 的改动必须同步这里。
- **缓解**：把"手册 → 代码"的引用关系在手册里写清（已有部分）；批次 0 先修 S2-12 的路径错，并补一条"手册中的文件路径必须存在"的通用测试。

### R-3 计划文档层：六份计划已覆盖大量内容，避免把"已解决"当新发现

- 2026-09-13 五份分别覆盖 AQI 口径统一、ERA5 交付、手册、读图转型、横切收尾；2026-10-18 覆盖 Supabase 加固（S1-S17）。`内部不一致清单` 8 条已处置 7 条。
- **阻力表现**：做 S1-2（AQI 等级）、S2-9（ERA5 换算）时容易与计划的"完成标准"冲突（例如计划 Task 4 要求"nwp 不再持有断点表"已经做完，但等级区间仍留了一份）；新报告若重复这些会被视为噪音。
- **缓解**：本报告已把交叉项标为"残留"而非"新发现"（见 S1-2 矩阵的漂移列）。

### R-4 CI 层：门禁不等于全量测试，静态检查工具不在门禁

- 门禁只跑 11 个文件（`tests.yml:28-58`）；`pytest tests -q` 是 `continue-on-error`（:61-64）；`research/` 下的 5 个静态检查脚本（`check_py_vars.py`、`check_plotly_cssvar.py`、`check_chart_colors.py` 等）没有任何 CI 步骤。
- **阻力表现**：结构改造期间"本地绿、CI 绿、线上坏"的概率上升；S1-2/S1-3 需要的"重复语义检查"没有落点。
- **缓解**：批次 5 把 2~3 个最稳的 research 脚本接进 CI（先非阻断，再阻断）。

### R-5 运行时层：单进程多会话、模块全局、本地文件共享

- `analyzer.CUSTOM_THRESHOLDS`（模块全局）、`$HOME` 下的偏好文件、`st.cache_data` 的进程级缓存。测试（AppTest）默认单会话，**覆盖不到多会话串扰**。
- **阻力表现**：任何"把状态从 session_state 提到模块级"的优化都会引入串号风险；反之，模块级状态是当前最难测的一类 bug。
- **缓解**：`app_state` 注册表里显式禁止模块级可变状态；对 `analyzer` 的自定义阈值加"会话隔离"回归测试（两会话交替）。

### R-6 依赖层：没有 lint/type 配置，`modules/` 无 `__all__`/公共 API 边界

- `requirements-dev.txt` 只有 `pytest>=8.0`；无 `pyproject.toml`/`ruff`/`mypy`；`modules/__init__.py` 为空（0 字节）。跨模块私有导入（`weather_wall` → `nwp._compute_cn_aqi`）没有任何机制拦截。
- **阻力表现**：重构时没有"哪些是公共 API"的机器可读定义，工具无法帮忙发现断链。
- **缓解**：最低成本方案——在 `modules/__init__.py` 声明公共符号 + 一个 AST 脚本禁止"跨模块导入以下划线开头的符号"（dry-run 起步）。

---

## 八、建议批次（按依赖顺序，每批带判定标准）

> 原则：先用最小改动止血，再建状态地基，然后按"语义"和"数据"两个维度收敛，最后切大模块。每批的判定标准是"可机器验证的完成条件"，不是"感觉改完了"。批 0/1 先做，批 2/3 可并行，批 4 依赖 1-3 全部完成，批 5 贯穿全程。

### 批次 0：止血（1~2 天，5 个文件以内，不改变架构）

内容：
1. `_safe_reset` 修复：keep 集合改为 `auth_scope()`，显式保留 `_sb_client`/`_sb_admin_client`（或在重置后强制 `sign_out_user` 回登录页，二选一，建议前者）；重置后置 `df=None` 并阻止本轮/下一轮 `_auto_load_done` 自动载入。
2. `analyzer.CUSTOM_THRESHOLDS` 从模块全局改为 session_state（`st.session_state["custom_thresholds"]`），`set_custom_thresholds` 写入 session；登出清空。
3. 统一等级字符串：nwp 的 `I/II/III/IV` 改为 config 的全角 `Ⅰ/Ⅱ/Ⅲ/Ⅳ`（或反向统一，选一个）。
4. 修 `docs/用户使用手册.md:113` 的 `supabase/schema.sql` → `sql/schema.sql`。
5. 删除 7 个死符号 + 2 个死键（S2-10）。

**判定标准**：① 10 个可直跑的 `python -B tests/<file>.py` 与 `pytest tests` 全绿（现有 412 条）；新增 4 条回归测试——① `_safe_reset` 后 `_sb_client` 仍在；② 两会话自定义阈值互不影响；③ 重置后不自动载入云端数据；④ 手册中的 `.sql` 路径存在。全仓 `grep` 无 `supabase/schema.sql`、无 `nwp_combined`。

### 批次 1：状态地基（3~5 天；依赖批 0）

内容：
1. 新增 `modules/app_state.py`：`STATE_DEFAULTS` + `SCOPE` 注册表，提供 `reset_data()/reset_tab(tab_id)/auth_scope()`；
2. `app.py` 的三处清单（`_safe_reset`、`_RESET_KEYS_BY_TAB`、`init_session`）改由注册表派生；
3. `_ensure_derived()`：dispatch 前统一算 `warnings_list`/`quality_score`（用 `df_fingerprint` 做缓存键），Tab 3/4 只读；
4. 派生数据加"本次渲染不完整"标记，`_tab_error` 显示；`_error_log` 环形缓冲（S1-7）。

**判定标准**：① 一个脚本能打印出"所有被写入的 session key"并与注册表差集为空（AST + 运行时自检）；② `warnings_list` 在"导入→直接导出"路径下非空（新增 AppTest 用例）；③ `python -B tests/test_release_surface.py` 与全量 pytest 绿；④ `_TAB_NAMES`/`tab_labels` 合并为一份，`grep active_tab.*==\s*[0-9]` 只剩 1 处（枚举映射）。

### 批次 2：数据契约（5~7 天；可与批 3 并行）

内容：
1. 新增 `modules/schema.py`：`STANDARD_FIELDS` + `DTYPES` + `UNITS` + `validate(df)->(df, issues)` + `standardize_air_quality(df)`；
2. 四个入口接线：文件上传、API、`db.load_dataset`、nwp 的 fetch 返回处；
3. 污染物列名归一（`pm2_5→pm25`、`no2→nox`；`co/o3` 显式声明为 `AQ_ONLY_FIELDS`，不混入 `STANDARD_FIELDS`）；
4. `db.save_dataset` 增加 schema 版本（或 `load_dataset` 强制 validate 并提示缺失列）。

**判定标准**：① 新增一个数据源只需实现一个 adapter（用一个假 adapter 的测试证明）；② `pm2_5/pm25` 两条链的数据经过同一 `validate` 后列名一致；③ 云端旧数据集载入时若缺列，UI 给出"缺 X 列，以下分析不可用"而不是静默；④ 现有 412 条测试绿，新增 ≥10 条 schema 测试。

### 批次 3：语义收敛（按语义逐项，2~3 天/项；可与批 2 并行）

优先级与判定：
1. **WMO 码**：新建 `modules/weather_code.py`，删除 `config.WMO_WEATHER_CODES` 或使其成为唯一数据源；判定：`grep -c "range(50, 70)\|range(80, 87)\|range(0, 20)"` 等天气码区间只剩 weather_code.py 一处。
2. **热指数**：只保留一个公式；判定：`grep "def heat_index"` 计数 = 1，两处调用方共用。
3. **预警阈值/等级**：`modules/warn_rules.py`（S1-1）；判定：`grep ">= 10.8\|>= 17.2\|>= 24.5"` 只命中 config/warn_rules；nwp 的 `_analyze_forecast` 无硬编码阈值；侧边栏默认值来自 config（grep 不到数字字面量）。
4. **配色**：`config.COLORS` 派生化（S1-3）；判定：`config.py` 中 `#rrggbb` 计数 ≤ 5（仅保留确实无法 token 化的色）。
每项完成时把对应"重复实现"测试从"锁两份"改为"锁一份 + 断言唯一性"。

### 批次 4：大模块切片（1~2 周；依赖批 1、2、3）

内容（按收益排序）：
1. `nwp_forecast` → `modules/forecast_analysis.py`（`_analyze_forecast`/`heat_index`/`_calc_life_indices`/`_calc_ssd`，不 import streamlit；`current_obs` 显式传入）；nwp 只留取数/缓存/图表/渲染。
2. `weather_wall` → `city_data.py`（CITY_LIBRARY + 场景映射）+ 渲染层；`wall_css` 移到模块级字符串或 `.css` 资源。
3. `theme_css` 的 CSS 外置为 `modules/theme.css`（由 `importlib.resources` 读取），Python 只保留变量块生成。
4. `reporter` 的纯排版与业务文案分离（可选，收益较低）。

**判定标准**：① `nwp_forecast.py` < 1,200 行且 `forecast_analysis.py` 有独立测试（≥15 条，覆盖高温/暴雨/大风/生活指数）；② `weather_wall` 的 `st.*` 与 `requests` 不出现在 `city_data.py`；③ `theme_css.py` 行数 < 300，CSS 文件可被 lint；④ 全量 pytest + 门禁绿，且应用代码的改动**没有引起测试文件中"结构位置断言"的修改**（用 git diff 统计 tests/ 改动行数证明）。

### 批次 5：测试与 CI 治理（与批 0 并行起步，持续）

内容：
1. `tests/support/`：统一 `__main__` 样板、AppTest 构造、临时偏好文件；
2. `test_chart_reader` 的 5 处源码切片改行为断言；保留"用户可见文案"类源码断言（HJ 633/GB 3095、版本号）；
3. CI：AppTest 冒烟 3 条进阻断门禁；`research/check_py_vars.py` 等 2 个静态检查进 CI（先非阻断）；
4. 最小 lint：ruff 规则先只开 `F401`（未用导入，可立即抓出 `_go_back` 一类）与 `F841`。

**判定标准**：① 新增测试无需手写 `__main__`；② CI 失败能在本地一条命令复现；③ 批次 3/4 的每个 PR 中 tests/ 的改动只包含"新增行为断言"，不包含"修改结构断言"。

### 批次依赖图

```
批 0（止血）──► 批 1（状态地基）──► 批 4（大模块切片）
                    │                    ▲
                    ├── 批 2（数据契约）──┘
                    └── 批 3（语义收敛）──┘
批 5（测试治理）贯穿 0→4，与批 0 同起步
```

**互斥写域提示**：批 0/1 集中在 `app.py`/`auth.py`/`analyzer.py`；批 2 在 `modules/data_loader.py`/`db.py`/新 `schema.py`；批 3 在 `config.py`/`nwp_forecast.py`/新 `weather_code.py`/`warn_rules.py`；批 4 在 `nwp_forecast.py`/`weather_wall.py`/`theme_css.py`。**批 3 与批 4 都改 nwp_forecast，必须串行**（先批 3 收敛语义，再批 4 搬迁，否则搬迁会把重复实现一起搬走）。

---

## 九、与既有计划/已修项的边界（避免把已规划事项当新发现）

| 既有事项 | 来源 | 本报告如何处理 |
|---|---|---|
| AQI 口径统一（断点表单一真相源、nwp 不再持有断点表） | 2026-09-13-01 | 视为已完成；只记录**残留**：`_AQ_LEVELS` 等级区间与 `config.AQI_LEVELS` 仍双份、末档 99999 vs 500（S1-2 矩阵） |
| ERA5 catalogue 修正与脚本包 | 2026-09-13-02 | 视为已完成；只记录**结构残留**：catalogue/SCALES/脚本模板三处（S2-9） |
| 用户手册体系化 + 内容契约测试 | 2026-09-13-03 | 视为已完成；只记录**新发现**：手册 `supabase/schema.sql` 路径错（S2-12） |
| AI 读图转型、配额、用量记账 | 2026-09-13-04 | 视为已完成；只记录结构观察（chart_reader 分层可作样板，S1-8 反证） |
| 横切收尾（版本、依赖、Secrets、CI、标准标注） | 2026-09-13-05 | 视为已完成；CI 门禁/源码断言作为**重构阻力**（R-1/R-4）记录，不重复其结论 |
| Supabase 加固 S1-S17（RLS、service_role、GFS 缓存、配额 RPC） | 2026-10-18 + research/supabase-体检 | **不重复**，其细节归 C 号审计；本报告只记录"键格式与 SQL 正则靠注释绑定"这一代码层结构（S2-2） |
| 内部不一致清单 8 条（标准年份、WARN_RULES、算法说明、风玫瑰口径等） | research/内部不一致清单 | 7 条已处置、1 条有意保留；本报告不重开，只在 S1-2 引用其"风玫瑰两口径"作为"有意的差异"案例 |

---

## 十、任务十项覆盖索引

| 任务要求 | 本报告对应位置 |
|---|---|
| 1. 模块边界与职责漂移（IO/业务/渲染） | 依赖图、S1-6、S1-8、S2-11、数据画像（UI 调用表） |
| 2. 重复实现（阈值/AQI/主题色/列名/缓存/错误/DataFrame 校验） | S1-1、S1-2 矩阵、S1-3、S2-2、S2-7、S2-8 |
| 3. 上帝模块内部结构、能否拆纯逻辑层 | S1-8（含函数长度表与 `chart_reader`/`analyzer` 反证） |
| 4. 状态管理（键散布、生命周期、keep 集合、跨 Tab 契约） | S1-4、S1-5、S2-5、第六节 1-6 条 |
| 5. 数据流契约（列名/单位/索引、导入→分析→导出） | S1-6、S2-9、S2-11 |
| 6. 错误边界（`_safe_render`/`_tab_error`、可诊断性） | S1-7、S1-9（失败路径测试缺失） |
| 7. 配置与常量真相源 | S2-1、S1-1、S1-3、S2-10（死常量） |
| 8. 导入图、循环依赖、import 期副作用 | 依赖图 + import 期副作用表 + 懒加载环（config↔design_tokens、auth↔theme_aether、db→auth 反向） |
| 9. 测试结构（行为 vs 实现细节、重构阻力） | S1-9、R-1~R-4 |
| 10. Streamlit 重跑模型交互 | 第六节（含 `CUSTOM_THRESHOLDS` 全局与 `$HOME` 共享两条独立风险） |

---

## 十一、运行时复现确认清单（本审计环境无法执行，交给实现批次验证）

1. **`_safe_reset` 是否破坏登录客户端**：登录 → 在任一带数据 Tab 触发一个异常（或用 debug 开关制造）→ 点「重置会话并回到首页」→ 点「保存到云端」/打开「我的数据集」→ 观察是否报错、侧边栏存储用量是否变 0。预期：`_sb_client` 被删后新建的客户端无登录态，云端操作失效。
2. **`_safe_reset` 删除已实例化 widget key 是否抛 `StreamlitAPIException`**：同上路径，观察控制台。
3. **重置后自动载入是否复活数据**：登录且有云端数据集 → 触发 `_safe_reset` → 任意交互一次 → 观察 `df` 是否被重新载入。
4. **自定义阈值跨会话串扰**：两个浏览器会话（A/B），A 应用自定义高温阈值 → B 对新数据跑观测检测 → 看是否按 A 的阈值判定。
5. **暗色偏好跨用户泄漏**：A 切暗色并退出 → B 用新浏览器会话打开登录页 → 看首屏是否暗色（在 Streamlit Cloud 单容器、共享 `$HOME` 的部署上）。
6. **预报 Tab 坐标/数据错配**：在预报 Tab 改经纬度但不点获取 → 看生活指数是否按新坐标的实时值计算（函数读 `fc_lat/fc_lon`）。
7. **直接导出路径缺预警**：导入数据 → 不打开「读图解析」→ 直接到「报告导出」生成 Word → 检查"事件检测"章节是否为空。

---

## 十二、附录：重复实现与死代码的精确清单（供批次 3/0 直接引用）

**同一语义多实现（行号为定义处）**

| # | 语义 | 位置 |
|---|---|---|
| 1 | 暗色判断 | config.py:351 / design_tokens.py:369 / theme_aether.py:156 / chart_theme.py:142 |
| 2 | WMO 天气码 | config.py:665（死）/ nwp_forecast.py:634 / nwp_forecast.py:1554 / nwp_forecast.py:1595 / weather_wall.py:271 / codec.py:234 / analyzer.py:329 |
| 3 | AQI 等级区间 | config.py:562 / nwp_forecast.py:314（测试锁死两份） |
| 4 | AQI 等级→色 token | design_tokens.py:332 / nwp_forecast.py:314 第 4 元素 |
| 5 | 热指数 | analyzer.py:33 / nwp_forecast.py:557 |
| 6 | 风玫瑰 | visualizer.py:82 / nwp_forecast.py:790、819 |
| 7 | 蒲福分档 | config.py:316 / nwp_forecast.py:779 / visualizer.py:109 |
| 8 | 字段标签+单位 | config.py:338 / reporter.py:1206 / visualizer.py:867 / codec.py:322 / app.py:181 |
| 9 | 字段别名 | config.py:9（172 行）/ reporter.py:35 |
| 10 | 异常→中文 | config.py:748 / config.py:773（死） |
| 11 | 会话清理/keep | app.py:87 / app.py:103 / auth.py:183 |
| 12 | 导航栈 | app.py:145 / utils.py:140 / visualizer.py:784 |
| 13 | 阈值默认值 | config.py:212-311 / app.py:541-597 / nwp_forecast.py:960-1050 |
| 14 | 缓存 | st.cache_data×10 / session 动态键×6 类 / Supabase 表 / retry 装饰器 |
| 15 | DataFrame 校验 | data_quality.py:19 / app.py:788 / 38 处列守卫 / 12 处 to_numeric |

**死代码/死键（grep 计数 = 定义行数）**

`app._render_progress_bar:265`、`utils.tab_fingerprint_match:56`、`utils.render_back_button:151`、`app.py:40 _go_back`、`config.ONBOARDING_STEPS:638`、`config.WMO_WEATHER_CODES:665`、`config.ERROR_TRANSLATIONS:773`；状态键 `nwp_combined`（app.py:110 死引用）、`nwp_air_quality_for_analysis`（nwp:1870/1874 只写不读）；函数 `analyzer.multi_factor_coupling`/`generate_advice`（analyzer.py:10-11 自述无生产调用者，仅测试覆盖）。

---

## 十三、方法说明与免责

- 本报告所有 `file:line` 均来自当前工作区快照（2026-10-18 审计时点），行号在源码变动后会漂移，引用时请以片段内容为准。
- "重复实现计数""session 键数""import 边数"由脚本统计（AST/正则），脚本未落盘（审计只读约束），方法见文中说明，可复现。
- 涉及 Streamlit 运行时语义、Supabase 客户端会话存储的判断均标注「推断」，并在第十一节给出可执行复现步骤；未标注「推断」的行为均可在源码中直接验证。
- 未执行任何测试：审计环境缺 `streamlit/pytest/pandas`，运行测试会 import 失败；因此本报告不声称"当前测试全绿"。
