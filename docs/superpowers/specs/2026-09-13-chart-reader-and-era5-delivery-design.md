# 读图解析转型 · ERA5 交付闭环 · 手册体系化 设计方案

- 日期：2026-09-13
- 状态：已获用户逐节批准（六节无异议，含 5a AQI 统一）
- 目标版本：2.3.0 → 2.4.0（发布号最终定为 `2.3.1`，见文末附录 C）
- 关联需求：用户提出的四项改进
  1. 页面使用说明优化，侧边栏单独开启用户使用手册详细说明
  2. 智能分析建议板块转型（功能与其他板块大量重合）
  3. ERA5 数据下载的变量选择不够详细清晰
  4. CDS 引导说明更新，Python 脚本辅助下载功能落实

---

## 1. 背景与问题陈述

### 1.1 需求 1：使用说明处于原始状态

- 侧边栏没有任何手册入口。使用说明只是主区顶部一个折叠块（`app.py:448-465`），仅 4 条要点。
- 仓库根目录 `用户使用手册.html`（30 KB，14 个二级标题，含 FAQ）在代码中**零引用**，是一份脱机文档。其第七章「智能分析与建议（核心功能）」正是本次要改造掉的板块，并引用了早已不存在的「气候态」Tab。
- 结论：文档与实际功能已经漂移，且漂移不可见（没有任何机制会发现）。

### 1.2 需求 2：智能分析 Tab 与其他板块大量重合

`modules\analyzer.py::render_analysis_tab`（`analyzer.py:1106-1305`）目前渲染 9 个内容块，经逐块比对：

| 内容块 | 本 Tab 位置 | 重复位置 | 重叠程度 |
|---|---|---|---|
| 历史事件检测（8 类国标卡片） | `analyzer.py:1151-1191` | `nwp_forecast.py:1261-1273`（预报口径）；`app.py:900-913`（顶层重复跑一遍供报告用） | 表现层近似相同，数据源不同 |
| 多要素耦合分析 | `analyzer.py:1195-1202` | `nwp_forecast.py:1319-1322` | 概念重叠，判据不同 |
| 空气质量评估 | `analyzer.py:1204-1210` | `visualizer.py:611-689`；`nwp_forecast.py:1488-1492`、`1878-1896`；同页二次计算 `analyzer.py:1287` | 数据源相同，标准与聚合不同 |
| 数据统计摘要 | `analyzer.py:1236-1268` | `visualizer.py:896-908`；`reporter.py:349-373`、`1203-1217` | 本 Tab 版本是子集 |
| 数值预报驱动分析 | `analyzer.py:1274-1280` | `nwp_forecast.py:1236-1322` | 本 Tab 版本是子集 |
| 公众出行 / 农业建议 | `analyzer.py:1214-1232` | `reporter.py:748-790`、`1060-1078` | 文案库同源，取数排版各写一遍 |
| 综合建议 | `analyzer.py:1282-1284` | `nwp_forecast.py:1510-1704`（7 项生活指数） | 粒度不同，目标用户相同 |
| AI 智能解读 | `analyzer.py:1286-1305` → `ai_narrative.py:436-482` | 无重复实现 | 全平台唯一 |
| 趋势分析与异常检测 | `analyzer.py:878-925` | 无等价实现 | 全平台唯一 |

本 Tab 独有的内容（无任何其他板块提供）：趋势分析与 IQR 异常检测（全仓唯一使用 `np.polyfit` 与 Tukey IQR 的位置）、`multi_factor_coupling` 中的气压骤降与风寒判据、`_render_smart_advice` 中的 PM2.5–风速负相关建议、`_build_wind_summary` 的最大风速时段风向与转向判定、AI 解读块。

本次处置：前四块随 Tab 渲染器一并删除（用户已确认不保留），AI 解读块经改造后以读图解析形态保留。

用户决策：**保留 AI 模块，向读图解析方向转型；不保留国标预警检测**（8 类检测仍由 `app.py:900-913` 运行并喂给报告导出，报告中不缺失）。

### 1.3 需求 3 与 4：ERA5 引导无法使用

`modules\data_loader.py::_render_era5_guide`（`data_loader.py:888-1034`）的现状：

- Python 代码只显示在 `st.text_area`，没有可下载文件，没有落地执行。
- 生成代码使用了 CDS 新版 API 已废弃的关键字与不存在的变量。经对 CDS 官方 constraints 接口做**无凭证在线校验**（`POST /api/retrieve/v1/processes/<dataset>/constraints`），逐条实测结论见附录 A。
- 引导文案两处（`data_loader.py:900`、`:970`）指向「再分析数据处理」Tab，该 Tab 不存在（`app.py:676-683` 只有 6 个标签，ERA5 实为导入页 API 区第三个子标签）。
- `era5_data` / `era5_lat` / `era5_lon` 三个 session key 仅出现在重置列表（`app.py:107`），全项目**无任何写入点**，即 ERA5 数据没有任何入口流回平台。

### 1.4 连带发现：AQI 口径即将成为「页面说谎」

- `analyzer.check_air_quality` 是全项目唯一使用 `config.AQI_BREAKPOINTS`（HJ 633-2026 表）的地方，改造后将成为死代码。
- 剩余的 AQI 计算全部走 `nwp_forecast._compute_cn_aqi`（`nwp_forecast.py:344-364`）的私有 2012 版断点表（`nwp_forecast.py:270-281`），消费者是数值预报 Tab 与首页天气墙（`weather_wall.py:225` 懒加载复用）。
- 同一 PM2.5 浓度在两处得出不同结果：浓度 50 → 2026 表 IAQI 100，2012 表 IAQI 69；浓度 75 → 125「轻度污染」vs 100「良」。
- `config.AQI_BREAKPOINTS` 自身存在结构性缺陷：
  - `"nox"` 第二档 `(41, 60)`、第三档 `(81, 120)` —— **61~80 是空洞**，落在此区间的浓度无档可归。
  - `"so2"` 浓度节点为 `50/100/200/400/800/1600`，与国标体系的 `50/150/475/800/1600/2100` 不符。
  - 缺少 `co` 与 `o3` 两项（`nwp_forecast` 的私有表含 6 项）。
- `analyzer._calc_single_aqi`（`analyzer.py:397-405`）在浓度超出末档时 `return 0`，即 PM2.5 > 400 μg/m³ 会显示 **AQI 0「优」**。
- Word 报告（`modules\reporter.py`）不含任何 AQI 内容（已 grep 确认无 `AQI`/`aqi`/`pm25` 匹配），因此本项不影响报告。

用户决策：**同意统一（5a）**。

---

## 2. 目标与非目标

### 2.1 目标

1. 建立 `docs/用户使用手册.md` 作为手册唯一真相源，侧边栏可单独开启，应用内可读，可现场导出为独立 HTML。
2. 智能分析 Tab 转型为「AI 读图解析」，删除与其他板块重合的内容块，成为全平台唯一能力。
3. ERA5 变量选择器具备分组、单位、可用性、说明、预设与规模预警，并修正全部非法变量名与关键字。
4. CDS 引导说明与当前 API 一致；交付可直接运行、能把数据送回平台的脚本包。
5. AQI 计算路径统一到单一实现，修掉结构性缺陷与超量程缺陷，并让页面如实标注所用标准版本。

### 2.2 非目标（本次明确不做）

- 不做应用内 CDS 代下载（用户已选「各人自备账号，平台只交付脚本包」）。理由见第 12 节决策记录。
- 不重新定义各污染物的评价时段口径（O₃ 1h/8h、CO 1h/24h 等）。本次只统一计算路径与结构不变量。
- 不做审计中发现的其他死代码清理：`app._render_progress_bar`、`config.WARN_STYLES`、`nwp_forecast.results["trends"]`、`reporter._PLAIN_TYPE_DESC` 中 5 个永不命中的键、`gfs_fc_cache_*`/`aq_cache_*` 不在重置列表。这些登记为后续待办，不在本次范围内。
- 不引入任何当前环境中尚不存在的第三方包，不修改 `requirements.txt` 中已有条目的版本锁定（新增的两条为已存在的传递依赖，见 4.2）。
- 不改变 8 类国标预警检测算法与阈值，不改变 `warnings_list` → 报告导出的数据流。
- 不做图片本地持久化、不做图库管理、不做多轮对话追问。

---

## 3. 术语

