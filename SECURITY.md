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
RLS 策略定义于 `supabase/schema.sql`，需在 Supabase 控制台 SQL Editor 执行该文件（可重复执行）：
- `datasets`：策略 `datasets_owner_only`，`using (auth.uid() = user_id)`，用户仅访问自己的数据。写入一律经 `save_dataset`（SECURITY DEFINER）在服务端强制存储配额，客户端无直插/直改权限。
- `profiles`：仅本人可 select；update 权限已从 authenticated 撤销，配额列只能由 service_role（管理员面板）修改。
- `vision_usage`：仅本人可 select 自己那行；insert/update/delete 对客户端全部撤销，计数只能经下面三个函数改动。
- `get_vision_quota` / `begin_vision_call` / `record_vision_usage`：SECURITY DEFINER 且默认 PUBLIC 执行权已收回，仅授予 authenticated 与 service_role。三个函数**一律以 `auth.uid()` 判定身份、不接受调用方传入 user_id**（否则可伪造或清空他人计数），`record_vision_usage` 的 token 增量钳到非负（否则可传负数反向冲销用量绕过每日上限）。
- `invite_codes`：启用 RLS 且不开任何 anon / authenticated policy，仅经 SECURITY DEFINER 函数访问。
- `gfs_cache`：读仅限 authenticated（避免匿名访客读到他人查询过的经纬度），写与改限自己创建的行，单行数据上限 100KB。

公开库与公开 anon key 架构下，RLS 是唯一的信任边界。请确认线上库已执行上述 schema.sql；**升级到 2.3.7 及以后必须重跑一次**以建出读图配额相关对象。

## 已落实的安全核查（2026-07-26）
- git 历史扫描：从未提交真实 `.streamlit/secrets.toml`，无密钥泄露。
- 仓库内 `docs/Supabase基本操作说明.docx` 仅含占位符说明（`https://xxxx.supabase.co`），无真实 URL / key。
- RLS 策略经代码审阅确认正确。

## 公开库部署须知
- 源码与 anon key 对所有人可见，安全性由 RLS 承担。
- `service_role` key 仅存在于服务端（Streamlit Cloud Secrets），绝不进入前端或代码。
- 建议定期在 Supabase 后台轮换 anon / service_role key。
- Streamlit Cloud 位于美区，国内访问存在延迟；免费层有休眠、内存与并发限制。
- 任何人可 fork 本库直接部署，建议搭配 LICENSE（MIT）明确归属。
