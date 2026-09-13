# AQI 口径统一 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把散落在 `analyzer._calc_single_aqi` 与 `nwp_forecast._compute_cn_aqi` 的两套 AQI 实现统一为 `modules/aqi.py` 单一实现，修掉 `config.AQI_BREAKPOINTS` 的结构缺陷（NOx 61–80 空洞、缺 CO 与 O₃、SO₂ 非标节点）与超量程返回 0 的缺陷（PM2.5 > 400 会显示 AQI 0「优」），并让页面如实标注实际所用标准版本（HJ 633-2012）。

**Architecture:** 断点数值集中在 `config.AQI_BREAKPOINTS`（6 项污染物、结构可校验）；计算逻辑集中在 `modules/aqi.py`（`validate_breakpoints` + `iaqi` + `comprehensive_aqi`）；两个调用方各自保留原有返回签名，内部委托新模块，因此 `nwp_forecast._compute_cn_aqi` 的 3 个调用点（`nwp_forecast.py:421`、`:1430`、`weather_wall.py:242`）全部无需改动。`nwp_forecast._AQ_LEVELS` 作为「AQI 等级 → 色 token」的展示用表**保留**（图表色带渲染有 4 处依赖，见 `nwp_forecast.py:359/469/478/545`），不删除，改为新增一致性测试锁死它与 `config.AQI_LEVELS` 不漂移。

**Tech Stack:** Python 3.12（CI）/ 3.14（本机）、pandas 3.0、numpy 2.5、pytest（可选，测试亦可 `python -B` 直跑）、streamlit 1.59

**Spec:** `docs/superpowers/specs/2026-09-13-chart-reader-and-era5-delivery-design.md`（第 5.5 节、第 5.2.9/5.2.10 节）

## Global Constraints

- 不引入当前环境中尚不存在的第三方包；不修改 `requirements.txt` 中已有条目的版本锁定。
- 应用侧不得 `import cdsapi` / `xarray` / `netCDF4`（本批次无关，列出以防误用）。
- AQI 标准名一律渲染 `config.AQI_STANDARD_LABEL`，**禁止**在 UI 文本、图表标题、docstring 中硬编码标准版本号。
- 断点数值口径固定为 HJ 633-2012（气态污染物 1h 表 / 颗粒物与 CO 24h 表），`AQI_STANDARD_LABEL = "HJ 633-2012"`，理由见 spec 第 5.5.5 节。
- 新增模块 `modules/aqi.py` 只依赖标准库 `math` 与 `config`，**不得** import `streamlit` 或 `design_tokens`（颜色解析是调用方的职责）。
- 测试文件风格遵循仓库既有约定：模块 docstring + `sys.path` 注入 + 直接 import + 纯 `assert`（无 fixture）；既可被 pytest 收集，也可 `python -B tests/test_aqi.py` 直接运行。
- 每次提交前必须跑通：`python -B tests/test_analyzer.py`、`python -B tests/test_weather_wall.py`、`python -B tests/test_aqi.py`。
- 每个 Task 结束时提交一次，提交信息用仓库既有的 `type(scope): 说明` 格式。
- 本批次**不**修改 `APP_VERSION`（留到第 5 批次改为 2.4.0）。
- 本批次**不**改动 `analyzer.check_air_quality` 的对外返回结构（dict 的键与含义保持不变），因为它在第 5 批次删除前仍需可用。
- 保留 `analyzer._aqi_level_name`（`analyzer.py:408-419`）与 `nwp_forecast._AQ_LEVELS`：前者是唯一的 AQI→(标签, token) 助手且被改写后的 `check_air_quality` 继续使用；后者是图表色带的数据源。
- 本批次**不**触碰 `visualizer.py:614/651/656`、`analyzer.py:551`、`app.py:454-465` 中「GB 3095-2026 达标限值」相关文案：那是 `AIR_POLLUTANT_LIMITS` 口径，与 AQI 断点表是两张不同的表，登记到第 5 批次统一处理。
- `research/check_chart_colors.py:3` 引用了 `_AQ_LEVELS`，它是 research 目录下的一次性探针脚本，不参与 CI，本次不动。

---

### Task 1: 断点表口径统一与结构校验

把 `config.AQI_BREAKPOINTS` 整表替换为 HJ 633-2012 的六项污染物分指数表（补齐 CO 与 O₃，消除 NOx 空洞），并在新模块 `modules/aqi.py` 中实现可测试的结构校验函数。

**Files:**
- Create: `modules/aqi.py`
- Modify: `config.py:525-544`（替换整段断点表并新增 `AQI_STANDARD_LABEL`）
- Test: `tests/test_aqi.py`

**Interfaces:**
- Consumes: `config.AQI_BREAKPOINTS`（dict，键 `pm25` / `pm10` / `so2` / `nox` / `co` / `o3`；值 `[(lo, hi, iaqi_lo, iaqi_hi), ...]`）
- Produces:
  - `modules.aqi.IAQI_NODES: tuple[int, ...]`
  - `modules.aqi.ALLOWED_IAQI_CAPS: tuple[int, ...]`
  - `modules.aqi.REQUIRED_POLLUTANTS: tuple[str, ...]`
  - `modules.aqi.POLLUTANT_LABELS: dict[str, str]`
  - `modules.aqi.validate_breakpoints(table: dict | None = None) -> list[str]`
  - `config.AQI_STANDARD_LABEL: str`

- [ ] **Step 1: 写失败测试（新建 `tests/test_aqi.py`）**