| 术语 | 含义 |
|---|---|
| 读图解析 | 用户上传外部气象图（天气图、卫星云图、雷达回波、模式形势图等），由多模态模型输出结构化文字解读 |
| 视觉模型 | 具备图像输入能力的 LLM，通过 OpenAI 兼容的 `image_url` 内容块接收图片 |
| catalogue | ERA5 产品与变量的元数据单一真相源，选择器与脚本生成共用 |
| 真相源 | 唯一被人工维护的数据源，其余产物由它现场生成，不存在第二份副本 |

---

## 4. 架构总览

### 4.1 模块边界

```
新增（4 个模块）
  modules/manual.py        手册加载 / 章节解析 / 应用内渲染 / 独立 HTML 生成
  modules/chart_reader.py  图片校验与压缩 / 读图 prompt / 多模态调用 / 页面渲染
  modules/era5_guide.py    ERA5 catalogue / 参数 UI / payload 构建 / 脚本包 ZIP 生成
  modules/aqi.py           IAQI 与综合 AQI 唯一实现 + 断点表结构校验

改造（2 个模块）
  modules/ai_narrative.py  保留报告排版与 .docx 导出；新增 call_vision_llm；删除 detection 版叙事
  modules/analyzer.py      删除 5 个 Tab 专属渲染器与 check_against_extremes；AQI 委托 modules/aqi

数据流
  手册：  docs/用户使用手册.md ──> manual.parse/render ──> 应用内页面 + 导出 HTML
  读图：  上传图片 ──> chart_reader 校验压缩 ──> 视觉模型 ──> 报告卡片 + .docx + .md
  ERA5： era5_guide.catalogue ──> 参数 UI（同一份元数据） ──> payload ──> 脚本包 ZIP
  AQI：   config.AQI_BREAKPOINTS ──> aqi.iaqi/comprehensive ──> analyzer / nwp_forecast / weather_wall
```

### 4.2 设计原则

- **单一真相源**：手册正文、ERA5 变量元数据、AQI 断点各只有一处，其余全部生成。
- **不新增依赖**：图片处理用 `PIL`，Markdown → HTML 用 `markdown_it`，ZIP 用标准库 `zipfile`。三者中前两者已是 streamlit 的传递依赖（实测环境内 `PIL 12.3.0`、`markdown_it 4.2.0` 均可用），本次在 `requirements.txt` 中显式声明以消除传递依赖假设。
- **应用不 import 可选重依赖**：应用侧永不 `import cdsapi / xarray / netCDF4`（实测本机三者中 `cdsapi` 未安装）。它们只出现在生成的脚本包内，由用户在本地安装。
- **不假装降级**：视觉调用失败时不生成任何替代文本（文本模型读不了图，编造等同幻觉）。

---

## 5. 详细设计

### 5.1 用户使用手册（需求 1）

#### 5.1.1 真相源

新建 `docs/用户使用手册.md`，UTF-8，14 章，编号 1–14 连续，使用 `## N. 标题` 作为章标题、`### ` 作为节标题。章节：

| 章 | 标题 | 关键内容 |
|---|---|---|
| 1 | 这份手册怎么用 | 三种阅读路径：评审/首次使用者/排障；每章一句话摘要 |
| 2 | 平台能力与边界 | 能做什么；明确声明不替代国家气象部门权威预报 |
| 3 | 安装与启动 | 本地启动、依赖版本、Secrets 配置、常见启动故障 |
| 4 | 界面总览 | 顶部摘要卡、侧边栏、6 个 Tab 的职责与跳转关系 |
| 5 | 数据导入与质量控制 | 三种导入方式、列名别名规则、质控指标含义与判读 |
| 6 | 可视化分析怎么读 | 各子面板的读图要点与适用场景 |
| 7 | 数值预报 | 数据来源、时效、AQI 分档、高温面板、精度详情 |
| 8 | AI 读图解析 | 支持哪些图、图片要求与体积上限、如何提问、结果如何解读、导出报告、隐私提示 |
| 9 | 报告导出 | 两种报告版本的差别与适用场景 |
| 10 | 报文解码 | METAR/SYNOP 用法与已知限制 |
| 11 | ERA5 再分析数据获取 | 完整流程：注册 → 接受许可 → 选参数 → 下载脚本包 → **手动打开终端**并执行命令 → CSV 回导；含 Windows 与 macOS/Linux 打开终端的具体步骤；常见错误对照 |
| 12 | 侧边栏与自定义阈值 | 各阈值输入项含义、与国家标准的关系、重置按钮行为 |
| 13 | 常见问题 | 分类：安装启动 / 数据导入 / 读图解析 / ERA5 / 报告导出 |
| 14 | 标准引用与术语表 | 引用标准全称与实施日期；术语中英对照 |

#### 5.1.2 应用内入口与渲染

侧边栏用户面板下方增加主按钮「📖 用户使用手册」。点击置 `st.session_state["_manual_open"] = True` 并 `st.rerun()`。

`app.py` 在登录门禁之后、主头部之前插入拦截：

```python
if st.session_state.get("_manual_open"):
    from modules.manual import render_manual_page
    render_manual_page()
    st.stop()
```

放在登录门禁之后，保证未登录用户仍先看到登录页；放在主头部之前，使手册页独占主区。手册页顶部提供「← 返回应用」按钮，置 `_manual_open = False` 并 `st.rerun()`。

**不占用 Tab 编号**，因此 `active_tab`、`_nav_stack`、`_TAB_NAMES`、`_RESET_KEYS_BY_TAB`、所有 `_navigate_to()` 调用均不受影响。

#### 5.1.3 章节导航

使用 `st.selectbox` 章节选择器（选项为「全部」+ 14 章标题）+ 「显示全部」勾选。切换时只渲染所选章节。

被否决的备选：页内 `#anchor` 跳转。Streamlit 生成的标题 id 依版本变化，不可靠，且跨版本静默失效。

#### 5.1.4 独立 HTML 导出

`build_manual_html(markdown_text) -> bytes`：

- 用 `markdown_it.MarkdownIt("commonmark").enable("table")` 渲染正文。
- 内嵌一份 CSS，沿用现有 `用户使用手册.html` 的配色与组件（蓝色渐变色头、卡片、`.tip` / `.warn` / `.danger` 提示块、深色代码块）。
- 自动生成目录（锚点由标题序号生成，形如 `ch-7`），目录链接在导出文件内**必须可用**（导出为静态 HTML，锚点由本函数自己写入，不依赖 Streamlit）。
- 头部显示版本号（取 `config.APP_VERSION`）与生成时间。

页面提供 `st.download_button`，文件名 `用户使用手册.html`。

#### 5.1.5 旧文件处置

`用户使用手册.html` 的内容迁入 Markdown 后**从仓库删除**，`README.md` 增加指向 `docs/用户使用手册.md` 的链接。不做两份并行维护。

#### 5.1.6 接口

```python
# modules/manual.py
MANUAL_PATH: str                    # 绝对路径，由 __file__ 推导，不依赖 cwd
CHAPTER_RE = re.compile(r"^##\s+(\d+)\.\s+(.+?)\s*$", re.M)

def load_manual_markdown() -> str
def parse_chapters(md_text: str) -> list[dict]
    # -> [{"index": int, "title": str, "anchor": f"ch-{index}", "body_md": str}, ...]
def render_manual_page() -> None
def render_sidebar_entry() -> None
def build_manual_html(md_text: str) -> bytes
```

`parse_chapters` 对空章、编号不连续、编号重复不抛异常，而是返回解析结果并在页面顶部显示一条 `st.warning`，避免文档小错导致整页不可用。

### 5.2 AI 读图解析（需求 2）

#### 5.2.1 导航与标签变更

| 位置 | 现状 | 改为 |
|---|---|---|
| `app.py:680` tab_labels[3] | `"[检测] 智能分析与建议"` | `"[读图] AI 读图解析"` |
| `app.py:102` `_TAB_NAMES[3]` | `"智能分析"` | `"读图解析"` |
| `app.py:114` `_RESET_KEYS_BY_TAB` 键 | `"智能分析"` | `"读图解析"`，键集见 5.2.8 |
| `app.py:240` 摘要卡按钮 | `"🔔 检测"` | `"🖼 读图"` |
| `app.py:324` 下一步提示 | 提到「[检测] 查看预报驱动的智能分析建议」 | 按实际数据状态改写为指向读图解析或报告导出 |
| `modules/analyzer.py:1108` 子标题 | `"[检测] 智能分析与建议"` | 随渲染器一并删除 |

**Tab 索引 3 保持不变**，`_navigate_to(3)` 等全部调用点无需修改。

#### 5.2.2 页面结构

`render_chart_reader_tab()` 自上而下：

