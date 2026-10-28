# 六模块改版执行与验收记录

更新于 2026-10-28。最新状态见 [41 城发布记录](landmark-release/README.md)。实现分支原为 `codex/weather-workbench`，现已合入 main 并部署；编制基线为 `6531f89b31553f5316e2ca0c26177280030cee8a`。用户已授权更新 main 及现有线上网站；以下 2026-10-26 检查作为历史记录保留，本轮没有付费 AI 调用。

## 当前成果

| 模块 | 已实现 |
| --- | --- |
| 公共框架 | 六模块顶部导航、共享天气带、原位展开天气墙、明暗主题、窄屏布局、稳定业务状态。 |
| 天气墙 | 生成的晴、多云、雨、阴、雾、雪、雷雨、夜景素材；进页短动画、天气图形悬停及离开回静态；缺失和旧缓存标识。 |
| 数值预报 | 城市 3/7/16 天确认、待请求与成功结果分离、失败保留旧结果、有限历史与来源返回、温度和降水分层、明确累计窗口和时间口径。 |
| 数据导入 | 三步来源/检查/分析流程，质量摘要、可滚动预览，保留文件、手动、在线和 ERA5 入口。 |
| 可视化 | 保留七项子模块和原有计算，统一数据上下文、筛选、图表与主题。 |
| AI 读图 | 生成前简化，生成后核心结论/依据/不确定性分层，冻结原图、引用校验、旧文本及解析失败回退、导出兼容。 |
| 报告与解码 | Word 实际内容预览；METAR/SYNOP 字段来源、未解析词组、快照与重复添加保护；能见度限值展示一致。 |

41 城地标已在后续授权中加入运行时，独立素材、映射和新回归见发布记录。二级 AI 坐标框选未启用。真实生成内容准确性与本地展示验收分开，未擅自调用模型。

## 六模块原阶段回归（2026-10-26）

| 项目 | 结果与证据 |
| --- | --- |
| 全量 pytest | **556 passed, 3 skipped，42.55 s**；`evidence/pytest-final.xml`。3 个跳过均为真实 Supabase RPC 用例。 |
| 新增可见度语义检查及相关页面测试 | 16 passed，13.08 s。 |
| 状态注册 | 251 个键、10 条前缀规则通过。 |
| Python CSS 变量 | 454 处引用、86 个变量定义通过。 |
| Plotly 颜色 | 明暗主题各 8 trace 均为实际颜色；无错误 CSS var 引用。 |
| PostgreSQL 行为测试 | `npm.cmd test`，6 项通过，覆盖并发预算、可信结算、幂等释放、耗尽拒绝、跨日与 RLS。此项使用 PGlite，不能替代真实项目测试。 |
| 构建及依赖 | compileall、pip check、git diff --check 通过。依赖版本未在本轮更换；先前已跑的漏洞审计未在最后的显示修正后重复执行。 |
| 浏览器 | 六模块明暗主题与 7 种宽度，共 112 张最终状态截图，清单见 `evidence/final-evidence-manifest.json`；最后警告/错误日志查询为空，见 `evidence/console-final.json`。 |

新增能见度测试后，首次全量回归曾因 README 用例数仍写 555/3 而出现两项失败。README 已同步为 556/4，再次全量运行全部通过；没有掩盖失败或删除测试。

## 真实后端环境

经用户选择，在组织“应急管理大学气象社”（`nprowicbaalchxntjjvb`）创建独立项目 `weather-workbench-test`，项目引用 `qwpmssfefisdosxaiwub`，区域 Singapore / `ap-southeast-1`。项目状态经连接器确认 `ACTIVE_HEALTHY`，PostgreSQL 17.11.0.003。

仅此测试项目执行了以下变更。

1. `weather_workbench_test_initial_schema`，导入仓库现有 `sql/schema.sql`。
2. `pin_updated_at_trigger_search_path`，固定 `public.set_updated_at()` 的 search_path 为 `pg_catalog, pg_temp`，仓库 SQL 同步此一行防护。生产数据库没有执行该变更。

当前测试项目有 9 张 public 业务表，9 张均开启 RLS，schema 标记为 2026-10-23。**测试 Auth 用户数为 0**，账号创建未完成。

测试 API 地址 `https://qwpmssfefisdosxaiwub.supabase.co`。密钥仅存本机被 Git 忽略的 `.env.supabase-test.local`，未进入前端、文档、日志或提交。没有写入生产 `.streamlit/secrets.toml`。

连接器不提供 Auth 管理和服务端密钥读取，因此在用户登录官方控制台后，读取了该测试项目的既有兼容密钥，并核对 JWT 中项目引用及角色。随后用 Python Auth Admin API 尝试创建已确认的专用测试账号，请求在 TLS 握手阶段中断，未触达业务创建流程；数据库用户数确认仍为 0。

已检查的网络路径包括本机默认路径、已运行的 127.0.0.1:7897 代理、用户切换线路后的两种路径、TLS 1.2 以及公开 DNS 对照。Supabase 官网可连接，项目 API 均返回 `SSL UNEXPECTED_EOF_WHILE_READING` 或 Schannel handshake failure。用户确认代理处于全局模式。该证据不足以确定节点链路、目标服务路径或其他中间环节的具体根因。

