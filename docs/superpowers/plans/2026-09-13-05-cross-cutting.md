# 横切收尾与一致性修复 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成发布前的横切收尾：版本号、依赖声明、Secrets 模板、CI 门禁、README 与文档同步、删除旧 HTML，并修掉 `research/内部不一致清单-2026-09-13.md` 中归属本批次的四项「页面对外说法与实现不符」。

**Architecture:** 不改动任何业务逻辑；本批次只做声明、文档与展示文案的对齐，以及一处常量抽取（浓度限值标准标签）。所有改动都以测试或源码断言锁定，避免文档再次漂移。

**Tech Stack:** 不新增依赖；`requirements.txt` 只把已有的传递依赖显式化

**Spec:** `docs/superpowers/specs/2026-09-13-chart-reader-and-era5-delivery-design.md` 第 10 节影响面清单
**前置：** 批次 1–4 已完成（338 项测试全绿）。本批次是最后一个批次。

## Global Constraints

- 不修改任何业务逻辑与阈值；不新增第三方依赖。
- 版本号从 `2.3.0` 升到 `2.4.0`，只改 `config.APP_VERSION` 一处。
- 用户可见文案中**不得**出现无法核实年份的标准名（`GB 3095-2026`、`HJ 633-2026`）。AQI 分指数口径继续渲染 `AQI_STANDARD_LABEL`。
- 删除根目录 `用户使用手册.html` 前必须确认无任何代码引用它。
- `docs/用户使用手册.md` 里的版本号由导出注入，不得硬编码。
- 提交前必须跑通四个 CI 门禁脚本与 `python -B -m pytest tests -q`。

---

### Task 1: 版本号、依赖声明、Secrets 模板、CI 门禁

**Files:**
- Modify: `config.py`（`APP_VERSION`）
- Modify: `requirements.txt`
- Modify: `.streamlit/secrets.toml.example`
- Modify: `.github/workflows/tests.yml`
- Test: `tests/test_release_surface.py`（新增）

**Interfaces:**
- Produces: `tests/test_release_surface.py`（发布面契约测试）

- [ ] **Step 1: 写失败测试（新建 `tests/test_release_surface.py`）**

```python
"""发布面契约测试：版本号、依赖声明、Secrets 模板、CI 门禁、旧文件清理。

这些是「容易漂移但不该漂移」的声明类事实，集中锁定。

无 pytest 时可直接运行（`python -B tests/test_release_surface.py`）。
"""
import io
import os
import sys

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)


def _read(rel):
    with io.open(os.path.join(_APP_DIR, rel), encoding="utf-8") as handle:
        return handle.read()


def test_version_bumped():
    from config import APP_VERSION
    assert APP_VERSION == "2.4.0", APP_VERSION


def test_requirements_declare_image_and_markdown_deps():
    """Pillow 与 markdown-it-py 此前只是 streamlit 的传递依赖，现须显式声明。"""
    text = _read("requirements.txt")
    assert "Pillow" in text
    assert "markdown-it-py" in text


def test_secrets_example_lists_vision_keys():
    text = _read(".streamlit/secrets.toml.example")
    for key in ("LLM_VISION_MODEL", "LLM_VISION_API_KEY", "LLM_VISION_BASE_URL"):
        assert key in text, key
    assert "不会回落到 LLM_MODEL" in text or "不回落到" in text


def test_ci_runs_all_gate_scripts():
    text = _read(".github/workflows/tests.yml")
    for script in ("test_analyzer.py", "test_data_quality.py",
                   "test_auth_session.py", "test_codec.py",
                   "test_aqi.py", "test_era5_guide.py", "test_manual.py",
                   "test_chart_reader.py"):
        assert script in text, script


def test_legacy_html_removed():
    """旧的手册 HTML 已被 docs/用户使用手册.md 取代。"""
    assert not os.path.exists(os.path.join(_APP_DIR, "用户使用手册.html"))


def test_no_unverifiable_standard_years_in_user_facing_text():
    """用户可见文案不得声称无法核实的标准年份。"""
    for rel in ("app.py", "modules/visualizer.py", "modules/analyzer.py",
                "modules/nwp_forecast.py", "modules/reporter.py"):
        text = _read(rel)
        for bad in ("GB 3095-2026", "HJ 633-2026"):
            assert bad not in text, "%s 含 %s" % (rel, bad)
```

