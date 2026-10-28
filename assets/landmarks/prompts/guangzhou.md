# Guangzhou landmark source

- Asset: `assets/landmarks/source/guangzhou.png`
- Built-in image_gen, one generation, transparent_background=true.
- Original generated path: `$CODEX_HOME\generated_images\01a177d2-cccc-7a51-9c25-fb8539c802a8\exec-48f8c98b-718a-49ee-b13c-9592fc948d2e.png`
- Copied byte-for-byte; no pixel editing or resizing.
- Reference 1: `docs/design/workbench-20261026/city-landmarks/central-south-preview-v1.png`
- Reference 2: `docs/design/workbench-20261026/city-landmarks/landmark-shanghai.png`
- Actual size: 1905 × 825 pixels; RGBA.
- SHA-256: `89f73991b9b01592228d3767024dbf485d58eb085c12e9a2fc071029660e2716`

## Inspection

The Canton Tower is recognizable, with pinched waist, twisted steel lattice and a complete antenna. Cool blue-gray architectural detail matches the reference. Transparent background is real; no sky, labels or UI. Bottom mist and water fade into alpha. No correction generation was used because the landmark and alpha are valid.

- Alpha range 0–255.
- Fully transparent pixels: 85.5934%.
- Fully opaque pixels: 0.0150%.
- Alpha >16 bounding box: [883,45,1886,818], or x 46.35–99.00%, y 5.45–99.15%.
- Alpha >128 bounding box: [925,48,1864,796], or x 48.56–97.85%, y 5.82–96.48%.
- Left half nonzero alpha: 1.1958% of left-half pixels.
- Top quarter nonzero alpha: 0.8001% of top-quarter pixels.

Remaining limitations: generated tower is taller than requested, and the river base extends left of 50%; use a smaller right/bottom-anchored display scale to protect text and restore top clearance. There are faint cyan/blue edge fringes and tiny low-alpha stray pixels; the body is sufficiently legible. Keep this original source unchanged. These are visual decorative landmarks, not an accurate architectural survey. No application code, browser, integration or deployment was touched by this asset task.

## Final prompt

```text
Use case: stylized-concept.
Asset type: one production-ready transparent raster landmark overlay for a weather card.
Create a NEW separate Guangzhou Canton Tower landmark scene, approximately 1920 x 832, wide aspect ratio 2.3077:1. Deliver actual RGBA transparency, not an opaque black, white, checkerboard, sky, or gradient backdrop.
Input image 1 is ONLY the Guangzhou card in the second row left of a multi-city preview board: use it for the recognizable Canton Tower subject and soft atmospheric illustration. DO NOT reproduce or crop the preview board or any UI.
Input image 2 is ONLY the existing Shanghai transparent overlay: match its cool blue-gray low-saturation realistic illustrated architectural material, soft natural light, distant-scale composition and transparent layout. Replace ALL Shanghai landmarks with Guangzhou; do not include any Shanghai tower.
Subject: one unmistakable Canton Tower (广州塔), an elegant very tall slender twisted hyperboloid steel lattice tower, wide at base and upper body, distinctly pinched narrow waist, tightly crossed curved metal lattice, observation floors integrated inside the upper lattice, and its COMPLETE long thin antenna reaching upward. The tower must retain its real slender proportions. Add only a few very low modest riverside city buildings and a narrow sliver of Pearl River water, subordinate to the tower. No competing skyscraper.
Composition: the LEFT 50 percent of the entire canvas must be fully transparent for weather text. The top 24 percent must be transparent. All subject material in the bottom-right area approximately x=52% to 98%, y=25% to 97%. Position the Canton Tower around x=76% with its antenna at y=27% and base around y=86%. Low city strip from x=57% to94% and y=73% to88%, with restrained river reflection/mist at y=87% to95%. Keep the entire tower and antenna visible, without clipping. Leave natural transparent margins. Do not enlarge the landmark to fill the whole canvas.
Rendering: finely detailed, quiet photorealistic architectural illustration, blue-gray steel with muted pale highlights, subtle desaturated greenery, gentle believable daylight. Clear recognizable silhouette, good material detail, no oversaturated tourism-poster colors. Full usable subject opacity; CSS will later set default and hover opacity. Very soft natural mist feathering at bottom and side base, gradual alpha fade with no hard rectangular ground edge and no giant glowing oval.
Absolute exclusions: NO sky, clouds, sun, weather graphics, text, city names, digits, labels, UI cards, rounded card rectangle, frame, watermark, black matte, white matte, checkerboard pattern, complete rectangular ground plane. Only the Canton Tower and small riverfront cluster on genuinely transparent background.
```
