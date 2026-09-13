# AI 读图解析转型 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把「智能分析与建议」Tab 转型为「AI 读图解析」：用户上传外部气象图，由多模态模型输出六段式结构化解读，可导出 docx/md；同时删除该 Tab 与其他板块重合的全部内容块、5 个专属渲染器与其连锁死代码。

**Architecture:** 新增 `modules/chart_reader.py`（图片校验与压缩、读图 prompt、页面渲染）；`modules/ai_narrative.py` 保留「报告排版 + docx 导出」并新增多模态调用（`resolve_vision_config` / `call_vision_llm`），删除 detection 版叙事（`build_prompt` / `build_fallback_markdown` / `render_ai_block`）；`app.py` 的 Tab 3 改为无条件渲染（读图不依赖已导入数据），并同步标签、`_TAB_NAMES`、`_RESET_KEYS_BY_TAB`。**Tab 索引 3 保持不变**，因此所有 `_navigate_to(3)` 调用点无需修改。

**Tech Stack:** Python 3.12/3.14、streamlit 1.59、Pillow 12.3（已是 streamlit 传递依赖）、requests（已有）

**Spec:** `docs/superpowers/specs/2026-09-13-chart-reader-and-era5-delivery-design.md` 第 5.2 节（另需第 5.2.9/5.2.10 的删除与保留清单）

## Global Constraints

- 不引入当前环境尚不存在的第三方包；`Pillow` 与 `markdown-it-py` 已在 `requirements.txt` 显式声明（批次 5 完成），本批次直接使用。
- 视觉模型配置键为 `LLM_VISION_MODEL`（**必需**）/ `LLM_VISION_API_KEY`（回落 `LLM_API_KEY`）/ `LLM_VISION_BASE_URL`（回落 `LLM_BASE_URL`，再回落 `https://api.deepseek.com`）。**`LLM_VISION_MODEL` 未配置即视为未配置，绝不回落到 `LLM_MODEL`**（默认的 `deepseek-chat` 无视觉能力，回落会造成「配了却一直失败」的隐性故障）。
- 视觉调用失败**不做文本降级**：文本模型读不了图，编造摘要等同幻觉。失败即明确报错 + 保留原图 + 重试。
- 图片全程内存处理，不落盘；三重上限：原始字节 20 MB、压缩后单图 5 MB、压缩后合计 12 MB，最多 3 张。
- `modules/chart_reader.py` 只依赖标准库、`PIL`、`streamlit`、`config` 与 `modules.ai_narrative`。
- 删除前必须对每个候选符号做一次全仓引用确认（Task 3 的 Step 1），只删确认无调用者的符号；`multi_factor_coupling`、`generate_advice`、8 个检测器、`set_custom_thresholds`、`heat_index_celsius` **保留**（`tests/test_analyzer.py` 92 条用例覆盖它们）。
- 本批次**必须同步修改** `tests/test_aqi.py`：删除 2 个断言 `check_air_quality` 存在的用例，并把「标准标注接线」用例的检查范围从 `analyzer.py` 收敛到仍渲染 AQI 的模块。否则批次 1 的测试会红。
- 本批次不修改 `config.APP_VERSION`（留到批次 5）。
- 提交前必须跑通四个 CI 门禁脚本与 `python -B -m pytest tests -q`。

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `modules/chart_reader.py`（新增） | 图片校验/压缩、读图 prompt、页面渲染 |
| `modules/ai_narrative.py`（改造） | 报告排版与 docx 导出（保留）+ 多模态调用（新增）；删除 detection 版叙事 |
| `modules/analyzer.py`（瘦身） | 删除 5 个 Tab 专属渲染器及其连锁死代码 |
| `app.py`（接线） | 标签/计数/重置键、Tab 3 无条件渲染、删除死 import 与注册项、移除主区旧使用手册折叠块 |
| `tests/test_chart_reader.py`（新增） | 图片管线、prompt 契约、配置解析 |
| `tests/test_ai_narrative.py`（新增） | 多模态请求体结构、报告排版与 docx 导出（含嵌图） |
| `tests/test_aqi.py`（修改） | 删除已删函数的用例、收敛标准标注检查范围 |

---

### Task 1: 图片管线与读图 prompt（`modules/chart_reader.py` 纯逻辑部分）

**Files:**
- Create: `modules/chart_reader.py`
- Test: `tests/test_chart_reader.py`

**Interfaces:**
- Produces:
  - 常量：`MAX_IMAGES = 3`、`MAX_RAW_BYTES = 20 * 1024 * 1024`、`MAX_IMAGE_BYTES = 5 * 1024 * 1024`、`MAX_TOTAL_BYTES = 12 * 1024 * 1024`、`MAX_EDGE_PX = 1600`、`JPEG_QUALITY = 88`、`MIN_EDGE_PX = 200`
  - `process_image(raw: bytes, name: str) -> dict` → `{"name", "ok", "error", "orig_kb", "new_kb", "width", "height", "jpeg_bytes"}`
  - `check_total_size(images: list[dict]) -> str | None`
  - `build_chart_prompt(images_meta: list[dict], user_note: str) -> str`
  - `estimate_image_tokens(images: list[dict]) -> int`
  - `render_chart_reader_tab() -> None`（Task 3 实现，本任务先不写）

