# 产品信息架构与交互流程审计（B 号，只读）

审计对象：`weather_app`（Streamlit 1.59 单体应用，提交 `9023696` 工作区状态）。
审计范围：用户可见结构，即从打开页面到拿走一份结果的路径上有多少结构性摩擦。
只读声明：本报告未修改任何源码、配置或测试；仓库内唯一新增文件是本文件。唯一被执行的仓库脚本是既有的
`research/darkmode_contrast_probe.py --check`（纯计算，无网络、无密钥）。另外用 Streamlit 自带的
`AppTest` 在进程内跑了三个最小探针（不启动服务器、不连接 Supabase），探针源码在系统临时目录，见文末
「证据索引」。

不重复既往发现：`research/内部不一致清单-2026-09-13.md` 的 8 条、`docs/superpowers/plans/` 的五个计划
及其实施记录已逐条读过。已在清单中登记的「天气墙两个开关不相邻」本报告不再展开（清单第 7 项）。本报告
与 A 号（代码架构）、C 号（部署与运行时安全）的分工见文末。

---

## 一句话结论

6 个 Tab 与 6 个渲染模块一一对应，组织依据是模块交付物；用户任务阶段没有成为切分依据。真正的主路径
（导入 → 质控 → 分析 → 导出）横跨 4 个 Tab，而每一步的上下文都会以不同方式丢失。最贵的摩擦有四处：首屏把所有人挡在零信息页且没有
自助进入路径；8 类预警检测没有 UI 归属，报告是否漏报取决于用户有没有点过 AI 读图 Tab；三处「看起来
能点」的按钮实际无效；导入向导把「渲染一次」当成「用户提交一次」，会静默重复合并数据。这些问题的共同
特征是**不报错**，所以不会被测试和日志发现，只会让用户得到错误结论或反复重来。

---

## 主路径走查（从打开到导出）

以「第一次访问者要拿到一份 Word 报告」为目标，逐步标注摩擦点。F 编号在正文中被引用。

| 步 | 用户动作 / 看到什么 | 摩擦点 | 证据 |
|---|---|---|---|
| F1 | 打开 URL，只看到登录/注册表单与一个「管理员入口」折叠区 | 首屏没有任何产品证据，游客正文约 146 字符；无「如何获得邀请码」的联系路径 | `app.py:437-439`、`research/README.md:37-38`、`auth.py:293-334` |
| F2 | 选「注册」，填邮箱密码，提交后被告知要邀请码 | 模式单选在 `st.form` 内，邀请码输入框要等一次提交触发重跑才出现，第一次提交必然报错 | `auth.py:296-318` |
| F3 | 登录成功，无数据，主区是天气墙 | 首次为空：占位卡「天气墙还空着」，必须手动搜索或定位；手册却写「默认预置 34 城，首页最多 6 卡」 | `weather_wall.py:671-677`、`weather_wall.py:736-738`、`docs/用户使用手册.md:140` |
| F4 | 同屏还有「⚡ 快速开始 — 导入数据」与下方向导的 3 个大按钮 | 两个入口做同一件事；导航条在两者之下，首屏看不到完整层级 | `app.py:376-384`、`app.py:657-695`、`app.py:703-732` |
| F5 | 点「上传文件」，进入第 1 步，导入成功后自动进第 2 步 | 全流程没有步骤指示，只有页面标题「Step 2」；手册叫「第 0/1/2 步」，界面从 Step 1 起算 | `app.py:714-776`、`docs/用户使用手册.md:182-188` |
| F6 | 第 2 步看三项指标、前 10 行、质控报告，点「确认数据」 | 质控评分与明细只在这一步可见；确认后 `import_step` 归 0，再回导入 Tab 就看不到质量报告了 | `app.py:776-815`、`app.py:159-257` |
| F7 | 到可视化，顶部出现摘要卡（日期筛选、3 个跳转、保存到云端） | 日期筛选只作用于可视化，导出与预警仍用全量数据；保存成功的提示被随后的 `st.rerun()` 吞掉 | `app.py:204-213`、`app.py:886`、`app.py:913-921`、`app.py:251-256` |
| F8 | 去数值预报 | 必须手填经纬度与天数，不会从已导入数据（标准字段里有 `longitude/latitude`）带出；与数据无联动 | `app.py:928-929`、`modules/nwp_forecast.py:1819-1827` |
| F9 | 去 AI 读图 | 不依赖数据，本可独立成事；但结果与输入都是「一次性」的，切 Tab 回来图片列表被清空 | `modules/chart_reader.py:437-540`、`modules/chart_reader.py:467-468` |
| F10 | 去报文解码，粘贴、解码、想把记录并入手动录入 | 「+ 加入手动录入」按钮无效（写在解码按钮的点击分支里）；解码结果在任何一次重跑后消失 | `modules/codec.py:301-347` |
| F11 | 去报告导出 | 无数据时页面仍显示空的两列 CSV 与可点的生成按钮；生成后提示被 `st.rerun()` 覆盖；报告里的预警取决于 F9 有没有发生过 | `modules/reporter.py:1128-1202`、`app.py:890-908` |
| F12 | 发现数据不对，点侧边栏「重置当前模块数据」 | 清理表按 Tab 硬编码，`api_df`、`manual_data` 等键不在其中，重置不彻底 | `app.py:100-142` |
| F13 | 某个 Tab 抛异常，点「重置会话并回到首页」 | 清空全部业务数据，提示语却说「不影响其他功能」 | `app.py:64-96` |
| F14 | 刷新页面或按浏览器后退 | 刷新等于退出登录（Supabase 客户端只活在 `session_state`，没有 cookie/token 持久化）；全仓没有 URL 路由，深链不存在 | `auth.py:38-39`、`auth.py:147-155`、`README.md:296-299`、全仓检索 `query_params` 无命中 |
| F15 | 打开侧边栏手册 | 独立页 1009 行、14 章，是当前唯一的 onboarding；但它描述的若干交互与实现不符 | `modules/manual.py:163-217`、`app.py:444-449`、S2-8 |

最短可完成路径的代价：登录 → 封面 → 导入（方式 → 输入 → 预览/质控）→ 确认 → 可视化 → 导出 → 生成 →
下载，共 5 次导航、2 次隐式自动跳转，中途任何一次刷新或切换 Tab 都可能丢掉上下文。

---

## S1（结构性：不修会持续造成流失、误操作或支持成本）

### S1-1 登录门禁：零信息首屏 + 无自助进入路径 + 刷新即登出

**证据**

`app.py:437-439`
```python
if not is_authenticated():
    render_auth_page()
    st.stop()
```

`auth.py:293-334`（节选）
```python
st.markdown("## 气象数据交互分析平台")
st.caption("登录或注册后使用 · 数据按账号私有隔离 · 注册需邀请码")

with st.form("auth_form"):
    mode = st.radio("操作", ["登录", "注册"], horizontal=True, key="auth_mode")
    ...
    if mode == "注册":
        invite_code = st.text_input(
            "邀请码", placeholder="向管理员索取", key="auth_invite"
        ).strip().upper()
...
st.info("注册需有效邀请码，由管理员在下方「管理员入口」生成并分发。")
_render_admin_panel()
```

游客能看到什么：登录页的全部内容。仓库自己的实测记录写着「未登录时页面正文只有约 146 字符、止步于
『管理员入口』」（`research/README.md:37-38`）。没有截图、没有示例数据、没有功能预告。