1. 标题与一句话说明（上传气象图，AI 输出结构化解读）。
2. 隐私提示条：图片将发送至所配置的 AI 服务商；含涉密或未公开信息的图片请勿上传。
3. 上传区 `st.file_uploader(type=["png","jpg","jpeg","webp"], accept_multiple_files=True)`。
4. 图片清单与处理结果：原尺寸、原体积、压缩后体积、是否需要重新压缩。
5. 可选补充说明输入框（例：「这是 500hPa 高空图，请重点关注槽脊位置」），限 500 字。
6. 生成按钮 + 限频提示。
7. 解读结果（报告卡片）与导出按钮。
8. 常见失败原因与处理对照表。

**本 Tab 不依赖已导入数据**，零数据可正常使用。因此 `app.py:895` 的 `if st.session_state["df"] is not None:` 守卫必须改为无条件渲染。

#### 5.2.3 图片管线

全部在内存中处理，不写磁盘。

| 参数 | 值 | 理由 |
|---|---|---|
| `MAX_IMAGES` | 3 | 控制单次成本；多图对比需求有限 |
| `MAX_RAW_BYTES` | 20 MB | 原始字节硬上限。超过则直接拒绝，不解码——防止解压炸弹与内存膨胀 |
| `MAX_IMAGE_BYTES` | 5 MB | 单图上限，判定对象为**压缩后**字节 |
| `MAX_TOTAL_BYTES` | 12 MB | 合计上限，判定对象为各图**压缩后**字节之和 |
| `MAX_EDGE_PX` | 1600 | 长边上限；气象图上的等值线数值与坐标标注需保持可读 |
| `JPEG_QUALITY` | 88 | 平衡文本锐度与体积 |
| `MIN_EDGE_PX` | 200 | 长边低于此值直接拒绝（无解析价值） |

处理步骤：原始字节 > `MAX_RAW_BYTES` 直接拒绝 → `PIL.Image.open(BytesIO(raw))` → `img.verify()`（**魔数校验，不信任扩展名**）→ 重新 `open` 取尺寸与格式 → 长边超过 `MAX_EDGE_PX` 则等比缩放 → 转 RGB（处理 PNG 透明通道）→ 存为 JPEG q=88 到 `BytesIO`。解码前显式设定 `Image.MAX_IMAGE_PIXELS`，使 PIL 自带的解压炸弹保护生效。

判定顺序：`MAX_RAW_BYTES` 闸门在解码前 → 解码并压缩 → 压缩后单图字节超 `MAX_IMAGE_BYTES` 则拒绝该图（**唯一一次压缩，不做二次降质重试**，避免用户无从判断画质损失）→ 各图压缩后字节之和超 `MAX_TOTAL_BYTES` 则整体拒绝。

#### 5.2.4 模型配置

`st.secrets` 键：

| 键 | 必需 | 缺省行为 |
|---|---|---|
| `LLM_VISION_MODEL` | **是** | 未配置即视为「读图解析未配置」。**不回落**到 `LLM_MODEL` |
| `LLM_VISION_API_KEY` | 否 | 回落到 `LLM_API_KEY` |
| `LLM_VISION_BASE_URL` | 否 | 回落到 `LLM_BASE_URL`，再回落到 `https://api.deepseek.com` |

不回落 `LLM_MODEL` 是有意为之：默认的 `deepseek-chat` 无视觉能力，若回落会导致「配置了却始终失败」的隐性故障。宁可明确报「未配置」。

请求体（OpenAI 兼容多模态协议，provider 无关）：

```json
{
  "model": "<LLM_VISION_MODEL>",
  "messages": [
    {"role": "system", "content": "<系统指令>"},
    {"role": "user", "content": [
      {"type": "text", "text": "<读图 prompt>"},
      {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,<...>"}}
    ]}
  ],
  "temperature": 0.3,
  "max_tokens": 1600
}
```

`temperature 0.3` 与现有 `call_llm` 一致；`max_tokens 1600`（现有为 800）因为读图需输出六段结构化内容。超时 90 秒（现有为 30 秒），视觉请求耗时更长。

#### 5.2.5 读图 prompt 契约

`build_chart_prompt(images_meta, user_note) -> str`，固定输出六段，标题用 `【】` 包裹以复用现有 `_parse_sections` 切片逻辑：

1. `【图像信息】` 图片数量、文件名、标注的图种与时间（若图中可读）
2. `【图面要素识别】` 坐标轴、色标、图例、单位、等值线间隔分别是什么
3. `【主要分布特征】` 高/低压、槽脊、锋面、雨带、回波强度分布等可判读的系统
4. `【关键数值与极值】` 图中可读的极值及其位置，必须与图面标注一致
5. `【趋势与演变】` 仅当上传多图或图中含时序/多时次时输出，否则明确写「单图无法判断演变」
6. `【风险提示与结论】` 面向业务与公众的可操作结论

硬约束（写入 prompt 正文，逐条明示）：

- 图中未标注的信息必须写「图中未标注」，不得推测。
- 禁止编造站点名、地名、数值、时间、模式名称。
- 引用数值时必须同时给出该数值在图中的位置特征（如「色标右端」「等值线密集区」）。
- 无法确定图种时，先说明不确定，再给出最可能的判读与其依据。
- 气象结论仅供学习参考，最终以官方发布为准。

#### 5.2.6 错误处理与降级矩阵

| 情况 | 行为 |
|---|---|
| `LLM_VISION_MODEL` 未配置 | `st.info` 配置指引（含所需三个键名），**不显示**生成按钮 |
| 未上传图片即点击生成 | `st.warning` 提示，不发起调用 |
| 单图压缩后超 5 MB | 该图标记失败并说明原因，不进入 prompt；其余图片正常处理 |
| 单图原始字节超 20 MB | 拒绝该图，提示「文件过大，请先自行压缩后上传」 |
| 合计超 12 MB | 整体拒绝并提示精简张数 |
| 伪装文件（扩展名合法但非图片） | 魔数校验失败，拒绝并说明 |
| 长边 < 200 px | 拒绝并说明「分辨率过低，无法解析」 |
| 调用超时 / HTTP 错误 / 返回体结构异常 | `st.error` 显示可读原因（截断至 200 字）+ 保留原图 + 重试按钮；**不生成任何替代文本** |
| 返回内容为空字符串 | 视为失败，同上 |
| `.docx` 导出失败 | 网页展示保留，单独提示导出失败 |

#### 5.2.7 输出与导出

- 报告卡片：复用 `ai_narrative._report_html`（`ai_narrative.py:333-352`）。
- `.docx`：复用 `ai_narrative._build_docx`，新增**嵌入上传的原图**（`doc.add_picture`，宽度限制 15 cm），便于答辩留档。
- `.md`：新增纯文本下载，内容为模型原始输出。
- 文件名：`气象读图解析报告.docx` / `.md`。

#### 5.2.8 会话状态与限频

| 键 | 内容 |
|---|---|
| `chart_reader_images` | `list[dict]`，每项 `{name, orig_kb, new_kb, width, height, jpeg_bytes, error}` |
| `chart_reader_text` | 模型输出原文 |
| `chart_reader_meta` | `{generated, images: int, model: str}` |
| `chart_reader_last_gen` | 上次生成时间戳 |
| `chart_reader_gen_count` | 本会话生成次数 |

`_RESET_KEYS_BY_TAB["读图解析"] = ["chart_reader_images", "chart_reader_text", "chart_reader_meta", "chart_reader_last_gen", "chart_reader_gen_count"]`。

限频：沿用 60 秒最小间隔，新增每会话最多 10 次硬上限。每次生成前在按钮区显示「本会话已生成 N/10 次」与当前图片数、压缩后合计体积、粗略图像 token 估算（按 `宽×高/750` 估算，取整到百）。

#### 5.2.9 删除清单

以下函数在改造后无任何调用者，且**均无测试覆盖**（已核对 `tests/` 全部用例仅覆盖纯逻辑函数），予以删除：