- [ ] **Step 1: 写失败测试（新建 `tests/test_chart_reader.py`）**

```python
"""AI 读图解析回归测试：图片管线、prompt 契约、配置解析、报告导出。

用 PIL 现场合成测试图片，不依赖仓库内的二进制夹具。

无 pytest 时可直接运行（`python -B tests/test_chart_reader.py`）。
"""
import io
import os
import sys

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from PIL import Image  # noqa: E402

from modules import chart_reader  # noqa: E402


def _png_bytes(width, height, mode="RGB", color=None):
    img = Image.new(mode, (width, height),
                    color or ((30, 60, 120) if mode == "RGB" else (255, 0, 0, 128)))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_process_image_accepts_normal_png():
    result = chart_reader.process_image(_png_bytes(800, 600), "chart.png")
    assert result["ok"] is True, result["error"]
    assert result["width"] == 800 and result["height"] == 600
    assert result["jpeg_bytes"][:2] == b"\xff\xd8"  # JPEG 魔数
    assert result["orig_kb"] > 0 and result["new_kb"] > 0


def test_process_image_downscales_long_edge_to_limit():
    result = chart_reader.process_image(_png_bytes(3200, 1600), "big.png")
    assert result["ok"] is True, result["error"]
    assert max(result["width"], result["height"]) == chart_reader.MAX_EDGE_PX
    assert result["width"] * 2 == result["height"]  # 保持纵横比


def test_process_image_keeps_small_image_size():
    """长边未超限时不做缩放，避免无谓降质。"""
    result = chart_reader.process_image(_png_bytes(640, 480), "small.png")
    assert (result["width"], result["height"]) == (640, 480)


def test_process_image_rejects_oversized_raw_bytes():
    """解码前按原始字节拒绝，防止解压炸弹与内存膨胀。"""
    blob = b"\x89PNG\r\n\x1a\n" + b"\x00" * (chart_reader.MAX_RAW_BYTES + 1)
    result = chart_reader.process_image(blob, "huge.png")
    assert result["ok"] is False
    assert "过大" in result["error"]


def test_process_image_rejects_disguised_non_image():
    """扩展名合法但内容不是图片时必须拒绝（不信任文件名）。"""
    result = chart_reader.process_image(b"this is not an image at all", "fake.png")
    assert result["ok"] is False
    assert result["error"]


def test_process_image_rejects_low_resolution():
    result = chart_reader.process_image(_png_bytes(120, 100), "tiny.png")
    assert result["ok"] is False
    assert "分辨率" in result["error"]


def test_process_image_handles_transparency():
    """PNG 透明通道必须能转成 JPEG 而不报错。"""
    result = chart_reader.process_image(_png_bytes(600, 400, mode="RGBA"),
                                        "alpha.png")
    assert result["ok"] is True, result["error"]


def test_process_image_rejects_when_still_too_large_after_compress(monkeypatch=None):
    """压缩后仍超单图上限时拒绝：临时收紧阈值以覆盖该分支。"""
    original = chart_reader.MAX_IMAGE_BYTES
    try:
        chart_reader.MAX_IMAGE_BYTES = 1024  # 1 KB
        result = chart_reader.process_image(_png_bytes(1200, 900), "photo.png")
        assert result["ok"] is False
        assert "压缩" in result["error"] or "上限" in result["error"]
    finally:
        chart_reader.MAX_IMAGE_BYTES = original


def test_check_total_size():
    ok = [{"ok": True, "new_kb": 1000}, {"ok": True, "new_kb": 2000}]
    assert chart_reader.check_total_size(ok) is None
    big = [{"ok": True, "new_kb": 7000}, {"ok": True, "new_kb": 7000}]
    msg = chart_reader.check_total_size(big)
    assert msg and "合计" in msg


def test_check_total_size_ignores_failed_images():
    mixed = [{"ok": False, "new_kb": 0}, {"ok": True, "new_kb": 1000}]
    assert chart_reader.check_total_size(mixed) is None


def test_build_chart_prompt_has_six_sections():
    meta = [{"name": "a.png", "width": 800, "height": 600}]
    prompt = chart_reader.build_chart_prompt(meta, "")
    for section in ("【图像信息】", "【图面要素识别】", "【主要分布特征】",
                    "【关键数值与极值】", "【趋势与演变】", "【风险提示与结论】"):
        assert section in prompt, section


def test_build_chart_prompt_has_anti_hallucination_rules():
    prompt = chart_reader.build_chart_prompt([{"name": "a.png",
                                               "width": 800, "height": 600}], "")
    assert "图中未标注" in prompt
    assert "不得编造" in prompt or "禁止编造" in prompt


def test_build_chart_prompt_includes_user_note():
    prompt = chart_reader.build_chart_prompt(
        [{"name": "a.png", "width": 800, "height": 600}],
        "这是 500hPa 高空图")
    assert "500hPa" in prompt


def test_build_chart_prompt_lists_all_images():
    metas = [{"name": "a.png", "width": 800, "height": 600},
             {"name": "b.jpg", "width": 1000, "height": 700}]
    prompt = chart_reader.build_chart_prompt(metas, "")
    assert "a.png" in prompt and "b.jpg" in prompt


def test_estimate_image_tokens_positive():
    tokens = chart_reader.estimate_image_tokens(
        [{"width": 1600, "height": 1200}, {"width": 800, "height": 600}])
    assert tokens > 0
    assert isinstance(tokens, int)
```