- [ ] **Step 2: 运行确认失败**

Run: `python -B -m pytest tests/test_release_surface.py -q`
Expected: FAIL（版本号仍 2.3.0、依赖未声明、CI 未含新脚本、旧 HTML 仍在、多处 2026 字样）

- [ ] **Step 3: 逐项修正**

- `config.py`：`APP_VERSION = "2.4.0"`，并把版本注释改为本次改造摘要。
- `requirements.txt`：追加 `Pillow>=10.0` 与 `markdown-it-py>=3.0`，并加注释说明二者此前是 streamlit 的传递依赖、现显式声明以去掉传递依赖假设。
- `.streamlit/secrets.toml.example`：在 LLM 段落之后追加三个视觉键，并写明「`LLM_VISION_MODEL` 必需、不会回落到 `LLM_MODEL`」。
- `.github/workflows/tests.yml`：在既有四个门禁步骤之后追加 `test_aqi.py`、`test_era5_guide.py`、`test_manual.py`、`test_chart_reader.py` 四个步骤（同样用 `python -B` 直跑）。

- [ ] **Step 4: 提交**

```bash
git add config.py requirements.txt .streamlit/secrets.toml.example .github/workflows/tests.yml tests/test_release_surface.py
git commit -m "chore(release): 版本 2.4.0、显式声明 Pillow/markdown-it-py、CI 补全门禁"
```

---

### Task 2: README 全量同步

**Files:**
- Modify: `README.md`

**必须修正的失实之处（逐条对代码核对过）：**

| 位置 | 现状 | 改为 |
|---|---|---|
| 功能表「智能分析与建议」行 | 描述 8 类预警卡片与耦合建议 | **AI 读图解析**：上传气象图（天气图/卫星云图/雷达回波/模式形势图），多模态模型输出六段式解读，可导出 docx（含原图）与 md；图片四重上限；不依赖已导入数据 |
| 项目结构树 | 缺 4 个新模块与新测试 | 补 `manual.py`、`chart_reader.py`、`era5_guide.py`、`era5_script_pack.py`、`aqi.py` 与对应测试文件；`ai_narrative.py` 注释改为「多模态读图调用 + 报告排版与导出」 |
| 结构树末行 | `用户使用手册.html` | 改为 `docs/用户使用手册.md`（应用内手册唯一真相源） |
| 最短上手路径 | 「Tab4 查看预警与建议 → Tab5 导出」 | Tab 序号已变：Tab1 导入 → Tab2 可视化 → Tab3 AI 读图解析 → **Tab4 报告导出**；并把手册链接指向侧边栏入口与 `docs/用户使用手册.md` |
| 测试章节 | 三个可直跑脚本、`test_analyzer.py 91 条` | 四个门禁脚本可直跑（多出 `test_codec.py`）；`test_analyzer.py` 为 **92 条**；补一句「其余为 pytest 用例，共 338 项」 |
| 预警标准章节 | 「侧边栏自定义检测阈值面板当前提供**高温、大风、大雾**三类输入框；其余…界面暂未提供」 | **已提供七组**：高温、大风、大雾、暴雨、霜冻、霾、雷电（含各组的等级与默认值）；说明默认值即国家标准值 |
| 部署章节 | 「另有 `LLM_API_KEY` 等 3 项为可选，用于 AI 预警叙事」 | 区分两组：`LLM_*` 文本模型（已无生产调用者，列为保留项）与 `LLM_VISION_*` 视觉模型（读图解析必需，缺失时页面给出配置指引） |
| Secrets 章节 | 仅列 LLM 三项 | 追加三个视觉键的说明 |
| 版本核对段落 | 「v2.3.0 发布时…」 | 保留该历史案例，另注明当前版本 2.4.0 |