| 函数 | 位置 | 类型 |
|---|---|---|
| `render_analysis_tab` | `analyzer.py:1106-1305` | UI 入口 |
| `_render_smart_advice` | `analyzer.py:928-983` | UI 块 |
| `_render_trend_section` | `analyzer.py:878-925` | UI 块 |
| `_render_air_quality_section` | `analyzer.py:492-554` | UI 块 |
| `_render_nwp_analysis_section` | `analyzer.py:820-875` | UI 块 |
| `check_against_extremes` | `analyzer.py:988-1031` | 逻辑，**运行期不可达**：`analyzer.py:992` 的 `if not extreme` 必命中，`climate_extreme` 全项目唯一写入点是 `app.py:834 = None` |
| `ai_narrative.build_prompt` | `ai_narrative.py:26-205` | 逻辑，detection 专用 |
| `ai_narrative.build_fallback_markdown` | `ai_narrative.py:248-274` | 逻辑，detection 专用 |
| `ai_narrative.render_ai_block` | `ai_narrative.py:436-482` | UI 入口 |
| `config.WARN_STYLES` 的 import | `analyzer.py:13` | 死 import（常量本身不在本次删除范围） |

同时删除 `app.py:906` 的 `("极值", check_against_extremes)` 注册项与 `app.py:36` 的 import。

#### 5.2.10 保留清单

以下**纯逻辑**函数保留不动，理由：`app.py:900-913` 顶层仍在运行它们并把结果写入 `warnings_list` 供报告导出使用，且 `tests/test_analyzer.py` 全部 91 条用例覆盖它们。

`check_high_temperature` / `check_cold_wave` / `check_gale` / `check_fog` / `check_rainstorm` / `check_frost` / `check_thunderstorm` / `check_haze` / `multi_factor_coupling` / `generate_advice` / `set_custom_thresholds`。

`check_air_quality` **不在此列**：它在第 5 步（读图解析改造）中随 `_render_air_quality_section` 一并删除。理由是其两个调用点（`_render_air_quality_section`、`analyzer.py:1287`）都在本次删除范围内，Word 报告也不含 AQI 内容（已 grep 确认），保留它等于在删除旧死代码的同时新增一处死代码。删除前先在第 1 批次把它改写为委托 `modules.aqi`，使 `modules/aqi.py` 的测试覆盖不依赖 `analyzer`。

`app.py:37` 的 `multi_factor_coupling` import 在 `app.py` 内无调用点，一并移除（函数本身保留在 `analyzer.py` 供测试与其他模块使用）。

#### 5.2.11 ai_narrative.py 改造后职责

保留：`_parse_sections`、`_build_meta`（改名为 `_build_report_meta(scope, extra)` 以脱离 detection 结构）、`_CSS`、`_report_html`、`_set_cjk`、`_build_docx`（增加可选 `images` 参数）、`_display_report`（改为接收 `(text, meta, images)`）。

新增：`call_vision_llm(prompt, images_b64, api_key, base_url=None, model=None) -> str`、`resolve_vision_config() -> dict | None`。

删除：5.2.9 表中三项，以及原 `_build_meta(detection)` 对 detection 结构的依赖。

`_build_meta` 的改造需同步检查 `render_export_tab` 是否复用（已确认 `reporter.py` 独立实现报告，不依赖 `ai_narrative`）。

### 5.3 ERA5 变量选择器（需求 3）

#### 5.3.1 catalogue 单一真相源

迁移 `_ERA5_PRODUCTS`（`data_loader.py:821-885`）到新模块 `modules/era5_guide.py` 并重构为带元数据的结构：

```python
ERA5_PRODUCTS: dict[str, dict] = {
  "<产品显示名>": {
    "dataset": str,                 # CDS dataset 标识
    "url": str,                     # 数据集页面
    "type": "hourly" | "pressure" | "monthly",
    "product_type": list[str] | None,   # None 表示该数据集不接受此键
    "allow_day": bool,              # ERA5-Land 月均值必须为 False
    "time_values": list[str] | None,    # None 表示全部 24 个整点
    "resolution": str,              # 如 "0.1° × 0.1°"
    "coverage": str,                # 如 "1950 年至今（滞后约 2–3 个月）"
    "field_limit": int,             # CDS 单请求字段数上限
    "lag_months": int,
    "notes": str,
    "variables": {
      "<api_name>": {"label": str, "unit": str, "group": str, "note": str},
    },
    "unsupported": {
      "<api_name>": {"label": str, "reason": str, "switch_to": str | None},
    },
    "derivations": [
      {"kind": "uv_to_speed_dir", "u": ..., "v": ..., "output": ["wind_speed", "wind_direction"]},
    ],
  }
}
```

分组取值：`温度` / `湿度` / `风` / `气压` / `降水与蒸发` / `云与辐射` / `大气层结`。

#### 5.3.2 修正清单

全部依据附录 A 的在线实测结论：

| 产品 | 修正项 | 现状 | 改为 |
|---|---|---|---|
| ERA5-Land 小时 | `relative_humidity` | 提供且默认可选 | 移入 `unsupported`，原因「ERA5-Land 不提供相对湿度」，`switch_to` 指向气压层产品 |
| ERA5-Land 小时 | `cloud_cover` | 提供且默认可选 | 移入 `unsupported`，`switch_to` 指向单层产品 |
| ERA5-Land 月均值 | 同上两项 | 提供 | 同上 |
| 单层 | `relative_humidity` | 提供 | 移入 `unsupported`，仅气压层提供 |
| 单层 / 气压层 | `product_type` | **完全缺失** | 补 `["reanalysis"]` |
| 单层 / 气压层 | 10m 风变量名 | `10m_u_component_of_wind` / `10m_v_component_of_wind` | **保持不变**（实测正确）。实施时不得改写为 `u_component_of_wind_10m` / `v_component_of_wind_10m`，该名在任何数据集都不存在 |
| 气压层 | `geopotential_height` | 使用该名 | 改为 `geopotential`，`note` 注明「位势高度 = 位势 ÷ 9.80665」 |
| 气压层 | 层列表 | 34 项 | 按实测 37 项：`1,2,3,5,7,10,20,30,50,70,100,125,150,175,200,225,250,300,350,400,450,500,550,600,650,700,750,775,800,825,850,875,900,925,950,975,1000` |
| 月均值 | `product_type` | 缺失 | 补 `["monthly_averaged_reanalysis"]`，并在 UI 说明 `by_hour_of_day` 变体的差别 |
| 月均值 | `day` | 会带上 | **不带**（`allow_day = False`） |
| 月均值 | `time` | `00:00` | 保持 `["00:00"]`（实测仍正确） |
| 全产品 | `format` | `'format': 'netcdf'` | `'data_format': 'netcdf'` |
| 全产品 | `download_format` | 缺失 | 补 `'unarchived'` |

#### 5.3.3 体验设计

- **分组多选**：变量按组分区展示，组内多选；每组显示已选数量。
- **不支持变量可见但不可选**：不隐藏。显示为禁用项并附原因与「切换到支持该变量的产品」按钮。隐藏会使用户误以为该变量在 CDS 中不存在，是更严重的误导。
- **单位与换算标注**：每个变量在选择器上显示 `中文名（api_name，单位）`，需要换算的追加说明（`K → ℃`、`m → mm`、`u/v 分量 → 风速风向`）。
- **常用组合预设**（`st.selectbox`，选中即填充变量多选）：站点气象常用 / 降水与蒸发 / 高空环流（气压层）/ 云与辐射。
- **产品说明卡**：分辨率、覆盖范围与时效、是否需要 `product_type`、月均值是否允许 `day`、字段数上限。
- **请求规模预警**：实时估算 `字段数 = 变量数 × 年数 × 月数 × 天数（按所选月份实际天数累加）× 时次数 × 层数`，与 `field_limit` 对比。超限时显示 `st.error` 并禁止生成脚本包，同时在文案中给出「缩小区域/减少变量/缩短时段」的具体建议。这一条把 CDS 侧「提交后才排队或失败」的反馈提前到了用户点击之前。
- **年份范围动态化**：从 `range(1950, 2025)`（硬编码）改为 `range(1950, 当前年)`，并在说明中写明 ERA5 约滞后 2–3 个月、ERA5T 近实时数据可能被后续修订。
- **参数对照清单**：已选变量与参数可一键复制为纯文本，字段名与 CDS 官网表单一致，便于不用脚本包的用户手动在网页上填表。

#### 5.3.4 payload 构建

`build_payload(product_key, years, months, variables, pressure_levels, area) -> dict`：

- 按 `type` 决定是否写入 `pressure_level`。
- 按 `allow_day` 决定是否写入 `day`。
- 按 `product_type is not None` 决定是否写入 `product_type`。
- `time_values` 非空时写入该列表，否则写入全部 24 个整点。
- 统一写入 `data_format: "netcdf"` 与 `download_format: "unarchived"`。
- 全部键值以列表形式写出（与 CDS 官网表单生成的一致）。
- 返回前用 `KEYS_ALLOWED_BY_TYPE` 白名单校验键集，多余键直接抛 `ValueError`（开发期暴露出错，而不是把非法请求交给用户）。