注册路径还有一处局部摩擦：模式单选在 `st.form` 内，表单只在提交时把控件值送回服务端，所以选「注册」
不会立刻显示邀请码输入框，第一次提交只会得到「请填写邀请码」（`auth.py:303-315`）。这是一次必付的
往返，按 Streamlit 表单语义推断，未在浏览器实测。

登录态的生命周期：Supabase 客户端按会话缓存在 `st.session_state`（`auth.py:147-155`），没有 cookie 或
token 持久化通道（全仓检索 `cookie|localStorage|sessionStorage` 无实现命中）。浏览器刷新会新建会话，
于是回到登录页。README 的「重新登录时会自动载入最近一次保存的数据集」（`README.md:299`）默认了这一点。

**a) 根因**

数据私有隔离、存储配额、读图计费全部绑在 `user_id` 上（`README.md:246-299`），把门禁放在 `app.py` 最外层
是当时最省事的安全默认。注册从公开改为邀请码后（`README.md:254`），权限入口收敛了，但「没有码的人怎么
办」没有对应的界面决策。管理员面板长在登录页，是因为 service_role 管理操作只在那里被实现过；管理入口与
终端用户入口因此共用一屏。

**b) 不修的长期代价**

- 评审者、同学、潜在用户的第一分钟得不到任何产品证据，也无法自助获取访问权限，「向管理员索取」没有给出
  任何联系方式，路径在此终止。
- 每次刷新都要重新登录。手册与界面至少三处把「刷新页面」当成恢复手段（手册第 444–449 行的配额表、
  第 897 行的等待提示，以及 `modules/chart_reader.py:523` 的会话上限文案），等于建议用户登出后重来，
  未保存的导入数据同时丢失。
- 首屏有一个「管理员入口」折叠区，文案还告诉普通用户邀请码由它生成，等于把管理面暴露给所有人，同时
  让管理员必须先登出才能生成邀请码。

**c) 最小修复切口（一个交互决策，1 个文件）**

把 `app.py:437-439` 的未登录分支从「只剩表单」改成「只读产品预览 + 登录卡」：天气墙不依赖用户数据，可以
先渲染；登录卡上方加三行能力说明与「如何获取邀请码」（部署者联系方式或申请方式）；再加一个「加载示例
数据」入口，读 `示例数据/` 里的 CSV，只允许可视化/质控/导出，禁用云保存、GFS 缓存、AI 读图。全部改动在
`app.py` 一个文件内，`auth.py` 不动。

**d) 保留现状的理由（对抗性审查）**

公开预览会把无密钥的 Open-Meteo 天气墙暴露给匿名流量（虽有 10 分钟缓存，仍按访客量计入限流），「示例
数据」模式一旦写不好，可能被当成绕过登录与配额的通道。课程/隐私场景下「必须登录」本身是合理的安全默认。
所以可接受的最小范围只包括静态示例数据与天气墙，AI 读图、GFS、云存储仍然必须登录；如果连这个范围都不
接受，退一步只改 `auth.py` 加产品说明与邀请获取路径，风险为零但收益有限。

---

### S1-2 8 类事件检测没有 UI 归属，报告结论取决于用户有没有点过「AI 读图」

**证据**

`app.py:890-908`（节选）
```python
if st.session_state["active_tab"] == 3:
    if st.session_state["df"] is not None:
        fp = _df_fingerprint(st.session_state["df"])
        if st.session_state.get("_warn_fp") != fp:
            all_w = []
            checks = [
                ("高温", check_high_temperature), ("寒潮", check_cold_wave),
                ...
            ]
            for name, fn in checks:
                try:
                    all_w += fn(st.session_state["df"])
                except Exception as e:
                    st.warning(f"{name}检测因数据问题跳过: {e}")
            st.session_state["warnings_list"] = all_w
```

`app.py:913-921`
```python
if st.session_state["active_tab"] == 4:
    _safe_render(
        "报告导出",
        render_export_tab,
        st.session_state["df"],
        st.session_state.get("warnings_list", []),
        ...
    )
```

全仓检索 `warnings_list`，唯一写入检测结果的点是 `app.py:907`（其余两处是初始化为空），读取点只有报告
导出。界面上没有任何地方展示观测数据的检测结果；数值预报 Tab 展示的是预报侧的 `analysis["warnings"]`，
与观测侧是两套。手册第 555 行还写明「没有预警事件时不出现事件检测与防御建议节」。

**a) 根因**

旧版 Tab 3 是「智能分析与建议」，检测长在那里；改造成 AI 读图（`docs/superpowers/plans/2026-09-13-04-chart-reader.md`）
时，页面内容换了，检测代码留在原地当副作用（`app.py:890` 的注释仍写着「数据指纹缓存」）。README 首段与
「预警标准」章节仍把国家预警匹配当核心卖点（`README.md:3`、`README.md:232-238`），产品面却没有对应入口。
这是模块边界与信息架构脱节的典型形态：功能还在，家没了。

**b) 不修的长期代价**

同一份数据，用户先点开 AI 读图再导出，报告有「事件检测与预警」章；直接去导出，报告没有这一章，读者会
理解成「没有触发预警」。结论不可复现，且错在安静处。演示或答辩时如果按「导入 → 导出」的最短路径操作，
平台最核心的预警能力会在成品里消失。

**c) 最小修复切口（1 个文件）**

把检测从「tab 3 渲染副作用」提升为「数据就绪即计算」：在 `_render_data_summary_card` 进入时（`df` 变化时）
算一次并缓存 `_warn_fp`；摘要卡加一行「检出 N 个预警事件」并在可视化顶部提供一个只读列表。报告逻辑不改，
只是不再依赖用户是否访问过读图 Tab。

**d) 保留现状的理由（对抗性审查）**

检测是纯 pandas 逻辑（8 个函数），放在导出前计算也说得通；但「在界面里展示」会新增一块 UI 与一套阈值
解释，和侧边栏自定义阈值、Word 报告的防御建议存在三处口径要同步。最小改动可以先只算不展示，把报告漏报
修掉，展示留到下一批。

---

### S1-3 多处「看起来能点」的按钮实际无效；解码结果不落状态

**证据 A：嵌套按钮（报文解码）**

`modules/codec.py:301-347`（节选）
```python
if st.button("[搜索] 解码", use_container_width=True, key="decode_btn"):
    ...
    if result:
        st.success(f"[OK] 解码成功 | 站点: {result.get('station_id', 'N/A')}")
        ...
        if st.button("[+] 将此记录添加到手动录入区", use_container_width=True):
            st.session_state["manual_data"].append(result)
            st.success("已添加！请切换到数据导入 Tab 查看")
```

**证据 B：同类写法（API 使用）**

`modules/data_loader.py:691-721`（节选）
```python
if st.button("[搜索] 获取气象数据", use_container_width=True, key="api_fetch"):
    ...
    st.session_state["api_fetched_weather"] = df
    ...
    if st.button("[使用] 使用气象数据", use_container_width=True, key="api_use_weather_solo"):
        st.session_state["api_df"] = weather
        st.session_state["api_source"] = st.session_state["api_weather_source"]
        st.rerun()
```
合并版按钮（`data_loader.py:711`、`data_loader.py:762`）与空气质量版（`data_loader.py:769`）是同一结构，同样
嵌在「获取」按钮的点击分支内。

**证据 C：封面主按钮在无数据时是空操作**