- [ ] **Step 1: 按上表逐项改写 `README.md`**
- [ ] **Step 2: 自查**：README 中出现的每个模块名、Tab 名、测试文件名都能在仓库中找到；数字（92 条 / 338 项 / 6 个 Tab / 7 组阈值 / 8 类预警）与代码一致
- [ ] **Step 3: 提交**

```bash
git add README.md
git commit -m "docs(readme): 同步 2.4.0 的功能、结构、测试与阈值现状"
```

---

### Task 3: 一致性修复（清单中归属本批次的四项）

**Files:**
- Modify: `config.py`（新增浓度限值标准标签 + 两处注释）
- Modify: `modules/visualizer.py`（三处文案 + 风玫瑰半径说明）
- Modify: `modules/reporter.py`（技术说明三处失实）
- Modify: `docs/同类项目核心介绍.md`（陈旧 Tab 引用）
- Test: `tests/test_release_surface.py`（追加断言）

**Interfaces:**
- Produces: `config.LIMIT_STANDARD_LABEL: str`

- [ ] **Step 1: 追加失败测试**

```python
def test_concentration_limit_label_is_honest():
    """浓度达标限值的标准名不得声称无法核实的年份。"""
    from config import LIMIT_STANDARD_LABEL
    assert "2026" not in LIMIT_STANDARD_LABEL
    assert "GB 3095" in LIMIT_STANDARD_LABEL


def test_visualizer_renders_config_labels():
    text = _read("modules/visualizer.py")
    assert "LIMIT_STANDARD_LABEL" in text


def test_reporter_does_not_reference_missing_constants():
    """报告技术说明不得指向不存在的 config 常量。"""
    text = _read("modules/reporter.py")
    assert "WARN_RULES" not in text


def test_reporter_algorithm_notes_match_implementation():
    """技术说明里的算法描述必须与实现一致。"""
    text = _read("modules/reporter.py")
    assert "分 5 级" not in text          # 穿衣指数实现为 6 档
    assert "24h 降水概率" not in text      # 带伞依据 72h 累计降水 + 天气码


def test_no_stale_tab_reference_in_docs():
    for rel in ("docs/同类项目核心介绍.md", "README.md"):
        text = _read(rel)
        for bad in ("气候态", "再分析数据处理"):
            assert bad not in text, "%s 含 %s" % (rel, bad)
```

- [ ] **Step 2: 运行确认失败**

- [ ] **Step 3: 实施修复**

1. **`config.py` 新增标签**：

```python
# 大气污染物浓度达标限值所用的标准名。与 AQI 分指数（AQI_STANDARD_LABEL）是两张表：
# 本表用于判断浓度是否达标，AQI 表用于换算分指数。年份无从核实，故不标注年份。
LIMIT_STANDARD_LABEL = "GB 3095 二级标准限值"
```

并把第 571 行注释 `# 健康建议（按AQI等级，HJ 633-2026 新增敏感人群分类）` 改为
`# 健康建议（按 AQI 等级，口径见 AQI_STANDARD_LABEL）`；
第 581 行注释 `# 大气污染物标准浓度限值 (GB 3095-2026 二级标准 Phase2 终版, μg/m³)` 改为
`# 大气污染物标准浓度限值（口径见 LIMIT_STANDARD_LABEL，μg/m³）`。

2. **`visualizer.py`** 三处文案改为渲染常量：
   - 第 614 行 caption → `f"基于 {LIMIT_STANDARD_LABEL} 评估 PM2.5/PM10/SO₂/NOx 浓度趋势与达标率"`
   - 第 651 行 hovertemplate → `f"{LIMIT_STANDARD_LABEL}: {limit} {unit}"`
   - 第 656 行图标题 → `f"污染物浓度时间序列（虚线 = {LIMIT_STANDARD_LABEL}）"`
   并在文件顶部 config 导入中加入 `LIMIT_STANDARD_LABEL`。
   另在风玫瑰图处补一句 caption，说明**半径读数为样本出现频次**（与数值预报页按频率百分比绘制的玫瑰图口径不同）。

