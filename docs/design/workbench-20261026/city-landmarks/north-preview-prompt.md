# 北方与东北 · 生成记录

方式：内置 Image Gen。仅设计预览，无应用代码变更。

原图：$CODEX_HOME\generated_images\01a17599-957c-7ff0-aae9-4069a80bf331\exec-5ff4b8af-3bef-4803-a0a5-779db2299546.png

保存：north-northeast-preview-v1.png

参考：preview-v1.png，作为天空、卡片与排版风格参考。

检查：9 个城市及地标标签齐全；天气数值均为示例。地标显现状态偏清晰，常态仍按双态参考淡化。建筑细部属于生成概念，未做逐栋测绘精度认证。

## 完整提示词

```text
Use case: ui-mockup
Create a high-fidelity expanded city-landmark weather-card preview based on the attached design. The attached image is the style reference, not something to paste into the output. Preserve its photographic blue sky, soft cumulus clouds, pale lavender/warm white surrounding surface, refined rounded cards, atmospheric haze, and typography hierarchy.

Target dimensions: 1536 x 960, landscape. A single component collection sheet, exactly 9 equal horizontal weather cards in a strict 3-column by 3-row grid. Margins about32px, gutters20px, header110px. Each card about477 x230. No extra card, no missing city, no duplicates. Do not reproduce the reference's two-column before/after comparison.

Title exact Chinese: "城市地标彩蛋 · 北方与东北"
Subtitle exact Chinese: "地标显现态预览 · 默认状态沿用淡化规则"
Footer exact Chinese: "静态概念预览 · 天气数值仅为示例 · 本轮未接入代码"
Each card has the exact city name large white in upper left, a larger "24°" below, "多云" as the only weather condition, and the exact landmark label in smaller white lettering near bottom left. Keep text sharp, legible and correctly spelled. All weather values are placeholders. Do not add dates or present live observations.

Each landmark appears in the lower-right part of its own card, around45% of card width, with natural atmospheric perspective, subdued cool colors and fine believable architectural features. Weather sky and large temperature remain primary. Show the moderately clearer hover state, not completely opaque tourism photographs. Soft haze dissolves buildings into the sky and ground. Avoid repetitive generic pagodas. Match each recognizable landmark carefully:
ROW1:
1 北京, label "天坛祈年殿": ONE round Hall of Prayer for Good Harvests with THREE concentric blue-tiled roof tiers and a gold finial, red columns and white marble round terraces.
2 天津, label "天津之眼": a large circular Ferris wheel standing over a bridge across a narrow river, not a generic tower.
3 石家庄, label "石家庄电视塔": tall tapering open steel lattice TV tower, broad angular lattice legs, small circular observation levels high on it, tall antenna.
ROW2:
4 太原, label "双塔寺": TWO slender tall gray brick octagonal pagodas of almost equal height, each with many small closely spaced eaves, surrounded by sparse greenery.
5 呼和浩特, label "大召寺": low Tibetan-Chinese Buddhist temple hall, golden/yellow roofs, white walls, restrained red structural details; no huge stupa or Potala substitution.
6 沈阳, label "沈阳故宫大政殿": the distinctive low octagonal imperial hall with double yellow tiled roof and red columns, not Beijing Temple of Heaven.
ROW3:
7 长春, label "伪满皇宫同德殿": a long symmetrical two-story buff/yellow palace with a dark broad hipped Chinese roof, a central entrance with smaller roof, not a many-storey pagoda.
8 哈尔滨, label "圣索菲亚教堂": red brick Byzantine church with its large dark green onion dome and smaller side domes, realistic architecture.
9 大连, label "星海湾大桥": long sea-crossing suspension bridge with two tower structures, curved suspension cables and slim vertical hangers over a blue bay.

No map, no flags, no marketing badges, no sidebar, no browser chrome, no new controls, no watermarks. Keep full cards inside canvas, no clipping. This is one consistent design collection of the approved weather-card style, not nine different graphic styles. No code.
```
