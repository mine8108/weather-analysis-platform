"""
气象报文解码模块：SYNOP、METAR 标准编码报文解析
"""

import streamlit as st
from datetime import datetime, timezone


def _report_time(day, hour, minute=0, reference_time=None):
    """报文只含日时分；选择距参考 UTC 时刻最近的合法相邻月份。"""
    reference = reference_time or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    reference = reference.astimezone(timezone.utc)
    candidates = []
    for offset in (-1, 0, 1):
        month_index = reference.year * 12 + reference.month - 1 + offset
        year, month = divmod(month_index, 12)
        try:
            candidates.append(datetime(year, month + 1, day, hour, minute, tzinfo=timezone.utc))
        except ValueError:
            continue
    if not candidates:
        raise ValueError("报文日期或时分无效")
    return min(candidates, key=lambda value: abs(value - reference))


class _DecodedResult(dict):
    """Capture the token at the actual assignment site without re-parsing heuristics."""
    def __init__(self, provenance):
        super().__init__(station_id="UNKNOWN", timestamp=None)
        self.provenance = provenance
        self.source = None

    def set_source(self, index, token):
        self.source = {"index": index, "token": token}

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        if self.provenance is not None and self.source is not None:
            if value is None:
                self.provenance.pop(key, None)
            else:
                self.provenance[key] = dict(self.source)


