# 气象读图配对验证结果

实验清单日期2026-11-04，报告生成于 2026-11-04T15:49:40.464411+00:00（UTC）。本次完成24个真实案例、两种模型共48次主实验生成尝试，另有3次合成流程探针。

**决策建议：保留 Qwen 默认入口，将 Sol high 作为待独立专家复核的增强解读候选。暂不切换生产默认模型。** Sol 在本次小样本中的可见数值、符号、单位和证据范围处理更稳；交互耗时超过预先登记的75秒P95目标，专业综合解释仍有明显遗漏。

以下质量指标来自 Codex 对照原图及来源的初审，未完成独立气象专家盲评。参考事实提前冻结；两处原图色标记录错误另附勘误，对双方统一评分。评分顺序隐藏模型标识，但同一助手参与参考编写与评分，仍有判断偏差风险。

## 留出集结果

| 指标 | GPT-6.1 Sol high | Qwen3.8 Flash |
| --- | ---: | ---: |
| 案例数 | 18 | 18 |
| 输出契约通过 | 18 | 14 |
| 初审可接受 | 18 | 6 |
| 初审严重错误 | 0 | 9 |
| 已知用量未缓存标价估算，USD | 0.8930 | 0.0382 |
| 每份初审可接受报告，USD | 0.0496 | 0.0064 |
| 完成/取回耗时中位数，秒 | 109.0 | 66.1 |
| 完成/取回耗时P95，秒 | 159.3 | 84.7 |

耗时包含网络、模型生成、轮询与必要的同ID结果取回；受本机网络影响，不能解释为服务商纯推理速度。后台传输策略在开发阶段及留出读取故障后调整，生成模型、思考度、图片和提示词保持固定。

| 留出图类 | 案例 | Sol 初审可接受 | Qwen 初审可接受 |
| --- | ---: | ---: | ---: |
| 曲线 | 3 | 3 | 2 |
| 地面及高空形势 | 4 | 4 | 0 |
| 雷达 | 3 | 3 | 1 |
| 卫星 | 3 | 3 | 2 |
| 多图综合 | 5 | 5 | 1 |

## 额度、token和工程记录

全研究已知用量的 OpenAI 未缓存标价估算为 **$1.1772**；另有 **2 次**早期无回执请求，用量未知，继续保留合计 **$0.98304** 本地预留。此预留不能称为实际扣费。

Qwen全研究原生未缓存标价估算为 **¥0.3406**，单独由阿里云结算，不能使用OpenAI赠送额度。缓存、折扣、免费额度及账单尚未核对。全研究本地预算占用为 **$2.5224 / $10**，包含未知预留及已知费用余量。

真实Sol成功返回的总生成量中位数为 **4,078 token**，最大 **5,657 token**，均含内部思考；本轮继续保留32768上限。正文长度与token量分别核算，六段正文要求800至2000个去空白Unicode字符。推理已包含在输出计费量中，不能再相加。

生成POST不自动重试。早期2次无回执失败保留预算。另2次后台读取中断通过原response ID取回，没有重新生成；后续临时GET读取最多连续尝试3次。原始失败事件保留在追加式账本中。180秒是HTTP读取超时与后台轮询窗口，无法保证严格的端到端完成时间。

离线相关测试107项通过，测试阻断真实HTTP；这些测试验证工程契约，不构成气象质量验证。生产应用、Supabase配额与线上模型均未修改。

## 关键差异与不足

- Qwen在JMA高空图漏读−15.9的负号，并把风羽解读为锋面；在低分辨率高空图把5520等值线读成583并将闭合低值结构反判为高值中心。
- Qwen在三时次雷达图将地图缩放级别3至15当作反射率色标；在一组真实有色标的三产品图中反而漏读DBZ、KTS和%。
- 在逆序上传的两张地面图中，Sol正确读取2024年1月8日至9日；Qwen误读为2006年1月2日至3日，并据此陈述错误年份的过程。
- 部分Qwen回答的专业内容可读，但JSON语法错误，现有解析器无法接收；原回答保留，未付费重写。
- Sol在多处形势图中未提取可辨认的主低压数值，位置描述偏笼统；对云街和跨产品物理配合的解释偏浅。较少错误与更完整的业务分析需要分别核查。

## 逐案例记录

总分只用于定位复核重点，不能作为经过独立标定的气象准确率。严重错误与交付失败分别记录。无回执案例在交付总表中记0分，该记录不包含可供科学内容评价的回答。