- [ ] **Step 2: 运行确认失败**

Run: `python -B -m pytest tests/test_chart_reader.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'modules.chart_reader'`

- [ ] **Step 3: 实现 `modules/chart_reader.py` 的纯逻辑部分**

要点（真实实现，无占位）：

- 常量按 Interface 定义。
- `process_image(raw, name)`：
  1. `if len(raw) > MAX_RAW_BYTES:` → `{"ok": False, "error": "文件过大（原始 %.1f MB，上限 %d MB），请先自行压缩后上传"}`；
  2. 设定 `Image.MAX_IMAGE_PIXELS` 后 `Image.open(BytesIO(raw))` + `img.verify()`，异常一律 → `{"ok": False, "error": "不是有效的图片文件（仅支持 PNG/JPEG/WebP）"}`；
  3. 重新 `open` 取 `size`；长边 `< MIN_EDGE_PX` → 拒绝，error 含「分辨率」；
  4. 长边 `> MAX_EDGE_PX` 时等比缩放；`convert("RGB")`；`save(BytesIO, "JPEG", quality=JPEG_QUALITY, optimize=True)`；
  5. 压缩后 `len > MAX_IMAGE_BYTES` → 拒绝，error 含「压缩后仍超过单图上限」；
  6. 成功返回含 `jpeg_bytes` 与尺寸、`orig_kb`/`new_kb` 的 dict。
- `check_total_size(images)`：仅对 `ok` 的项求和，超过 `MAX_TOTAL_BYTES` 返回含「合计」的提示，否则 `None`。
- `build_chart_prompt(images_meta, user_note)`：六段标题逐字使用；写入反幻觉硬约束（图中未标注必须写「图中未标注」；禁止编造站点名/地名/数值/时间/模式名；引用数值须给出图面位置特征；图种不确定先声明不确定）；列出每张图的文件名与像素尺寸；`user_note` 非空时以「用户补充说明：」段落插入。
- `estimate_image_tokens(images)`：按 `sum(round(w*h/750))` 估算（取整到百）。

- [ ] **Step 4: 运行确认通过**

Run: `python -B -m pytest tests/test_chart_reader.py -q`
Expected: PASS（15 项）

- [ ] **Step 5: 提交**

```bash
git add modules/chart_reader.py tests/test_chart_reader.py
git commit -m "feat(chart): 图片校验压缩管线与六段式读图 prompt"
```

---

### Task 2: 多模态调用与报告改造（`modules/ai_narrative.py`）

**Files:**
- Modify: `modules/ai_narrative.py`
- Test: `tests/test_ai_narrative.py`（新增）

**Interfaces:**
- Consumes: `chart_reader.build_chart_prompt` 的产物
- Produces:
  - `modules.ai_narrative.resolve_vision_config() -> dict | None`（`{"api_key", "base_url", "model"}`；`LLM_VISION_MODEL` 缺失时返回 `None`）
  - `modules.ai_narrative.call_vision_llm(prompt, images_b64, api_key, base_url=None, model=None) -> str`
  - `modules.ai_narrative.build_report_meta(scope: str) -> dict`
  - `modules.ai_narrative.display_report(text: str, meta: dict, images: list[dict] | None = None) -> None`
  - `modules.ai_narrative.parse_sections(text) -> list[tuple[str, str]]`（`_parse_sections` 转公开，供测试直接调用）

- [ ] **Step 1: 写失败测试**

