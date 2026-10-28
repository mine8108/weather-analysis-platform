# 西部 10 城地标天气卡片概念预览

- 最终预览：`$PROJECT_ROOT/docs/design/workbench-20261026/city-landmarks/west-preview-v1.png`
- 原始生成文件：`$CODEX_HOME/generated_images/01a177d2-91e6-7ea0-b3a9-913448893b53/exec-b7811f41-945c-4e5d-8749-8d89aa2c5b48.png`
- 初始生成文件：`$CODEX_HOME/generated_images/01a177d2-91e6-7ea0-b3a9-913448893b53/exec-cf4bc6ec-458c-4112-8d40-bb1d6959c571.png`
- 风格参考：`$PROJECT_ROOT/docs/design/workbench-20261026/city-landmarks/preview-v1.png`
- 工具：内置 image_gen；一次初始生成、一次针对最后一行卡片宽度的修正。
- 实际尺寸：1448 × 1086 px，RGB，不透明；目标为1536 × 1152，比例一致为4:3。
- 最终PNG原样复制，未改像素。本轮未接入应用代码。
- 视觉核对：3列4行，最后一行1张靠左，10个城市无遗漏或重复；等宽修正已生效。
- 文本配对：重庆—洪崖洞；成都—安顺廊桥；贵阳—甲秀楼；昆明—金马碧鸡坊；拉萨—布达拉宫；西安—钟楼；兰州—中山桥；西宁—浦宁之珠；银川—鼓楼；乌鲁木齐—国际大巴扎观光塔。全部显示24°、多云，属于示例天气。
- 主体核对：重庆层叠吊脚楼群、成都廊桥、贵阳楼阁和石拱桥、昆明双牌坊、拉萨山体宫殿、西安方台基钟楼、兰州多跨钢桥、西宁单球钢构塔、银川楼阁、乌鲁木齐圆柱观光塔均有对应主体。
- 剩余缺陷：修正版遗漏要求的页脚“静态概念预览 · 天气数值仅为示例 · 本轮未接入代码”；成都雾感比要求弱；多处地标比“淡淡彩蛋”显现态仍突出；建筑细部和周边景观属于AI概念插画，未逐项实景核验，后续如需接入需按城市参考细化。
- 图中天气数值仅为设计示例，并非实况或预报。

## 初始完整提示词

Use case: ui-mockup. Create ONE complete high-quality bitmap design preview board for ten western Chinese city landmark weather cards. Target1536x1152 pixels, landscape4:3. The supplied image is ONLY the reference for atmospheric sky material, rounded weather-card style, typography and the way landmarks emerge from soft mist. Follow the reference's sky blue, pale lavender and warm white palette, realistic voluminous clouds, subtle sunlight, navy board headings and white card text. This is a STATIC CONCEPT PREVIEW, not an implemented website. No browser chrome, phone frame, maps, flags, badges, icons inventory or unrelated UI.

Board exact title centered top: “城市地标彩蛋 · 西部”
Exact subtitle under title: “地标显现态预览 · 默认状态沿用淡化规则”
At bottom exact footer: “静态概念预览 · 天气数值仅为示例 · 本轮未接入代码”

Layout: THREE columns and FOUR rows of equal horizontal cards. Card size about470x215px, gaps18px, tidy side margins. Exactly TEN cards. The LAST ROW contains ONLY ONE CARD at the LEFT; leave the other two positions naturally empty on the pale board background, no placeholder outlines or extra cards. Reading order is left-to-right then top-to-bottom, all city names unique. No city omitted, no city duplicated. Keep all10 cards and footer fully visible and uncropped.

Every card has large Chinese city name on left upper, “24°” as large white temperature beneath, “多云” nearby. These identical weather numbers are examples. No additional temperatures or humidity/wind rows needed. At lower left in readable smaller white type, put the exact landmark label supplied below. Right-lower55% of the card contains its recognizable realistically proportioned landmark, softly blended into clouds/haze, with moderate visibility similar to but slightly softer than the RIGHT column in reference. Keep landmarks wholly away from city name and temperature. Clouds/weather remain first visual hierarchy, landmarks a subtle discovery. Each card is a complete sky view, not an isolated monument on plain solid blue. Chengdu may be mistier in the lower half. Use thin soft rounded corners, no heavy shadows.

