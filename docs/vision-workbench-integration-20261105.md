# 三模型读图的本地接入记录

日期为北京时间2026-11-05。本轮按用户最终选择保留Qwen默认，增加Terra与Sol可选项；仅本地开发和测试，未部署、未修改云端Secrets或数据库结构。

## 最终入口

| 入口 | 模型 | 思考设置 | 接口 | 默认 |
| --- | --- | --- | --- | --- |
| Qwen3.8 Flash | `qwen3.8-flash` | 服务商原生默认 | 流式Chat Completions | 是 |
| GPT-6.1 Terra | `gpt-6.1-terra` | `xhigh` | Responses后台任务 | 否 |
| GPT-6.1 Sol（专业增强） | `gpt-6.1-sol` | `high` | Responses后台任务 | 否 |

三种模型生成上限均为32768 token，同时受服务端本次预留预算约束。六段正文合计800至2000个去空白Unicode字符，包含标点、数字与字母；标题和结构化依据字段不计入正文。未满足结构或长度要求时保留原始内容与实际用量，提示核查，不自动付费改写。

更换模型选项只改变下一次生成设置。原报告、原图快照与模型信息保持绑定，点击生成后才更新。专业形势图和多图任务可选Sol，用户仍需对照原图核验结论。

## 实现位置

- `modules/vision_service.py` 保存模型档位、独立凭据解析、严格JSON Schema、后台提交、取回与任务日志。
- `modules/chart_reader.py` 提供三模型选择、后台进度、配额预留与结算接线、报告归属及正文校验。
- `modules/ai_narrative.py` 保留原兼容接口，增加Qwen流式用量接收；不保存内部思考正文。
- `modules/app_state.py` 登记新增模型和任务状态，重置或退出登录时清理对应会话状态。

OpenAI请求使用各模型指定的思考设置，不发送temperature；输出限额使用`max_output_tokens`。Qwen使用原生思考设置、temperature 0.3及`max_tokens`，并启用流式最终usage回执。

## 配额与取回

沿用现有Supabase服务端的`begin_vision_call`和`settle_vision_call`，没有新增表或迁移。模型请求前先预留，已知用量按输入加完整生成量结算并释放余量；思考token已含在生成量中，不重复加算。未知用量保留保守预算，读取后台结果不占用新的生成次数。

OpenAI后台任务只创建一次，先将请求标识写入本机日志，再提交。返回response ID后立即保存，后续只GET同一响应。本地接入显式使用store=true，以支持后续取回；正式部署前应结合资料类型确定服务端保留与持久化策略。自动查看窗口为180秒，单次提交读取超时180秒；GET读取超时20秒。超过自动查看窗口可点击“查看最新进度”，不会创建第二份生成任务。未收到任务编号时显示待确认状态，用户可结束追踪并保留预算，程序不会自行重发。

任务日志按用户标识的哈希隔离，保存在Git忽略的`.vision-jobs/`。日志保存调用标识、模型、response ID、可见报告、图片哈希与用量；不保存密钥、图片字节和内部思考正文。重新进入页面可恢复待完成任务；原图仍只保存在会话内存中，服务重启后需重新上传相同原图恢复含图核对。线上若使用临时磁盘，重建实例可能丢失本机日志，正式部署前需确定持久化位置。

切换模型、查看依据、读取进度和导出不会自动重新生成。结算失败会保留待结算记录，按调用标识幂等重试结算，不重复计入会话累计。

## 服务端凭据

OpenAI选项使用`OPENAI_API_KEY`，顺序为进程环境变量、Streamlit Secrets、本机`.env.local`。服务地址可设置`OPENAI_BASE_URL`，默认`https://api.openai.com/v1`。

Qwen选项使用`QWEN_VISION_API_KEY`，兼容本机已保存的`BASELINE_VISION_API_KEY`及原Qwen的`LLM_VISION_API_KEY`。只有原模型名以qwen开头时才使用旧`LLM_VISION_*`配置。服务地址默认`https://dashscope.aliyuncs.com/compatible-mode/v1`，也可设置`QWEN_VISION_BASE_URL`。两家凭据互不回落。

