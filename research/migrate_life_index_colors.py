"""一次性迁移脚本：把生活指数里的硬编码严重度色替换为 token 名。

为什么用脚本而不是逐行手工编辑：
- 目标模式 ``"color": "#xxxxxx"`` 在文件中恰好只出现在生活指数定义处，
  可由正则精确锚定，手工改 30 处反而容易漏改或改错行；
- 迁移是纯文本映射，可复算、可审计。

用法：python research/migrate_life_index_colors.py [--apply]
不带 --apply 时只做 dry-run 并打印差异统计。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parents[1] / "modules" / "nwp_forecast.py"

# 原 hex → 语义 token 名。同一个 hex 在「穿衣建议」与「生活指数」两个语境下
# 语义不同（例如 #3b82f6 在穿衣里表示"冷"，在洗车里并不出现），因此按语境
# 分别映射：这里只处理生活指数的严重度梯度，穿衣的冷暖梯度另有映射。
SEVERITY = {
    "#22c55e": "sev-best",   # 最适宜
    "#84cc16": "sev-good",   # 较适宜
    "#eab308": "sev-mid",    # 中等（紫外线/舒适度）
    "#f59e0b": "sev-mid",    # 一般
    "#ef4444": "sev-bad",    # 不适宜 / 强
}

# 穿衣指数用的是「冷→热」的温标梯度，不是好坏梯度
CLOTHING = {
    "#3b82f6": "accent",     # 厚冬装
    "#06b6d4": "humid",      # 初冬装 / 偏凉
    "#22c55e": "sev-best",   # 春秋装
    "#84cc16": "sev-good",   # 轻便
    "#f59e0b": "sev-mid",    # 夏装
    "#ef4444": "sev-bad",    # 酷热
}

# 带伞建议：蓝色系表示"需要带伞"，不是严重度
UMBRELLA = {
    "#3b82f6": "humid",
    "#06b6d4": "rain",
    "#22c55e": "sev-best",
}

PATTERN = re.compile(r'"color": "(#[0-9a-fA-F]{6})"')

# 按行区间选用映射表（1-based，闭区间）
def mapping_for(line_no: int) -> dict[str, str]:
    if 1538 <= line_no <= 1551:      # 1. 穿衣指数
        return CLOTHING
    if 1553 <= line_no <= 1561:      # 2. 带伞建议
        return UMBRELLA
    return SEVERITY                  # 3~7. 舒适度 / 运动 / 紫外线 / 洗车 / 晾晒


def main() -> int:
    apply = "--apply" in sys.argv
    text = TARGET.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    changed = 0
    for i, line in enumerate(lines):
        line_no = i + 1
        m = PATTERN.search(line)
        if not m:
            continue
        table = mapping_for(line_no)
        token = table.get(m.group(1).lower())
        if not token:
            print(f"  第 {line_no} 行：{m.group(1)} 无映射，跳过")
            continue
        new_line = PATTERN.sub(f'"color": "{token}"', line)
        if new_line != line:
            lines[i] = new_line
            changed += 1
            print(f"  第 {line_no} 行：{m.group(1)} → {token}")

    print(f"\n共 {changed} 处待迁移")
    if apply:
        TARGET.write_text("".join(lines), encoding="utf-8")
        print(f"已写入 {TARGET}")
    else:
        print("（dry-run，未写入；加 --apply 生效）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