```python
"""AQI 统一计算回归测试。

覆盖：
- 断点表结构校验能检出间隙、IAQI 不衔接、缺失污染物、非法末档节点；
- IAQI 在各档边界取值正确，超末档钳制到本污染物上限而非返回 0；
- 综合 AQI 取最大值、首要污染物判定与并列处理；
- nwp_forecast 的四元组包装与统一实现同源，且两张等级表不漂移。

无 pytest 时可直接运行（`python -B tests/test_aqi.py`）。
"""
import os
import sys

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from config import AQI_BREAKPOINTS, AQI_LEVELS, AQI_STANDARD_LABEL  # noqa: E402
from modules import aqi  # noqa: E402


def test_standard_label_is_honest():
    """标准版本必须如实标注为 2012，不得声称 2026。"""
    assert AQI_STANDARD_LABEL == "HJ 633-2012", AQI_STANDARD_LABEL


def test_config_table_passes_validation():
    """config 内置断点表必须无结构缺陷。"""
    problems = aqi.validate_breakpoints(AQI_BREAKPOINTS)
    assert problems == [], "断点表存在结构缺陷：%s" % problems


def test_config_table_covers_six_pollutants():
    """六项污染物缺一不可（原表缺 co 与 o3）。"""
    assert set(aqi.REQUIRED_POLLUTANTS) <= set(AQI_BREAKPOINTS), sorted(AQI_BREAKPOINTS)


def test_validation_detects_nox_gap():
    """重现原表的 NOx 61~80 空洞，校验必须报出。"""
    broken = dict(AQI_BREAKPOINTS)
    broken["nox"] = [(0, 40, 0, 50), (41, 60, 51, 100), (81, 120, 101, 150),
                     (121, 200, 151, 200), (201, 400, 201, 300),
                     (401, 800, 301, 500)]
    problems = aqi.validate_breakpoints(broken)
    assert any("nox" in p and "不连续" in p for p in problems), problems


def test_validation_detects_missing_pollutant():
    """缺项必须被检出。"""
    incomplete = {k: v for k, v in AQI_BREAKPOINTS.items() if k != "o3"}
    problems = aqi.validate_breakpoints(incomplete)
    assert any("o3" in p and "缺少" in p for p in problems), problems


def test_validation_detects_iaqi_node_mismatch():
    """相邻档 IAQI 不衔接必须被检出。"""
    broken = dict(AQI_BREAKPOINTS)
    broken["o3"] = [(0, 160, 0, 50), (161, 200, 60, 100),
                    (201, 300, 101, 150), (301, 400, 151, 200)]
    problems = aqi.validate_breakpoints(broken)
    assert any("o3" in p and "不衔接" in p for p in problems), problems


def test_validation_detects_illegal_cap():
    """末档 IAQI 上限只能是 200 或 500。"""
    broken = dict(AQI_BREAKPOINTS)
    broken["o3"] = [(0, 160, 0, 50), (161, 200, 51, 100),
                    (201, 300, 101, 150), (301, 400, 151, 400)]
    problems = aqi.validate_breakpoints(broken)
    assert any("o3" in p and "末档" in p for p in problems), problems
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -B -m pytest tests/test_aqi.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'modules.aqi'`（`config` 亦尚无 `AQI_STANDARD_LABEL`）

- [ ] **Step 3: 替换 `config.py` 的断点表段（现第 525-544 行）**

把现第 525 行 `# =====...` 至第 544 行 `}` 的整段（含原有的 `AQI_BREAKPOINTS` 定义与其上方注释）替换为：

```python
# ============================================================
# 七、大气环境质量标准 (GB 3095 达标限值 + HJ 633 AQI 分指数)
# ============================================================
# AQI 计算实际使用的标准版本，单一真相源。
# 页面、手册、图表标题一律渲染本常量，禁止硬编码版本号。
#
# 现状说明：HJ 633-2026 表 1 的具体断点数值在标准文本公开发布前无法核验，
# 因此本平台采用可核验的 HJ 633-2012 分指数表并如实标注，不声称使用 2026 版。
# 待 2026 版表 1 可核验时，只需替换下方 AQI_BREAKPOINTS 的数值与本常量。
AQI_STANDARD_LABEL = "HJ 633-2012"

# 各污染物浓度→AQI 分指数断点 (μg/m³，CO 为 mg/m³)
# 格式: (浓度下限, 浓度上限, IAQI下限, IAQI上限)
# 口径：气态污染物（SO₂/NO₂/CO/O₃）用 1 小时均值表；颗粒物（PM2.5/PM10）用 24 小时均值表。
# 气态污染物的 1h 表只定义到 IAQI 200，超出部分按末档斜率外推后钳制到 200。
# 结构不变量由 modules/aqi.validate_breakpoints 校验：档间连续、IAQI 节点衔接、末档节点合法。
AQI_BREAKPOINTS = {
    # 24 小时均值表
    "pm25": [(0, 35, 0, 50), (36, 75, 51, 100), (76, 115, 101, 150),
             (116, 150, 151, 200), (151, 250, 201, 300), (251, 350, 301, 400),
             (351, 500, 401, 500)],
    "pm10": [(0, 50, 0, 50), (51, 150, 51, 100), (151, 250, 101, 150),
             (251, 350, 151, 200), (351, 420, 201, 300), (421, 500, 301, 400),
             (501, 600, 401, 500)],
    # 1 小时均值表（气态）
    "so2": [(0, 150, 0, 50), (151, 500, 51, 100), (501, 650, 101, 150),
            (651, 800, 151, 200)],
    "nox": [(0, 100, 0, 50), (101, 200, 51, 100), (201, 700, 101, 150),
            (701, 1200, 151, 200)],
    "co": [(0, 5, 0, 50), (6, 10, 51, 100), (11, 35, 101, 150), (36, 60, 151, 200),
           (61, 90, 201, 300), (91, 120, 301, 400), (121, 150, 401, 500)],
    "o3": [(0, 160, 0, 50), (161, 200, 51, 100), (201, 300, 101, 150),
           (301, 400, 151, 200)],
}
```

注意：紧随其后的 `AQI_LEVELS`（第 546-553 行）与 `AQI_ADVICE`（第 556-563 行）保持不动；`AQI_LEVELS` 的最后档为 `(301, 500)`，与 `iaqi` 的最大钳制值一致。

- [ ] **Step 4: 新建 `modules/aqi.py`（本步只实现表与校验）**

