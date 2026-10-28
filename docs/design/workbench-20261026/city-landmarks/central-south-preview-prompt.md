# 中南与港澳城市地标天气卡片预览提示词

- 日期：2026-10-26
- 生成方式：内置 image_gen，单次生成，未追加修正。
- 参考图：$PROJECT_ROOT/docs/design/workbench-20261026/city-landmarks/preview-v1.png
- 原生成图：$CODEX_HOME/generated_images/01a177d2-cccc-7a51-9c25-fb8539c802a8/exec-71167ba6-a0af-4f15-be97-6b7fe1611f75.png
- 归档图：$PROJECT_ROOT/docs/design/workbench-20261026/city-landmarks/central-south-preview-v1.png
- 请求尺寸：1536 × 1152；实际尺寸：1448 × 1086，RGB；保留生成原图，未修改像素。
- SHA-256：bec3885b86ed43f1f9030feb25c6cb96100c0bff852505936b3bd3ea8f8d1669

## 视觉核对

十一张卡片按指定顺序排列，三列四行，最后一行两张、第三格留白。城市名、24°、多云及地标标签均在图中可见，无重复或漏城。

| 城市 | 地标 | 核对结果 |
| --- | --- | --- |
| 郑州 | 中原福塔 | 钢结构高塔与花瓣状上部观景盘可识别 |
| 武汉 | 黄鹤楼 | 多层黄色飞檐楼阁可识别 |
| 长沙 | 天心阁 | 古城墙上的传统阁楼可识别 |
| 广州 | 广州塔 | 细腰扭转网格塔可识别 |
| 南宁 | 青秀山龙象塔 | 青绿山丘上的多层传统塔可识别 |
| 海口 | 世纪大桥 | 双塔斜拉桥与桥面可识别 |
| 深圳 | 平安金融中心 | 尖顶修长摩天楼可识别 |
| 三亚 | 凤凰岛 | 多座曲面卵形高楼与海岛可识别 |
| 桂林 | 日月双塔 | 金色高塔、银灰低塔及湖面可识别 |
| 香港 | 维港与中银大厦 | 三角斜撑高楼及窄幅海港天际线可识别 |
| 澳门 | 大三巴牌坊 | 独立石立面与台阶可识别，未画完整教堂 |

剩余差异：部分地标比要求的柔雾显现态略鲜明，香港、海口与三亚的水岸横向延伸较宽。图为静态概念表达，建筑细部与塔层数没有进行测绘级核验。未接入页面、未修改应用代码。

## 完整生成提示词

```text
Create one polished raster design preview board for Chinese city-landmark weather cards, target size 1536 x 1152 pixels. The attached image is the authoritative reference for the sky texture, soft photographic cloud rendering, cool sky-blue/lavender/warm-white palette, fine rounded card corners and left-text/right-landmark composition. It is a style reference only; do not duplicate its cities or its two-column comparison structure.

This NEW board must show EXACTLY ELEVEN different cities in a clean three-column by four-row grid of equal-size horizontal weather cards. The fourth row contains only TWO cards in the first two columns; its third grid position stays naturally empty as the page background, with no placeholder border, empty card, icon or text. Never duplicate a city and never omit a city. All cards approximately 470 x 215 pixels, equal width and height, about18px gaps. Header fits above and footer fits below, without clipping.

Top centered title, exact Chinese:
“城市地标彩蛋 · 中南与港澳”
Subtitle, exact:
“地标显现态预览 · 默认状态沿用淡化规则”
Footer, exact:
“静态概念预览 · 天气数值仅为示例 · 本轮未接入代码”

Each card is a beautiful realistic blue sky and soft cloud scene following the attached reference. Weather remains the first visual layer. On the LEFT, put the exact city name in large bold white Chinese, a large “24°”, and “多云”. These are intentionally identical example weather values for all11 cards. At bottom-left place the exact main landmark name in smaller but readable white text. Do not add humidity, wind, high/low numbers, coordinates, map pins or unnecessary UI. Keep white text crisply legible against a calm medium-blue left half. A light sky-lit haze blends into each landmark, with the landmark on the lower-right approximately55% area; it must NEVER obscure any of the city name,24°,多云 or landmark label. Landmarks are slightly softer and less contrasty than the reference's right-hand hover column, but clearly recognizable. Avoid postcard saturation and enormous giant landmark cutouts. Buildings must have plausible realistic proportions.

STRICT CITY ORDER AND UNIQUE SUBJECTS, row by row left to right:
Row1 left: city “郑州”; bottom label “中原福塔”. Depict Zhongyuan Tower: a high steel broadcasting tower with a tall slender shaft, exposed structural supports and a distinctive flower-petal-shaped observation deck near the upper part. NOT a waist-shaped Canton Tower.
Row1 middle: city “武汉”; bottom label “黄鹤楼”. Depict Yellow Crane Tower: the recognizable traditional FIVE-LEVEL yellow-walled pavilion with five layered golden-yellow upturned eaves, smaller garden/treetops at the base.
Row1 right: city “长沙”; bottom label “天心阁”. Depict Tianxin Pavilion: a traditional multi-story Chinese pavilion mounted on an old gray stone city wall, distinct from the five-level Yellow Crane Tower.

Row2 left: city “广州”; bottom label “广州塔”. Depict Canton Tower: a very tall thin hyperboloid twisted lattice tower with a narrow waist and extended top antenna; realistic airy steel grid.
Row2 middle: city “南宁”; bottom label “青秀山龙象塔”. Depict Longxiang Pagoda on a green Qingxiu Mountain hill: a tall traditional NINE-STORY pagoda with layered upturned eaves, leafy green hill base.
Row2 right: city “海口”; bottom label “世纪大桥”. Depict Haikou Century Bridge: a twin-pylon cable-stayed bridge, long low deck and two tall pylons with fan-like cables over a little blue water. Do not replace with an arch bridge.

Row3 left: city “深圳”; bottom label “平安金融中心”. Depict Ping An Finance Centre: an extremely slender tapered silver glass skyscraper with a sharp pyramidal/spire-like crown and clearly vertical facets.
Row3 middle: city “三亚”; bottom label “凤凰岛”. Depict Phoenix Island: several distinctive curved sail-shaped / elongated egg-shaped high-rise towers grouped on a small offshore island, little tropical blue water below, not one ordinary tower.
Row3 right: city “桂林”; bottom label “日月双塔”. Depict the Sun and Moon Twin Pagodas: two visibly DIFFERENT-height traditional towers, the taller warm golden pagoda and shorter silver-gray pagoda, with subtle lake reflections and a small green shore.

Row4 left: city “香港”; bottom label “维港与中银大厦”. Depict a narrow Victoria Harbour skyline with the Bank of China Tower prominent: angular triangular facets and diagonal structural bracing in its glass tower, realistic quiet waterfront. No flag or map.
Row4 middle: city “澳门”; bottom label “大三巴牌坊”. Depict ONLY the historic Ruins of St.Paul's stone facade, recognizable Baroque carved stone front with three arched openings and stepped triangular upper facade; a few steps below. It is a freestanding surviving facade, NOT an intact church with a roof or nave.
Row4 right: entirely empty page background.

Style and layout: app-design presentation rather than tourist poster. Plenty of pale background margins, strong clean typography, fine rounded corners, restrained navy title. Within each card preserve the atmospheric sky dominance and white weather lettering of the reference. Render the Chinese city and landmark labels accurately and only once per card. No maps, flags, badges, shields, additional UI, buttons, tabs, browser frame, device, watermark, or decorative filler. Output ONLY the complete single preview board.
```
