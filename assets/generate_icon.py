#!/usr/bin/env python3
"""Generate app icons for Remote Desktop."""

import os
import struct
from PIL import Image, ImageDraw, ImageFont

SIZES = [16, 32, 64, 128, 256, 512, 1024]

# Colors matching the app theme
BG_COLOR = (13, 17, 23)         # #0d1117
CARD_COLOR = (22, 27, 34)      # #161b22
ACCENT_GREEN = (63, 185, 80)   # #3fb950
ACCENT_BLUE = (31, 111, 235)   # #1f6feb
BORDER_COLOR = (48, 54, 61)    # #30363d
WHITE = (240, 246, 252)        # #f0f6fc


def draw_icon(size: int) -> Image.Image:
    """Draw the remote desktop icon at a given size."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Scale factor
    s = size / 1024.0

    # Background rounded rectangle
    radius = int(180 * s)
    margin = int(20 * s)
    draw.rounded_rectangle(
        [margin, margin, size - margin, size - margin],
        radius=radius,
        fill=BG_COLOR
    )

    # Inner card area
    inner_margin = int(80 * s)
    inner_radius = int(100 * s)
    draw.rounded_rectangle(
        [inner_margin, inner_margin, size - inner_margin, size - inner_margin],
        radius=inner_radius,
        fill=CARD_COLOR
    )

    # Main monitor (larger, back)
    mon_x1 = int(180 * s)
    mon_y1 = int(180 * s)
    mon_x2 = int(650 * s)
    mon_y2 = int(550 * s)
    mon_radius = int(30 * s)
    border_w = int(8 * s)

    # Monitor border
    draw.rounded_rectangle(
        [mon_x1, mon_y1, mon_x2, mon_y2],
        radius=mon_radius,
        fill=BORDER_COLOR
    )
    # Monitor screen
    draw.rounded_rectangle(
        [mon_x1 + border_w, mon_y1 + border_w,
         mon_x2 - border_w, mon_y2 - border_w],
        radius=max(1, mon_radius - border_w),
        fill=ACCENT_BLUE + (80,)
    )
    # Monitor stand
    stand_w = int(60 * s)
    stand_h = int(40 * s)
    stand_cx = (mon_x1 + mon_x2) // 2
    draw.rectangle(
        [stand_cx - stand_w // 2, mon_y2,
         stand_cx + stand_w // 2, mon_y2 + stand_h],
        fill=BORDER_COLOR
    )
    # Stand base
    base_w = int(120 * s)
    base_h = int(12 * s)
    draw.rounded_rectangle(
        [stand_cx - base_w // 2, mon_y2 + stand_h,
         stand_cx + base_w // 2, mon_y2 + stand_h + base_h],
        radius=max(1, int(6 * s)),
        fill=BORDER_COLOR
    )

    # Second monitor (smaller, front-right, overlapping)
    mon2_x1 = int(420 * s)
    mon2_y1 = int(340 * s)
    mon2_x2 = int(830 * s)
    mon2_y2 = int(670 * s)

    # Monitor 2 border
    draw.rounded_rectangle(
        [mon2_x1, mon2_y1, mon2_x2, mon2_y2],
        radius=mon_radius,
        fill=BORDER_COLOR
    )
    # Monitor 2 screen
    draw.rounded_rectangle(
        [mon2_x1 + border_w, mon2_y1 + border_w,
         mon2_x2 - border_w, mon2_y2 - border_w],
        radius=max(1, mon_radius - border_w),
        fill=ACCENT_GREEN + (90,)
    )
    # Monitor 2 stand
    stand2_cx = (mon2_x1 + mon2_x2) // 2
    draw.rectangle(
        [stand2_cx - stand_w // 2, mon2_y2,
         stand2_cx + stand_w // 2, mon2_y2 + stand_h],
        fill=BORDER_COLOR
    )
    # Stand 2 base
    draw.rounded_rectangle(
        [stand2_cx - base_w // 2, mon2_y2 + stand_h,
         stand2_cx + base_w // 2, mon2_y2 + stand_h + base_h],
        radius=max(1, int(6 * s)),
        fill=BORDER_COLOR
    )

    # Connection arrows between monitors (green glowing line)
    arrow_y = int(420 * s)
    arrow_x1 = int(560 * s)
    arrow_x2 = int(510 * s)
    line_w = max(1, int(10 * s))

    # Draw dotted connection line
    for i in range(3):
        cx = arrow_x2 + int(i * 30 * s)
        cy = arrow_y - int(40 * s)
        dot_r = max(1, int(8 * s))
        draw.ellipse(
            [cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r],
            fill=ACCENT_GREEN
        )

    # "RD" text at bottom
    text_y = int(770 * s)
    try:
        font_size = int(160 * s)
        font = ImageFont.truetype("/System/Library/Fonts/SFCompact.ttf", font_size)
    except (OSError, IOError):
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
        except (OSError, IOError):
            font = ImageFont.load_default()

    # Draw "RD" text
    text = "RD"
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_x = (size - text_w) // 2
    draw.text((text_x, text_y), text, fill=ACCENT_GREEN, font=font)

    return img


def create_icns(png_path: str, icns_path: str):
    """Create macOS .icns file from PNG using iconutil."""
    import subprocess
    import tempfile

    iconset_dir = tempfile.mkdtemp(suffix=".iconset")

    img = Image.open(png_path)

    icns_sizes = [
        (16, "16x16"),
        (32, "16x16@2x"),
        (32, "32x32"),
        (64, "32x32@2x"),
        (128, "128x128"),
        (256, "128x128@2x"),
        (256, "256x256"),
        (512, "256x256@2x"),
        (512, "512x512"),
        (1024, "512x512@2x"),
    ]

    for px, name in icns_sizes:
        resized = img.resize((px, px), Image.LANCZOS)
        resized.save(os.path.join(iconset_dir, f"icon_{name}.png"))

    subprocess.run(
        ["iconutil", "-c", "icns", iconset_dir, "-o", icns_path],
        check=True
    )

    import shutil
    shutil.rmtree(iconset_dir)
    print(f"Created: {icns_path}")


def create_ico(png_path: str, ico_path: str):
    """Create Windows .ico file from PNG."""
    img = Image.open(png_path).convert("RGBA")

    sizes = [16, 32, 48, 64, 128, 256]
    images = [img.resize((s, s), Image.LANCZOS) for s in sizes]

    # Save largest first, append smaller
    images[-1].save(
        ico_path,
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=images[:-1]
    )
    print(f"Created: {ico_path}")


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Generate 1024x1024 master icon
    print("Generating icon...")
    icon = draw_icon(1024)

    png_path = os.path.join(script_dir, "icon.png")
    icon.save(png_path, "PNG")
    print(f"Created: {png_path}")

    # Create .icns for macOS
    icns_path = os.path.join(script_dir, "icon.icns")
    try:
        create_icns(png_path, icns_path)
    except Exception as e:
        print(f"Could not create .icns (need macOS iconutil): {e}")

    # Create .ico for Windows
    ico_path = os.path.join(script_dir, "icon.ico")
    try:
        create_ico(png_path, ico_path)
    except Exception as e:
        print(f"Could not create .ico: {e}")


if __name__ == "__main__":
    main()
