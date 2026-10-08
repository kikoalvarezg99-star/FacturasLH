"""Guardado de diarios procesados, clientes y envíos."""
from __future__ import annotations

import json
import re
import shutil
import time
from datetime import datetime
from pathlib import Path

from .config import ruta_datos, ruta_documentos
from .exportar import exportar_csv, exportar_excel
from .informe import generar_listado
from .lector import Diario, leer_diario
from .modelo import Cliente, clave_cliente


def _leer_json(ruta: Path, defecto):
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except Exception:
        return defecto


def _escribir_json(ruta: Path, datos) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(ruta.suffix + ".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    tmp.replace(ruta)


def nombre_archivo(texto: str) -> str:
    t = re.sub(r'[\\/:*?"<>|]+', " ", texto or "").strip()
    return " ".join(t.split())[:80] or "sin nombre"


class Almacen:
    def __init__(self):
        self.base = ruta_datos()
        self.dir_diarios = self.base / "diarios"
        self.dir_entrada = self.base / "entrada"
        self.dir_diarios.mkdir(parents=True, exist_ok=True)
        self.dir_entrada.mkdir(parents=True, exist_ok=True)
        self._cache = None

    # --------------------------------------------------------- estado correo
    def estado_correo(self) -> dict:
        return _leer_json(self.base / "estado_correo.json", {})

    def guardar_estado_correo(self, estado: dict) -> None:
        _escribir_json(self.base / "estado_correo.json", estado)

    # -------------------------------------------------------------- clientes
    def clientes(self) -> dict[str, Cliente]:
        datos = _leer_json(self.base / "clientes.json", {})
        return {k: Cliente.from_dict(v) for k, v in datos.items()}

    def guardar_clientes(self, clientes: dict[str, Cliente]) -> None:
        _escribir_json(self.base / "clientes.json", {k: c.to_dict() for k, c in clientes.items()})

    def guardar_cliente(self, cliente: Cliente) -> None:
        cl = self.clientes()
        cl[cliente.clave] = cliente
        self.guardar_clientes(cl)

    def _fusionar_clientes(self, diario: Diario) -> None:
        cl = self.clientes()
        for k, c in diario.clientes.items():
            if k not in cl:
                cl[k] = c
            else:
                for campo in ("nombre", "nif", "codigo"):
                    if not getattr(cl[k], campo) and getattr(c, campo):
                        setattr(cl[k], campo, getattr(c, campo))
        self.guardar_clientes(cl)

    def importar_clientes(self, ruta) -> dict:
        """Importa la ficha de clientes exportada del programa de gestión (CSV o Excel).

        Reconoce columnas como cod_cliente, razon_social, nombre_comercial, cif, direccion1,
        cp, poblacion, provincia, telefono y email. Devuelve un resumen del resultado.
        """
        filas = leer_tabla_clientes(Path(ruta))
        cl = self.clientes()
        nuevos = actualizados = con_email = omitidos = 0
        for r in filas:
            g = lambda *ks: next((str(r[k]).strip() for k in ks if r.get(k) not in (None, "") and str(r[k]).strip()), "")  # noqa: E731
            if g("cliente_varios").upper() in ("S", "SI", "1", "TRUE") or g("fecha_baja"):
                omitidos += 1
                continue
            cod = g("cod_cliente", "codigo", "cod", "codigo_cliente", "cuenta")
            nombre = g("razon_social", "nombre", "nombre_comercial", "cliente")
            nif = g("cif", "nif", "nif_cif", "dni").upper().replace(" ", "").replace("-", "")
            if nif in ("0", "12345678X", "12345678D", "00000000T"):
                nif = ""
            if not (cod or nombre):
                continue
            if cod.endswith(".0"):
                cod = cod[:-2]
            clave = clave_cliente(nombre, "" if cod else nif, cod)
            c = cl.get(clave)
            if c is None:
                c = Cliente(clave=clave)
                cl[clave] = c
                nuevos += 1
            else:
                actualizados += 1
            email = re.sub(r"\s*[;,/ ]\s*", ", ", g("email", "correo", "e_mail", "mail")).strip(", ")
            c.nombre = nombre or c.nombre
            c.nif = nif or c.nif
            c.codigo = cod or c.codigo
            dirs = " ".join(x for x in (g("direccion1", "direccion", "domicilio"), g("direccion2")) if x)
            c.direccion = dirs or c.direccion
            c.cp = g("cp", "codigo_postal") or c.cp
            c.poblacion = g("poblacion", "localidad", "municipio") or c.poblacion
            c.provincia = g("provincia") or c.provincia
            c.telefono = g("telefono", "telefono2", "movil", "telefono3") or c.telefono
            if email and "@" in email:
                c.email = email
            if c.email:
                con_email += 1
        self.guardar_clientes(cl)
        return {"nuevos": nuevos, "actualizados": actualizados, "con_email": con_email, "omitidos": omitidos}

    def cliente(self, clave: str, diario: Diario | None = None) -> Cliente:
        c = self.clientes().get(clave)
        if c:
            return c
        if diario and clave in diario.clientes:
            return diario.clientes[clave]
        return Cliente(clave=clave, nombre=clave)

    # --------------------------------------------------------------- diarios
    # Cada diario recibido se guarda (uso interno) y sus facturas se integran en un
    # registro único de facturas: el diario más reciente manda en su periodo.
    def procesar(self, ruta_origen, cfg: dict, origen: str = "manual", asunto: str = "",
                 remitente: str = "") -> tuple[str, Diario]:
        ruta_origen = Path(ruta_origen)
        diario = leer_diario(ruta_origen, cfg)
        ident = time.strftime("%Y%m%d-%H%M%S")
        n = 1
        while (self.dir_diarios / ident).exists():
            n += 1
            ident = f"{time.strftime('%Y%m%d-%H%M%S')}-{n}"
        carpeta = self.dir_diarios / ident
        carpeta.mkdir(parents=True)
        destino = carpeta / ruta_origen.name
        shutil.copy2(ruta_origen, destino)
        _escribir_json(carpeta / "diario.json", diario.to_dict())
        _escribir_json(carpeta / "meta.json", {
            "id": ident, "archivo": ruta_origen.name, "original": destino.name,
            "recibido": datetime.now().isoformat(timespec="seconds"),
            "origen": origen, "asunto": asunto, "remitente": remitente,
            **self._resumen(diario),
        })
        self._fusionar_clientes(diario)
        if diario.facturas:
            self._integrar(diario)
        return ident, diario

    @staticmethod
    def _resumen(diario: Diario) -> dict:
        d, h = diario.fecha_desde, diario.fecha_hasta
        return {"num_facturas": len(diario.facturas), "num_clientes": len(diario.clientes),
                "desde": d.isoformat() if d else "", "hasta": h.isoformat() if h else "",
                "avisos": diario.avisos}

    def reprocesar(self, ident: str, cfg: dict) -> Diario:
        """Vuelve a leer el archivo original (útil tras una actualización del lector)."""
        diario = leer_diario(self.ruta_original(ident), cfg)
        self.guardar_diario(ident, diario)
        f = self.dir_diarios / ident / "meta.json"
        meta = _leer_json(f, {})
        meta.update(self._resumen(diario))
        _escribir_json(f, meta)
        self._fusionar_clientes(diario)
        self.reconstruir()
        return diario

    def lista_diarios(self) -> list[dict]:
        out = []
        for d in self.dir_diarios.iterdir():
            meta = _leer_json(d / "meta.json", None)
            if not meta:
                continue
            if "num_facturas" not in meta:  # diarios guardados por versiones anteriores
                meta.update(self._resumen(Diario.from_dict(_leer_json(d / "diario.json", {}))))
                _escribir_json(d / "meta.json", meta)
            out.append(meta)
        return sorted(out, key=lambda m: m["recibido"], reverse=True)

    def diario(self, ident: str) -> Diario:
        return Diario.from_dict(_leer_json(self.dir_diarios / ident / "diario.json", {}))

    def guardar_diario(self, ident: str, diario: Diario) -> None:
        _escribir_json(self.dir_diarios / ident / "diario.json", diario.to_dict())

    def meta(self, ident: str) -> dict:
        return _leer_json(self.dir_diarios / ident / "meta.json", {})

    def eliminar_diario(self, ident: str) -> None:
        shutil.rmtree(self.dir_diarios / ident, ignore_errors=True)
        self.reconstruir()

    def ruta_original(self, ident: str) -> Path:
        meta = self.meta(ident)
        return self.dir_diarios / ident / meta.get("original", "")

    # ------------------------------------------------- registro de facturas
    @property
    def _f_registro(self) -> Path:
        return self.base / "facturas.json"

    def registro(self) -> Diario:
        """Todas las facturas recibidas (sin duplicados)."""
        f = self._f_registro
        if not f.exists():
            if any(self.dir_diarios.iterdir()):
                self.reconstruir()
            else:
                return Diario(archivo="registro")
        mt = f.stat().st_mtime
        if self._cache is None or self._cache[0] != mt:
            d = Diario.from_dict(_leer_json(f, {}))
            d.desde = d.hasta = None
            self._cache = (mt, d)
        return self._cache[1]

    def _guardar_registro(self, d: Diario) -> None:
        _escribir_json(self._f_registro, d.to_dict())
        self._cache = None

    @staticmethod
    def _clave_factura(f) -> str:
        return f"{f.numero}|{f.fecha}|{f.cliente_clave}"

    def _integrar(self, diario: Diario, registro: Diario | None = None, guardar: bool = True) -> Diario:
        reg = registro or self.registro()
        desde, hasta = diario.fecha_desde, diario.fecha_hasta
        nuevas = {self._clave_factura(f) for f in diario.facturas}
        conservar = [f for f in reg.facturas
                     if not (desde and hasta and f.fecha and desde <= f.fecha <= hasta)
                     and self._clave_factura(f) not in nuevas]
        manuales = _leer_json(self.base / "tipos_manuales.json", {})
        for f in diario.facturas:
            f.tipo = manuales.get(self._clave_factura(f), f.tipo)
        reg = Diario(archivo="registro", facturas=conservar + list(diario.facturas),
                     clientes={**reg.clientes, **diario.clientes})
        if guardar:
            self._guardar_registro(reg)
        return reg

    def reconstruir(self) -> None:
        reg = Diario(archivo="registro")
        for meta in sorted(self.lista_diarios(), key=lambda m: m["recibido"]):
            reg = self._integrar(self.diario(meta["id"]), reg, guardar=False)
        self._guardar_registro(reg)

    def cambiar_tipo(self, factura, tipo: str) -> None:
        manuales = _leer_json(self.base / "tipos_manuales.json", {})
        manuales[self._clave_factura(factura)] = tipo
        _escribir_json(self.base / "tipos_manuales.json", manuales)
        reg = self.registro()
        clave = self._clave_factura(factura)
        for f in reg.facturas:
            if self._clave_factura(f) == clave:
                f.tipo = tipo
        factura.tipo = tipo
        self._guardar_registro(reg)

    def ultima_recepcion(self) -> str:
        lista = self.lista_diarios()
        return lista[0]["recibido"] if lista else ""

    # ----------------------------------------------------------------- envíos
    def envios(self, grupo: str) -> dict:
        return _leer_json(self.base / "envios.json", {}).get(grupo, {})

    def registrar_envio(self, grupo: str, clave: str, destinatarios: list[str]) -> None:
        f = self.base / "envios.json"
        datos = _leer_json(f, {})
        datos.setdefault(grupo, {}).setdefault(clave, []).append(
            {"fecha": datetime.now().isoformat(timespec="seconds"), "para": destinatarios})
        _escribir_json(f, datos)

    # -------------------------------------------------------------- salidas
    def carpeta(self, nombre: str) -> Path:
        p = ruta_documentos() / nombre_archivo(nombre)
        p.mkdir(parents=True, exist_ok=True)
        return p

    def generar_pdf(self, vista: Diario, clave: str, cfg: dict, etiqueta: str) -> Path:
        cliente = self.cliente(clave, vista)
        ruta = self.carpeta(etiqueta) / (nombre_archivo(f"Listado facturas {cliente.nombre} {etiqueta}") + ".pdf")
        return generar_listado(ruta, vista.facturas_de(clave), cliente, cfg, vista.desde, vista.hasta)

    def generar_excel(self, vista: Diario, clave: str | None, cfg: dict, etiqueta: str) -> Path:
        clientes = {**vista.clientes, **self.clientes()}
        if clave:
            facts = vista.facturas_de(clave)
            nombre = f"Listado facturas {self.cliente(clave, vista).nombre} {etiqueta}"
        else:
            facts = sorted(vista.facturas, key=lambda f: (clientes.get(f.cliente_clave, Cliente(f.cliente_clave)).nombre, f.fecha or datetime.min.date()))
            nombre = f"Facturas {etiqueta}"
        return exportar_excel(self.carpeta(etiqueta) / (nombre_archivo(nombre) + ".xlsx"), facts, clientes,
                              cfg["empresa"], titulo=f"Listado de facturas · {etiqueta}")

    def generar_csv(self, vista: Diario, clave: str | None, cfg: dict, etiqueta: str) -> Path:
        clientes = {**vista.clientes, **self.clientes()}
        if clave:
            facts = vista.facturas_de(clave)
            nombre = f"Listado facturas {self.cliente(clave, vista).nombre} {etiqueta}"
        else:
            facts = vista.facturas
            nombre = f"Facturas {etiqueta}"
        return exportar_csv(self.carpeta(etiqueta) / (nombre_archivo(nombre) + ".csv"), facts, clientes)

    def generar_347(self, fila, ejercicio: int, cfg: dict) -> Path:
        from .modelo347 import generar_carta
        ruta = self.carpeta(f"Modelo 347 {ejercicio}") / (nombre_archivo(f"Modelo 347 {ejercicio} {fila.cliente.nombre}") + ".pdf")
        return generar_carta(ruta, fila, ejercicio, cfg)

    def exportar_347(self, filas, ejercicio: int, cfg: dict) -> Path:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
        wb = Workbook()
        ws = wb.active
        ws.title = f"347 {ejercicio}"
        ws.append([cfg["empresa"]["nombre"]])
        ws.append([f"Modelo 347 · Ejercicio {ejercicio} · Clientes con operaciones > 3.005,06 €"])
        ws.append([])
        cab = ["Código", "Cliente", "NIF/CIF", "1T", "2T", "3T", "4T", "Total", "Facturas"]
        ws.append(cab)
        for c in ws[4]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="1F2328")
        for fl in filas:
            ws.append([fl.cliente.codigo, fl.cliente.nombre, fl.cliente.nif, *fl.trimestres, fl.total, len(fl.facturas)])
        n = ws.max_row
        ws.append(["", "TOTAL", "", *[f"=SUM({col}5:{col}{n})" for col in "DEFGH"], f"=SUM(I5:I{n})"])
        for row in ws.iter_rows(min_row=5, min_col=4, max_col=8):
            for c in row:
                c.number_format = '#,##0.00 €'
        for col, w in zip("ABCDEFGHI", [9, 42, 13, 13, 13, 13, 13, 14, 9]):
            ws.column_dimensions[col].width = w
        ws["A1"].font = Font(bold=True, size=13)
        ws.freeze_panes = "A5"
        ruta = self.carpeta(f"Modelo 347 {ejercicio}") / f"Resumen Modelo 347 {ejercicio}.xlsx"
        wb.save(ruta)
        return ruta