def decode_synop(report, reference_time=None, *, provenance=None):
    """解码 SYNOP 陆地地面天气报告（简化版）。

    支持 FM-12 SYNOP 基本段：
    AAXX YYGGiw IIiii iRixhVV Nddff 1sTTT 2sTdTdTd 3PPPP 6RRR1

    修复 R-15：
    - 报文头顺序改为 YYGGiw → IIiii（原实现把日期组当区站号、把区站号当日期组）
    - 补上 Nddff 组解析（总云量 / 风向 / 风速），并按 iw 区分 m/s 与节
    - wind_indicator 初始化到函数顶部，缺日期组时不再抛 UnboundLocalError
    - 温度 / 露点符号规则改为「0 为正、1 为负」（原实现把 0~4 全当正号）
    - iRixhVV 的 h 是云底高度码，不再被误当成总云量
    """
    result = _DecodedResult(provenance)
    wind_indicator = None

    try:
        tokens = report.strip().split()

        if not tokens:
            return result, ["报文为空"]

        idx = 0

        # AAXX 标识组 (如果存在)
        if tokens[idx] in ["AAXX", "BBXX"]:
            idx += 1

        # YYGGiw - 日期 / 小时 / 风力指示码
        if idx < len(tokens) and len(tokens[idx]) == 5 and tokens[idx].isdigit():
            group = tokens[idx]
            result.set_source(idx, group)
            try:
                day = int(group[0:2])
                hour = int(group[2:4])
                wind_indicator = int(group[4])
                if 1 <= day <= 31 and 0 <= hour <= 23:
                    result["timestamp"] = _report_time(day, hour, reference_time=reference_time)
            except (ValueError, IndexError):
                pass
            idx += 1

        # IIiii - 区站号
        if idx < len(tokens) and len(tokens[idx]) == 5 and tokens[idx].isdigit():
            result.set_source(idx, tokens[idx])
            result["station_id"] = tokens[idx]
            idx += 1

        # iRixhVV - 降水指示 / 天气指示 / 云底高 / 能见度
        if idx < len(tokens) and len(tokens[idx]) == 5:
            group = tokens[idx]
            result.set_source(idx, group)
            try:
                vis_code = int(group[3:5]) if group[3:5].isdigit() else None

                if vis_code is not None:
                    # SYNOP 能见度码转换表（简化；VV=0 表示能见度 <0.1 km）
                    vis_table = {
                        0: 0.05, 90: 0.05, 91: 0.05, 92: 0.2, 93: 0.5, 94: 1.0,
                        95: 2.0, 96: 4.0, 97: 10.0, 98: 20.0, 99: 50.0,
                    }
                    if 1 <= vis_code <= 50:
                        result["visibility"] = vis_code / 10.0  # 0.1 km 为单位
                    elif 56 <= vis_code <= 80:
                        result["visibility"] = float(vis_code - 50)
                    elif 81 <= vis_code <= 89:
                        result["visibility"] = float(30 + (vis_code - 80) * 5)
                    elif vis_code in vis_table:
                        result["visibility"] = vis_table[vis_code]
            except (ValueError, IndexError):
                pass
            idx += 1

        # Nddff - 总云量(N) / 风向(dd) / 风速(ff)
        if (idx < len(tokens) and len(tokens[idx]) == 5
                and all(char in "0123456789/" for char in tokens[idx])):
            group = tokens[idx]
            result.set_source(idx, group)
            try:
                # WMO 2700 的十分量对照；区间采用代表值，不能把码值直接当云量成数。
                # https://www.nodc.noaa.gov/gtspp/document/codetbls/wmocodes/table2700.html
                # N=9 为天空遮蔽，/ 为无法判断或未观测，均保留缺失。
                cloud_tenths = {"0": 0.0, "1": 1.0, "2": 2.5, "3": 4.0,
                                "4": 5.0, "5": 6.0, "6": 7.5, "7": 9.0, "8": 10.0}
                result["cloud_cover"] = cloud_tenths.get(group[0])
                dd = int(group[1:3]) if group[1:3].isdigit() else None
                ff = int(group[3:5]) if group[3:5].isdigit() else None
                result["wind_direction"] = None if dd in (None, 99) else dd * 10
                if ff is None:
                    result["wind_speed"] = None
                elif wind_indicator in (3, 4):  # 单位为节
                    result["wind_speed"] = round(ff * 0.514444, 1)
                else:  # iw 0/1 为 m/s
                    result["wind_speed"] = float(ff)
            except (ValueError, IndexError):
                pass
            idx += 1

        # 在报文中搜索温度组 (1sTTT)
        for token_index, token in enumerate(tokens[idx:], start=idx):
            result.set_source(token_index, token)
            if len(token) == 5 and token[0] == "1":
                try:
                    sign = -1 if token[1] == "1" else 1
                    result["temperature"] = int(token[2:]) / 10.0 * sign
                    break
                except (ValueError, IndexError):
                    continue

        # 露点组 (2sTdTdTd)
        for token_index, token in enumerate(tokens[idx:], start=idx):
            result.set_source(token_index, token)
            if len(token) == 5 and token[0] == "2":
                try:
                    sign = -1 if token[1] == "1" else 1
                    result["dewpoint"] = int(token[2:]) / 10.0 * sign
                    break
                except (ValueError, IndexError):
                    continue

        # 气压组 (3PPPP 或 4PPPP)
        for token_index, token in enumerate(tokens[idx:], start=idx):
            result.set_source(token_index, token)
            if len(token) == 5 and token[0] == "3":
                try:
                    pres = int(token[1:]) / 10.0
                    result["pressure"] = pres if pres > 500 else pres + 1000
                    break
                except (ValueError, IndexError):
                    continue

        # 降水量组 (6RRR1)
        for token_index, token in enumerate(tokens[idx:], start=idx):
            result.set_source(token_index, token)
            if len(token) >= 4 and token[0] == "6":
                try:
                    precip = int(token[1:4])
                    result["precipitation"] = precip if precip < 990 else (precip - 990) / 10.0
                    break
                except (ValueError, IndexError):
                    continue

        # 现在天气组 (7wwWW)：天气现象码的真正来源
        # （原实现误把 iRixhVV 的 R+ix 两位当作天气码）
        for token_index, token in enumerate(tokens[idx:], start=idx):
            result.set_source(token_index, token)
            if len(token) == 5 and token[0] == "7":
                try:
                    result["weather_code"] = int(token[1:3])
                    break
                except (ValueError, IndexError):
                    continue

    except Exception as e:
        return result, [f"解析出错: {str(e)}"]

    return result, []