```python
"""环境空气质量指数（AQI）统一计算模块。

口径：HJ 633-2012 分指数表——气态污染物（SO₂/NO₂/CO/O₃）用 1 小时均值表，
颗粒物（PM2.5/PM10）用 24 小时均值表。实际所用标准版本由
``config.AQI_STANDARD_LABEL`` 单一标注，页面与手册如实渲染该常量。

本模块是全项目唯一的 IAQI / 综合 AQI 实现。此前散落在
``analyzer._calc_single_aqi`` 与 ``nwp_forecast._compute_cn_aqi`` 的两套实现已删除。

已知局限：气态污染物分指数按 1 小时表计算。``nwp_forecast.fetch_air_quality``
传入逐时浓度，口径正确；``analyzer.check_air_quality`` 传入时段均值，会高估
气态污染物的分指数。评价时段口径的重新定义不在本次范围内。

本模块不 import streamlit 与 design_tokens：颜色解析是调用方的职责。
"""

from math import isfinite

from config import AQI_BREAKPOINTS, AQI_LEVELS

# 标准 IAQI 节点。每个污染物的节点序列必须是它的前缀，且相邻档首尾相接。
IAQI_NODES = (0, 50, 100, 150, 200, 300, 400, 500)

# 允许的末档节点：气态污染物的 1 小时表仅定义到 200
ALLOWED_IAQI_CAPS = (200, 500)

# 必须提供断点表的污染物
REQUIRED_POLLUTANTS = ("pm25", "pm10", "so2", "nox", "co", "o3")

# 各污染物显示标签
POLLUTANT_LABELS = {
    "pm25": "PM2.5",
    "pm10": "PM10",
    "so2": "SO₂",
    "nox": "NO₂",
    "co": "CO",
    "o3": "O₃",
}


def validate_breakpoints(table=None):
    """校验断点表结构，返回缺陷描述列表；空列表表示合法。

    不抛异常：缺陷以返回值交给调用方决定如何处理。
    """
    table = AQI_BREAKPOINTS if table is None else table
    problems = []

    for key in REQUIRED_POLLUTANTS:
        if key not in table:
            problems.append("%s: 缺少该污染物的断点表" % key)

    for key, bands in table.items():
        if not bands:
            problems.append("%s: 断点表为空" % key)
            continue
        prev_hi = None
        prev_iaqi_hi = None
        malformed = False
        for idx, band in enumerate(bands):
            if len(band) != 4:
                problems.append("%s: 第 %d 档不是四元组 %r" % (key, idx, band))
                malformed = True
                break
            lo, hi, i_lo, i_hi = band
            if lo > hi:
                problems.append("%s: 第 %d 档浓度区间倒置 %r" % (key, idx, band))
            if i_lo >= i_hi:
                problems.append("%s: 第 %d 档 IAQI 区间非递增 %r" % (key, idx, band))
            if i_lo not in IAQI_NODES or i_hi not in IAQI_NODES:
                problems.append("%s: 第 %d 档 IAQI 节点不在 %r 内 %r"
                                % (key, idx, IAQI_NODES, band))
            if idx == 0:
                if lo != 0:
                    problems.append("%s: 首档浓度下限必须为 0，实际 %r" % (key, lo))
                if i_lo != 0:
                    problems.append("%s: 首档 IAQI 下限必须为 0，实际 %r" % (key, i_lo))
            else:
                if lo != prev_hi + 1:
                    problems.append("%s: 第 %d 档与上一档不连续（上一档上限 %r，本档下限 %r）"
                                    % (key, idx, prev_hi, lo))
                if i_lo != prev_iaqi_hi:
                    problems.append("%s: 第 %d 档 IAQI 与上一档不衔接（上一档 %r，本档 %r）"
                                    % (key, idx, prev_iaqi_hi, i_lo))
            prev_hi, prev_iaqi_hi = hi, i_hi
        if malformed:
            continue
        if bands[-1][3] not in ALLOWED_IAQI_CAPS:
            problems.append("%s: 末档 IAQI 上限应为 %r 之一，实际 %r"
                            % (key, ALLOWED_IAQI_CAPS, bands[-1][3]))

    return problems
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -B -m pytest tests/test_aqi.py -v`
Expected: PASS（7 项）

- [ ] **Step 6: 确认既有测试未被破坏**

Run: `python -B tests/test_analyzer.py`
Expected: 全部通过。此时 `analyzer._calc_single_aqi` 仍按四元组遍历，与新的表结构兼容；其数值结果会变化（原本用 2026 断点，现用 2012 断点），但既有测试断言的是预警检测，不涉及 AQI。

- [ ] **Step 7: 提交**

```bash
git add config.py modules/aqi.py tests/test_aqi.py
git commit -m "feat(aqi): 断点表统一为 HJ 633-2012 六项口径并实现结构校验"
```

---

### Task 2: 单污染物分指数 `iaqi()`

实现 `iaqi(conc, pollutant)`：档内线性插值、超末档外推后钳制到本污染物上限、非有限值返回 `None`、支持 `pm2_5` / `no2` 别名。

**Files:**
- Modify: `modules/aqi.py`（追加 `POLLUTANT_ALIASES`、`normalize_key`、`iaqi`）
- Test: `tests/test_aqi.py`（追加用例）

**Interfaces:**
- Consumes: Task 1 的 `IAQI_NODES`、`REQUIRED_POLLUTANTS`、`config.AQI_BREAKPOINTS`
- Produces:
  - `modules.aqi.POLLUTANT_ALIASES: dict[str, str]`
  - `modules.aqi.normalize_key(raw_key) -> str | None`
  - `modules.aqi.iaqi(conc, pollutant) -> float | None`

- [ ] **Step 1: 追加失败测试**

在 `tests/test_aqi.py` 末尾追加：