### 5.4 CDS 引导与脚本包（需求 4）

#### 5.4.1 引导说明修正

`_render_era5_guide` 的说明文案重写，关键变化：

| 项 | 现状文案 | 改为 |
|---|---|---|
| API 地址 | `url: https://cds.climate.copernicus.eu/api`（未说明 UID 问题） | 明确「无 UID 字段；旧式 `uid:key` 会走已废弃的 LegacyClient 分支而失败」 |
| 客户端版本 | `pip install cdsapi` | `pip install "cdsapi>=0.7.7"` |
| 许可证 | 完全未提 | **提升为首要失败原因**：数据集许可必须在登录状态下于该数据集的下载页手工接受，API 无法代办；未接受时报 `Client has not agreed to the required terms and conditions`，并给出个人资料页可查看已接受许可的说明 |
| 队列与限额 | 「CDS 下载需要排队」 | 补充数据集字段数上限、并发任务上限、2025-04 起 netCDF 成本限额（超限 403）、相同请求命中缓存可能返回不完整的 ERA5T 数据 |
| 返回格式 | 「下载后为 NetCDF 格式」 | 补充多变量或多文件请求**仍可能返回 ZIP**，以及新版 netCDF 的时间维名可能是 `valid_time` 而非 `time` |
| 数据格式关键字 | 未提 | 说明 `format` 已废弃、须用 `data_format` + `download_format`，且缺省 `data_format` 会静默返回 GRIB |
| 失效 Tab 引用 | 两处指向「再分析数据处理」Tab | 改为指向「数据导入」Tab 的实际流程 |

导出格式说明补充：`data_format` 仅接受 `grib` / `netcdf`；`download_format` 接受 `zip` / `unarchived`。

#### 5.4.2 脚本包内容

`build_script_zip(...) -> bytes`，用标准库 `zipfile` 写入 `io.BytesIO`，通过 `st.download_button` 下载，文件名 `era5_download_pack.zip`。

| 文件 | 内容 |
|---|---|
| `era5_download.py` | 见 5.4.3 |
| `.cdsapirc.example` | `url: https://cds.climate.copernicus.eu/api` + `key: <你的 API Key>`，注释说明无 UID、放置位置为 `~/.cdsapirc` |
| `README.txt` | **主路径为手动打开终端执行命令**：如何打开终端（Windows：`Win + R` 输入 `cmd`，或开始菜单搜索 PowerShell；macOS：应用程序 → 实用工具 → 终端）、三步命令、许可接受链接、常见错误对照表（许可证未接受 / 422 / 403 成本限额 / 队列受限 / 返回 ZIP） |
| `requirements.txt` | `cdsapi>=0.7.7`、`xarray`、`netCDF4`、`pandas` |
| `一键运行.bat` | **可选加速器，非主路径**。Windows 用户若不想敲命令可双击运行：`pip install -r requirements.txt` → `python era5_download.py` → `pause`。README 中标注为「也可双击本文件」 |
| `运行.sh` | macOS / Linux 的可选加速器，内容同 `.bat`，带 `set -e` |

#### 5.4.3 生成脚本的能力契约

`era5_download.py` 必须实现：

1. **参数烘焙**：文件顶部 `PARAMS = {...}` 为 5.3.4 构建的完整合法 payload，用户无需编辑。
2. **可读报错**：捕获并分类——
   - 许可证未接受 → 打印数据集下载页链接与该数据集名称，提示手工接受后重试；
   - HTTP 422 → 打印「请求参数不被该数据集接受」并列出 payload 键集，指引登录 CDS 表单核对；
   - HTTP 403 且含成本限额信息 → 提示缩小请求范围；
   - 队列受限 → 提示稍后重试或减少请求规模；
   - 配置文件缺失 → 提示 `.cdsapirc` 位置与内容格式。
3. **进度反馈**：`cdsapi.Client(..., progress=True)` 之外的补充说明，明确「状态从 queued 变为 running 可能需要数十分钟到数小时，可关闭终端后凭请求 ID 重新获取」。
4. **ZIP 自动解包**：下载产物为 ZIP 时解包出全部 `.nc`，返回文件清单。
5. **单位换算与派生量**：
   - 温度 `K → ℃`（`-273.15`）
   - 累计降水 `m → mm`（`×1000`）
   - 气压 `Pa → hPa`（`÷100`）
   - 云量 `0–1 → 0–100 %`
   - 位势 `→ 位势高度`（`÷9.80665`）
   - `u/v` 分量 → 风速 `sqrt(u²+v²)` 与气象风向 `(270 - degrees(atan2(v, u))) % 360`
6. **NetCDF → CSV**：`xarray.open_dataset`，兼容时间维名 `time` 与 `valid_time`；存在 `expver` 维时按 `expver` 合并或取最新；输出**长表 CSV**，列名映射见下表，直接可被「数据导入」Tab 识别。

| ERA5 变量 | CSV 列名 | 换算 |
|---|---|---|
| `2m_temperature` | `temperature` | K → ℃ |
| `2m_dewpoint_temperature` | `dewpoint` | K → ℃ |
| `skin_temperature` | `skin_temperature` | K → ℃ |
| `surface_pressure` | `pressure` | Pa → hPa |
| `mean_sea_level_pressure` | `mslp` | Pa → hPa |
| `total_precipitation` | `precipitation` | m → mm |
| `10m_u_component_of_wind` + `10m_v_component_of_wind` | `wind_speed`、`wind_direction` | 分量合成 |
| `total_cloud_cover` / `cloud_cover` | `cloud_cover` | 0–1 → % |
| `relative_humidity` | `humidity` | 不变 |
| `snow_depth` | `snow_depth` | 不变 |
| `geopotential` | `geopotential_height` | ÷9.80665 |
| 其他 | 原变量名 | 不换算 |

时间列统一写为 `timestamp`（ISO 格式），满足「数据导入」Tab 的字段识别规则。

7. **无第三方密钥经手**：脚本只读取本机 `~/.cdsapirc`，不接受任何命令行密钥参数。

#### 5.4.4 应用侧零依赖约束

`modules/era5_guide.py` 只允许 `import` 标准库（`io`、`zipfile`、`textwrap`、`datetime`）与 `streamlit`。脚本正文以字符串模板形式存放，通过 `textwrap.dedent` 生成。**禁止**在应用侧 `import cdsapi / xarray / netCDF4`，以保证 Streamlit Cloud 部署不会因缺少这些重依赖而失败，且避免 Cloud 上的内存风险。

### 5.5 AQI 口径统一（5a）

#### 5.5.1 新模块

`modules/aqi.py`：

```python
IAQI_NODES = (0, 50, 100, 150, 200, 300, 400, 500)

def validate_breakpoints(table: dict) -> list[str]
    # 返回缺陷描述列表，空列表表示合法。模块导入时对 config.AQI_BREAKPOINTS 执行一次，
    # 缺陷以 warnings.warn 输出（不抛异常，避免阻断应用启动）

def iaqi(conc: float, pollutant: str) -> float | None
def comprehensive_aqi(concentrations: dict) -> dict
    # -> {"aqi": int, "level": str, "color": str, "primary": str | None, "details": [...]}
```

#### 5.5.2 结构不变量（`validate_breakpoints` 强制）

对每个污染物，断点表为 `[(lo, hi, iaqi_lo, iaqi_hi), ...]`：

1. `lo_0 == 0`。
2. 每档 `lo <= hi`。
3. 档间连续：`lo_{i+1} == hi_i + 1`（允许 1 的整数间隙）。**现状 `"nox"` 的 60→81 违反此条。**
4. `iaqi` 节点严格递增，首档 `iaqi_lo == 0`，每一项均取自 `IAQI_NODES = (0, 50, 100, 150, 200, 300, 400, 500)`；末档 `iaqi_hi` 允许为 **200**（气态污染物的 1h 表仅定义到 200）或 **500**（颗粒物与 CO）。
5. 相邻档的 `iaqi_hi == iaqi_lo_{i+1}`（不允许在 IAQI 轴上出现空洞）。
6. 污染物的浓度单位在表中以注释标注（`CO` 为 mg/m³，其余为 μg/m³）。

#### 5.5.3 计算规则

