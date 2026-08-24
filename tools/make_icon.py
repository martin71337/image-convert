"""Draw the application icon and write the multi-resolution Windows ``.ico``.

**A build step, not a committed binary.** The artwork is the code in this file -
one authoritative representation - and the ``.ico`` is derived from it into build
output every time it is needed. A hand-made ``.ico`` committed beside the drawing
code would be a second representation of the same fact, and the two would
eventually disagree about what the program looks like.

**Drawn at 4x and reduced.** Pillow's ICO writer will resize for you, but
rasterising a 16 px icon directly gives jagged diagonals on the mountain and a
lumpy rounded corner. Every size is drawn into a 4x canvas and reduced with
LANCZOS, which is what makes the small sizes - the ones actually seen, in the
taskbar and the title bar - come out clean.

**The glyph is sized for 16 px first.** At 16 px there are sixteen pixels to say
everything with, so the icon is a solid tile, one large white photo shape, and a
single contrasting accent. Detail that cannot survive that reduction was left
out rather than drawn and lost.

Run it directly::

    py tools/make_icon.py                    # -> build/icon/imageconvert.ico
    py tools/make_icon.py --png preview.png  # also write a 512 px preview
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_OUTPUT = REPO_ROOT / "build" / "icon" / "imageconvert.ico"
"""Build output, git-ignored. ``imgconv.gui.icon`` looks here when running from
source; the two are pinned to each other by the suite so they cannot drift."""

ICON_SIZES = (16, 32, 48, 64, 128, 256)
"""The sizes Windows asks for: 16 and 32 for the taskbar and title bar, 48 for
Explorer's medium icons, 256 for the largest it will request."""

SUPERSAMPLE = 4

# The firm's palette, so the tool sits visually with the owner's other work.
GREEN = (0, 99, 81, 255)
GREEN_DEEP = (0, 74, 61, 255)
ORANGE = (248, 153, 29, 255)
WHITE = (255, 255, 255, 255)


def draw(size: int) -> Image.Image:
    """Render the icon at ``size`` pixels square, RGBA.

    All geometry is expressed as a fraction of ``size`` so the drawing is
    resolution-independent; nothing here is tuned to one particular size.
    """
    scale = size * SUPERSAMPLE
    image = Image.new("RGBA", (scale, scale), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)

    def units(fraction: float) -> float:
        return fraction * scale

    # The tile. A rounded square rather than a full bleed: Windows renders app
    # icons against every possible background, and a defined edge is what keeps
    # it from dissolving into a dark taskbar.
    pen.rounded_rectangle(
        (0, 0, scale - 1, scale - 1),
        radius=units(0.22),
        fill=GREEN,
    )

    # The photograph: a white rectangle occupying most of the tile. This is the
    # shape that has to survive reduction to 16 px, so it is large and plain.
    photo = (units(0.17), units(0.22), units(0.83), units(0.70))
    pen.rounded_rectangle(photo, radius=units(0.05), fill=WHITE)

    left, top, right, bottom = photo
    width = right - left
    height = bottom - top

    # Sun, then mountains, cut out of the white in the tile colour. Drawn as
    # solid shapes rather than outlines: an outline thinner than a pixel at the
    # target size disappears entirely.
    pen.ellipse(
        (
            left + width * 0.68,
            top + height * 0.16,
            left + width * 0.86,
            top + height * 0.44,
        ),
        fill=ORANGE,
    )

    pen.polygon(
        [
            (left + width * 0.04, bottom - height * 0.04),
            (left + width * 0.40, top + height * 0.42),
            (left + width * 0.72, bottom - height * 0.04),
        ],
        fill=GREEN_DEEP,
    )
    pen.polygon(
        [
            (left + width * 0.48, bottom - height * 0.04),
            (left + width * 0.72, top + height * 0.56),
            (left + width * 0.97, bottom - height * 0.04),
        ],
        fill=GREEN,
    )

    # The conversion arrow, along the bottom. One bold horizontal stroke with a
    # solid head - at 16 px it reduces to a short orange dash, which still reads
    # as motion from left to right and does not turn to mud.
    # Inset from the tile edge by the same margin as the photo above it, so the
    # arrowhead does not crowd the rounded corner.
    bar_top = units(0.795)
    bar_bottom = units(0.865)
    pen.rectangle((units(0.20), bar_top, units(0.56), bar_bottom), fill=ORANGE)
    pen.polygon(
        [
            (units(0.52), units(0.745)),
            (units(0.78), units(0.83)),
            (units(0.52), units(0.915)),
        ],
        fill=ORANGE,
    )

    return image.resize((size, size), Image.LANCZOS)


def generate(output: Path = DEFAULT_OUTPUT, sizes: tuple[int, ...] = ICON_SIZES) -> Path:
    """Draw every size and write the ``.ico``. Returns its path.

    Staged and renamed, like every other file this project writes: a build
    interrupted halfway leaves either the previous icon or nothing, never a
    truncated one that Explorer would go on to cache.
    """
    ordered = sorted(sizes)
    images = [draw(size) for size in ordered]
    largest = images[-1]

    output.parent.mkdir(parents=True, exist_ok=True)
    staged = output.with_name(output.name + ".partial")
    largest.save(
        staged,
        format="ICO",
        sizes=[(s, s) for s in ordered],
        append_images=images[:-1],
    )
    staged.replace(output)
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--png",
        type=Path,
        default=None,
        help="also write a 512 px PNG preview, for looking at the artwork",
    )
    arguments = parser.parse_args(argv)

    written = generate(arguments.output)
    print(f"wrote {written} ({written.stat().st_size:,} bytes, "
          f"{', '.join(f'{s}x{s}' for s in ICON_SIZES)})")

    if arguments.png:
        arguments.png.parent.mkdir(parents=True, exist_ok=True)
        draw(512).save(arguments.png)
        print(f"wrote {arguments.png}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
