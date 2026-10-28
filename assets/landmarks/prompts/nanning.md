# Nanning landmark source

- Asset: `assets/landmarks/source/nanning.png`
- Built-in image_gen with transparent_background=true: one initial generation and two targeted tier-count corrections.
- Final original path: `$CODEX_HOME\generated_images\01a177d2-cccc-7a51-9c25-fb8539c802a8\exec-e7825c7c-6540-4d16-a2df-46f4345f6874.png`
- Initial path: `$CODEX_HOME\generated_images\01a177d2-cccc-7a51-9c25-fb8539c802a8\exec-7e4ca6dc-ecba-4173-80cb-2af499ca0f89.png`
- First correction path: `$CODEX_HOME\generated_images\01a177d2-cccc-7a51-9c25-fb8539c802a8\exec-e1ae3de5-4562-4d43-94a8-e016e6fd4ad1.png`
- Final copied byte-for-byte, no pixel editing or resizing.
- References: `docs/design/workbench-20261026/city-landmarks/central-south-preview-v1.png` and `docs/design/workbench-20261026/city-landmarks/landmark-beijing.png`.
- Actual size: 1905 × 825 pixels; RGBA.
- SHA-256: `fa939bebd556bec8f6b33dea7620fd6fb153f21f724594fc920bd265f9ccee22`

## Inspection

The initial image had seven visible tiers; the first correction produced eight. The final correction visibly contains nine distinct roof/eave tiers, a complete pointed finial, a traditional pale-stone pagoda body and a small wooded hill with low mist. The final nine principal roof bands can be counted near y=193,242,288,333,381,427,474,519,565 in the 825-pixel canvas. Real transparency; no sky, labels or UI.

- Alpha range 0–255.
- Fully transparent pixels: 82.9074%.
- Fully opaque pixels: 0.0074%.
- Alpha >16 bounding box: [950,84,1905,825], or x 49.87–100.00%, y 10.18–100.00%.
- Alpha >128 bounding box: [958,96,1897,822], or x 50.29–99.58%, y 11.64–99.64%.
- Left-half nonzero alpha: 0.0213% of left-half pixels.
- Top 27% nonzero alpha: 1.6762% of that region's pixels.

Remaining limitations: tower is higher than requested and the soft base reaches the right and bottom canvas boundaries. The integration layer should apply its unified right/bottom anchored scale. Minor low-alpha fringe/stray pixels were only recorded. The asset is a decorative landmark illustration rather than a surveyed architectural reconstruction. No application code, browser, integration or deployment was touched. No further generation after this final result.

## Initial prompt

```text
Use case: stylized-concept.
Asset type: one production transparent landmark overlay for a city weather card, wide 1920 x 832 approximate dimensions, 2.3077:1 aspect ratio.
Create a NEW independent scene of Longxiang Pagoda on Qingxiu Mountain, Nanning (南宁青秀山龙象塔), on a genuinely transparent RGBA canvas.
Reference image 1 is a multi-city design preview. Use ONLY the Nanning card (row 2 column 2), for the traditional pagoda landmark and wooded mountain appearance. Do not reproduce any card, sky, text or weather. Reference image 2 is the existing Beijing transparent landmark asset; use its fine blue-gray realistic illustrated architectural finish, subdued daylight, naturally feathered mist base and bottom-right layout, but no Beijing building.
Subject: the distinctive NINE-STORY traditional Longxiang Pagoda: a tall slim, tapering octagonal classical Chinese pagoda, nine clearly separated stacked tiled roof/eave tiers with gracefully upturned corners, restrained warm-brown/gray roofs, pale gray stone body with dark openings, a small pointed finial on top. It is NOT a modern television or broadcasting tower, NOT a skyscraper, NOT a broad pavilion. Keep the entire finial and tower visible. At its foot include only a small wooded slope of Qingxiu Mountain, desaturated green trees, very modest stone base and a touch of low soft mist. Trees are low and subordinate.
Composition: put a SMALL distant landmark group only in lower-right. Preserve entire left 50% and upper 27% of the wide canvas as actual transparent empty space. Pagoda centered at x=77%, from y=30% to85%, about 12% canvas width; the wooded base only x=56%..96%, y=77%..94%. Keep transparent margin around every side, no clipping. Do not turn it into a close-up or large island covering the canvas.
Style: finely detailed softly realistic architectural illustration, low-saturation cool blue-gray shadows, muted pale warm masonry and subdued green foliage, gentle natural light. Clear nine-tier silhouette and intricate roof detail. Architecture has normal useful opacity; CSS later handles default and hover. Soft alpha fade at the base and sides, without a broad opaque white oval or hard rectangular ground edge.
No sky, clouds, sun, weather effects, text, plaque lettering, city labels, digits, UI, card frame, rounded rectangle, watermarks, black/white background, checkerboard texture or saturated tourist-poster colors. Only this isolated pagoda with small wooded hill on true transparency.
```

## First correction prompt

```text
Use case: precise-object-edit.
Edit the attached transparent Nanning Longxiang Pagoda asset. Preserve the transparent wide canvas, cool blue-gray architectural illustration style, lower-right location, existing wooded hill, soft mist, lighting and colors. Change ONLY the pagoda to have EXACTLY NINE separate occupied stories and EXACTLY NINE complete roof/eave tiers. The current image has too few tiers. This is a critical landmark correction.

Count the eave tiers from top to bottom 1,2,3,4,5,6,7,8,9, visually separated by narrow wall/window bands. Show a complete pointed finial, then the small highest roof, then EIGHT progressively wider distinct roofs below it. Every roof has graceful upturned corners. There must be NINE clearly visible tiers, all above the stone base and unobstructed by trees. Keep the overall tower within the same general height, by making each individual story slightly shorter. Do not add written numerals or labels. Keep the traditional octagonal pagoda form with pale gray stone body and restrained warm-brown/gray roofs, not a modern tower or pavilion.

Output one approximately 1920 x 832 genuine transparent RGBA image with the left half empty and transparent, top largely transparent, scene only at lower-right. Preserve normal subject opacity and naturally feathered base. No sky, sun, clouds, weather, text, plaques, UI, background color, checkerboard, black/white matte or framing. Nine roofs is the only substantive correction; do not enlarge the scene or alter the subject into another landmark.
```

## Final correction prompt

```text
Use case: precise-object-edit.
Make ONE exact architectural correction to this transparent image of Nanning Longxiang Pagoda: the current tower has EIGHT visible roofs. Add exactly ONE extra complete story and roof band between the existing lowest roof and the second-lowest roof. Preserve every other roof. The final pagoda must have NINE visible roof tiers, each separated by a window/story band. This extra story should be inserted near the lower third; shorten the existing story heights slightly if needed to keep the overall tower size similar.

Please count the finished roof edge silhouettes from top to bottom before delivering: first uppermost cap roof, second roof, third roof, fourth roof, fifth roof, sixth roof, seventh roof, eighth roof, ninth lowest roof over the entry floor. Nine roofs must be visibly distinct. Keep the existing finial separate from this count. No labels or numbers.

Preserve the entire rest of the image: same transparent wide 1920x832 approximately canvas, tower at right, same colors, nine-story traditional tapered octagonal Chinese pagoda style, complete finial, same small wooded hill, low mist, and all left-side transparency. No background, no sky, no UI, no text. True RGBA transparency. Do not add any new objects. Only insert the missing ninth tier.
```
