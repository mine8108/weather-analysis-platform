# 太原 · 双塔寺

- 工具：内置 Image Gen，transparent_background=true，一轮生成。
- 参考：docs/design/workbench-20261026/city-landmarks/north-northeast-preview-v1.png；同目录 landmark-beijing.png。
- 原生成路径：$CODEX_HOME\generated_images\01a177d2-afeb-7f12-b880-f8ab1547f28a\exec-ea4dce99-8acc-40a1-aab7-21b0b810d6d6.png
- 输出：assets/landmarks/source/taiyuan.png；原样复制、未改像素；SHA-256 与原图一致。
- 元数据：1905 × 825，RGBA，930,374 字节。
- Alpha：0–255；全透明 1,225,062 像素（77.949%）；半透明 346,388；全不透明 175。
- Alpha > 8 内容边界：[838,123,1905,825]，约 x=44.0%–100%，y=14.9%–100%。
- 视觉核对：两座细长灰砖塔接近等高，顶端完整，密檐砖层、塔窗与基座寺院树木清楚，未画成巨大木构楼阁；未含天空、文字或 UI；背景具真实透明通道。
- 剩余限制：树木与雾边伸到 x≈44%，左半有 17,762 个非零 alpha 像素；塔尖高于目标 y=28%，底部雾边贴近画布下边界。主体为生成式概念复现，未逐项核验建筑细节；少量外围色边保留。接入端可统一约束图层尺寸。未改应用代码。

## Prompt

```text
Use case: stylized-concept.
Create one standalone transparent RGBA PNG landmark layer for a weather card, approximately 1920 x 832 pixels, very wide canvas.

Reference image 1 is the northern-city card preview: use ONLY Taiyuan / 太原 in row 2 column 1 for the identity of Twin Pagoda Temple / 双塔寺. IMPORTANT correction to this reference: the two towers in the new asset must be almost the same height and at the same visual scale, not a large foreground tower with a tiny distant tower.
Reference image 2 is the Beijing transparent layer: use only its right-side placement, low-saturation realistic style and soft atmospheric base, not its building.

Subject: the two recognizable slender octagonal BRICK PAGODAS of Taiyuan's Twin Pagoda Temple (Yongzuo Temple). Two similar tall gray-brown brick towers, nearly equal height (difference less than 3%), standing on the same ground plane, both entirely visible. Dense stacked courses with approximately thirteen subtle projecting brick-cornice tiers and small dark recessed openings, tapering gently toward delicate pointed finials. The geometry must read as slender historic masonry brick towers, not large wooden pavilion towers, not broad sweeping-roof palace buildings, not two dramatically different sizes. No red-column multistorey pavilions. Preserve credible brick texture and restrained stone color.

Composition: both complete towers occupy the lower RIGHT HALF of the full wide transparent canvas. Tower centers around x=71% and x=85%, tops near y=30% and y=31%, bases near y=86%; towers stand close enough to read as a pair but do not overlap. Include only a little low dark green-gray tree canopy and a modest temple stone base between their feet, ending in a small patch of soft mist. Entire visible group stays within x=54%..98%, y=28%..97%. All left 50% and top 25% must be completely transparent. Do not enlarge one tower to add perspective; front or mild three-quarter view keeps the heights visually comparable. No water or wide ground rectangle.

Style: calm low-saturation blue-gray realistic illustration, gentle natural daylight, softly aged brick surface, subtle warm highlights, clear fine detail on the towers. The landmark core remains readable at normal opacity; overall opacity will be controlled in CSS. Bottom greenery and base dissolve through a thin soft mist to true transparent alpha, with no hard crop or opaque rectangular ground.

Genuine RGBA transparent background outside the actual pair and base. No sky, sun, clouds, weather, text, city name, labels, signage, number, watermark, logo, UI or frame. No black/white painted background or checkerboard. No neon or colored edge halo. Produce only this one Taiyuan landmark asset.
```