```python
def test_iaqi_band_edges_pm25():
    """PM2.5 档边界：0→0，35→50，36→51，500→500。"""
    assert aqi.iaqi(0, "pm25") == 0.0
    assert aqi.iaqi(35, "pm25") == 50.0
    assert aqi.iaqi(36, "pm25") == 51.0
    assert aqi.iaqi(500, "pm25") == 500.0


def test_iaqi_linear_interpolation_pm25():
    """PM2.5 在 351~500 μg/m³ 档线性插值，对应 IAQI 401~500。"""
    expected = (500 - 401) / (500 - 351) * (425 - 351) + 401
    assert abs(aqi.iaqi(425, "pm25") - expected) < 1e-9


def test_iaqi_out_of_range_clamps_not_zero():
    """超末档必须钳制到本污染物上限，不得返回 0（原实现返回 0 会显示「优」）。"""
    assert aqi.iaqi(5000, "pm25") == 500.0
    assert aqi.iaqi(9999, "o3") == 200.0


def test_iaqi_gas_cap_is_200():
    """气态污染物 1h 表只到 IAQI 200。"""
    assert aqi.iaqi(800, "so2") == 200.0
    assert aqi.iaqi(1200, "nox") == 200.0
    assert aqi.iaqi(400, "o3") == 200.0


def test_iaqi_co_uses_mg():
    """CO 单位为 mg/m³：5 对应 IAQI 50，150 对应 IAQI 500。"""
    assert aqi.iaqi(5, "co") == 50.0
    assert aqi.iaqi(150, "co") == 500.0


def test_iaqi_accepts_aliases():
    """数值预报侧使用的 pm2_5 / no2 别名必须可解析。"""
    assert aqi.iaqi(35, "pm2_5") == aqi.iaqi(35, "pm25")
    assert aqi.iaqi(100, "no2") == aqi.iaqi(100, "nox")
    assert aqi.iaqi(100, "NO2") == aqi.iaqi(100, "nox")


def test_iaqi_invalid_input_returns_none():
    """非数值、缺失、未知污染物一律返回 None。"""
    assert aqi.iaqi(None, "pm25") is None
    assert aqi.iaqi(float("nan"), "pm25") is None
    assert aqi.iaqi(float("inf"), "pm25") is None
    assert aqi.iaqi("abc", "pm25") is None
    assert aqi.iaqi(10, "unknown") is None


def test_iaqi_negative_and_string_numeric():
    """负值按 0 处理；数字字符串可解析。"""
    assert aqi.iaqi(-5, "pm25") == 0.0
    assert aqi.iaqi("35", "pm25") == 50.0
```

- [ ] **Step 2: 运行确认失败**

Run: `python -B -m pytest tests/test_aqi.py -v`
Expected: FAIL，`AttributeError: module 'modules.aqi' has no attribute 'iaqi'`

- [ ] **Step 3: 在 `modules/aqi.py` 末尾追加实现**

```python
# 别名归一化：数值预报侧使用 pm2_5 / no2 作为列名
POLLUTANT_ALIASES = {
    "pm2_5": "pm25",
    "pm25": "pm25",
    "pm10": "pm10",
    "so2": "so2",
    "no2": "nox",
    "nox": "nox",
    "co": "co",
    "o3": "o3",
}


def normalize_key(raw_key):
    """把别名归一化为规范污染物键；无法识别时返回 None。"""
    if raw_key is None:
        return None
    return POLLUTANT_ALIASES.get(str(raw_key).strip().lower())


def iaqi(conc, pollutant):
    """单污染物分指数。无法计算时返回 None。

    超末档按末档斜率线性外推后钳制到该污染物自身的最大 IAQI 节点
    （颗粒物与 CO 为 500，气态污染物为 200）——**不返回 0**。
    """
    key = normalize_key(pollutant)
    if key is None or key not in AQI_BREAKPOINTS:
        return None
    if conc is None:
        return None
    try:
        value = float(conc)
    except (TypeError, ValueError):
        return None
    if not isfinite(value):
        return None
    if value <= 0:
        return 0.0

    bands = AQI_BREAKPOINTS[key]
    cap = bands[-1][3]
    for lo, hi, i_lo, i_hi in bands:
        if value <= hi:
            # 表若有间隙，把落点收进本档下限（防御性；合法表不会触发）
            point = value if value >= lo else lo
            return (i_hi - i_lo) / (hi - lo) * (point - lo) + i_lo

    lo, hi, i_lo, i_hi = bands[-1]
    extrapolated = (i_hi - i_lo) / (hi - lo) * (value - lo) + i_lo
    return float(min(extrapolated, cap))
```

- [ ] **Step 4: 运行确认通过**

Run: `python -B -m pytest tests/test_aqi.py -v`
Expected: PASS（15 项）

- [ ] **Step 5: 提交**

```bash
git add modules/aqi.py tests/test_aqi.py
git commit -m "feat(aqi): 实现 iaqi 分指数，超量程钳制到污染物上限而非返回 0"
```

---

### Task 3: 综合 AQI `comprehensive_aqi()`

实现多污染物综合 AQI：取各分指数最大值、`AQI > 50` 时判定首要污染物、并列时全部列出、返回逐污染物明细。

**Files:**
- Modify: `modules/aqi.py`（追加 `level_of` 与 `comprehensive_aqi`）
- Test: `tests/test_aqi.py`（追加用例）

**Interfaces:**
- Consumes: Task 2 的 `iaqi`、`normalize_key`；`config.AQI_LEVELS`
- Produces:
  - `modules.aqi.level_of(aqi_value) -> str`
  - `modules.aqi.comprehensive_aqi(concentrations: dict) -> dict`
    - 返回 `{"aqi": int | None, "level": str, "primary": str | None, "primary_all": list[str], "details": list[dict]}`
    - `details` 每项为 `{"key": str, "label": str, "conc": float, "iaqi": int, "level": str}`

- [ ] **Step 1: 追加失败测试**

在 `tests/test_aqi.py` 末尾追加：