密钥继续使用用户已授权保存的本机文件，本轮未创建或复制新密钥。配置示例见`.streamlit/secrets.toml.example`，不含真实凭据。

## 本地验收

全量测试使用项目虚拟环境，结果为 **657 passed、3 skipped，75.39秒**。新增28项用例阻断真实HTTP，覆盖三模型路由、独立凭据、预算上限、单次提交、重启后取回、临时读取失败、输出边界、未知用量、Qwen流式回执，以及真实Streamlit控件的切换、生成、取回和报告快照。

会话状态注册表检查通过，258个键、10条前缀规则；Python侧CSS变量引用464处均可解析，Plotly中没有误用CSS变量。浏览器已核对本地预览菜单，Qwen为默认，Terra和Sol均可选；预览生成按钮禁用，不产生费用。

用户授权离线检查后最多两次真实调用。本轮受控验收入口为`.vision-poc/workbench-integration-20261105/acceptance.py`，硬限制两次生成POST，复用已存在的任务编号；测试中的配额与结算使用隔离的本地替身，模型生成与取回访问真实OpenAI API，云端数据库没有写入。

两次真实调用均完成，输出结构和长度通过，UI显示与Word/Markdown导出通过。

| 模型 | 样本 | 正文字数 | 输入/生成token（含思考） | 端到端耗时 | 标价估算USD | Word原图 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| gpt-6.1-terra xhigh | synoptic_01 | 1047 | 1985 / 7377 | 103.4秒 | 0.038870 | 1 |
| gpt-6.1-sol high | multi_01 | 1355 | 3449 / 4579 | 114.2秒 | 0.052688 | 3 |

合计标价估算为 **$0.091558**，实际费用以账单为准。两次调用各结算一次，切换模型及重复渲染没有新增生成。Terra任务在验收脚本中断后通过原ID恢复，端到端耗时含中断与恢复等待；不能解释为服务商纯生成时间。Terra在该样本正确保留−15.9°C负号和2012年1月2日UTC时次。Qwen本轮做离线回归，未另发第三次付费请求。详细回执、可见输出及导出位于`.vision-poc/workbench-integration-20261105/`。

## 本地运行

```powershell
.\.venv\Scripts\python.exe -B -m streamlit run app.py
```

本轮已重启本地127.0.0.1:8501开发进程加载最终配置，健康检查HTTP 200。已有其他开发进程若禁用了文件监听，需重启后加载新代码。需要原有登录与可信配额服务配置才可在正式页面生成；没有配额预留时不会访问模型。独立验收脚本使用本地配额替身，仅用于测试，不参与生产页面。

上一轮24案例比较参见`vision-poc-results-20261104.md`。本轮两次真实调用用于接入冒烟与导出验收，Terra的专业质量仍需代表性样本评估。

## Streamlit Cloud上线操作

本地验收记录保留上述时点的范围。发布三模型入口时，将配套代码与测试合并到网站绑定的`main`分支，确认GitHub CI通过后执行`Reboot app`。项目生产配置关闭文件监听，需在真实页面确认新菜单生效。重启前等待在途读图任务结束。

云端保留原Qwen与Supabase配置，在Secrets顶层设置`OPENAI_API_KEY`，可选设置`OPENAI_BASE_URL = "https://api.openai.com/v1"`。本机`.env.local`、`.vision-poc/`和`.vision-jobs/`不进入Git提交。现有三模型接入沿用已部署的配额RPC，不要求重建数据库。

上线后先核对Qwen默认、Terra xhigh和Sol high可选，以及切换模型不触发生成。真实API、云端配额结算与下载由线上验收确认，本地通过不替代该项验收。云端实例磁盘不保证持久保存；当前版本适合小范围试用，长期运行前应将后台任务编号及结算状态持久化到数据库，并验证实例重建后的恢复。

## 官方接口依据

- [GPT-6.1 Terra](https://developers.openai.com/api/docs/models/gpt-6.1-terra)和[GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol)的图像输入、思考参数和输出支持。
- [Responses后台模式](https://developers.openai.com/api/docs/guides/background)的一次创建和按ID取回。
- [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)及[Responses创建参数](https://developers.openai.com/api/reference/resources/responses/methods/create)的严格JSON Schema输出。