EXACT10 CARDS AND POSITIONS:
ROW1 LEFT:
City “重庆”
Landmark label “洪崖洞”
Landmark visual: recognizable warm timber stilt-house building complex built in stacked terraces on a steep urban hillside, many layered traditional roofs and hanging-floor facades. A compact distant view, not a single pagoda, not modern towers.
ROW1 CENTER:
City “成都”
Landmark label “安顺廊桥”
Landmark visual: a traditional roofed bridge crossing a river horizontally, with pavilion towers at both ends and an enclosed gallery over the bridge; white-gray bridge base and muted traditional roof details. Extra soft river fog. Do not substitute a standalone pagoda or a modern skyline.
ROW1 RIGHT:
City “贵阳”
Landmark label “甲秀楼”
Landmark visual: a three-story traditional Chinese pavilion with flying eaves standing in the river, with an adjacent stone arch bridge, a small refined scenic cluster.
ROW2 LEFT:
City “昆明”
Landmark label “金马碧鸡坊”
Landmark visual: TWO traditional painted Chinese ceremonial archways near each other, ornate wooden tiled roofs and pillared gates, clearly paired. Do not draw a temple hall.
ROW2 CENTER:
City “拉萨”
Landmark label “布达拉宫”
Landmark visual: a broad mountain-top palace complex, extensive stepped WHITE walls and a central RED palace rising on a hill, unmistakable Potala Palace proportions. Desaturated, atmospheric and distant.
ROW2 RIGHT:
City “西安”
Landmark label “钟楼”
Landmark visual: the Xi'an Bell Tower, a traditional multi-eaved Chinese pavilion on a broad SQUARE gray masonry plinth with archway opening. Strong recognizable horizontal square-platform silhouette.
ROW3 LEFT:
City “兰州”
Landmark label “中山桥”
Landmark visual: a low MULTI-SPAN STEEL TRUSS bridge across the Yellow River, angular steel frame spans seen sideways or gentle three-quarter, distant mountains behind. Not suspension cables, no large tower bridge or Golden Gate shape.
ROW3 CENTER:
City “西宁”
Landmark label “浦宁之珠”
Landmark visual: a steel-lattice sightseeing television tower on Xishan hill, ONE prominent spherical observation tower near the top supported by the steel structure, slim antenna above. It has ONE LARGE SPHERE, not Shanghai's two-sphere Oriental Pearl. Do NOT draw a mosque.
ROW3 RIGHT:
City “银川”
Landmark label “鼓楼”
Landmark visual: a traditional double-eaved pavilion above a substantial rectangular BRICK platform, old Chinese drum tower proportions, different from Xi'an card through warm-gray brick and smaller traditional tower.
ROW4 LEFT:
City “乌鲁木齐”
Landmark label “国际大巴扎观光塔”
Landmark visual: a tall warm brick-colored CYLINDRICAL observation tower with decorative horizontal brick bands and a gently domed top, a few low bazaar rooftops nearby. It should be a distant landmark vignette on the right, not an oversized generic pointed minaret.

Make Chinese text exceptionally clean and faithful, especially “浦宁之珠”, “安顺廊桥”, “金马碧鸡坊”, “乌鲁木齐”. Landmark captions belong at the lower left; no labels atop buildings. Do not invent other wording. All10 exact city-landmark pairings must match. Keep the board elegant, calm, airy and readable with the sky weather identity dominant. Output only this one finished board.

## 唯一修正提示词

Make one precise layout correction to the attached western-city weather-card preview. Preserve all existing Chinese text, the ten city names and ten landmark labels, all landmark identities, weather numbers, sky colors, title, subtitle and footer. The last-row 乌鲁木齐 card is incorrectly wider than the cards above. Recompose ONLY this last-row card so it has EXACTLY THE SAME WIDTH AND HEIGHT as the 重庆 card in the top-left and aligns to the same left and right edges as the FIRST COLUMN. Its left edge and height remain unchanged, its right edge must align with the right edges of 重庆、昆明、兰州. Resize/recompose the landmark and sky within that narrower card without squeezing text or distorting the cylindrical tower. Keep the exact city name “乌鲁木齐”, the exact caption “国际大巴扎观光塔”, “24°” and “多云” clear. The last two grid positions remain naturally empty. Do not add, remove or repeat any city. The final board is still a neat3-column4-row grid with only one card in row4. Keep all other9 cards exactly unchanged. Do not add presentation annotations or explanation. Output only the corrected complete bitmap preview, approximately1536x1152.
