"""AI 读图解析：图片校验与压缩、读图 prompt 构造、页面渲染。

设计要点：
- 图片全程在内存处理，不落盘；三重上限分别是原始字节、压缩后单图、压缩后合计。
- 先按原始字节设闸再解码，避免解压炸弹；随后用 PIL 的 verify() 做魔数校验，
  不信任文件扩展名与 MIME。
- 只做一次压缩，不做二次降质重试——否则用户无从判断画质损失。
- 视觉调用失败时**不生成任何替代文本**：文本模型读不了图，编造摘要等同幻觉。
"""

import base64
import io

from PIL import Image

# 上传与体积上限
MAX_IMAGES = 3
MAX_RAW_BYTES = 20 * 1024 * 1024      # 原始字节硬上限，超过直接拒绝，不解码
MAX_IMAGE_BYTES = 5 * 1024 * 1024     # 压缩后单图上限
MAX_TOTAL_BYTES = 12 * 1024 * 1024    # 压缩后合计上限
MAX_PIXELS = 50 * 1000 * 1000         # 解码后的像素数上限
MAX_EDGE_PX = 1600                    # 长边上限（保等值线数值与坐标标注可读）
MIN_EDGE_PX = 200                     # 长边下限（低于此无解析价值）
JPEG_QUALITY = 88

ALLOWED_UPLOAD_TYPES = ["png", "jpg", "jpeg", "webp"]

# 单次生成的会话限制
MIN_INTERVAL_SECONDS = 60
MAX_GENERATIONS_PER_SESSION = 10

_SECTIONS = ("【图像信息】", "【图面要素识别】", "【主要分布特征】",
             "【关键数值与极值】", "【趋势与演变】", "【风险提示与结论】")


def _fail(name, message, orig_bytes=0):
    return {"name": name, "ok": False, "error": message,
            "orig_kb": max(0, orig_bytes // 1024), "new_kb": 0,
            "width": 0, "height": 0, "jpeg_bytes": None}


def process_image(raw, name):
    """校验并压缩一张上传图片。

    返回 {"name", "ok", "error", "orig_kb", "new_kb", "width", "height", "jpeg_bytes"}。
    失败时 ok 为 False 且 error 给出可读原因；成功时 jpeg_bytes 为压缩后的 JPEG 字节。
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
            if width * height > MAX_PIXELS:
                return _fail(name, "图片像素数过大（%.0f 万像素，上限 %.0f 万），请先缩小后上传"
                             % (width * height / 10000.0, MAX_PIXELS / 10000.0), len(raw))

            long_edge = max(width, height)
            if long_edge < MIN_EDGE_PX:
                return _fail(name, "分辨率过低（长边 %d 像素，至少需要 %d 像素），无法解析"
                             % (long_edge, MIN_EDGE_PX), len(raw))

            if long_edge > MAX_EDGE_PX:
                scale = MAX_EDGE_PX / float(long_edge)
                width = max(1, int(round(width * scale)))
                height = max(1, int(round(height * scale)))
                img = img.resize((width, height), Image.LANCZOS)

            buffer = io.BytesIO()
            img.convert("RGB").save(buffer, format="JPEG",
                                    quality=JPEG_QUALITY, optimize=True)
            data = buffer.getvalue()
    except Exception:  # noqa: BLE001 - 损坏文件在 resize/convert 阶段也可能失败
        return _fail(name, "图片处理失败（文件可能已损坏或不完整）", len(raw))

    if len(data) > MAX_IMAGE_BYTES:
        return _fail(name, "压缩后仍超过单图上限（%.2f MB > %.0f MB），请先自行压缩后上传"
                     % (len(data) / 1048576.0, MAX_IMAGE_BYTES / 1048576.0), len(raw))

    return {"name": name, "ok": True, "error": None,
            "orig_kb": orig_kb, "new_kb": max(1, len(data) // 1024),
            "width": width, "height": height, "jpeg_bytes": data}


def check_total_size(images):
    """合计体积校验：只统计成功的图片；超限返回提示文本，否则 None。"""
    total_kb = sum(item.get("new_kb", 0) for item in images if item.get("ok"))
    if total_kb * 1024 > MAX_TOTAL_BYTES:
        return ("压缩后合计 %.1f MB，超过上限 %.0f MB，请减少图片张数或先自行压缩"
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


def image_to_data_url(jpeg_bytes):
    """压缩后的 JPEG 字节 → OpenAI 兼容的 data URL。"""
    return "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes).decode("ascii")