没有关闭证书校验、没有修改系统 DNS 或代理配置、没有以 SQL 伪造 Auth 用户、没有以数据库管理连接替代真实登录结果。

3 个真实集成用例目前保持跳过。测试配置文件虽已保存，尚无有效测试账号，不将其装载为可用测试环境。后续 API 可连通后，先完成专用账号及 1 MiB 存储测试额度，再执行 `integration_tests/test_rpc_security.py`。不要把目标改为生产项目。

安全顾问中 `set_updated_at` 的可变 search_path 警告已消失。剩余 6 个“RLS 已开但无普通用户策略”提示对应只允许可信服务端访问的表；6 个“authenticated 可调用 SECURITY DEFINER”提示对应有 auth.uid 身份约束的配额与保存 RPC。这些配置经自检核对，仍保留顾问提示原意，不宣称“零告警”。参考 [无策略提示](https://supabase.com/docs/guides/database/database-linter?lint=0008_rls_enabled_no_policy)、[SECURITY DEFINER 提示](https://supabase.com/docs/guides/database/database-linter?lint=0029_authenticated_security_definer_function_executable)。

本次查阅了 [PostgreSQL 17.11 变更](https://supabase.com/changelog/postgres-15-19-17-11-breaking-changes) 和 [TLS 配置变更](https://supabase.com/changelog/cbc-tls-ciphers-deprecated)。新建空库没有旧 ltree、btree_gist 索引或遗留加密数据；当前 TLS 错误未被归因于该公告。

## 视觉与动态证据

- 根目录 `design-qa.md` 记录完整并排对照、修正前后、保真范围及视觉结论。
- `evidence/capture-final.jsonl` 记录每次实际视口、输出尺寸与浏览器缩放。
- `evidence/motion/page-entry-full.gif` 为 22 张真实全幅截图组成的 1487 × 1058 进入动画记录，约 4.12 秒；包含短动画结束后的静态阶段。
- GIF 编码会合并重复画面；该进入动画实际编码为 8 帧、4.09 秒。`motion/recording-manifest.json` 记录编码后的帧数、时长和哈希，原始 22 张截图及采样时间保留在 `motion/entry-full.json`。
- `evidence/motion/idle-hover-leave.gif` 记录约 10 秒静置及图形/文字悬停与移开。
- `evidence/motion/dialog-reduced-motion.gif` 记录弹窗及减少动态行为。
- 早期 `page-entry-after-fix.gif` 和 `page-entry-final.gif` 受内置浏览器录屏裁切影响，保留作排障材料，不作为全幅证据。
- 运行时天气素材共 13 个文件、1,296,232 字节；文档中的 GIF 与参考图不属于首屏天气素材负载。

## 仍需完成

1. 修复测试 API 的本机连接，创建测试账号，完成真实登录、云数据保存/加载、跨用户隔离和 3 条 RPC 集成测试。
2. 在实际触屏设备验证城市选择与确认。内置浏览器不支持触屏事件注入，本轮只能证明窄屏布局和键盘/鼠标操作。
3. 在真实浏览器标签切换下验证后台暂停。内置面板隐藏时 document.hidden 仍为 false，该方式未触发浏览器可见性事件。
4. 原生浏览器 200% 缩放和 Word 实际版面人工验收。用户已打开 Edge 本地预览，但计算机操作工具无法可靠识别浏览器 URL，未继续操作；原生缩放仍待用户反馈。实际浏览器下载已完成，专业/通俗 Word 正文与预览一致，两类 CSV 各 168 条；通俗版空章节跳号已修复并重新下载核验，证据见 `landmark-release/evidence/export-check.json`。本机缺少文档渲染器，未将内容一致记作分页排版通过。

41 城地标集成及线上发布已获后续明确授权并完成；当前显隐规则为仅鼠标悬停天气图像区域时出现，移开后隐藏。该项已退出待办，无需重复请求批准。

这些待办意味着 P5 尚未退出，完整目标保持未完成。

## 本地预览与回退

启动预览使用 `.venv\Scripts\python.exe -m streamlit run preview_workbench.py --server.port 8502 --server.address 127.0.0.1 --server.headless true`。该入口不会登录、调用天气服务或调用付费 AI。正式应用依然从 `app.py` 运行。

原阶段未逐项提交；后续已留存修改前工作目录 ZIP、逐文件哈希、Git bundle 与补丁，并以 `a65ce78` 发布完整工作台及 41 城悬停地标，`d5a1ed3` 修复线上字体路径。提交与 CI 证据见发布记录，不补造逐阶段提交历史。

若需查看基线，使用独立只读/临时工作区检出远程标记 `archive/pre-workbench-20261026`（`6531f89`），不要在当前工作目录直接执行破坏性 reset。回退前保存当前 diff、未跟踪的模块和运行素材。当前已部署，生产回退应使用可审查的回退提交并经原流水线部署；Streamlit 重启会丢失进程内会话。

测试数据库与生产隔离，不因 UI 回退删除测试项目，也不将测试库迁移合并到生产。是否保留或删除测试项目应在联调完成后另行决定。