def decode_metar(report, reference_time=None, *, provenance=None):
    """
    解码 METAR/SPECI 航空气象报告（简化版）
    """
    result = _DecodedResult(provenance)

    try:
        tokens = report.strip().split()

        if not tokens:
            return result, ["报文为空"]

        # METAR/SPECI 标识
        idx = 0
        if tokens[idx] in ["METAR", "SPECI"]:
            idx += 1

        # 机场 ICAO 码
        if idx < len(tokens) and len(tokens[idx]) == 4 and tokens[idx].isalpha():
            result.set_source(idx, tokens[idx])
            result["station_id"] = tokens[idx]
            idx += 1

        # 日期时间组 (DDHHMMZ)
        if idx < len(tokens) and len(tokens[idx]) == 7 and tokens[idx].endswith("Z"):
            group = tokens[idx]
            result.set_source(idx, group)
            try:
                day = int(group[0:2])
                hour = int(group[2:4])
                minute = int(group[4:6])
                result["timestamp"] = _report_time(day, hour, minute, reference_time)
            except (ValueError, IndexError):
                pass
            idx += 1

        # 遍历剩余组
        for token_index, token in enumerate(tokens[idx:], start=idx):
            result.set_source(token_index, token)
            token = token.strip()

            # 风向风速组 (dddssKT 或 dddssGggKT 或 VRBssKT)
            if (token.endswith("KT") or token.endswith("MPS")) and (
                token[:3].isdigit() or token[:3] == "VRB"
            ):
                try:
                    if token[:3] == "VRB":
                        result["wind_direction"] = None
                    else:
                        result["wind_direction"] = int(token[:3])

                    speed_part = token[3:]
                    is_knots = "KT" in speed_part
                    clean = speed_part.replace("KT", "").replace("MPS", "").strip()

                    if not clean:
                        continue

                    if "G" in clean:
                        parts = clean.split("G")
                        result["wind_speed"] = float(parts[0]) if parts[0] else None
                    else:
                        result["wind_speed"] = float(clean)

                    # KT 转 m/s
                    if is_knots and result["wind_speed"] is not None:
                        result["wind_speed"] *= 0.5144
                except (ValueError, IndexError):
                    pass
                continue

            # 能见度组
            if token.isdigit() and len(token) == 4:
                try:
                    result["visibility"] = int(token) / 1000.0  # 转 km
                except ValueError:
                    pass
                continue

            # 天气现象组 (+/- + 2字母码)
            wx_codes = ["RA", "SN", "DZ", "GR", "GS", "FG", "BR", "HZ", "FU", "SA", "DU",
                        "TS", "SH", "FZ", "BL", "DR", "MI", "BC", "PR", "VA", "SQ", "PO",
                        "FC", "DS", "SS"]
            if len(token) >= 2:
                code = token[-2:] if token[0] in ["+", "-"] else token
                if code in wx_codes:
                    weather_map = {
                        "TS": 95, "RA": 60, "SN": 70, "DZ": 50,
                        "FG": 40, "BR": 10, "HZ": 5, "GR": 96,
                    }
                    result["weather_code"] = weather_map.get(code, 10)
                    continue

            # 云组 (FEW/SCT/BKN/OVC + 高度)
            cloud_tokens = ["FEW", "SCT", "BKN", "OVC", "NSC", "CAVOK", "SKC", "CLR"]
            if token[:3] in cloud_tokens:
                cloud_map = {"FEW": 2, "SCT": 4, "BKN": 7, "OVC": 10, "NSC": 0, "SKC": 0, "CLR": 0}
                result["cloud_cover"] = cloud_map.get(token[:3], None)
                continue

            # 温度/露点组 (TT/TdTd)
            if "/" in token and len(token.split("/")) == 2:
                parts = token.split("/")
                try:
                    t_str, td_str = parts[0], parts[1]
                    if t_str.startswith("M"):
                        result["temperature"] = -int(t_str[1:])
                    else:
                        result["temperature"] = int(t_str)

                    if td_str.startswith("M"):
                        result["dewpoint"] = -int(td_str[1:])
                    elif td_str not in ["XX", "//"]:
                        result["dewpoint"] = int(td_str)
                except ValueError:
                    pass
                continue

            # 气压组 (QPPPP 或 APPPP)
            if token.startswith("Q") and len(token) == 5:
                try:
                    result["pressure"] = int(token[1:])
                except ValueError:
                    pass
                continue
            if token.startswith("A") and len(token) == 5:
                try:
                    # 英寸汞柱 → hPa
                    result["pressure"] = int(token[1:]) * 0.338639
                except ValueError:
                    pass
                continue

    except Exception as e:
        return result, [f"解析出错: {str(e)}"]

    return result, []


