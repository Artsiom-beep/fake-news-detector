from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw


def _draw_icon(size: int) -> Image.Image:
    canvas = 256
    scale = size / canvas

    def p(value: float) -> int:
        return round(value * scale)

    image = Image.new("RGBA", (size, size), "#fff4dc")
    draw = ImageDraw.Draw(image)

    for y in range(size):
        amount = y / max(size - 1, 1)
        r = round(255 * (1 - amount) + 159 * amount)
        g = round(244 * (1 - amount) + 63 * amount)
        b = round(220 * (1 - amount) + 51 * amount)
        draw.line((0, y, size, y), fill=(r, g, b, 255))

    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=p(56), outline="#fff8ec", width=max(1, p(3)))
    draw.pieslice((p(24), p(138), p(250), p(318)), 180, 360, fill=(111, 45, 43, 42))
    draw.rounded_rectangle((p(57), p(55), p(170), p(192)), radius=p(24), fill="#fffaf4")

    for y, width in [(85, 62), (112, 73), (139, 44)]:
        draw.line((p(77), p(y), p(77 + width), p(y)), fill="#b8573c", width=p(12), joint="curve")

    draw.ellipse((p(99), p(94), p(207), p(202)), fill="#235f58")
    draw.line((p(190), p(187), p(221), p(218)), fill="#235f58", width=p(18))
    draw.ellipse((p(116), p(111), p(190), p(185)), fill="#f1bc72", outline="#fffaf4", width=p(9))
    draw.line((p(136), p(149), p(149), p(162), p(176), p(128)), fill="#21574f", width=p(11), joint="curve")
    draw.ellipse((p(128), p(123), p(144), p(139)), fill=(255, 250, 244, 215))
    return image


def build_icon(out_path: Path, png_path: Path | None = None) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [_draw_icon(size) for size in sizes]
    images[-1].save(out_path, sizes=[(size, size) for size in sizes], append_images=images[:-1])
    if png_path is not None:
        png_path.parent.mkdir(parents=True, exist_ok=True)
        images[-1].save(png_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the Windows icon used by the desktop build.")
    parser.add_argument("--out", default="build/icon/FakeNewsDetector.ico", help="Output .ico path.")
    parser.add_argument("--png", default="", help="Optional PNG preview path.")
    args = parser.parse_args()

    png_path = Path(args.png) if args.png else None
    build_icon(Path(args.out), png_path=png_path)
    print(f"Generated {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
