# 气象数据交互分析平台 · Weather Data Analysis Platform

一个基于 **Python + Streamlit** 的可交互式气象数据分析与预警软件。用户可以导入气温、气压、湿度、风、云、能见度、天气现象等观测数据，平台自动完成**数据可视化**、**国家预警标准匹配**、**多要素耦合分析**，并生成**公众出行 / 农业生产建议**与可导出的分析报告。

> 全部依赖均为开源库，外部数据接口（Open-Meteo 历史气象、ERA5 气候态）**无需任何 API Key**，开箱即用。

---

## ✨ 核心功能

| 模块 | 功能 |
|------|------|
| **数据导入** | 支持 CSV / Excel 上传、网页手动逐条录入、Open-Meteo API 按经纬度+时间自动拉取；智能列名识别；标准模板下载 |
| **数据质控** | 物理量范围校验（温度/气压/湿度/风速）、相邻时次突跳检测、缺失率统计、百分制数据质量评分 |
| **可视化分析** | 温/压/湿/风多要素综合看板、风向风速玫瑰图、要素关系散点矩阵、统计摘要；**要素分布直方图（默认含降水量，可叠加多要素对比）** |
| **智能分析与建议** | 覆盖高温、寒潮、大风、大雾、暴雨、霜冻、雷电、霾共 **8 类国家预警标准**；热应激、降水可能性、风寒效应等耦合风险；自动生成公众出行与农业生产建议 |
| **气候态参照** | 拉取近 5 年同期 ERA5 气候态均值，计算气温/降水/风速距平 |
| **报文解码** | 粘贴 METAR / SYNOP 标准报文，自动解析为结构化数据 |
| **报告导出** | 处理后数据导出 CSV、一键生成 Word 分析报告、关键图表导出 |
| **数值预报 (GFS)** | 接入 Open-Meteo **GFS 数值预报（免注册，最长 16 天）**：气温/体感温度/降水时间序列、未来 72 小时高温预报面板（含 35/37/40℃ 国家阈值线）、逐日降水预报；并可抓取目标点周边网格生成**空间预报场热力图**（时间图 + 空间图双视图） |

---

## 🛠 技术栈

- **Web 框架**：[Streamlit](https://streamlit.io/) 1.59
- **数据处理**：pandas 3.0 / numpy 2.5
- **可视化**：Plotly 6.8（交互式）、Matplotlib 3.11（静态导出）
- **报告生成**：python-docx 1.2（Word）
- **外部数据**：Open-Meteo Archive API、ERA5 气候态（均无需密钥）
- **部署目标**：Streamlit Community Cloud / 任意 Python 主机

---

## 📁 项目结构

```
weather_app/
├── app.py                      # Streamlit 主入口（8 个 Tab）
├── config.py                   # 国家预警阈值、字段映射、风力等级表、防御指南
├── requirements.txt            # 依赖（已锁定版本）
├── runtime.txt                 # Streamlit Cloud Python 版本声明
├── LICENSE                     # MIT
├── .streamlit/
│   └── config.toml             # 部署配置（headless / 主题）
├── templates/
│   └── data_template.csv       # 标准数据模板（下载显示名仍为「气象数据模板.csv」）
├── 示例数据/
│   ├── 示例气象数据.csv          # 可直接测试的演示数据
│   └── generate_demo.py        # 演示数据生成脚本
├── 用户使用手册.html            # 图文操作手册
└── modules/
    ├── __init__.py
    ├── data_loader.py          # CSV/Excel/手动/API 导入
    ├── data_quality.py         # 数据质量控制与评分
    ├── visualizer.py           # 可视化引擎
    ├── analyzer.py             # 预警检测 + 建议生成
    ├── climate_ref.py          # ERA5 气候态参照
    ├── codec.py                # SYNOP/METAR 解码
    ├── nwp_forecast.py         # GFS 数值预报接入 + 时间图/空间图渲染
    └── reporter.py             # Word/CSV 报告导出
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

**最短上手路径**：Tab1 上传 `示例数据/示例气象数据.csv` → Tab4 查看预警与建议 → Tab7 导出 Word 报告。更详细的操作见 `用户使用手册.html`。

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

所有功能（含 API 拉取、气候态参照）在云端均可正常使用，无需配置任何密钥。

---

## 🔔 预警标准

预警阈值体系依据**中国气象局《气象灾害预警信号发布与传播办法》（第 16 号令）**的国家标准实现，覆盖高温、寒潮、大风、大雾、暴雨、霜冻、雷电、霾八类灾害的蓝/黄/橙/红四级。用户亦可在应用侧边栏自定义调整阈值（留空则采用国家标准）。

---

## 📄 许可证

[MIT](LICENSE) © 2026 郑昊 (mine8108)
