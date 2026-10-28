# 重庆 · 洪崖洞

## 产物与来源

- 资产：`$PROJECT_ROOT/assets/landmarks/source/chongqing.png`
- 内置 image_gen；transparent_background=true；一次生成，无修正。
- 原始生成文件：`$CODEX_HOME/generated_images/01a177d2-91e6-7ea0-b3a9-913448893b53/exec-4dcc446b-14cf-4bbf-8640-0987297d03b2.png`
- 参考1：`docs/design/workbench-20261026/city-landmarks/west-preview-v1.png`，重庆卡片的洪崖洞主体、层叠关系和色调。
- 参考2：`docs/design/workbench-20261026/city-landmarks/landmark-hangzhou.png`，透明图层的留白和右下构图。
- SHA-256：`FE243C21885A063D355F3046CFFF09F5C960568EDD5139B19A32ADDA44360C56`
- 直接复制生成PNG，未裁剪、抠图或改像素；未编辑应用代码。

## 检查

- 实际尺寸1905×825 px，RGBA，1095702字节。
- alpha范围0—255，完全透明74.52058%。
- 左半区域完全透明98.99567%，顶部25%区域完全透明99.68963%。
- alpha>16边界框[889,182,1891,807]，约x=46.67%—99.27%、y=22.06%—97.82%。
- alpha>128边界框[903,183,1888,793]。
- 最底行和最右列均没有alpha>16像素；屋顶及主体完整，无明显裁切。
- 主体为沿山势层叠的传统吊脚楼群，吊脚柱、木廊与多层屋顶可识别；少量河面、河岸与柔雾；无满幅现代城市、天空、文字或UI。
- 低饱和蓝灰建筑含暖色窗光，窗光比提示词略亮，但没有整幅强烈夜景背景。
- 剩余限制：极左雾/河面伸至46.7%处，左半并非100%透明；最高屋顶比目标y28%略高，实际约22.1%。接入方应按实际包围范围决定整体缩放或位置；建筑细部属于生成式概念插画，未逐项实景核验。

### 原始统计

```json
{
  "size": [
    1905,
    825
  ],
  "mode": "RGBA",
  "bytes": 1095702,
  "alpha_min": 0,
  "alpha_max": 255,
  "transparent_pct": 74.52057583711127,
  "left_half_transparent_pct": 98.99567099567099,
  "top_25pct_transparent_pct": 99.68962617536886,
  "bbox_alpha_gt16": [
    889,
    182,
    1891,
    807
  ],
  "bbox_alpha_gt128": [
    903,
    183,
    1888,
    793
  ],
  "alpha_gt16_on_last_row": 0,
  "alpha_gt16_on_right_edge": 0
}
```

## 完整提示词

Use case: stylized-concept.
Asset type: one standalone transparent PNG city landmark layer for a weather card: Chongqing, Hongyadong (洪崖洞).

Create a NEW detailed low-saturation realistic architectural illustration. Reference image1 is a preview board: use ONLY the Hongyadong subject in its top-left Chongqing card for identity, stepped stilt-house architecture, quiet atmosphere and material style. Never reproduce the board, card, words or weather. Reference image2 is the Hangzhou transparent landmark layer: MATCH its small right-bottom placement and extensive empty transparent space; replace its subject with Hongyadong.

Canvas approximately1920×832, wide landscape, with genuine alpha transparency. All pixels in the entire LEFT HALF (x=0%–50%) must be fully transparent. All pixels of the top25% must be transparent. The whole compact architectural scene, including haze, riverbank and every soft edge, must fit in the RIGHT HALF, ideally x=54%–97%, y=30%–95%. Buildings have a tallish layered mass rising on the right, so the scene must NOT become a wide panorama. Keep visible transparent padding on the right and bottom. The left side is reserved for weather UI text; absolutely no foliage, mist, river or isolated marks may enter it. Treat the entire art as one compact island sitting lower-right.

Subject: the recognizable Hongyadong traditional stilt-house complex, an interlocking dense cluster of old Chongqing riverside buildings with dark grey Chinese tiled roofs, wooden balconies, projecting stilts and terraces climbing a steep riverbank. Many distinct layered levels and upturned eaves, not a single temple, gate or tower. Tall layered buildings at the right and lower stepped buildings extending a little left, all contained in the right-half island. Include only a narrow soft suggestion of riverbank and a small dim river reflection under the buildings. A little cool mist may veil the lower structure and dissolve the river edge naturally. Keep full rooflines and both ends of the architectural cluster inside the image. No complete modern city skyline; no bridge and no unrelated pagoda.

Rendering: softly realistic architectural illustration, refined intricate surfaces at a restrained distance, muted cool slate blue and grey wood, slight natural timber browns, a few subtle warm amber accents within windows. Gentle neutral illumination, not a brightly lit nighttime tourist poster. Enough solid definition in the buildings for later CSS opacity animation; do not globally pre-fade them. Haze becomes genuinely translucent then fully transparent at its outer edges. Clear unique Hongyadong stepped structure, no hard rectangular terrain base.

Background MUST be truly transparent. NO sky, sun, moon, stars, weather clouds, rain, snowfall, colored field, black matte, white field, checkerboard pattern, typography, Chinese characters, numerals, labels, UI, card border, round frame, watermark, map, flags or people. Output only the one transparent architectural landmark layer.
