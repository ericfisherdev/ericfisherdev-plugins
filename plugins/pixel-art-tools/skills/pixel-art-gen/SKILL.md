---
name: Pixel Art Generator
description: >
  This skill should be used when the user asks to "create pixel art",
  "generate pixel art", "make a pixel art sprite", "draw pixel art",
  "8-bit style image", "retro pixel image", "pixel art of",
  "make me pixel art", or requests creating pixel art, sprites,
  or retro-style pixel graphics. Claude designs the art itself
  and renders it to PNG using a bundled script — no external API needed.
version: 0.1.0
---

# Pixel Art Generator

Generate pixel art PNGs from text descriptions. You design the art yourself and render it with the bundled Python script.

## Prerequisites

Before generating pixel art, ensure:

1. **Pillow** Python package is installed: `pip install Pillow`

If Pillow is missing, install it before proceeding.

## Design Process

When a user requests pixel art, follow these steps:

### Step 1: Choose Grid Size

Pick a grid size based on subject complexity:

| Complexity | Grid | Examples |
|------------|------|----------|
| Simple icons | 8x8 | heart, star, arrow, smiley |
| Standard sprites | 16x16 | character, animal, item |
| Detailed scenes | 32x32 | landscape, building, vehicle |

If the user specifies a size (e.g., "10x10"), use that instead.

### Step 2: Choose a Palette

Constrain yourself to **4-8 colors**. Fewer colors = better pixel art. Pick colors that suit the subject. See `~/.claude/skills/pixel-art-gen/references/pixel-art-guide.md` for suggested palettes.

### Step 3: Design in Layers

Think through the design systematically:

1. **Silhouette** — outline the main shape
2. **Base fill** — fill with primary colors
3. **Details** — add features (eyes, patterns, textures)
4. **Shading** — add darker/lighter variants for depth

### Step 4: Generate JSON Pixel Data

Create a JSON object using the sparse coordinate format. Only list non-background pixels:

```json
{
  "width": 8,
  "height": 8,
  "background": "#FFFFFF",
  "grid_lines": false,
  "pixel_size": 32,
  "pixels": [
    {"x": 3, "y": 0, "color": "#FF0000"},
    {"x": 4, "y": 0, "color": "#FF0000"}
  ]
}
```

**Important rules:**
- Coordinates are 0-indexed. `x` is column (left to right), `y` is row (top to bottom).
- Only include pixels that differ from the background color.
- Use hex colors (e.g., `"#FF6B35"`) for precision. CSS named colors (e.g., `"red"`) and `"transparent"` are also supported.
- Double-check coordinates — off-by-one errors ruin pixel art.

### Step 5: Render to PNG

1. Write the JSON data to a file (e.g., `pixel_art.json`)
2. Run the render script:

```bash
python3 ~/.claude/skills/pixel-art-gen/scripts/render_pixel_art.py \
  pixel_art.json \
  -o pixel_art.png
```

3. Display the result to the user using the Read tool on the output PNG file.

**Script arguments:**

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `input` | Yes | - | JSON file path, or `-` for stdin |
| `-o, --output` | No | `pixel_art.png` | Output PNG file path |
| `-p, --pixel-size` | No | `32` | Size of each logical pixel in the output |
| `-g, --grid-lines` | No | off | Enable 1px grid lines at pixel boundaries |
| `--no-grid-lines` | No | - | Explicitly disable grid lines (overrides JSON) |

### Step 6: Iterate

After displaying the result, offer to adjust:
- Colors or palette
- Individual pixel positions
- Grid size (start over at larger/smaller resolution)
- Add/remove grid lines
- Change background color

## Workflow Summary

When a user requests pixel art:

1. Determine the subject and appropriate grid size
2. Choose a constrained color palette (4-8 colors)
3. Mentally design the art layer by layer
4. Generate the JSON pixel data with explicit x,y coordinates
5. Write the JSON to a file
6. Run the render script to produce a PNG
7. Display the PNG to the user with the Read tool
8. Offer to make adjustments

## Tips for Better Pixel Art

- **Symmetry**: Many subjects (faces, creatures, objects) benefit from horizontal symmetry
- **Outline**: A 1px dark outline helps shapes read clearly at small sizes
- **Anti-aliasing**: For diagonal lines, use intermediate colors at stair-step edges
- **Highlights**: Place lighter colors on top-left to suggest a light source
- **Shadows**: Place darker colors on bottom-right

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `Pillow not installed` | Run `pip install Pillow` |
| Garbled output | Check x,y coordinates are within grid bounds (0 to width-1, 0 to height-1) |
| Colors look wrong | Use hex codes for precision; named colors may vary |
| Image too small/large | Adjust `-p` pixel size (default 32) |
