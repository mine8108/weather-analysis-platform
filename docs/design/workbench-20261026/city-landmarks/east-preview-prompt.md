# 华东城市地标天气卡片概念预览

- 生成日期：2026-10-26
- 工具：内置 Image Gen，1 次生成，未进行修正生成。
- 目标尺寸：1536 × 1152；实际尺寸：1448 × 1086（4:3），RGB，2,089,163 字节。保留生成器原尺寸，未进行缩放。
- 参考图片：C:\Users\ASUS\Desktop\24024115 郑昊\气象网站\weather_app\docs\design\workbench-20261026\city-landmarks\preview-v1.png
- 原生成路径：$CODEX_HOME\generated_images\01a177d2-afeb-7f12-b880-f8ab1547f28a\exec-eb3421f3-c20a-47bc-8c15-4641b50cbaa7.png
- 最终图片：C:\Users\ASUS\Desktop\24024115 郑昊\气象网站\weather_app\docs\design\workbench-20261026\city-landmarks\east-preview-v1.png
- 保存方式：原图直接复制，未改变像素；SHA-256 与原文件一致。

## 视觉检查

11 个城市均出现一次，排列为 3、3、3、2，最后一格留白。所有卡片均为 24°、多云示例，标题、副标题和底部说明齐全。

| 城市 | 地标标签 | 可见主体 |
| --- | --- | --- |
| 上海 | 陆家嘴天际线 | 东方明珠、上海中心、环球金融中心组成天际线 |
| 南京 | 中山陵 | 蓝瓦白石纪念堂与中央阶梯 |
| 杭州 | 西湖与雷峰塔 | 湖面、柳岸和远处雷峰塔 |
| 合肥 | 清风阁 | 仿古阁楼与园林；细部属于生成式概念表达，尚未依据实景逐项核验 |
| 福州 | 白塔 | 白色分层塔体 |
| 济南 | 超然楼 | 湖边多层传统阁楼 |
| 南昌 | 滕王阁 | 多层传统阁楼与高台基座 |
| 苏州 | 东方之门 | 顶部连成门形的成对玻璃高楼 |
| 青岛 | 栈桥回澜阁 | 海面长栈桥及尽端亭阁 |
| 厦门 | 鼓浪屿八卦楼 | 红色圆顶西式建筑 |
| 台北 | 台北101 | 竹节式蓝绿高楼 |

剩余限制：这是静态设计概念图。建筑细节经过生成式概括，合肥清风阁、济南超然楼等不应据此认定为精确建筑复刻。部分地标对比度比原先的“弱一些”要求更显著，后续可在整板评审中决定淡化程度。未修改、接入或部署应用代码。

## 完整提示词