- `IAQI = (iaqi_hi - iaqi_lo) / (hi - lo) × (C - lo) + iaqi_lo`，`C` 使用 `max(0, conc)`。
- 超出末档：按末档斜率线性外推后，**钳制到该污染物自身的最大 IAQI 节点**（颗粒物与 CO 为 500，气态污染物为 200），**禁止返回 0**（修掉 `analyzer.py:405`）。
- 落在档间间隙或非有限值：返回 `None`，该污染物不参与综合 AQI。
- 综合 AQI = 各 IAQI 最大值；`AQI <= 50` 时 `primary = None`；并列最大值时列出全部。
- 等级与颜色按 `config.AQI_LEVELS` 判定，AQI 范围 1–500。

#### 5.5.4 调用点收敛

| 位置 | 现状 | 改为 |
|---|---|---|
| `analyzer._calc_single_aqi`（`analyzer.py:397`） | 私有实现 | 删除，`check_air_quality` 直接调 `aqi.comprehensive_aqi` |
| `nwp_forecast._iaqi` / `_compute_cn_aqi`（`nwp_forecast.py:315-364`） | 私有 2012 表 | 删除私有表 `_PM25_BP` 等与两个函数，改为薄封装调用 `aqi.comprehensive_aqi`（保留函数名与返回签名，避免改动 3 个调用点） |
| `weather_wall.py:225` | 懒加载 `nwp_forecast._compute_cn_aqi` | 不改代码，自动获得统一后的结果 |

`nwp_forecast._compute_cn_aqi` 现有返回值为四元组，统一后仍返回四元组 `(aqi, level, primary, color)`，保持 `nwp_forecast.py:421`、`:1430`、`weather_wall.py:242` 三处调用点不变。

#### 5.5.5 数值来源与如实标注

断点数值**必须以 HJ 633-2026 表 1 为准**。核实步骤：

1. 优先查生态环境部标准文本 / 全国标准信息公共服务平台；
2. 其次查 HJ 633-2026 官方 PDF；
3. 若两者均不可及，**不得**把现有 `config` 表或 2012 表当作「2026 标准」使用。

无论核实结果如何，`config.py` 新增显式常量：

```python
AQI_STANDARD_LABEL = "HJ 633-2026"   # 或实际所用版本，如 "HJ 633-2012"
```

页面文案、手册、图表标题一律渲染该常量，**禁止硬编码标准名**。这样即使最终只能核实到旧版断点，页面也不会声称用了新标准。

**最终落地决定（2026-09-13 用户确认「按如实标注实际所用标准版本落地」）**

HJ 633-2026 表 1 的数值不可公开核实（标准文本在付费墙后），因此采用 `modules/nwp_forecast.py` 中已在生产运行的 **HJ 633-2012 断点表**作为统一口径，`AQI_STANDARD_LABEL = "HJ 633-2012"`。该表与国标 1h（气态）/ 24h（颗粒物、CO）分指数表一致：

| 污染物 | 时段 | 浓度节点 | IAQI 节点 |
|---|---|---|---|
| PM2.5 | 24h | 0, 35, 75, 115, 150, 250, 350, 500 μg/m³ | 0–500 |
| PM10 | 24h | 0, 50, 150, 250, 350, 420, 500, 600 μg/m³ | 0–500 |
| SO₂ | 1h | 0, 150, 500, 650, 800 μg/m³ | 0–200 |
| NO₂ | 1h | 0, 100, 200, 700, 1200 μg/m³ | 0–200 |
| CO | 1h | 0, 5, 10, 35, 60, 90, 120, 150 mg/m³ | 0–500 |
| O₃ | 1h | 0, 160, 200, 300, 400 μg/m³ | 0–200 |

选它的三个理由：数值可核验、不属编造；数值预报 Tab 与首页天气墙本就运行在这张表上，统一后**这两处的 AQI 数值不变**，行为变更仅限标准标注文字；它天然覆盖六项污染物，直接补齐了 `config` 表缺失的 CO 与 O₃。

`config.AQI_BREAKPOINTS` 整表替换为该口径。页面、手册、图表标题渲染 `AQI_STANDARD_LABEL`，如实显示为 2012 版。待 HJ 633-2026 表 1 可核实时，只需替换 `config` 中的数值与该常量，其余代码不动。

**已知局限（写入模块文档字符串）**：`fetch_air_quality` 以逐时浓度代入 1h 表，正确；`check_air_quality` 以时段均值代入同一张表，会高估气态污染物的分指数。评价时段口径的重新定义超出本次范围（见 2.2 节），仅记录。

---

## 6. 接口契约汇总

### 6.1 新增模块对外接口

```python
# modules/manual.py
def load_manual_markdown() -> str
def parse_chapters(md_text: str) -> list[dict]
def render_manual_page() -> None
def render_sidebar_entry() -> None
def build_manual_html(md_text: str) -> bytes

# modules/chart_reader.py
MAX_IMAGES: int; MAX_RAW_BYTES: int; MAX_IMAGE_BYTES: int; MAX_TOTAL_BYTES: int
MAX_EDGE_PX: int; JPEG_QUALITY: int; MIN_EDGE_PX: int
def process_image(raw: bytes, name: str) -> dict
    # -> {"name", "ok": bool, "error": str|None, "orig_kb", "new_kb", "width", "height", "jpeg_bytes"}
def build_chart_prompt(images_meta: list[dict], user_note: str) -> str
def render_chart_reader_tab() -> None

# modules/era5_guide.py
ERA5_PRODUCTS: dict
KEYS_ALLOWED_BY_TYPE: dict
def build_payload(product_key, years, months, variables, pressure_levels, area) -> dict
def estimate_field_count(product_key, years, months, variables, pressure_levels) -> int
def build_script_zip(product_key, payload, meta) -> bytes
def render_era5_guide() -> None

# modules/aqi.py
IAQI_NODES: tuple
def validate_breakpoints(table: dict) -> list[str]
def iaqi(conc: float, pollutant: str) -> float | None
def comprehensive_aqi(concentrations: dict) -> dict

# modules/ai_narrative.py（改造后）
def resolve_vision_config() -> dict | None
def call_vision_llm(prompt, images_b64, api_key, base_url=None, model=None) -> str
def _build_report_meta(scope: str, extra: dict) -> dict
def _display_report(text: str, meta: dict, images: list[dict] | None = None) -> None
```

### 6.2 只允许通过的模块边界

- `app.py` 只能通过 `modules.*` 的公开函数访问功能；不直接读写 `chart_reader_*` 之外的 session key。
- `modules/chart_reader.py` 不直接读写 `st.secrets` 之外的外部状态；配置解析统一走 `ai_narrative.resolve_vision_config()`。
- `modules/era5_guide.py` 不得 import 任何非标准库的第三方包。

---

## 7. 配置变更

`.streamlit/secrets.toml.example` 新增：

```toml
# ===== AI 读图解析（多模态） =====
# LLM_VISION_MODEL 必须显式配置，且必须是具备图像输入能力的模型；
# 不会回落到 LLM_MODEL（deepseek-chat 无视觉能力，回落会导致持续失败）。
LLM_VISION_MODEL = ""                     # 例：qwen-vl-max / glm-4v / gpt-4o
LLM_VISION_BASE_URL = ""                  # 留空则回落 LLM_BASE_URL
LLM_VISION_API_KEY = ""                   # 留空则回落 LLM_API_KEY
```

`config.py` 新增 `AQI_STANDARD_LABEL`；`APP_VERSION` 改为 `"2.4.0"`。

`requirements.txt` 新增（显式声明已有的传递依赖，不引入新包）：

```
Pillow>=10.0
markdown-it-py>=3.0
```

---

## 8. 安全与隐私

| 风险 | 处置 |
|---|---|
| 上传伪装文件 | PIL 魔数校验，不信任扩展名与 Content-Type |
| 巨图导致内存膨胀 | 三重上限（单图 5 MB、合计 12 MB、张数 3）且压缩在内存完成，不落盘 |
| 视觉 API 密钥泄露 | 仅从 `st.secrets` 读取，不进代码、不进前端、不写入日志；异常信息截断至 200 字后再展示 |
| 图片外传的知情同意 | 页面上传区上方固定显示隐私提示；手册第 8 章重复说明 |
| 成本滥用 | 会话级 60 秒最小间隔 + 每会话 10 次硬上限 + 生成前显示图片数与 token 估算 |
| 第三方密钥经手 | ERA5 脚本包方案下应用完全不接触密钥；脚本只读本机 `~/.cdsapirc` |
| 生成脚本被注入 | 脚本模板中的参数来自受控的 catalogue 与用户数字输入（年份/月份/经纬度），坐标与层数经类型与范围校验后再格式化；字符串插值只用于受控枚举与数值 |

