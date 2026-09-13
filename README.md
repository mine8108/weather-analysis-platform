# 气象数据交互分析平台 · Weather Data Analysis Platform

一个基于 **Python + Streamlit** 的可交互式气象数据分析与预警软件。用户可以导入气温、气压、湿度、风、云、能见度、天气现象等观测数据，平台自动完成**数据可视化**、**国家预警标准匹配**、**多要素耦合分析**，并生成**公众出行 / 农业生产建议**与可导出的分析报告。

> 全部依赖均为开源库，外部数据接口（Open-Meteo 气象 / 空气质量 / GFS 预报）**无需任何 API Key**。进入主程序需先登录，因此还需配置 Supabase 密钥（见下方「登录与多用户私有数据」）。

---

## ✨ 核心功能

| 模块 | 功能 |
|------|------|
| **数据导入** | 支持 CSV / Excel 上传、网页手动逐条录入、Open-Meteo API 按经纬度+时间自动拉取；智能列名识别；标准模板下载；API 区含 **ERA5（CDS）变量 catalogue 与脚本包下载**（4 个产品 / 8 个变量分组 / 5 组常用预设 / 提交前字段数预警） |
| **数据质控** | 内置于「数据导入」向导第 2 步，导入后默认展示质量报告：物理量范围校验（温度/气压/湿度/风速等）、相邻时次突跳检测、缺失率统计、百分制数据质量评分 |
| **可视化分析** | 温/压/湿/风多要素综合看板、风向风速玫瑰图、要素关系散点矩阵、统计摘要；**要素分布直方图（默认含降水量，可叠加多要素对比）** |
| **AI 读图解析** | 上传气象图（天气图 / 卫星云图 / 雷达回波 / 模式形势图），由多模态模型输出**六段式结构化解读**（图面要素 → 分布特征 → 关键数值 → 趋势演变 → 风险结论）；图片四重上限（3 张 / 原始 20MB / 提交 5MB / 合计 12MB）；**不依赖已导入数据**；可导出 Word（含原图）与 Markdown。调用失败不做文本降级 |
| **报文解码** | 粘贴 METAR / SYNOP 标准报文，自动解析为结构化数据 |
| **报告导出** | 处理后数据与 GFS 预报数据导出 CSV；一键生成 Word 分析报告（专业版为表格化排版、通俗版为叙述式），报告内不含图片 |
| **数值预报 (GFS)** | 接入 Open-Meteo **GFS 数值预报（免注册，最长 16 天）**：气温/体感温度/降水时间序列、空气质量预报（AQI 六级分档，口径见 `AQI_STANDARD_LABEL`）、未来 72 小时高温预报面板（含 35/37/40℃ 国家阈值线）、风玫瑰预报、预报验证（GFS vs 实况） |
| **明暗主题** | 浅色 / 暗色一键切换（登录用户偏好云端同步，未登录时本地保存）；全站配色由 `design_tokens` 单一真相源驱动，图表随主题重绘，明暗切换不重载数据 |
| **用户手册** | 侧边栏「📖 用户使用手册」入口，**14 章**详细说明，不占用 Tab 编号；正文唯一真相源为 `docs/用户使用手册.md`，应用内阅读并可现场导出独立 HTML |

---

## 🛠 技术栈

