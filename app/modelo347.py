"""Modelo 347: clientes con operaciones anuales superiores a 3.005,06 € y carta de confirmación."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether, NextPageTemplate,
                                PageTemplate, Paragraph, Spacer, Table, TableStyle)

from .config import ruta_logo
from .informe import FONDO, GRIS, GRIS_CLARO, MESES, TINTA, _CanvasNumerado, _esc, eur, fecha_es
from .modelo import Cliente, Factura

UMBRAL = 3005.06


@dataclass
class Fila347:
    clave: str
    cliente: Cliente
    facturas: list[Factura] = field(default_factory=list)

    @property
    def total(self) -> float:
        return round(sum(f.importe_total for f in self.facturas), 2)

    @property
    def trimestres(self) -> list[float]:
        t = [0.0, 0.0, 0.0, 0.0]
        for f in self.facturas:
            if f.fecha:
                t[(f.fecha.month - 1) // 3] += f.importe_total
        return [round(x, 2) for x in t]


def calcular(facturas: list[Factura], clientes: dict[str, Cliente], ejercicio: int,
             umbral: float = UMBRAL) -> tuple[list[Fila347], list[Fila347]]:
    """Devuelve (clientes a declarar, clientes que superan el umbral pero no tienen NIF)."""
    grupos: dict[str, list[Factura]] = {}
    for f in facturas:
        if f.fecha and f.fecha.year == ejercicio:
            grupos.setdefault(f.cliente_clave, []).append(f)
    incluidos, sin_nif = [], []
    for clave, fs in grupos.items():
        fila = Fila347(clave, clientes.get(clave) or Cliente(clave=clave, nombre=clave),
                       sorted(fs, key=lambda f: (f.fecha, f.numero)))
        if fila.total <= umbral:
            continue
        if not fila.cliente.nif or clave.startswith("NOM:"):
            sin_nif.append(fila)
        else:
            incluidos.append(fila)
    orden = lambda x: x.cliente.nombre.lower()  # noqa: E731
    return sorted(incluidos, key=orden), sorted(sin_nif, key=orden)


def fecha_larga(d: date) -> str:
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"


def generar_carta(ruta, fila: Fila347, ejercicio: int, cfg: dict) -> Path:
    emp = cfg["empresa"]
    acento = colors.HexColor(emp.get("color") or "#C2410C")
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ancho, alto = A4
    margen = 18 * mm
    util = ancho - 2 * margen
    c = fila.cliente

    st = {
        "n": ParagraphStyle("n", fontName="Helvetica", fontSize=9.5, leading=13.5, textColor=TINTA),
        "b": ParagraphStyle("b", fontName="Helvetica-Bold", fontSize=9.5, leading=13.5, textColor=TINTA),
        "tit": ParagraphStyle("tit", fontName="Helvetica-Bold", fontSize=14, leading=18, textColor=acento),
        "td": ParagraphStyle("td", fontName="Helvetica", fontSize=8.8, leading=11, textColor=TINTA),
        "tdr": ParagraphStyle("tdr", fontName="Helvetica", fontSize=8.8, leading=11, textColor=TINTA, alignment=TA_RIGHT),
        "th": ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=7.6, leading=9.5, textColor=colors.white),
        "thr": ParagraphStyle("thr", fontName="Helvetica-Bold", fontSize=7.6, leading=9.5, textColor=colors.white, alignment=TA_RIGHT),
        "kv": ParagraphStyle("kv", fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=TINTA),
        "ke": ParagraphStyle("ke", fontName="Helvetica", fontSize=7, leading=9, textColor=GRIS),
    }

    logo = ImageReader(str(ruta_logo(cfg)))
    lw, lh = logo.getSize()
    alto_logo = 17 * mm
    ancho_logo = alto_logo * lw / lh
    top = alto - 14 * mm

    def cabecera(cv, doc):
        cv.saveState()
        cv.drawImage(logo, margen, top - alto_logo, ancho_logo, alto_logo, mask="auto")
        x = margen + ancho_logo + 5 * mm
        cv.setFillColor(TINTA)
        cv.setFont("Helvetica-Bold", 11.5)
        cv.drawString(x, top - 4.5 * mm, emp["nombre"])
        cv.setFont("Helvetica", 7.8)
        cv.setFillColor(GRIS)
        y = top - 8.8 * mm
        lineas = [f"CIF {emp['cif']}" if emp.get("cif") else "", emp.get("direccion", ""),
                  f"{emp.get('cp', '')} {emp.get('poblacion', '')} ({emp.get('provincia', '')})".strip(),
                  "  ·  ".join(x for x in (emp.get("telefono", ""), emp.get("email", "")) if x)]
        for t in lineas:
            if t:
                cv.drawString(x, y, t)
                y -= 3.3 * mm
        cv.setFillColor(acento)
        cv.rect(margen, top - alto_logo - 4 * mm, util, 1.1, stroke=0, fill=1)
        cv.restoreState()

    def ventana(cv, doc):
        """Destinatario en la posición de la ventana de un sobre americano (DL)."""
        cabecera(cv, doc)
        cv.saveState()
        x, y_top, w, h = 105 * mm, alto - 48 * mm, 87 * mm, 30 * mm
        cv.setStrokeColor(GRIS_CLARO)
        cv.setLineWidth(0.6)
        cv.roundRect(x - 4 * mm, y_top - h, w, h, 2 * mm, stroke=1, fill=0)
        cv.setFillColor(TINTA)
        ty = y_top - 6 * mm
        maximo = w - 8 * mm

        def escribir(texto, fuente, tam):
            from reportlab.pdfbase.pdfmetrics import stringWidth
            while tam > 7 and stringWidth(texto, fuente, tam) > maximo:
                tam -= 0.25
            while texto and stringWidth(texto, fuente, tam) > maximo:
                texto = texto[:-1]
            cv.setFont(fuente, tam)
            cv.drawString(x, ty, texto)

        escribir(c.nombre or "", "Helvetica-Bold", 10)
        for t in [c.direccion, " ".join(p for p in (c.cp, c.poblacion) if p), c.provincia]:
            if t:
                ty -= 4.6 * mm
                escribir(t, "Helvetica", 9)
        # fecha a la izquierda, a la altura del destinatario
        cv.setFont("Helvetica", 9)
        cv.setFillColor(GRIS)
        cv.drawString(margen, y_top - 6 * mm, f"{emp.get('poblacion', '')}, {fecha_larga(date.today())}")
        cv.restoreState()

    def pie(cv, n, total):
        cv.saveState()
        cv.setStrokeColor(GRIS_CLARO)
        cv.setLineWidth(0.6)
        cv.line(margen, 12 * mm, ancho - margen, 12 * mm)
        cv.setFont("Helvetica", 7)
        cv.setFillColor(GRIS)
        cv.drawString(margen, 8 * mm, f"{emp['nombre']}  ·  CIF {emp.get('cif', '')}  ·  Modelo 347 ejercicio {ejercicio}  ·  {c.nombre}"[:150])
        cv.drawRightString(ancho - margen, 8 * mm, f"Pág. {n} de {total}")
        cv.restoreState()

    doc = BaseDocTemplate(str(ruta), pagesize=A4, leftMargin=margen, rightMargin=margen,
                          topMargin=margen, bottomMargin=18 * mm,
                          title=f"Modelo 347 {ejercicio} - {c.nombre}", author=emp["nombre"])
    marco_1 = Frame(margen, 18 * mm, util, alto - 18 * mm - 84 * mm, id="primera", leftPadding=0, rightPadding=0)
    marco_n = Frame(margen, 18 * mm, util, alto - 18 * mm - 40 * mm, id="resto", leftPadding=0, rightPadding=0)
    doc.addPageTemplates([PageTemplate(id="primera", frames=[marco_1], onPage=ventana),
                          PageTemplate(id="resto", frames=[marco_n], onPage=cabecera)])

    h: list = [NextPageTemplate("resto")]
    h.append(Paragraph(f"DECLARACIÓN ANUAL · MODELO 347 · EJERCICIO {ejercicio}", st["tit"]))
    h.append(Spacer(1, 1.5 * mm))
    linea = Table([[""]], colWidths=[util], rowHeights=[1])
    linea.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), 0.8, GRIS_CLARO)]))
    h += [linea, Spacer(1, 4 * mm)]
    h.append(Paragraph("Señores:", st["n"]))
    h.append(Spacer(1, 2 * mm))
    h.append(Paragraph(
        f"Les remitimos el detalle de las facturas realizadas durante el ejercicio <b>{ejercicio}</b> "
        "que figuran en nuestros archivos, a efectos de la declaración anual de operaciones con "
        "terceras personas (Modelo 347).", st["n"]))
    h.append(Spacer(1, 5 * mm))

    def kpi(v, e):
        return [Paragraph(v, st["kv"]), Paragraph(e, st["ke"])]

    kp = Table([[kpi(_esc(c.nif or "—"), "NIF / CIF"), kpi(str(len(fila.facturas)), "FACTURAS"),
                 kpi(eur(fila.total), "IMPORTE FACTURAS (IVA INCLUIDO)")]],
               colWidths=[util * 0.3, util * 0.2, util * 0.5])
    kp.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (1, 0), FONDO),
        ("BACKGROUND", (2, 0), (2, 0), colors.Color(acento.red, acento.green, acento.blue, alpha=0.10)),
        ("LINEBEFORE", (0, 0), (0, 0), 2, acento),
        ("LEFTPADDING", (0, 0), (-1, -1), 9), ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7), ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    h += [kp, Spacer(1, 6 * mm)]

    filas = [[Paragraph(t, st["thr"] if i == 3 else st["th"]) for i, t in
              enumerate(["Factura", "Fecha factura", "Fecha contabilización", "Importe"])]]
    for f in fila.facturas:
        filas.append([Paragraph(_esc(f.numero), st["td"]), Paragraph(fecha_es(f.fecha), st["td"]),
                      Paragraph(fecha_es(f.fecha), st["td"]), Paragraph(eur(f.importe_total), st["tdr"])])
    t = Table(filas, colWidths=[util * 0.25, util * 0.22, util * 0.28, util * 0.25], repeatRows=1)
    estilos = [("BACKGROUND", (0, 0), (-1, 0), TINTA), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
               ("TOPPADDING", (0, 0), (-1, -1), 2.6), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.6),
               ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
               ("LINEBELOW", (0, -1), (-1, -1), 0.8, TINTA)]
    for i in range(2, len(filas), 2):
        estilos.append(("BACKGROUND", (0, i), (-1, i), FONDO))
    t.setStyle(TableStyle(estilos))
    h += [t, Spacer(1, 6 * mm)]

    nombres = ["Total primer trimestre", "Total segundo trimestre", "Total tercer trimestre",
               "Total cuarto trimestre"]
    filas_t = [[Paragraph(n, st["n"]), Paragraph(eur(v), st["tdr"])] for n, v in zip(nombres, fila.trimestres)]
    filas_t.append([Paragraph("<b>TOTAL EJERCICIO</b>", ParagraphStyle("x", parent=st["n"], textColor=colors.white)),
                    Paragraph(f"<b>{eur(fila.total)}</b>", ParagraphStyle("y", parent=st["tdr"], textColor=colors.white, fontSize=10.5, leading=13))])
    tt = Table(filas_t, colWidths=[util * 0.26, util * 0.16])
    tt.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, GRIS_CLARO), ("BACKGROUND", (0, -1), (-1, -1), acento),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    cierre = [
        Paragraph("Les agradeceríamos que, en caso de existir alguna discrepancia, nos lo indicaran lo antes "
                  "posible para proceder a las comprobaciones oportunas. En caso de no recibir respuesta, "
                  "tomaremos estos datos como correctos y procederemos a su declaración.", st["n"]),
        Spacer(1, 3 * mm),
        Paragraph("Aprovechamos la ocasión para saludarles cordialmente.", st["n"]),
        Spacer(1, 9 * mm),
        Paragraph(_esc(emp["nombre"]), st["b"]),
        Paragraph("Dpto. Administración", st["n"]),
    ]
    bloque = Table([[cierre, tt]], colWidths=[util * 0.55, util * 0.45])
    bloque.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                                ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (0, 0), 8 * mm),
                                ("RIGHTPADDING", (1, 0), (1, 0), 0)]))
    h.append(KeepTogether([bloque]))
    doc.build(h, canvasmaker=lambda *a, **k: _CanvasNumerado(*a, pie=pie, **k))
    return ruta
