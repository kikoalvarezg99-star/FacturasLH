"""Generación del PDF "Listado de facturas" para un cliente."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (KeepTogether, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

from .config import ruta_logo
from .modelo import IRPF_TIPOS, IVA_TIPOS, RE_TIPOS, Cliente, Factura

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]

TINTA = colors.HexColor("#1F2328")
GRIS = colors.HexColor("#6B7280")
GRIS_CLARO = colors.HexColor("#E5E7EB")
FONDO = colors.HexColor("#F6F7F9")

COLOR_TIPO = {
    "Contado": colors.HexColor("#15803D"),
    "Crédito": colors.HexColor("#1D4ED8"),
    "Simplificada": colors.HexColor("#6B7280"),
    "Rectificativa": colors.HexColor("#B91C1C"),
}


# ------------------------------------------------------------- formato


def eur(x: float, simbolo: bool = True) -> str:
    s = f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} €" if simbolo else s


def pct(x: float) -> str:
    if not x:
        return "—"
    if x not in IVA_TIPOS and x not in RE_TIPOS and x not in IRPF_TIPOS:
        return "varios"  # factura con varios tipos agrupados en el diario
    s = f"{x:.2f}".rstrip("0").rstrip(".")
    return s.replace(".", ",") + " %"


def fecha_es(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else ""


def texto_periodo(desde: date | None, hasta: date | None) -> str:
    if not desde or not hasta:
        return ""
    if desde.year == hasta.year and desde.month == hasta.month:
        import calendar

        ultimo = calendar.monthrange(desde.year, desde.month)[1]
        if desde.day == 1 and hasta.day == ultimo:
            return f"{MESES[desde.month - 1]} de {desde.year}"
    return f"del {fecha_es(desde)} al {fecha_es(hasta)}"


# ------------------------------------------------- canvas con "Página x de y"


class _CanvasNumerado(rl_canvas.Canvas):
    def __init__(self, *a, pie=None, **k):
        super().__init__(*a, **k)
        self._paginas = []
        self._pie = pie

    def showPage(self):
        self._paginas.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._paginas)
        for estado in self._paginas:
            self.__dict__.update(estado)
            if self._pie:
                self._pie(self, self._pageNumber, total)
            super().showPage()
        super().save()


# --------------------------------------------------------------- informe


def generar_listado(ruta_salida, facturas: list[Factura], cliente: Cliente, cfg: dict,
                    desde: date | None = None, hasta: date | None = None) -> Path:
    emp = cfg["empresa"]
    acento = colors.HexColor(emp.get("color") or "#C2410C")
    acento_suave = colors.Color(acento.red, acento.green, acento.blue, alpha=0.10)
    ruta_salida = Path(ruta_salida)
    ruta_salida.parent.mkdir(parents=True, exist_ok=True)

    fechas = [f.fecha for f in facturas if f.fecha]
    desde = desde or (min(fechas) if fechas else None)
    hasta = hasta or (max(fechas) if fechas else None)
    periodo = texto_periodo(desde, hasta)

    ancho, alto = A4
    margen = 15 * mm
    util = ancho - 2 * margen

    st = {
        "n": ParagraphStyle("n", fontName="Helvetica", fontSize=8.5, leading=11, textColor=TINTA),
        "p": ParagraphStyle("p", fontName="Helvetica", fontSize=7.5, leading=9.5, textColor=GRIS),
        "etq": ParagraphStyle("etq", fontName="Helvetica-Bold", fontSize=6.8, leading=9,
                              textColor=acento, spaceAfter=2),
        "cli": ParagraphStyle("cli", fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=TINTA),
        "td": ParagraphStyle("td", fontName="Helvetica", fontSize=7.6, leading=9.5, textColor=TINTA),
        "tdr": ParagraphStyle("tdr", fontName="Helvetica", fontSize=7.6, leading=9.5, textColor=TINTA,
                              alignment=TA_RIGHT),
        "th": ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=6.8, leading=8.5,
                             textColor=colors.white),
        "thr": ParagraphStyle("thr", fontName="Helvetica-Bold", fontSize=6.8, leading=8.5,
                              textColor=colors.white, alignment=TA_RIGHT),
        "kpi_v": ParagraphStyle("kv", fontName="Helvetica-Bold", fontSize=12.5, leading=15, textColor=TINTA),
        "kpi_e": ParagraphStyle("ke", fontName="Helvetica", fontSize=6.8, leading=9, textColor=GRIS),
    }

    # -------------------------------------------- cabecera y pie (todas las páginas)
    logo = ImageReader(str(ruta_logo(cfg)))
    lw, lh = logo.getSize()
    alto_logo = 20 * mm
    ancho_logo = alto_logo * lw / lh

    lineas_emp = [emp.get("nombre", "")]
    if emp.get("cif"):
        lineas_emp.append(f"CIF {emp['cif']}")
    dir1 = emp.get("direccion", "")
    dir2 = " ".join(x for x in [emp.get("cp", ""), emp.get("poblacion", "")] if x)
    if emp.get("provincia"):
        dir2 = f"{dir2} ({emp['provincia']})" if dir2 else emp["provincia"]
    contacto = "  ·  ".join(x for x in [emp.get("telefono", ""), emp.get("email", ""), emp.get("web", "")] if x)

    def cabecera(c, doc):
        c.saveState()
        top = alto - margen
        c.drawImage(logo, margen, top - alto_logo, ancho_logo, alto_logo, mask="auto")
        x = margen + ancho_logo + 5 * mm
        c.setFillColor(TINTA)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(x, top - 5.5 * mm, lineas_emp[0])
        c.setFont("Helvetica", 7.6)
        c.setFillColor(GRIS)
        y = top - 10 * mm
        for t in lineas_emp[1:] + [dir1, dir2, contacto]:
            if t:
                c.drawString(x, y, t)
                y -= 3.4 * mm
        # bloque título
        c.setFillColor(acento)
        c.setFont("Helvetica-Bold", 16)
        c.drawRightString(ancho - margen, top - 6 * mm, "LISTADO DE FACTURAS")
        c.setFillColor(TINTA)
        c.setFont("Helvetica", 8.5)
        if periodo:
            c.drawRightString(ancho - margen, top - 11 * mm, f"Periodo: {periodo}")
        c.setFillColor(GRIS)
        c.setFont("Helvetica", 7.6)
        c.drawRightString(ancho - margen, top - 15 * mm, f"Fecha de emisión: {fecha_es(date.today())}")
        # línea de acento
        c.setFillColor(acento)
        c.rect(margen, top - alto_logo - 4 * mm, util, 1.2, stroke=0, fill=1)
        c.restoreState()

    def pie(c, n, total):
        c.saveState()
        c.setStrokeColor(GRIS_CLARO)
        c.setLineWidth(0.6)
        c.line(margen, 12 * mm, ancho - margen, 12 * mm)
        c.setFont("Helvetica", 7)
        c.setFillColor(GRIS)
        izq = emp.get("nombre", "")
        if emp.get("cif"):
            izq += f"  ·  CIF {emp['cif']}"
        izq += f"  ·  Cliente: {cliente.nombre}"
        c.drawString(margen, 8 * mm, izq[:140])
        c.drawRightString(ancho - margen, 8 * mm, f"Página {n} de {total}")
        c.restoreState()

    doc = SimpleDocTemplate(
        str(ruta_salida), pagesize=A4, leftMargin=margen, rightMargin=margen,
        topMargin=margen + alto_logo + 8 * mm, bottomMargin=18 * mm,
        title=f"Listado de facturas - {cliente.nombre}", author=emp.get("nombre", ""),
        subject=f"Listado de facturas {periodo}",
    )
    historia = []

    # ------------------------------------------------------- bloque cliente
    datos_cli = []
    if cliente.nif:
        datos_cli.append(f"NIF/CIF: <b>{cliente.nif}</b>")
    if cliente.codigo:
        datos_cli.append(f"Código cliente: {cliente.codigo}")
    dir_c = ", ".join(x for x in [cliente.direccion,
                                    " ".join(y for y in [cliente.cp, cliente.poblacion] if y),
                                    cliente.provincia] if x)
    if dir_c:
        datos_cli.append(dir_c)
    cont_c = "  ·  ".join(x for x in [cliente.telefono, cliente.email] if x)
    if cont_c:
        datos_cli.append(cont_c)

    caja_cli = [Paragraph("CLIENTE", st["etq"]), Paragraph(_esc(cliente.nombre), st["cli"])]
    caja_cli += [Paragraph(_esc_b(t), st["n"]) for t in datos_cli]

    base_t = sum(f.base for f in facturas)
    iva_t = sum(f.cuota_iva for f in facturas)
    re_t = sum(f.cuota_re for f in facturas)
    irpf_t = sum(f.irpf for f in facturas)
    total_t = sum(f.importe_total for f in facturas)

    def kpi(valor, etiqueta):
        return [Paragraph(valor, st["kpi_v"]), Paragraph(etiqueta, st["kpi_e"])]

    kpis = Table(
        [[kpi(str(len(facturas)), "FACTURAS"), kpi(eur(base_t), "BASE IMPONIBLE")],
         [kpi(eur(iva_t + re_t), "IVA" + (" + REC. EQUIV." if re_t else "")), kpi(eur(total_t), "TOTAL")]],
        colWidths=[util * 0.21] * 2,
    )
    kpis.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("BACKGROUND", (0, 0), (-1, -1), FONDO),
        ("BACKGROUND", (1, 1), (1, 1), acento_suave),
        ("LINEBEFORE", (0, 0), (0, -1), 2, acento),
    ]))

    bloque = Table([[caja_cli, kpis]], colWidths=[util * 0.58, util * 0.42])
    bloque.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, 0), 10), ("RIGHTPADDING", (0, 0), (0, 0), 10),
        ("TOPPADDING", (0, 0), (0, 0), 8), ("BOTTOMPADDING", (0, 0), (0, 0), 8),
        ("LEFTPADDING", (1, 0), (1, 0), 8), ("RIGHTPADDING", (1, 0), (1, 0), 0),
        ("TOPPADDING", (1, 0), (1, 0), 0),
        ("BOX", (0, 0), (0, 0), 0.6, GRIS_CLARO),
    ]))
    historia += [bloque, Spacer(1, 7 * mm)]

    # ------------------------------------------------------ tabla de facturas
    con_re = re_t != 0
    con_irpf = irpf_t != 0
    cols = [("Tipo", 0.11, False), ("Nº factura", 0.135, False), ("Fecha", 0.09, False),
            ("Base imponible", 0.115, True), ("% IVA", 0.06, True), ("Cuota IVA", 0.10, True)]
    if con_re:
        cols += [("% R.E.", 0.06, True), ("Recargo", 0.085, True)]
    if con_irpf:
        cols += [("% IRPF", 0.06, True), ("IRPF", 0.085, True)]
    cols += [("Total", 0.11, True)]
    suma = sum(c[1] for c in cols)
    anchos = [util * c[1] / suma for c in cols]

    filas = [[Paragraph(t, st["thr"] if der else st["th"]) for t, _, der in cols]]
    estilos = []
    franja = False
    for f in facturas:
        lineas = f.lineas or [None]
        inicio = len(filas)
        for i, l in enumerate(lineas):
            primero = i == 0
            fila = []
            if primero:
                color_t = COLOR_TIPO.get(f.tipo, TINTA)
                fila += [Paragraph(f'<font color="{color_t.hexval().replace("0x", "#")}"><b>{f.tipo}</b></font>', st["td"]),
                         Paragraph(_esc(f.numero), st["td"]), Paragraph(fecha_es(f.fecha), st["td"])]
            else:
                fila += ["", "", ""]
            fila += [Paragraph(eur(l.base, False) if l else "", st["tdr"]),
                     Paragraph(pct(l.iva_pct) if l else "", st["tdr"]),
                     Paragraph(eur(l.iva, False) if l else "", st["tdr"])]
            if con_re:
                fila += [Paragraph(pct(l.re_pct) if l and l.re else "—", st["tdr"]),
                         Paragraph(eur(l.re, False) if l and l.re else "—", st["tdr"])]
            if con_irpf:
                fila += [Paragraph(pct(f.irpf_pct) if primero and f.irpf else ("—" if primero else ""), st["tdr"]),
                         Paragraph(("-" + eur(f.irpf, False)) if primero and f.irpf else ("—" if primero else ""), st["tdr"])]
            fila += [Paragraph(f"<b>{eur(f.importe_total)}</b>" if primero else "", st["tdr"])]
            filas.append(fila)
        if franja:
            estilos.append(("BACKGROUND", (0, inicio), (-1, len(filas) - 1), FONDO))
        franja = not franja
        if len(lineas) > 1:
            estilos.append(("TOPPADDING", (3, inicio + 1), (-2, len(filas) - 1), 0))

    tabla = Table(filas, colWidths=anchos, repeatRows=1)
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), TINTA),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, 0), 5), ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
        ("TOPPADDING", (0, 1), (-1, -1), 3.2), ("BOTTOMPADDING", (0, 1), (-1, -1), 3.2),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, -1), (-1, -1), 0.8, TINTA),
    ] + estilos))
    historia += [tabla, Spacer(1, 6 * mm)]

    # --------------------------------------------- resumen por tipo de IVA
    resumen: dict[tuple, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
    for f in facturas:
        for l in f.lineas:
            k = (l.iva_pct, l.re_pct if l.re else 0.0)
            resumen[k][0] += l.base
            resumen[k][1] += l.iva
            resumen[k][2] += l.re
    cab_r = ["% IVA", "Base imponible", "Cuota IVA"] + (["% R.E.", "Recargo"] if con_re else [])
    filas_r = [[Paragraph(t, st["thr"]) for t in cab_r]]
    for (piva, pre), (b, i, r) in sorted(resumen.items(), key=lambda x: -x[0][0]):
        fila = [pct(piva), eur(b), eur(i)] + ([pct(pre) if r else "—", eur(r) if r else "—"] if con_re else [])
        filas_r.append([Paragraph(x, st["tdr"]) for x in fila])
    pesos = [0.7, 1.25, 1.0, 0.7, 1.0][:len(cab_r)]
    anchos_r = [util * 0.56 * w / sum(pesos) for w in pesos]
    t_res = Table(filas_r, colWidths=anchos_r)
    t_res.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4B5563")),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, GRIS_CLARO),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    bloque_res = [Paragraph("RESUMEN POR TIPO DE IVA", st["etq"]), t_res]

    # ------------------------------------------------------------- totales
    filas_t = [["Base imponible", eur(base_t)], ["Cuota IVA", eur(iva_t)]]
    if con_re:
        filas_t.append(["Recargo de equivalencia", eur(re_t)])
    if con_irpf:
        filas_t.append(["Retención IRPF", "-" + eur(irpf_t)])
    filas_t.append(["TOTAL", eur(total_t)])
    t_tot = Table([[Paragraph(a, st["n"]), Paragraph(b, st["tdr"])] for a, b in filas_t[:-1]]
                  + [[Paragraph("<b>TOTAL</b>", ParagraphStyle("tt", parent=st["n"], textColor=colors.white, fontSize=10)),
                      Paragraph(f"<b>{filas_t[-1][1]}</b>", ParagraphStyle("tv", parent=st["tdr"], textColor=colors.white, fontSize=11, leading=13))]],
                  colWidths=[util * 0.22, util * 0.16])
    t_tot.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, GRIS_CLARO),
        ("BACKGROUND", (0, -1), (-1, -1), acento),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("TOPPADDING", (0, -1), (-1, -1), 6), ("BOTTOMPADDING", (0, -1), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    final = Table([[bloque_res, t_tot]], colWidths=[util * 0.6, util * 0.4])
    final.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    historia.append(KeepTogether([final]))

    # resumen por tipo de factura
    por_tipo: dict[str, list] = defaultdict(lambda: [0, 0.0])
    for f in facturas:
        por_tipo[f.tipo][0] += 1
        por_tipo[f.tipo][1] += f.importe_total
    if por_tipo:
        texto = "   ·   ".join(f"{t}: {n} ({eur(v)})" for t, (n, v) in sorted(por_tipo.items()))
        historia += [Spacer(1, 5 * mm), Paragraph(f"<b>Por tipo de factura</b> — {texto}", st["p"])]

    doc.build(historia, onFirstPage=cabecera, onLaterPages=cabecera,
              canvasmaker=lambda *a, **k: _CanvasNumerado(*a, pie=pie, **k))
    return ruta_salida


def _esc(t: str) -> str:
    return (t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _esc_b(t: str) -> str:
    """Escapa todo salvo las etiquetas <b> que añadimos nosotros."""
    return _esc(t).replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")