```python
def test_comprehensive_takes_max_iaqi():
    """综合 AQI 取各分指数最大值。"""
    result = aqi.comprehensive_aqi({"pm25": 35, "pm10": 50, "so2": 150})
    assert result["aqi"] == 50, result


def test_comprehensive_primary_is_max_pollutant():
    """首要污染物为分指数最大者。"""
    result = aqi.comprehensive_aqi({"pm25": 115, "pm10": 50})
    assert result["aqi"] == 150
    assert result["primary"] == "PM2.5"
    assert result["primary_all"] == ["PM2.5"]
    assert result["level"] == "轻度污染"


def test_comprehensive_primary_all_on_tie():
    """并列最大时全部列为首要污染物。"""
    result = aqi.comprehensive_aqi({"pm25": 35, "pm10": 50})
    assert result["aqi"] == 50
    assert set(result["primary_all"]) == {"PM2.5", "PM10"}


def test_comprehensive_primary_none_when_good():
    """AQI <= 50 时无首要污染物。"""
    result = aqi.comprehensive_aqi({"pm25": 10})
    assert result["aqi"] == 14
    assert result["level"] == "优"
    assert result["primary"] is None
    assert result["primary_all"] == []


def test_comprehensive_accepts_aliases():
    """别名与规范名混用结果一致。"""
    a = aqi.comprehensive_aqi({"pm2_5": 75, "no2": 100})
    b = aqi.comprehensive_aqi({"pm25": 75, "nox": 100})
    assert a["aqi"] == b["aqi"] == 100
    assert a["primary"] == b["primary"] == "PM2.5"


def test_comprehensive_details_shape():
    """明细包含键、标签、浓度、分指数与等级。"""
    result = aqi.comprehensive_aqi({"pm25": 115, "o3": 200})
    assert {d["key"] for d in result["details"]} == {"pm25", "o3"}
    pm25_detail = [d for d in result["details"] if d["key"] == "pm25"][0]
    assert pm25_detail["label"] == "PM2.5"
    assert pm25_detail["iaqi"] == 150
    assert pm25_detail["level"] == "轻度污染"
    assert pm25_detail["conc"] == 115.0


def test_comprehensive_skips_unusable_values():
    """缺失/非数值项被跳过，不参与综合。"""
    result = aqi.comprehensive_aqi({"pm25": None, "pm10": float("nan"), "o3": 400})
    assert result["aqi"] == 200
    assert [d["key"] for d in result["details"]] == ["o3"]


def test_comprehensive_no_data():
    """无任何可用浓度时 aqi 为 None。"""
    result = aqi.comprehensive_aqi({})
    assert result["aqi"] is None
    assert result["level"] == "无数据"
    assert result["primary"] is None
    assert result["details"] == []


def test_level_of_boundaries():
    """等级区间边界：50 优 / 51 良 / 101 轻度污染 / 500 严重污染。"""
    assert aqi.level_of(0) == "优"
    assert aqi.level_of(50) == "优"
    assert aqi.level_of(51) == "良"
    assert aqi.level_of(100) == "良"
    assert aqi.level_of(101) == "轻度污染"
    assert aqi.level_of(500) == "严重污染"


def test_level_tables_do_not_drift():
    """nwp_forecast 的展示用等级表必须与 config.AQI_LEVELS 一致（截到 500）。"""
    from modules.nwp_forecast import _AQ_LEVELS

    config_pairs = []
    for _lv, info in sorted(AQI_LEVELS.items()):
        lo, hi = info["range"]
        config_pairs.append((lo, hi, info["label"]))

    nwp_pairs = [(lo, hi, name) for lo, hi, name, _tok in _AQ_LEVELS[:5]]
    nwp_pairs.append((_AQ_LEVELS[5][0], 500, _AQ_LEVELS[5][2]))

    assert config_pairs == nwp_pairs, (config_pairs, nwp_pairs)
```

- [ ] **Step 2: 运行确认失败**

Run: `python -B -m pytest tests/test_aqi.py -v`
Expected: FAIL，`AttributeError: module 'modules.aqi' has no attribute 'comprehensive_aqi'`。`test_level_tables_do_not_drift` 在本步应已通过（两张表当前一致），它在此引入用于防漂移。

- [ ] **Step 3: 在 `modules/aqi.py` 末尾追加实现**

```python
def level_of(aqi_value):
    """AQI 数值 → 等级标签。区间取自 config.AQI_LEVELS。"""
    for _lv, info in sorted(AQI_LEVELS.items()):
        lo, hi = info["range"]
        if lo <= aqi_value <= hi:
            return info["label"]
    return "严重污染"


def comprehensive_aqi(concentrations):
    """由多项浓度计算综合 AQI。

    concentrations: dict，键可用规范名或别名（pm2_5 / no2 等），值可为数值或数字字符串。
    返回:
        {"aqi": int | None, "level": str, "primary": str | None,
         "primary_all": list[str], "details": list[dict]}
    aqi 为 None 表示无任何可用浓度。
    AQI <= 50 时 primary 为 None；并列最大时 primary_all 列出全部。
    """
    details = []
    for raw_key, conc in (concentrations or {}).items():
        key = normalize_key(raw_key)
        if key is None:
            continue
        value = iaqi(conc, key)
        if value is None:
            continue
        rounded = int(round(value))
        details.append({
            "key": key,
            "label": POLLUTANT_LABELS[key],
            "conc": float(conc),
            "iaqi": rounded,
            "level": level_of(rounded),
        })

    if not details:
        return {"aqi": None, "level": "无数据", "primary": None,
                "primary_all": [], "details": []}

    best = max(d["iaqi"] for d in details)
    best_labels = [d["label"] for d in details if d["iaqi"] == best]
    if best <= 50:
        primary, primary_all = None, []
    else:
        primary, primary_all = best_labels[0], best_labels

    return {
        "aqi": best,
        "level": level_of(best),
        "primary": primary,
        "primary_all": primary_all,
        "details": details,
    }
```

- [ ] **Step 4: 运行确认通过**

Run: `python -B -m pytest tests/test_aqi.py -v`
Expected: PASS（26 项）

- [ ] **Step 5: 提交**

```bash
git add modules/aqi.py tests/test_aqi.py
git commit -m "feat(aqi): 实现 comprehensive_aqi 综合指数与等级判定"
```

---

### Task 4: 收敛 `nwp_forecast` 的私有实现

删除 `nwp_forecast` 的 6 张私有断点表、`_AQ_POLLUTANTS` 与 `_iaqi`，把 `_compute_cn_aqi` 改为委托统一实现的薄包装，保持四元组返回签名不变。

**Files:**
- Modify: `modules/nwp_forecast.py`（第 266-291 行的私有表、第 315-341 行的 `_iaqi`、第 344-364 行的 `_compute_cn_aqi`、第 28-29 行的导入行）
- Test: `tests/test_aqi.py`（追加包装一致性用例）

**Interfaces:**
- Consumes: Task 3 的 `comprehensive_aqi`
- Produces: `modules.nwp_forecast._compute_cn_aqi(conc: dict) -> tuple[int | None, str, str, str]`（`aqi, level, primary, color_hex`；无数据时 `(None, "无数据", "—", <muted hex>)`）——签名与现状完全一致，3 个调用点不改

