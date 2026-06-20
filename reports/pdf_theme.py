"""
Sentinel XO — Sistema de diseño compartido para reportes PDF (ReportLab)
========================================================================

Un único módulo con la paleta, tipografía de marca (IBM Plex) y los
componentes reutilizables (header, secciones, tarjetas KPI, tablas, pills,
barras de progreso, callouts, footer). Todos los generadores de reporte
(generator, device_report, security_report, system_overview) importan de aquí
para verse idénticos y para no duplicar helpers.

Sin dependencias de Django: recibe primitivos (strings, números, listas), no
objetos del ORM. Eso permite testear/previsualizar el diseño con datos ficticios.

Las fuentes IBM Plex (.ttf) deben vivir en `reports/fonts/`. Si no están, se
degrada con elegancia a Helvetica/Courier sin romper nada.
"""
import os
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle
from reportlab.graphics.shapes import Drawing, Rect, Line, Circle, Polygon
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


# ════════════════════════════════════════════════════════════════════════════
#  GEOMETRÍA
# ════════════════════════════════════════════════════════════════════════════
PAGE_W, PAGE_H = A4
ML = MR = 16 * mm
MT = 14 * mm
MB = 20 * mm
CW = PAGE_W - ML - MR


# ════════════════════════════════════════════════════════════════════════════
#  PALETA — clara para impresión, con acentos de marca
# ════════════════════════════════════════════════════════════════════════════
INK      = colors.HexColor("#0B1220")   # navy header
INK_2    = colors.HexColor("#16203A")   # navy secundario
TEXT     = colors.HexColor("#1F2937")   # texto fuerte
BODY     = colors.HexColor("#3A4658")   # texto cuerpo
MUTED    = colors.HexColor("#6B7688")   # texto atenuado
FAINT    = colors.HexColor("#98A2B3")   # muy atenuado
LINE     = colors.HexColor("#E5E9F0")   # hairline
LINE_2   = colors.HexColor("#EFF2F7")   # hairline suave
PAPER    = colors.white
SUBTLE   = colors.HexColor("#F7F9FC")   # fondo tarjeta
SUBTLE_2 = colors.HexColor("#FBFCFE")   # zebra

BRAND    = colors.HexColor("#2F7BFF")   # azul marca
BRAND_DK = colors.HexColor("#1F5FE0")
CYAN     = colors.HexColor("#0FA9C8")   # cian legible (no neón)
PURPLE   = colors.HexColor("#7C5CFC")
GREEN    = colors.HexColor("#10B981")
AMBER    = colors.HexColor("#E0930B")
RED      = colors.HexColor("#E5484D")

# Header band sobre INK
ON_INK   = colors.HexColor("#EAF2FF")
ON_INK_2 = colors.HexColor("#9DB2D6")
KICKER   = colors.HexColor("#7FB0FF")

# Pills (bg, fg)
PILL = {
    "green":  (colors.HexColor("#E7F8F1"), colors.HexColor("#0B7A55")),
    "amber":  (colors.HexColor("#FFF3DE"), colors.HexColor("#92610A")),
    "red":    (colors.HexColor("#FDEBEC"), colors.HexColor("#B42318")),
    "blue":   (colors.HexColor("#E8F0FF"), colors.HexColor("#1E50C9")),
    "cyan":   (colors.HexColor("#E2F6FB"), colors.HexColor("#0C748B")),
    "purple": (colors.HexColor("#EFEAFE"), colors.HexColor("#5A3FD6")),
    "slate":  (colors.HexColor("#F0F3F8"), colors.HexColor("#586173")),
}

MESES = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio",
    7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre",
}


# ════════════════════════════════════════════════════════════════════════════
#  TIPOGRAFÍA — IBM Plex con fallback a Helvetica/Courier
# ════════════════════════════════════════════════════════════════════════════
def _font_dir():
    env = os.environ.get("SENTINEL_PDF_FONT_DIR")
    if env and Path(env).is_dir():
        return Path(env)
    return Path(__file__).resolve().parent / "fonts"