def _save_codec_draft():
    st.session_state["codec_draft"] = {"type": st.session_state.get("codec_type"), "text": st.session_state.get("codec_input", "")}


def render_codec_tab():
    import hashlib
    import json
    from modules.ui.shell import page_heading
    from modules.weather_view_model import format_value
    page_heading("报文解码", "将报文中的已识别字段与原始编码对应，保留未解析内容供核查。")
    draft = st.session_state.get("codec_draft") or {}
    options = ["SYNOP (地面天气报告)", "METAR (航空气象报告)"]
    if "codec_type" not in st.session_state:
        st.session_state["codec_type"] = draft.get("type") or options[0]
    if "codec_input" not in st.session_state:
        st.session_state["codec_input"] = draft.get("text", "")
    entry, output = st.columns([1, 1.7])
    with entry, st.container(border=True, key="codec_input_panel"):
        st.markdown("#### 原始报文")
        codec_type = st.radio("报文类型", options, key="codec_type", on_change=_save_codec_draft)
        report_text = st.text_area("粘贴气象报文", height=190, placeholder="METAR ZBAA 260800Z 18005MPS 9999 SCT030 24/12 Q1018",
                                  key="codec_input", on_change=_save_codec_draft)
        st.caption("报文时间按 UTC 解析；年、月以当前 UTC 时间为参照，选择最近的合法相邻月份。历史报文需另行核对年月。")
        if st.button("解码报文", icon=":material/code:", type="primary", width="stretch", key="decode_btn"):
            if not report_text.strip():
                st.warning("请输入报文内容。")
            else:
                provenance = {}
                decoder = decode_synop if "SYNOP" in codec_type else decode_metar
                reference = datetime.now(timezone.utc)
                result, errors = decoder(report_text, reference_time=reference, provenance=provenance)
                st.session_state["codec_result"] = dict(result) or None
                st.session_state["codec_errors"] = list(errors or [])
                st.session_state["codec_snapshot"] = {"raw": report_text, "type": codec_type, "provenance": provenance,
                    "reference": reference.isoformat(), "id": hashlib.sha256((codec_type + report_text + str(result.get("timestamp"))).encode()).hexdigest()}
        with st.expander("支持范围与示例"):
            st.caption("当前为简化解析器，未覆盖全部云层、阵风、趋势组与地区扩展组。未识别内容会保留，不计作成功解码字段。")
            st.code("METAR ZBAA 260800Z 18005MPS 9999 SCT030 24/12 Q1018", language=None, wrap_lines=True)
            st.code("AAXX 26081 54511 11580 81805 10240 20120 30180 60001 70000", language=None, wrap_lines=True)
    with output:
        result = st.session_state.get("codec_result")
        errors = st.session_state.get("codec_errors") or []
        snapshot = st.session_state.get("codec_snapshot") or {}
        if not result:
            with st.container(border=True):
                st.markdown("#### 解码结果")
                st.info("粘贴报文并点击解码，可查看字段、单位和原文对应关系。")
            return
        if snapshot and (report_text != snapshot["raw"] or codec_type != snapshot["type"]):
            st.info("输入已调整；下方仍为上次解码结果，点击解码后更新。")
        for err in errors:
            st.error(err)
        provenance = snapshot.get("provenance") or {}
        valid = {k: v for k, v in result.items() if v is not None and v != "UNKNOWN"}
        with st.container(border=True, key="codec_result_panel"):
            st.markdown(f"#### {result.get('station_id', '未知站点')} · 解码结果")
            st.caption(f"{snapshot.get('type', '旧版结果')} · 已解析 {len(valid)} 个字段 · 简化解析")
            timestamp = result.get("timestamp")
            st.caption(f"报文时间 {timestamp.isoformat()}（UTC）" if timestamp else "报文时间未成功解析")
            metrics = st.columns(4)
            for col, field, title, unit in zip(metrics, ["temperature", "pressure", "wind_speed", "visibility"],
                                              ["气温", "气压", "风速", "能见度"], [" °C", " hPa", " m/s", " km"]):
                display_value = format_value(result.get(field), unit, 1)
                if field == "visibility" and "METAR" in snapshot.get("type", "") and provenance.get(field, {}).get("token") == "9999":
                    display_value = "≥ 10 km"
                col.metric(title, display_value)
            labels = {"station_id": ("站点", ""), "timestamp": ("报文时间", "UTC"), "temperature": ("气温", "°C"),
                      "dewpoint": ("露点", "°C"), "pressure": ("气压", "hPa"), "wind_speed": ("风速", "m/s"),
                      "wind_direction": ("风向", "°"), "visibility": ("能见度", "km"), "cloud_cover": ("云量", "成"),
                      "weather_code": ("天气码", ""), "precipitation": ("降水量", "mm")}
            rows = []
            for field, value in valid.items():
                source = provenance.get(field)
                label, unit = labels.get(field, (field, ""))
                display_value = str(round(value, 3)) if isinstance(value, float) else str(value)
                if field == "visibility" and "METAR" in snapshot.get("type", "") and source and source.get("token") == "9999":
                    display_value = "≥ 10"
                rows.append({"字段": label, "解码值": display_value,
                             "单位": unit, "原文编码": source["token"] if source else "旧结果未记录",
                             "词组序号": str(source["index"] + 1) if source else "—"})
            st.dataframe(rows, hide_index=True, width="stretch")
            if not valid or errors:
                st.warning("报文仅部分解析或含错误，请核对原文。")
            used = {item["index"] for item in provenance.values()}
            unparsed = [f"{i + 1} · {token}" for i, token in enumerate(snapshot.get("raw", "").split())
                        if i not in used and token not in {"METAR", "SPECI", "AAXX", "BBXX", "="}]
            if unparsed:
                st.caption("未解析词组 " + "；".join(unparsed))
            st.caption("编码限值、代表值与缺省单位需结合原始词组核查；METAR 9999 按能见度至少 10 km 展示。下方原始 JSON 保留解析器的兼容数值。")
        with st.expander("复制与核对原文", expanded=True):
            st.caption("代码框右上角可复制完整文本；也可选中文字复制。")
            st.code(snapshot.get("raw", "旧版结果未保存原文"), language=None, wrap_lines=True)
            st.code(json.dumps(valid, ensure_ascii=False, indent=2, default=str), language="json", wrap_lines=True)
        added = snapshot.get("id") in st.session_state.get("codec_added_ids", [])
        if st.button("已加入手动录入区" if added else "加入手动录入区", icon=":material/playlist_add:",
                     key="codec_add_manual", width="stretch", disabled=added or not valid or not snapshot or bool(errors)):
            st.session_state.setdefault("manual_data", []).append(dict(result))
            st.session_state["codec_added_ids"] = (st.session_state.get("codec_added_ids", []) + [snapshot["id"]])[-100:]
            st.rerun()
        if added:
            st.caption("这份结果已加入，可在数据导入的手动录入区继续检查。")
