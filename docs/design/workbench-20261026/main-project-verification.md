# Supabase 主项目受控验收记录

日期：2026-10-28。目标项目 `weather_app`（`eexfkvupwvcwwyqoigql`）。用户先取消独立测试项目，随后明确改用主项目，并允许创建隔离测试账号和少量测试数据，验收后清理。

## 已完成的主项目检查

- 连接器与官方控制台均确认该项目为 Production、Healthy。
- 实际读取主库目录，9 张 public 业务表全部开启 RLS。
- `datasets_owner_only` 同时用 `auth.uid() = user_id` 限制读取/修改目标及写入后的归属。
- `claim_invite_code` 和 `is_invite_code_valid` 均未向 anon 或 authenticated 授予 EXECUTE。
- 在主库只读事务内切换至 authenticated 角色、不给用户身份，`save_dataset` 返回 `ok:false / 未登录`，`begin_outbound_call` 返回 `allowed:false / 未登录`。
- 在主库只读事务内切换至 anon 角色，读取 datasets 返回 PostgreSQL `42501 permission denied`，符合拒绝匿名读取的预期。工具错误中的 GRANT 建议没有执行。
- 已读实现中，存储与出站计数函数均先锁定测试主体对应的 profiles 行再操作；这是代码/目录检查，不等于真实并发通过。

这些结果证明实际主库的所述配置和拒绝路径，不证明成功登录、真实用户之间的隔离或并发请求结果。

## 受控验收范围及实际尝试

私有脚本位于 `.git/codex-archives/20261028_landmark_assets/main_project_smoke.py`，仅接受显式目标确认 `--allow-production eexfkvupwvcwwyqoigql`。

- 最多创建 2 个带唯一 run 标记的临时账号，使用合成 CSV；每个测试账号存储额度限定 128 KiB。
- 并发最多 2 路，每个用例 4 次请求；不调用付费 AI 或外部天气服务。
- 计划验证密码登录、保存/加载/更新、跨用户读取/修改/伪造归属拒绝、存储与出站配额及邀请码权限。
- 所有写操作只能针对本次创建的账号；清理前再次验证账号标记，注销会话、恢复原配额值、删除本次测试数据与账号并核对残留。
- 不迁移 schema、不更改 RLS、不调整现有真实用户额度。

实际运行 `codex-wb-20261028-180709-e9380959` 在第一个 Auth 健康检查请求即因 TLS 错误失败，尚未进入建号阶段。**创建账号 0，写入测试数据 0，成功业务/并发用例 0**。失败记录留在同名私有 JSON；不能将其替代原有 3 项集成用例的通过结果。

## 连接证据与边界

- Python requests 直连及显式 `127.0.0.1:7897` 代理均出现 TLS 握手错误。
- 内置浏览器访问主项目 `/auth/v1/health` 收到正常的缺少 API key 响应。
- 官方 PyPI `curl_cffi 0.17.0` 的 Windows wheel 经 SHA-256 核对后，仅安装到私有 `probe-deps`；没有更改应用依赖。浏览器兼容 TLS 直连曾返回 HTTP 401，但之后正式运行及独立 Session 对照仍失败，连通性未稳定复现。
- 后续系统解析得到 `198.18.0.194`，公共 DNS 返回 `172.64.149.246` 与 `104.18.38.10`。以请求级地址绑定分别连接两个公共地址、保留原域名/SNI 与证书校验后均仍失败；没有修改系统 DNS，不能据此把故障单独归因为 DNS。
- 最后一次有上限复核为北京时间 2026-10-28 18:55，仅向健康端点发送 1 次无凭据请求，结果仍为 `SSLError`。证据在私有 `final-blocker-recheck.json`；临时主项目凭据文件确认已不存在。
- 全程保留证书校验；没有关闭 TLS 验证或修改系统代理。Windows 的系统代理开关读取为关闭，但这不足以判断代理软件的 TUN 模式或所有流量的实际路径。
- 官方 [TLS 密码套件变更公告](https://supabase.com/changelog/cbc-tls-ciphers-deprecated) 的变更日期晚于本次检查，当前错误没有被归因于该公告。
- 现有官方控制台的兼容密钥曾私密保存到被 Git 忽略的临时文件，仅用于本次本机测试；本轮结束清除该临时文件，密钥未提交仓库或写入文档。

## 顾问提示

主项目仍有 `set_updated_at` 未固定 search_path 的警告，见 [官方说明](https://supabase.com/docs/guides/database/database-linter?lint=0011_function_search_path_mutable)。另有泄漏密码保护未启用、5 张服务端用途表未定义普通用户策略以及 6 个 authenticated 可调用 SECURITY DEFINER 函数的提示。后两类需结合实际权限和身份检查判断，不能直接等同于泄漏；本次没有修改这些配置，也没有将其表述为零告警。

后续仍使用本次明确授权的主项目和隔离测试范围。连接稳定后才能运行成功路径与有限并发；无需重新请求同一授权。

## 停止重复尝试的条件

主项目连接阻碍已跨用户触发轮与两轮续作持续复现，当前没有已启动、可等待完成的后台测试。停止自动重试，等待本机到项目 API 的稳定连接或可用执行环境。项目健康、浏览器偶发可达、只读 SQL 和本地回归均不能替代未执行的成功路径与并发验收。

完整工作台目标另有原生 Edge 200% 缩放、真实后台暂停、触屏与 Word 实际版面待验收。最新原生 Edge 尝试仍被工具以“无法可靠识别当前浏览器 URL”为由中止；未将工具限制当作界面缺陷或通过证据。