def _decodificar_texto(datos: bytes) -> str:
    try:
        return datos.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    # Exportaciones de algunos programas vienen en Windows-1252 y otras en Mac Roman:
    # se elige la que produce más letras españolas válidas.
    validas = set("ÑñÁÉÍÓÚáéíóúÜüºª")
    raras = set("„¼¥‡∑ÆØ¬")
    mejor, puntos = datos.decode("cp1252", errors="replace"), None
    for cod in ("cp1252", "mac_roman", "latin-1"):
        try:
            t = datos.decode(cod)
        except UnicodeDecodeError:
            continue
        p = sum(ch in validas for ch in t) - 3 * sum(ch in raras for ch in t)
        if puntos is None or p > puntos:
            mejor, puntos = t, p
    return mejor


def leer_tabla_clientes(ruta: Path) -> list[dict]:
    import csv
    import io

    def clave(k):
        from .lector import normalizar
        return normalizar(str(k or "")).replace(" ", "_")

    if ruta.suffix.lower() in (".xlsx", ".xlsm"):
        import openpyxl
        ws = openpyxl.load_workbook(str(ruta), data_only=True, read_only=True).worksheets[0]
        filas = [list(r) for r in ws.iter_rows(values_only=True)]
        if not filas:
            return []
        cab = [clave(c) for c in filas[0]]
        return [dict(zip(cab, f)) for f in filas[1:]]
    texto = _decodificar_texto(ruta.read_bytes()).replace("\r\n", "\n").replace("\r", "\n")
    try:
        dialecto = csv.Sniffer().sniff(texto[:5000], delimiters=";,\t|")
        sep = dialecto.delimiter
    except csv.Error:
        sep = ";"
    lector = csv.reader(io.StringIO(texto), delimiter=sep)
    filas = list(lector)
    if not filas:
        return []
    cab = [clave(c) for c in filas[0]]
    return [dict(zip(cab, f)) for f in filas[1:] if any(x.strip() for x in f)]
