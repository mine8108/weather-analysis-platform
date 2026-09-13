"""AI 读图解析回归测试：图片管线、prompt 契约、页面接线。

用 PIL 现场合成测试图片，不依赖仓库内的二进制夹具。
两处体积上限分支通过「临时收紧阈值」覆盖，避免在测试里分配几十 MB 内存。

无 pytest 时可直接运行（`python -B tests/test_chart_reader.py`）。
"""
import io
import os
import sys

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from PIL import Image, ImageDraw  # noqa: E402

from modules import chart_reader  # noqa: E402


def _png_bytes(width, height, mode="RGB"):
    color = (255, 0, 0, 128) if mode == "RGBA" else (30, 60, 120)
    img = Image.new(mode, (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _with_limit(name, value, fn):
    """临时收紧模块级阈值，覆盖体积上限分支后还原。"""
    import functools
    original = getattr(chart_reader, name)
    try:
        setattr(chart_reader, name, value)
        return fn()
    finally:
        setattr(chart_reader, name, original)


# ============================================================
# 一、图片管线
# ============================================================

def test_process_image_accepts_normal_png():
    result = chart_reader.process_image(_png_bytes(800, 600), "chart.png")
    assert result["ok"] is True, result["error"]
    assert result["width"] == 800 and result["height"] == 600
    assert result["mime"] == "image/png"
    assert result["data_bytes"][:4] == b"\x89PNG"
    assert result["orig_kb"] > 0 and result["new_kb"] > 0
    assert result["error"] is None


def test_process_image_downscales_long_edge_to_limit():
    result = chart_reader.process_image(_png_bytes(3200, 1600), "big.png")
    assert result["ok"] is True, result["error"]
    assert max(result["width"], result["height"]) == chart_reader.MAX_EDGE_PX
    assert (result["width"], result["height"]) == (1600, 800)  # 等比缩放


def test_process_image_keeps_small_image_size():
    """长边未超限时不做缩放，避免无谓降质。"""
    result = chart_reader.process_image(_png_bytes(640, 480), "small.png")
    assert (result["width"], result["height"]) == (640, 480)


def test_process_image_rejects_oversized_raw_bytes():
    """解码前按原始字节拒绝，防止解压炸弹与内存膨胀。"""
    def _run():
        return chart_reader.process_image(_png_bytes(400, 300), "ok.png")
    result = _with_limit("MAX_RAW_BYTES", 16, _run)
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
    """PNG 透明通道必须能安全处理：透传时保留，重编码时铺白底。"""
    result = chart_reader.process_image(_png_bytes(600, 400, mode="RGBA"),
                                        "alpha.png")
    assert result["ok"] is True, result["error"]
    assert result["mime"] == "image/png"


def test_process_image_rejects_when_still_too_large_after_compress():
    """处理后仍超单图上限时拒绝：临时收紧阈值以覆盖该分支。"""
    def _run():
        return chart_reader.process_image(_png_bytes(1200, 900), "photo.png")
    result = _with_limit("MAX_IMAGE_BYTES", 1024, _run)
    assert result["ok"] is False
    assert "上限" in result["error"]


def test_process_image_failure_keeps_name():
    result = chart_reader.process_image(b"nope", "broken.png")
    assert result["name"] == "broken.png"
    assert result["ok"] is False


# ============================================================
# 一之二、编码策略（真实天气图暴露）
# ============================================================

def _line_art_png(width, height):
    """合成线画类图：白底 + 密集细线，模拟天气图的等值线与站点数字。"""
    img = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    for x in range(0, width, 4):
        draw.line([(x, 0), (x, height)], fill=(0, 0, 0), width=1)
    for y in range(0, height, 4):
        draw.line([(0, y), (width, y)], fill=(200, 0, 0), width=1)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _encode_with(raw, fmt, **kw):
    with Image.open(io.BytesIO(raw)) as img:
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format=fmt, **kw)
        return buf.getvalue()


def test_process_image_passes_through_png_without_reencoding():
    """未触发缩放时不得重编码。

    真实数据实测：JMA 600×512 线画 PNG 64 KB → JPEG q88 85 KB（+33%），
    WPC 748×562 GIF 35 KB → JPEG 181 KB（5.2 倍）。线画内容 JPEG 效率极差，
    而界面此前把该列标为「压缩后」，用户会看到「压缩后比原始大」。
    """
    raw = _line_art_png(800, 600)
    result = chart_reader.process_image(raw, "chart.png")
    assert result["ok"] is True, result["error"]
    assert result["kept_original"] is True
    assert result["data_bytes"] == raw
    assert result["mime"] == "image/png"
    assert result["new_kb"] <= result["orig_kb"], "提交体积不得大于原始体积"


def test_process_image_passes_through_jpeg_without_reencoding():
    raw = _encode_with(_line_art_png(800, 600), "JPEG", quality=90)
    result = chart_reader.process_image(raw, "chart.jpg")
    assert result["ok"] is True, result["error"]
    assert result["data_bytes"] == raw
    assert result["mime"] == "image/jpeg"


def test_process_image_switches_to_png_for_resized_line_art():
    """触发缩放后必须重编码；线画内容应取 PNG 而非 JPEG。"""
    raw = _line_art_png(2400, 1200)
    result = chart_reader.process_image(raw, "big.png")
    assert result["ok"] is True, result["error"]
    assert max(result["width"], result["height"]) == chart_reader.MAX_EDGE_PX
    assert result["kept_original"] is False

    with Image.open(io.BytesIO(result["data_bytes"])) as out:
        resized = out.convert("RGB")
    jpeg = io.BytesIO()
    resized.save(jpeg, format="JPEG", quality=chart_reader.JPEG_QUALITY, optimize=True)
    png = io.BytesIO()
    resized.save(png, format="PNG", optimize=True)
    assert len(png.getvalue()) < len(jpeg.getvalue()), "线画内容若 JPEG 更小则本测试无意义"
    assert result["mime"] == "image/png"


def test_process_image_keeps_jpeg_for_photo_like_content():
    """相片类内容用 PNG 会膨胀，必须仍取 JPEG。"""
    import random
    random.seed(7)
    size = 2000 * 1200
    noise = bytes(random.getrandbits(8) for _ in range(size * 3))
    img = Image.frombytes("RGB", (2000, 1200), noise)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    result = chart_reader.process_image(buf.getvalue(), "photo.jpg")
    assert result["ok"] is True, result["error"]
    assert result["mime"] == "image/jpeg"


def test_process_image_never_emits_webp():
    """导出 docx 用的 python-docx 不支持 WebP，故输出格式只能是 PNG/JPEG。"""
    img = Image.new("RGB", (900, 700), (10, 90, 160))
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=90)
    result = chart_reader.process_image(buf.getvalue(), "chart.webp")
    assert result["ok"] is True, result["error"]
    assert result["kept_original"] is False
    assert result["mime"] in ("image/png", "image/jpeg")