- [ ] **Step 1: 追加失败测试**

在 `tests/test_aqi.py` 末尾追加：

```python
def test_nwp_wrapper_matches_unified_implementation():
    """nwp 四元组包装必须与统一实现同源。"""
    from modules.nwp_forecast import _compute_cn_aqi

    conc = {"pm2_5": 115, "pm10": 60, "so2": 200, "no2": 300,
            "co": 12.0, "o3": 250}
    number, level, primary, color = _compute_cn_aqi(conc)
    unified = aqi.comprehensive_aqi(conc)
    assert number == unified["aqi"] == 150
    assert level == unified["level"] == "轻度污染"
    assert primary == unified["primary"] == "PM2.5"
    assert isinstance(color, str) and color.startswith("#")


def test_nwp_wrapper_no_data():
    """全空输入返回无数据四元组且不抛异常。"""
    from modules.nwp_forecast import _compute_cn_aqi

    number, level, primary, color = _compute_cn_aqi({})
    assert number is None
    assert level == "无数据"
    assert primary == "—"
    assert isinstance(color, str)


def test_nwp_private_breakpoint_tables_are_gone():
    """私有断点表必须已删除，避免与 config 双份维护。"""
    from modules import nwp_forecast

    for name in ("_PM25_BP", "_PM25_I", "_PM10_BP", "_PM10_I", "_SO2_BP",
                 "_SO2_I", "_NO2_BP", "_NO2_I", "_CO_BP", "_CO_I",
                 "_O3_BP", "_O3_I", "_AQ_POLLUTANTS", "_iaqi"):
        assert not hasattr(nwp_forecast, name), name


def test_nwp_level_table_kept_for_charts():
    """_AQ_LEVELS 是图表色带的数据源，必须保留。"""
    from modules import nwp_forecast

    assert hasattr(nwp_forecast, "_AQ_LEVELS")
    assert len(nwp_forecast._AQ_LEVELS) == 6
```

- [ ] **Step 2: 运行确认失败**

Run: `python -B -m pytest tests/test_aqi.py -v`
Expected: `test_nwp_private_breakpoint_tables_are_gone` 失败（属性仍在）；`test_nwp_wrapper_matches_unified_implementation` 也可能因 pm10 分档不同而失败（旧表 PM10 第二档到 150、新表到 150，但旧表 0-50/51-150 与新的相同；实际差异出现在 PM2.5 与 CO 分档上，故该用例在实施前即可能通过——若通过则以 `test_nwp_private_breakpoint_tables_are_gone` 作为红点即可）。

- [ ] **Step 3: 删除私有断点表**

在 `modules/nwp_forecast.py` 中删除从 `_PM25_BP = [0, 35, 75, ...]` 起、到 `_AQ_POLLUTANTS = [...]` 列表结束（即 `]` 收尾那一行）为止的整块（现第 270-291 行）。**不要**删除其后的 `_AQ_LEVELS`（现第 296-303 行），它是图表色带的等级映射表。

把该块上方原有的注释（现第 266-269 行，内容是「国标 HJ 633-2012：每种污染物自带…」）替换为：

```python
# 国标 AQI 分指数表的单一真相源是 config.AQI_BREAKPOINTS，计算由 modules.aqi 统一实现。
# 本模块不再持有断点表，仅保留下方的等级→色 token 映射供图表使用。
```

- [ ] **Step 4: 删除 `_iaqi` 并改写 `_compute_cn_aqi`**

删除 `def _iaqi(c, bp, iaqi_nodes):` 整个函数（现第 315-341 行）。

把 `def _compute_cn_aqi(conc):` 整个函数（现第 344-364 行）替换为：

```python
def _compute_cn_aqi(conc):
    """按国标由六项浓度计算 AQI，返回 (aqi:int|None, level:str, primary:str, color:str)。

    计算委托 modules.aqi.comprehensive_aqi（单一实现），本函数只做
    「四元组 + 具体色值」的适配：图表侧需要 hex 而非 var()。
    说明（A 方案）：PM2.5/PM10 国标用 24h 均值，此处以逐时浓度近似代入 24h 限值表，
    牺牲部分严谨度换取与 GFS 逐时曲线对齐；气态污染物用 1h 表，正确。
    标准版本见 config.AQI_STANDARD_LABEL。
    """
    result = comprehensive_aqi(conc or {})
    if result["aqi"] is None:
        return None, "无数据", "—", token_value("text-muted")
    return (result["aqi"], result["level"], result["primary"] or "无",
            _aq_color(aqi_token(result["level"])))
```

- [ ] **Step 5: 补导入**

现第 29 行为 `from modules.design_tokens import color_value, css_var, token_value, warn_token`，改为：

```python
from modules.design_tokens import (
    aqi_token,
    color_value,
    css_var,
    token_value,
    warn_token,
)
```

现第 28 行为 `from config import COLORS, safe_chart, _is_dark, WARN_LEVEL_ORDER, LIFE_INDEX_META as _LIFE_INDEX_META, WIND_DIRECTIONS`，追加 `AQI_STANDARD_LABEL`：

```python
from config import (AQI_STANDARD_LABEL, COLORS, safe_chart, _is_dark,
                    WARN_LEVEL_ORDER, LIFE_INDEX_META as _LIFE_INDEX_META,
                    WIND_DIRECTIONS)
```

在文件顶部导入区新增一行：

```python
from modules.aqi import comprehensive_aqi
```

- [ ] **Step 6: 运行确认通过**

Run: `python -B -m pytest tests/test_aqi.py -v`
Expected: PASS（30 项）

- [ ] **Step 7: 回归数值预报与天气墙测试**

Run: `python -B tests/test_weather_wall.py`
Expected: 全部通过（其 AQI 断言传入显式 dict，不依赖断点数值）

- [ ] **Step 8: 提交**

```bash
git add modules/nwp_forecast.py tests/test_aqi.py
git commit -m "refactor(aqi): nwp_forecast 删除私有断点表，计算委托 modules.aqi"
```

---

### Task 5: 收敛 `analyzer` 并接线标准标注