`app.py:376-384`（节选）
```python
c1, c2, c3 = st.columns([1, 2, 1])
with c2:
    if st.button("⚡ 快速开始 — 导入数据", use_container_width=True, type="primary",
                 key="onboard_quick"):
        # 进入导入流程后关闭封面标志：导入完成即回到数据摘要卡视图
        st.session_state["_wall_cover"] = False
        _navigate_to(0)
````app.py:661-662`
```python
if not has_any_data or st.session_state.get("_wall_cover", False):
    _render_onboarding_page()
```
首次登录时没有数据，`not has_any_data` 恒为真，`_wall_cover` 置否不改变分支；`active_tab` 本来就是 0，
`_navigate_to(0)` 只触发一次同样的渲染。也就是说，首屏唯一的 primary 按钮点下去页面没有任何变化。这个按钮
只在「有数据且用户主动回到封面」时才真正有意义。

**证据 D：机制复现（8 行最小脚本，AppTest 进程内运行，输出为实测）**

```python
if st.button("fetch", key="fetch"):
    st.session_state["fetched"] = True
    if st.button("use", key="use"):
        st.session_state["hit"] += 1
```
```
run1 buttons: ['fetch']
run2 (after fetch) buttons: ['fetch', 'use']
hit after fetch: 0
run3 (after use click) buttons: ['fetch']
hit after use click: 0
```
点击 `use` 的那次 rerun 里外层 `if st.button("fetch")` 为 False，`use` 按钮不会被渲染，点击事件没有观察者。
这是 Streamlit 按钮事件模型的直接结果：按钮值只在它触发的那一次 rerun 中为 True。

**证据 E：结果不持久**

`modules/codec.py:301-319` 里 `result` 是局部变量；任何一次重跑（改报文类型、切 Tab、改主题）都会让解码
结果消失。用同样的 AppTest 验证「条件渲染导致 widget 值丢失」：一个带 `key` 的 `st.text_area` 在切到别的
Tab 再切回来之后为空（`back on A value:` 空串）。手册第 440 行只承认了上传区会被清空，没有覆盖文本框。

**a) 根因**

「获取结果 → 使用结果」被写成了父子代码块，符合线性脚本的直觉，与 Streamlit 的事件模型不符；API 的
「使用」按钮是后来加的 P0 优化（`modules/data_loader.py:707` 注释），加在既有分支内部。封面主按钮则源于
「封面标志 + active_tab」两个状态各自有效、组合起来无效：它把「关闭封面」当成「进入导入」，但导入内容
本来就已经在下方渲染。解码结果同样没有提升到 `session_state`，因为做完即用是当时的假设。

**b) 不修的长期代价**

手册第 163 行与第 5.1 节（第 176 行）都把「加入手动录入」「使用并合并」写成可用功能，用户会反复点击并
怀疑是自己的数据或网络问题；首屏唯一的 primary 按钮无反应，用户会先怀疑页面卡住。报文解码这条「粘贴即得
结构化数据」的链路实际是断的，而这恰好是最容易被演示的功能，也是支持成本最高的形态。

**c) 最小修复切口（2 个文件）**

把解码结果与 API 抓取结果写入显式 `session_state` 键，在「解码按钮 / 获取按钮」分支之外渲染结果区与
「加入手动录入 / 使用数据」按钮；或者给这两个按钮挂 `on_click` 回调。`_RESET_KEYS_BY_TAB` 同步加上新键，
避免重置后残留。封面主按钮的二选一：删掉它（向导就在下方），或改成「滚动到导入向导」并在标题上做一次
视觉强调。

**d) 保留现状的理由（对抗性审查）**

嵌套按钮在视觉上没有坏，只表现为点击无反应，因此线上没有异常日志；一旦改，必须同时处理「重置后旧结果
残留」与「重复点击」两个状态问题，改动面比看起来大。相比之下，最小的一步是先把结果落到 session 并移到
分支外，回调方案留到后续。封面主按钮可以暂时只改文案（「在下方选择导入方式」），成本几乎为零。

---

### S1-4 导入向导把「渲染一次」当「提交一次」：手动记录会被重复合并，陈旧 API 数据会直接进第 2 步

**证据 A：手动录入自动跳步并重复合并**

`app.py:753-766`
```python
elif method == "manual":
    df_manual = _safe_render("导入-手动", render_manual_input_section)
    if df_manual is not None:
        ...
        if st.session_state["df"] is not None:
            st.session_state["df"] = pd.concat([st.session_state["df"], df_manual], ignore_index=True)
        else:
            st.session_state["df"] = df_manual
        st.session_state["import_step"] = 2
        st.rerun()
```

`modules/data_loader.py:526-535`
```python
if "manual_data" in st.session_state and st.session_state["manual_data"]:
    ...
    manual_df = pd.DataFrame(st.session_state["manual_data"])
    st.dataframe(manual_df, use_container_width=True)
    ...
    return manual_df
```

`manual_data` 一旦非空，`render_manual_input_section` 每次渲染都会返回整张表；`app.py` 每次拿到返回值就
`pd.concat` 并跳到第 2 步。于是：添加第一条记录后界面自动进入第 2 步；点「← 返回上一步」回到手动录入，
渲染立刻把同一批记录再 concat 一遍并再次跳到第 2 步。每往返一次行数翻倍。

**证据 B：重新导入不清派生数据**

`app.py:821-833`（节选）
```python
if st.button("🔄 重新导入", use_container_width=True, key="wiz_retry"):
    st.session_state["import_step"] = 0
    st.session_state["import_method"] = None
    st.session_state["df"] = None
    st.session_state["source"] = ""
    st.session_state["warnings_list"] = []
    st.session_state["quality_score"] = 0.0
    ...
    st.session_state["_filter_date_range"] = None
```

这份清单里没有 `manual_data`，也没有 `api_df`。而 `modules/data_loader.py:818` 的返回值是
`st.session_state.get("api_df", None)`：只要之前点过「使用」，重新导入后再选「API 获取」，第 1 步渲染结束
就带着旧 `api_df` 返回，`app.py` 直接跳到第 2 步，且不再发起任何请求。侧边栏「重置当前模块数据」的
`_RESET_KEYS_BY_TAB["导入"]`（`app.py:103-117`）同样不含 `api_df`。

**a) 根因**

向导是叠加在旧的三子标签路径之上的（`import_step == 999` 就是旧路径，`app.py:841`），两条路径共享同一批
session 键。步骤状态只是一个裸整数，没有「本步输入」的独立草稿；render 函数用「返回了 DataFrame」表达
「用户完成了」，其语义实际是「这次渲染产出了数据」。这是代码结构与交互语义错位，单点修补不足。

**b) 不修的长期代价**

数据静默重复会污染质控评分、所有图表与报告，而且用户没有明显线索；「返回上一步」在手动路径上不可用；
「重新导入」之后旧数据复活，用户会以为删除失败。任何一条都足以让一次演示失败。

**c) 最小修复切口（1 个文件即可）**

交互决策：手动录入改为「添加记录只写 session，显式点『完成录入』才返回 DataFrame」，把 concat 收敛到
完成动作；「重新导入」与 `_reset_current_tab` 补清 `manual_data`、`api_df`、`api_source` 等键。`app.py`
一处流程改动，`data_loader.py` 只改返回值语义。

**d) 保留现状的理由（对抗性审查）**

彻底重写向导（每步草稿 + 可达性）收益低于成本；用户手动逐条录入的量本来就小，手册也建议批量文件导入。
所以「完成录入」按钮与清理表补齐是性价比最高的折中，不需要状态机重构。