---

## 9. 测试策略

沿用仓库现有风格：测试文件既可被 pytest 收集，也可 `python -B tests/test_x.py` 直接运行（CI 的四个门禁用例即用此方式）。

| 新增/修改 | 覆盖点 |
|---|---|
| `tests/test_manual.py`（新增） | 手册文件存在；章节编号 1–14 连续无重复；章节数与目录一致；每章正文非空；`build_manual_html` 输出含 `<table>`（当正文含表格时）、含全部章节锚点、不含 `TODO`/`TBD` |
| `tests/test_chart_reader.py`（新增） | 原始字节超 20 MB 拒绝；压缩后超 5 MB 拒绝；长边 > 1600 被缩到 1600；长边 < 200 拒绝；扩展名合法但内容非图片被拒绝；PNG 透明通道转 JPEG 不报错；`build_chart_prompt` 含全部六段标题与反幻觉约束关键句；`resolve_vision_config` 在缺 `LLM_VISION_MODEL` 时返回 `None`、在配置齐备时返回三键 |
| `tests/test_era5_guide.py`（新增） | 每个产品的 `build_payload` 键集落在 `KEYS_ALLOWED_BY_TYPE` 白名单内；ERA5-Land 小时无 `product_type`；单层/气压层含 `product_type`；月均值无 `day` 且 `time == ["00:00"]`；全产品含 `data_format`/`download_format` 且不含 `format`；ERA5-Land 产品不得出现 `relative_humidity`/`cloud_cover`；气压层不得出现 `geopotential_height`；`estimate_field_count` 在超限时返回值大于 `field_limit`；`build_script_zip` 产出的 ZIP 含 6 个条目且 `era5_download.py` 内含 `data_format`、不含 `'format'`；**测试不 import `cdsapi`/`xarray`/`netCDF4`** |
| `tests/test_aqi.py`（新增） | `validate_breakpoints` 能检出间隙（用构造的 NOx 空洞表）、非单调 IAQI、缺失 `co`/`o3`；`iaqi` 在各档边界取值正确；超末档返回 500 而非 0；负值按 0 处理；综合 AQI 取最大值；AQI ≤ 50 时 `primary is None`；并列最大列出全部 |
| `tests/test_analyzer.py`（修改） | 现有 91 条**全部保持通过**；`check_air_quality` 相关断言（若有）改为经 `modules.aqi` 的等值结果；删除对已删函数的引用（若有） |
| `tests/test_weather_wall.py`（回归） | 现有 AQI 断言传入显式 dict，不依赖断点数值，应保持通过；执行确认 |

CI 的四个门禁脚本（`test_auth_session.py`、`test_data_quality.py`、`test_analyzer.py`、`test_codec.py`）必须全部通过。建议把新增的 `test_era5_guide.py` 与 `test_aqi.py` 加入门禁步骤。

---

## 10. 影响面清单

### 新增

- `docs/用户使用手册.md`
- `docs/superpowers/specs/2026-09-13-chart-reader-and-era5-delivery-design.md`（本文件）
- `modules/manual.py`、`modules/chart_reader.py`、`modules/era5_guide.py`、`modules/aqi.py`
- `tests/test_manual.py`、`tests/test_chart_reader.py`、`tests/test_era5_guide.py`、`tests/test_aqi.py`

### 修改

- `app.py`：侧边栏手册入口、手册页拦截、Tab 标签与 `_TAB_NAMES`、`_RESET_KEYS_BY_TAB`、Tab 3 无条件渲染、删除 `check_against_extremes` 注册与两个无用 import、摘要卡与下一步提示文案
- `modules/analyzer.py`：删除 5 个渲染器与 `check_against_extremes`；`check_air_quality` 委托 `modules.aqi`；更新模块 docstring（现称「分析建议引擎」）
- `modules/ai_narrative.py`：见 5.2.11
- `modules/data_loader.py`：删除 `_ERA5_PRODUCTS` 与 `_render_era5_guide`，改为 `from modules.era5_guide import render_era5_guide`
- `modules/nwp_forecast.py`：AQI 委托 `modules.aqi`，删除私有断点表
- `config.py`：`AQI_BREAKPOINTS` 结构修复与补项、新增 `AQI_STANDARD_LABEL`、`APP_VERSION`
- `.streamlit/secrets.toml.example`：新增三个视觉模型键
- `requirements.txt`：显式声明 `Pillow`、`markdown-it-py`
- `README.md`：功能表第 16 行（智能分析与建议）改为读图解析；项目结构树；测试清单；新增手册链接
- `docs/同类项目核心介绍.md`：清除对已不存在的「气候态」Tab 的引用
- `.github/workflows/tests.yml`：把两个新增门禁脚本加入步骤

### 删除

- `用户使用手册.html`（内容迁入 `docs/用户使用手册.md`）

---

## 11. 风险登记

| 风险 | 影响 | 缓解 |
|---|---|---|
| 视觉模型对气象图判读能力有限（等值线密集图、非中文标注图） | 解读质量不达预期 | prompt 中强制「图中未标注即声明」；提供补充说明输入框让用户指定图种与关注点；手册第 8 章写明适用与不适用场景 |
| 视觉 API 成本高于文本 | 运营成本上升 | 三重限制（张数、体积、次数）+ 生成前成本可见 |
| 用户上传含敏感信息的图片 | 合规风险 | 上传区固定隐私提示 + 手册重复说明 + 不落盘 |
| HJ 633-2026 断点数值无法核实 | 可能输出与标准不符的 AQI | `AQI_STANDARD_LABEL` 如实标注实际所用版本；结构缺陷必修；核实步骤写入实施第 0 步 |
| AQI 数值变化引发既有用户困惑 | 行为变更 | README 与手册记录本次变更；版本号自 2.3.0 升至 2.4.0 |
| CDS 上游继续变更（2024-09、2025-04 已有两次） | 脚本失效 | 引导说明写明「以 CDS 官网表单生成的代码为准」并给出核对方法；catalogue 与 payload 有测试锁定，变更时能定位 |
| `markdown_it` / `PIL` 的传递依赖关系在未来 streamlit 版本中改变 | 手册或图片功能失效 | 显式写入 `requirements.txt`，不再依赖传递关系 |
| 删除 `render_analysis_tab` 后仍有隐藏调用者 | 运行期报错 | 实施前对全仓做一次精确引用搜索，删除后跑全量测试与应用启动冒烟 |

---

## 12. 设计决策记录

| 决策 | 结论 | 被否决方案与否决理由 |
|---|---|---|
| 智能分析 Tab 的去向 | 转型为 AI 读图解析，不保留国标预警检测 | 保留检测卡（用户明确否决）；另立新 Tab 并删除旧 Tab（导航膨胀，收益相同） |
| 读图的技术路线 | 用户上传外部气象图，多模态模型读图（C 方案 + 体积限制） | 数据驱动读本平台图表（用户未选）；真视觉读本平台图表（需 kaleido 依赖与另配视觉密钥）；A+C 混合（范围过大） |
| 手册的真相源 | `docs/用户使用手册.md` 单一真相源，应用内渲染 + 现场导出 HTML | 单 HTML + iframe 嵌入（30 KB 手工维护成本高、暗色适配差）；两份并行维护（必然漂移） |
| ERA5 下载形态 | 只交付脚本包 ZIP，各人自备 CDS 账号 | 应用内代下载（CDS 许可只能账号本人网页接受且一人一号；Cloud 无持久磁盘、同步阻塞、密钥经手，收益仅为省去「打开终端」一步）；访客自带 key 服务器代跑（前提一步都省不掉却引入密钥代持风险） |
| 视觉模型密钥 | provider 无关的 OpenAI 兼容实现，按 `st.secrets` 配置 | 硬编码某一家（锁定用户）；回落 `LLM_MODEL`（默认模型无视觉能力，造成隐性持续失败） |
| 视觉调用失败的降级 | 不降级，明确报错并保留原图 | 复用文本模型生成摘要（文本模型读不了图，输出等同幻觉） |
| AQI 处置 | 统一到 `modules/aqi` 并修结构缺陷，标准版本如实标注 | 只记账不动（页面继续声称 2026 标准却用 2012 断点）；直接删掉 AQI 展示（丢失已有功能） |
| ERA5 代码归属 | 抽出到 `modules/era5_guide.py` | 留在 `data_loader.py`（该文件已 1059 行，且新功能含 catalogue、UI、ZIP 生成三块职责） |

---

## 13. 验收标准

