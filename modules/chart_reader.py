"""AI 读图解析：图片校验与编码、读图 prompt 构造、页面渲染。

设计要点：
- 图片全程在内存处理，不落盘；三重上限分别是原始字节、提交单图、提交合计。
- 先按原始字节设闸再解码，避免解压炸弹；随后用 PIL 的 verify() 做魔数校验，
  不信任文件扩展名与 MIME。
- 编码策略「能不改就不改」：未触发缩放且输入已是 PNG/JPEG 时原样提交；需要重
  编码时在 JPEG 与 PNG 中取更小者。天气图是线画类内容，JPEG 对它的效率极差
  （实测 PNG 64 KB 的图转 JPEG q88 变 85 KB，GIF 35 KB 的更会变 181 KB）。
- 重编码只做一次，不做二次降质重试——否则用户无从判断画质损失。
- 视觉调用失败时**不生成任何替代文本**：文本模型读不了图，编造摘要等同幻觉。
"""

import base64
import io
import time

import streamlit as st

from PIL import Image

# 上传与体积上限
MAX_IMAGES = 3
MAX_RAW_BYTES = 20 * 1024 * 1024      # 原始字节硬上限，超过直接拒绝，不解码
MAX_IMAGE_BYTES = 5 * 1024 * 1024     # 提交单图上限
MAX_TOTAL_BYTES = 12 * 1024 * 1024    # 提交合计上限
MAX_PIXELS = 50 * 1000 * 1000         # 解码后的像素数上限
MAX_EDGE_PX = 1600                    # 长边上限（保等值线数值与坐标标注可读）
MIN_EDGE_PX = 200                     # 长边下限（低于此无解析价值）
JPEG_QUALITY = 88

ALLOWED_UPLOAD_TYPES = ["png", "jpg", "jpeg", "webp"]

# 可原样提交的输入格式。WebP 不在其中：python-docx 无法把 WebP 嵌进导出的 docx。
_PASSTHROUGH_MIMES = {"PNG": "image/png", "JPEG": "image/jpeg"}

# 单次生成的会话限制
MIN_INTERVAL_SECONDS = 60
# 每会话最多尝试 5 次。计的是「尝试」而非「成功」：失败调用同样被服务商计费，
# 只数成功就会让反复失败不计入额度。会话级限制刷新页面即重置，属防误操作级别，
# 不是成本控制——真正的硬配额需要服务端状态（见计划文档的配额设计讨论）。
MAX_GENERATIONS_PER_SESSION = 5

# 用量记账字段。与 ai_narrative._normalize_usage 的键保持一致。
USAGE_KEYS = ("prompt", "completion", "reasoning", "total")

_SECTIONS = ("【图像信息】", "【图面要素识别】", "【主要分布特征】",
             "【关键数值与极值】", "【趋势与演变】", "【风险提示与结论】")