---

### S1-5 导航栈语义失真：只进不出，唯一的返回按钮会落到错误 Tab；页面状态是叠加的

**证据 A：栈只有 push**

`app.py:145-156`
```python
def _navigate_to(tab_idx):
    cur = st.session_state.get("active_tab", 0)
    if cur != tab_idx:
        stack = st.session_state.get("_nav_stack", [])
        stack.append(cur)
        if len(stack) > 10:
            stack = stack[-10:]
        st.session_state["_nav_stack"] = stack
    st.session_state["active_tab"] = tab_idx
    st.rerun()
```

唯一的 pop 在 `modules/visualizer.py:782-789`（可视化空数据的「← 返回导入」）。`utils.go_back` 与
`render_back_button`（`utils.py:140-156`）在应用里没有调用者；`app.py:40` 把 `go_back` 导入成 `_go_back`
后从未使用。手动点 radio 切换（`app.py:692-695`）不入栈也不清栈，所以栈里只有历史「程序化跳转」。

**证据 B：返回落点实例**

导入第 2 步点「确认数据」→ 栈 `[0]` → 可视化；摘要卡点「🖼 读图」→ 栈 `[0, 1]` → 读图；手动切到「数据
导入」Tab，点侧边栏「重置当前模块数据」清掉数据；再手动切到「可视化」（此时为空）点「← 返回导入」→
`stack.pop()` 得到 `1`，落回可视化自己身上，再点一次才回到导入。按钮写着「返回导入」，第一次却原地不动。

**证据 C：页面状态是叠加的**

`app.py:661-665` 只决定「主区上半部分」显示封面还是摘要卡：
```python
if not has_any_data or st.session_state.get("_wall_cover", False):
    _render_onboarding_page()
else:
    _render_next_step_hint()
    _render_data_summary_card()
```
导航与 Tab 内容在 `app.py:667` 之后无条件渲染。有数据时点侧边栏「☁️ 天气墙封面」，页面变成
「天气墙 + 当前 Tab 内容」上下叠放，封面里的「返回数据视图」在墙的上方，Tab 内容仍在下方。

**a) 根因**

导航栈是为「摘要卡跳转」这类程序化导航设计的，返回入口只接了一个空态；设计没有完成。Streamlit 没有路由，
手切 Tab 不经过 `_navigate_to`，栈因此不能代表用户的「上一页」。页面状态用几个独立布尔量拼成
（`active_tab`、`_nav_stack`、`import_step`、`_wall_cover`、`_manual_open`、`_filter_date_range`），没有单一
状态机，叠加态是必然结果。

**b) 不修的长期代价**

手册第 138 行写「跳转走统一的导航栈，供『← 返回』类按钮回退」，用户按文档理解去找返回，找不到；找到的
那一个会把用户带去错误页面。叠加的封面状态让人分不清「我现在在首页还是在工作区」。

**c) 最小修复切口（1 个文件）**

二选一：手动切换 Tab 时清空 `_nav_stack`（让「返回」只回退程序跳转，语义变诚实）；或在导航条左侧常驻一个
「← 返回」按钮，栈空时置灰。前者改动 3 行且不新增 UI 噪音，建议先做前者。

**d) 保留现状的理由（对抗性审查）**

6 个 Tab 之间本来没有深层级，「返回」的真实需求很小；常驻返回按钮会占用导航条，也会诱导用户把线性流程
当成可随意回退的。清栈方案保留了程序跳转的可回退性，成本最低。

---

### S1-6 摘要卡的时间筛选只作用于可视化，导出、报告与预警仍是全量

**证据**

`app.py:886` 是唯一使用筛选后数据的地方：
```python
if st.session_state["active_tab"] == 1:
    _viz_df = _safe_render("可视化-数据", _get_filtered_df)
    _safe_render("可视化", render_visualization_tab, _viz_df)
```

`app.py:913-921` 的导出传入的是未筛选的 `st.session_state["df"]`；测预警也是（`app.py:904` 用
`st.session_state["df"]`）。而手册写的是：

> 数据摘要卡……提供数据时间范围筛选器（**按日期区间过滤全站使用的数据**）。来源：`docs/用户使用手册.md:134`

> [下载] 处理后数据 (CSV)……当前会话数据（**含筛选后的结果**）。来源：`docs/用户使用手册.md:537`

**a) 根因**

筛选器是后来加在摘要卡上的「全站」愿望，`_get_filtered_df()` 只接到了可视化；其他 Tab 直接读原始 `df`。
文案先于实现写进手册。

**b) 不修的长期代价**

用户筛出「7 月 1–7 日」再导出，拿到的是整月数据；报告里的统计与图表和用户刚看到的视图不一致。这类偏差
不会报错，只会被当成平台算错。用户对「筛选」的信任一旦崩掉，之后每个数字都要人工复核。

**c) 最小修复切口（1 个文件）**

把导出与预警检测改为传 `_get_filtered_df()`（两处 3 行），摘要卡底部加一行「当前筛选将作用于图表、预警与
导出」；如果产品希望导出全量，则改按钮与手册文案，明确「筛选仅作用于图表」。二选一即可，不要保留现状。

**d) 保留现状的理由（对抗性审查）**

改实现会剥夺「导出全量」这个隐含能力（可加「使用全量导出」开关）；改文案则让筛选显得只服务一个 Tab，
产品价值下降。这属于产品决策层面，超出纯 bug 修复范围，需要先定语义再动手。

---

## S2（局部但会扩散）

### S2-1 登录后首屏是空天气墙，而手册、模块文档与测试三方都声称「预置 34 城」

**证据**

`modules/weather_wall.py:671-677`
```python
if "wall_cities" not in st.session_state:
    st.session_state["wall_cities"] = load_cities()
cities: list[dict] = st.session_state["wall_cities"]
...
if not cities:
    st.markdown(_placeholder_html(), unsafe_allow_html=True)
    return
```
`load_cities()` 没存过就是空列表；模块文档字符串写「默认预置全国 34 个省级行政区」（`weather_wall.py:3`），
`capital_cities()`（`weather_wall.py:95-97`）只被测试调用（`tests/test_weather_wall.py:20-23`，注释还写着
「需求 1：默认预置」），产品从不使用。占位卡文案是「天气墙还空着」。手册第 140 行写「默认预置全国 34 个
省级行政区……首页最多同时展示 6 张城市卡片」。

**a) 根因**：空态是用户拍板过的降级方案（代码注释 `weather_wall.py:674`「用户已拍板定位失败的降级方案」），
但手册、README 与测试没有随决策更新；测试锁住了函数而没锁接线，制造了「已覆盖」的错觉。

**b) 代价**：新用户登录后的第一屏是空白装饰区块加两个搜索控件，与「天气墙」这个名字的预期相反；手册
描述的 6 张卡片会让人以为加载失败。

**c) 最小切口**：`weather_wall.py` 一个文件，在占位卡里加一个「一键添加示例城市（6 个）」按钮，复用
`capital_cities()[:MAX_CITIES]`；保留空态默认，不预置。文档同步为「默认空，可一键添加示例」。

**d) 保留现状的理由**：不预置可以避免替用户决定城市，也少一次首屏网络请求；但空态至少应给一个可点的
起步动作，否则「空」就只是空。

### S2-2 六个 Tab 按模块交付物切分，主流程横跨四站；提示条只推一条线性路径，且前提是错的

**证据**

