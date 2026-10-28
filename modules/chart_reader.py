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
import hashlib
import io
import time
from collections import OrderedDict

import streamlit as st

from PIL import Image

# 上传与体积上限（2026-10-22 配额调整：5 张 / 单图 1.5 MB）
MAX_IMAGES = 5
MAX_IMAGE_BYTES = int(1.5 * 1024 * 1024)  # 单图上限：原始字节与提交字节同一阈值
MAX_RAW_BYTES = MAX_IMAGE_BYTES           # 解码前闸门，超过直接拒绝，不解码
MAX_TOTAL_BYTES = MAX_IMAGES * MAX_IMAGE_BYTES  # 提交合计上限（5 × 1.5 MB = 7.5 MB）
# 安全修复（SEC-13）：5000 万像素在解码/转 RGB/LANCZOS 时峰值可达数百 MB，
# 单张就足以在 1GB 实例上触发 OOM；收紧到 1600 万像素。
MAX_PIXELS = 16 * 1000 * 1000         # 解码后的像素数上限
MAX_EDGE_PX = 1600                    # 长边上限（保等值线数值与坐标标注可读）
MIN_EDGE_PX = 200                     # 长边下限（低于此无解析价值）
JPEG_QUALITY = 88

# 处理结果缓存：按原始字节哈希，避免每次 rerun 重复解码/重编码（SEC-13）
_PROCESS_CACHE = OrderedDict()
_PROCESS_CACHE_MAX = 12

ALLOWED_UPLOAD_TYPES = ["png", "jpg", "jpeg", "webp"]

# 可原样提交的输入格式。WebP 不在其中：python-docx 无法把 WebP 嵌进导出的 docx。
_PASSTHROUGH_MIMES = {"PNG": "image/png", "JPEG": "image/jpeg"}

# 单次生成的会话限制
MIN_INTERVAL_SECONDS = 60
# 每会话最多尝试 10 次，与每日次数上限对齐，避免「每日十次」被会话级上限截成五次。
# 计的是「尝试」而非「成功」：失败调用同样被服务商计费，只数成功就会让反复失败
# 不计入额度。会话级限制刷新页面即重置，属防误操作级别，不是成本控制——真正的
# 硬配额在服务端（见 sql/schema.sql 第 9 节），刷新无法绕过。
MAX_GENERATIONS_PER_SESSION = 10

# 单次输出预算要留给 prompt 与估算误差的余量
SAFETY_MARGIN_TOKENS = 2000

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


def _has_private_metadata(img) -> bool:
    """图片是否带有 EXIF/文本块等可识别信息（SEC-14）。

    ICC 色彩配置不属于隐私信息，不在此列；EXIF（含 GPS）、PNG 文本块
    会被原样送第三方 LLM 并嵌入 docx，必须在提交前剥离。
    """
    try:
        if len(img.getexif() or {}) > 0:
            return True
    except Exception:
        pass
    try:
        if getattr(img, "text", None):
            return True
    except Exception:
        pass
    info = getattr(img, "info", {}) or {}
    return any(key in info and info[key] for key in ("exif", "comment", "text"))


def process_image(raw, name):
    """带缓存的图片处理入口（SEC-13）：同一份字节只解码/重编码一次。"""
    try:
        key = hashlib.sha256(raw).hexdigest() + "|" + str(name or "")[:80]
    except Exception:
        key = None
    if key is not None:
        cached = _PROCESS_CACHE.get(key)
        if cached is not None:
            _PROCESS_CACHE.move_to_end(key)
            return dict(cached)
    result = _process_image_uncached(raw, name)
    if key is not None:
        _PROCESS_CACHE[key] = dict(result)
        _PROCESS_CACHE.move_to_end(key)
        while len(_PROCESS_CACHE) > _PROCESS_CACHE_MAX:
            _PROCESS_CACHE.popitem(last=False)
    return result


