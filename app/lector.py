"""Lectura del diario de facturación (PDF, Excel o CSV).

El lector no depende de un programa de gestión concreto: busca la fila de
cabecera (Nº factura, Fecha, Cliente, Base, IVA, Total...), deduce las columnas
por su posición y agrupa las facturas por cliente.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from .modelo import (IRPF_TIPOS, IVA_TIPOS, RE_TIPOS, Cliente, Factura,
                     LineaImpuesto, aproximar, clave_cliente, r2)

# ------------------------------------------------------------ utilidades


def normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    t = t.lower()
    t = re.sub(r"\bn\s*o?\s*\.?(?=\s|$)", "num ", t)  # Nº, N°, No.
    t = re.sub(r"[^a-z0-9%]+", " ", t)
    t = " ".join(t.split())
    # siglas con puntos: "r e" -> "re", "i v a" -> "iva"
    return re.sub(r"\b(?:[a-z] )+[a-z]\b", lambda m: m.group(0).replace(" ", ""), t)


_RE_IMPORTE = re.compile(r"^\(?-?\s*(\d{1,3}(?:[.\s]\d{3})*|\d+)([.,]\d{1,4})?\s*-?\)?\s*(€|eur)?$", re.I)


def parse_importe(valor) -> Optional[float]:
    """'1.234,56' -> 1234.56 · '12,30-' -> -12.3 · admite números ya convertidos."""
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    s = str(valor).strip().replace(" ", " ").replace("€", "").strip()
    if not s:
        return None
    s = s.replace("%", "").strip()
    if not _RE_IMPORTE.match(s + ("" if s else "x")):
        return None
    negativo = s.startswith("-") or s.endswith("-") or (s.startswith("(") and s.endswith(")"))
    s = s.strip("()- ").replace(" ", "")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    elif s.count(".") == 1 and len(s.split(".")[1]) == 3:
        s = s.replace(".", "")  # 1.234 = mil doscientos...
    elif s.count(".") > 1:
        s = s.replace(".", "")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if negativo else v


_RE_FECHA = re.compile(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})$")
_RE_FECHA_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def parse_fecha(valor) -> Optional[date]:
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    s = str(valor).strip()
    m = _RE_FECHA.match(s)
    try:
        if m:
            d, mth, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if y < 100:
                y += 2000
            return date(y, mth, d)
        m = _RE_FECHA_ISO.match(s)
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None
    return None


_RE_NIF = re.compile(r"\b([ABCDEFGHJKLMNPQRSUVW]-?\d{7}[0-9A-J]|\d{8}-?[A-Z]|[XYZ]-?\d{7}-?[A-Z])\b")


def buscar_nif(texto: str) -> str:
    m = _RE_NIF.search((texto or "").upper())
    return m.group(1).replace("-", "") if m else ""


# --------------------------------------------------- cabeceras de columnas

_EXACTOS = {
    "num factura": "numero", "numero factura": "numero", "num fra": "numero", "factura": "numero",
    "num": "numero", "numero": "numero", "documento": "numero", "num documento": "numero",
    "num doc": "numero", "fra": "numero", "n factura": "numero",
    "serie": "serie",
    "fecha": "fecha", "fecha factura": "fecha", "f factura": "fecha", "fecha fra": "fecha",
    "cliente": "cliente", "nombre": "cliente", "razon social": "cliente", "nombre cliente": "cliente",
    "cod cliente": "cod_cliente", "codigo cliente": "cod_cliente", "codigo": "cod_cliente",
    "cod": "cod_cliente", "cuenta": "cod_cliente",
    "nif": "nif", "cif": "nif", "nif cif": "nif", "cif nif": "nif", "dni": "nif", "nif dni": "nif",
    "tipo": "tipo", "tipo factura": "tipo", "forma pago": "tipo", "forma de pago": "tipo",
    "f pago": "tipo", "pago": "tipo",
    "base": "base", "base imponible": "base", "b imponible": "base", "base imp": "base", "bi": "base",
    "% iva": "iva_pct", "iva %": "iva_pct", "%iva": "iva_pct", "tipo iva": "iva_pct", "t iva": "iva_pct",
    "cuota iva": "iva", "iva": "iva", "imp iva": "iva", "importe iva": "iva", "cuota": "iva",
    "% re": "re_pct", "re %": "re_pct", "%re": "re_pct", "% rec": "re_pct", "% recargo": "re_pct",
    "tipo re": "re_pct",
    "re": "re", "recargo": "re", "cuota re": "re", "rec equiv": "re", "recargo equivalencia": "re",
    "imp re": "re", "r e": "re",
    "% irpf": "irpf_pct", "irpf %": "irpf_pct", "%irpf": "irpf_pct", "% ret": "irpf_pct",
    "% retencion": "irpf_pct", "tipo irpf": "irpf_pct",
    "irpf": "irpf", "retencion": "irpf", "ret": "irpf", "cuota irpf": "irpf",
    "total": "total", "total factura": "total", "importe total": "total", "liquido": "total",
    "importe": "total", "total fra": "total", "pvp": "total", "total pvp": "total",
    "vencim": None, "vencimiento": None, "f vencimiento": None, "margen": None, "fl": None,
}


def campo_de_cabecera(texto: str) -> Optional[str]:
    n = normalizar(texto)
    if not n:
        return None
    if n in _EXACTOS:
        return _EXACTOS[n]
    if n.startswith("venc") or n.startswith("margen") or n.startswith("benef"):
        return None
    tiene = lambda *ps: any(p in n.split() or p in n for p in ps)  # noqa: E731
    pct = "%" in n or "porc" in n or n.startswith("tipo ") or n.startswith("t ")
    if "iva" in n.split():
        if "sin" in n.split():
            return "base"
        if n.startswith("total") and ("con" in n.split() or "incl" in n):
            return "total"
        return "iva_pct" if pct else "iva"
    if tiene("recargo") or "re" in n.split():
        return "re_pct" if pct else "re"
    if tiene("irpf", "retenc"):
        return "irpf_pct" if pct else "irpf"
    if tiene("base"):
        return "base"
    if tiene("total", "liquido"):
        return "total"
    if tiene("fecha"):
        return "fecha"
    if tiene("nif", "cif", "dni"):
        return "nif"
    if ("cod" in n or "cuenta" in n) and "cliente" in n:
        return "cod_cliente"
    if tiene("cliente", "razon", "nombre"):
        return "cliente"
    if tiene("serie"):
        return "serie"
    if tiene("pago", "tipo"):
        return "tipo"
    if tiene("factura", "num", "documento"):
        return "numero"
    return None


def ajustar_campos(campos: list[Optional[str]]) -> list[Optional[str]]:
    """Si no hay columna de número de factura pero sí 'Código' y 'Cliente',
    el código es el número de factura (p. ej. Diario de facturación ampliado)."""
    if "numero" not in campos and "cod_cliente" in campos and "cliente" in campos:
        return ["numero" if c == "cod_cliente" else c for c in campos]
    return campos


def es_cabecera(campos: list[Optional[str]]) -> bool:
    c = set(x for x in campos if x)
    return len(c) >= 3 and bool(c & {"fecha", "numero"}) and bool(c & {"base", "total"})


# ------------------------------------------------------------- resultado


@dataclass
class Diario:
    archivo: str
    facturas: list[Factura] = field(default_factory=list)
    clientes: dict[str, Cliente] = field(default_factory=dict)
    avisos: list[str] = field(default_factory=list)
    desde: Optional[date] = None  # periodo indicado en el diario (Desde: / Hasta:)
    hasta: Optional[date] = None

    @property
    def fecha_desde(self) -> Optional[date]:
        if self.desde:
            return self.desde
        fs = [f.fecha for f in self.facturas if f.fecha]
        return min(fs) if fs else None

    @property
    def fecha_hasta(self) -> Optional[date]:
        if self.hasta:
            return self.hasta
        fs = [f.fecha for f in self.facturas if f.fecha]
        return max(fs) if fs else None

    def _indice(self) -> dict[str, list[Factura]]:
        idx = self.__dict__.get("_idx")
        if idx is None or self.__dict__.get("_idx_n") != len(self.facturas):
            def orden(f):
                dig = re.findall(r"\d+", f.numero)
                return (f.fecha or date.min, int(dig[-1]) if dig else 0, f.numero)
            idx = {}
            for f in self.facturas:
                idx.setdefault(f.cliente_clave, []).append(f)
            for lista in idx.values():
                lista.sort(key=orden)
            self.__dict__["_idx"], self.__dict__["_idx_n"] = idx, len(self.facturas)
        return idx

    def facturas_de(self, clave: str) -> list[Factura]:
        return list(self._indice().get(clave, []))

    def filtrar(self, desde: Optional[date], hasta: Optional[date]) -> "Diario":
        """Copia del diario con solo las facturas del periodo indicado."""
        fs = [f for f in self.facturas
              if (not desde or (f.fecha and f.fecha >= desde)) and (not hasta or (f.fecha and f.fecha <= hasta))]
        claves = {f.cliente_clave for f in fs}
        return Diario(archivo=self.archivo, facturas=fs,
                      clientes={k: c for k, c in self.clientes.items() if k in claves},
                      avisos=self.avisos, desde=desde or self.desde, hasta=hasta or self.hasta)

    def to_dict(self) -> dict:
        return {
            "archivo": self.archivo,
            "facturas": [f.to_dict() for f in self.facturas],
            "clientes": {k: c.to_dict() for k, c in self.clientes.items()},
            "avisos": self.avisos,
            "desde": self.desde.isoformat() if self.desde else None,
            "hasta": self.hasta.isoformat() if self.hasta else None,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Diario":
        return cls(
            archivo=d.get("archivo", ""),
            facturas=[Factura.from_dict(x) for x in d.get("facturas", [])],
            clientes={k: Cliente.from_dict(v) for k, v in d.get("clientes", {}).items()},
            avisos=d.get("avisos", []),
            desde=date.fromisoformat(d["desde"]) if d.get("desde") else None,
            hasta=date.fromisoformat(d["hasta"]) if d.get("hasta") else None,
        )


# --------------------------------------------------------- lectura de PDF


def _agrupar_lineas(palabras: list[dict], tolerancia: float = 3.0) -> list[list[dict]]:
    lineas: list[list[dict]] = []
    for w in sorted(palabras, key=lambda w: (round(w["top"]), w["x0"])):
        if lineas and abs(lineas[-1][0]["top"] - w["top"]) <= tolerancia:
            lineas[-1].append(w)
        else:
            lineas.append([w])
    return [sorted(l, key=lambda w: w["x0"]) for l in lineas]


def _frases(linea: list[dict], hueco: float = 4.5) -> list[dict]:
    """Une palabras cercanas en celdas ("Base" + "Imponible")."""
    out: list[dict] = []
    for w in linea:
        if out and w["x0"] - out[-1]["x1"] <= hueco:
            out[-1] = {"text": out[-1]["text"] + " " + w["text"], "x0": out[-1]["x0"], "x1": w["x1"]}
        else:
            out.append({"text": w["text"], "x0": w["x0"], "x1": w["x1"]})
    return out


def _cabecera_pdf(linea: list[dict]) -> Optional[list[dict]]:
    celdas = _frases(linea)
    campos = ajustar_campos([campo_de_cabecera(c["text"]) for c in celdas])
    if not es_cabecera(campos):
        # segundo intento: cada palabra como celda propia
        celdas = [{"text": w["text"], "x0": w["x0"], "x1": w["x1"]} for w in linea]
        campos = ajustar_campos([campo_de_cabecera(c["text"]) for c in celdas])
        if not es_cabecera(campos):
            return None
    cols = []
    vistos = set()
    for i, (c, campo) in enumerate(zip(celdas, campos)):
        if not campo:
            # columna que no nos interesa (vencimiento, margen…): se conserva para
            # que sus datos no se cuelen en la columna de al lado
            cols.append({"campo": f"_col{i}", "x0": c["x0"], "x1": c["x1"]})
            continue
        if campo in vistos:  # segunda columna "IVA" suele ser la cuota
            if campo == "iva_pct":
                campo = "iva"
            elif campo == "re_pct":
                campo = "re"
            elif campo == "irpf_pct":
                campo = "irpf"
            else:
                continue
        vistos.add(campo)
        cols.append({"campo": campo, "x0": c["x0"], "x1": c["x1"]})
    return cols


_TEXTO = {"cliente", "nif", "tipo", "serie", "cod_cliente"}


def _asignar(cols: list[dict], w: dict) -> Optional[str]:
    mejor, mejor_sol = None, 0.0
    for c in cols:
        sol = min(w["x1"], c["x1"] + 2) - max(w["x0"], c["x0"] - 2)
        if sol > mejor_sol:
            mejor, mejor_sol = c["campo"], sol
    if mejor:
        return mejor
    # Dentro del hueco de una columna de texto (p. ej. un teléfono en el nombre del
    # cliente) pertenece a esa columna aunque parezca un número.
    orden = sorted(cols, key=lambda c: c["x0"])
    for c, sig in zip(orden, orden[1:]):
        if c["campo"] in _TEXTO and w["x0"] >= c["x0"] - 2 and w["x1"] <= sig["x0"] - 1:
            return c["campo"]
    # Sin solape: el texto se alinea a la izquierda (columna que empieza antes)
    # y los importes a la derecha (columna que termina después).
    centro = (w["x0"] + w["x1"]) / 2
    if parse_importe(w["text"]) is not None:
        return min(cols, key=lambda c: abs(centro - (c["x0"] + c["x1"]) / 2))["campo"]
    candidatos = [c for c in cols if c["x0"] <= w["x0"] + 2]
    if candidatos:
        return max(candidatos, key=lambda c: c["x0"])["campo"]
    return min(cols, key=lambda c: min(abs(centro - c["x0"]), abs(centro - c["x1"])))["campo"]


_NUMERICOS = {"base", "iva_pct", "iva", "re_pct", "re", "irpf_pct", "irpf", "total"}


def _es_ancla(linea: list[dict]) -> bool:
    """Línea principal de una factura: la que lleva la fecha."""
    return any(parse_fecha(w["text"]) for w in linea)


def _importes(linea: list[dict], cols: list[dict]) -> int:
    return sum(1 for w in linea if parse_importe(w["text"]) is not None and _asignar(cols, w) in _NUMERICOS)


def _es_pegable(linea: list[dict], texto: str, cols: list[dict]) -> bool:
    """Trozo de una fila partida en varias líneas (p. ej. nombre largo del cliente)."""
    if _importes(linea, cols) > 1:
        return False
    n = normalizar(texto)
    if re.match(r"^(sub)?total|^suma|^totales", n) or _RE_ETIQUETA_CLIENTE.match(texto) or buscar_nif(texto):
        return False
    if sum(1 for w in linea if campo_de_cabecera(w["text"])) >= 2:
        return False
    return True


def _a_fila(trozos: list[list[dict]], cols: list[dict]) -> dict:
    partes: dict[str, list[str]] = {}
    for linea in trozos:
        for w in linea:
            partes.setdefault(_asignar(cols, w), []).append(w["text"])
    fila: dict = {"_texto": " ".join(" ".join(w["text"] for w in l) for l in trozos)}
    for campo, ps in partes.items():
        fila[campo] = ("" if campo in _NUMERICOS else " ").join(ps)
    return fila


def _volcar(pendientes: list[dict], filas: list[dict]) -> None:
    """Convierte las líneas de una página en filas, uniendo las líneas partidas a su
    línea principal más cercana (los PDF centran en vertical las celdas de una línea)."""
    if not pendientes:
        return
    anclas = [i for i, p in enumerate(pendientes) if _es_ancla(p["linea"])]
    tops = [pendientes[i]["top"] for i in anclas]
    saltos = sorted(b - a for a, b in zip(tops, tops[1:]) if b > a)
    paso = saltos[len(saltos) // 2] if saltos else 14.0
    umbral = max(3.0, paso * 0.45)
    grupos: dict[int, list[int]] = {i: [i] for i in anclas}
    sueltas = []
    for i, p in enumerate(pendientes):
        if i in grupos:
            continue
        if anclas and _es_pegable(p["linea"], p["texto"], p["cols"]):
            j = min(anclas, key=lambda a: abs(pendientes[a]["top"] - p["top"]))
            if abs(pendientes[j]["top"] - p["top"]) <= umbral and pendientes[j]["cols"] is p["cols"]:
                grupos[j].append(i)
                continue
        sueltas.append(i)
    salida = []
    for j, miembros in grupos.items():
        miembros.sort(key=lambda k: pendientes[k]["top"])
        salida.append((pendientes[j]["top"], _a_fila([pendientes[k]["linea"] for k in miembros], pendientes[j]["cols"])))
    for i in sueltas:
        p = pendientes[i]
        salida.append((p["top"], _a_fila([p["linea"]], p["cols"])))
    salida.sort(key=lambda x: x[0])
    filas.extend(f for _, f in salida)
    pendientes.clear()


def _filas_pdf(ruta: Path) -> list[dict]:
    import pdfplumber

    filas: list[dict] = []
    cols = None
    with pdfplumber.open(str(ruta)) as pdf:
        for pagina in pdf.pages:
            pendientes: list[dict] = []
            palabras = pagina.extract_words(x_tolerance=1.5, y_tolerance=2, keep_blank_chars=False)
            for linea in _agrupar_lineas(palabras):
                texto = " ".join(w["text"] for w in linea)
                cab = _cabecera_pdf(linea)
                if cab:
                    _volcar(pendientes, filas)
                    cols = cab
                    continue
                if cols is None:
                    filas.append({"_texto": texto})
                    continue
                pendientes.append({"top": linea[0]["top"], "linea": linea, "texto": texto, "cols": cols})
            _volcar(pendientes, filas)
            pagina.flush_cache()
    return filas


# ------------------------------------------------- lectura de Excel / CSV


def _filas_tabla(tabla: list[list]) -> list[dict]:
    filas: list[dict] = []
    cab: Optional[list[Optional[str]]] = None
    for registro in tabla:
        celdas = ["" if v is None else v for v in registro]
        if not any(str(c).strip() for c in celdas):
            continue
        campos = ajustar_campos([campo_de_cabecera(str(c)) if isinstance(c, str) else None for c in celdas])
        if es_cabecera(campos):
            vistos, cab = set(), []
            for campo in campos:
                if campo in vistos and campo in ("iva_pct", "re_pct", "irpf_pct"):
                    campo = campo[:-4]
                cab.append(None if campo in vistos else campo)
                vistos.add(campo)
            continue
        texto = " ".join(str(c) for c in celdas if str(c).strip())
        if cab is None:
            filas.append({"_texto": texto})
            continue
        fila = {"_texto": texto}
        for campo, valor in zip(cab, celdas):
            if campo and str(valor).strip() != "":
                fila[campo] = valor
        filas.append(fila)
    return filas


def _filas_excel(ruta: Path) -> list[dict]:
    import openpyxl

    wb = openpyxl.load_workbook(str(ruta), data_only=True, read_only=True)
    filas: list[dict] = []
    for ws in wb.worksheets:
        filas += _filas_tabla([list(r) for r in ws.iter_rows(values_only=True)])
    return filas


def _filas_csv(ruta: Path) -> list[dict]:
    datos = ruta.read_bytes()
    for cod in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            texto = datos.decode(cod)
            break
        except UnicodeDecodeError:
            continue
    try:
        dialecto = csv.Sniffer().sniff(texto[:4000], delimiters=";,\t|")
    except csv.Error:
        dialecto = csv.excel
        dialecto.delimiter = ";"
    return _filas_tabla(list(csv.reader(texto.splitlines(), dialecto)))


# --------------------------------------------- de filas a facturas


def _texto(fila: dict, campo: str) -> str:
    v = fila.get(campo)
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def detectar_tipo(texto_tipo: str, serie: str, total: float, sin_cliente: bool, cfg: dict) -> str:
    n = normalizar(texto_tipo)
    if n:
        if re.search(r"simplif|ticket", n):
            return "Simplificada"
        if re.search(r"rectif|abono|devoluc", n):
            return "Rectificativa"
        if re.search(r"contado|efectivo|metalico|tarjeta|bizum|caja", n):
            return "Contado"
        if re.search(r"credito|giro|recibo|transferencia|pagare|domicil|aplazad|\d+\s*d", n):
            return "Crédito"
    series = cfg.get("tipos", {}).get("series", {})
    s = (serie or "").upper()
    for pref in sorted(series, key=len, reverse=True):
        if pref and s.startswith(pref.upper()):
            return series[pref]
    if total < 0:
        return "Rectificativa"
    if sin_cliente:
        return "Simplificada"
    return cfg.get("tipos", {}).get("por_defecto", "Crédito")


_RE_ETIQUETA_CLIENTE = re.compile(r"^\s*cliente\s*[:.]?\s*(.*)$", re.I)


def _cliente_desde_texto(texto: str) -> Optional[tuple[str, str, str]]:
    """Línea de agrupación tipo 'Cliente: 4300012 FERRETERIA PEPE SL  NIF B12345678'."""
    m = _RE_ETIQUETA_CLIENTE.match(texto)
    nif = buscar_nif(texto)
    if not m and not nif:
        return None
    resto = m.group(1) if m else texto
    if nif:
        resto = re.sub(r"(nif|cif|dni)\s*[:.]?\s*", " ", resto, flags=re.I)
        resto = re.sub(re.escape(nif), " ", resto.upper().replace("-", ""), flags=re.I)
    cod = ""
    mc = re.match(r"^\s*(\d{3,})\s*[-–]?\s*(.*)$", resto)
    if mc:
        cod, resto = mc.group(1), mc.group(2)
    nombre = " ".join(resto.replace(" - ", " ").split()).strip(" -")
    if not nombre and not nif:
        return None
    return nombre, nif, cod


def _es_total(fila: dict) -> bool:
    t = normalizar(fila.get("_texto", ""))
    return bool(re.match(r"^(sub)?total|^suma|^totales|^acumulado|.*\btotal (cliente|general|diario)", t))


def _completar_linea(base, iva_pct, iva, re_pct, re_c) -> LineaImpuesto:
    base = base or 0.0
    if iva is None and iva_pct is not None:
        iva = r2(base * iva_pct / 100)
    elif iva is not None and iva_pct is None:
        if base and abs(iva) > 0:
            calc = iva / base * 100
            if abs(aproximar(calc, IVA_TIPOS) - calc) <= 0.35:
                iva_pct = aproximar(calc, IVA_TIPOS)
            elif iva in IVA_TIPOS:  # la columna "IVA" era el porcentaje
                iva_pct, iva = iva, r2(base * iva / 100)
            else:
                iva_pct = r2(calc)
        else:
            iva_pct = 0.0
    if re_c is None and re_pct is not None:
        re_c = r2(base * re_pct / 100)
    elif re_c is not None and re_pct is None:
        if base and abs(re_c) > 0:
            calc = re_c / base * 100
            if abs(aproximar(calc, RE_TIPOS, 0.1) - calc) <= 0.1:
                re_pct = aproximar(calc, RE_TIPOS, 0.1)
            elif re_c in RE_TIPOS:
                re_pct, re_c = re_c, r2(base * re_c / 100)
            else:
                re_pct = r2(calc)
        else:
            re_pct = 0.0
    return LineaImpuesto(base=r2(base), iva_pct=iva_pct or 0.0, iva=r2(iva or 0.0),
                         re_pct=re_pct or 0.0, re=r2(re_c or 0.0))


_COMBINACIONES = [(21.0, 0.0), (10.0, 0.0), (5.0, 0.0), (4.0, 0.0), (2.0, 0.0), (0.0, 0.0),
                  (21.0, 5.2), (10.0, 1.4), (5.0, 0.62), (4.0, 0.5)]


def _linea_desde_total(base: float, total: float, irpf: float) -> LineaImpuesto:
    """Cuando el diario solo trae Base y Total (PVP), deduce IVA y recargo."""
    diff = total - base + abs(irpf or 0.0)
    if not base:
        return LineaImpuesto(base=0.0, iva=r2(diff))
    calc = diff / base * 100
    tol = max(0.35, 1.0 / abs(base) + 0.05)
    piva, pre = min(_COMBINACIONES, key=lambda c: abs(calc - c[0] - c[1]))
    if abs(calc - piva - pre) > tol:
        return LineaImpuesto(base=r2(base), iva_pct=r2(calc), iva=r2(diff))  # varios tipos
    if not pre:
        return LineaImpuesto(base=r2(base), iva_pct=piva, iva=r2(diff))
    iva = r2(base * piva / 100)
    return LineaImpuesto(base=r2(base), iva_pct=piva, iva=iva, re_pct=pre, re=r2(diff - iva))


def _nombre_clave(nombre: str) -> str:
    return " ".join((nombre or "").upper().split())


def filas_a_diario(filas: list[dict], archivo: str, cfg: dict) -> Diario:
    diario = Diario(archivo=archivo)
    actual_cli: Optional[tuple[str, str, str]] = None
    fact: Optional[Factura] = None
    id_actual: tuple = ()
    datos_cli: list[tuple[Factura, str, str, str]] = []
    totales_linea: list[float] = []
    total_cab: Optional[float] = None
    cif_empresa = buscar_nif(cfg.get("empresa", {}).get("cif", ""))

    def cerrar():
        nonlocal fact, totales_linea, total_cab
        if fact is None:
            return
        if fact.irpf and not fact.irpf_pct and fact.base:
            calc_irpf = fact.irpf / abs(fact.base) * 100
            if abs(aproximar(calc_irpf, IRPF_TIPOS) - calc_irpf) <= 0.35:
                fact.irpf_pct = aproximar(calc_irpf, IRPF_TIPOS)
            elif fact.irpf in IRPF_TIPOS:  # la columna "IRPF" era el porcentaje
                fact.irpf_pct, fact.irpf = fact.irpf, r2(abs(fact.base) * fact.irpf / 100)
            else:
                fact.irpf_pct = r2(calc_irpf)
        calc = fact.total_calculado
        if len(fact.lineas) > 1 and totales_linea and abs(sum(totales_linea) - calc) <= 0.05:
            fact.total = r2(sum(totales_linea))
        elif total_cab is not None:
            fact.total = r2(total_cab)
        else:
            fact.total = calc
        if abs(fact.total - calc) > 0.05:
            fact.aviso = f"El total del diario ({fact.total:.2f}) no cuadra con base + impuestos ({calc:.2f})"
        diario.facturas.append(fact)
        fact, totales_linea, total_cab = None, [], None

    for fila in filas:
        mp = re.match(r"^\s*(desde|hasta)\s*(?:fecha)?\s*:?\s*(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})\s*$",
                      fila.get("_texto", ""), re.I)
        if mp and not diario.facturas and fact is None:
            setattr(diario, mp.group(1).lower(), parse_fecha(mp.group(2)))
            continue
        if _es_total(fila):
            cerrar()
            continue
        numero = _texto(fila, "numero")
        fecha = parse_fecha(_texto(fila, "fecha")) if "fecha" in fila else None
        if isinstance(fila.get("fecha"), (date, datetime)):
            fecha = parse_fecha(fila["fecha"])
        base = parse_importe(fila.get("base"))
        total = parse_importe(fila.get("total"))

        # Líneas de agrupación por cliente (sin importes)
        if base is None and total is None and (fecha is None or not numero):
            cli = _cliente_desde_texto(fila.get("_texto", ""))
            if cli and cif_empresa and cli[1] == cif_empresa:
                cli = None  # cabecera con los datos de nuestra propia empresa
            if cli:
                cerrar()
                actual_cli = cli
            elif sum(1 for w in fila.get("_texto", "").split() if campo_de_cabecera(w)) >= 2:
                cerrar()  # bloque de totales / resumen al final del diario
            continue

        valores = {k: parse_importe(fila.get(k)) for k in
                   ("iva_pct", "iva", "re_pct", "re", "irpf_pct", "irpf")}
        linea = _completar_linea(base, valores["iva_pct"], valores["iva"], valores["re_pct"], valores["re"])
        serie = _texto(fila, "serie")
        num_completo = f"{serie}-{numero}" if serie and not numero.upper().startswith(serie.upper()) else numero

        if ("iva" not in fila and "iva_pct" not in fila and total is not None
                and base is not None and not linea.re):
            linea = _linea_desde_total(base, total, parse_importe(fila.get("irpf")) or 0.0)

        ident = (_texto(fila, "tipo").lower(), num_completo, fecha)
        nueva = bool(numero) and (fact is None or ident != id_actual)
        if nueva:
            cerrar()
            nombre = _texto(fila, "cliente")
            nif = buscar_nif(_texto(fila, "nif")) or _texto(fila, "nif").upper()
            cod = _texto(fila, "cod_cliente")
            if not cod:
                mc = re.match(r"^\s*(\d+)\s+-\s*(.*)$", nombre)  # "4399 - FLUHIDRA, S.L."
                if mc:
                    cod, nombre = mc.group(1), mc.group(2).strip()
            if not (nombre or nif or cod) and actual_cli:
                nombre, nif, cod = actual_cli
            if not nif and nombre:
                nif = buscar_nif(nombre)
                if nif:
                    nombre = " ".join(nombre.upper().replace(nif, "").split()) or nombre
            sin_cliente = not (nombre or nif or cod)
            if sin_cliente:
                nombre = "Clientes varios (sin identificar)"
            serie_tipo = serie or re.match(r"^[A-Za-z]*", numero).group(0)
            tipo = detectar_tipo(_texto(fila, "tipo"), serie_tipo, total or linea.base, sin_cliente, cfg)
            fact = Factura(numero=num_completo, fecha=fecha, tipo=tipo)
            datos_cli.append((fact, nombre, nif, cod))
            id_actual = ident
            total_cab = total
        elif fact is None:
            continue
        if base is not None or linea.iva or linea.re:
            fact.lineas.append(linea)
        if total is not None:
            totales_linea.append(total)
        irpf, irpf_pct = valores["irpf"], valores["irpf_pct"]
        if irpf is None and irpf_pct:
            irpf = r2(linea.base * irpf_pct / 100)
        if irpf:
            fact.irpf = r2(fact.irpf + abs(irpf))
            fact.irpf_pct = irpf_pct or fact.irpf_pct
    cerrar()

    # Clientes: por NIF; si no hay, por código. Un código usado con nombres distintos
    # (p. ej. 0 o 9999 = "clientes de contado") se separa por nombre.
    nombres_por_cod: dict[str, set] = {}
    for _, nombre, nif, cod in datos_cli:
        if cod and not nif:
            nombres_por_cod.setdefault(cod, set()).add(_nombre_clave(nombre))
    for f, nombre, nif, cod in datos_cli:
        generico = bool(cod) and len(nombres_por_cod.get(cod, ())) > 1
        clave = clave_cliente(nombre, nif, "" if generico else cod)
        f.cliente_clave = clave
        if clave not in diario.clientes:
            diario.clientes[clave] = Cliente(clave=clave, nombre=nombre, nif=nif,
                                             codigo="" if generico else cod)

    if not diario.facturas:
        diario.avisos.append(
            "No se ha encontrado ninguna factura. Comprueba que el diario tiene una fila de cabecera "
            "con columnas como Nº factura, Fecha, Base y Total.")
    else:
        con_aviso = sum(1 for f in diario.facturas if f.aviso)
        if con_aviso:
            diario.avisos.append(f"{con_aviso} factura(s) con totales que no cuadran: revísalas.")
    return diario


def leer_diario(ruta, cfg: dict) -> Diario:
    ruta = Path(ruta)
    ext = ruta.suffix.lower()
    if ext == ".pdf":
        filas = _filas_pdf(ruta)
    elif ext in (".xlsx", ".xlsm"):
        filas = _filas_excel(ruta)
    elif ext in (".csv", ".txt"):
        filas = _filas_csv(ruta)
    else:
        raise ValueError(f"Formato no admitido: {ext}")
    return filas_a_diario(filas, ruta.name, cfg)