1. 侧边栏可单独打开用户使用手册；应用内 14 章均可读；导出的 HTML 在浏览器中打开时目录锚点可用、样式完整；手册内容与 2.4.0 实际功能一致。
2. 智能分析 Tab 已更名为读图解析；未导入任何数据时可正常上传图片并生成解读；上传图片超过体积或张数上限时给出明确原因而非静默失败；未配置视觉模型时给出可操作的配置指引且不报错。
3. ERA5 变量选择器按组展示且标注单位与换算；不支持的变量以禁用态显示并说明原因；请求规模超限时在生成前预警。
4. 生成的 ZIP 在干净环境（仅安装包内 `requirements.txt`）中运行不出现 `format` 关键字 422 错误；脚本导出的 CSV 可直接被「数据导入」Tab 识别出 `timestamp`/`temperature` 等标准字段；`README.txt` 含 Windows 与 macOS/Linux 手动打开终端的具体步骤，**不依赖 `.bat`/`.sh` 即可完成全流程**；手册第 11 章与之一致。
5. AQI 全应用走同一实现；构造的 NOx 空洞表能被校验函数检出；PM2.5 = 500 μg/m³ 时返回 500 而非 0；页面与手册显示的标准版本与实际断点表一致。
6. `python -B` 运行四个 CI 门禁脚本全部通过；`pytest tests -q` 无新增失败。
7. 应用可正常启动，冷启动无异常；`git status` 中不再存在 `用户使用手册.html`。

---

## 附录 A · ERA5 / CDS 在线实测结论

核验方式：读取 CDS 机器可读定义（`/api/catalogue/v1/collections/<dataset>`、`/api/retrieve/v1/processes/<dataset>`），并用 `POST /api/retrieve/v1/processes/<dataset>/constraints?allow_unauthenticated=true` 做**无凭证在线校验**——未知键返回 HTTP 422，非法值返回 200 但允许值列表为空。校验时数据集记录 `updated: 2026-09-13`。

### A.1 请求关键字

| 关键字 | 实测状态 |
|---|---|
| `format` | **已废弃**，四个数据集全部返回 422 |
| `data_format` | 当前关键字，枚举**恰为** `grib` / `netcdf`；缺省时单层与气压层静默返回 GRIB |
| `download_format` | 当前关键字，枚举 `zip` / `unarchived`，服务端默认 `unarchived`，下载表单标记为必填 |

各数据集允许的键集：

| 数据集 | 允许键 |
|---|---|
| `reanalysis-era5-land` | `variable, year, month, day, time, area, data_format, download_format`（**无 `product_type`**） |
| `reanalysis-era5-land-monthly-means` | `product_type, variable, year, month, time, area, data_format, download_format`（**无 `day`**） |
| `reanalysis-era5-pressure-levels` | `product_type, variable, year, month, day, time, pressure_level, area, data_format, download_format` |
| `reanalysis-era5-single-levels` | `product_type, variable, year, month, day, time, area, data_format, download_format` |

### A.2 变量标识符

ERA5-Land 小时数据（共 60 个变量）：

| 量 | 标识符 | 是否存在 |
|---|---|---|
| 2m 气温 | `2m_temperature` | 是 |
| 2m 露点 | `2m_dewpoint_temperature` | 是 |
| 地表温度 | `skin_temperature` | 是 |
| 总降水 | `total_precipitation` | 是 |
| 10m 风 U/V | `10m_u_component_of_wind` / `10m_v_component_of_wind` | 是 |
| 地面气压 | `surface_pressure` | 是 |
| 相对湿度 | — | **不存在** |
| 总云量 | — | **不存在** |

`10m_u_component_of_wind` 在 ERA5-Land 与单层均正确；`u_component_of_wind_10m` 在任何数据集都不存在。`relative_humidity` 仅存在于气压层，`total_cloud_cover` 仅存在于单层。ERA5-Land 为陆面掩膜产品，海洋格点缺失。

气压层：`geopotential`（**不是** `geopotential_height`）、`temperature`、`u_component_of_wind`、`v_component_of_wind`、`relative_humidity`、`specific_humidity`、`vertical_velocity`。

### A.3 月均值

- `product_type` 必填，取值 `monthly_averaged_reanalysis`（月整体）或 `monthly_averaged_reanalysis_by_hour_of_day`。
- 变量名**无前缀**，`2m_temperature` 之类即正确。
- `time` 仅接受 `"00:00"`（对 `monthly_averaged_reanalysis`）。
- 不允许 `day` 键。

### A.4 凭证与许可证

- `~/.cdsapirc` 仍为 `url` + `key`，**已无 UID**；`cdsapi` 亦接受 `CDSAPI_URL` / `CDSAPI_KEY` 环境变量与 `CDSAPI_RC` 路径。
- 当前 URL：`https://cds.climate.copernicus.eu/api`；`/api/v2` 已于 2024-09-26 停用，`cds-beta` 主机已于 2025-01 停用。
- 建议 `cdsapi>=0.7.7`。
- **数据集许可必须由账号本人在该数据集下载页手工接受，API 无法代办**；未接受时报 `Client has not agreed to the required terms and conditions`。
- 原始 HTTP 认证使用 `PRIVATE-TOKEN` 头，而非 `Authorization`。

### A.5 队列与限额

| 数据集 | 单请求字段数上限 |
|---|---|
| ERA5-Land 小时 | 12,000 |
| ERA5-Land 月均值 | 100,000 |
| ERA5 单层 | 120,000 |
| ERA5 气压层 | 120,000 |

超限不报错而是排队。并发排队任务数有上限（历史上 32，近期约 10–20），超限时返回 `Number of API queued requests for this dataset is temporarily limited`。2025-04 起 netCDF 请求另有成本限额，超限返回 403 `cost limits exceeded`。相同请求命中缓存可能返回不完整的 ERA5T 数据。

---

## 附录 B · 实施顺序建议

本设计覆盖 4 项需求与 1 项连带修复，规模不适合作单一批次实施。下面的 5 个批次**各自可独立验证、可独立回滚**，每一批完成后主干都应保持可用；实施计划按此分解。

按依赖关系与风险排序：

0. **核实 AQI 断点数值**并确定 `AQI_STANDARD_LABEL`（阻塞第 5 步）。
1. `modules/aqi.py` + `config` 修复 + `tests/test_aqi.py` + 三处调用点收敛（纯逻辑，风险最低，可先固化）。
2. `modules/era5_guide.py` + catalogue 修正 + ZIP 生成 + `tests/test_era5_guide.py` + `data_loader` 改写。
3. `modules/manual.py` + `docs/用户使用手册.md` + 侧边栏入口 + `tests/test_manual.py`（手册中读图与 ERA5 两章依赖第 2、4 步的最终形态，可先写骨架并在后续步骤回填）。
4. `modules/chart_reader.py` + `ai_narrative.py` 改造 + `app.py` Tab 改造 + 删除清单 + `tests/test_chart_reader.py`。
5. 横切收尾：`requirements.txt`、`secrets.toml.example`、`README.md`、`docs/同类项目核心介绍.md`、CI 工作流、`APP_VERSION`、删除旧 HTML、全量回归与启动冒烟。

第 4 步是唯一会改变既有导航与页面结构的步骤，安排在手册与 ERA5 之后，便于在其之前保持主干随时可用。

---

## 附录 C · 版本号最终决议（2026-09-13 补充）

本设计从立项到落地一直按「2.3.0 → 2.4.0」推进，正文、第 1–5 批计划与 `test_release_surface` 的目标断言都写作 2.4.0。全部批次实施完毕后，用户决议**最终发布号取 `2.3.1`**。

已落地的三处改动：`config.APP_VERSION = "2.3.1"`、`tests/test_release_surface.py::test_version_bumped` 的断言、`README.md` 的「当前版本」注记。

保留未改的：正文与第 1–5 批计划中的 2.4.0 字样作为当时的决策轨迹留档，不回溯改写。凡涉及当前版本的事实判断一律以 `config.APP_VERSION` 为准，任何文档与正文都不硬编码版本号。

**一处需要知情的取舍**：本次含 Tab 3 语义变更（智能分析 → 读图解析）与 AQI 数值口径变更，按语义化版本惯例本应升次版本号（2.4.0）。选 2.3.1 意味着把「线上版本辨识」这一用途放在「变更量级表达」之前，代价是单看号段会低估本次变更幅度。若日后需要对变更幅度做诚实表达，把 `APP_VERSION` 与上述两处注记改回 2.4.0 即可，代码与测试不依赖具体号值。