3. **`reporter.py`**：
   - 第 420 行 `"具体阈值参见 config.py 中 WARN_RULES 定义。"` → `"具体阈值见 config.py 中的各类预警阈值常量（HIGH_TEMP_WARNING / GALE_WARNING 等）。"`
   - 第 424 行 → `"穿衣指数：基于气温分 6 档（0 酷热 / 1 夏装 / 2 轻便 / 3 春秋装 / 4 初冬装 / 5 厚冬装）\n"`
   - 第 425 行 → `"带伞建议：基于未来 72 小时累计降水与天气码分 3 档（0 无需带伞 / 2 建议备伞 / 3 必带伞）\n"`
   - 第 428 行 → `"紫外线：由天气码近似分 4 档（弱/中/强/很强）\n"`

4. **`docs/同类项目核心介绍.md`** 第 68 行 `用户上传 + GFS 预报 API + 气候态` → `用户上传 + GFS 预报 API + ERA5 再分析（CDS 脚本包）`。

- [ ] **Step 4: 运行确认通过**
- [ ] **Step 5: 提交**

```bash
git add config.py modules/visualizer.py modules/reporter.py docs/同类项目核心介绍.md tests/test_release_surface.py
git commit -m "fix(docs): 修正浓度限值标准标注与报告技术说明的失实描述"
```

---

### Task 4: 删除旧 HTML、文档收尾与最终验收

**Files:**
- Delete: `用户使用手册.html`
- Modify: `research/内部不一致清单-2026-09-13.md`（标注处置结果）

- [ ] **Step 1: 确认无代码引用旧 HTML**

Run: 全仓 `*.py` 搜索 `用户使用手册.html`，期望 0 命中（README 与文档引用不属于代码引用，一并改掉）。

- [ ] **Step 2: 删除旧文件**

```bash
git rm 用户使用手册.html
```

- [ ] **Step 3: 更新内部不一致清单的处置状态**（把已修的 4 项标为「已修（批次 5）」）

- [ ] **Step 4: 最终全量验收**

Run:
```
python -B tests/test_auth_session.py
python -B tests/test_data_quality.py
python -B tests/test_analyzer.py
python -B tests/test_codec.py
python -B tests/test_aqi.py
python -B tests/test_era5_guide.py
python -B tests/test_manual.py
python -B tests/test_chart_reader.py
python -B -m pytest tests -q
python -c "import ast,io; ast.parse(io.open('app.py',encoding='utf-8').read())"
```
Expected: 八个门禁 exit=0；pytest 全量无失败；`app.py` 语法通过。

- [ ] **Step 5: 启动冒烟（AppTest）**

用临时入口脚本分别渲染：手册页、读图页、ERA5 引导区（在 `st.tabs` 上方直接调用 `render_era5_guide()`），断言三者 `at.exception` 均为 0。临时脚本放系统临时目录，不进仓库。

- [ ] **Step 6: 提交**

```bash
git add -A
git commit -m "chore(release): 删除旧手册 HTML，标注一致性清单处置结果"
```

---

## 完成标准

1. `config.APP_VERSION == "2.4.0"`；`requirements.txt` 显式声明 `Pillow` 与 `markdown-it-py`。
2. `.streamlit/secrets.toml.example` 含三个视觉键，并写明不回落 `LLM_MODEL`。
3. CI 工作流包含 8 个门禁脚本。
4. `用户使用手册.html` 已删除，全仓无代码引用；`docs/用户使用手册.md` 仍在并被应用内手册使用。
5. `app.py`、`visualizer.py`、`analyzer.py`、`nwp_forecast.py`、`reporter.py` 中不出现 `GB 3095-2026` 与 `HJ 633-2026`。
6. `config.LIMIT_STANDARD_LABEL` 存在且不含年份；`visualizer.py` 引用它。
7. `reporter.py` 不再引用不存在的 `WARN_RULES`；技术说明与实际算法一致。
8. README 中出现的模块名、Tab 名、测试文件名、数字全部与仓库一致。
9. 八个门禁脚本 exit=0；`pytest tests -q` 全绿；手册页、读图页、ERA5 引导区 AppTest 均 0 异常。
10. `research/内部不一致清单-2026-09-13.md` 中归属本批次的四项标注为已修。