`app.py:671-678`
```python
tab_labels = [
    "[导入] 数据导入",
    "[图表] 可视化分析",
    "[预报] 数值预报",
    "[读图] AI 读图解析",
    "[导出] 报告导出",
    "[雷达] 报文解码",
]
```
6 个 Tab 与 `modules/` 下 6 个渲染模块一一对应，是交付物清单。数据流上，报文解码的唯一产物要回 Tab 0
使用（`codec.py:347` 原文「请切换到数据导入 Tab 查看」），却被放在最后一站。提示条（`app.py:313-330`）只在
「已有预报」时才提示读图，而读图根本不依赖预报（`chart_reader.py:443`「本页不需要先导入数据」）；无预报时
它也不会提示数值预报。

**a) 根因**：每个新能力获得一个新 Tab（读图替换了旧的检测 Tab，报文解码追加在末尾），Tab 是历史叠加的结果；
提示条沿用旧 onboarding 的线性叙事。

**b) 代价**：用户要记住 6 个入口和它们之间的隐含顺序；两个独立能力（预报、读图）被写成主线附属；报文解码
的产物离使用地最远。

**c) 最小切口**：先改提示条（`app.py:313-330` 一个函数），按「有没有数据、有没有预报」给出并列的下一步，
不再把读图挂在预报之后；Tab 重排（报文解码并入导入作为第 4 种方式）留到结构批次。

**d) 保留现状的理由**：6 个 Tab 是 README、手册、测试与用户肌肉记忆的既有契约，重排的回归成本远高于收益；
先修提示条是唯一低风险的部分。

### S2-3 导航条位于页面中段，封面/摘要卡/导航三层叠放；无进度指示；首屏有两个「开始导入」

**证据**：`app.py:657-665` 先渲染封面或摘要卡，`app.py:667-695` 才渲染导航；封面里的「⚡ 快速开始 — 导入
数据」（`app.py:376-384`）与下方 Tab 0 向导的 3 个按钮（`app.py:714-732`）功能重叠，且无数据时那次点击是
空操作（见 S1-3 证据 C）。`_render_progress_bar`（`app.py:265-310`）实现了「导入 → 质控 → 图表 → 读图 →
导出」的进度条，但全仓没有任何调用者；`ONBOARDING_STEPS`（`config.py:638`）同样没有消费者。

**a) 根因**：封面与摘要卡后插到主区顶部，导航保持在原位置；旧的线性 onboarding 被天气墙替换后，进度条函数
与配置留在原地。

**b) 代价**：首屏两个入口分散注意力；滚动后切 Tab 要回到顶部；用户不知道自己在流程的哪一步（导入完成后
没有任何「第 2/3 步」提示）。

**c) 最小切口**：`app.py` 把导航 radio 提到主标题之下、封面/摘要卡之上；删掉封面里的 quick start（或改成
「在下方选择导入方式」）。进度指示可先不做，导航上移就能显著降低定位成本。

**d) 保留现状的理由**：封面下移可能是为了让天气墙抢首屏；但当前封面并不独占（Tab 内容仍在下方渲染），
这个理由不成立。上移导航只改 20 行，风险集中在首屏观感。

### S2-4 跨 Tab 上下文丢失：条件渲染会清空未提交的输入与读图图片

**证据**：Tab 内容用 `if active_tab == N` 条件渲染（`app.py:884-929`），未激活的 Tab 不实例化 widget：

```python
# app.py:884-887
if st.session_state["active_tab"] == 1:
    _viz_df = _safe_render("可视化-数据", _get_filtered_df)
    _safe_render("可视化", render_visualization_tab, _viz_df)
```
```python
# modules/chart_reader.py:467-468
st.session_state["chart_reader_images"] = images
```
AppTest 探针实测：带 `key` 的 `st.text_area` 在切到另一个 Tab 再切回来后值为空。`chart_reader` 每次渲染都
覆盖图片缓存，切走再回来 `uploads` 为空，于是把缓存写成空列表。手册第 440 行只承认了上传区会被清空
（「换标签、点别的控件都会触发重跑并清空它」），没有覆盖文本框、备注、API 日期这些输入。

**a) 根因**：Streamlit 的 widget 生命周期与「Tab 常驻」的期望冲突；项目知道这个约束，但只对「导出用图片」
做了单独缓存（`chart_reader_report_images`），没有做通用的输入持久化。

**b) 代价**：填了半页的报文、补充说明、日期范围，切一次 Tab 就没了；读图报告文字还在但图片列表清空，
重新生成要重传。

**c) 最小切口**：把每个 Tab 的关键输入落到显式 session 键（报文文本、读图备注、API 日期），渲染时用
session 值作为 `value`；1–2 个文件。不要改成 `st.tabs` 全量渲染，那会拖慢首屏。

**d) 保留现状的理由**：全量持久化会增加 `_RESET_KEYS_BY_TAB` 的维护负担，且 Streamlit 没有「保留未渲染
widget」的开关；只持久化 3 个高价值输入是折中。

### S2-5 空态与阻断路径不统一：导出 Tab 无空态，还能生成一份写着「没有数据」的报告

**证据**：可视化空态有提示与返回（`visualizer.py:782-789`）；数值预报空态有一句 info（`nwp_forecast.py:1845-1847`）；
导出 Tab 无数据时仍渲染标题、空列与可点的「生成报告」：

```python
# modules/reporter.py:1128-1155（节选）
st.write("#### [统计] 数据导出")
c1, c2, c3 = st.columns(3)
with c1:
    if df is not None and not df.empty:
        ...          # 只有有数据时才出现下载按钮
with c2:
    fc_df = st.session_state.get("fc_df", None)
    if fc_df is not None and not fc_df.empty:
        ...
with c3:
    pass
```
生成结果里只有一行 `⚠ 当前没有数据可生成报告`（`reporter.py:443-444`）。手册第 150 行写「导出至少需要
数据或预报之一」，界面上没有任何提示。

**a) 根因**：各模块自己写空态，没有共享的空态组件或契约；报告生成逻辑被写成「没有数据也能生成」。

**b) 代价**：用户会下载到一份只有免责声明的 Word，然后怀疑平台；也可能以为是筛选把数据筛没了。

**c) 最小切口**：`reporter.py` 顶部加与可视化一致的 info 与「前往导入」按钮（`_navigate_to(0)`），3 行。

**d) 保留现状的理由**：允许生成空报告在模板调试时有用；加提示而不阻断即可。

### S2-6 错误恢复会清空数据，提示语却说「不影响其他功能」；登录页在错误边界之外

**证据**

`app.py:87-96`（节选）
```python
def _safe_reset():
    keep = {"active_tab", "import_step", "import_method", "_nav_stack", "auth_user"}
    keep |= {k for k in st.session_state if k.startswith(("auth_", "invite_", "admin_"))}
    for _k in list(st.session_state.keys()):
        if _k not in keep:
            del st.session_state[_k]
```
`app.py:69-75` 的隔离提示写「已隔离处理，不影响其他功能」，按钮是「🔄 重置会话并回到首页」。

`auth.py:531` 是全仓唯一未做兜底的 `st.secrets` 读取：
```python
admin_pw = str(st.secrets.get("ADMIN_PASSWORD", "")).strip()
```
用 AppTest 在不注入 secrets 的情况下跑 `app.py`，实测在登录页抛出
`StreamlitSecretNotFoundError`，异常文本包含本机绝对路径；而 README 第 285 行写「未配置密钥时页面会提示
如何设置，不会崩溃」。`tests/test_smoke.py:13-24` 在启动前注入四条假密钥，这条路径因此从未被覆盖。

