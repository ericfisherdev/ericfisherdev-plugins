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

## Contents

- Needs
- Design Process
- Workflow Summary
- Troubleshooting
- Files

Generate pixel art PNGs from text descriptions. You design the art yourself and render it with the bundled Python script.

## Needs

- python3
- **Pillow** Python package: `pip install Pillow` (install it before proceeding if it is missing)

## Design Process

When a user requests pixel art, follow these steps:

### Step 1: Choose Grid Size

Pick a grid size based on subject complexity:

| Complexity | Grid (defaults) | Examples |
|------------|-----------------|----------|
| Simple icons | 8x8 | heart, star, arrow, smiley |
| Standard sprites | 16x16 | character, animal, item |
| Detailed scenes | 32x32 | landscape, building, vehicle |

If the user specifies a size (e.g., "10x10"), use that instead.

### Step 2: Choose a Palette

Default to **4-8 colors**; go wider only when the subject needs it. Fewer colors = better pixel art. Pick colors that suit the subject. See `${CLAUDE_SKILL_DIR}/references/pixel-art-guide.md` for suggested palettes.

### Step 3: Generate JSON Pixel Data

Create a JSON object using the sparse coordinate format. Only list non-background pixels.

Use this exact format; the renderer rejects missing width, height, or pixels.

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

Examples (request → JSON):

An 8x8 green up arrow:

```json
{
  "width": 8,
  "height": 8,
  "background": "#FFFFFF",
  "pixels": [
    {"x": 3, "y": 0, "color": "#38B764"}, {"x": 4, "y": 0, "color": "#38B764"}, {"x": 2, "y": 1, "color": "#38B764"}, {"x": 3, "y": 1, "color": "#38B764"},
    {"x": 4, "y": 1, "color": "#38B764"}, {"x": 5, "y": 1, "color": "#38B764"}, {"x": 1, "y": 2, "color": "#38B764"}, {"x": 2, "y": 2, "color": "#38B764"},
    {"x": 3, "y": 2, "color": "#38B764"}, {"x": 4, "y": 2, "color": "#38B764"}, {"x": 5, "y": 2, "color": "#38B764"}, {"x": 6, "y": 2, "color": "#38B764"},
    {"x": 3, "y": 3, "color": "#38B764"}, {"x": 4, "y": 3, "color": "#38B764"}, {"x": 3, "y": 4, "color": "#38B764"}, {"x": 4, "y": 4, "color": "#38B764"},
    {"x": 3, "y": 5, "color": "#38B764"}, {"x": 4, "y": 5, "color": "#38B764"}, {"x": 3, "y": 6, "color": "#38B764"}, {"x": 4, "y": 6, "color": "#38B764"}
  ]
}
```

A 16x16 small sun on a dark blue sky:

```json
{
  "width": 16,
  "height": 16,
  "background": "#29366F",
  "pixels": [
    {"x": 7, "y": 7, "color": "#FFCD75"}, {"x": 7, "y": 8, "color": "#FFCD75"}, {"x": 8, "y": 7, "color": "#FFCD75"}, {"x": 8, "y": 8, "color": "#FFCD75"},
    {"x": 7, "y": 5, "color": "#EF7D57"}, {"x": 8, "y": 5, "color": "#EF7D57"}, {"x": 7, "y": 10, "color": "#EF7D57"}, {"x": 8, "y": 10, "color": "#EF7D57"},
    {"x": 5, "y": 7, "color": "#EF7D57"}, {"x": 5, "y": 8, "color": "#EF7D57"}, {"x": 10, "y": 7, "color": "#EF7D57"}, {"x": 10, "y": 8, "color": "#EF7D57"},
    {"x": 6, "y": 6, "color": "#EF7D57"}, {"x": 9, "y": 6, "color": "#EF7D57"}, {"x": 6, "y": 9, "color": "#EF7D57"}, {"x": 9, "y": 9, "color": "#EF7D57"}
  ]
}
```

### Step 4: Render to PNG

1. Write the JSON data to a file (e.g., `pixel_art.json`)
2. Run the render script:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/render_pixel_art.py" \
  pixel_art.json \
  -o pixel_art.png
```

3. Read the PNG yourself. If the subject does not read clearly, or the render printed a warning on stderr, fix `pixel_art.json` and re-render. Show the result only when clean.
4. Display the result to the user using the Read tool on the output PNG file.

**Script arguments:**

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `input` | Yes | - | JSON file path, or `-` for stdin |
| `-o, --output` | No | `pixel_art.png` | Output PNG file path |
| `-p, --pixel-size` | No | `32` | Size of each logical pixel in the output |
| `-g, --grid-lines` | No | off | Enable 1px grid lines at pixel boundaries |
| `--no-grid-lines` | No | - | Explicitly disable grid lines (overrides JSON) |

### Step 5: Iterate

After displaying the result, offer to adjust:
- Colors or palette
- Individual pixel positions
- Grid size (start over at larger/smaller resolution)
- Add/remove grid lines
- Change background color

To apply a requested change: edit `pixel_art.json` in place → re-run the render command above → Read the new PNG.

## Workflow Summary

When a user requests pixel art:

Copy this checklist and track progress:

- [ ] Step 1: Determine the subject and appropriate grid size
- [ ] Step 2: Choose a color palette (default 4-8 colors)
- [ ] Step 3: Generate the JSON pixel data with explicit x,y coordinates
- [ ] Step 4: Write the JSON to a file
- [ ] Step 5: Run the render script to produce a PNG
- [ ] Step 6: Read the PNG yourself and fix the JSON and re-render if it is unclear or the render warned
- [ ] Step 7: Display the PNG to the user with the Read tool
- [ ] Step 8: Offer to make adjustments

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Garbled output | Check x,y coordinates are within grid bounds (0 to width-1, 0 to height-1) |
| Colors look wrong | Use hex codes for precision; named colors may vary |
| Image too small/large | Adjust `-p` pixel size (default 32) |

## Files

- [references/pixel-art-guide.md](references/pixel-art-guide.md) — JSON schema fields, suggested palettes, a worked example; read when choosing colors or checking the format.
- [scripts/render_pixel_art.py](scripts/render_pixel_art.py) — renders the JSON to a PNG; exits 1 after writing the image if any pixels fell outside the grid.
- [evals/test-prompts.md](evals/test-prompts.md) — three test prompts and the baseline without the skill.
