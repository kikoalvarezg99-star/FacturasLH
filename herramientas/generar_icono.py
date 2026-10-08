"""Genera el icono del programa (assets/logo.ico e icono64.png).

Uso: python herramientas/generar_icono.py [variante]
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

RAIZ = Path(__file__).resolve().parent.parent
FUENTE = "/usr/share/fonts/opentype/inter/InterDisplay-Black.otf"
NARANJA_1, NARANJA_2 = (244, 112, 38), (176, 52, 10)
CARBON_1, CARBON_2 = (52, 58, 66), (24, 27, 31)


def degradado(s, c1, c2):
    g = Image.new("RGB", (1, s))
    for y in range(s):
        t = y / (s - 1)
        g.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(c1, c2)))
    return g.resize((s, s))


def cuadrado(s, c1, c2, margen=0.035, radio=0.23):
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    m = int(s * margen)
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle([m, m, s - m, s - m], radius=int(s * radio), fill=255)
    img.paste(degradado(s, c1, c2), (0, 0), mask)
    return img


def rombo(d, s, ancho, color, escala=1.0, cy=0.5):
    w, h = 0.40 * escala, 0.27 * escala
    pts = [(0.5 - w, cy), (0.5, cy - h), (0.5 + w, cy), (0.5, cy + h)]
    pts = [(x * s, y * s) for x, y in pts]
    d.line(pts + pts[:2], fill=color, width=int(s * ancho), joint="curve")


def texto(d, s, t, tam, color, cy=0.5):
    f = ImageFont.truetype(FUENTE, int(s * tam))
    x0, y0, x1, y1 = d.textbbox((0, 0), t, font=f)
    d.text(((s - (x1 - x0)) / 2 - x0, s * cy - (y1 - y0) / 2 - y0), t, font=f, fill=color)


def variante(n, s=1024, pequeno=False):
    blanco = (255, 255, 255, 255)
    if n == "A":  # naranja, rombo doble blanco y LH
        img = cuadrado(s, NARANJA_1, NARANJA_2)
        d = ImageDraw.Draw(img)
        if pequeno:
            texto(d, s, "LH", 0.50, blanco)
        else:
            rombo(d, s, 0.036, blanco, escala=0.93)
            rombo(d, s, 0.015, blanco, escala=0.79)
            texto(d, s, "LH", 0.25, blanco)
    elif n == "B":  # carbón con rombo naranja relleno
        img = cuadrado(s, CARBON_1, CARBON_2)
        d = ImageDraw.Draw(img)
        w, h = 0.42, 0.29
        pts = [(0.5 - w, 0.5), (0.5, 0.5 - h), (0.5 + w, 0.5), (0.5, 0.5 + h)]
        pts = [(x * s, y * s) for x, y in pts]
        d.polygon(pts, fill=NARANJA_1)
        d.line(pts + pts[:2], fill=NARANJA_1, width=int(s * 0.06), joint="curve")
        texto(d, s, "LH", 0.50 if pequeno else 0.29, blanco)
    else:  # C: hoja de factura con sello LH
        img = cuadrado(s, NARANJA_1, NARANJA_2)
        d = ImageDraw.Draw(img)
        x0, y0, x1, y1 = 0.22 * s, 0.14 * s, 0.78 * s, 0.86 * s
        pliegue = 0.14 * s
        d.polygon([(x0, y0), (x1 - pliegue, y0), (x1, y0 + pliegue), (x1, y1), (x0, y1)], fill=blanco)
        d.polygon([(x1 - pliegue, y0), (x1 - pliegue, y0 + pliegue), (x1, y0 + pliegue)], fill=(230, 214, 204, 255))
        if not pequeno:
            for i, l in enumerate([0.36, 0.44, 0.52]):
                d.rounded_rectangle([x0 + 0.07 * s, l * s, x1 - (0.07 + 0.12 * (i == 2)) * s, l * s + 0.035 * s],
                                    radius=int(0.017 * s), fill=(214, 211, 209, 255))
        texto(d, s, "LH", 0.30 if not pequeno else 0.42, NARANJA_2 + (255,), cy=0.70 if not pequeno else 0.58)
    return img


def generar(n):
    grandes = {k: variante(n).resize((k, k), Image.LANCZOS) for k in (256, 128, 64, 48)}
    peq = variante(n, pequeno=True)
    chicos = {k: peq.resize((k, k), Image.LANCZOS) for k in (40, 32, 24, 20, 16)}
    return {**grandes, **chicos}


if __name__ == "__main__":
    n = sys.argv[1] if len(sys.argv) > 1 else "A"
    tam = generar(n)
    tam[256].save(RAIZ / "assets" / "logo.ico", sizes=[(k, k) for k in sorted(tam)],
                  append_images=[tam[k] for k in sorted(tam) if k != 256])
    tam[64].save(RAIZ / "assets" / "icono64.png")
    tam[256].save(RAIZ / "assets" / "icono256.png")
    print("Icono generado:", n)