def _fail(name, message, orig_bytes=0):
    return {"name": name, "ok": False, "error": message,
            "orig_kb": max(0, orig_bytes // 1024), "new_kb": 0,
            "width": 0, "height": 0,
            "data_bytes": None, "mime": None, "kept_original": False}


def _flatten_to_rgb(img):
    """转成 RGB；带透明通道时铺白底。

    透传路径不经过这里，透明度原样保留。只有必须重编码时才铺白底，避免透明区
    被压成黑色——黑色底会掩盖浅色等值线，而等值线正是要读的内容。
    """
    if img.mode in ("RGBA", "LA", "PA") or (
            img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        canvas = Image.new("RGB", rgba.size, (255, 255, 255))
        canvas.paste(rgba, mask=rgba.split()[-1])
        return canvas
    return img.convert("RGB")


def _encode_smallest(img):
    """在 JPEG 与 PNG 之间取更小者，返回 (bytes, mime)。

    只用这两种格式：导出 docx 的 python-docx 不支持 WebP。
    线画类图（天气图、等值线图、站点图）PNG 更小，相片类图 JPEG 更小，无法预先
    判定，故两者都编码后比较。每张图长边最多 1600 px，这点 CPU 开销可忽略。
    """
    rgb = _flatten_to_rgb(img)
    jpeg_buffer = io.BytesIO()
    rgb.save(jpeg_buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    png_buffer = io.BytesIO()
    rgb.save(png_buffer, format="PNG", optimize=True)
    jpeg = (jpeg_buffer.getvalue(), "image/jpeg")
    png = (png_buffer.getvalue(), "image/png")
    return png if len(png[0]) < len(jpeg[0]) else jpeg


def process_image(raw, name):
    """校验并处理一张上传图片。

    返回 {"name", "ok", "error", "orig_kb", "new_kb", "width", "height",
    "data_bytes", "mime", "kept_original"}。失败时 ok 为 False 且 error 给出可读
    原因；成功时 data_bytes 为实际提交给模型的字节，mime 为其真实类型。

    编码策略是「能不改就不改」：未触发缩放且输入已是 PNG/JPEG 时原样提交，
    零重编码、零画质损失；需要重编码时（触发缩放，或输入为 WebP/GIF）
    在 JPEG 与 PNG 中取更小者。
    """
    if not raw:
        return _fail(name, "文件为空")

    if len(raw) > MAX_RAW_BYTES:
        return _fail(name, "文件过大（原始 %.2f MB，上限 %.0f MB），请先自行压缩后上传"
                     % (len(raw) / 1048576.0, MAX_RAW_BYTES / 1048576.0),
                     len(raw))

    orig_kb = max(1, len(raw) // 1024)

    # 第一步：魔数校验（verify 会消耗文件对象，故随后重新打开）
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            probe.verify()
    except Image.DecompressionBombError:
        return _fail(name, "图片像素过大，已拒绝解码", len(raw))
    except Exception:  # noqa: BLE001 - 任何解码失败都视为非法图片
        return _fail(name, "不是有效的图片文件（仅支持 PNG / JPEG / WebP）", len(raw))

    try:
        with Image.open(io.BytesIO(raw)) as img:
            width, height = img.size
            source_format = (img.format or "").upper()
            if width * height > MAX_PIXELS:
                return _fail(name, "图片像素数过大（%.0f 万像素，上限 %.0f 万），请先缩小后上传"
                             % (width * height / 10000.0, MAX_PIXELS / 10000.0), len(raw))

            long_edge = max(width, height)
            if long_edge < MIN_EDGE_PX:
                return _fail(name, "分辨率过低（长边 %d 像素，至少需要 %d 像素），无法解析"
                             % (long_edge, MIN_EDGE_PX), len(raw))

            resized = long_edge > MAX_EDGE_PX
            if resized:
                scale = MAX_EDGE_PX / float(long_edge)
                width = max(1, int(round(width * scale)))
                height = max(1, int(round(height * scale)))
                img = img.resize((width, height), Image.LANCZOS)

            if not resized and source_format in _PASSTHROUGH_MIMES:
                data = raw
                mime = _PASSTHROUGH_MIMES[source_format]
                kept_original = True
            else:
                data, mime = _encode_smallest(img)
                kept_original = False
    except Exception:  # noqa: BLE001 - 损坏文件在 resize/convert 阶段也可能失败
        return _fail(name, "图片处理失败（文件可能已损坏或不完整）", len(raw))

    if len(data) > MAX_IMAGE_BYTES:
        return _fail(name, "处理后的字节仍超过单图上限（%.2f MB > %.0f MB），请先自行压缩后上传"
                     % (len(data) / 1048576.0, MAX_IMAGE_BYTES / 1048576.0), len(raw))

    return {"name": name, "ok": True, "error": None,
            "orig_kb": orig_kb, "new_kb": max(1, len(data) // 1024),
            "width": width, "height": height,
            "data_bytes": data, "mime": mime, "kept_original": kept_original}


def check_total_size(images):
    """合计体积校验：只统计成功的图片；超限返回提示文本，否则 None。"""
    total_kb = sum(item.get("new_kb", 0) for item in images if item.get("ok"))
    if total_kb * 1024 > MAX_TOTAL_BYTES:
        return ("提交合计 %.1f MB，超过上限 %.0f MB，请减少图片张数或先自行压缩"
                % (total_kb / 1024.0, MAX_TOTAL_BYTES / 1048576.0))
    return None


def estimate_image_tokens(images):
    """粗略估算图像 token 数（按 宽×高/750，取整到百），用于生成前的成本可见。"""
    total = 0
    for item in images:
        width = int(item.get("width") or 0)
        height = int(item.get("height") or 0)
        if width and height:
            total += round(width * height / 750.0)
    return int(round(total / 100.0) * 100)


def merge_usage(previous, current):
    """累加两次用量，缺失字段按 0 计。

    失败调用可能只拿到部分字段（甚至完全没有 usage），因此这里不能用
    ``previous["total"] += ...`` 这类写法——一个 KeyError 就会把整页弄崩。
    """
    merged = {}
    for key in USAGE_KEYS:
        merged[key] = int((previous or {}).get(key) or 0) \
            + int((current or {}).get(key) or 0)
    return merged


def format_usage(usage):
    """把用量说成人话：总量为准，推理型模型的思考占比必须点明。

    以 total 为准而非 completion：prompt 那部分同样计费，只用输出量会低报成本。
    """
    usage = usage or {}
    total = int(usage.get("total") or 0)
    completion = int(usage.get("completion") or 0)
    reasoning = int(usage.get("reasoning") or 0)
    text = "%s token" % format(total or completion, ",")
    if reasoning and completion:
        text += "（输出 %s，其中思考 %s，占 %.0f%%）" % (
            format(completion, ","), format(reasoning, ","),
            100.0 * reasoning / completion)
    return text


def build_chart_prompt(images_meta, user_note):
    """构造读图 prompt：六段固定结构 + 反幻觉硬约束。"""
    lines = [
        "你是一名气象业务分析师。下面会给出用户上传的气象图（天气图、卫星云图、"
        "雷达回波、模式形势图等）。请**只依据图面可见信息**输出结构化解读。",
        "",
        "输出必须严格包含以下六段，段标题逐字保留：",
        "1. %s 图片数量、文件名与像素尺寸；能读出的图种、时间、区域、层次。" % _SECTIONS[0],
        "2. %s 坐标轴、色标、图例、单位、等值线间隔分别是什么。" % _SECTIONS[1],
        "3. %s 可判读的天气系统与分布特征（高低压、槽脊、锋面、雨带、回波强度分布等）。"
        % _SECTIONS[2],
        "4. %s 图中可读的极值及其出现位置；数值必须与图面标注一致。" % _SECTIONS[3],
        "5. %s 仅当上传多张图或图中含时序/多时次时输出；单图必须明确写「单图无法判断演变」。"
        % _SECTIONS[4],
        "6. %s 面向业务与公众、可操作的结论。" % _SECTIONS[5],
        "",
        "硬性约束（违反即视为无效输出）：",
        "- 图中未标注的信息必须写「图中未标注」，不得推测。",
        "- 禁止编造站点名、地名、数值、时间与模式名称。",
        "- 引用数值时必须同时给出该数值在图中的位置特征（如「色标右端」「等值线密集区」）。",
        "- 无法确定图种时，先声明不确定，再给出最可能的判读及其依据。",
        "- 不得把单张图面的短期信息外推为气候趋势或长期预测。",
        "- 涉及预警等级仅作参考提示，最终以官方气象部门发布为准。",
        "",
        "本次上传的图片：",
    ]
    for index, meta in enumerate(images_meta or [], start=1):
        lines.append("- 图 %d：%s（%s × %s 像素）"
                     % (index, meta.get("name", "未命名"),
                        meta.get("width", "?"), meta.get("height", "?")))
    note = (user_note or "").strip()
    if note:
        lines += ["", "用户补充说明（请优先结合它判读）：", note]
    lines += ["", "请直接输出六段正文，不要重复上述指令。"]
    return "\n".join(lines)


def image_to_data_url(data, mime):
    """提交字节 → OpenAI 兼容的 data URL。类型必须与真实字节一致。"""
    return "data:%s;base64,%s" % (mime, base64.b64encode(data).decode("ascii"))


# ============================================================
# 页面渲染
# ============================================================

_SETUP_HINT = (
    "读图解析尚未配置。请在 Streamlit Secrets 中设置：\n\n"
    "- `LLM_VISION_MODEL`（**必需**，须是具备图像输入能力的模型，例如 `qwen-vl-max`、"
    "`glm-4v`、`gpt-4o`）\n"
    "- `LLM_VISION_API_KEY`（留空则回落 `LLM_API_KEY`）\n"
    "- `LLM_VISION_BASE_URL`（留空则回落 `LLM_BASE_URL`）\n\n"
    "注意：**不会**回落到 `LLM_MODEL`。默认的 `deepseek-chat` 没有视觉能力，"
    "回落只会造成「配置了却一直失败」的隐性故障。"
)

_FAILURE_TABLE = """
| 现象 | 可能原因 | 处置 |
|---|---|---|
| 提示「读图解析尚未配置」 | 未设置 `LLM_VISION_MODEL` | 按上方说明在 Secrets 中配置后重启应用 |
| 某张图标记为失败 | 超过体积/像素上限、分辨率过低或文件不是有效图片 | 按该图给出的原因处理；伪装扩展名的文件会被拒绝 |
| 整体拒绝上传 | 张数超过 3 张，或提交合计超过 12 MB | 减少张数或先自行压缩 |
| 生成失败并给出可读错误 | 模型服务超时、密钥无效、额度不足，或输出预算被推理过程耗尽 | 原图已保留，可直接重试；错误文本会带出 `finish_reason`、模型名与响应片段，据此处置；预算不足可调大 `LLM_VISION_MAX_TOKENS` |
| 解读里出现「图中未标注」 | 图中确实没有该信息 | 这是刻意的反幻觉约束，不是故障 |
| 解读与图不符 | 模型判读能力有限，尤其是等值线密集或非中文标注的图 | 在补充说明里指明图种、层次与关注点可显著改善 |
"""


def _render_failure_table():
    with st.expander("常见失败原因与处理", expanded=False):
        st.markdown(_FAILURE_TABLE)


def _record_usage(usage):
    """把一次调用的用量并入会话累计，并记下最近一次。

    必须在成功与失败两条路径上都调用：服务商对失败的调用同样计费。
    """
    last = merge_usage(None, usage)
    total = merge_usage(st.session_state.get("chart_reader_usage_total"), usage)
    st.session_state["chart_reader_usage_last"] = last
    st.session_state["chart_reader_usage_total"] = total
    return last, total


def _generate(cfg, images, note):
    """执行一次读图解析。失败即报错并保留原图，不产出任何替代文本。"""
    from modules.ai_narrative import (VISION_MAX_TOKENS, build_report_meta,
                                      call_vision_llm)

    now = time.time()
    last = float(st.session_state.get("chart_reader_last_gen", 0) or 0)
    if now - last < MIN_INTERVAL_SECONDS:
        st.warning("生成过于频繁，请 %d 秒后再试。"
                   % int(MIN_INTERVAL_SECONDS - (now - last)))
        return
    count = int(st.session_state.get("chart_reader_gen_count", 0) or 0)
    if count >= MAX_GENERATIONS_PER_SESSION:
        st.warning("本会话尝试次数已达上限（%d 次），请刷新页面后继续。"
                   % MAX_GENERATIONS_PER_SESSION)
        return

    prompt = build_chart_prompt(images, note)
    data_urls = [image_to_data_url(item["data_bytes"], item["mime"])
                 for item in images]

    usage = {}
    with st.spinner("正在读图解析，通常需要十几秒..."):
        try:
            text = call_vision_llm(prompt, data_urls, cfg["api_key"],
                                   base_url=cfg["base_url"], model=cfg["model"],
                                   max_tokens=cfg.get("max_tokens"),
                                   usage_out=usage)
        except Exception as exc:  # noqa: BLE001 - 任何失败都报错，不降级
            _record_usage(usage)
            st.session_state["chart_reader_gen_count"] = count + 1
            detail = str(exc).strip() or exc.__class__.__name__
            st.error("读图解析失败：%s" % detail[:200])
            spent = int(usage.get("completion") or 0)
            st.caption("本次尝试仍会被服务商计费%s。原图已保留，可直接重试。"
                       "本功能**不提供文本模型降级**——文本模型读不了图，"
                       "编造的摘要会误导判断。"
                       % ("（消耗 %s）" % format_usage(usage) if spent else ""))
            return

    _record_usage(usage)
    st.session_state["chart_reader_text"] = text
    st.session_state["chart_reader_meta"] = build_report_meta(
        "上传气象图 %d 张（模型：%s）" % (len(images), cfg["model"]))
    st.session_state["chart_reader_last_gen"] = time.time()
    st.session_state["chart_reader_gen_count"] = count + 1


def render_chart_reader_tab():
    """渲染 AI 读图解析页。不依赖任何已导入数据。"""
    from modules.ai_narrative import (VISION_MAX_TOKENS, display_report,
                                      resolve_vision_config)

    st.subheader("[读图] AI 读图解析")
    st.caption("上传气象图（天气图 / 卫星云图 / 雷达回波 / 模式形势图），"
               "由多模态模型输出六段式结构化解读。本页不需要先导入数据。")
    st.info("隐私提示：上传的图片会发送至所配置的 AI 服务商。"
            "含涉密或未公开信息的图片请勿上传。")

    cfg = resolve_vision_config()
    if cfg is None:
        st.warning(_SETUP_HINT)
        _render_failure_table()
        return

    uploads = st.file_uploader(
        "上传气象图（最多 %d 张，单图 5 MB 以内）" % MAX_IMAGES,
        type=ALLOWED_UPLOAD_TYPES, accept_multiple_files=True,
        key="chart_reader_uploader")

    images = []
    if uploads:
        if len(uploads) > MAX_IMAGES:
            st.error("最多上传 %d 张，当前选了 %d 张，请先精简后再上传。"
                     % (MAX_IMAGES, len(uploads)))
        else:
            for item in uploads:
                images.append(process_image(item.getvalue(),
                                            item.name or "未命名"))
    st.session_state["chart_reader_images"] = images

    if images:
        st.write("**图片处理结果**")
        rows = []
        for item in images:
            rows.append({
                "文件名": item["name"],
                "状态": "✓ 已就绪" if item["ok"] else "✗ " + (item["error"] or "失败"),
                "原始 (KB)": item["orig_kb"],
                "提交 (KB)": item["new_kb"],
                "尺寸": ("%d × %d" % (item["width"], item["height"]))
                        if item["width"] else "—",
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)

    ok_images = [item for item in images if item.get("ok")]
    total_error = check_total_size(images)
    if total_error:
        st.error(total_error)

    note = st.text_area("补充说明（可选，最多 500 字）",
                        placeholder="例如：这是 500hPa 高空图，请重点关注槽脊位置与急流",
                        max_chars=500, key="chart_reader_note")

    count = int(st.session_state.get("chart_reader_gen_count", 0) or 0)
    tokens = estimate_image_tokens(ok_images)
    total_usage = st.session_state.get("chart_reader_usage_total") or {}
    remaining = max(0, MAX_GENERATIONS_PER_SESSION - count)
    st.caption("本会话已尝试 %d/%d 次（剩余 %d 次）；本次就绪图片 %d 张，"
               "提交合计约 %d KB，估算图像 token ≈ %d。"
               % (count, MAX_GENERATIONS_PER_SESSION, remaining,
                  len(ok_images), sum(item["new_kb"] for item in ok_images), tokens))
    if total_usage.get("completion"):
        cap_note = "单次输出上限 %s token" % format(
            VISION_MAX_TOKENS, ",") if VISION_MAX_TOKENS else ""
        st.caption("本会话累计消耗 %s。%s"
                   % (format_usage(total_usage), cap_note))
    else:
        st.caption("单次输出上限 %s token；失败调用同样计费，故按尝试次数计数。"
                   % format(VISION_MAX_TOKENS, ","))

    disabled = (not ok_images) or bool(total_error) \
        or count >= MAX_GENERATIONS_PER_SESSION
    if remaining <= 0:
        st.warning("本会话尝试次数已用完（%d 次）。刷新页面可重置，"
                   "但每次调用都会真实计费，请留意用量。"
                   % MAX_GENERATIONS_PER_SESSION)
    if st.button("生成读图解析", key="chart_reader_generate", type="primary",
                 disabled=disabled, use_container_width=True):
        _generate(cfg, ok_images, note)

    text = st.session_state.get("chart_reader_text")
    meta = st.session_state.get("chart_reader_meta")
    if text and meta:
        display_report(text, meta, ok_images)

    if not ok_images and not uploads:
        st.caption("上传图片后即可生成解读。支持 PNG / JPEG / WebP，"
                   "建议长边不低于 200 像素、不超过 1600 像素以获得最佳识别效果。")

    _render_failure_table()
