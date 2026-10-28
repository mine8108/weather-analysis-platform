# 天津 · 天津之眼

- 工具：内置 Image Gen，transparent_background=true；初次生成后针对轮圈内透明空隙和水面范围进行一次修正。
- 参考：docs/design/workbench-20261026/city-landmarks/north-northeast-preview-v1.png；同目录 landmark-beijing.png。
- 最终原生成路径：$CODEX_HOME\generated_images\01a177d2-afeb-7f12-b880-f8ab1547f28a\exec-0c2bfb2f-66e2-4029-9813-edf289237af8.png
- 初次生成路径：$CODEX_HOME\generated_images\01a177d2-afeb-7f12-b880-f8ab1547f28a\exec-fe5a53ef-9b24-49b6-aadf-7bc53fcb57fa.png
- 输出：assets/landmarks/source/tianjin.png；最终原图直接复制，未改像素；SHA-256 与原图一致。
- 元数据：1905 × 825，RGBA，1,105,907 字节。
- Alpha：0–255；全透明 1,190,509 像素（75.75%）；半透明 380,926；全不透明 190。
- Alpha > 8 内容边界：[974,133,1883,792]，约 x=51.1%–98.8%，y=16.1%–96.0%。
- 左侧 50%：仅 61 个 alpha=1 的极弱杂点，主要主体与水面不越中线。
- 视觉核对：完整轮圈、辐条与桥上 Y 形支架；桥梁横梁和桥墩可见，跨河关系成立；无文字/UI/天气。真实透明通道。
- 剩余限制：轮圈内部仍有部分蓝灰半透明残留与细碎彩边，未达到所有辐条间隙完全清透；轮圈顶部约 y=16.1%，比目标偏高，顶部 25% 未全空。当前仅交付素材，由主任务决定显示缩放和是否接受此透明细节。未改应用代码。

## Initial prompt

```text
Use case: stylized-concept.
Create one standalone TRANSPARENT RGBA PNG landmark overlay, about 1920 x 832 pixels, wide canvas. This is the Tianjin Eye / 天津之眼 for a weather card.

Reference 1: northern-city preview board, use ONLY the Tianjin card in row 1 column 2 for landmark identity and gentle realistic rendering.
Reference 2: the Beijing transparent landmark image, use ONLY its right-aligned transparent-canvas composition and softly feathered base. Do not copy the Beijing building, any card, sky, lettering, clouds or weather.

Subject: the recognizable Tianjin Eye, a huge circular white-spoked observation wheel with small muted red passenger capsules around the rim, physically supported by the distinctive white triangular / Y-shaped bridge-mounted supports on Yongle Bridge across the Hai River. Show the complete ring and every capsule, the wheel's central hub and delicate radial spokes. The white structural supports must connect to a visible horizontal river bridge deck and solid bridge piers directly beneath. It is a large wheel built ON A CROSS-RIVER BRIDGE, not an isolated amusement-park wheel. A slim strip of calm blue-gray river water beneath the bridge and tiny low riverbank greenery may complete the scene; keep them minimal. No city skyline or extra buildings.

Composition: isolate the entire small scenic group inside the LOWER RIGHT of the full canvas. The left 50% of the whole image must be truly empty transparent alpha=0. Keep all visible material, INCLUDING ALL WATER AND MIST, to the right of x=56%. Wheel center about x=78%, y=55%; circular wheel top around y=28%, bottom around y=80%, with correct circular perspective. Bridge extends only from x=58% to x=97%, around y=82%; piers and a thin water strip beneath end above y=96%. Leave transparent margins around top, bottom and right. Do not expand the lake or water patch across the centerline. Preserve huge transparent empty space on the left and top rather than cropping the canvas to the landmark.

Style: refined low-saturation realistic illustration, gentle natural daylight, soft blue-gray and pale ivory structure, subtle gray-red capsules, clean legible details. The full structure remains visually clear; opacity will be controlled later in CSS. Light thin mist only at the bottom fades naturally into true transparency, with no hard rectangular base and no colored edge fringe.

Transparency: genuinely transparent background, including the empty areas INSIDE the wheel between the spokes, through the triangular support gaps, and beneath the bridge between its piers. No sky or colored fill behind the wheel. No black or white painted background, no checkerboard pattern, no UI, words, numbers, logo, watermark, frame, weather icons, sun, clouds, or card borders. Produce one Tianjin asset only.
```

## Final correction prompt

```text
Use case: background-extraction / precise-object-edit.
Edit the attached Tianjin Eye transparent asset. Preserve the recognizable complete circular wheel, small passenger capsules, thin spokes, white Y-shaped supports, the river bridge deck and its piers, and a very narrow river strip at the bottom. Preserve its realistic blue-gray visual style.

REQUIRED FIX: remove ALL remaining sky-like filled background from INSIDE the wheel. The spaces between the thin individual spokes must be genuinely fully transparent alpha=0, just like outside the wheel. No translucent blue disk, no pale blue patches, no white fill, no gray fill, no fuzzy colored noise. Only actual metal spokes remain visible across this empty circular space. Gaps in the Y-shaped supports and gaps between bridge piers must also reveal transparent alpha. Keep clean natural antialiasing only at the actual structure's edges, not a broad colored halo. No sky or background anywhere.

Also scale the complete scenic group down slightly within the same full wide 1905 x 825 transparent canvas: keep the highest capsule below y=26%, the bottom soft mist above y=97%, and keep the entire image's left 52% absolutely transparent, including all river, trees and mist. Place all visible content in x=55%..98%. Preserve the entire wheel uncropped and the visible bridge below it. Water must be a small thin strip under the bridge, not a large foreground lake. Do not add any content. Maintain huge empty transparent canvas at left and above.

Do not paint a black/white/checkerboard background. Output genuine RGBA transparency. No text, UI, frame, logos, clouds, sun or extra skyline. Produce only this corrected Tianjin asset.
```
