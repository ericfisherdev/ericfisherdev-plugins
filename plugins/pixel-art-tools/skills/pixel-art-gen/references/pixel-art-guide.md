# Pixel Art Reference Guide

## JSON Pixel Data Schema

```json
{
  "width": 16,
  "height": 16,
  "background": "#FFFFFF",
  "grid_lines": false,
  "pixel_size": 32,
  "pixels": [
    {"x": 0, "y": 0, "color": "#FF0000"},
    {"x": 1, "y": 0, "color": "red"},
    {"x": 2, "y": 0, "color": "transparent"},
    {"x": 3, "y": 0, "color": [255, 128, 0]},
    {"x": 4, "y": 0, "color": [255, 128, 0, 200]}
  ]
}
```

### Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `width` | int | Yes | - | Grid width in logical pixels |
| `height` | int | Yes | - | Grid height in logical pixels |
| `background` | string | No | `"#FFFFFF"` | Background color (hex, named, or `"transparent"`) |
| `grid_lines` | bool | No | `false` | Draw 1px grid lines at pixel boundaries |
| `pixel_size` | int | No | `32` | Size of each logical pixel in the output PNG |
| `pixels` | array | Yes | - | Array of pixel objects (sparse — only non-background pixels) |

### Pixel Object

| Field | Type | Description |
|-------|------|-------------|
| `x` | int | Column index, 0-indexed from left |
| `y` | int | Row index, 0-indexed from top |
| `color` | string or array | Hex (`"#RRGGBB"`/`"#RRGGBBAA"`), CSS name (`"red"`), `"transparent"`, or RGB/RGBA array (`[R,G,B]`/`[R,G,B,A]`) |

## Suggested Color Palettes

### General Purpose (8 colors)

| Name | Hex | Use |
|------|-----|-----|
| Black | `#1A1C2C` | Outlines, darkest shadows |
| Dark Blue | `#5D275D` | Deep shadows |
| Red | `#B13E53` | Accents, warm tones |
| Orange | `#EF7D57` | Warm midtones |
| Yellow | `#FFCD75` | Highlights, warm light |
| Green | `#38B764` | Vegetation, nature |
| Light Blue | `#29366F` | Cool shadows, sky |
| White | `#F4F4F4` | Highlights, brightest areas |

### Nature (6 colors)

| Name | Hex | Use |
|------|-----|-----|
| Dark Green | `#265C42` | Deep foliage, shadows |
| Green | `#3E8948` | Main foliage |
| Light Green | `#63C74D` | Bright leaves, highlights |
| Brown | `#8B4513` | Wood, earth |
| Sky Blue | `#87CEEB` | Sky, water |
| White | `#FFFFFF` | Clouds, highlights |

### Warm / Fire (5 colors)

| Name | Hex | Use |
|------|-----|-----|
| Dark Red | `#6B0000` | Deepest shadow |
| Red | `#CC0000` | Core flame |
| Orange | `#FF6600` | Mid flame |
| Yellow | `#FFCC00` | Bright flame |
| White | `#FFFFCC` | Hottest point |

### Cool / Ice (5 colors)

| Name | Hex | Use |
|------|-----|-----|
| Dark Blue | `#0A1628` | Deep shadow |
| Blue | `#1B4965` | Mid shadow |
| Cyan | `#5FA8D3` | Base ice |
| Light Blue | `#BEE9E8` | Highlights |
| White | `#FFFFFF` | Brightest ice |

### Skin Tones (4 colors)

| Name | Hex | Use |
|------|-----|-----|
| Shadow | `#8B5E3C` | Darkest skin tone |
| Mid | `#C68642` | Base skin |
| Light | `#E0AC69` | Highlighted skin |
| Highlight | `#F1C27D` | Brightest skin highlight |

## Example: 8x8 Heart

```json
{
  "width": 8,
  "height": 8,
  "background": "#FFFFFF",
  "pixel_size": 32,
  "pixels": [
    {"x": 1, "y": 1, "color": "#B13E53"},
    {"x": 2, "y": 1, "color": "#B13E53"},
    {"x": 4, "y": 1, "color": "#B13E53"},
    {"x": 5, "y": 1, "color": "#B13E53"},
    {"x": 0, "y": 2, "color": "#B13E53"},
    {"x": 1, "y": 2, "color": "#EF7D57"},
    {"x": 2, "y": 2, "color": "#B13E53"},
    {"x": 3, "y": 2, "color": "#B13E53"},
    {"x": 4, "y": 2, "color": "#B13E53"},
    {"x": 5, "y": 2, "color": "#EF7D57"},
    {"x": 6, "y": 2, "color": "#B13E53"},
    {"x": 0, "y": 3, "color": "#B13E53"},
    {"x": 1, "y": 3, "color": "#B13E53"},
    {"x": 2, "y": 3, "color": "#B13E53"},
    {"x": 3, "y": 3, "color": "#B13E53"},
    {"x": 4, "y": 3, "color": "#B13E53"},
    {"x": 5, "y": 3, "color": "#B13E53"},
    {"x": 6, "y": 3, "color": "#B13E53"},
    {"x": 1, "y": 4, "color": "#B13E53"},
    {"x": 2, "y": 4, "color": "#B13E53"},
    {"x": 3, "y": 4, "color": "#B13E53"},
    {"x": 4, "y": 4, "color": "#B13E53"},
    {"x": 5, "y": 4, "color": "#B13E53"},
    {"x": 2, "y": 5, "color": "#B13E53"},
    {"x": 3, "y": 5, "color": "#B13E53"},
    {"x": 4, "y": 5, "color": "#B13E53"},
    {"x": 3, "y": 6, "color": "#B13E53"}
  ]
}
```

## Design Tips

### Grid Size Selection

- **8x8**: Icons, simple symbols, emoji-like art
- **10x10**: Slightly more detail, small characters
- **16x16**: Standard sprites, characters with expressions
- **32x32**: Detailed scenes, complex characters, buildings

### Design Workflow

1. **Start with the silhouette**: Outline the main shape in your darkest color
2. **Fill base colors**: Use 2-3 main colors for the largest areas
3. **Add details**: Eyes, patterns, small features
4. **Add shading**: Darker variants below/right, lighter variants above/left
5. **Review**: Check that the shape reads clearly — simplify if needed

### Common Patterns

- **Outlines**: Use a dark color (not pure black — try `#1A1C2C`) for 1px outlines
- **Dithering**: Alternate two colors in a checkerboard for a blend effect
- **Highlights**: Place a lighter pixel at top-left corners of shapes
- **Anti-aliasing**: Use intermediate colors at diagonal stair-step edges