def test_process_image_flattens_transparency_onto_white():
    """重编码路径必须铺白底，不能把透明区压成黑色（黑色会掩盖浅色等值线）。"""
    img = Image.new("RGBA", (2000, 500), (0, 0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    result = chart_reader.process_image(buf.getvalue(), "alpha.png")
    assert result["ok"] is True, result["error"]
    with Image.open(io.BytesIO(result["data_bytes"])) as out:
        pixel = out.convert("RGB").getpixel((10, 10))
    assert min(pixel) >= 250, pixel


def test_image_to_data_url_uses_actual_mime():
    png = chart_reader.image_to_data_url(b"\x89PNG\r\n\x1a\n", "image/png")
    jpeg = chart_reader.image_to_data_url(b"\xff\xd8\xff\xe0", "image/jpeg")
    assert png.startswith("data:image/png;base64,")
    assert jpeg.startswith("data:image/jpeg;base64,")


# ============================================================
# 一之三、用量记账与配额
# ============================================================

def test_generation_cap_and_budget_match_configured_quota():
    """每会话 5 次、单次 2 万 token 是用户设定的额度，锁住防止被改回去。"""
    assert chart_reader.MAX_GENERATIONS_PER_SESSION == 5
    from modules.ai_narrative import VISION_MAX_TOKENS
    assert VISION_MAX_TOKENS == 20000


def test_merge_usage_sums_all_fields():
    merged = chart_reader.merge_usage(
        {"prompt": 100, "completion": 200, "reasoning": 150, "total": 300},
        {"prompt": 10, "completion": 20, "reasoning": 5, "total": 30})
    assert merged == {"prompt": 110, "completion": 220,
                      "reasoning": 155, "total": 330}


def test_merge_usage_treats_missing_as_zero():
    """失败调用可能只拿到部分字段，缺失一律按 0 计，不能让记账抛异常。"""
    assert chart_reader.merge_usage(None, {"total": 7})["total"] == 7
    assert chart_reader.merge_usage({}, None)["total"] == 0
    assert chart_reader.merge_usage({"prompt": 5}, {"completion": 3}) == {
        "prompt": 5, "completion": 3, "reasoning": 0, "total": 0}


def test_format_usage_mentions_reasoning_share():
    """推理型模型的思考占大头，展示时必须点明，否则用户无法理解成本。"""
    text = chart_reader.format_usage(
        {"prompt": 911, "completion": 11475, "reasoning": 10437, "total": 12386})
    assert "11,475" in text
    assert "思考" in text and "10,437" in text


def test_format_usage_without_reasoning_is_plain():
    text = chart_reader.format_usage(
        {"prompt": 10, "completion": 20, "reasoning": 0, "total": 30})
    assert "30" in text
    assert "思考" not in text


# ============================================================
# 二、合计体积
# ============================================================

def test_check_total_size():
    ok = [{"ok": True, "new_kb": 1000}, {"ok": True, "new_kb": 2000}]
    assert chart_reader.check_total_size(ok) is None
    big = [{"ok": True, "new_kb": 7000}, {"ok": True, "new_kb": 7000}]
    msg = chart_reader.check_total_size(big)
    assert msg and "合计" in msg


def test_check_total_size_ignores_failed_images():
    mixed = [{"ok": False, "new_kb": 0}, {"ok": True, "new_kb": 1000}]
    assert chart_reader.check_total_size(mixed) is None


def test_check_total_size_empty():
    assert chart_reader.check_total_size([]) is None


# ============================================================
# 三、读图 prompt 契约
# ============================================================

def _meta(name="a.png", width=800, height=600):
    return {"name": name, "width": width, "height": height, "ok": True}


def test_build_chart_prompt_has_six_sections():
    prompt = chart_reader.build_chart_prompt([_meta()], "")
    for section in ("【图像信息】", "【图面要素识别】", "【主要分布特征】",
                    "【关键数值与极值】", "【趋势与演变】", "【风险提示与结论】"):
        assert section in prompt, section


def test_build_chart_prompt_has_anti_hallucination_rules():
    prompt = chart_reader.build_chart_prompt([_meta()], "")
    assert "图中未标注" in prompt
    assert "编造" in prompt


def test_build_chart_prompt_includes_user_note():
    prompt = chart_reader.build_chart_prompt([_meta()], "这是 500hPa 高空图")
    assert "500hPa" in prompt


def test_build_chart_prompt_lists_all_images():
    metas = [_meta("a.png"), _meta("b.jpg", 1000, 700)]
    prompt = chart_reader.build_chart_prompt(metas, "")
    assert "a.png" in prompt and "b.jpg" in prompt


def test_build_chart_prompt_forbids_climate_extrapolation():
    """禁止把短期图面信息外推为气候结论（与平台免责口径一致）。"""
    prompt = chart_reader.build_chart_prompt([_meta()], "")
    assert "官方" in prompt


# ============================================================
# 四、图像 token 估算
# ============================================================

def test_estimate_image_tokens_positive():
    tokens = chart_reader.estimate_image_tokens(
        [{"width": 1600, "height": 1200}, {"width": 800, "height": 600}])
    assert tokens > 0
    assert isinstance(tokens, int)


def test_estimate_image_tokens_empty():
    assert chart_reader.estimate_image_tokens([]) == 0


# ============================================================
# 五、页面与接线契约
# ============================================================

def _source(rel):
    import io
    with io.open(os.path.join(_APP_DIR, rel), encoding="utf-8") as handle:
        return handle.read()


def test_app_tab_label_renamed_to_chart_reader():
    source = _source("app.py")
    assert "[读图] AI 读图解析" in source
    assert "智能分析与建议" not in source


def test_app_tab_names_and_reset_keys_updated():
    source = _source("app.py")
    assert '"读图解析"' in source
    assert '"chart_reader_images"' in source


def test_app_renders_chart_tab_without_data():
    """读图不依赖已导入数据：渲染调用在 Tab 3 块内无条件执行。

    注意不能直接搜 "df is not None"——Tab 3 块内确实有一段检测守卫
    （数据指纹缓存，用于喂报告导出），它合法地判断 df。判据改为：
    渲染调用必须出现在该守卫块结束之后。
    """
    source = _source("app.py")
    start = source.index('if st.session_state["active_tab"] == 3:')
    end = source.index("# ---- Tab 4", start)
    block = source[start:end]
    call = block.index("render_chart_reader_tab")
    guard_end = block.index('st.session_state["_warn_fp"] = fp')
    assert call > guard_end, "读图渲染必须位于检测守卫块之后，无条件执行"


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
    source = _source("app.py")
    assert "check_against_extremes" not in source
    assert '"极值"' not in source


def test_app_dropped_stale_manual_expander():
    """主区旧的「使用手册」折叠块与过期的 2026 标准引用必须移除。"""
    source = _source("app.py")
    assert "HJ 633-2026" not in source
    assert "GB 3095-2026" not in source


def test_no_module_still_reads_detection_result():
    for path in ("app.py", "modules/analyzer.py", "modules/ai_narrative.py"):
        assert "detection_result" not in _source(path), path


def test_chart_reader_exposes_renderer():
    from modules import chart_reader
    assert callable(chart_reader.render_chart_reader_tab)


def test_chart_table_labels_submitted_size_honestly():
    """列名不得再写「压缩后」：透传时字节不变，重编码后也可能比原始更大。"""
    source = _source("modules/chart_reader.py")
    assert "压缩后 (KB)" not in source
    assert "提交 (KB)" in source


if __name__ == "__main__":
    import traceback

    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except Exception:
                failed += 1
                print(f"[FAIL] {name}")
                traceback.print_exc()
            else:
                print(f"[PASS] {name}")
    print(f"\n{'FAILED' if failed else 'ALL PASSED'} ({failed} failures)")
    sys.exit(1 if failed else 0)