```python
def test_resolve_vision_config_requires_explicit_model():
    """LLM_VISION_MODEL 未配置时视为未配置，绝不回落到 LLM_MODEL。"""
    from modules import ai_narrative
    original = ai_narrative.st.secrets
    class _FakeSecrets(dict):
        def get(self, key, default=None):
            return dict.get(self, key, default)
    try:
        ai_narrative.st.secrets = _FakeSecrets({"LLM_API_KEY": "k",
                                                "LLM_MODEL": "deepseek-chat"})
        assert ai_narrative.resolve_vision_config() is None
    finally:
        ai_narrative.st.secrets = original


def test_resolve_vision_config_falls_back_for_key_and_url():
    from modules import ai_narrative
    original = ai_narrative.st.secrets
    class _FakeSecrets(dict):
        def get(self, key, default=None):
            return dict.get(self, key, default)
    try:
        ai_narrative.st.secrets = _FakeSecrets({
            "LLM_VISION_MODEL": "qwen-vl-max",
            "LLM_API_KEY": "text-key",
            "LLM_BASE_URL": "https://example.invalid/v1",
        })
        cfg = ai_narrative.resolve_vision_config()
        assert cfg["model"] == "qwen-vl-max"
        assert cfg["api_key"] == "text-key"
        assert cfg["base_url"] == "https://example.invalid/v1"
    finally:
        ai_narrative.st.secrets = original
```

其余用例（`call_vision_llm` 的请求体结构、`parse_sections`、`build_report_meta`、`display_report` 的 docx 嵌图）用 `requests.post` 打桩（monkeypatch 模块内 `requests.post`）验证 payload 的 `messages[0]["content"]` 含 `{"type": "image_url"}` 项、base64 前缀为 `data:image/jpeg;base64,`、`max_tokens >= 1200`；用 `python-docx` 打开 `_build_docx` 的产物断言段落数 > 0 且含图片关系（`len(doc.inline_shapes) == 1`）。

- [ ] **Step 2: 运行确认失败**

- [ ] **Step 3: 改造 `modules/ai_narrative.py`**

保留：`_parse_sections`（转公开 `parse_sections`）、`_CSS`、`_report_html`、`_set_cjk`、`_build_docx`（新增 `images` 参数，逐张 `doc.add_picture(BytesIO(jpeg_bytes), width=Cm(15))`）、`_display_report`（改名 `display_report`，签名 `(text, meta, images=None)`）。

新增：`resolve_vision_config`、`call_vision_llm`（OpenAI 兼容多模态；`timeout=90`；`temperature=0.3`；`max_tokens=1600`；失败抛异常由调用方处理）。

删除：`build_prompt`、`build_fallback_markdown`、`render_ai_block`、`_build_meta`（被 `build_report_meta` 取代）。

- [ ] **Step 4: 运行确认通过**
- [ ] **Step 5: 提交**

```bash
git add modules/ai_narrative.py tests/test_ai_narrative.py
git commit -m "feat(chart): 多模态调用与报告导出改造，删除 detection 版叙事"
```

---

### Task 3: Tab 页、接线与删除清理

**Files:**
- Modify: `modules/chart_reader.py`（追加 `render_chart_reader_tab`）
- Modify: `modules/analyzer.py`（瘦身）
- Modify: `app.py`（接线 + 删除）
- Modify: `tests/test_aqi.py`（同步批次 1 的用例）
- Test: `tests/test_chart_reader.py`（追加页面与接线契约）

**Interfaces:**
- Produces: `modules.chart_reader.render_chart_reader_tab() -> None`

- [ ] **Step 1: 删除前的引用确认（必须先做，结论写进提交信息）**

对以下每个符号执行全仓引用搜索（`grep` 工具，范围为 `*.py`），确认除自身定义与其内部调用外无其他调用者，并把结论记录为清单：

```
_aqi_level_name   check_air_quality   _render_air_quality_section
_fmt_ts           _wd_name            _build_wind_summary
_build_aq_summary _build_nwp_summary  _render_nwp_analysis_section
_render_trend_section  _render_smart_advice  check_against_extremes
render_analysis_tab
```

**预期结论**（若与实际不符，以实际为准并在提交信息中说明）：`check_air_quality`、`_render_air_quality_section`、`_render_trend_section`、`_render_smart_advice`、`render_analysis_tab`、`_render_nwp_analysis_section` 仅被 `render_analysis_tab` 或彼此调用；`_fmt_ts` / `_wd_name` / `_build_wind_summary` / `_build_aq_summary` / `_build_nwp_summary` 的唯一调用链条自 `render_analysis_tab`（`_build_wind_summary` 亦被 `_build_nwp_summary` 调用）；`check_against_extremes` 仅被 `app.py` 的检测清单引用。

**必须保留**（有测试或其他调用者）：8 个检测器、`multi_factor_coupling`、`generate_advice`、`set_custom_thresholds`、`heat_index_celsius`。

- [ ] **Step 2: 追加失败测试（页面与接线契约）**

