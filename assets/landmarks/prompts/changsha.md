# Changsha landmark source

- Asset: `assets/landmarks/source/changsha.png`
- Built-in image_gen, one generation, transparent_background=true.
- Original generated path: `$CODEX_HOME\generated_images\01a177d2-cccc-7a51-9c25-fb8539c802a8\exec-c33b9fd2-9da7-4f86-8465-cc4e3b28e287.png`
- Copied byte-for-byte, no pixel editing or resizing.
- Reference 1: `docs/design/workbench-20261026/city-landmarks/central-south-preview-v1.png`
- Reference 2: `docs/design/workbench-20261026/city-landmarks/landmark-beijing.png`
- Actual size: 1905 × 825 pixels; RGBA.
- SHA-256: `8e46728828b39c6859cb42dc30ba8ac895adb3ef0b841e119608660935122ccd`

## Inspection

The scene clearly depicts a traditional layered pavilion with side pavilions on a stone-block battlement city wall. Textured wall is readable and the whole has the correct pavilion-on-wall silhouette, rather than a standalone pagoda. Subdued roofs and blue-gray masonry, restrained trees, soft fading base. Real alpha transparency; no sky, labels or UI. No corrective generation used.

- Alpha range 0–255.
- Fully transparent pixels: 75.0656%.
- Fully opaque pixels: 0.0013%.
- Alpha >16 bounding box: [798,272,1896,814], or x 41.89–99.53%, y 32.97–98.67%.
- Alpha >128 bounding box: [810,276,1885,799], or x 42.52–98.95%, y 33.45–96.85%.
- Left-half nonzero alpha: 3.5667% of left-half pixels.
- Top 28% nonzero alpha: 0.0902% of that region's pixels, mainly tiny stray low-alpha pixels.

Remaining limitations: architecture has good top clearance, but hill/trees and mist extend farther left than the requested 52% boundary. Use a smaller right/bottom-anchored display scale to protect the weather copy. There are faint colored low-alpha edge fringes and tiny stray pixels. Preserve the original source. This is a decorative landmark illustration, not a measured architectural reconstruction. No application code, browser, integration or deployment was touched.

## Final prompt

```text
Use case: stylized-concept.
Asset type: one independent transparent architectural landmark layer for a weather card, approximately 1920 x 832 wide canvas, aspect ratio 2.3077:1.
Create a NEW isolated distant scene of Changsha Tianxin Pavilion (长沙天心阁), genuinely transparent RGBA background.
Reference image 1 is a multi-city preview board. Use ONLY Changsha card at row 1 column 3 for landmark subject and soft realism. Do not reproduce the board or any sky, weather, text or UI. Reference image 2 is a transparent Beijing landmark layer; match its refined low-saturation architectural rendering, cool blue-gray shading, subtle warm accents, compact lower-right layout and soft fading base, but include NO Beijing building.
Primary landmark: traditional Tianxin Pavilion perched ON a substantial old gray stone city wall. The recognisable relationship between a low multi-eaved traditional wooden pavilion and the masonry battlement wall is essential. The central pavilion has muted reddish-brown columns, layered gray and subdued golden-brown tiled roofs with upturned eaves, and lower side wings along the wall. It must look like the real historic pavilion-on-wall composition, NOT an isolated pagoda, tall tower or Yellow Crane Tower. Show clear textured stone block wall base and a few small trees, restrained natural hill/ground at the foot.
Composition: modest distant landmark group entirely in lower-right. LEFT HALF and TOP 28% of the entire canvas must be absolutely transparent. Pavilion roof tip around x=77%, y=34%; pavilion and wall occupy x=59%..94%, y=34%..87%. A few small trees and very thin soft mist at base may extend only x=53%..97%, y=70%..95%. Do not scale the architecture to fill the canvas. Keep a genuine transparent margin around the scene; no clipping of eaves or wall.
Style: finely detailed realistic architectural illustration, quiet blue-gray and muted cool greens with gentle warm roof accents, soft natural daylight, photographic materials but subtly painterly atmosphere. Preserve normal usable subject opacity because CSS later controls idle/hover opacity. Feather only the small hill/base into subtle mist and transparent alpha; no hard rectangular ground and no large opaque glowing oval.
Exclude all sky, clouds, sun, weather symbols, text, plaque lettering, city names, numbers, labels, UI, cards, borders, frames, watermarks, black or white background, checkerboard pattern, bright saturated tourist-poster colors. Only Tianxin Pavilion on its old stone wall and small trees, on actual transparency.
```
