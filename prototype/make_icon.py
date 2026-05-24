"""Render Real Horizon brand icons for home-assistant/brands.

Outputs:
    docs/brand/icon@2x.png   (512x512)
    docs/brand/icon.png      (256x256)

Both are PNG with transparent background, square, hard-clipped to a circle
(HA renders the icon inside a rounded tile so a circular logo lines up nicely).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

SIZE = 512  # render at 2x then downsample for 1x

# Card palette.
SKY_TOP = (11, 36, 71)        # #0b2447 deep navy
SKY_BOT = (58, 124, 168)      # #3a7ca8 lighter horizon blue
MOUNTAIN = (31, 77, 42)       # #1f4d2a
MOUNTAIN_DARK = (14, 42, 22)  # #0e2a16
SUN = (251, 191, 36)          # #fbbf24
SUN_RIM = (180, 83, 9)        # #b45309


def render(size: int) -> Image.Image:
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    # Sky gradient (top -> horizon).
    sky = Image.new("RGBA", (size, size))
    draw = ImageDraw.Draw(sky)
    for y in range(size):
        f = y / (size - 1)
        c = (
            round(SKY_TOP[0] + (SKY_BOT[0] - SKY_TOP[0]) * f),
            round(SKY_TOP[1] + (SKY_BOT[1] - SKY_TOP[1]) * f),
            round(SKY_TOP[2] + (SKY_BOT[2] - SKY_TOP[2]) * f),
            255,
        )
        draw.line([(0, y), (size, y)], fill=c)

    # Sun: roughly between the two peaks, partially behind the mountain.
    sun_cx = round(size * 0.50)
    sun_cy = round(size * 0.46)
    sun_r = round(size * 0.13)

    # Soft glow around the sun (blurred yellow halo).
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse(
        (sun_cx - sun_r * 2, sun_cy - sun_r * 2,
         sun_cx + sun_r * 2, sun_cy + sun_r * 2),
        fill=(SUN[0], SUN[1], SUN[2], 90),
    )
    glow = glow.filter(ImageFilter.GaussianBlur(radius=size * 0.04))
    sky = Image.alpha_composite(sky, glow)

    # Sun disc.
    draw = ImageDraw.Draw(sky)
    draw.ellipse(
        (sun_cx - sun_r, sun_cy - sun_r, sun_cx + sun_r, sun_cy + sun_r),
        fill=SUN, outline=SUN_RIM, width=max(2, round(size * 0.008)),
    )

    # Mountain silhouette: two peaks with a saddle between them.
    s = size
    peaks = [
        (0, s),                          # bottom-left
        (0, round(s * 0.74)),            # left edge of land
        (round(s * 0.16), round(s * 0.66)),
        (round(s * 0.34), round(s * 0.40)),   # peak 1 (lower)
        (round(s * 0.46), round(s * 0.60)),   # saddle (sun peeks here)
        (round(s * 0.66), round(s * 0.28)),   # peak 2 (higher)
        (round(s * 0.82), round(s * 0.55)),
        (s,               round(s * 0.66)),
        (s, s),                          # bottom-right
    ]
    draw.polygon(peaks, fill=MOUNTAIN, outline=MOUNTAIN_DARK)

    # Clip everything to a circle inscribed in the canvas.
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    canvas.paste(sky, (0, 0), mask)
    return canvas


def main() -> None:
    out_dir = Path(__file__).resolve().parent.parent / "docs" / "brand"
    out_dir.mkdir(parents=True, exist_ok=True)

    full = render(SIZE)
    full.save(out_dir / "icon@2x.png")
    full.resize((256, 256), Image.LANCZOS).save(out_dir / "icon.png")
    print(f"wrote {out_dir / 'icon@2x.png'} (512x512)")
    print(f"wrote {out_dir / 'icon.png'} (256x256)")


if __name__ == "__main__":
    main()
