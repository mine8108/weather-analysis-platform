# 安全说明（Security）

本仓库通过公开 GitHub 库部署于 Streamlit Cloud，后端使用 Supabase。本文说明安全模型与告知事项。

## 负责任披露
发现安全漏洞请联系仓库维护者（GitHub: mine8108）或私信 Issues。请勿公开细节直至修复完成。

## 密钥管理规范
- 所有敏感凭证（SUPABASE_URL、SUPABASE_ANON_KEY、SUPABASE_SERVICE_ROLE_KEY、ADMIN_PASSWORD、LLM_API_KEY）仅存放于 Streamlit Cloud Secrets 或本地 `.streamlit/secrets.toml`（已被 `.gitignore` 屏蔽）。
- 禁止在源码中硬编码任何密钥。
- `.streamlit/secrets.toml.example` 仅为占位模板，不含真实值。
- `LLM_API_KEY` 用于 AI 预警叙事（DeepSeek，OpenAI 兼容）。该 key 仅供后端调用 LLM，调用经 `requests` 直接发起，不进入前端 JS、不写入任何下载产物。缺失时 AI 块自动降级为结构化摘要，不阻断主流程。

## Supabase 行级安全（RLS）
RLS 策略定义于 `supabase/schema.sql`，需在 Supabase 控制台 SQL Editor 执行该文件（可重复执行）：
- `datasets`：策略 `datasets_owner_only`，`using (auth.uid() = user_id)`，用户仅访问自己的数据。
- `profiles`：仅本人可 select / update。
- `invite_codes`：启用 RLS 且不开任何 anon / authenticated policy，仅经 SECURITY DEFINER 函数访问。
- `gfs_cache`：公开读写（设计意图，仅缓存非敏感预报数据，用于降低 Open-Meteo 限流）。

公开库与公开 anon key 架构下，RLS 是唯一的信任边界。请确认线上库已执行上述 schema.sql。

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