- **Web 框架**：[Streamlit](https://streamlit.io/) 1.59
- **数据处理**：pandas 3.0 / numpy 2.5
- **可视化**：Plotly 6.8（交互式，支持导出 HTML）
- **报告生成**：python-docx 1.2（Word）
- **登录与存储**：Supabase（邮箱密码登录 + RLS 行级安全）
- **外部数据**：Open-Meteo Archive / Forecast / Air-Quality API（均无需密钥）
- **部署目标**：Streamlit Community Cloud / 任意 Python 主机

---

## 📁 项目结构

```
weather_app/
├── app.py                      # Streamlit 主入口（6 个 Tab）
├── auth.py                     # Supabase 邮箱密码登录 / 邀请码注册
├── db.py                       # 用户数据集云端持久化（按 user_id 隔离）
├── utils.py                    # DataFrame 指纹、API 重试、预加载缓存
├── config.py                   # 国家预警阈值、字段映射、风力等级表、防御指南
├── requirements.txt            # 运行依赖（supabase 未锁版本，其余固定）
├── requirements-dev.txt        # 开发依赖（pytest，不参与线上部署）
├── runtime.txt                 # Streamlit Cloud Python 版本声明
├── LICENSE                     # MIT
├── SECURITY.md                 # 安全说明
├── supabase/
│   └── schema.sql              # datasets 表建表脚本 + RLS 策略
├── .streamlit/
│   ├── config.toml             # 部署配置（headless / 主题）
│   └── secrets.toml.example    # 密钥模板（复制为 secrets.toml 后填写）
├── templates/
│   └── data_template.csv       # 标准数据模板（下载显示名仍为「气象数据模板.csv」）
├── docs/
│   └── 用户使用手册.md          # 手册唯一真相源（应用内阅读 + 现场导出 HTML）
├── tests/                      # 自测脚本（无 pytest 亦可直接运行）
│   ├── conftest.py
│   ├── test_analyzer.py        # 预警检测与耦合分析 92 条
│   ├── test_aqi.py             # AQI 断点表结构 / 分指数 / 综合指数 35 条
│   ├── test_data_quality.py    # 数据质控 9 条
│   ├── test_auth_session.py    # 登录会话 8 条
│   ├── test_codec.py           # 报文解码回归
│   ├── test_era5_guide.py      # ERA5 catalogue 与 payload 26 条
│   ├── test_era5_script_pack.py # ERA5 脚本包 ZIP 与换算函数 29 条
│   ├── test_manual.py          # 手册结构与内容契约 24 条
│   ├── test_chart_reader.py    # 读图管线 / 编码策略 / prompt / 接线契约 36 条
│   ├── test_ai_narrative.py    # 多模态请求体与报告导出 17 条
│   ├── test_release_surface.py # 版本 / 依赖 / Secrets / CI 契约 18 条
│   ├── test_weather_wall.py    # 天气墙（依赖 pytest；单跑需登录态）
│   └── test_smoke.py           # 导入冒烟检查
├── 示例数据/
│   ├── 示例气象数据.csv          # 可直接测试的演示数据
│   └── generate_demo.py        # 演示数据生成脚本
└── modules/
    ├── __init__.py
    ├── data_loader.py          # CSV/Excel/手动/API 导入
    ├── data_quality.py         # 数据质量控制与评分
    ├── visualizer.py           # 可视化引擎（7 个子面板）
    ├── analyzer.py             # 国标事件检测 + 耦合分析 + 建议生成（纯逻辑，不渲染页面）
    ├── aqi.py                  # AQI 分指数与综合指数唯一实现
    ├── codec.py                # SYNOP/METAR 解码
    ├── nwp_forecast.py         # GFS 数值预报接入 + 时间图/空气质量/风玫瑰/预报验证
    ├── verify.py               # GFS 预报 vs 实况 的定量验证
    ├── reporter.py             # Word/CSV 报告导出
    ├── chart_reader.py         # AI 读图解析（图片校验压缩 + 读图 prompt + 页面）
    ├── ai_narrative.py         # 多模态调用 + 报告排版与 docx/md 导出
    ├── era5_guide.py           # ERA5 变量 catalogue / payload 构建 / 规模预警 / 引导页
    ├── era5_script_pack.py     # ERA5 脚本包六个文件与 ZIP 打包
    ├── manual.py               # 用户手册加载 / 章节解析 / 应用内渲染 / HTML 导出
    ├── weather_wall.py         # 封面页天气墙（城市天气卡片）
    ├── theme_aether.py         # 主题注入与明暗切换（会话级，无需重载）
    ├── design_tokens.py        # 配色 token 单一真相源（浅色/暗色双套，含对比度校验）
    ├── theme_css.py            # 全站主题样式表（暗色覆盖层按 html[data-dsh-theme] 作用域）
    ├── chart_theme.py          # Plotly 主题模板（图表配色随明暗同步）
    ├── city_prefs.py           # 天气墙城市列表持久化
    ├── geocode.py              # 城市名 ↔ 经纬度双向解析
    └── geolocate.py            # 浏览器定位组件封装
├── research/                   # 审计工具与核查记录（不参与线上部署）
│   ├── darkmode_contrast_probe.py  # WCAG 2.1 AA 对比度审计（双主题）
│   ├── check_py_vars.py            # CSS 变量引用完整性检查
│   ├── check_plotly_cssvar.py      # 图表误用 CSS var() 检查
│   ├── check_chart_colors.py       # 图表颜色实值检查（防 token 名泄漏进 Plotly）
│   ├── era5_variable_enums_2026-09-13.json  # CDS constraints 接口实测的变量枚举快照
│   └── 内部不一致清单-2026-09-13.md          # 跨文件不一致审计与处置归属
```

---

## 🚀 本地运行

要求 Python ≥ 3.11（推荐 3.12）。

```bash
# 1. 进入项目目录
cd weather_app

# 2. 安装依赖（建议使用虚拟环境）
pip install -r requirements.txt

# 3. 启动应用
streamlit run app.py
```

启动后终端会显示本地地址（默认 `http://localhost:8501`），浏览器打开即可使用。

> ⚠️ 注意：`pip install` 与 `streamlit run` 是**终端命令**，请在系统命令行 / Anaconda Prompt 中执行，不要写进 `.py` 文件用 IDE 运行。

**最短上手路径**：Tab1 数据导入（上传 `示例数据/示例气象数据.csv`，在第 2 步查看质量报告）→ Tab2 可视化分析 → **Tab4 报告导出**生成 Word 报告。Tab3 的「AI 读图解析」**不依赖已导入数据**，可随时上传一张天气图体验。完整操作见侧边栏「📖 用户使用手册」或 `docs/用户使用手册.md`。

---

## 🧪 测试

`tests/` 下为自测脚本。其中九个可直接运行，无需安装 pytest（CI 的门禁就是用这种方式跑的）：

```bash
python -B tests/test_analyzer.py         # 预警检测与耦合分析 92 条
python -B tests/test_data_quality.py     # 数据质控 9 条
python -B tests/test_auth_session.py     # 登录会话 8 条
python -B tests/test_codec.py            # 报文解码
python -B tests/test_aqi.py              # AQI 断点表 / 分指数 / 综合指数 35 条
python -B tests/test_era5_guide.py       # ERA5 catalogue 与 payload 26 条
python -B tests/test_manual.py           # 手册结构与内容契约 24 条
python -B tests/test_chart_reader.py     # 读图管线与编码策略 36 条
python -B tests/test_release_surface.py  # 版本/依赖/Secrets/CI 契约 18 条
```

其余用例用 pytest 运行全部（当前共 **364** 项；`tests/test_weather_wall.py` 依赖 pytest，且其中的 AppTest 用例单跑需要登录态）：

```bash
pip install -r requirements-dev.txt
pytest tests -q
```

改配色或图表样式后，另跑 `research/` 下的四项审计，全部以退出码 0 为通过：

```bash
python -B research/darkmode_contrast_probe.py   # 双主题 WCAG 对比度，须 0 项不达标
python -B research/check_py_vars.py             # CSS 变量引用是否有未定义项
python -B research/check_plotly_cssvar.py       # 图表是否误用了浏览器才认的 var()
python -B research/check_chart_colors.py        # 图表颜色是否为 Plotly 认可的实值
```

> 前三项是静态检查，第四项会真实调用图表函数并检查 figure 内的颜色属性，用于拦截「token 名泄漏进 Plotly」这类只在运行时才暴露的问题。

上游数据源会变，所以另有一项**联网**核对，建议每季度跑一次（不进 CI，避免上游故障导致流水线变红）：

```bash
python -B research/check_era5_variables.py --cache .cache-era5   # ERA5 变量名与 CDS 线上枚举
```

> 它通过 CDS 公开的 process 描述接口核对两件事：本地展示的变量名是否都真实存在（防上游改名）、标注为「不支持」的变量是否确实不在枚举中（防误导用户）。需要 CDS 账号与 API Key 才能下载数据，但这项核对**不需要任何凭据**。退出码 0 一致、1 不一致、2 联网失败（2 不等于通过）。

**发布后请肉眼核对一次线上版本号。** `git push` 成功、远端 `main` 已更新，**不等于**
Streamlit Cloud 已经重建容器：v2.3.0 发布时就遇到过推送十余分钟后线上仍返回旧版本号、
容器启动时间停在推送之前的情况，而这一状态是静默的，不主动核对就会误以为线上已是新版。
（当前版本：**2.3.2**。）

做法很简单——侧边栏页脚始终显示 `© 气象数据交互分析平台 <版本号>`，与 `config.py` 的
`APP_VERSION` 对一眼即可。若不一致，去 Streamlit Cloud 面板对该应用执行 **Reboot app**
（会重新 clone 分支并重建容器）。

---

## 📊 数据格式

标准字段（列名不区分大小写，支持中英文别名自动识别）：

| 字段 | 含义 | 单位 |
|------|------|------|
| `timestamp` | 观测时间 | YYYY-MM-DD HH:MM[:SS] |
| `temperature` | 气温 | ℃ |
| `pressure` | 本站气压 | hPa |
| `humidity` | 相对湿度 | % |
| `wind_speed` | 风速 | m/s |
| `wind_direction` | 风向 | °（0–360） |
| `cloud_cover` | 总云量 | 成（0–10） |
| `visibility` | 能见度 | km |
| `precipitation` | 降水量 | mm |
| `weather_code` | WMO 天气现象代码 | 整数 |
| `station_id` | 站点编号 | 字符串 |

可直接下载 `templates/data_template.csv` 作为填写模板。

---

## 🌐 部署到 Streamlit Community Cloud（免费）

本仓库已按 Streamlit Cloud 规范准备好（`app.py` 在根目录、`requirements.txt`、`runtime.txt`、`.streamlit/config.toml` 齐全）。

1. 将本仓库推送到你的 GitHub 账号（见下方「推送代码」）。
2. 打开 [share.streamlit.io](https://share.streamlit.io)，使用 GitHub 登录。
3. 点击 **New app** → 选择本仓库 → 分支 `main` → 主文件填写 `app.py`。
4. 点击 **Deploy**，约 1–2 分钟后获得公开访问链接。

所有依赖联网的功能（Open-Meteo 气象 / 空气质量 / GFS 预报拉取）在云端均可正常使用。**但登录已是进入主程序的前置条件**：未配置 Supabase 密钥时，`app.py` 会停在登录页并提示如何写入 `.streamlit/secrets.toml`（不会崩溃），因此线上部署必须配置 4 项密钥——`SUPABASE_URL`、`SUPABASE_ANON_KEY`、`SUPABASE_SERVICE_ROLE_KEY`、`ADMIN_PASSWORD`（见下方章节）。

可选的 AI 配置分两组：**读图解析**需要 `LLM_VISION_MODEL`（必需，须为具备图像输入能力的模型）与可选的 `LLM_VISION_API_KEY` / `LLM_VISION_BASE_URL`，缺失时读图页给出配置指引且不显示生成按钮；`LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` 为保留的文本模型配置，当前没有生产调用者，缺失不影响任何功能。

---

## 🔔 预警标准

预警阈值体系依据**中国气象局《气象灾害预警信号发布与传播办法》（第 16 号令）**的国家标准实现，覆盖高温、寒潮、大风、大雾、暴雨、霜冻、雷电、霾八类灾害的蓝/黄/橙/红四级。侧边栏「自定义检测阈值」面板提供**七组**输入：高温、大风、大雾、暴雨、霜冻、霾、雷电（雷电为时间窗口而非数值阈值）。默认值即国家标准值，修改后点「[OK] 应用自定义阈值」生效，仅影响当前会话；`analyzer.set_custom_thresholds()` 亦可在代码侧覆盖。

空气质量相关有两套口径，页面上分别标注：**AQI 分指数**用 `config.AQI_STANDARD_LABEL`（当前为 HJ 633-2012，因 2026 版表 1 的断点数值无法公开核实），**浓度达标限值**用 `config.LIMIT_STANDARD_LABEL`。两者不是同一张表，不要把 AQI 等级与浓度达标混读。

---

## 📄 许可证

[MIT](LICENSE) © 2026 郑昊 (mine8108)

---

## 🔐 登录与多用户私有数据（Supabase）

平台已内置基于 Supabase 的邮箱密码登录，每位用户的数据按账号**私有隔离**。

### 1. 创建 Supabase 项目
- 注册 [supabase.com](https://supabase.com) → New Project。
- Authentication → Providers → Email：
  - 关闭 `Confirm email` 以便本地测试直接登录（生产可开启）。
  - **关闭 `Allow new users to sign up`（允许公开注册）**：本平台采用「邀请码授权注册」，注册账号必须经管理员发放的邀请码、由服务端建账号，因此必须关闭公开注册。
- 复制 Project URL 与 `anon public` 密钥（Settings → API）。
- 复制 `service_role` 密钥（Settings → API，标记为 secret，**切勿在前端暴露**），用于服务端管理操作。

### 2. 建表与行级安全
- Supabase → SQL Editor → 新建查询 → 粘贴 `supabase/schema.sql` 并执行。
- 该脚本创建 `datasets` 表并启用 RLS，保证用户只能读写自己的数据。

### 3. 配置密钥
- 本地：复制 `.streamlit/secrets.toml.example` 为 `.streamlit/secrets.toml` 并填入。
- Streamlit Cloud：Settings → Secrets 粘贴：
  ```
  SUPABASE_URL = "https://xxxx.supabase.co"
  SUPABASE_ANON_KEY = "eyJ..."              # anon public 密钥（可前端暴露）
  SUPABASE_SERVICE_ROLE_KEY = "eyJ..."     # service_role 密钥（仅服务端，严禁泄露）
  ADMIN_PASSWORD = "你的管理员密码"          # 管理员面板解锁密码
  ```
  可选项见 `.streamlit/secrets.toml.example`。AI 相关分两组：读图解析用 `LLM_VISION_MODEL`（必需）/ `LLM_VISION_API_KEY` / `LLM_VISION_BASE_URL`；文本模型 `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` 为保留项，当前无生产调用者。**读图解析的模型名不会回落到 `LLM_MODEL`**——默认文本模型没有视觉能力，回落只会造成「配置了却一直失败」。

### 4. 部署
- `requirements.txt` 已加入 `supabase`，推送至 GitHub 后 Streamlit Cloud 自动安装。
- 未配置密钥时页面会提示如何设置，不会崩溃。

### 5. 邀请码注册与存储配额
- **注册授权**：公开注册已关闭。管理员在登录页底部「🔧 管理员入口」输入 `ADMIN_PASSWORD` 解锁后，可生成邀请码（每码一次性）发给用户；用户注册时填邀请码 → 服务端校验并建账号 → 自动登录。
- **存储配额**：每位用户默认 10 MB（数据以 CSV 文本存于 `datasets.csv_text`）。保存数据集前按 `OCTET_LENGTH(csv_text)` 累计校验，超额拒绝并提示。管理员可在面板内按用户调整配额（MB）。
- 侧边栏实时显示「☁️ 云存储 已用 / 配额 MB」进度条。

### 使用说明
- 未登录只显示登录/注册页；登录后进入主程序。
- 导入数据后点「💾 保存到云端」，数据存到本人账号下。
- 重新登录会自动载入最近一次保存的数据集；侧边栏「📂 我的数据集」可切换/删除。
- 退出登录会清空当前会话的工作数据，避免串号。