删除 `analyzer._calc_single_aqi`，让 `check_air_quality` 委托统一实现（对外返回结构不变，继续用 `_aqi_level_name` 得到色 token），把「实际所用标准版本」接到 UI 文本上。

**Files:**
- Modify: `modules/analyzer.py`（第 14 行导入、第 394 行注释、第 397-405 行 `_calc_single_aqi`、第 422-489 行 `check_air_quality`、第 1209 行标题）
- Modify: `modules/nwp_forecast.py`（第 1424 行注释、第 1893-1896 行 `st.caption`）
- Test: `tests/test_aqi.py`（追加一致性用例）

**Interfaces:**
- Consumes: Task 3 的 `comprehensive_aqi`、`config.AQI_STANDARD_LABEL`、`config.AIR_POLLUTANT_LIMITS`
- Produces: `modules.analyzer.check_air_quality(df) -> dict | None`（返回结构与现状一致：`aqi` / `primary` / `level` / `color` / `advice` / `details`；`details` 每项含 `field` / `label` / `avg` / `max` / `iaqi` / `level` / `color` / `limit` / `exceed_daily` / `exceed_hourly`）

- [ ] **Step 1: 追加失败测试**

在 `tests/test_aqi.py` 末尾追加：

```python
def test_analyzer_check_air_quality_delegates_to_unified():
    """analyzer.check_air_quality 结果与统一实现一致，且保留原返回结构。"""
    import pandas as pd
    from modules.analyzer import check_air_quality

    df = pd.DataFrame({
        "pm25": [115.0] * 24,
        "pm10": [60.0] * 24,
        "so2": [200.0] * 24,
        "nox": [300.0] * 24,
    })
    result = check_air_quality(df)
    unified = aqi.comprehensive_aqi({"pm25": 115.0, "pm10": 60.0,
                                     "so2": 200.0, "nox": 300.0})
    assert result["aqi"] == unified["aqi"] == 150
    assert result["level"] == unified["level"] == "轻度污染"
    assert result["primary"] == unified["primary"] == "PM2.5"
    assert set(result) == {"aqi", "primary", "level", "color", "advice", "details"}
    assert {d["field"] for d in result["details"]} == {"pm25", "pm10", "so2", "nox"}
    detail = [d for d in result["details"] if d["field"] == "pm25"][0]
    assert set(detail) == {"field", "label", "avg", "max", "iaqi", "level",
                           "color", "limit", "exceed_daily", "exceed_hourly"}
    assert detail["iaqi"] == 150
    assert detail["label"] == "PM2.5"


def test_analyzer_check_air_quality_no_pollutants_returns_none():
    """无污染物字段时返回 None。"""
    import pandas as pd
    from modules.analyzer import check_air_quality

    assert check_air_quality(pd.DataFrame({"temperature": [20.0]})) is None


def test_calc_single_aqi_removed():
    """旧的私有分指数函数必须已删除。"""
    from modules import analyzer

    assert not hasattr(analyzer, "_calc_single_aqi")


def test_standard_label_is_wired_into_ui_sources():
    """UI 文本所在的模块必须引用 AQI_STANDARD_LABEL，而不是硬编码版本号。"""
    import io

    for path in ("modules/analyzer.py", "modules/nwp_forecast.py"):
        full = os.path.join(_APP_DIR, path)
        with io.open(full, encoding="utf-8") as handle:
            source = handle.read()
        assert "AQI_STANDARD_LABEL" in source, "%s 未引用 AQI_STANDARD_LABEL" % path
```

- [ ] **Step 2: 运行确认失败**

Run: `python -B -m pytest tests/test_aqi.py -v`
Expected: `test_calc_single_aqi_removed` 失败（属性仍在）；`test_standard_label_is_wired_into_ui_sources` 失败（两个文件均未引用常量）

- [ ] **Step 3: 删除 `_calc_single_aqi` 并改写 `check_air_quality`**

删除 `modules/analyzer.py` 第 397-405 行的 `def _calc_single_aqi(conc, pollutant):` 整个函数（含其 docstring 与 `return 0`）。

保留第 408-419 行的 `_aqi_level_name`（改写后的 `check_air_quality` 仍使用它）。

把 `def check_air_quality(df):` 整个函数（现第 422-489 行）替换为：

```python
def check_air_quality(df):
    """
    综合 AQI + 逐污染物分析 + 健康建议。

    分指数与综合指数由 modules.aqi 统一计算（单一实现），本函数只负责
    从 DataFrame 取时段均值、做达标判断、组装 UI 所需的返回结构。
    实际所用标准版本见 config.AQI_STANDARD_LABEL。

    返回: dict | None（无污染物字段时为 None）
    """
    pollutant_fields = [
        ("so2",  "SO₂"),
        ("nox",  "NO₂"),
        ("pm10", "PM10"),
        ("pm25", "PM2.5"),
    ]
    available = [(field, label) for field, label in pollutant_fields
                 if field in df.columns and df[field].dropna().any()]

    if not available:
        return None

    means = {field: float(df[field].dropna().mean()) for field, _label in available}
    unified = comprehensive_aqi(means)
    by_key = {d["key"]: d for d in unified["details"]}

    results = []
    for field, label in available:
        key = POLLUTANT_ALIASES.get(field, field)
        detail = by_key.get(key)
        if detail is None:
            continue
        vals = df[field].dropna()
        mean_conc = float(vals.mean())
        max_conc = float(vals.max())

        # 达标判断（GB 3095 二级标准限值；与 AQI 断点表是两张不同的表）
        limits = AIR_POLLUTANT_LIMITS.get(field, {})
        daily_limit = limits.get("daily")
        hourly_limit = limits.get("hourly")
        exceed_daily = mean_conc > daily_limit if daily_limit else False
        exceed_hourly = bool(max_conc > hourly_limit) if hourly_limit else False

        label_name, color = _aqi_level_name(detail["iaqi"])

        results.append({
            "field": field,
            "label": label,
            "avg": round(mean_conc, 1),
            "max": round(max_conc, 1),
            "iaqi": detail["iaqi"],
            "level": label_name,
            "color": color,
            "limit": daily_limit,
            "exceed_daily": exceed_daily,
            "exceed_hourly": exceed_hourly,
        })

    if not results:
        return None

    overall_level, overall_color = _aqi_level_name(unified["aqi"])
    return {
        "aqi": unified["aqi"],
        "primary": unified["primary"],
        "level": overall_level,
        "color": overall_color,
        "advice": AQI_ADVICE.get(overall_level, ""),
        "details": results,
    }
```

