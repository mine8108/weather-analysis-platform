# 主题改造与发布核对：审计与验证工具

本目录存放配套的**可复算**工具。每个脚本独立可执行，不依赖浏览器插件，可在 CI 或本地直接跑。

## 常驻检查器（建议每次改动配色后运行）

| 脚本 | 作用 | 通过标准 |
|---|---|---|
| `check_py_vars.py` | 校验 Python 源码引用的每个 CSS 变量都能解析到 token 表（用 ast 区分代码与文档字符串） | 退出码 0 |
| `check_plotly_cssvar.py` | 检查图表代码是否误用 `var(--token)`——plotly.js 绘制 SVG，**不解析 CSS 自定义属性**，写了会静默失效 | 退出码 0 |
| `check_chart_colors.py` | 真实调用图表函数，检查 figure 内所有颜色属性是否为 Plotly 认可的实值（拦截「token 名泄漏进 Plotly」这类只在运行时暴露的问题） | 退出码 0 |
| `darkmode_contrast_probe.py --check` | 对亮/暗两套 token 做 WCAG 2.1 对比度审计（正文 4.5:1），并把带 alpha 的语义底色先合成到卡片底再计算 | 退出码 0 |
| `check_deploy.py` | 发布核对：比对仓库 `APP_VERSION`、线上页脚版本号、本地提交与远端的关系 | 退出码 0 |

```bash
python research/check_py_vars.py
python research/check_plotly_cssvar.py
python research/check_chart_colors.py
python research/darkmode_contrast_probe.py --check
python research/check_deploy.py
```

`darkmode_contrast_probe.py` 不带参数时会输出一段探针 HTML，
把当前主题下每个 token 的真实取值渲染成色块，便于人工核对。

### check_deploy.py：为什么需要它

`git push` 成功、远端 `main` 已更新，**不等于** Streamlit Cloud 已经重建容器。
2026-09-11 的 v2.3.0 发布就踩过这个坑：合并与推送全部成功，但线上连续十余分钟仍返回旧
版本号，容器最后一次启动时间停在推送之前。这种「已合并未部署」是**静默**的，会让人误以为
线上已是新版。本脚本把那次人工排查固化下来。

实现上有三个坑，都已在代码里注释：

1. **版本号在鉴权门之后**。`APP_VERSION` 渲染在侧边栏页脚，未登录时页面只有登录卡片，
   任何位置都读不到版本号。因此脚本需要可选凭据——只从环境变量
   `DEPLOY_CHECK_EMAIL` / `DEPLOY_CHECK_PASSWORD` 取，**不进仓库、不打印**。
   未提供凭据时会明确报「无法确认」（退出码 2），不谎报通过。
2. **应用正文读不到**。Streamlit 把应用渲染在同源 iframe 里，它不是独立 CDP 目标，只是
   主页面目标下的子 frame；而且同源子 frame 在**默认执行上下文**里求值只返回空串，必须
   经 `Page.createIsolatedWorld` 建一个隔离上下文才读得到。这一点是靠 `Page.getFrameTree`
   逐 frame 实测出来的，不是猜的。
3. **登录卡片没有 `<form>`**。实测 `document.forms.length === 0`，所以不能 `requestSubmit`，
   只能按可见文案点提交按钮。

`cdp_client.py` 是配套的极简 CDP 客户端（仅标准库：手写 WebSocket 握手与成帧），
目的是让整个检查**零第三方依赖**——不需要 Python 的 playwright、也不需要 Node 的
npm install，只要本机有 Chrome / Edge / Chromium。它只实现本项目需要的三件事：
建目标、挂载会话、求值一段 JS。

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

DOM 级验证有两种做法，都记录在此以便复现。

**一、标准化做法：`check_deploy.py` + `cdp_client.py`**（零第三方依赖，见上文）。
适用于「线上到底跑的是哪个版本」这类需要登录后才可见的核对。

**二、交互式排查**适用于「为什么这个元素在暗色下是白的」这类探索性问题。
本次改造用的是 Playwright（本机缓存的 chromium），脚本位于会话临时目录、不在仓库内。
核心手段：

- **亮底元素扫描**：暗色主题下遍历所有元素，找出计算背景亮度 > 0.55 且尺寸
  > 10px 的元素，并打印其祖先 `data-testid` 链。这是发现
  「`stNumberInputContainer` 仍是纯白」「React-Aria selectbox 外壳未覆盖」
  等问题的关键手段——只靠截图肉眼比对会大量漏检。
- **对比度实测**：不只看 token 字面量，而是把 `var()` 塞进隐藏探针元素，
  读 `getComputedStyle` 拿到**解析后的** rgb，再算 WCAG 比值。
- **Plotly 模板生效性**：读渲染后 SVG 的 `.gridlayer` 描边色与 `rect.bg`
  填充色。网格线用模板色说明模板已生效；背景填充若仍为主题色，
  说明前端组件覆盖了它，需要把取值写进 figure 的 `layout` 而非仅留在 template。

**踩过的坑（省下后来人一次重走）**：

- 应用的 DOM 在 iframe 内，读**外层** `document.body.innerText` 永远是 0，会误判成
  「页面空白」。必须先定位到应用那个 frame。
- Streamlit 的 `stCheckbox` 把真实 `<input>` 包在 `clip-path: inset(50%)` 的隐藏
  span 里，同级另有承载外观的 div，所以 `input:checked + div` 这种兄弟选择器**永远
  匹配不上**，勾选态只能用 `:has(input:checked)` 挂在容器上。
- React-Aria 组件（如 selectbox）忽略元素级 `.click()`，需要真实坐标或原生键盘事件。

## 判定标准汇总

- 暗色主题下**不得存在**亮度 > 0.55、尺寸 > 10px 的实心背景元素；
- 亮色主题下**不得存在**面积 > 120×30 的实心深色背景元素；
- 正文类文字对比度 ≥ 4.5:1（大号加粗亦从严按 4.5:1）；
- 图表网格线与刻度文字取自当前主题模板，画布背景透明（由卡片底色承担）。
