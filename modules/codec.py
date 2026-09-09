"""
气象报文解码模块：SYNOP、METAR 标准编码报文解析
"""

import streamlit as st
from datetime import datetime


def decode_synop(report):
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
    result = {"station_id": "UNKNOWN", "timestamp": None}
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
            try:
                day = int(group[0:2])
                hour = int(group[2:4])
                wind_indicator = int(group[4])
                if 1 <= day <= 31 and 0 <= hour <= 23:
                    now = datetime.now()
                    result["timestamp"] = datetime(
                        now.year, now.month, min(day, 28), hour, 0
                    )
            except (ValueError, IndexError):
                pass
            idx += 1

        # IIiii - 区站号
        if idx < len(tokens) and len(tokens[idx]) == 5 and tokens[idx].isdigit():
            result["station_id"] = tokens[idx]
            idx += 1

        # iRixhVV - 降水指示 / 天气指示 / 云底高 / 能见度
        if idx < len(tokens) and len(tokens[idx]) == 5:
            group = tokens[idx]
            try:
                vis_code = int(group[4]) if group[4] != "/" else None

                if vis_code is not None:
                    # SYNOP 能见度码转换表（简化；VV=0 表示能见度 <0.1 km）
                    vis_table = {
                        0: 0.05, 90: 0.05, 91: 0.05, 92: 0.2, 93: 0.5, 94: 1.0,
                        95: 2.0, 96: 4.0, 97: 10.0, 98: 20.0, 99: 50.0,
                    }
                    if 1 <= vis_code <= 50:
                        result["visibility"] = vis_code / 10.0  # 0.1 km 为单位
                    elif vis_code in vis_table:
                        result["visibility"] = vis_table[vis_code]
            except (ValueError, IndexError):
                pass
            idx += 1

        # Nddff - 总云量(N) / 风向(dd) / 风速(ff)
        if idx < len(tokens) and len(tokens[idx]) == 5 and tokens[idx].isdigit():
            group = tokens[idx]
            try:
                result["cloud_cover"] = min(int(group[0]), 10)
                dd = int(group[1:3])
                ff = int(group[3:5])
                result["wind_direction"] = None if dd == 99 else dd * 10
                if wind_indicator in (3, 4):  # 单位为节
                    result["wind_speed"] = round(ff * 0.514444, 1)
                else:  # iw 0/1 为 m/s
                    result["wind_speed"] = float(ff)
            except (ValueError, IndexError):
                pass
            idx += 1

        # 在报文中搜索温度组 (1sTTT)
        for token in tokens[idx:]:
            if len(token) == 5 and token[0] == "1":
                try:
                    sign = -1 if token[1] == "1" else 1
                    result["temperature"] = int(token[2:]) / 10.0 * sign
                    break
                except (ValueError, IndexError):
                    continue

        # 露点组 (2sTdTdTd)
        for token in tokens[idx:]:
            if len(token) == 5 and token[0] == "2":
                try:
                    sign = -1 if token[1] == "1" else 1
                    result["dewpoint"] = int(token[2:]) / 10.0 * sign
                    break
                except (ValueError, IndexError):
                    continue

        # 气压组 (3PPPP 或 4PPPP)
        for token in tokens[idx:]:
            if len(token) == 5 and token[0] == "3":
                try:
                    pres = int(token[1:]) / 10.0
                    result["pressure"] = pres if pres > 500 else pres + 1000
                    break
                except (ValueError, IndexError):
                    continue

        # 降水量组 (6RRR1)
        for token in tokens[idx:]:
            if len(token) >= 4 and token[0] == "6":
                try:
                    precip = int(token[1:4])
                    result["precipitation"] = precip if precip < 990 else (precip - 990) / 10.0
                    break
                except (ValueError, IndexError):
                    continue

        # 现在天气组 (7wwWW)：天气现象码的真正来源
        # （原实现误把 iRixhVV 的 R+ix 两位当作天气码）
        for token in tokens[idx:]:
            if len(token) == 5 and token[0] == "7":
                try:
                    result["weather_code"] = int(token[1:3])
                    break
                except (ValueError, IndexError):
                    continue

    except Exception as e:
        return result, [f"解析出错: {str(e)}"]

    return result, []


def decode_metar(report):
    """
    解码 METAR/SPECI 航空气象报告（简化版）
    """
    result = {"station_id": "UNKNOWN", "timestamp": None}

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
            result["station_id"] = tokens[idx]
            idx += 1

        # 日期时间组 (DDHHMMZ)
        if idx < len(tokens) and len(tokens[idx]) == 7 and tokens[idx].endswith("Z"):
            group = tokens[idx]
            try:
                day = int(group[0:2])
                hour = int(group[2:4])
                minute = int(group[4:6])
                now = datetime.now()
                result["timestamp"] = datetime(now.year, now.month, min(day, 28), hour, minute)
            except (ValueError, IndexError):
                pass
            idx += 1

        # 遍历剩余组
        for token in tokens[idx:]:
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


def render_codec_tab():
    """渲染气象报文解码 Tab"""
    st.subheader("[雷达] 气象报文解码")

    codec_type = st.radio("报文类型", ["SYNOP (地面天气报告)", "METAR (航空气象报告)"],
                          horizontal=True, key="codec_type")

    report_text = st.text_area(
        "粘贴气象报文",
        height=120,
        placeholder="例如 SYNOP: AAXX 54511 ...\n或 METAR: METAR ZBAA 010800Z ...",
        key="codec_input"
    )

    if st.button("[搜索] 解码", use_container_width=True, key="decode_btn"):
        if not report_text.strip():
            st.warning("请输入报文内容")
            return

        if "SYNOP" in codec_type:
            with st.spinner("正在解码 SYNOP 报文..."):
                result, errors = decode_synop(report_text)
        else:
            with st.spinner("正在解码 METAR 报文..."):
                result, errors = decode_metar(report_text)

        if errors:
            for err in errors:
                st.error(err)

        # 显示解码结果
        if result:
            st.success(f"[OK] 解码成功 | 站点: {result.get('station_id', 'N/A')}")

            cols = st.columns(4)
            field_config = [
                ("temperature", "气温", "℃"),
                ("pressure", "气压", "hPa"),
                ("dewpoint", "露点温度", "℃"),
                ("wind_speed", "风速", "m/s"),
                ("wind_direction", "风向", "°"),
                ("visibility", "能见度", "km"),
                ("cloud_cover", "云量", "成"),
                ("weather_code", "天气码", ""),
                ("precipitation", "降水量", "mm"),
            ]

            for i, (key, label, unit) in enumerate(field_config):
                if key in result and result[key] is not None:
                    val = result[key]
                    cols[i % 4].metric(
                        label,
                        f"{val:.1f} {unit}" if isinstance(val, (int, float)) else str(val)
                    )

            # 提供"添加到当前数据"按钮
            if st.button("[+] 将此记录添加到手动录入区", use_container_width=True):
                if "manual_data" not in st.session_state:
                    st.session_state["manual_data"] = []
                st.session_state["manual_data"].append(result)
                st.success("已添加！请切换到数据导入 Tab 查看")