```python
def test_app_tab_label_renamed_to_chart_reader():
    with io.open(os.path.join(_APP_DIR, "app.py"), encoding="utf-8") as f:
        source = f.read()
    assert "[读图] AI 读图解析" in source
    assert "智能分析与建议" not in source


def test_app_tab_names_and_reset_keys_updated():
    with io.open(os.path.join(_APP_DIR, "app.py"), encoding="utf-8") as f:
        source = f.read()
    assert '"读图解析"' in source
    assert '"chart_reader_images"' in source


def test_app_renders_chart_tab_without_data():
    """读图不依赖已导入数据：Tab 3 必须无条件渲染。"""
    with io.open(os.path.join(_APP_DIR, "app.py"), encoding="utf-8") as f:
        source = f.read()
    idx = source.index("render_chart_reader_tab")
    window = source[max(0, idx - 300):idx]
    assert "df is not None" not in window, window


def test_analyzer_dropped_dead_renderers():
    from modules import analyzer
    for name in ("render_analysis_tab", "_render_air_quality_section",
                 "_render_trend_section", "_render_smart_advice",
                 "_render_nwp_analysis_section", "check_air_quality",
                 "_aqi_level_name", "check_against_extremes",
                 "_build_nwp_summary", "_build_aq_summary",
                 "_build_wind_summary", "_fmt_ts", "_wd_name"):
        assert not hasattr(analyzer, name), name


def test_analyzer_kept_public_logic():
    from modules import analyzer
    for name in ("check_high_temperature", "check_cold_wave", "check_gale",
                 "check_fog", "check_rainstorm", "check_frost",
                 "check_thunderstorm", "check_haze", "multi_factor_coupling",
                 "generate_advice", "set_custom_thresholds", "heat_index_celsius"):
        assert hasattr(analyzer, name), name


def test_app_dropped_dead_imports_and_registration():
    with io.open(os.path.join(_APP_DIR, "app.py"), encoding="utf-8") as f:
        source = f.read()
    assert "check_against_extremes" not in source
    assert "\"极值\"" not in source


def test_ai_narrative_dropped_detection_api():
    from modules import ai_narrative
    for name in ("build_prompt", "build_fallback_markdown", "render_ai_block"):
        assert not hasattr(ai_narrative, name), name
    for name in ("resolve_vision_config", "call_vision_llm", "display_report",
                 "build_report_meta", "parse_sections"):
        assert hasattr(ai_narrative, name), name


def test_no_module_still_reads_detection_result():
    for path in ("app.py", "modules/analyzer.py", "modules/ai_narrative.py"):
        with io.open(os.path.join(_APP_DIR, path), encoding="utf-8") as f:
            assert "detection_result" not in f.read(), path
```

- [ ] **Step 3: 实现 `render_chart_reader_tab()`**

结构（自上而下）：隐私提示条 → `st.file_uploader(type=["png","jpg","jpeg","webp"], accept_multiple_files=True)` → 图片清单（名称/原尺寸/原体积/压缩后体积/失败原因）→ 补充说明输入框（限 500 字）→ 成本与次数提示（本会话 N/10 次、图片数、压缩后合计、估算图像 token）→ 生成按钮（含 60 秒间隔与 10 次上限）→ 报告卡片与「下载 .docx / .md」→ 失败原因对照表。

未配置视觉模型时：`st.info` 给出三个配置键名与「可选服务商」提示，**不渲染生成按钮**。

生成流程：`resolve_vision_config()` → 校验图片与合计体积 → `build_chart_prompt` → 读取 `jpeg_bytes` 做 base64 → `call_vision_llm` → 成功则写 `chart_reader_text` / `chart_reader_meta`；失败则 `st.error`（错误文本截断 200 字）+ 保留原图 + 重试，**不生成任何替代文本**。

会话键：`chart_reader_images`、`chart_reader_text`、`chart_reader_meta`、`chart_reader_last_gen`、`chart_reader_gen_count`。

- [ ] **Step 4: 按 Step 1 的清单瘦身 `modules/analyzer.py`**

删除确认无调用者的符号；随后清理因此不再使用的导入（逐个确认后再删）。预期变为未使用：`AQI_ADVICE`、`AQI_LEVELS`、`AQI_STANDARD_LABEL`、`AIR_POLLUTANT_LIMITS`、`aqi_token`、`POLLUTANT_ALIASES`、`comprehensive_aqi`；`warn_token`、`css_var`、`FIELD_LABELS`、`WARN_LEVEL_ORDER`、`np`、`pd`、`st` 是否仍被使用须逐一确认。模块 docstring 同步改写（不再包含「分析建议引擎」与空气质量评估的表述）。

- [ ] **Step 5: 修改 `app.py`**

- `tab_labels[3]` → `"[读图] AI 读图解析"`；`_TAB_NAMES[3]` → `"读图解析"`；`_RESET_KEYS_BY_TAB` 的键 `"智能分析"` → `"读图解析"`，值改为 5 个 `chart_reader_*` 键。
- Tab 3 分支改为无条件 `_safe_render("读图解析", render_chart_reader_tab)`（删除 `if st.session_state["df"] is not None:` 守卫与指纹缓存逻辑）。
- 摘要卡按钮 `"🔔 检测"` → `"🖼 读图"`；`_render_next_step_hint` 中指向「[检测] 查看预报驱动的智能分析建议」的文案改写。
- 删除 `check_against_extremes` 的 import 与 `("极值", ...)` 注册项；删除 `multi_factor_coupling` 的无用 import。
- 删除主区顶部那段过期的「📖 使用手册」折叠块（其文案引用旧的智能分析与 GB 3095-2026/HJ 633-2026 口径，且已被侧边栏手册取代）。

