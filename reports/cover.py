"""
Sentinel XO — Portada premium compartida para reportes PDF
==========================================================
`render_with_cover(...)` arma un documento con una PRIMERA página de portada
oscura (estilo Guía del Servicio: fondo navy, textura de grilla, regla con
gradiente, lockup de marca, compañía + período en grande) seguida del contenido
con el tema claro estándar y footer en todas las páginas.

Lo usan generator.py (mensual), device_report.py (por equipo) y
security_report.py (seguridad) para mantener una papelería coherente.
"""
import io

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, FrameBreak,
                                NextPageTemplate, PageBreak, Spacer, Paragraph,
                                Table, TableStyle)
from reportlab.graphics.shapes import Drawing, Rect, String, Circle
from reportlab.pdfbase.pdfmetrics import stringWidth

from reports import pdf_theme as T

PAGE_W, PAGE_H = A4

_INK_TOP = colors.HexColor("#0b1422")
_INK_BOT = colors.HexColor("#080d16")
_GRID    = colors.HexColor("#111c2e")


def _ps(**kw):
    d = dict(fontName=T.FONT, fontSize=9, textColor=T.ON_INK, leading=13)
    d.update(kw)
    return ParagraphStyle("cv", **d)


def _spaced(text):
    """Letra-espaciado tipo kicker: 'ABC' → 'A B C'."""
    return " ".join(list(text)).replace("   ", " &nbsp; ")


def _paint_cover(support):
    def _inner(canvas, doc):
        canvas.saveState()
        canvas.linearGradient(0, 0, 0, PAGE_H, (_INK_BOT, _INK_TOP), (0, 1))
        canvas.setStrokeColor(_GRID); canvas.setLineWidth(0.4)
        x = 0
        while x < PAGE_W:
            canvas.line(x, 0, x, PAGE_H); x += 28
        y = 0
        while y < PAGE_H:
            canvas.line(0, y, PAGE_W, y); y += 28
        canvas.saveState()
        path = canvas.beginPath(); path.rect(0, PAGE_H - 4, PAGE_W, 4); canvas.clipPath(path, stroke=0)
        canvas.linearGradient(0, PAGE_H - 2, PAGE_W, PAGE_H - 2,
            (colors.HexColor("#22e6ff"), colors.HexColor("#2f7bff"), colors.HexColor("#9b6bff")), (0, .5, 1))
        canvas.restoreState()
        canvas.setFont(T.FONT_SB, 8.5); canvas.setFillColor(colors.HexColor("#C7D6F0"))
        canvas.drawString(T.ML, 44, f"Preparado por {doc._sx_company}")
        canvas.setFont(T.FONT, 8.5); canvas.setFillColor(colors.HexColor("#5f7596"))
        canvas.drawRightString(PAGE_W - T.MR, 44, f"Documento confidencial · {support}")
        canvas.restoreState()
    return _inner


def _pill_dark(text):
    fs, pad, dot = 8.5, 13, 6
    w = stringWidth(text, T.FONT_SB, fs) + pad * 2 + dot + 8
    h = 23
    d = Drawing(w, h)
    d.add(Rect(0, 0, w, h, rx=11, ry=11,
               fillColor=colors.HexColor("#0e2233"), strokeColor=colors.HexColor("#1d4d50")))
    d.add(Circle(pad + 2, h / 2, 3, fillColor=T.GREEN, strokeColor=None))
    d.add(String(pad + dot + 6, h / 2 - 3, text, fontName=T.FONT_SB, fontSize=fs,
                 fillColor=colors.HexColor("#5ee0b0")))
    return d


def _brand(product, tag):
    logo = T.logo_mark(26, T.ON_INK, T.CYAN)
    name = Paragraph(product, _ps(fontName=T.FONT_BD, fontSize=15, textColor=T.ON_INK, leading=16))
    sub = Paragraph(_spaced(tag), _ps(fontName=T.MONO, fontSize=7, textColor=T.KICKER, leading=11))
    inner = Table([[name], [sub]], colWidths=[T.CW - 40])
    inner.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                               ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    t = Table([[logo, inner]], colWidths=[40, T.CW - 40])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                           ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    return t


def _cover_flowables(*, product, product_tag, kicker, title, subtitle, generated_at, pill_text):
    fl = [_brand(product, product_tag), FrameBreak()]
    fl.append(Spacer(0, 96))
    if pill_text:
        fl.append(_pill_dark(pill_text))
        fl.append(Spacer(0, 18))
    fl.append(Paragraph(_spaced(kicker.upper()),
                        _ps(fontName=T.FONT_SB, fontSize=10, textColor=T.KICKER, leading=14)))
    fl.append(Spacer(0, 12))
    fl.append(Paragraph(title,
                        _ps(fontName=T.FONT_BD, fontSize=32, textColor=colors.HexColor("#F4F8FF"), leading=36)))
    if subtitle:
        fl.append(Spacer(0, 10))
        fl.append(Paragraph(subtitle, _ps(fontName=T.FONT, fontSize=15, textColor=T.ON_INK_2, leading=20)))
    fl.append(Spacer(0, 14))
    fl.append(Paragraph(f"Generado el {generated_at}",
                        _ps(fontName=T.MONO, fontSize=9, textColor=colors.HexColor("#5f7596"), leading=13)))
    return fl


def render_with_cover(*, company, support, content_story,
                      kicker, title, subtitle="", generated_at="",
                      product="Sentinel XO", product_tag="XO CONTROL",
                      pill_text="Monitoreo activo 24/7") -> bytes:
    """Construye el PDF: portada oscura + contenido claro con footer."""
    buf = io.BytesIO()
    doc = BaseDocTemplate(buf, pagesize=A4,
                          leftMargin=T.ML, rightMargin=T.MR,
                          topMargin=T.MT, bottomMargin=T.MB)
    doc._sx_company = company

    f_logo = Frame(T.ML, PAGE_H - T.MT - 46, T.CW, 46, id="logo",
                   leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    f_hero = Frame(T.ML, 120, T.CW, PAGE_H - 120 - 210, id="hero",
                   leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    cover_tmpl = PageTemplate(id="cover", frames=[f_logo, f_hero], onPage=_paint_cover(support))

    f_content = Frame(T.ML, T.MB, T.CW, PAGE_H - T.MT - T.MB, id="content")
    footer = T.make_footer(company, support)
    content_tmpl = PageTemplate(id="content", frames=[f_content], onPage=footer)

    doc.addPageTemplates([cover_tmpl, content_tmpl])

    cover = _cover_flowables(product=product, product_tag=product_tag, kicker=kicker,
                             title=title, subtitle=subtitle, generated_at=generated_at,
                             pill_text=pill_text)
    story = cover + [NextPageTemplate("content"), PageBreak()] + content_story
    doc.build(story)

    pdf = buf.getvalue()
    buf.close()
    return pdf
