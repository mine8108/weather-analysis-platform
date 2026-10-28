# 城市地标彩蛋图片预览

状态更新于 2026-10-28：用户已授权实现 41 城地标并更新现有线上网站。运行时接入与验证见 [发布记录](../landmark-release/README.md)。下方保留原设计阶段说明与来源。

用户选择：平时淡淡可见，悬停天气区域时更清晰。用户再次明确先生成图片，再修改页面。

## 41 城扩展预览

范围已按用户回复确定为大陆 31 座省会、首府及直辖市，加香港、澳门、台北，以及深圳、苏州、青岛、厦门、大连、三亚、桂林，共 41 城。完整映射与选型依据见 [city-inventory-41.md](city-inventory-41.md)。

四组图片展示较清晰的地标显现状态，用于审核地标与天空的融合。网页继续只显示关注城市。运行时使用另行生成的 41 张透明单体素材，清单在 `assets/landmarks/catalog.json`，压缩文件与校验值在 `assets/landmarks/manifest.json`；这些设计板本身不作为网页背景。

| 分组 | 城市数 | 图片 | 完整提示词与生成记录 |
| --- | --- | --- | --- |
| 北方与东北 | 9 | [north-northeast-preview-v1.png](north-northeast-preview-v1.png) | [north-preview-prompt.md](north-preview-prompt.md) |
| 华东 | 11 | [east-preview-v1.png](east-preview-v1.png) | [east-preview-prompt.md](east-preview-prompt.md) |
| 中南与港澳 | 11 | [central-south-preview-v1.png](central-south-preview-v1.png) | [central-south-preview-prompt.md](central-south-preview-prompt.md) |
| 西部 | 10 | [west-preview-v1.png](west-preview-v1.png) | [west-preview-prompt.md](west-preview-prompt.md) |

生成图的建筑细部为概念表达，不能替代逐城实景核对。当前显现态的对比度偏强，后续静态常态需淡化。地标选择由城市决定，晴、雨、雪、雾等天空与天气表现独立随气象数据变化。

审阅结果与已知差异见 [preview-review.md](preview-review.md)，实际尺寸、来源与文件校验信息见 [preview-manifest.json](preview-manifest.json)。西部图缺少页脚声明，统一说明：四组图片均为静态概念预览，天气数值仅为示例，本轮未接入代码。

## 首轮三城双态参考

预览：preview-v1.png。左列默认淡化，右列悬停显现。北京天坛祈年殿、杭州西湖与雷峰塔、上海陆家嘴。数值均为设计示例，图片不证明动画已经实现。生成图两列有少量地标尺度差异；后续实现建议固定地标位置和大小，只改变雾层和显现强度。

生成方式：内置 Image Gen，无 CLI/API 回退。
原设计图：$CODEX_HOME\generated_images\01a17599-957c-7ff0-aae9-4069a80bf331\exec-9ebab685-c7db-43a9-bd83-6a7331b8e314.png

三个透明素材仅供后续设计参考，当前保存在本目录，不在生产 static/weather 中。生成素材存在少量低 alpha 蓝青边缘，若后续接入需先检查实际天空合成效果。

原素材来源：
- 北京：$CODEX_HOME\generated_images\01a177d2-91e6-7ea0-b3a9-913448893b53\exec-ba331c0a-3026-45a1-87e2-e0fc7e4721d0.png
- 杭州：$CODEX_HOME\generated_images\01a177d2-afeb-7f12-b880-f8ab1547f28a\exec-cb96e85a-0153-4c2c-9e21-bb83f29c3ea8.png
- 上海：$CODEX_HOME\generated_images\01a177d2-cccc-7a51-9c25-fb8539c802a8\exec-cb1ea14d-3301-4e80-bb56-ee2d3776b9ff.png

## 设计图完整提示词

```text
Create a polished Chinese product-design comparison board by adapting the weather-card design in reference image 1 and compositing the landmark inserts from references 2, 3 and 4. This is a static DESIGN PREVIEW for a professional meteorological analysis workbench, not a functioning application or a real weather report.

Reference roles:
1. The full weather-wall mockup is the authoritative art direction: soft sky blue, lavender, warm white background; rounded photographic sky cards; white city labels and large temperature; elegant restrained Chinese UI typography. Preserve this visual language closely.
2. The transparent Temple of Heaven image is the Beijing landmark insert. Preserve the recognizable three-tier circular blue-roof Hall of Prayer for Good Harvests.
3. The transparent West Lake/Leifeng Pagoda image is the Hangzhou landmark insert. Preserve the lake, tree-lined shore and recognizable pagoda.
4. The transparent Lujiazui skyline image is the Shanghai landmark insert. Preserve the recognizable Oriental Pearl Tower and major towers. Transparent regions must blend with the sky, never appear black.

Board composition: landscape approximately 1536 by 1080. Very clean premium UI presentation with a small title at top, then TWO equal columns and THREE rows of wide weather cards. Left column heading exactly “默认状态 · 淡淡可见”. Right column heading exactly “悬停天气区域 · 地标显现”. Rows in order: Beijing, Hangzhou, Shanghai. Each row shows the SAME city, same weather, same values, same composition on both sides, with ONLY landmark visibility and a very subtle cloud/haze shift changing on the right. Card aspect ratio about 2.6:1, consistent rounded corners 14px, ample narrow gutters, no phone frame or browser chrome. Background is the same very soft sky-blue-to-pale-lavender and warm-white atmosphere as reference 1, mostly pale and calm. No unrelated dashboard panels.

Exact title “城市地标彩蛋”. Subtitle “保留天空质感，让城市藏在天气里”.
Beijing cards: “北京”, “24°”, “多云”, “28° / 20°”; softly lit blue-gray cumulus sky. Temple of Heaven sits small in the lower-right far distance, never underneath editable text on left.
Hangzhou cards: “杭州”, “26°”, “晴间多云”, “30° / 22°”; pale blue sky, soft clouds, a gentle hint of sunshine. A small West Lake shore, quiet water and Leifeng Pagoda occupy only lower-right, blended into atmospheric haze.
Shanghai cards: “上海”, “27°”, “晴”, “31° / 23°”; clear soft blue sky, warm small sun in upper-right and delicate clouds. Lujiazui skyline occupies only lower-right, at a restrained scale no larger in apparent prominence than the temple or lake scenes.
Use crisp white city names at upper-left, large temperature at middle-left, weather condition beside temperature. Small unobtrusive humidity/wind data near lower-left may read “湿度 56%   风速 2.8 m/s” consistently as demonstration values; DO NOT add fake data-source status or current real timestamps.

Critical visual behavior shown in the STILL image: On the LEFT cards, landmarks should be softly recognizable yet distant and quiet, approximately 20–25% visual contrast through light atmospheric haze. On the RIGHT cards, landmarks become gently clearer, around 55–60% visual contrast. Keep sky and clouds dominant in BOTH states. This should feel like discovering a city in the distance, not a postcard or tourist poster. Reduce the landmark groups in scale if necessary to avoid left-side text or full-width ground strips. No floating sticker appearance, harsh outline, cyan fringes or hard water cutout edges. Integrate the bases with fine atmospheric haze. Do not change temperature, card brightness, card size or text position between states. No large hover glow, no outlined callout boxes, no arrow annotations across the board. A tiny neutral cursor over the weather region in the right-hand cards is acceptable but optional.

Footer in small clear Chinese text “静态概念预览 · 地标默认静止，悬停时短暂显现 · 天气数值仅为示例”.
Deliver one refined, coherent image with all SIX cards fully visible and no cropping.
```
