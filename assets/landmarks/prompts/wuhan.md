# Wuhan landmark source

- Asset: `assets/landmarks/source/wuhan.png`
- Built-in image_gen, one generation, transparent_background=true.
- Original generated path: `$CODEX_HOME\generated_images\01a177d2-cccc-7a51-9c25-fb8539c802a8\exec-bb776675-b9bc-4878-9aca-2032390f20cb.png`
- Copied byte-for-byte, no pixel editing or resizing.
- Reference 1: `docs/design/workbench-20261026/city-landmarks/central-south-preview-v1.png`
- Reference 2: `docs/design/workbench-20261026/city-landmarks/landmark-beijing.png`
- Actual size: 1905 × 825 pixels; RGBA.
- SHA-256: `27047e3c00a76b10af39b23780e7390fed38a211a07bc3b91c028613eb82266a`

## Inspection

Recognizable Yellow Crane Tower with five principal golden-yellow roof tiers/upturned eaves, subdued dark red structure, pale terraces and small rocky tree-covered hill. No sky, labels or UI. Real alpha transparency and soft base mist. No corrective generation used.

- Alpha range 0–255.
- Fully transparent pixels: 77.1722%.
- Fully opaque pixels: 0.0010%.
- Alpha >16 bounding box: [923,178,1905,815], or x 48.45–100.00%, y 21.58–98.79%.
- Alpha >128 bounding box: [935,180,1884,793], or x 49.08–98.90%, y 21.82–96.12%.
- Left-half nonzero alpha: 0.8619% of left-half pixels.
- Top 28% nonzero alpha: 0.5724% of that region's pixels.

Remaining limitations: the rooftop starts at about y=21.6% rather than 28%, and the soft hill base reaches slightly left of 50% and touches the right edge. Display it slightly smaller with a right/bottom anchor to restore clearance. A low-alpha reddish fringe is visible around roof edges against the black transparency viewer; check over the actual sky background. There are tiny low-alpha stray pixels. Preserve this source. This is a decorative architectural illustration, not a precise survey. No application code, browser, integration or deployment was touched.

## Final prompt

```text
Use case: stylized-concept.
Asset type: one standalone transparent raster landmark overlay for a weather card, approximately 1920 x 832, wide 2.3077:1 canvas.
Create a NEW transparent isolated distant view of Wuhan Yellow Crane Tower (黄鹤楼). True alpha transparency, no opaque background.
Reference image 1 is a multi-city preview sheet: use ONLY the Wuhan card, row 1 column 2, as the subject and atmosphere reference. Do not reproduce the sheet, cards, sky, city labels, weather or numbers.
Reference image 2 is the existing Beijing Temple of Heaven transparent layer: use ONLY its blue-gray low-saturation realistic architectural illustration style, delicate detailing, natural light, bottom-right placement and soft feathered base. Do not include the Temple of Heaven.
Subject: recognizably Yellow Crane Tower with FIVE main stories and FIVE broad golden-yellow tile roofs with graceful Chinese upturned eaves, deep muted red/brown columns and pale stone terraces. A classical multi-story pavilion, not a narrow Buddhist pagoda. Preserve the distinctive widening lower roof tiers. Muted warm yellow roofs within an overall cool blue-gray style. Small hill and just a few restrained low trees around the base, only tiny subordinate foreground surface, fading in soft mist.
Composition is critical: leave the entire LEFT 50% canvas fully transparent and the TOP 28% fully transparent. Treat the scene as a modest small distant landmark group in the lower-right, not a full-canvas close-up. The tower's roof tip begins around y=30%, never near the canvas top. Tower centered around x=77%, width about 23% of canvas and height about 52%. All hill, terrace, trees and mist confined approximately x=53%..97%, y=70%..96%. Complete tower and all eaves visible. Natural transparent margins, especially between scene and frame borders.
Rendering: finely detailed softly realistic architectural illustration, restrained blue-gray shadows and warm pale yellow roofs, soft natural daylight, delicate subdued greens. Normal usable opacity in the architecture; CSS will later control idle and hover opacity. Base and sides fade naturally with alpha into delicate low mist, without hard edges or a broad glowing opaque disk.
No sky, clouds, sun, weather, text, lettering, plaque characters, UI, cards, borders, rounded frame, city name, digits, watermark, black/white matte, checkerboard or large rectangular ground. Only the isolated Yellow Crane Tower and very small hill/trees group on real transparency.
```
