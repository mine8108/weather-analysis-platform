# 昆明 · 金马碧鸡坊

## 产物与来源

- 资产：`$PROJECT_ROOT/assets/landmarks/source/kunming.png`
- 内置 image_gen，transparent_background=true；一次生成，无修正。
- 原始生成文件：`$CODEX_HOME/generated_images/01a177d2-91e6-7ea0-b3a9-913448893b53/exec-760ef126-a548-4ad2-8f72-5ffe576c8242.png`
- 参考1：`docs/design/workbench-20261026/city-landmarks/west-preview-v1.png` 昆明卡片，双牌坊与风格。
- 参考2：`docs/design/workbench-20261026/city-landmarks/landmark-hangzhou.png`，透明画布与构图。
- 原样复制生成PNG，未裁剪、抠图、改像素；未修改应用代码。

## 检查

- 实际1903×826 px，RGBA，1093370字节；alpha范围0—255。
- 全图透明70.37881%；左半透明91.01736%；上方30%区域透明99.70832%。
- alpha>16边界框[713,301,1903,826]，约x=37.47%—100%、y=36.44%—100%。
- alpha>128边界框[749,302,1868,798]。
- 底边15像素、右边19像素alpha>16，主要为微弱雾边。
- 两座独立牌坊有各自完整柱列、屋顶、基座；前后错位，局部屋檐在投影中接近，无连续连体屋顶。少量广场石面与树木，没有河水、天气天空、文字或UI。
- 图形预览有醒目红色/黄色低alpha彩边；直接读取RGBA确认高红低绿蓝像素在alpha>16和alpha>128时均仅1个，绝大部分彩色边缘属于非常低alpha像素，按约定保留并记录。
- 剩余限制：小景偏宽，树木和雾伸至x37.5%，由接入端统一缩放到右侧。彩绘和金色细节比目标略鲜明，且屋檐投影局部接近；建筑细部与场地布局属于概念插画，未逐项实景核验。

## 原始alpha统计

```json
{
  "size": [
    1903,
    826
  ],
  "mode": "RGBA",
  "bytes": 1093370,
  "alpha_min": 0,
  "alpha_max": 255,
  "transparent_pct": 70.37880802454134,
  "left_half_transparent_pct": 91.0173565228904,
  "top_30pct_transparent_pct": 99.70832331647664,
  "bbox_alpha_gt16": [
    713,
    301,
    1903,
    826
  ],
  "bbox_alpha_gt128": [
    749,
    302,
    1868,
    798
  ],
  "alpha_gt16_on_last_row": 15,
  "alpha_gt16_on_right_edge": 19,
  "bright_red_pixels_alpha_gt16": 1,
  "bright_red_pixels_alpha_gt128": 1
}
```

## 完整提示词

Use case: stylized-concept.
Asset type: ONE independent transparent PNG landmark illustration for a weather card — Kunming, Jinma and Biji Archways (金马碧鸡坊).

Create a NEW image, approximately1920×832 wide landscape, genuine alpha-transparent background. Reference image1 is a western-city weather preview: use only its Kunming card in row2 column1 for the pair of archways and palette; do not draw the board, card, weather or words. Reference image2 is a transparent Hangzhou overlay: match ONLY its compact lower-right composition and extensive transparency, never its pagoda, water or vegetation amount.

Main subject: TWO DISTINCT freestanding traditional Chinese painted ceremonial archways in Kunming, side by side with a clear open gap separating the structures. Each is a complete ornate multi-tier tiled-roof gateway with carved stone columns, three open passage bays, delicate timber brackets, layered upturned eaves and restrained painted architectural detail. Show one slightly nearer and one a little farther to give realistic plaza depth, both similarly substantial and unmistakably independent gateways. Keep every roof tip and supporting column visible. They must NOT merge into one connected building, temple complex, long hall, continuous roof, city wall or bridge. Keep the actual negative space between the two archways visible and transparent above the tiny ground patch. Do not add legible inscriptions or lettering to the archway plaques; treat them as restrained undecorated panels.

Composition: a small architectural cameo in the lower-right of the wide canvas. Aim for the entire group including haze and minimal environment inside x=54%–97%, y=35%–95%. The entire left50% and upper30% must be completely transparent with no stray marks. Keep clean transparent margin around all sides of the group, especially right and bottom. The gateway pair has a little dry pale stone plaza immediately beneath its feet and only a small suggestion of foliage behind the far right edge. No road, traffic, people, surrounding city or mountain panorama.

Visual style: detailed softly realistic architectural illustration, delicate authentic-looking proportions and textures; cool slate blue and grey roofs, low-saturation stone, muted jade/teal painted brackets and a little natural timber warmth. Gentle neutral light, restrained highlights. The subject itself has clear definition for later CSS opacity fading; no global pre-fade. The tiny plaza and base of the columns dissolve softly into a little thin mist and then real transparent pixels with organic soft edges. No bright glowing border, no hard ground rectangle, no lake or river.

Do not include sky, clouds, sun, moon, stars, rainfall, snowfall, weather icons, text, Chinese characters, numerals, labels, UI, cards, frames, rounded rectangles, maps, flags, watermark, checkerboard, black matte, white or colored background. Output only this one complete transparent layer of the paired archways.