## 风险与备注

- 本批次唯一有行为影响的是 `config.LIMIT_STANDARD_LABEL` 的文案变化：图表标题与 caption 会从「GB 3095-2026 二级日均限值」变为「GB 3095 二级标准限值」。这是刻意去掉无法核实的年份，阈值数值不变。
- `reporter.py` 技术说明属于**已生成报告**的内容，改动只影响之后生成的报告，不追溯历史文件。
- 删除 `用户使用手册.html` 是不可逆的仓库操作，但内容已在批次 3 迁入 `docs/用户使用手册.md` 并由 24 项测试锁定。

## 实施记录（2026-09-13）

### 抓到一个会让新 CI 门禁形同虚设的缺陷

在给 CI 追加四个新门禁步骤后，我核对了「直跑」这一执行方式本身：仓库既有的 4 个门禁脚本都有 `if __name__ == "__main__"` 运行器，而我在批次 1–4 新增的 6 个测试文件**一个都没有**。后果是 `python -B tests/test_aqi.py` 只会导入模块然后退出 0——**CI 里那四个新步骤会永远显示绿色却什么都不跑**。

修复：给 6 个文件补上仓库既有样式的运行器，并新增 `test_gate_scripts_have_standalone_runners` 把它们锁住。补完后逐个核对真实执行数：

| 脚本 | 直跑执行数 |
|---|---|
| `test_aqi.py` | 35 |
| `test_era5_guide.py` | 26 |
| `test_manual.py` | 24 |
| `test_chart_reader.py` | 28 |
| `test_ai_narrative.py` | 17 |
| `test_release_surface.py` | 14 |
| `test_era5_script_pack.py` | 29 |

### README 里还查出两处失实（均已修）

1. 预警标准章节称「侧边栏自定义检测阈值面板当前提供**高温、大风、大雾**三类输入框；其余…界面暂未提供」——实际早已是**七组**（高温/大风/大雾/暴雨/霜冻/霾/雷电）。这是最容易误导用户的类型：读者会以为要改代码才能调阈值。
2. 部署章节把三个 `LLM_*` 键说成「用于 AI 预警叙事」——该功能在批次 4 已被读图解析取代，文本模型当前没有生产调用者。

### 报告技术说明另发现一处失实

清单第 5 项列了穿衣/带伞/紫外线三处，实施时又查出**洗车指数**的依据也写错（原文「基于降水预报分 3 级」，实现是按未来 72 小时累计降水分 3 档），一并修正。

### 清单第 7 项有意不修

侧边栏两个天气墙控件顺序问题属纯可用性微调，收益低于误伤既有用户肌肉记忆的风险，已在清单中标注为「未修（有意保留）」而非遗漏。

### 验收证据（2026-09-13）

```
九个门禁脚本直跑（python -B）        → 全部 exit=0，ALL PASSED
python -B -m pytest tests -q         → 352 passed
AppTest 手册页 + 读图页 + ERA5 引导区 → 0 异常；3 个下拉 / 9 个多选 / 2 个下载按钮
AppTest 完整 app.py（临时假密钥）      → 0 异常、0 错误块，登录门禁正常渲染；临时密钥文件已删除
README 陈旧引用扫描                   → 气候态 / 再分析数据处理 / 用户使用手册.html / 智能分析与建议 / WARN_RULES / 2026 标准名 均为 0 命中
git status                           → 干净
```

**未覆盖的部分（如实说明）**：完整 `app.py` 的 AppTest 只跑到登录门禁——未登录时正确地停在登录页，因此那一次没有渲染 6 个 Tab 的内容。要渲染主程序需要真实 Supabase 会话，本地不具备。三个新增页面（手册、读图、ERA5 引导）已用各自渲染器做 AppTest 验证，其余 Tab 由 352 项测试与各模块的既有测试覆盖。
