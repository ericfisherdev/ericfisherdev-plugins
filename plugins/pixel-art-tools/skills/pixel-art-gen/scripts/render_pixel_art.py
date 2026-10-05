#!/usr/bin/env python3
"""Render JSON pixel data to a PNG image using Pillow.

Usage:
    python3 render_pixel_art.py <input.json> -o output.png [-p pixel_size] [-g] [--no-grid-lines]
    echo '{"width":2,"height":2,"pixels":[...]}' | python3 render_pixel_art.py - -o output.png
"""

import argparse
import json
import sys

try:
    from PIL import Image, ImageDraw, ImageColor
except ImportError:
    print("Error: Pillow is not installed. Run: pip install Pillow", file=sys.stderr)
    sys.exit(1)


# CSS named colors that Pillow doesn't know about (Pillow covers most, but
# we add "transparent" as a special case)
SPECIAL_COLORS = {
    "transparent": (0, 0, 0, 0),
}


def parse_color(color):
    """Parse a color value into an RGBA tuple.

    Supports:
      - Hex strings: "#RRGGBB", "#RRGGBBAA", "#RGB", "#RGBA"
      - CSS named colors: "red", "dodgerblue", etc.
      - Special values: "transparent"
      - RGB/RGBA arrays: [255, 128, 0] or [255, 128, 0, 200]
    """
    if isinstance(color, (list, tuple)):
        if len(color) == 3:
            return tuple(color) + (255,)
        elif len(color) == 4:
            return tuple(color)
        else:
            raise ValueError(f"RGB/RGBA array must have 3 or 4 elements, got {len(color)}")

    if not isinstance(color, str):
        raise ValueError(f"Unsupported color type: {type(color)}")

    color_lower = color.strip().lower()

    if color_lower in SPECIAL_COLORS:
        return SPECIAL_COLORS[color_lower]

    try:
        rgba = ImageColor.getrgb(color)
        if len(rgba) == 3:
            return rgba + (255,)
        return rgba
    except (ValueError, AttributeError):
        raise ValueError(f"Unrecognized color: {color!r}")


def render_pixel_art(data, pixel_size_override=None, grid_lines_override=None):
    """Render pixel art data to a Pillow Image.

    Args:
        data: Parsed JSON pixel data dict.
        pixel_size_override: If set, overrides pixel_size from JSON.
        grid_lines_override: If set (True/False), overrides grid_lines from JSON.

    Returns:
        PIL.Image.Image in RGBA mode.
    """
    width = data["width"]
    height = data["height"]
    background = data.get("background", "#FFFFFF")
    pixel_size = pixel_size_override or data.get("pixel_size", 32)
    grid_lines = data.get("grid_lines", False)

    if grid_lines_override is not None:
        grid_lines = grid_lines_override

    bg_color = parse_color(background)
    img_width = width * pixel_size
    img_height = height * pixel_size

    img = Image.new("RGBA", (img_width, img_height), bg_color)
    draw = ImageDraw.Draw(img)

    for pixel in data.get("pixels", []):
        x = pixel["x"]
        y = pixel["y"]
        color = parse_color(pixel["color"])

        if x < 0 or x >= width or y < 0 or y >= height:
            print(f"Warning: pixel ({x}, {y}) is outside the {width}x{height} grid, skipping.",
                  file=sys.stderr)
            continue

        x0 = x * pixel_size
        y0 = y * pixel_size
        x1 = x0 + pixel_size
        y1 = y0 + pixel_size

        if color[3] == 0:
            # Transparent: clear this region (draw transparent rect)
            transparent_block = Image.new("RGBA", (pixel_size, pixel_size), (0, 0, 0, 0))
            img.paste(transparent_block, (x0, y0))
        else:
            draw.rectangle([x0, y0, x1 - 1, y1 - 1], fill=color)

    if grid_lines:
        grid_color = (0, 0, 0, 60)
        for gx in range(1, width):
            line_x = gx * pixel_size
            draw.line([(line_x, 0), (line_x, img_height - 1)], fill=grid_color, width=1)
        for gy in range(1, height):
            line_y = gy * pixel_size
            draw.line([(0, line_y), (img_width - 1, line_y)], fill=grid_color, width=1)

    return img


def main():
    parser = argparse.ArgumentParser(
        description="Render JSON pixel data to a PNG image."
    )
    parser.add_argument(
        "input",
        help="Path to JSON file, or '-' for stdin",
    )
    parser.add_argument(
        "-o", "--output",
        default="pixel_art.png",
        help="Output PNG file path (default: pixel_art.png)",
    )
    parser.add_argument(
        "-p", "--pixel-size",
        type=int,
        default=None,
        help="Size of each logical pixel in output (default: from JSON or 32)",
    )
    parser.add_argument(
        "-g", "--grid-lines",
        action="store_true",
        default=False,
        help="Enable grid lines at pixel boundaries",
    )
    parser.add_argument(
        "--no-grid-lines",
        action="store_true",
        default=False,
        help="Disable grid lines (overrides JSON setting)",
    )

    args = parser.parse_args()

    # Read input
    if args.input == "-":
        raw = sys.stdin.read()
    else:
        with open(args.input, "r") as f:
            raw = f.read()

    data = json.loads(raw)

    # Determine grid lines override
    grid_lines_override = None
    if args.no_grid_lines:
        grid_lines_override = False
    elif args.grid_lines:
        grid_lines_override = True

    img = render_pixel_art(data, pixel_size_override=args.pixel_size,
                           grid_lines_override=grid_lines_override)
    img.save(args.output, "PNG")
    print(f"Saved {args.output} ({img.width}x{img.height}px)")


if __name__ == "__main__":
    main()
