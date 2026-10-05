# Test prompts for pixel-art-gen

Run each prompt in a fresh session with the skill on and again with it off. Compare against the expected outcome.

## Prompt 1: simple icon

> Create pixel art of a heart.

Expected with skill: picks an 8x8 grid and a 4-8 color palette, writes `pixel_art.json` in the sparse x/y/color format, runs `render_pixel_art.py` to produce `pixel_art.png`, reads the PNG to check the heart reads clearly, then shows it and offers adjustments.

Baseline without skill: describes a heart in text or ASCII art, or writes ad-hoc drawing code; no JSON file, no PNG from the bundled renderer, no self-check of the image.

## Prompt 2: user-specified size and revision

> Make me a 10x10 pixel art sprite of a mushroom, then change the cap to blue.

Expected with skill: uses the requested 10x10 grid instead of the default, renders and shows the PNG, then for the change edits `pixel_art.json` in place, re-runs the render command, and reads the new PNG before showing it.

Baseline without skill: redraws the whole thing from scratch or returns code only; the grid size may drift from 10x10 and the revised image is not re-rendered or checked.

## Prompt 3: out-of-grid pixels

> Draw pixel art of a 16x16 smiley face (8-bit style).

Expected with skill: if any pixel lands outside the 16x16 grid, the render still writes the PNG but exits 1 with `Dropped N pixel(s) outside the 16x16 grid: (x,y), ...` on stderr; the skill fixes `pixel_art.json`, re-renders until clean, and only then shows the image.

Baseline without skill: no renderer and no exit-code check, so bad coordinates go unnoticed or the image is shown with missing features.