- [ ] **Step 5b: 同步手册与防回流断言（删掉折叠块后必做）**

`docs/用户使用手册.md` 第 4 章现存一条对主区折叠块的描述（约第 129 行）：

> 3. **使用手册折叠块**：标题行下方的「📖 使用手册」折叠区给出一段快速入门、数据格式与标准引用摘要；完整说明在本手册（侧边栏入口）。

删掉折叠块后这句即成失效描述。处置：**删除该条**（其信息已由同章侧边栏「📖 用户使用手册」条目覆盖），并在 `tests/test_manual.py` 增加一条防回流断言：

```python
def test_manual_does_not_describe_removed_main_area_expander():
    """主区使用手册折叠块已在读图解析改造中删除，手册不得再描述它。"""
    text = _manual_text()
    assert "使用手册折叠块" not in text
```

这一步是本次跨批次核查的产物：手册与 App 的一致性无法靠内容契约测试全覆盖，删除 UI 元素时必须回查手册是否描述了它。

- [ ] **Step 6: 同步 `tests/test_aqi.py`**

- 删除 `test_analyzer_check_air_quality_delegates_to_unified` 与 `test_analyzer_check_air_quality_no_pollutants_returns_none`（被测函数已删除）。
- `test_standard_label_is_wired_into_ui_sources` 的检查范围由 `("modules/analyzer.py", "modules/nwp_forecast.py")` 改为 `("modules/nwp_forecast.py",)`，并更新 docstring 说明 AQI 渲染已迁出 analyzer。
- 更新模块 docstring 中关于 analyzer 委托的描述。

- [ ] **Step 7: 运行确认通过**

Run: `python -B -m pytest tests/test_chart_reader.py tests/test_ai_narrative.py tests/test_aqi.py -q`
Expected: PASS

- [ ] **Step 8: 提交**

```bash
git add modules/chart_reader.py modules/analyzer.py modules/ai_narrative.py app.py tests/
git commit -m "feat(chart): 智能分析 Tab 转型为 AI 读图解析并清理连锁死代码"
```

---

### Task 4: 集成验证、手册第 8 章复核与全量回归

- [ ] **Step 1: AppTest 实跑读图页（未配置密钥的降级路径）**

用系统临时目录里的入口脚本调用 `render_chart_reader_tab()`，断言 `at.exception` 长度为 0、出现配置指引 `st.info`、**不出现**生成按钮。

- [ ] **Step 2: AppTest 实跑「已上传图片」路径**

入口脚本内用 `st.session_state` 预置一张合法图片（PIL 现场合成）后调用渲染函数，断言 0 异常且出现生成按钮与图片清单。

- [ ] **Step 3: 复核手册第 8 章**

对照本批次实际实现逐条核对 `docs/用户使用手册.md` 第 8 章：图片上限（单图 5 MB / 合计 12 MB / 最多 3 张 / 长边 1600 px）、六段标题、无文本降级、隐私提示、导出格式（docx/md）。若实现与手册不一致，**以实现为准修改手册**，并复跑 `python -B -m pytest tests/test_manual.py -q`。

- [ ] **Step 4: 全量回归**