| 案例 | 划分 | Sol状态/初审 | Qwen状态/初审 |
| --- | --- | --- | --- |
| curve_01 | dev | ok / 98分 / 通过 | ok / 90分 / 通过 |
| curve_02 | holdout | ok / 99分 / 通过 | ok / 94分 / 通过 |
| curve_03 | holdout | ok / 99分 / 通过 | ok / 94分 / 通过 |
| curve_04 | holdout | ok / 99分 / 通过 | ok / 62分 / 未通过 / 严重错误 |
| multi_01 | dev | ok / 99分 / 通过 | ok / 50分 / 未通过 / 严重错误 |
| multi_02 | holdout | ok / 97分 / 通过 | ok / 77分 / 未通过 |
| multi_03 | holdout | ok / 99分 / 通过 | ok / 83分 / 通过 |
| multi_04 | holdout | ok / 90分 / 通过 | ok / 57分 / 未通过 / 严重错误 |
| multi_05 | holdout | ok / 94分 / 通过 | invalid_structure / 50分 / 未通过 / 严重错误 |
| multi_06 | holdout | ok / 99分 / 通过 | body_length_failed / 73分 / 未通过 / 严重错误 |
| radar_01 | dev | ok / 99分 / 通过 | ok / 91分 / 通过 |
| radar_02 | holdout | ok / 97分 / 通过 | ok / 62分 / 未通过 / 严重错误 |
| radar_03 | holdout | ok / 97分 / 通过 | invalid_structure / 83分 / 未通过 |
| radar_04 | holdout | ok / 96分 / 通过 | ok / 83分 / 通过 |
| satellite_01 | dev | ok / 97分 / 通过 | ok / 89分 / 通过 |
| satellite_02 | holdout | ok / 98分 / 通过 | ok / 91分 / 通过 |
| satellite_03 | holdout | ok / 99分 / 通过 | ok / 92分 / 通过 |
| satellite_04 | holdout | ok / 93分 / 通过 | invalid_structure / 90分 / 未通过 |
| synoptic_01 | dev | request_or_parse_error / 0分 / 未通过 | ok / 48分 / 未通过 / 严重错误 |
| synoptic_02 | dev | ok / 96分 / 通过 | invalid_structure / 60分 / 未通过 / 严重错误 |
| synoptic_03 | holdout | ok / 89分 / 通过 | ok / 56分 / 未通过 / 严重错误 |
| synoptic_04 | holdout | ok / 91分 / 通过 | ok / 66分 / 未通过 / 严重错误 |
| synoptic_05 | holdout | ok / 91分 / 通过 | ok / 49分 / 未通过 / 严重错误 |
| synoptic_06 | holdout | ok / 94分 / 通过 | ok / 35分 / 未通过 / 严重错误 |

## 接入前仍需完成

1. 独立气象专家至少复核6个困难案例，尤其是形势中心数值、KTS速度/百分比产品和多图时序判断；使用附勘误的盲评包，评分人先不查看模型映射。
2. 若继续试点，采用有进度状态、response ID持久化和结果取回的异步增强入口；同时保留快速默认入口。180秒以内未取回时显示待完成，不再次生成。
3. 后续在开发集先比较全图加局部放大及服务端结构化输出约束，对所有模型采用相同输入，核查可修复的工程差距。Sol本轮最大生成5657，后续可测试16384上限对困难任务的截断率；当前配置保留32768。
4. 对工作台实际中文业务图再补代表性验收，核对预留释放、错误展示、引用和下载不重复计费，再决定生产配置。两家服务商账单单独核对。

本轮数据以英文北美公开专业图和ERA5自制曲线为主，部分图故意缺少标题或元数据；13个事件组中的案例并非完全独立。结果支持选择下一步试点方向，无法外推全部中国业务产品或罕见严重错误率。Sol high与Qwen原生思考设置的差异还包含计算策略；同一输出长度区间也不代表同样的信息密度。

## 可复核文件与来源

- [方案与运行说明](vision-poc-20261104.md)
- [汇总指标](../.vision-poc/study/decision_metrics.json)、[原始账本](../.vision-poc/study/ledger.jsonl)、[逐项初审](../.vision-poc/study/reviews.csv)
- [盲评包](../.vision-poc/study/blind_review.json)、[模型映射](../.vision-poc/study/private_mapping.json)
- [冻结样本](../.vision-poc/real/manifest.json)、[参考勘误](../.vision-poc/real/reference_errata.json)、[素材来源和哈希](../.vision-poc/real/source_inventory.json)
- [Sol官方模型与价格](https://developers.openai.com/api/docs/models/gpt-6.1-sol)、[Responses后台模式](https://developers.openai.com/api/docs/guides/background)、[Qwen3.8 Flash官方说明](https://help.aliyun.com/zh/model-studio/qwen3-8-flash)
- [ERA5曲线数据接口](https://open-meteo.com/en/docs/historical-weather-api)、[JMA高空图示例](https://www.jma.go.jp/jma/kishou/know/kurashi/upper_map.html)、[NWS OUN过程](https://www.weather.gov/oun/events-20240427)、[NWS IWX过程](https://www.weather.gov/iwx/20240507_TornadoesSevereWx)、[NWS MRX过程](https://www.weather.gov/mrx/May_8_9_Severe)