**a) 根因**：错误边界只包住了 Tab 渲染（`_safe_render`），首屏与登录页在边界之外；重置选择「清空一切回
导入」最省事。P0-4 修复只覆盖了 `auth._secrets_get`，漏掉了管理面板这一处。

**b) 代价**：任一 Tab 因数据形状抛异常，用户点重置会丢掉未保存的导入数据，而提示说「不影响其他功能」；
没有 secrets 的部署首屏直接显示堆栈，与文档承诺相反。

**c) 最小切口**：`auth.py:531` 改用 `_secrets_get`（1 行，已验证）；`app.py` 的隔离提示改为「本页已暂停，
可切换其他 Tab；重置会清空未保存数据」并加一个「只重试本页」按钮。2 个文件。

**d) 保留现状的理由**：重置是最后手段，简单有效；Streamlit 没有 per-Tab 恢复机制，保留「重置」按钮本身
合理，只需要把代价说清楚。

### S2-7 读图有两层几乎相同的配额，且用「刷新页面可重置」诱导用户登出

**证据**

`modules/chart_reader.py:492-525`（节选）
```python
count = int(st.session_state.get("chart_reader_gen_count", 0) or 0)
remaining = max(0, MAX_GENERATIONS_PER_SESSION - count)
st.caption("本会话已尝试 %d/%d 次（剩余 %d 次）……" % (...))
...
elif remaining <= 0:
    st.warning("本会话尝试次数已用完（%d 次）。刷新页面可重置，"
               "但每次调用都会真实计费，请留意用量。" % MAX_GENERATIONS_PER_SESSION)
```
手册第 444–450 行列出「每日 5 次 / 本会话 5 次」两张表，默认值相同。刷新即退出登录（S1-1），且未保存的
导入数据同时丢失。

**a) 根因**：会话级防连点先上线，服务端每日配额后加（`docs/superpowers/plans/2026-09-13-04-chart-reader.md`
的实施记录），旧文案没有回收。

**b) 代价**：用户看到两个相同的「5 次」不知道该看哪个；被引导去刷新，付出重新登录与丢数据的代价。

**c) 最小切口**：`chart_reader.py` 一个文件，删掉「刷新页面可重置」的说法，改为「会话上限用于防连点，
每日配额才是硬限制」；或直接删会话计数只留服务端配额。

**d) 保留现状的理由**：会话上限能挡住连点造成的重复计费，保留有意义；只改文案即可。

### S2-8 手册与实现漂移，而契约测试只锁「关键词在不在」

**证据**

- 手册重置表（`docs/用户使用手册.md:817-828`）写「智能分析与建议（读图解析）| 预警列表、质量评分、预警
  指纹」，实现是 `_RESET_KEYS_BY_TAB["读图解析"] = ["chart_reader_images", ...]`（`app.py:112-114`），且
  `warnings_list`、`quality_score` 根本不在任何重置表里。
- 手册第 153 行还留着旧 Tab 名「[检测] 智能分析与建议」的兼容说明，说明改名时没有全量清理。
- 手册第 162 行说数值预报写入的动作流会话键「供读图解析与报告复用」，但 `chart_reader` 不读任何 `fc_*` 键。
- 手册第 176 行描述的「[使用] 使用并合并气象+空气质量」是 S1-3 里那个无效按钮。
- 手册第 537 行说 CSV「含筛选后的结果」，见 S1-6。

`tests/test_manual.py:182-237` 的契约只检查章节标题、关键词出现与禁用词；`test_smoke.py` 只跑到登录页。
测试锁不住「文档描述的行为是否存在」。

**a) 根因**：手册由实现者写，测试用字符串存在性代替行为一致性；改名、改按钮时缺少反向检查文档的步骤。

**b) 代价**：手册是当前唯一的 onboarding 与排障入口，一条失实描述会直接变成一次支持请求；手册越详细，
失实的杀伤力越大。

**c) 最小切口**：在 `test_manual.py` 增加三条低成本源码契约：手册重置表与 `app.py` 的
`_RESET_KEYS_BY_TAB` 键集合一致；手册里出现的每个按钮标签都能在源码中找到；手册里的 Tab 名等于
`app.py` 的 `tab_labels`。1 个测试文件 + 修手册 4 处。

**d) 保留现状的理由**：逐条行为测试需要 AppTest 过登录门禁（缺真实 Supabase 会话），成本高；源码字符串
契约是当前性价比最高的替代，能拦住大部分改名漂移。

### S2-9 高级功能可发现性：ERA5 三层深，管理员面板只在登录页

**证据**：ERA5 入口链路是 Tab 0 → 向导第 0 步选「API 获取」→ 第 1 步 → API 区的第三个子 Tab：

```python
# modules/data_loader.py:666-668
api_tab1, api_tab2, api_tab3 = st.tabs([
    "Open-Meteo (气象)", "Open-Meteo (空气质量)", "ERA5 (CDS 引导)"
])
```
脚本包、变量 catalogue、规模预警这些差异化能力，需要用户先猜到这里有第三个子 Tab。管理员面板只在登录页
（`auth.py:334`、`auth.py:529-533`），管理员登录后反而不可达，必须登出或无痕窗口才能生成邀请码。读图配额
的调整路径只写在手册第 3.3 节。

**a) 根因**：功能放在实现所在位置，没有「工具 / 设置」这一层；管理员面板与用户登录页共屏。

**b) 代价**：ERA5 是区别于普通绘图工具的差异化能力，却藏在最深处；管理员每次管理账号都要登出。

**c) 最小切口**：导入第 0 步加第 4 个按钮「ERA5 脚本包」直达；侧边栏加密码保护的「管理」入口，复用
`_render_admin_panel`。2 个文件。

**d) 保留现状的理由**：管理入口出现在所有用户的侧边栏会增加攻击面与困惑；所以只推荐 ERA5 直达，管理入口
维持现状并在 README 里写明「需在登录页操作」。

### S2-10 移动端与窄屏：全局列堆叠、图表被压到 280px、6 个导航变 6 行

**证据**：`modules/theme_css.py:561-573`（节选）
```css
@media screen and (max-width: 768px) {
    [data-testid="column"] { flex: 1 1 100% !important; min-width: 100% !important; }
    [data-testid="stRadio"] [role="radiogroup"] { flex-direction: column !important; }
    .js-plotly-plot, .plot-container { max-height: 280px !important; }
}
```
全局 `column` 规则把天气墙三列、日志三列、表单两列全部压成单列；导航胶囊变成 6 行竖向列表；所有图表被
限高 280px，等高线、图例与色标在手机上基本不可读。

**a) 根因**：用 CSS 覆盖 Streamlit 内部 `data-testid` 实现响应式，没有可选的作用域容器；Streamlit 自身的
布局能力有限。

**b) 代价**：手机端首屏被导航吃掉一半；图表在高信息密度场景（天气图、相关矩阵）失效。对「随时看天气」
这种移动优先场景是硬伤。

**c) 最小切口**：`theme_css.py` 把 `column` 堆叠规则收窄到特定容器（如只对 `st.columns` 的表单区），图表
高度改为 `min-height` 并允许横向滚动；1 个文件。

**d) 保留现状的理由**：Streamlit 的响应式靠内部选择器维持，改窄作用域需要逐页回归；如果目标用户以桌面
为主，这笔账不划算。

