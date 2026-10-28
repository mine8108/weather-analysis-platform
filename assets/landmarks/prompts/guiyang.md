# 贵阳 · 甲秀楼

## 产物与来源

- 资产：`$PROJECT_ROOT/assets/landmarks/source/guiyang.png`
- 内置 image_gen，transparent_background=true；一次生成，无修正。
- 原始生成文件：`$CODEX_HOME/generated_images/01a177d2-91e6-7ea0-b3a9-913448893b53/exec-6ae108f7-39fe-4f4a-af7d-7b08b4732fda.png`
- 参考1：`docs/design/workbench-20261026/city-landmarks/west-preview-v1.png` 的贵阳卡片，主体与整体风格。
- 参考2：`docs/design/workbench-20261026/city-landmarks/landmark-hangzhou.png`，透明构图参考。
- SHA-256：`C4C9B5407BD0B9735358EDB1E8E3E456256E3F850FB986FE0456B186A4E8A532`
- 原样复制生成PNG，没有裁剪、抠图或改像素；未编辑应用代码。

## 检查

- 实际尺寸1905×825 px，RGBA，1033518字节。
- alpha范围0—255，完全透明74.22998%；左半94.08722%；顶部25%区域99.86163%。
- alpha>16边界框[771,193,1890,811]，约x=40.47%—99.21%、y=23.39%—98.30%。
- alpha>128边界框[812,195,1875,795]。
- 最右列与最底行均无alpha>16像素。
- 三层阁楼、三个主要屋顶层级、石拱桥、少量树木与河面均可辨识，塔尖和主体完整；没有天空、文字、UI或整幅背景。
- 主体符合本次概念参考，建筑细部与桥梁连接关系未逐项实景核验。
- 剩余限制：河面、桥与树木小景偏宽，实际延伸至x40.5%，需要接入端统一缩放到右侧；极低alpha边缘有少量彩色边缘残留，已按约定记录且不重复生成。柔雾与倒影接近底部但明显像素没有被裁断。

## 原始alpha统计

```json
{
  "size": [
    1905,
    825
  ],
  "mode": "RGBA",
  "bytes": 1033518,
  "alpha_min": 0,
  "alpha_max": 255,
  "transparent_pct": 74.2299848882526,
  "left_half_transparent_pct": 94.08721670486376,
  "top_25pct_transparent_pct": 99.86163137374818,
  "bbox_alpha_gt16": [
    771,
    193,
    1890,
    811
  ],
  "bbox_alpha_gt128": [
    812,
    195,
    1875,
    795
  ],
  "alpha_gt16_on_last_row": 0,
  "alpha_gt16_on_right_edge": 0
}
```

## 完整提示词

Use case: stylized-concept.
Asset type: one independent transparent PNG city landmark layer for a weather card: Guiyang, Jiaxiu Tower (甲秀楼).

Generate a NEW softly realistic architectural illustration, approximately1920×832 landscape with genuine alpha transparency. Input image1 is a western-city preview board: use only the top-right Guiyang card for the landmark identity, palette and gentle style, never reproduce its UI. Input image2 is the transparent Hangzhou landmark layer: use its extensive transparent canvas and compact right-bottom composition as layout reference, not its pagoda.

Subject: Jiaxiu Tower in Guiyang, a recognizably THREE-STOREY traditional Chinese pavilion with three clear main roof levels and upturned tiled eaves, dark wood and restrained muted red details, sitting on a pale stone platform in the river. Include an elegant stone arch bridge leading toward the pavilion, only a little riverside greenery and a small patch of reflective river below. Show the complete pavilion silhouette, full roof finial and enough of the connected arched bridge to read the site clearly. Do not turn the pavilion into a tall multi-storey pagoda or a city gate. Keep the scene an intimate riverside landmark cameo, not a panorama or modern skyline.

Composition: the entire scene, including bridge, small trees, water and mist, is in the lower RIGHT portion of the wide canvas. Aim to fit all visible imagery inside x=54%–97%, y=30%–96%. The left half must remain fully transparent, as must the large upper portion. Keep generous actual transparent margins and no disconnected marks. The architectural island should be similar in scale to the Hangzhou layer. Place the tall pavilion nearer x=82%, with the stone bridge running a short distance toward its left within the right half. Nothing may touch or be cropped by the outer image edges.

Rendering and color: refined detailed softly realistic illustration, correct believable structure, low-saturation cool slate blue and grey, subtle restrained natural wood and muted warm accents. Gentle neutral light, no dramatic evening illumination. Visible architectural texture and crisp recognizable eave silhouettes, softened only by slight atmospheric perspective. A delicate light-blue-grey mist hugs the lower stone base and river and fades organically into genuine transparency. Keep structure strong enough for later CSS default/hover opacity; do not pre-fade everything. Small trees and reflections remain subordinate.

Genuine transparent background only: no sky, clouds, sun, moon, stars, rain, snow, black/white/colored matte, checkerboard texture, rectangle of ground, long horizon, full background buildings, typography, Chinese characters, numbers, labels, card shape, UI, border, rounded frame, map, flag, people, watermark. Output exactly one isolated complete landmark layer.
