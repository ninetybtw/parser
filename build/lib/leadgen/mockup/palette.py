"""Палитра из логотипа: доминирующие цвета → основной, акцентный, цвет текста.

Без нейросетей: квантуем картинку до нескольких цветов, отбрасываем фон
(почти белый/чёрный/прозрачный), берём самый «весомый» насыщенный цвет.
Контраст текста считаем по WCAG, чтобы кнопки читались.
"""

from __future__ import annotations

import colorsys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

DEFAULT_PRIMARY = (37, 99, 235)


@dataclass(frozen=True)
class Palette:
    primary: str
    primary_dark: str
    accent: str
    on_primary: str
    soft: str

    def as_dict(self) -> dict[str, str]:
        return self.__dict__.copy()


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def luminance(rgb: tuple[int, int, int]) -> float:
    def ch(c: int) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (ch(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _shift(rgb: tuple[int, int, int], lightness: float) -> tuple[int, int, int]:
    h, l, s = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
    r, g, b = colorsys.hls_to_rgb(h, max(0.0, min(1.0, lightness)), s)
    return round(r * 255), round(g * 255), round(b * 255)


def _darken_until_readable(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    """Белый текст на основном цвете должен иметь контраст ≥ 4.5 — иначе затемняем."""
    h, l, s = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
    while contrast(rgb, (255, 255, 255)) < 4.5 and l > 0.15:
        l -= 0.04
        rgb = _shift(rgb, l)
    return rgb


def dominant_colors(image: Image.Image, n: int = 6) -> list[tuple[tuple[int, int, int], int]]:
    img = image.convert("RGBA")
    img.thumbnail((128, 128))
    background = Image.new("RGBA", img.size, (255, 255, 255, 255))
    background.alpha_composite(img)
    quant = background.convert("RGB").quantize(colors=n, method=Image.Quantize.MEDIANCUT)
    pal = quant.getpalette() or []
    counts = sorted(quant.getcolors() or [], reverse=True)
    return [(tuple(pal[i * 3:i * 3 + 3]), count) for count, i in counts]  # type: ignore[misc]


def palette_from_colors(colors: list[tuple[tuple[int, int, int], int]]) -> Palette:
    scored = []
    for rgb, count in colors:
        h, l, s = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
        if l > 0.92 or l < 0.08 or s < 0.18:  # фон, чёрный текст, серое
            continue
        scored.append((count * (0.5 + s), rgb))
    scored.sort(reverse=True)
    primary = scored[0][1] if scored else DEFAULT_PRIMARY
    accent = scored[1][1] if len(scored) > 1 else _shift(primary, 0.6)
    primary = _darken_until_readable(primary)
    h, l, s = colorsys.rgb_to_hls(*(c / 255 for c in primary))
    return Palette(
        primary=_hex(primary),
        primary_dark=_hex(_shift(primary, l * 0.7)),
        accent=_hex(accent),
        on_primary="#ffffff",
        soft=_hex(_shift(primary, 0.95)),
    )


def palette_from_logo(path: str | Path | None) -> Palette:
    if not path:
        return palette_from_colors([])
    try:
        with Image.open(path) as img:
            return palette_from_colors(dominant_colors(img))
    except (OSError, ValueError, Image.DecompressionBombError):
        return palette_from_colors([])