def _register_fonts():
    """Registra IBM Plex; devuelve dict de nombres lógicos → fuente real."""
    d = _font_dir()
    faces = {
        "SANS":    "IBMPlexSans-Regular.ttf",
        "SANS_MD": "IBMPlexSans-Medium.ttf",
        "SANS_SB": "IBMPlexSans-SemiBold.ttf",
        "SANS_BD": "IBMPlexSans-Bold.ttf",
        "MONO":    "IBMPlexMono-Regular.ttf",
        "MONO_MD": "IBMPlexMono-Medium.ttf",
        "MONO_SB": "IBMPlexMono-SemiBold.ttf",
    }
    reg = {
        "SANS": "PlexSans", "SANS_MD": "PlexSans-Md", "SANS_SB": "PlexSans-Sb",
        "SANS_BD": "PlexSans-Bd", "MONO": "PlexMono", "MONO_MD": "PlexMono-Md",
        "MONO_SB": "PlexMono-Sb",
    }
    try:
        for key, fname in faces.items():
            path = d / fname
            if not path.exists():
                raise FileNotFoundError(path)
            pdfmetrics.registerFont(TTFont(reg[key], str(path)))
        # Familias para que <b> funcione en markup de Paragraph
        pdfmetrics.registerFontFamily(
            "PlexSans", normal="PlexSans", bold="PlexSans-Bd",
            italic="PlexSans", boldItalic="PlexSans-Bd")
        pdfmetrics.registerFontFamily(
            "PlexMono", normal="PlexMono", bold="PlexMono-Sb",
            italic="PlexMono", boldItalic="PlexMono-Sb")
        return reg, True
    except Exception:
        return {
            "SANS": "Helvetica", "SANS_MD": "Helvetica", "SANS_SB": "Helvetica-Bold",
            "SANS_BD": "Helvetica-Bold", "MONO": "Courier", "MONO_MD": "Courier",
            "MONO_SB": "Courier-Bold",
        }, False


_F, FONTS_OK = _register_fonts()
FONT      = _F["SANS"]
FONT_MD   = _F["SANS_MD"]
FONT_SB   = _F["SANS_SB"]
FONT_BD   = _F["SANS_BD"]
MONO      = _F["MONO"]
MONO_MD   = _F["MONO_MD"]
MONO_SB   = _F["MONO_SB"]


# ════════════════════════════════════════════════════════════════════════════
#  PÁRRAFOS
# ════════════════════════════════════════════════════════════════════════════
def ps(name, **kw):
    d = dict(fontName=FONT, fontSize=9, textColor=BODY, leading=13)
    d.update(kw)
    return ParagraphStyle(name, **d)


def P(txt, **kw):
    return Paragraph(str(txt), ps("p", **kw))


# ════════════════════════════════════════════════════════════════════════════
#  LOGO (marca vectorial: diamante + cruz + núcleo)
# ════════════════════════════════════════════════════════════════════════════
def logo_mark(size=26, color=ON_INK, core=BRAND):
    d = Drawing(size, size)
    c = size / 2.0
    r = size * 0.40
    sw = max(0.8, size * 0.045)
    d.add(Polygon([c, c - r, c + r, c, c, c + r, c - r, c],
                  strokeColor=color, strokeWidth=sw, fillColor=None))
    d.add(Line(c, c - r * 0.66, c, c + r * 0.66, strokeColor=color, strokeWidth=sw))
    d.add(Line(c - r * 0.66, c, c + r * 0.66, c, strokeColor=core, strokeWidth=sw))
    d.add(Circle(c, c, size * 0.075, fillColor=core, strokeColor=None))
    return d


