# 成都 · 安顺廊桥

## 产物与来源

- 资产：`$PROJECT_ROOT/assets/landmarks/source/chengdu.png`
- 内置 image_gen，transparent_background=true；一次初始生成、一次构图修正。
- 原始最终文件：`$CODEX_HOME/generated_images/01a177d2-91e6-7ea0-b3a9-913448893b53/exec-113ed4a4-fdd5-4457-9957-dec680bf360c.png`
- 初次生成文件：`$CODEX_HOME/generated_images/01a177d2-91e6-7ea0-b3a9-913448893b53/exec-41ff723c-32fe-48c9-85ba-d0a998f7f8dd.png`
- 参考1：`docs/design/workbench-20261026/city-landmarks/west-preview-v1.png`，成都卡片主体和风格。
- 参考2：`docs/design/workbench-20261026/city-landmarks/landmark-hangzhou.png`，透明布局和小景尺度。
- SHA-256：`8A976B4DC84F09BBE213129D08924F7E32471171B3DB0F0DFF5381FBC2D35CFD`
- 直接复制生成PNG，未裁剪、抠图或改像素。本任务未编辑应用代码。

## 检查

- 实际1905×825 px，RGBA，913915字节。
- alpha范围0—255；完全透明像素76.40385%。
- 左半区域完全透明95.97021%；顶部35%完全透明99.99927%。
- alpha>16边界框[795,393,1905,825]，约x=41.73%—100%、y=47.64%—100%。
- alpha>128边界框[819,394,1876,806]。
- 最底行141像素alpha>16，最右列22像素alpha>16。
- 桥梁与两端亭楼完整、三孔桥拱可识别，有少量河面和柔雾，无文字、UI、天空或天气图标。
- 已针对首版过宽及上方孤立杂点做一次修正；孤立大杂点已消除。
- 剩余限制：左下雾、植被与河面仍进入41.7%—50%区间，没有完全满足左半全部透明；柔雾/倒影在右边和底边仍有少量接边。屋顶完整但窗口暖光和倒影比要求更强。地标细部属于生成式概念插画，未逐项实景核验。
- 接入方应注意上述实际包围范围；可通过图层布局进一步压缩到右侧，避免天气文字覆盖，不应将这份检查写成“布局完全通过”。

## 初始完整提示词

Use case: stylized-concept.
Asset type: one transparent PNG architectural landmark overlay for a professional weather card, Chengdu — Anshun Bridge (安顺廊桥).

Generate a NEW standalone transparent architectural illustration. Reference image 1 is ONLY the Chengdu card subject/style guide from the top-middle position of the western-city preview board; do not reproduce the board, typography or card. Reference image 2 is ONLY the transparent Hangzhou overlay's framing, quiet realistic rendering and right-bottom placement; do not draw Hangzhou's pagoda.

Canvas: wide landscape, approximately 1920×832. Actual alpha transparency, not a colored background. The entire left 50% and upper 32% must be completely empty transparent pixels. Position the complete bridge and a small piece of reflective river in the right half, approximately x=52%–98%, y=35%–97%. Keep clear transparent margin on every outer edge; do not crop any roof or bridge end. It should occupy the same quiet right-bottom island of imagery as the Hangzhou layer. Keep all imagery to the right; this is essential for city and temperature text on the left.

Subject: a recognizable traditional Chinese roofed Anshun Bridge in Chengdu, viewed from a slightly oblique riverbank viewpoint. The long bridge spans horizontally over the river, multiple visible broad masonry arches beneath a continuous traditional tiled-roof covered gallery, slightly taller pavilion roofs toward both ends, delicate upturned eaves, restrained dark reddish-brown timber and blue-grey slate roof details. Show the full bridge across the image island, with clear space through the arches, some river reflection and only a tiny amount of riverbank vegetation at the ends. Architecture must read as a long inhabited covered bridge, not a pagoda, generic temple, separate standalone pavilions, or suspension bridge. Preserve the relaxed scale of the Chengdu reference.

Style: refined, detailed, softly realistic architectural illustration with realistic material texture and correct proportions, low saturation cool blue-grey palette, muted natural timber. Light is gentle and even, no dramatic glow, no golden floodlights. Soft translucent mist curls lightly along the river and around the bridge feet; Chengdu's mist can be slightly denser, but roofline and arches remain clearly recognizable. The small river patch and mist dissolve organically into real transparent pixels, with no rectangle, straight horizon, hard cut edge or solid ground slab. The structure itself has enough opacity to remain readable when later CSS applies 24% default opacity or 60% hover opacity; do not pre-fade the whole artwork.

Must have NO sky, sun, moon, clouds as weather icons, rainfall, snowfall, stars, mountains or distant skyline; no black, white, blue, grey or checkerboard background; no text, Chinese characters, numbers, labels, border, rounded frame, watermark, card, UI, shadows outside the object, map, people or flags. Output only this one complete transparent landmark layer.

## 构图修正完整提示词

Use case: precise-object-edit. Correct ONLY the composition of the attached transparent Anshun Bridge asset. Keep its existing recognizable complete Anshun covered bridge, all three visible bridge arches, blue-grey roof, muted reddish timber, soft river reflection and delicate bottom mist. Keep actual transparent alpha.

The existing landscape island is much too wide and reaches far into the left text zone. Uniformly REDUCE the ENTIRE bridge, trees, mist and river island to about TWO THIRDS of its current size without cropping or distortion, then position it in the LOWER RIGHT so the whole visible non-transparent island fits approximately x=52%–97%, y=50%–95% of the SAME wide canvas. The leftmost visible mist or vegetation must be to the right of x=50%; absolutely every pixel of the LEFT HALF must be fully transparent. Absolutely every pixel in the top35% must be fully transparent. Remove the isolated round stray mark near x=23%, y=16% completely. Do not add new objects or a background.

Keep the complete bridge from end to end with transparent margins at the right and bottom, no cropped vegetation, no cropped reflection. The clear architecture should not be pre-faded, while the mist and edges should fade naturally to transparent. A smaller quiet architectural cameo, suitable behind weather-card UI, matching the right-bottom scale of the Hangzhou asset. Retain the same wide aspect around1920x832. No text, numbers, sky, sun, moon, weather, colored backdrop, black matte, checkerboard, UI, hard edge or watermark.
