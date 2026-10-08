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
from .informe import MESES, generar_listado
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
            "origen": origen, "asunto": asunto, "remitente": remitente, "envios": {},
            **self._resumen(diario),
        })
        self._fusionar_clientes(diario)
        return ident, diario

    @staticmethod
    def _resumen(diario: Diario) -> dict:
        d, h = diario.fecha_desde, diario.fecha_hasta
        return {"num_facturas": len(diario.facturas), "num_clientes": len(diario.clientes),
                "desde": d.isoformat() if d else "", "hasta": h.isoformat() if h else "",
                "avisos": diario.avisos}

    def reprocesar(self, ident: str, cfg: dict) -> Diario:
        """Vuelve a leer el archivo original (útil tras una actualización del lector)."""
        anterior = self.diario(ident)
        diario = leer_diario(self.ruta_original(ident), cfg)
        if len(anterior.facturas) == len(diario.facturas):  # conserva tipos corregidos a mano
            for viejo, nuevo in zip(anterior.facturas, diario.facturas):
                if (viejo.numero, viejo.fecha) == (nuevo.numero, nuevo.fecha):
                    nuevo.tipo = viejo.tipo
        self.guardar_diario(ident, diario)
        f = self.dir_diarios / ident / "meta.json"
        meta = _leer_json(f, {})
        meta.update(self._resumen(diario))
        _escribir_json(f, meta)
        self._fusionar_clientes(diario)
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

    def registrar_envio(self, ident: str, clave: str, destinatarios: list[str]) -> None:
        f = self.dir_diarios / ident / "meta.json"
        meta = _leer_json(f, {})
        meta.setdefault("envios", {}).setdefault(clave, []).append(
            {"fecha": datetime.now().isoformat(timespec="seconds"), "para": destinatarios})
        _escribir_json(f, meta)

    def eliminar_diario(self, ident: str) -> None:
        shutil.rmtree(self.dir_diarios / ident, ignore_errors=True)

    def ruta_original(self, ident: str) -> Path:
        meta = self.meta(ident)
        return self.dir_diarios / ident / meta.get("original", "")

    # -------------------------------------------------------------- salidas
    def carpeta_salida(self, ident: str, diario: Diario) -> Path:
        d = diario.fecha_hasta
        nombre = f"{d.year}-{d.month:02d} {MESES[d.month - 1]}" if d else ident
        p = ruta_documentos() / nombre
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _base_nombre(self, diario: Diario, cliente: Cliente) -> str:
        d = diario.fecha_hasta
        sufijo = f" {d.year}-{d.month:02d}" if d else ""
        return nombre_archivo(f"Listado facturas {cliente.nombre}{sufijo}")

    def generar_pdf(self, ident: str, diario: Diario, clave: str, cfg: dict) -> Path:
        cliente = self.cliente(clave, diario)
        ruta = self.carpeta_salida(ident, diario) / (self._base_nombre(diario, cliente) + ".pdf")
        return generar_listado(ruta, diario.facturas_de(clave), cliente, cfg,
                               diario.fecha_desde, diario.fecha_hasta)

    def generar_excel(self, ident: str, diario: Diario, clave: str | None, cfg: dict) -> Path:
        clientes = {**diario.clientes, **self.clientes()}
        if clave:
            cliente = self.cliente(clave, diario)
            facts = diario.facturas_de(clave)
            nombre = self._base_nombre(diario, cliente)
        else:
            facts = sorted(diario.facturas, key=lambda f: (clientes.get(f.cliente_clave, Cliente(f.cliente_clave)).nombre, f.fecha or datetime.min.date()))
            nombre = f"Diario completo {ident}"
        return exportar_excel(self.carpeta_salida(ident, diario) / (nombre + ".xlsx"), facts, clientes,
                              cfg["empresa"], titulo="Listado de facturas")

    def generar_csv(self, ident: str, diario: Diario, clave: str | None, cfg: dict) -> Path:
        clientes = {**diario.clientes, **self.clientes()}
        if clave:
            facts = diario.facturas_de(clave)
            nombre = self._base_nombre(diario, self.cliente(clave, diario))
        else:
            facts = diario.facturas
            nombre = f"Diario completo {ident}"
        return exportar_csv(self.carpeta_salida(ident, diario) / (nombre + ".csv"), facts, clientes)


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