Run:
```
python -B tests/test_auth_session.py
python -B tests/test_data_quality.py
python -B tests/test_analyzer.py
python -B tests/test_codec.py
python -B -m pytest tests -q
python -c "import modules.chart_reader, modules.analyzer, modules.ai_narrative, modules.manual, modules.era5_guide, app"
```
Expected: 四个门禁 exit=0；pytest 无新增失败；`app` 导入需已配置 Supabase 密钥，未配置时确认其余模块可导入。

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "test(chart): 读图页集成验证与手册第 8 章对齐"
```

---

## 完成标准

1. `modules/analyzer.py` 不再含 13 个已删符号中的任何一个，且保留清单中的 12 个符号全部存在。
2. `app.py` 的 Tab 3 标签为「[读图] AI 读图解析」，`_TAB_NAMES[3]` 为「读图解析」，重置键集为 5 个 `chart_reader_*` 键；Tab 3 **不**再依赖 `df`。
3. `app.py`、`modules/analyzer.py`、`modules/ai_narrative.py` 中不再出现 `detection_result`。
4. `resolve_vision_config()` 在缺 `LLM_VISION_MODEL` 时返回 `None`；配置齐备时三项均正确解析。
5. `call_vision_llm` 的请求体含 `image_url` 内容块与 `data:image/jpeg;base64,` 前缀，`max_tokens >= 1200`。
6. 图片管线：原始字节超 20 MB 拒绝、长边压到 1600、长边 < 200 拒绝、伪装文件拒绝、透明 PNG 可处理、压缩后超 5 MB 拒绝、合计超 12 MB 拒绝。
7. `build_chart_prompt` 含六段标题与反幻觉硬约束，并纳入用户补充说明与全部图片名。
8. `tests/test_aqi.py` 全绿；`tests/test_analyzer.py` 92 条全绿；四个 CI 门禁 exit=0；`python -B -m pytest tests -q` 无新增失败。
9. AppTest 实跑读图页两条路径均 0 异常。
10. 手册第 8 章与实现一致（图片上限、六段结构、无降级、导出格式）。

## 风险与备注

- **连锁删除是本批次最大风险**：`_build_*` 三个汇总函数与两个格式化助手只在 Tab 3 的调用链上存活，删错会把 `tests/test_analyzer.py` 之外的其他路径打断。Step 1 的引用确认是强制前置，且删除后立刻跑全量回归。
- `multi_factor_coupling` 与 `generate_advice` 在删除后**没有生产调用者**（只剩测试）：这是 spec 明确要求保留的公开逻辑，本批次不动它们，但应在批次 5 的 README 说明中如实反映其当前定位。
- 视觉模型的图片判读质量依赖所配模型；prompt 只能约束输出格式与禁止编造，无法保证识别准确度。手册第 8 章需写明适用与不适用场景。
- `tests/test_analyzer.py` 的 92 条用例是本批次的安全网，**任何一条变红都意味着删多了**。

## 实施记录（2026-09-13）

### 引用确认的实际结论

对 18 个符号做了全仓引用清点（`*.py`，50 个文件），13 个待删符号的调用者**全部落在将被删除的渲染器内部或彼此之间**，删除安全。三处与原计划的出入：

1. **`check_air_quality` 的调用点比计划多一处**：除 `_render_air_quality_section` 与 `render_analysis_tab` 外，`tests/test_aqi.py` 有两个用例直接断言它存在。已按计划在同批次内删除这两个用例，并把「标准标注接线」用例的检查范围从 `analyzer.py` 收敛为 `nwp_forecast.py`；同时新增 `test_analyzer_no_longer_computes_aqi`，把「analyzer 不得再持有任何 AQI 入口」固化成断言。
2. **`generate_advice` 既无生产调用者也无任何测试**——计划里「92 条用例覆盖它们」的说法对它不成立，spec 保留它的理由（「app.py 顶层仍在运行它们」）也不成立。处置：**按 spec 保留**，并补两条测试（事件→公众/农业双路产出、未知类别不产出），把它从「无覆盖的死代码」变为「有覆盖的公开逻辑」。
3. `_fmt_ts` / `_wd_name` / `_build_*` 的唯一调用链确实起自 `render_analysis_tab`，与预判一致。

删除规模：`analyzer.py` 1297 → 465 行；本批次提交净减 **576 行**（706 增 / 1282 删）。`analyzer.py` 的模块 docstring 已重写为职责边界声明，并顺带修掉了第 2 行一个既有的乱码字符。

### 任务边界跨过了破损状态，故合并提交

Task 2 删掉 `ai_narrative.render_ai_block`，而 `analyzer.render_analysis_tab` 仍在函数内导入它——若按计划分两次提交，中间那个提交的 Tab 3 一渲染就崩。**处置：Task 2 与 Task 3 合并为一次提交**（`9719542`），保证主干每个提交都可运行。这是对计划任务边界的修正，不是省略步骤。

### 集成测试抓到一个真 bug（已修）

AppTest 实跑读图页（无 secrets 环境）时抛 `StreamlitSecretNotFoundError`：`st.secrets.get(key, default)` 在**完全没有 secrets 文件**时抛异常，而不是返回默认值。后果是未配置密钥的环境整页崩溃，而不是给出配置指引。

修复：`modules/ai_narrative.py` 新增 `_secret(name, default)` 统一兜底，`resolve_vision_config` 改为经它读取。已补回归用例 `test_resolve_vision_config_survives_missing_secrets_file`（先看它红再修）。注意该缺陷在改造前的旧代码里同样存在（原 `render_ai_block` 也是裸调 `st.secrets.get`），只是当时没有整页路径触发它。

### 我自己写错的三处测试，均已修正

1. **`test_app_renders_chart_tab_without_data` 查错了位置**：它取 `source.index("render_chart_reader_tab")`，而第一处出现在 **import 行**，于是检查的 300 字符窗口与 Tab 3 无关，断言永远为真。改为定位 `active_tab == 3` 块、并要求渲染调用出现在检测守卫块（`_warn_fp` 赋值）之后。
2. **两条用例空洞通过**：用 `except Exception` 捕获，函数不存在时抛的 `AttributeError` 也被当成「预期的失败」。改为 `_expect_failure` 助手，显式把 `AttributeError` 判为测试不成立。
3. **一处档位断言写反**：`test_process_image_downscales_long_edge_to_limit` 原写 `width * 2 == height`，3200×1600 缩放后是 1600×800，应为 `(width, height) == (1600, 800)`。

### 手册漂移发现两处（已同步）

删掉主区「使用手册折叠块」后，手册第 4 章仍描述它；摘要卡按钮由「🔔 检测」改为「🖼 读图」后，手册第 4 章末尾与第 155 行表格仍写旧名。两处均已修正，并新增 `test_manual_does_not_describe_removed_main_area_expander` 与 `test_manual_matches_renamed_summary_card_button` 两条防回流断言。

第 8 章（读图解析）逐条对照实现：20 项实质声明全部命中；仅一处按「以实现为准」修正——手册写「未上传图片即点击生成 → 提示先上传」，实际是生成按钮禁用，点击不会发生。

### 验收证据（2026-09-13）

```
python -B -m pytest tests -q                          → 338 passed
四个 CI 门禁脚本                                       → 全部 exit=0
app.py AST 解析 + 7 个模块导入                          → OK
AppTest 读图页（无 secrets）                           → 0 异常；给出配置指引，不显示生成按钮
AppTest 读图页（临时 secrets，跑完即删）                 → 0 异常；出现生成按钮与隐私提示；无残留文件
残留引用扫描（15 个已删符号 × 全仓 .py）                 → 生产代码零引用，仅存于测试的反向断言
```

## 实施记录补记（2026-09-13，v2.3.2）：真实天气图推翻了本计划的编码设计

### 本计划的判断错在哪里

本计划与设计文档都规定「统一转为 RGB，以 JPEG 质量 88 编码一次」，理由是「JPEG 平衡文本锐度与体积」。这条判断从未用真实天气图验证过，而它是错的。

拿到真实图实测（[JMA 天气图](https://www.jma.go.jp/bosai/weather_map/data/list.json) 与 NOAA WPC）：

| 真实图 | 原文件 | 原实现输出 JPEG q88 | 体积变化 |
|---|---|---|---|
| JMA 亚洲地面图 600×512 PNG | 64 KB | 85 KB | **+33%** |
| JMA 日本周边图 600×581 PNG | 56 KB | 85 KB | **+52%** |
| WPC 大西洋分析图 748×562 GIF | 35 KB | 181 KB | **5.2 倍** |
| WPC 北美分析图 748×562 GIF | 39 KB | 194 KB | **5.0 倍** |

原因是天气图属于**线画类**内容（等值线、站点数字、少量颜色），JPEG 的 DCT 对这种内容效率极差。而界面把这一列直接标为「压缩后 (KB)」，于是真实用户看到的是「压缩后比原始大 5 倍」。合成测试图是纯色块与几何图形，恰好落在 JPEG 擅长的区间，所以 28 项测试全绿也发现不了。

### 改法

改为「能不改就不改」：未触发缩放且输入已是 PNG/JPEG 时**原样提交**（零重编码、零画质损失），需要重编码时（触发缩放，或输入为 WebP/GIF）同时试算 JPEG q88 与 PNG，**取体积更小者**。只用这两种格式，因为导出 docx 的 python-docx 不支持 WebP。顺带修掉一个同源缺陷：重编码路径原先 `convert("RGB")` 会把透明区压成黑色，改为铺白底，否则浅色等值线会被黑底吞掉。

修复后同一批真实图：两张 PNG 均为 **+0.0%**（原样透传），两张 GIF 降到 +60% / +44%（GIF 不在允许上传类型内，这条路径实际只由 WebP 触发，其膨胀是格式转换的固有代价）。界面列名同步从「压缩后」改为「提交」。

接口相应变化：`process_image` 返回 `data_bytes` / `mime` / `kept_original`（原 `jpeg_bytes` 消失），`image_to_data_url(data, mime)` 增加第二参数。`chart_reader_images` 会话结构的键名随之改变，`_build_docx` 读取 `data_bytes`。

### 新增测试（本文件条数由 28 增至 36）

`test_process_image_passes_through_png_without_reencoding`、`test_process_image_passes_through_jpeg_without_reencoding`、`test_process_image_switches_to_png_for_resized_line_art`、`test_process_image_keeps_jpeg_for_photo_like_content`、`test_process_image_never_emits_webp`、`test_process_image_flattens_transparency_onto_white`、`test_image_to_data_url_uses_actual_mime`、`test_chart_table_labels_submitted_size_honestly`。

其中两条是**对抗性**的：线画图那条先断言「JPEG 确实更大」，否则测试本身无意义；相片那条用随机噪声构造反例，确保新策略没有把 JPEG 路径整个砍掉。

### 教训

「合成测试全绿」不等于「真实数据可用」。测试图是我自己生成的，形状恰好迎合实现的假设；只有真实天气图才暴露了这个假设。凡是涉及**外部真实数据形态**的处理（图像编码、文件解析、编码字符集），都应当拿一到两份真实样本过一遍，而不是只跑合成夹具。
