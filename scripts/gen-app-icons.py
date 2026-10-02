# -*- coding: utf-8 -*-
"""Генератор 512x512 png-иконок для витрины (assets/icon.png).

Источники:
  - Wishlot: foreground из res/drawable (готовый арт) + тёмный squircle.
  - ChargeForecast: растеризация адаптивного вектора (background + lightning).
  - YandexMusicDownloader, InstagramTracker: плоская дизайн-иконка.
"""
import os
from PIL import Image, ImageDraw

S = 512
Q = 4                 # supersample
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons_out")
os.makedirs(OUT, exist_ok=True)


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def gradient(size, top, bottom, diagonal=False, stops=None):
    """Линейный градиент — попиксельно, без швов. stops: список (t, color)."""
    w, h = size

    def color_at(t):
        if stops:
            for i in range(len(stops) - 1):
                t0, c0 = stops[i]
                t1, c1 = stops[i + 1]
                if t0 <= t <= t1:
                    k = 0 if t1 == t0 else (t - t0) / (t1 - t0)
                    return lerp(c0, c1, k)
            return stops[-1][1]
        return lerp(top, bottom, t)

    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        if diagonal:
            for x in range(w):
                px[x, y] = color_at((x + y) / (w + h))
        else:
            c = color_at(y / h)
            for x in range(w):
                px[x, y] = c
    return img


def squircle_mask(size, radius):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size[0] - 1, size[1] - 1],
                                        radius=radius, fill=255)
    return m


def squircle_icon(top, bottom, radius=112, diagonal=False, stops=None):
    """RGB-иконка: градиент, обрезанный по squircle, углы прозрачные."""
    big = (S * Q, S * Q)
    bg = gradient((S, S), top, bottom, diagonal, stops).resize(big, Image.BICUBIC).convert("RGBA")
    bg.putalpha(squircle_mask(big, radius * Q))
    return bg


def apply_squircle(img, radius=112):
    """Обрезает готовую иконку по squircle с сглаживанием (маска рисуется в 4x)."""
    mask = squircle_mask((S * Q, S * Q), radius * Q).resize((S, S), Image.LANCZOS)
    out = img.convert("RGBA")
    out.putalpha(mask)
    return out


def finalize(img, name):
    out = img.resize((S, S), Image.LANCZOS)
    path = os.path.join(OUT, name)
    out.save(path, "PNG")
    print("saved", path, out.size, out.mode)


# ---------------------------------------------------------------- Wishlot
def wishlot():
    """Готовый арт из res/drawable: во всю рамку + squircle."""
    src = r"C:\projects\Wishlot\app\src\main\res\drawable\ic_launcher_foreground.png"
    fg = Image.open(src).convert("RGBA").resize((S, S), Image.LANCZOS)
    finalize(apply_squircle(fg), "wishlot.png")


# ---------------------------------------------------------- ChargeForecast
def charge_forecast():
    # из app/src/main/res/drawable/ic_launcher_{background,foreground}.xml (viewport 108)
    base = squircle_icon((11, 18, 32), (17, 27, 46), radius=112, diagonal=True)
    bolt = [(58, 28), (36, 58), (52, 58), (48, 80), (72, 46), (56, 46)]
    scale = (S * Q) / 108.0 * 1.35          # центр вектора — (54,54)
    c = S * Q / 2
    pts = [((x - 54) * scale + c, (y - 54) * scale + c) for x, y in bolt]
    layer = Image.new("RGBA", (S * Q, S * Q), (0, 0, 0, 0))
    ImageDraw.Draw(layer).polygon(pts, fill=(209, 255, 0, 255))
    base.alpha_composite(layer)
    finalize(base, "charge-forecast.png")


# ------------------------------------------------------ YandexMusicDownloader
def yandex_music_downloader():
    base = squircle_icon((255, 61, 0), (150, 20, 0), radius=112, diagonal=True)
    q = Q
    layer = Image.new("RGBA", (S * q, S * q), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    ink = (255, 255, 255, 255)
    # нота: голова + штиль + флажок
    head = [int(v * S * q) for v in (0.28, 0.60, 0.45, 0.74)]
    d.ellipse(head, fill=ink)
    stem_x = head[2] - int(0.045 * S * q)
    stem_top = int(0.30 * S * q)
    d.rectangle([stem_x, stem_top, stem_x + int(0.045 * S * q), int(0.67 * S * q)], fill=ink)
    d.polygon([(stem_x + int(0.045 * S * q), stem_top),
               (stem_x + int(0.045 * S * q), stem_top + int(0.07 * S * q)),
               (int(0.65 * S * q), int(0.45 * S * q)),
               (int(0.65 * S * q), int(0.36 * S * q))], fill=ink)
    # стрелка «скачать» справа внизу
    ax, ay = int(0.68 * S * q), int(0.54 * S * q)
    w = int(0.095 * S * q)
    d.rectangle([ax - w // 2, ay, ax + w // 2, ay + int(0.13 * S * q)], fill=ink)
    d.polygon([(ax - int(0.13 * S * q), ay + int(0.09 * S * q)),
               (ax + int(0.13 * S * q), ay + int(0.09 * S * q)),
               (ax, ay + int(0.26 * S * q))], fill=ink)
    base.alpha_composite(layer)
    finalize(base, "yandex-music-downloader.png")


# ------------------------------------------------------------ InstagramTracker
def instagram_tracker():
    stops = [(0.00, (253, 204, 100)), (0.25, (250, 126, 30)),
             (0.50, (214, 41, 118)), (0.75, (150, 47, 199)),
             (1.00, (79, 91, 213))]
    base = squircle_icon(None, None, radius=112, diagonal=True, stops=stops)
    q = Q
    layer = Image.new("RGBA", (S * q, S * q), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    ink = (255, 255, 255, 255)
    pad = int(0.20 * S * q)
    d.rounded_rectangle([pad, pad, S * q - pad, S * q - pad],
                        radius=int(0.17 * S * q), outline=ink,
                        width=int(0.045 * S * q))
    r = int(0.155 * S * q)
    c = S * q // 2
    d.ellipse([c - r, c - r, c + r, c + r], outline=ink, width=int(0.045 * S * q))
    dr = int(0.035 * S * q)
    dot_x = S * q - pad - int(0.16 * S * q)
    dot_y = pad + int(0.10 * S * q)
    d.ellipse([dot_x - dr, dot_y - dr, dot_x + dr, dot_y + dr], fill=ink)
    base.alpha_composite(layer)
    finalize(base, "instagram-tracker.png")


if __name__ == "__main__":
    wishlot()
    charge_forecast()
    yandex_music_downloader()
    instagram_tracker()
