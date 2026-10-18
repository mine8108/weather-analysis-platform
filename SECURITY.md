# 安全说明（Security）

本仓库通过公开 GitHub 库部署于 Streamlit Cloud，后端使用 Supabase。本文说明安全模型与告知事项。

## 负责任披露
发现安全漏洞请联系仓库维护者（GitHub: mine8108）或私信 Issues。请勿公开细节直至修复完成。

## 密钥管理规范
- 所有敏感凭证（SUPABASE_URL、SUPABASE_ANON_KEY、SUPABASE_SERVICE_ROLE_KEY、ADMIN_PASSWORD、LLM_API_KEY、LLM_VISION_API_KEY）仅存放于 Streamlit Cloud Secrets 或本地 `.streamlit/secrets.toml`（已被 `.gitignore` 屏蔽）。
- 禁止在源码中硬编码任何密钥。
- `.streamlit/secrets.toml.example` 仅为占位模板，不含真实值。
- `LLM_VISION_*` 用于「AI 读图解析」，经 `requests` 直接发起 OpenAI 兼容调用，不进入前端 JS、不写入任何下载产物。**未配置时读图页给出配置指引且不显示生成按钮；调用失败不降级**——文本模型读不了图，编造的摘要等同幻觉。文本模型 `LLM_*` 自 2.3.1 起已无生产调用者，仅作保留配置。
- `LLM_VISION_API_KEY` 属**部署方付费**的密钥：任何被邀请用户的每次读图调用都计费在部署方账上。因此配额是安全事项而非仅成本事项，见下节。

## Supabase 行级安全（RLS）
RLS 策略定义于 `sql/schema.sql`，需在 Supabase 控制台 SQL Editor 执行该文件（可重复执行）：
- `datasets`：策略 `datasets_owner_only`，`using (auth.uid() = user_id)`，用户仅访问自己的数据。写入一律经 `save_dataset`（SECURITY DEFINER）在服务端强制存储配额，客户端无直插/直改权限。
- `profiles`：仅本人可 select；update 权限已从 authenticated 撤销，配额列只能由 service_role（管理员面板）修改。
- `vision_usage`：仅本人可 select 自己那行；insert/update/delete 对客户端全部撤销，计数只能经下面三个函数改动。
- `get_vision_quota` / `begin_vision_call` / `record_vision_usage`：SECURITY DEFINER 且默认 PUBLIC 执行权已收回，仅授予 authenticated 与 service_role。三个函数**一律以 `auth.uid()` 判定身份、不接受调用方传入 user_id**（否则可伪造或清空他人计数），`record_vision_usage` 的 token 增量钳到非负（否则可传负数反向冲销用量绕过每日上限）。
- `invite_codes`：启用 RLS 且不开任何 anon / authenticated policy，仅经 SECURITY DEFINER 函数访问。码为 128 bit 随机值，库中只存 SHA-256 摘要；默认 7 天过期，`revoked_at` 由管理员一键作废，验码/认领/核销三条路径都过滤过期与作废。
- `gfs_cache`：读只经 `get_gfs_cache(key)` RPC，按精确 key 返回一行，客户端对表没有 select 权限，因此无法枚举他人查询过的坐标；写与删除只经 `put_gfs_cache`，且该函数仅授予 `service_role`。应用服务端用 service_role 客户端写入，登录用户不能直接调用，因此无法伪造缓存。函数内仍校验 key 与经纬度自洽、数据形状与单行 100KB 上限，写入时刷新 `updated_at` 并清理 6 小时前的旧行。客户端对表的 select/insert/update/delete 权限已收回。
- `admin_audit_log`：管理员操作审计表，RLS 开启且对 anon/authenticated 无任何策略与表权限，只允许 service_role 写入；记录生成/作废邀请码、调整存储配额与读图配额。
- `security_selfcheck()`：仅 service_role 可调，返回 `schema_version`、各表 RLS 状态、public 函数对 anon/authenticated/service_role 的执行权、以及业务表的表级读写权限。管理员面板每次解锁先跑一次，自检不通过即停止管理操作。
- 关键列 CHECK：角色、配额非负、缓存经纬度/天数/模型/单行大小、读图计数非负、邀请码有效期，均由数据库约束兜底。
- 函数执行权：Supabase 的默认权限会把 anon/authenticated 直接授予新函数，只 `revoke ... FROM public` 收不干净。`schema.sql` 因此对每个函数显式收回 anon/authenticated，再按需授予。

公开库与公开 anon key 架构下，RLS 是唯一的信任边界。请确认线上库已执行上述 schema.sql；**升级到 2.3.7 及以后必须重跑一次**以建出读图配额相关对象；**2026-10-18 的缓存与自检改动同样必须重跑一次**，否则管理员面板会提示「无法执行数据库安全自检」，GFS 二级缓存会静默回退到实时请求。

## 已落实的安全核查（2026-07-26）
- git 历史扫描：从未提交真实 `.streamlit/secrets.toml`，无密钥泄露。
- 仓库内 `docs/Supabase基本操作说明.docx` 仅含占位符说明（`https://xxxx.supabase.co`），无真实 URL / key。
- RLS 策略经代码审阅确认正确。

## 2026-10-18 审计修复（代码侧）
- 邀请码验码 / 认领 / 核销 / 释放改为仅 `service_role` 可执行，注册流程由服务端代调；注册失败不再区分「邮箱已注册」。
- 新增出站请求配额（`outbound_usage` + `begin_outbound_call()`，默认每人每日 200 次），覆盖 GFS 预报、实况、空气质量、历史 API 与天气墙批量请求。
- `save_dataset` 改为先取 `profiles` 行锁、再统计配额与数量，修复并发 TOCTOU。
- 天气墙城市名 HTML 转义，城市结构统一归一化（控制字符、长度、坐标有限性/范围）；本地偏好文件按 uid 分区。
- 上传 CSV/Excel 增加行 / 列 / 单元格上限与解析缓存；读图像素上限收紧到 1600 万并剥离 EXIF/PNG 文本块。
- GFS 缓存读取收归 `service_role`，一级会话缓存加 1 小时 TTL；第三方错误文本不再回显给用户。
- 管理员失败计数按会话隔离 + 全局滑动窗口限速；调试输出需 Secrets 中 `DEBUG_MODE = true` 才生效。
- `search_path` 统一补 `pg_temp`，收回触发器函数与 `invite_codes` 表权限，`security_selfcheck` 判定改为「缺失即失败」。

注意：`st.markdown(unsafe_allow_html=True)` 在 1.59.1 走 rehype-raw，**不经过 DOMPurify**；任何数据字符串必须先 `html.escape`。DOMPurify 只对 `st.html` 生效。

**部署后必须重跑 `sql/schema.sql`**（新增表 / 函数 / 列与多项执行权变更），否则出站配额与邀请码注册会失败。完整变更与验证见 `research/audit-2026-10-18/修复记录.md`。

## 公开库部署须知
- 源码与 anon key 对所有人可见，安全性由 RLS 承担。
- `service_role` key 仅存在于服务端（Streamlit Cloud Secrets），绝不进入前端或代码。
- 建议定期在 Supabase 后台轮换 anon / service_role key。
- Streamlit Cloud 位于美区，国内访问存在延迟；免费层有休眠、内存与并发限制。
- 任何人可 fork 本库直接部署，建议搭配 LICENSE（MIT）明确归属。
