# 石家庄 · 石家庄电视塔

- 工具：内置 Image Gen，transparent_background=true，一轮生成。
- 参考：docs/design/workbench-20261026/city-landmarks/north-northeast-preview-v1.png；同目录 landmark-beijing.png。
- 原生成路径：$CODEX_HOME\generated_images\01a177d2-afeb-7f12-b880-f8ab1547f28a\exec-a2d22604-0d3a-486b-b7a6-d2301707658a.png
- 输出：assets/landmarks/source/shijiazhuang.png；原样复制、未改像素；SHA-256 与原图一致。
- 元数据：1905 × 825，RGBA，467,965 字节。
- Alpha：0–255；全透明 1,414,891 像素（90.027%）；半透明 156,675；全不透明 59。
- Alpha > 8 内容边界：[1071,101,1877,825]，约 x=56.2%–98.5%，y=12.2%–100%。
- 左侧 50%：23 个 alpha=1 的极弱杂点，主要内容完全在右半。
- 视觉核对：完整天线塔顶、开放式锥形钢格构塔身与观景层可辨；基座少量绿地和柔雾；未含天空、文字或 UI，背景具真实透明通道。
- 剩余限制：塔顶约 y=12.2%，高于目标 y=28%；底部雾边靠近画布下边界，由接入端统一缩放控制。局部钢架空隙与外围仍有细碎低 alpha 色边，未据此宣称精确建筑复刻。按任务约定不为轻微外围杂点重做。未改应用代码。

## Prompt

```text
Use case: stylized-concept.
Create ONE standalone transparent RGBA PNG landmark layer for a weather card, about 1920 x 832 pixels, very wide canvas.

Reference image 1 is the northern-city preview board. Use ONLY the Shijiazhuang card in row 1 column 3 for landmark identity: Shijiazhuang Television Tower / 石家庄电视塔.
Reference image 2 is the existing Beijing transparent landmark layer. Use only its sparse right-hand composition, realistic low-saturation rendering and soft fading base. Do not reproduce its building or any UI.

Main subject: recognizable Shijiazhuang Television Tower, a tall OPEN STEEL LATTICE broadcasting tower. Its lower tower is exposed tapering steel-framework legs with diagonal cross-braces and open gaps, like a tall architectural space frame. Above the lattice shaft are distinct projecting observation / broadcasting platforms, and a slender antenna mast rising to the complete pointed top. Steel structure in cool slate blue-gray and soft ivory highlights. The tower must visibly be a lattice structure, NOT a solid concrete communication column, NOT a spherical Oriental Pearl Tower, NOT a twisting Canton Tower, and NOT a generic skyscraper. All open framework gaps are genuinely transparent so the future background can show through.

Composition: keep the complete tower and its antenna top uncut, standing in the lower RIGHT half of the full canvas. Tower center around x=78%, tip near y=29%, foot near y=88%. Broad steel base and a small patch of muted greenery beneath it remain within x=58%..96%. All visible scene content is inside x=52%..98%, y=28%..97%. The left 50% of the image and upper 25% are empty transparent alpha=0. Huge transparent negative space, no centered composition and no crop-to-subject. A few small subdued trees around its base suggest an urban park but must not hide the lattice structure. No other buildings, no water or wide ground strip.

Style: refined realistic architectural illustration, accurate-looking structural proportions, low saturation blue-gray natural daylight, delicate steel detail, soft natural colors. The landmark core is readable at normal opacity; UI will control fading. Small thin pale atmospheric mist at the base dissolves smoothly into actual alpha, not a rectangular ground patch. No heavy fog, no neon glow, no black/cyan halo or hard cutout border.

Background and exclusions: genuine alpha transparency everywhere except the actual tower, small greenery and slight edge mist. Transparent holes through the steel lattice. No sky, clouds, sun, weather, text, signage, labels, numbers, watermark, logos, card border, frame or UI. No painted black/white/checkerboard background. Output this one Shijiazhuang landmark only.
```
