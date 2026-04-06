#!/usr/bin/env python3
"""
make_icons.py — Generate icon assets from a source PNG.

Usage:
    python assets/make_icons.py path/to/source.png

Outputs (relative to the project root, i.e. one level above this script):
    assets/icon.png        — 1024x1024 transparent PNG
    assets/icon.icns       — macOS icon bundle (requires iconutil; skipped elsewhere)
    assets/scroll-icon.ico — Windows/cross-platform ICO with multiple sizes
"""

import sys
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from PIL import Image

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TOLERANCE = 30          # Euclidean RGB distance threshold for background removal
ICO_SIZES  = [16, 32, 48, 64, 128, 256]
ICNS_SIZES = [16, 32, 128, 256, 512]   # @2x variants are generated automatically


# ---------------------------------------------------------------------------
# Background removal
# ---------------------------------------------------------------------------

def remove_background(img: Image.Image, tolerance: int = TOLERANCE) -> Image.Image:
    """
    Remove the background from *img* using a flood-fill seeded from all four
    corners.  Works on gradient backgrounds where no single colour dominates.

    Algorithm:
      1. Seed a queue with the 4 corner pixels.
      2. For each pixel in the queue, if it hasn't been visited yet, compare it
         to its seeding neighbour.  If the Euclidean RGB distance is within
         *tolerance*, mark it transparent and enqueue its 4 cardinal neighbours.
      3. Stop when the queue is empty.

    This naturally follows the background across gradients without removing
    foreground pixels that happen to share colours with the background corners.
    """
    rgba = img.convert("RGBA")
    pixels = rgba.load()
    w, h = rgba.size

    visited = [[False] * h for _ in range(w)]
    # Each queue entry is (x, y, seed_r, seed_g, seed_b) — the colour of the
    # pixel that caused this one to be enqueued, so tolerance is measured
    # against the local neighbourhood rather than a global background colour.
    from collections import deque
    queue: deque = deque()

    def _enqueue_corner(x: int, y: int) -> None:
        r, g, b, _ = pixels[x, y]
        queue.append((x, y, r, g, b))

    _enqueue_corner(0,     0    )
    _enqueue_corner(w - 1, 0    )
    _enqueue_corner(0,     h - 1)
    _enqueue_corner(w - 1, h - 1)

    tol_sq = tolerance * tolerance

    while queue:
        x, y, sr, sg, sb = queue.popleft()
        if x < 0 or x >= w or y < 0 or y >= h:
            continue
        if visited[x][y]:
            continue
        visited[x][y] = True

        r, g, b, a = pixels[x, y]
        dist_sq = (r - sr) ** 2 + (g - sg) ** 2 + (b - sb) ** 2
        if dist_sq > tol_sq:
            continue  # foreground pixel — stop propagating

        pixels[x, y] = (r, g, b, 0)   # erase background

        # Propagate to cardinal neighbours, seeding with *this* pixel's colour
        # so the tolerance check adapts to local gradient changes.
        for nx, ny in [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]:
            if 0 <= nx < w and 0 <= ny < h and not visited[nx][ny]:
                queue.append((nx, ny, r, g, b))

    return rgba


# ---------------------------------------------------------------------------
# ICNS generation (macOS only)
# ---------------------------------------------------------------------------

def make_icns(icon_png: Path, out_icns: Path) -> bool:
    """
    Build an .icns file from *icon_png* (1024×1024 RGBA PNG) using macOS
    ``iconutil``.  Returns True on success, False if iconutil is unavailable.
    """
    if not shutil.which("iconutil"):
        print("  [skip] iconutil not found — skipping .icns generation.")
        return False

    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "icon.iconset"
        iconset.mkdir()

        img = Image.open(icon_png).convert("RGBA")

        for size in ICNS_SIZES:
            for scale, suffix in [(1, ""), (2, "@2x")]:
                pixel_size = size * scale
                resized = img.resize((pixel_size, pixel_size), Image.NEAREST)
                filename = f"icon_{size}x{size}{suffix}.png"
                resized.save(iconset / filename, "PNG")
                print(f"  iconset/{filename}  ({pixel_size}×{pixel_size})")

        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(out_icns)],
            check=True,
        )
    print(f"  Saved: {out_icns}")
    return True


# ---------------------------------------------------------------------------
# ICO generation
# ---------------------------------------------------------------------------

def make_ico(icon_png: Path, out_ico: Path, sizes: list[int] = ICO_SIZES) -> None:
    """
    Save a multi-resolution .ico file from *icon_png* using Pillow.
    """
    img = Image.open(icon_png).convert("RGBA")
    frames = []
    for s in sizes:
        resized = img.resize((s, s), Image.NEAREST)
        frames.append(resized)
        print(f"  ico frame: {s}×{s}")

    # PIL's ICO encoder accepts a list of sizes via the `sizes` kwarg, but
    # passing pre-resized frames as append_images is more reliable.
    frames[0].save(
        out_ico,
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=frames[1:],
    )
    print(f"  Saved: {out_ico}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: python {sys.argv[0]} path/to/source.png")
        sys.exit(1)

    source_path = Path(sys.argv[1]).expanduser().resolve()
    if not source_path.exists():
        print(f"Error: file not found: {source_path}")
        sys.exit(1)

    # Resolve output directory: assets/ lives next to this script.
    assets_dir = Path(__file__).parent.resolve()
    icon_png  = assets_dir / "icon.png"
    icon_icns = assets_dir / "icon.icns"
    icon_ico  = assets_dir / "scroll-icon.ico"

    # ------------------------------------------------------------------
    # Step 1 — Load source image and detect background
    # ------------------------------------------------------------------
    print(f"\n[1/4] Loading source image: {source_path}")
    src = Image.open(source_path)
    print(f"      Size: {src.size[0]}×{src.size[1]},  mode: {src.mode}")

    # ------------------------------------------------------------------
    # Step 2 — Remove background, resize to 1024×1024, save PNG
    # ------------------------------------------------------------------
    print(f"\n[2/4] Removing background via flood-fill (tolerance={TOLERANCE}) and saving icon.png …")
    transparent = remove_background(src, TOLERANCE)

    # Resize to 1024×1024 with NEAREST to keep crisp pixel-art edges.
    resized = transparent.resize((1024, 1024), Image.NEAREST)
    resized.save(icon_png, "PNG")
    print(f"      Saved: {icon_png}")

    # ------------------------------------------------------------------
    # Step 3 — Generate .icns (macOS only)
    # ------------------------------------------------------------------
    print(f"\n[3/4] Generating icon.icns …")
    make_icns(icon_png, icon_icns)

    # ------------------------------------------------------------------
    # Step 4 — Generate .ico
    # ------------------------------------------------------------------
    print(f"\n[4/4] Generating scroll-icon.ico …")
    make_ico(icon_png, icon_ico)

    print("\nDone.")


if __name__ == "__main__":
    main()
