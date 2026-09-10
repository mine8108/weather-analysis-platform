# 暗色模式改造：审计与验证工具

本目录存放本次「暗色模式系统化改造」配套的**可复算**工具。
每个脚本都是独立可执行的，不依赖浏览器插件，可在 CI 或本地直接跑。

## 常驻检查器（建议每次改动配色后运行）

| 脚本 | 作用 | 通过标准 |
|---|---|---|
| `check_py_vars.py` | 校验 Python 源码引用的每个 CSS 变量都能解析到 token 表（用 ast 区分代码与文档字符串） | 退出码 0 |
| `check_plotly_cssvar.py` | 检查图表代码是否误用 `var(--token)`——plotly.js 绘制 SVG，**不解析 CSS 自定义属性**，写了会静默失效 | 退出码 0 |
| `darkmode_contrast_probe.py --check` | 对亮/暗两套 token 做 WCAG 2.1 对比度审计（正文 4.5:1），并把带 alpha 的语义底色先合成到卡片底再计算 | 退出码 0 |

```bash
python research/check_py_vars.py
python research/check_plotly_cssvar.py
python research/darkmode_contrast_probe.py --check
```

`darkmode_contrast_probe.py` 不带参数时会输出一段探针 HTML，
把当前主题下每个 token 的真实取值渲染成色块，便于人工核对。

## 一次性迁移脚本（记录改动来源，已执行完毕）

这些脚本记录了改造过程中**批量替换的具体规则与理由**。
它们锚定的是改造前的代码形态，现在重跑会报「无匹配」或「行号漂移」，
属于预期行为——保留是为了让「改了什么、为什么这么改」可追溯。

| 脚本 | 迁移内容 |
|---|---|
| `migrate_life_index_colors.py` | 生活指数严重度色 hex → token 名（31 处） |
| `migrate_chart_colors.py` | 图表主题三元表达式 → token 引用（15 处） |
| `migrate_colors_table.py` | `COLORS["key"]` → `color_value("key")`（50 处） |
| `migrate_chart_cssvar.py` | 图表上下文里误用的 `css_var()` → `token_value()`（15 处） |

## 浏览器侧验证

DOM 级验证依赖 Playwright（本机缓存的 chromium），脚本位于会话临时目录，
不在仓库内。核心思路记录在此以便复现：

- **亮底元素扫描**：暗色主题下遍历所有元素，找出计算背景亮度 > 0.55 且尺寸
  > 10px 的元素，并打印其祖先 `data-testid` 链。这是发现
  「`stNumberInputContainer` 仍是纯白」「React-Aria selectbox 外壳未覆盖」
  等问题的关键手段——只靠截图肉眼比对会大量漏检。
- **对比度实测**：不只看 token 字面量，而是把 `var()` 塞进隐藏探针元素，
  读 `getComputedStyle` 拿到**解析后的** rgb，再算 WCAG 比值。
- **Plotly 模板生效性**：读渲染后 SVG 的 `.gridlayer` 描边色与 `rect.bg`
  填充色。网格线用模板色说明模板已生效；背景填充若仍为主题色，
  说明前端组件覆盖了它，需要把取值写进 figure 的 `layout` 而非仅留在 template。

## 判定标准汇总

- 暗色主题下**不得存在**亮度 > 0.55、尺寸 > 10px 的实心背景元素；
- 亮色主题下**不得存在**面积 > 120×30 的实心深色背景元素；
- 正文类文字对比度 ≥ 4.5:1（大号加粗亦从严按 4.5:1）；
- 图表网格线与刻度文字取自当前主题模板，画布背景透明（由卡片底色承担）。