### S2-11 可访问性：导航看不到焦点、图表没有替代文本、登录卡片没有 form 语义

**证据**

- `modules/theme_css.py:484` 隐藏了 radio 的原生圆点：`[data-testid="stRadio"] [role="radiogroup"] > label > div:first-child { display: none !important; }`；
  全文件只有 `[data-testid^="stBaseButton"]:focus-visible` 一条焦点样式（`theme_css.py:161-163`），导航胶囊
  没有 `:focus-visible` 规则。键盘用户无法看到当前焦点在哪个 Tab 上。
- 图表统一走 `config.safe_chart`（`config.py:707-742`），没有 alt/长描述/数据表替代；部分图表用 caption
  写了读图指南（风玫瑰），相关矩阵等没有。
- 仓库自己的浏览器实测记录：「登录卡片没有 `<form>`」（`research/README.md:44-46`），密码管理器与
  Enter 提交行为因此不可靠。
- 页面语言未声明（Streamlit 默认 `<html lang="en">`），中文读屏发音与断句受影响；Tab 标签形如
  「[导入] 数据导入」，读屏会念出方括号。

**a) 根因**：视觉优先的 CSS 覆盖隐藏了原生控件，却没有补键盘焦点；Plotly 没有内置可访问文本；`st.form`
渲染成 div，框架层无法补 `<form>` 语义。

**b) 代价**：键盘与读屏用户无法完成主路径；密码管理器不识别登录表单，用户每次手输；这也是课程评审里
最容易被指出的一类问题。

**c) 最小切口**：`theme_css.py` 给导航胶囊加 `label:has(input:focus-visible)` 轮廓；`config.safe_chart`
增加一个可选的 `st.expander("查看数据表")` 与 `fig.update_layout(meta=...)`；登录页加「按回车提交」提示。
2–3 个文件。

**d) 保留现状的理由**：Streamlit 生成的 DOM 无法完全满足 WCAG（没有 `<form>`、图表在 iframe 里），只能
缓解；全部补齐的收益与回归成本不成比例。先做焦点与数据表两项。

### S2-12 侧边栏：7 组阈值、手册、主题、重置挤在一起，显示偏好被埋在中段

**证据**：`app.py:487-655` 的侧边栏顺序是用户面板 → 手册 → 7 组阈值 → 调试 → 天气墙封面 → 暗色模式 →
天气墙显示 → 重置 → 页脚。主题切换位于第 6 个区块，前后都是与它无关的业务设置：

```python
# app.py:613-618
dark = st.checkbox("[显示] 暗色模式", value=st.session_state.get("dark_mode", False), key="dark_toggle",
                   help="切换「梦幻夜空 / 清透天空」主题，选择自动保存，重启后保持")
if dark != st.session_state.get("dark_mode", False):
    # 需求 3：切换写入持久化（本地文件 + 登录时 Supabase user_metadata）
    theme_aether.set_theme(dark)
    st.rerun()
```
既往清单第 7 项已登记「两个天气墙控件不相邻」，本报告不重复，只补一条：主题与天气墙都是「显示偏好」，
却与 7 组业务阈值混在同一垂直流里，第一次使用很难找到。

**a) 根因**：侧边栏承担了用户面板、业务设置、显示设置、资料与页脚五类职责，没有分组标签。
**b) 代价**：显示类偏好的发现成本高；阈值区占据大量垂直空间，把重置与页脚推得很远。
**c) 最小切口**：`app.py` 侧边栏加两个 `st.expander` 分组「业务设置 / 显示与工具」，不改变功能。
**d) 保留现状的理由**：侧边栏折叠会增加一次点击；且既往审计已明确不调整顺序（清单第 7 项），分组的收益
需要再评估。

---

## S3（表面：文案、间距、图标）

- **S3-1 图标体系混用**：Tab 标签是「[导入] 数据导入」这类方括号词，按钮却用「📊 图表」「🖼 读图」
  （`app.py:237-244`），导入区还有「[OK]」「[搜索]」「[合并]」「[雷达]」（`app.py:599`、`codec.py:289`、
  `weather_wall.py` 用 emoji）。页头与每个 Tab 副标题重复了 Tab 名（`app.py:453-455` 与 `visualizer.py:780`）。
  读屏听到的是「左方括号导入右方括号数据导入」，视觉上多一层噪音。
  根因是一次把 emoji 批量替换成方括号词的迁移没有做完整；最小切口是统一成「emoji + 名称」并去掉副标题
  重复，1 个文件；保留现状的理由是这纯属观感，与功能稳定无关。
- **S3-2 登录页错误文案面向部署者**：`auth.py:363-366` 对终端用户说「请查收邮件，或到 Supabase 控制台
  关闭 Confirm email」；`auth.py:329-331` 说邀请码「由管理员在下方管理员入口生成并分发」。用户既没有
  Supabase 控制台，也不该被告知去试管理员密码。改成「联系部署者」即可，1 个文件；保留现状的理由是这些
  错误几乎只在自部署环境出现。
- **S3-3 成功提示被 rerun 吞掉**：`app.py:251-256` 保存成功后立刻 `st.rerun()`，`st.success("已保存到
  云端 ✓")` 不会留在屏幕上；报告生成同理（`reporter.py:1186-1189`）。用户不确定是否保存成功，可能重复
  点击（云端会多一条同名数据集）。最小切口是改为按钮状态/侧边栏计数变化，或把成功提示放进 `st.toast`
  （toast 能跨 rerun 存活，见 `_safe_toast` 的用法）。1 个文件；保留现状的理由是云端列表与用量条本身
  也会变化，可作为间接反馈，但不够明确。
- **S3-4 死代码与死配置**：`_render_progress_bar`（`app.py:265-310`）无调用者；`ONBOARDING_STEPS`
  （`config.py:638`）无消费者；`app.py:40` 导入的 `_go_back` 未使用；`render_manual_input_section(existing_df=None)`
  的参数没有调用方传。它们的 IA 含义是「曾经设计过的线性流程被遗弃」，清理本身归 A 号审计，此处只记语义。

---

## 覆盖对照（任务书 10 项）

| # | 要求 | 对应发现 |
|---|---|---|
| 1 | 登录墙：首屏拦截、游客可见、代价与合理性 | S1-1、S2-9（管理员入口） |
| 2 | 6 Tab 的组织依据、顺序依赖与引导 | S2-2、S2-3、S1-2（检测无归属） |
| 3 | 导航栈与页面状态机、刷新/深链/后退 | S1-5、S1-1（刷新）、S2-3（叠加态） |
| 4 | 导入向导多步状态、中断恢复、跨 Tab 丢失 | S1-4、S2-4 |
| 5 | 功能可发现性：ERA5、读图配额、管理员、邀请码 | S2-9、S2-7、S3-2 |
| 6 | 阻断路径与空态、错误恢复 `_safe_reset` | S2-5、S2-6、S1-4 |
| 7 | 主题与视觉：作用域、图表重绘、对比度 | 见下「主题专项」 |
| 8 | 手册与应用一致性、测试契约 | S2-8、S2-1、S1-3 |
| 9 | 移动端/窄屏与 Streamlit 约束 | S2-10、S2-4（widget 生命周期） |
| 10 | 可访问性：键盘、焦点、颜色、替代文本 | S2-11、S3-1 |

### 主题专项（第 7 项）

