# 南昌 · 滕王阁

- 工具：内置 Image Gen，transparent_background=true，一轮生成。
- 参考：docs/design/workbench-20261026/city-landmarks/east-preview-v1.png；同目录 landmark-beijing.png。
- 原生成路径：$CODEX_HOME\generated_images\01a177d2-afeb-7f12-b880-f8ab1547f28a\exec-5e3fd4b0-7939-44f0-a978-55e3ade87870.png
- 输出：assets/landmarks/source/nanchang.png；原样复制，SHA-256 与原图一致。
- 元数据：1905 × 825，RGBA，980,102 字节。
- Alpha：0–255；全透明 1,206,132 像素（76.744%）；半透明 365,469；全不透明 24。
- Alpha > 8 内容边界：[802,238,1890,825]，约 x=42.1%–99.2%，y=28.8%–100%。
- 核对：完整宽阔重檐阁楼、抬高石台与少量树木江面，未含文字/UI/天空；真实透明通道。主体建筑保持右侧，底部水面和雾边伸入左侧 50%，未达到严格左半全部透明；左半有 25,416 个非零 alpha 像素。顶部 25% 有 57 个 alpha=1 的极弱杂点。色彩较参考略暖，局部边缘有生成式细碎色边。未改像素，未改应用代码。

## Prompt

```text
Use case: stylized-concept.
Asset type: one standalone transparent PNG landmark layer for a weather card, approximately 1920 x 832 pixels, very wide canvas. Genuine transparent alpha background.

Reference image 1 is the East China card preview board: use ONLY the Nanchang / 滕王阁 card in row 3 column 1 for landmark identity and soft realistic illustration style. Do not copy a whole card or any sky, weather, words or UI.
Reference image 2 is the existing transparent Beijing landmark layer: match its overall canvas composition, right-side isolated building scale, subtle natural colors, realistic detail and softly vanishing base. Do not reproduce the Beijing building.

Primary subject: Nanchang's recognizable Tengwang Pavilion, a complete broad grand Chinese pavilion with multiple sweeping overhanging double-eave roofs, dark blue-gray / muted teal tiled roofs, restrained dark red columns and warm pale walls, a substantial broad pale-stone elevated terrace, and symmetrical lower architectural wings. It must be a wide monumental riverside pavilion with the characteristic stacked curving roof silhouette, NOT a narrow pagoda, NOT Temple of Heaven, NOT Leifeng Pagoda, and NOT a generic tall skinny tower. Three-quarter frontal view with realistic proportions and delicate architectural texture.

Composition: place the entire building group in the lower RIGHT HALF of the full transparent canvas. The complete top roof and every roof tip remain uncropped. All main visible content, including a little soft vegetation and a tiny hint of river water beneath the terrace, stays inside x=52%..98% and y=28%..97%. Main pavilion center around x=78%; the roof peak near y=30%; broad base near y=85%. Left 50% of the full canvas MUST remain completely transparent alpha=0 for text; top 25% MUST remain completely transparent. Preserve those large empty areas and do not crop the canvas to the subject. No tree, haze, river or reflection on the left half.

Lighting/style: soft natural daylight, refined low-saturation realistic illustration, blue-gray atmospheric integration, clear and readable building core with modest natural warm highlights. Do not pre-fade the entire asset; visibility will be controlled by CSS. Only the outer base and sparse trees / thin water strip softly dissolve into genuinely transparent mist, with no rectangular ground patch. Trees and water are secondary and minimal; the building dominates.

Transparency and exclusions: genuine RGBA transparency, all space outside the object is fully transparent. No painted black or white background, no checkerboard pixels, no sky, no sun, no clouds, no weather icons, no city skyline behind, no text or readable signs, no numbers, no labels, no frame, no card, no watermark. No cyan fringe or hard cutout edge. Bottom mist fades to transparent alpha before the canvas boundary. Produce this one Nanchang landmark asset only.
```