# ════════════════════════════════════════════════════════════════════════════
#  HEADER BAND
# ════════════════════════════════════════════════════════════════════════════
def header_band(company, kicker, title, meta=None):
    """Banda superior navy: logo + marca a la izquierda, reporte/periodo a la derecha."""
    left_stack = Table([
        [Paragraph(company, ps("hco", fontName=FONT_BD, fontSize=16,
                               textColor=PAPER, leading=19))],
        [Paragraph("Plataforma de Monitoreo y Seguridad", ps("htag", fontName=FONT,
                   fontSize=8, textColor=ON_INK_2, leading=11))],
    ], colWidths=[None])
    left_stack.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (0, 0), 0), ("BOTTOMPADDING", (0, 0), (0, 0), 1),
        ("TOPPADDING", (0, 1), (0, 1), 0), ("BOTTOMPADDING", (0, 1), (0, 1), 0),
    ]))
    left = Table([[logo_mark(28), left_stack]], colWidths=[34, None])
    left.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))

    right_rows = [
        [Paragraph(kicker.upper(), ps("hk", fontName=MONO_MD, fontSize=7.5,
                   textColor=KICKER, leading=11, alignment=TA_RIGHT))],
        [Paragraph(title, ps("ht", fontName=FONT_BD, fontSize=15,
                   textColor=PAPER, leading=18, alignment=TA_RIGHT))],
    ]
    if meta:
        right_rows.append([Paragraph(meta, ps("hm", fontName=FONT, fontSize=8,
                          textColor=ON_INK_2, leading=11, alignment=TA_RIGHT))])
    right = Table(right_rows, colWidths=[None])
    right.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))

    band = Table([[left, right]], colWidths=[CW * 0.55, CW * 0.45])
    band.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), INK),
        ("LEFTPADDING", (0, 0), (-1, -1), 18),
        ("RIGHTPADDING", (0, 0), (-1, -1), 18),
        ("TOPPADDING", (0, 0), (-1, -1), 16),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 16),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))

    rule = Drawing(CW, 3)
    rule.add(Rect(0, 0, CW, 3, fillColor=BRAND, strokeColor=None))
    rule.add(Rect(0, 0, 96, 3, fillColor=CYAN, strokeColor=None))

    return [band, rule, Spacer(1, 14)]


# ════════════════════════════════════════════════════════════════════════════
#  INFO STRIP (metadatos en columnas con divisores)
# ════════════════════════════════════════════════════════════════════════════
def info_strip(cells, accent=BRAND):
    """cells = [(label, value, big?), ...]  → tira de metadatos."""
    cols = []
    widths = []
    n = len(cells)
    big_size = 12.5 if n <= 4 else 10.5
    for label, value, *rest in cells:
        big = rest[0] if rest else False
        cols.append(Table([
            [Paragraph(label.upper(), ps("isl", fontName=MONO_MD, fontSize=6.8,
                       textColor=MUTED, leading=10))],
            [Paragraph(str(value), ps("isv", fontName=FONT_SB if big else FONT_MD,
                       fontSize=big_size if big else 9.5, textColor=TEXT,
                       leading=(big_size + 3) if big else 13))],
        ], colWidths=[None]))
        widths.append(CW / n)
    for c in cols:
        c.setStyle(TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (0, 0), 0), ("BOTTOMPADDING", (0, 0), (0, 0), 3),
            ("TOPPADDING", (0, 1), (0, 1), 0), ("BOTTOMPADDING", (0, 1), (0, 1), 0),
        ]))
    strip = Table([cols], colWidths=widths)
    pad = 13 if n <= 4 else 10
    style = [
        ("BACKGROUND", (0, 0), (-1, -1), SUBTLE),
        ("LEFTPADDING", (0, 0), (-1, -1), pad),
        ("RIGHTPADDING", (0, 0), (-1, -1), pad),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 2, accent),
        ("BOX", (0, 0), (-1, -1), 0.75, LINE),
    ]
    for i in range(n - 1):
        style.append(("LINEAFTER", (i, 0), (i, 0), 0.75, LINE))
    strip.setStyle(TableStyle(style))
    return strip


# ════════════════════════════════════════════════════════════════════════════
#  SECTION HEADER (editorial: tick + título + subtítulo + hairline)
# ════════════════════════════════════════════════════════════════════════════
def section(title, subtitle="", accent=BRAND):
    tick = Drawing(10, 16)
    tick.add(Rect(0, 1, 4, 14, fillColor=accent, strokeColor=None, rx=1, ry=1))
    stack_rows = [[Paragraph(title.upper(), ps("sh", fontName=FONT_SB, fontSize=11,
                  textColor=TEXT, leading=14))]]
    if subtitle:
        stack_rows.append([Paragraph(subtitle, ps("ss", fontName=FONT, fontSize=8,
                          textColor=MUTED, leading=11))])
    stack = Table(stack_rows, colWidths=[None])
    stack.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (0, 0), 0), ("BOTTOMPADDING", (0, 0), (0, 0), 1),
        ("TOPPADDING", (0, -1), (0, -1), 0), ("BOTTOMPADDING", (0, -1), (0, -1), 0),
    ]))
    head = Table([[tick, stack]], colWidths=[12, None])
    head.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("VALIGN", (0, 0), (0, 0), "TOP"),
    ]))
    rule = Drawing(CW, 1)
    rule.add(Line(0, 0.5, CW, 0.5, strokeColor=LINE, strokeWidth=0.75))
    return [head, Spacer(1, 5), rule, Spacer(1, 10)]