- **作用域**：单一开关控制全局（`app.py:613-618`），主题属性写在 `<html>`/`<body>`（`theme_aether.py:170-209`），
  样式在登录门禁之前注入（`app.py:432`），所以登录页也跟随偏好。管理员/普通用户同进程无冲突。
- **图表重绘**：所有图表走 `config.safe_chart`，内部 `chart_theme.apply(fig)` 按当前 `dark_mode` 取模板并
  显式 `theme=None`（`config.py:722-731`）；切换开关触发整页 rerun 后重绘，数据在 session 里，GFS/AQI 有
  1 小时会话缓存（`nwp_forecast.py:354-362`），不存在「切主题重拉数据」。
- **对比度**：运行仓库自带探针 `research/darkmode_contrast_probe.py --check`，亮/暗两套 token 的正文、语义
  色、图表色在页面/卡片/侧边栏底上全部满足 4.5:1，**合计不合规 0 项**。这一项已达标，对抗性结论成立，
  不应在重构中改动配色。
- **可读性**：移动端图表限高 280px 是实际的读图障碍（S2-10），与对比度无关。

---

## 允许的有限可见变更清单（值得做且风险可控）

按「文件数 × 回归面」排序列出。所有改动都不新增依赖、不改数据模型。

| ID | 变更 | 文件 | 风险 | 预期收益 | 验证方式 |
|---|---|---|---|---|---|
| V1 | 天气墙空态加「一键添加 6 个示例城市」 | `weather_wall.py` | 低 | 登录后首屏从空变有内容；与手册/测试对齐 | 手动点一次 + 现有 `test_weather_wall` 不变 |
| V2 | 保存到云端改用 `st.toast` 成功反馈，按钮短暂进入「已保存」 | `app.py` | 低 | 消除「点了没反应/重复保存」 | 手动 + 无测试回归 |
| V3 | 导航 radio 上移到主标题之下；手动切换 Tab 时清空 `_nav_stack` | `app.py` | 低 | 导航可见、返回语义变诚实 | 手动走查 F4/F7/F15 |
| V4 | 事件检测改为「数据就绪即计算」，摘要卡显示「检出 N 个预警事件」 | `app.py` | 中 | 报告不再依赖是否访问读图 Tab；核心能力出现在界面 | 用 `示例数据/` 对比「导入→导出」与「导入→读图→导出」两份报告章节一致 |
| V5 | 报文解码结果落 session，并把「加入手动录入」移出点击分支；API「使用」按钮移出外层分支 | `codec.py`、`data_loader.py` | 中 | 修复文档承诺的功能；跨 Tab 不再丢结果 | AppTest 条件渲染用例 + 手动 |
| V6 | 导入向导：手动录入加显式「完成录入」；「重新导入」与重置表补清 `manual_data`/`api_df` | `app.py`（可选 `data_loader.py`） | 中 | 消除重复合并与陈旧数据 | 手动：录入 2 条 → 返回上一步 → 行数不变；重导后 API 不直接跳第 2 步 |
| V7 | 导出与预警改用筛选后的数据（或改文案，二选一） | `app.py` | 中 | 视图、报告、CSV 口径一致 | 用日期筛选后导出对比行数 |
| V8 | 登录页补产品说明 + 邀请码获取方式；`auth.py:531` 改 `_secrets_get` | `auth.py`（+ 可选 `app.py`） | 低 | 缓解首屏死路；消除无 secrets 崩溃 | AppTest 不注入 secrets 不再抛异常 |

不建议现在做：把 6 个 Tab 全部重排、引入 `st.navigation` 多页（会改登录门禁与 URL 模型，属于批次 3 的
架构选项）、给登录页加动画或营销素材（成本大于收益）。

如果只做一件事，选 V1。它是唯一在 1 个文件内、可独立回滚、能直接改变登录后首屏观感的改动，且不触碰
登录、数据流与配额任何一处结构。

---

## 建议批次

**批 0（半天，零逻辑风险）**：V8 的后半（secrets 兜底）+ 手册/README 同步 5 处失实（重置表、旧 Tab 名、
「使用」按钮、「筛选后导出」、「预置 34 城」）+ S3-2 文案。只改文案与 1 行代码。

**批 1（1–2 天，低风险可见）**：V1、V2、V3、S2-5 导出空态。每项都能独立回滚，不碰数据流。

**批 2（2–3 天，交互修复）**：V5、V6、S2-7 配额文案、S2-6 隔离提示。先补 AppTest 条件渲染用例再改，避免
回归到「按钮又藏回分支里」。

**批 3（3–5 天，结构性，需要产品决策）**：V4 事件检测归属；V7 筛选语义；S1-1 的游客只读首屏；S2-2 的
Tab 重组（报文解码并入导入）。这一批会改用户可见的主路径，必须配一次端到端走查与手册第 4/5/12 章更新。

**批 4（2 天，可访问性与移动端）**：S2-11 的焦点与数据表替代、S2-10 的图表高度与列堆叠作用域。目标是把
键盘可完成主路径与手机可读图两件事做到及格，不做全面 WCAG 改造。

每批的完成标准：批 0/1 用「静态检查 + 手动走查」即可；批 2 起要求至少一个 AppTest 用例覆盖被修的交互；
批 3 要求「导入 → 导出」最短路径与「导入 → 读图 → 导出」长路径产出同一份预警章节。

---

## 与 A/C 号审计的分工（避免重复）

- 归 A 号：模块边界与渲染函数耦合、`_nav_stack` 的导入未使用、死代码清理、`api_df/manual_data` 等状态键
  的命名与清理表维护、AppTest 覆盖不足的工程原因。
- 归 C 号：Supabase 会话失效处理、`st.secrets` 缺失的完整安全影响、邀请码与配额服务端边界、匿名访问的
  成本控制。
- 本报告只从「用户能否看见、能否完成、会不会得到错误结论」三点评判；同一处机制如果在 A/C 已登记，报告
  只补充 IA 侧影响，不重复根因分析。

---

## 证据索引

**静态证据**：`app.py`、`auth.py`、`utils.py`、`db.py`、`modules/{data_loader,codec,reporter,visualizer,nwp_forecast,chart_reader,weather_wall,city_prefs,manual,theme_aether,theme_css,design_tokens,chart_theme}.py`、
`docs/用户使用手册.md`、`README.md`、`research/内部不一致清单-2026-09-13.md`、`research/README.md`、
`docs/superpowers/plans/*.md`、`docs/superpowers/specs/*.md`、`tests/test_manual.py`、`tests/test_smoke.py`、
`tests/test_release_surface.py`、`tests/test_weather_wall.py`、`.streamlit/config.toml`。

**可复算工具**：`research/darkmode_contrast_probe.py --check`，运行结果「合计不合规 0 项」。

**进程内探针（AppTest，不启动服务器、不连 Supabase，源码在系统临时目录）**：

1. 嵌套按钮复现（8 行脚本），确认点击内层按钮后 `hit` 仍为 0。
2. 条件渲染清空 widget，确认切走再切回后 `st.text_area` 值为空。
3. 无 secrets 启动 `app.py`，确认登录页抛出 `StreamlitSecretNotFoundError`（异常文本含本机绝对路径）。

**未做/无法做**：真实浏览器里的注册两步提交（需要浏览器与 Supabase；本报告按 Streamlit 表单语义推断，
作为 S1-1 内的局部摩擦记录，未单列为一条 S1）；真实移动端渲染（按 CSS 规则推断）；真实登录后的端到端
点击（需要 Supabase 会话，按任务书要求不启动应用）。
