# Haikou landmark source

- Asset: `assets/landmarks/source/haikou.png`
- Built-in image_gen, one generation, transparent_background=true.
- Original generated path: `$CODEX_HOME\generated_images\01a177d2-cccc-7a51-9c25-fb8539c802a8\exec-d43842db-3e88-49ef-86c7-4e23982d7a25.png`
- Copied byte-for-byte, no pixel editing or resizing.
- References: `docs/design/workbench-20261026/city-landmarks/central-south-preview-v1.png` and `docs/design/workbench-20261026/city-landmarks/landmark-shanghai.png`.
- Actual size: 1905 × 825 pixels; RGBA.
- SHA-256: `f0ed94a4946459f40fd591836e45c5045e5b0b1ed9e690585c31b804fbcca4c2`

## Inspection

Two complete main pylons, clear fan-shaped diagonal stay cables, low road deck, a narrow riverbank and reflected water. The cable-stayed bridge identity is visible; no sailboats or suspension catenary. Real transparency, no sky, text or UI. No corrective generation used.

- Alpha range 0–255.
- Fully transparent pixels: 79.0979%.
- Fully opaque pixels: 0.0070%.
- Alpha >16 bounding box: [784,284,1871,812], or x 41.15–98.22%, y 34.42–98.42%.
- Alpha >128 bounding box: [808,285,1854,791], or x 42.41–97.32%, y 34.55–95.88%.
- Left-half nonzero alpha: 3.2150% of left-half pixels.
- Top 28% nonzero alpha: 0.0048% of that region's pixels.

Remaining limitations: bridge approach and water extend farther left than the requested 53% boundary; the integration layer should apply its unified right/bottom anchored scale. Water is slightly brighter blue than the muted target, and fine cables show low-alpha cyan/blue fringes against a black transparency viewer. Minor stray low-alpha pixels were only recorded. This is a decorative landmark illustration, not an engineering reconstruction. No application code, browser, integration or deployment was touched.

## Final prompt

```text
Use case: stylized-concept.
Asset type: one standalone transparent landmark overlay for a weather card, wide canvas approximately 1920 x 832, aspect ratio 2.3077:1.
Generate a NEW isolated distant architectural view of Haikou Century Bridge (海口世纪大桥) with actual RGBA transparency.
Reference image 1 is a multi-city design preview: use ONLY the Haikou card at row 2 column 3 for the landmark subject and lighting. Do not reproduce the board, card, sky, weather, city labels or temperature. Reference image 2 is an existing Shanghai transparent overlay: use only its restrained blue-gray realistic architectural rendering, subtle water reflection, soft mist feathering and lower-right placement. Do not include Shanghai buildings.
Subject: a true TWO-PYLON CABLE-STAYED BRIDGE spanning a small sliver of river. Two tall pointed pale-gray concrete pylons, one slightly nearer/larger than the other in a natural three-quarter side perspective, support a low long gently horizontal bridge deck with fine clearly visible FAN-SHAPED DIAGONAL STAY CABLES radiating from each pylon to deck. The elegant double tower/cable silhouette must remain complete. Include only modest distant low riverbank detail and a narrow quiet cool-blue water reflection. This must be the cable-stayed Century Bridge, not a suspension bridge: NO sagging main cable or hanging vertical cable grid, no sailboats, no ships, no extra pagodas or skyscrapers.
Composition: compact distant landmark group in bottom-right. Entire left 50% of canvas and upper 28% are empty true transparency. Confine bridge and water approximately x=53%..97%, y=34%..95%. Main tower tips near y=35%; bridge deck around y=76%; minimal water reflection at y=82%..93%. Keep all pylons and cable fans unclipped with transparent margins. Do not let the bridge span the whole canvas. No close-up.
Style: finely detailed softly realistic architectural illustration; low-saturation blue-gray bridge and water, pale highlights, soft natural daylight. Crisp enough cable silhouette, quiet atmosphere, no dramatic night lights. Usable normal opacity of bridge structure; CSS later controls default and hover. Gently feather the narrow water and riverbank edges into transparent alpha with delicate low mist, no opaque oval platform and no hard rectangular water edge.
Exclude all sky, clouds, sun, weather symbols, rain, text, labels, digits, UI, frames, borders, cards, watermark, black/white matte and checkerboard pattern. Only the bridge with very limited water/shore on real transparency.
```
