"""核对 ERA5 catalogue 的变量名与 CDS 线上枚举是否一致。

背景：`modules/era5_guide.py` 的变量表是 2026-09-13 从 CDS 实测采集的快照。上游若
增删或改名变量，仓库内的测试发现不了——它们只锁本地一致性，不联网。本脚本用 CDS
公开的 process 描述接口做真实核对，**不需要 CDS 账号与 API Key**。

核对两个方向：
1. 本地展示的变量名必须都存在于 CDS 枚举中，防止名字写错或上游改名；
2. 本地标注为「不支持」的变量必须确实不在 CDS 枚举中，防止误导用户放弃可用变量。

用法：
    python -B research/check_era5_variables.py              # 联网核对
    python -B research/check_era5_variables.py --cache DIR  # 复用已下载的描述文件

退出码：0 全部一致；1 发现不一致；2 联网失败（无法得出结论，不等于通过）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules import era5_guide  # noqa: E402

BASE = "https://cds.climate.copernicus.eu/api/retrieve/v1/processes"
TIMEOUT_SECONDS = 60


def _extract_api_names(items):
    """从本地 catalogue 的条目里取出 API 变量名。

    条目可能是字符串、字典（取 api/api_name/name/key/id 之一）或序列
    （取第一个「全小写且含下划线」的字符串）。
    """
    names = set()
    for item in items or []:
        candidate = None
        if isinstance(item, str):
            candidate = item
        elif isinstance(item, dict):
            for key in ("api", "api_name", "name", "key", "id"):
                if isinstance(item.get(key), str):
                    candidate = item[key]
                    break
        elif isinstance(item, (list, tuple)):
            for element in item:
                if isinstance(element, str) and element.islower() and "_" in element:
                    candidate = element
                    break
        if candidate:
            names.add(candidate)
    return names


def _fetch_enum(dataset, cache_dir):
    """取某数据集在 CDS 上的变量枚举；联网失败抛 OSError。"""
    cache_path = os.path.join(cache_dir, dataset + ".json") if cache_dir else None
    if cache_path and os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as handle:
            payload = json.load(handle)
    else:
        request = urllib.request.Request(
            "%s/%s" % (BASE, dataset),
            headers={"User-Agent": "weather-app-era5-check/1.0"})
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if cache_path:
            os.makedirs(cache_dir, exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)

    node = (payload.get("inputs") or {}).get("variable")
    if not node:
        return set()
    return set((node.get("schema") or {}).get("items", {}).get("enum", []))


def main():
    parser = argparse.ArgumentParser(description="核对 ERA5 变量名与 CDS 线上枚举")
    parser.add_argument("--cache", default=None,
                        help="描述文件缓存目录（复用可避免重复联网）")
    args = parser.parse_args()

    print("ERA5 变量名核对 · %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 64)

    network_error = None
    problems = []
    checked = 0

    for label, product in era5_guide.ERA5_PRODUCTS.items():
        dataset = product.get("dataset") or ""
        try:
            cds_enum = _fetch_enum(dataset, args.cache)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            network_error = "%s（%s）" % (exc, dataset)
            print("%-30s 无法获取 CDS 枚举，跳过" % label[:28])
            continue

        checked += 1
        mine = _extract_api_names(product.get("variables"))
        unsupported = _extract_api_names(product.get("unsupported"))
        missing = sorted(mine - cds_enum)
        wrongly_unsupported = sorted(unsupported & cds_enum)

        print("%-30s 本地 %3d 项 · CDS %3d 项 · 不支持声明 %d 项 · CDS 未收录 %3d 项"
              % (label[:28], len(mine), len(cds_enum), len(unsupported),
                 len(cds_enum - mine - unsupported)))
        if missing:
            problems.append((label, "本地变量在 CDS 不存在", missing))
            print("    [错误] 本地变量 CDS 不存在：%s" % missing[:12])
        if wrongly_unsupported:
            problems.append((label, "被误标为不支持", wrongly_unsupported))
            print("    [错误] 误标为不支持（CDS 实际存在）：%s" % wrongly_unsupported[:12])

    print("=" * 64)
    if not checked:
        print("未能核对任何数据集：%s" % (network_error or "原因未知"))
        print("退出码 2（无法得出结论，不等于通过）")
        return 2
    if problems:
        print("发现 %d 处不一致：%s" % (len(problems), [p[1] for p in problems]))
        print("处置：以 CDS 枚举为准更新 modules/era5_guide.py，并同步")
        print("      research/era5_variable_enums_<日期>.json 快照")
        return 1
    print("全部一致（已核对 %d 个数据集，变量名零错误、不支持声明零误标）" % checked)
    return 0


if __name__ == "__main__":
    sys.exit(main())
