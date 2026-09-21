"""Genera packaging/agentebc.ico desde images/logo-app.png con fondo transparente."""

from __future__ import annotations

from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "images" / "logo-app.png"
DST = ROOT / "packaging" / "agentebc.ico"
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def remove_outer_white(img: Image.Image, tolerance: int = 20) -> Image.Image:
    rgba = img.convert("RGBA")
    data = np.array(rgba)
    h, w = data.shape[:2]
    visited = np.zeros((h, w), dtype=bool)

    def is_background(px: np.ndarray) -> bool:
        r, g, b = int(px[0]), int(px[1]), int(px[2])
        return r >= 255 - tolerance and g >= 255 - tolerance and b >= 255 - tolerance

    q: deque[tuple[int, int]] = deque()
    for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        if is_background(data[y, x]):
            visited[y, x] = True
            q.append((x, y))

    for x in range(w):
        for y in (0, h - 1):
            if not visited[y, x] and is_background(data[y, x]):
                visited[y, x] = True
                q.append((x, y))
    for y in range(h):
        for x in (0, w - 1):
            if not visited[y, x] and is_background(data[y, x]):
                visited[y, x] = True
                q.append((x, y))

    while q:
        x, y = q.popleft()
        data[y, x, 3] = 0
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h and not visited[ny, nx] and is_background(data[ny, nx]):
                visited[ny, nx] = True
                q.append((nx, ny))

    return Image.fromarray(data)


def main() -> None:
    if not SRC.is_file():
        raise SystemExit(f"No se encontró {SRC}")

    img = Image.open(SRC)
    if img.mode != "RGBA":
        img = remove_outer_white(img)
        img.save(SRC, format="PNG")
    else:
        corners = [img.getpixel((0, 0)), img.getpixel((img.width - 1, 0))]
        if all(px[3] == 255 and px[0] >= 235 and px[1] >= 235 and px[2] >= 235 for px in corners):
            img = remove_outer_white(img)
            img.save(SRC, format="PNG")

    img.save(DST, format="ICO", sizes=ICO_SIZES)
    print(f"Icono generado: {DST}")


if __name__ == "__main__":
    main()