# ════════════════════════════════════════════════════════════════════════════
#  KPI CARDS
# ════════════════════════════════════════════════════════════════════════════
def kpi_cards(items, gap=8, value_size=None):
    """items = [(label, value, sub, accent_color), ...] → fila de tarjetas."""
    n = len(items)
    vsize = value_size or (19 if n <= 4 else 16.5)
    cards = []
    for label, value, sub, accent in items:
        card = Table([
            [Paragraph(label.upper(), ps("kl", fontName=MONO_MD, fontSize=6.8,
                       textColor=MUTED, leading=10))],
            [Paragraph(str(value), ps("kv", fontName=MONO_SB, fontSize=vsize,
                       textColor=accent, leading=vsize + 3))],
            [Paragraph(sub, ps("ks", fontName=FONT, fontSize=7.3,
                       textColor=FAINT, leading=10))],
        ], colWidths=[None])
        card.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), SUBTLE),
            ("BOX", (0, 0), (-1, -1), 0.75, LINE),
            ("LINEABOVE", (0, 0), (-1, 0), 2.4, accent),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (0, 0), 12),
            ("BOTTOMPADDING", (0, 0), (0, 0), 4),
            ("TOPPADDING", (0, 1), (0, 1), 0),
            ("BOTTOMPADDING", (0, 1), (0, 1), 3),
            ("TOPPADDING", (0, 2), (0, 2), 0),
            ("BOTTOMPADDING", (0, 2), (0, 2), 12),
        ]))
        cards.append(card)
    total_gap = gap * (n - 1)
    cw = (CW - total_gap) / n
    row = Table([cards], colWidths=[cw] * n)
    style = [
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    # gaps via padding interna
    for i in range(n):
        lp = gap / 2 if i > 0 else 0
        rp = gap / 2 if i < n - 1 else 0
        style.append(("LEFTPADDING", (i, 0), (i, 0), lp))
        style.append(("RIGHTPADDING", (i, 0), (i, 0), rp))
    row.setStyle(TableStyle(style))
    return row


# ════════════════════════════════════════════════════════════════════════════
#  PILLS / BADGES
# ════════════════════════════════════════════════════════════════════════════
def pill(txt, kind="slate"):
    bg, fg = PILL.get(kind, PILL["slate"])
    t = Table([[Paragraph(str(txt).upper(), ps("pl", fontName=FONT_SB, fontSize=6.8,
              textColor=fg, leading=9, alignment=TA_CENTER))]], colWidths=[None])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), bg),
        ("LEFTPADDING", (0, 0), (0, 0), 8), ("RIGHTPADDING", (0, 0), (0, 0), 8),
        ("TOPPADDING", (0, 0), (0, 0), 3), ("BOTTOMPADDING", (0, 0), (0, 0), 3),
    ]))
    return t


# ════════════════════════════════════════════════════════════════════════════
#  TABLAS
# ════════════════════════════════════════════════════════════════════════════
def th(txt, align=TA_LEFT):
    return Paragraph(str(txt).upper(), ps("th", fontName=FONT_SB, fontSize=7.3,
                     textColor=ON_INK, leading=10, alignment=align))


def td(txt, bold=False, color=TEXT, size=8.5, align=TA_LEFT, mono=False):
    fn = (MONO_MD if bold else MONO) if mono else (FONT_SB if bold else FONT)
    return Paragraph(str(txt), ps("td", fontName=fn, fontSize=size,
                     textColor=color, leading=12, alignment=align))