def _process_image_uncached(raw, name):
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
        return _fail(name, "文件过大（原始 %.2f MiB，上限 %.1f MiB），请先自行压缩后上传"
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

            if (not resized and source_format in _PASSTHROUGH_MIMES
                    and not _has_private_metadata(img)):
                # 安全修复（SEC-14）：无隐私元数据才原样透传；否则走重编码剥离
                data = raw
                mime = _PASSTHROUGH_MIMES[source_format]
                kept_original = True
            else:
                data, mime = _encode_smallest(img)
                kept_original = False
    except Exception:  # noqa: BLE001 - 损坏文件在 resize/convert 阶段也可能失败
        return _fail(name, "图片处理失败（文件可能已损坏或不完整）", len(raw))

    if len(data) > MAX_IMAGE_BYTES:
        return _fail(name, "处理后的字节仍超过单图上限（%.2f MiB > %.1f MiB），请先自行压缩后上传"
                     % (len(data) / 1048576.0, MAX_IMAGE_BYTES / 1048576.0), len(raw))

    return {"name": name, "ok": True, "error": None,
            "orig_kb": orig_kb, "new_kb": max(1, len(data) // 1024),
            "width": width, "height": height,
            "data_bytes": data, "mime": mime, "kept_original": kept_original}


def check_total_size(images):
    """合计体积校验：只统计成功的图片；超限返回提示文本，否则 None。"""
    total_kb = sum(item.get("new_kb", 0) for item in images if item.get("ok"))
    if total_kb * 1024 > MAX_TOTAL_BYTES:
        return ("提交合计 %.1f MiB，超过上限 %.1f MiB，请减少图片张数或先自行压缩"
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


# ============================================================
# 服务端每日配额（见 sql/schema.sql 第 9 节）
# 只有拿到服务端预留的预算与调用标识后才允许访问模型。
# ============================================================

def quota_allows(state, user_key=""):
    """返回是否允许调用及原因；预留失败时停止付费请求。"""
    if state:
        if state.get("allowed") and state.get("call_id") and state.get("reserved_tokens", 0) > 0:
            return True, ""
        return False, str(state.get("message") or "今日读图配额已用完。")
    return False, "配额服务暂不可用，本次未发起模型请求，请稍后重试。"


def quota_budget(state, prompt_tokens=0):
    """从本次已预留预算扣除输入估算和安全余量；返回 0 时停止调用。"""
    if not state:
        return 0
    remaining = state.get("reserved_tokens")
    if remaining is None:
        return 0
    try:
        remaining = int(remaining)
    except (TypeError, ValueError):
        return 0
    try:
        reserve = max(int(prompt_tokens or 0), 0)
    except (TypeError, ValueError):
        reserve = 0
    cap = remaining - SAFETY_MARGIN_TOKENS - reserve
    if cap <= 0:
        return 0
    return cap


def format_daily_quota(state):
    """今日配额状态的人话描述；state 不可用时返回空串。"""
    if not state:
        return ""
    line = ("今日读图已用 %s/%s 次（剩余 %s）· token %s/%s"
            % (state.get("calls_used", 0), state.get("calls_limit", 0),
               state.get("calls_remaining", 0),
               format(int(state.get("tokens_used") or 0), ","),
               format(int(state.get("tokens_limit") or 0), ",")))
    if state.get("tokens_reserved"):
        line += "（处理中预留 %s）" % format(int(state["tokens_reserved"]), ",")
    return line


def daily_quota_exhausted(state):
    """今日配额是否已用尽。state 为 None（服务不可用）时返回 False，交由放行逻辑。"""
    if not state:
        return False
    try:
        return int(state.get("calls_remaining") or 0) <= 0 \
            or int(state.get("tokens_remaining") or 0) <= 0
    except (TypeError, ValueError):
        return False


# ============================================================
# 报告与图片的对应关系
# 报告说的是「这一次」上传的图，这个对应关系在生成那一刻就固定了。上传区却会被
# 任意一次重跑清空（用户换标签、点别的控件），若导出时读当前上传区，docx 会静默
# 丢掉原图，与手册承诺的「导出 Word（含原图）」不符。因此在生成成功时把这批图
# 固化进会话，导出读缓存；缓存为空（刚上传、还没生成）时才退回当前上传区。
# ============================================================

def cached_report_images(images):
    """固化生成时那批图，只保留导出需要的字段，跳过硬失败或无字节的条目。"""
    kept = []
    for item in images or []:
        data = item.get("data_bytes")
        if not data:
            continue
        kept.append({"name": item.get("name", "未命名"),
                     "data_bytes": data,
                     "mime": item.get("mime")})
    return kept


def report_images_for_export(cached, current):
    """导出用哪批图：优先用生成时缓存的那批，没有缓存才用当前上传区。"""
    if cached:
        return list(cached)
    return list(current or [])


def build_chart_prompt(images_meta, user_note):
    """构造读图 prompt：六段固定结构 + 反幻觉硬约束。"""
    lines = [
        "你是一名气象业务分析师。下面会给出用户上传的气象图（天气图、卫星云图、"
        "雷达回波、模式形势图等）。请**只依据图面可见信息**输出结构化解读。",
        "",
        "JSON 的 sections 必须严格包含以下六段，title 使用括号内标题文字：",
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
        lines.append("- 图 %d（image_id=img_%d）：%s（%s × %s 像素）"
                     % (index, index, meta.get("name", "未命名"),
                        meta.get("width", "?"), meta.get("height", "?")))
    note = (user_note or "").strip()
    if note:
        lines += ["", "用户补充说明（请优先结合它判读）：", note]
    lines += ["", "只输出一个 JSON 对象，不附带代码围栏。结构如下，示例占位内容须替换为本次图面内容：",
              '{"schema_version":1,"findings":[{"id":"F1","text":"简洁核心结论",'
              '"kind":"visible","evidence_ids":["E1"],"limitation_ids":["L1"]}],'
              '"evidence":[{"id":"E1","image_id":"img_1","location":"原图中的具体位置",'
              '"feature":"在该位置可直接看见的图例、数值或形态"}],'
              '"limitations":[{"id":"L1","missing":"缺失或读不清的信息",'
              '"impact":"这会限制哪项结论","next_input":"建议补充的图像或信息"}],'
              '"sections":[{"title":"图像信息","body":"正文"},'
              '{"title":"图面要素识别","body":"正文"},{"title":"主要分布特征","body":"正文"},'
              '{"title":"关键数值与极值","body":"正文"},{"title":"趋势与演变","body":"正文"},'
              '{"title":"风险提示与结论","body":"正文"}]}',
              "核心结论最多 3 条，依据最多 8 条，不确定性最多 4 条。每条结论必须引用实际存在的依据编号。",
              "kind=visible 表示图面描述；kind=conditional 表示条件性推断，必须引用限制编号。",
              "至少说明一项适用边界；不给出数值置信度，不输出未经核验的框选坐标。所有引用只使用本次 img_1…img_N。",
              "若图不可判读，直接说明不可判读及原因，不为了填满结构编造结论。"]
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
| 整体拒绝上传 | 张数超过 5 张、单图超过 1.5 MiB，或提交合计超过 7.5 MiB | 减少张数或先自行压缩 |
| 生成失败并给出可读错误 | 模型服务超时、密钥无效、当日额度不足，或输出被服务商截断 | 原图已保留，可直接重试；错误文本会带出 `finish_reason`、模型名与响应片段，据此处置；当日 token 不足可次日再试或请管理员调整每日配额 |
| 解读里出现「图中未标注」 | 图中确实没有该信息 | 这是刻意的反幻觉约束，不是故障 |
| 解读与图不符 | 模型判读能力有限，尤其是等值线密集或非中文标注的图 | 在补充说明里指明图种、层次与关注点可显著改善 |
"""


def _render_failure_table():
    with st.expander("常见失败原因与处理", expanded=False):
        st.markdown(_FAILURE_TABLE)


def _record_usage(usage, call_id):
    """把一次调用的用量并入会话累计、写回服务端，并记下最近一次。

    必须在成功与失败两条路径上都调用：服务商对失败的调用同样计费。
    服务端写入失败只提示、不阻断——解读结果已经拿到，不该因为记账失败而丢弃。
    """
    from db import record_vision_usage

    last = merge_usage(None, usage)
    total = merge_usage(st.session_state.get("chart_reader_usage_total"), usage)
    st.session_state["chart_reader_usage_last"] = last
    st.session_state["chart_reader_usage_total"] = total
    pending = st.session_state.get("_pending_vision_usage", {})
    if not record_vision_usage(usage, call_id):
        pending[call_id] = usage
        st.caption("本次用量暂未结算，预算仍保留；重新打开此页会重试结算。")
    else:
        pending.pop(call_id, None)
    st.session_state["_pending_vision_usage"] = pending
    if not usage:
        st.caption("服务商未返回可靠用量，本次按预留预算计入每日配额。")
    return last, total


def _generate(cfg, images, note):
    """执行一次读图解析。失败即报错并保留原图，不产出任何替代文本。"""
    from db import begin_vision_call
    from modules.ai_narrative import build_report_meta, call_vision_llm

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

    # 服务端每日配额：先占后用，避免并发下多个标签同时穿透
    quota_state = begin_vision_call()
    _uid = (st.session_state.get("auth_user") or {}).get("id") or "anonymous"
    allowed, notice = quota_allows(quota_state, _uid)
    if notice:
        (st.warning if allowed else st.error)(notice)
    if not allowed:
        return
    # 安全修复（SEC-24）：预算要预留本次图片 prompt 的开销，否则实际总量会超配额。
    # 不再叠加固定单次上限：本次预算就是当日剩余额度。
    prompt = build_chart_prompt(images, note)
    budget = quota_budget(quota_state, estimate_image_tokens(images) + len(prompt.encode("utf-8")) + 800)
    if budget <= 0:
        _record_usage({"total": 0}, quota_state["call_id"])
        st.warning("今日 token 剩余额度不足以再生成一次，"
                   "请次日再试或联系管理员调整配额。")
        return

    data_urls = [image_to_data_url(item["data_bytes"], item["mime"])
                 for item in images]

    usage = {}
    with st.spinner("正在读图解析，通常需要十几秒..."):
        try:
            text = call_vision_llm(prompt, data_urls, cfg["api_key"],
                                   base_url=cfg["base_url"], model=cfg["model"],
                                   max_tokens=budget, usage_out=usage)
        except Exception as exc:  # noqa: BLE001 - 任何失败都报错，不降级
            _record_usage(usage, quota_state["call_id"])
            st.session_state["chart_reader_gen_count"] = count + 1
            detail = str(exc).strip() or exc.__class__.__name__
            st.error("读图解析失败：%s" % detail[:200])
            spent = int(usage.get("completion") or 0)
            st.caption("本次尝试仍会被服务商计费%s。原图已保留，可直接重试。"
                       "本功能**不提供文本模型降级**——文本模型读不了图，"
                       "编造的摘要会误导判断。"
                       % ("（消耗 %s）" % format_usage(usage) if spent else ""))
            return

    _record_usage(usage, quota_state["call_id"])
    from modules.ai_report_model import decode_report, freeze_images, input_fingerprint
    frozen = freeze_images(images)
    st.session_state["chart_reader_text"] = text
    st.session_state["chart_reader_meta"] = build_report_meta(
        "上传气象图 %d 张（模型：%s）" % (len(images), cfg["model"]))
    # 固化当次图片：报告与图片的对应关系在此刻固定，导出不再依赖上传区现状
    st.session_state["chart_reader_report_images"] = frozen
    st.session_state["chart_reader_result"] = decode_report(text, frozen)
    st.session_state["chart_reader_input_fingerprint"] = input_fingerprint(images, note)
    st.session_state.pop("chart_reader_selected_evidence", None)
    st.session_state["chart_reader_last_gen"] = time.time()
    st.session_state["chart_reader_gen_count"] = count + 1


def render_chart_reader_tab():
    """Upload and review share one immutable result snapshot; no calls on layout changes."""
    from modules.ai_narrative import resolve_vision_config
    from modules.ai_report_model import decode_report, input_fingerprint
    from modules.ui.ai_result import render_ai_result
    from modules.ui.shell import page_heading
    from db import record_vision_usage, get_vision_quota

    pending = st.session_state.get("_pending_vision_usage", {})
    for call_id, usage in list(pending.items()):
        if record_vision_usage(usage, call_id):
            pending.pop(call_id, None)
    st.session_state["_pending_vision_usage"] = pending
    cfg = resolve_vision_config()
    has_result = bool(st.session_state.get("chart_reader_text"))
    if has_result:
        title, settings = st.columns([3, 1], vertical_alignment="center")
        with title:
            page_heading("AI 读图解析", "以原图为依据，突出核心结论、图面特征和判断边界。")
        input_panel = settings.popover("上传图片与解读设置", width="stretch")
    else:
        page_heading("AI 读图解析", "以原图为依据，突出核心结论、图面特征和判断边界。")
        input_panel = st.container(border=True)
    with input_panel:
        left, right = st.columns([1.15, 1])
        with left:
            st.markdown("#### 气象图像")
            version = st.session_state.get("chart_reader_upload_version", 0)
            uploads = st.file_uploader("上传气象图（最多 5 张，单图 1.5 MiB 以内）", type=ALLOWED_UPLOAD_TYPES,
                                      accept_multiple_files=True, max_upload_size=2, key=f"chart_input_upload_{version}")
            st.caption("单图实际限制 1.5 MiB，合计 7.5 MiB；上传器显示的 2 MB 为传输上限。")
            images = list(st.session_state.get("chart_reader_images") or [])
            upload_error = ""
            if uploads:
                if len(uploads) > MAX_IMAGES:
                    upload_error = f"最多上传 {MAX_IMAGES} 张，当前选了 {len(uploads)} 张，请精简后再生成。"
                    st.error(upload_error)
                else:
                    images = [process_image(item.getvalue(), item.name or "未命名") for item in uploads]
                    st.session_state["chart_reader_images"] = images
            ok_images = [item for item in images if item.get("ok")]
            if ok_images:
                names = [f"图 {i + 1} · {item['name']}" for i, item in enumerate(ok_images)]
                index = st.selectbox("预览原图", range(len(ok_images)), format_func=lambda i: names[i], key="chart_reader_input_preview")
                st.image(ok_images[index]["data_bytes"], caption=names[index], width="stretch")
            else:
                st.info("添加天气图、卫星云图、雷达回波或模式形势图。图例、单位和时间标注越清楚，越便于核查。")
            if images:
                with st.expander("图片处理详情"):
                    st.dataframe([{"文件名": i["name"], "状态": "已就绪" if i["ok"] else i.get("error", "失败"),
                                   "原始 (KB)": i["orig_kb"], "提交 (KB)": i["new_kb"],
                                   "尺寸": f"{i['width']} × {i['height']}" if i.get("width") else "—"} for i in images],
                                 hide_index=True, width="stretch")
                if st.button("清空待解析图片", key="chart_reader_clear"):
                    st.session_state["chart_reader_images"] = []
                    st.session_state["chart_reader_upload_version"] = version + 1
                    st.rerun()
        with right:
            st.markdown("#### 解读关注点")
            if "chart_reader_note" not in st.session_state:
                st.session_state["chart_reader_note"] = st.session_state.get("chart_reader_note_saved", "")
            note = st.text_area("补充说明", placeholder="例如：500 hPa 形势图，请关注槽脊位置、数值标注与可能影响。",
                                max_chars=500, height=140, key="chart_reader_note", label_visibility="collapsed",
                                on_change=lambda: st.session_state.update(chart_reader_note_saved=st.session_state["chart_reader_note"]))
            total_error = check_total_size(images) or upload_error
            if total_error:
                st.error(total_error)
            count = int(st.session_state.get("chart_reader_gen_count", 0) or 0)
            remaining = max(0, MAX_GENERATIONS_PER_SESSION - count)
            quota_state = get_vision_quota() if cfg else None
            quota_line = format_daily_quota(quota_state)
            if quota_line:
                st.caption(quota_line + " · 每日北京时间 0 点重置")
            daily_blocked = daily_quota_exhausted(quota_state)
            if not cfg:
                st.info("读图服务尚未配置。可以准备图片，配置完成后再生成。")
                with st.expander("服务配置说明"):
                    st.markdown(_SETUP_HINT)
            if daily_blocked:
                st.warning("今日额度暂不可用；若存在待结算请求，请等待结算完成。")
            disabled = not cfg or not ok_images or bool(total_error) or daily_blocked or remaining <= 0
            st.caption("点击生成后，图片及补充说明会发送至已配置的 AI 服务商。")
            if st.button("生成读图解析", key="chart_reader_generate", type="primary", icon=":material/auto_awesome:",
                         disabled=disabled, width="stretch"):
                _generate(cfg, ok_images, note)
            with st.expander("额度与图片提交详情"):
                st.caption(f"本会话已尝试 {count}/{MAX_GENERATIONS_PER_SESSION} 次，剩余 {remaining} 次。就绪图片 {len(ok_images)} 张。")
                st.caption(f"提交合计约 {sum(i['new_kb'] for i in ok_images)} KiB，估算图像 token ≈ {estimate_image_tokens(ok_images)}。")
                st.caption("失败调用也可能消耗服务商用量；以返回的实际用量和服务端结算为准。")
                total_usage = st.session_state.get("chart_reader_usage_total") or {}
                if total_usage:
                    st.caption("本会话累计 " + format_usage(total_usage))
                if pending:
                    st.caption("有待结算请求，预算仍保留；重新进入本页时会重试结算。")
            st.markdown("**完整解读结构**")
            st.caption("图像信息 · 图面要素 · 分布特征 · 数值与极值 · 趋势演变 · 风险与结论")
    text = st.session_state.get("chart_reader_text")
    meta = st.session_state.get("chart_reader_meta")
    if text and meta:
        # Empty legacy snapshots must not be rebound to a later upload.
        frozen = report_images_for_export(st.session_state.get("chart_reader_report_images"), [])
        model = st.session_state.get("chart_reader_result")
        if not model or model.get("raw_response") != text:
            model = decode_report(text, frozen)
        generated_fp = st.session_state.get("chart_reader_input_fingerprint")
        if generated_fp and generated_fp != input_fingerprint(ok_images, note):
            st.info("待解析图片或关注点已改变；下方保留上次生成结果及其原图，重新生成后更新。")
        render_ai_result(model, meta, frozen)
    _render_failure_table()
