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

from PIL import Image  # noqa: E402

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
    assert result["jpeg_bytes"][:2] == b"\xff\xd8"  # JPEG 魔数
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
    """PNG 透明通道必须能转成 JPEG 而不报错。"""
    result = chart_reader.process_image(_png_bytes(600, 400, mode="RGBA"),
                                        "alpha.png")
    assert result["ok"] is True, result["error"]


def test_process_image_rejects_when_still_too_large_after_compress():
    """压缩后仍超单图上限时拒绝：临时收紧阈值以覆盖该分支。"""
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