def table(rows, col_widths, aligns=None, zebra=True, repeat=True):
    """rows[0] = headers (usar th()); resto = celdas (td()/pill()/etc.)."""
    t = Table(rows, colWidths=col_widths, repeatRows=1 if repeat else 0)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), INK),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 1), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 11),
        ("RIGHTPADDING", (0, 0), (-1, -1), 11),
        ("LINEBELOW", (0, 1), (-1, -1), 0.6, LINE),
        ("LINEBELOW", (0, 0), (-1, 0), 0, INK),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    if zebra:
        style.append(("ROWBACKGROUNDS", (0, 1), (-1, -1), [PAPER, SUBTLE_2]))
    if aligns:
        for col, al in aligns.items():
            a = {"L": "LEFT", "C": "CENTER", "R": "RIGHT"}[al]
            style.append(("ALIGN", (col, 0), (col, -1), a))
    t.setStyle(TableStyle(style))
    return t


# ════════════════════════════════════════════════════════════════════════════
#  BARRAS DE PROGRESO
# ════════════════════════════════════════════════════════════════════════════
def progress(pct, color, width=64, show_label=True):
    if pct is None:
        return td("—", color=FAINT)
    p = max(0.0, min(100.0, float(pct)))
    bar = Drawing(width, 7)
    bar.add(Rect(0, 1, width, 5, fillColor=LINE, strokeColor=None, rx=2.5, ry=2.5))
    if p > 0:
        bar.add(Rect(0, 1, max(2.0, width * p / 100.0), 5, fillColor=color,
                     strokeColor=None, rx=2.5, ry=2.5))
    if not show_label:
        return bar
    return Table([[bar],
                  [Paragraph(f"{round(p, 1)}%", ps("pb", fontName=MONO, fontSize=7,
                   textColor=MUTED, leading=9))]], colWidths=[width])


def status_color(pct, warn=70, crit=90):
    if pct is None:
        return FAINT
    return GREEN if pct < warn else (AMBER if pct < crit else RED)


def temp_color(val):
    if val is None:
        return FAINT
    return GREEN if val < 70 else (AMBER if val < 85 else RED)


# ════════════════════════════════════════════════════════════════════════════
#  CALLOUT (resumen IA / nota destacada)
# ════════════════════════════════════════════════════════════════════════════
def callout(label, text, accent=BRAND, tint=None):
    tint = tint or colors.HexColor("#F1F6FF")
    inner = Table([
        [Paragraph(label.upper(), ps("col", fontName=MONO_SB, fontSize=7,
                   textColor=accent, leading=11))],
        [Paragraph(text, ps("cot", fontName=FONT, fontSize=9.5,
                   textColor=BODY, leading=14.5))],
    ], colWidths=[None])
    inner.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (0, 0), 0), ("BOTTOMPADDING", (0, 0), (0, 0), 5),
        ("TOPPADDING", (0, 1), (0, 1), 0), ("BOTTOMPADDING", (0, 1), (0, 1), 0),
    ]))
    box = Table([[inner]], colWidths=[CW])
    box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), tint),
        ("LEFTPADDING", (0, 0), (-1, -1), 15),
        ("RIGHTPADDING", (0, 0), (-1, -1), 15),
        ("TOPPADDING", (0, 0), (-1, -1), 13),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 13),
        ("LINEBEFORE", (0, 0), (0, -1), 2.5, accent),
    ]))
    return box


# ════════════════════════════════════════════════════════════════════════════
#  EMPTY STATE
# ════════════════════════════════════════════════════════════════════════════
def empty(text):
    return Paragraph(text, ps("empty", fontName=FONT, fontSize=9,
                     textColor=MUTED, leading=13))


# ════════════════════════════════════════════════════════════════════════════
#  FOOTER
# ════════════════════════════════════════════════════════════════════════════
def make_footer(company, support):
    def _footer(canvas, doc):
        canvas.saveState()
        y = 12 * mm
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.5)
        canvas.line(ML, y + 5, PAGE_W - MR, y + 5)
        canvas.setFont(MONO, 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(ML, y - 3, f"{company}  ·  {support}  ·  Confidencial")
        canvas.drawRightString(PAGE_W - MR, y - 3, f"Página {doc.page}")
        canvas.restoreState()
    return _footer


# ════════════════════════════════════════════════════════════════════════════
#  ESPACIADO
# ════════════════════════════════════════════════════════════════════════════
def gap(h):
    return Spacer(1, h)