- [ ] **Step 4: 修正 `analyzer.py` 的导入行**

把现第 14 行

```python
    AQI_BREAKPOINTS, AQI_LEVELS, AQI_ADVICE, AIR_POLLUTANT_LIMITS,
```

替换为

```python
    AQI_ADVICE, AQI_LEVELS, AQI_STANDARD_LABEL, AIR_POLLUTANT_LIMITS,
```

（删掉不再需要的 `AQI_BREAKPOINTS`，保留 `AQI_LEVELS` 供 `_aqi_level_name` 使用，新增 `AQI_STANDARD_LABEL`。）

在现第 21 行 `)` 之后、第 23 行注释之前，新增：

```python
from modules.aqi import POLLUTANT_ALIASES, comprehensive_aqi
```

- [ ] **Step 5: 修正 `analyzer.py` 的标准标注**

现第 394 行 `# 大气环境质量评估 (GB 3095-2026 + HJ 633-2026)` 改为：

```python
# 大气环境质量评估（AQI 分指数口径见 config.AQI_STANDARD_LABEL）
```

现第 424 行 docstring 中「基于 HJ 633-2012 计算综合 AQI」一句由 Step 3 的整体替换一并去掉。

现第 1209 行

```python
        st.write("### [大气] 空气质量评估 (GB 3095-2026)")
```

改为

```python
        st.write(f"### [大气] 空气质量评估（{AQI_STANDARD_LABEL}）")
```

（该函数将在第 5 批次随 Tab 改造删除，本步先保证页面不说谎。）

- [ ] **Step 6: 修正 `nwp_forecast.py` 的标准标注**

现第 1424 行注释 `# 实时空气质量（国标 HJ 633-2012）` 改为：

```python
    # 实时空气质量（AQI 分指数口径见 config.AQI_STANDARD_LABEL）
```

现第 1893-1896 行为两个相邻字符串字面量的隐式拼接，把第二个字面量改为 f-string：

```python
    st.caption(
        "数据来源：CAMS 全球大气成分预报（Open-Meteo Air Quality API，最长 7 天）。"
        f"国标等级按 {AQI_STANDARD_LABEL} 计算，PM2.5/PM10 采用逐时近似。"
    )
```

现第 370 行 docstring 中的「（国标 HJ 633-2012）」改为「（口径见 config.AQI_STANDARD_LABEL）」。

- [ ] **Step 7: 运行确认通过**

Run: `python -B -m pytest tests/test_aqi.py -v`
Expected: PASS（34 项）

- [ ] **Step 8: 全量回归**

Run:
```
python -B tests/test_analyzer.py
python -B tests/test_data_quality.py
python -B tests/test_codec.py
python -B tests/test_weather_wall.py
python -B -m pytest tests -q
```
Expected: 四个门禁脚本全部通过；pytest 全量无新增失败

- [ ] **Step 9: 应用启动冒烟**

Run: `python -c "import modules.aqi, modules.analyzer, modules.nwp_forecast, modules.weather_wall, modules.visualizer"`
Expected: 无输出、退出码 0。若再导入 `app`，需已配置 Supabase 密钥；未配置时仅确认 `modules.*` 全部可导入即可。

- [ ] **Step 10: 提交**

```bash
git add modules/analyzer.py modules/nwp_forecast.py tests/test_aqi.py
git commit -m "refactor(aqi): analyzer 删除私有分指数实现并接线标准版本标注"
```

---

## 完成标准

1. `modules/aqi.py` 是全项目唯一的 IAQI / 综合 AQI 实现；`analyzer._calc_single_aqi`、`nwp_forecast._iaqi` 与 12 张私有断点常量、`_AQ_POLLUTANTS` 均已删除。
2. `config.AQI_BREAKPOINTS` 覆盖 6 项污染物，`validate_breakpoints(AQI_BREAKPOINTS) == []`。
3. PM2.5 = 5000 μg/m³ 时 `iaqi` 返回 500（原实现返回 0 并显示「优」）；O₃ = 9999 μg/m³ 时返回 200。
4. `config.AQI_STANDARD_LABEL == "HJ 633-2012"`，且 `modules/analyzer.py` 与 `modules/nwp_forecast.py` 引用该常量。
5. `python -B tests/test_aqi.py`、`python -B tests/test_analyzer.py`、`python -B tests/test_weather_wall.py` 全部通过；`python -m pytest tests -q` 无新增失败。
6. `nwp_forecast._compute_cn_aqi` 的四元组签名未变，`weather_wall.py:242`、`nwp_forecast.py:421`、`nwp_forecast.py:1430` 三处调用点未被修改（可用 `git diff` 确认这三行不在改动范围内）。
7. `nwp_forecast._AQ_LEVELS` 保留且有 6 档，`test_level_tables_do_not_drift` 通过。

## 与 spec 的偏差记录

- spec 第 5.5.5 节原写「`AQI_STANDARD_LABEL` 或为 `HJ 633-2026`」；本计划据用户 2026-09-13 的决定固定为 `"HJ 633-2012"`，数值表与理由已补记进 spec。
- spec 第 5.2.10 节原把 `check_air_quality` 列入保留清单；本计划说明它将在第 5 批次随 `_render_air_quality_section` 删除（spec 已同步修正）。本批次仍保持其对外返回结构可用，因此删除只发生在第 5 批次。
- `nwp_forecast._AQ_LEVELS` 予以保留（图表色带渲染在 `nwp_forecast.py:359/469/478/545` 有 4 处依赖），改为新增一致性测试锁死它与 `config.AQI_LEVELS` 不漂移，而不是删除。
- spec 未提及 `config.AQI_LEVELS` 末档为 `(301, 500)` 而 `nwp_forecast._AQ_LEVELS` 末档为 `(301, 99999)` 的差异。由于 `iaqi` 的最大钳制值为 500，该差异不可达，本计划用「截到 500 后比对」的方式在测试中消化它。