```text
Create one polished raster UI design preview board for a Chinese professional meteorological analysis workbench. Target 1536 x 1152 pixels, landscape 4:3. This is an image preview only, not working code.

REFERENCE: the supplied design board is ONLY a style and weather-card composition reference. Faithfully preserve its photographic soft volumetric cloud texture, atmospheric blue sky, delicate warm-white sunlight, pale lavender overall background, tasteful rounded corners, beautiful white typography and calm weather-first visual hierarchy. Use the reference's right-column landmark visibility state, but reduce landmark contrast a little so weather remains dominant. Do not copy its six-card arrangement or its Beijing card.

BOARD LAYOUT: exactly ELEVEN equal-sized horizontal weather cards, in THREE COLUMNS and FOUR ROWS. Cards approximately 470 x 215, consistent rounded radius and tight 18 px gutters. Wide clean title region at the top and small centered footer at the bottom. Rows 1–3 have three cards each. Row 4 has two cards in columns 1 and 2; column 3 remains naturally blank pale-lavender page background with NO card, NO placeholder, NO extra text. Keep every card fully visible, consistent size, no cropping. Do not repeat a city.

Exact main title at top: “城市地标彩蛋 · 华东”
Exact subtitle directly below: “地标显现态预览 · 默认状态沿用淡化规则”
Exact footer at bottom: “静态概念预览 · 天气数值仅为示例 · 本轮未接入代码”

EACH CARD: left 40–45% is clear calm blue sky for readable text. At upper left, large bold white city name. Under it, prominent large white “24°” with smaller white “多云” beside it. Along bottom left, a smaller clear white label naming that city's main landmark exactly as specified below. No weather numbers other than 24°. No min/max temperatures, no humidity, no wind, no extra UI controls. On the right half, a carefully recognizable realistically proportioned landmark gently emerges through light atmospheric haze in the lower-right region, never covering any text. Blue sky and soft white clouds remain the main subject and largest area. Landmarks are beautiful small city Easter eggs, not full-card travel photographs. Use restrained realistic perspective, soft edge mist, color integrated with the blue weather palette; no hard cutout border.

EXACT ELEVEN CARDS IN READING ORDER, match the city text, landmark label and visible building:
Row 1 column 1: city “上海”, bottom label “陆家嘴天际线”. Right-side Shanghai Lujiazui skyline with Oriental Pearl Tower's spheres, twisting Shanghai Tower, and the Shanghai World Financial Center's trapezoid opening. These form ONE city skyline.
Row 1 column 2: city “南京”, bottom label “中山陵”. Sun Yat-sen Mausoleum memorial hall, broad white-stone facade, blue tiled roof and long central stone stairway. This must look like a low blue-roof white memorial hall, NOT an ancient multi-storey pagoda.
Row 1 column 3: city “杭州”, bottom label “西湖与雷峰塔”. Quiet West Lake, willow-lined shore and a small distant five-storey tiered Leifeng Pagoda. Calm water reflections confined to the right.
Row 2 column 1: city “合肥”, bottom label “清风阁”. Qingfeng Pavilion in Bao Park, a refined Song-style Chinese pavilion tower, warm white walls and blue-gray traditional projecting roofs. Do NOT substitute Xiaoyao Pavilion / 逍遥阁, no oversized dark-red gate tower.
Row 2 column 2: city “福州”, bottom label “白塔”. Fuzhou White Pagoda, WHITE seven-storey OCTAGONAL pagoda, slender layered white masonry with recognizably seven storeys, keep the white tower distinct against soft blue.
Row 2 column 3: city “济南”, bottom label “超然楼”. Chaoran Tower at Daming Lake, grand symmetrical traditional multi-level Chinese pavilion building, broad projecting dark tiled eaves over warm pale walls, seen above lakeside greenery.
Row 3 column 1: city “南昌”, bottom label “滕王阁”. Tengwang Pavilion, red-column grand traditional pavilion with multi-tier sweeping green-gray roofs, broad raised white stone base and riverbank atmosphere, distinctive grand symmetrical proportions.
Row 3 column 2: city “苏州”, bottom label “东方之门”. The modern Gate of the Orient, two tall gently curved glass towers JOINED ACROSS THE TOP to form one giant arch / trouser-leg gateway. The central opening is very visible; do not show two unrelated towers.
Row 3 column 3: city “青岛”, bottom label “栈桥回澜阁”. Zhanqiao pier extends over a blue sea to the small octagonal Huilan Pavilion with traditional eaves at its end. Include the long sea pier and terminal pavilion, no unrelated skyline.
Row 4 column 1: city “厦门”, bottom label “鼓浪屿八卦楼”. Gulangyu Bagua Building / Organ Museum: an elegant western colonial villa with a LARGE DISTINCTIVE RED ROUND DOME and cream walls, not a Chinese pagoda.
Row 4 column 2: city “台北”, bottom label “台北101”. Taipei 101, recognizable blue-green skyscraper with stacked bamboo-joint tiers and slender spire, framed by soft clouds.
Row 4 column 3: empty background only.

All text is exact Chinese with correct glyphs, and all eleven cities appear ONCE. No maps, flags, badges, extra panels, sample icons, UI buttons, watermarks or logos. Preserve professional weather-card atmosphere and fully legible text.
```
