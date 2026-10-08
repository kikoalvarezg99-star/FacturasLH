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
from .modelo import Cliente


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
        })
        self._fusionar_clientes(diario)
        return ident, diario

    def lista_diarios(self) -> list[dict]:
        out = []
        for d in self.dir_diarios.iterdir():
            meta = _leer_json(d / "meta.json", None)
            if not meta:
                continue
            datos = _leer_json(d / "diario.json", {})
            facts = datos.get("facturas", [])
            fechas = sorted(f["fecha"] for f in facts if f.get("fecha"))
            meta["num_facturas"] = len(facts)
            meta["num_clientes"] = len(datos.get("clientes", {}))
            meta["desde"] = fechas[0] if fechas else ""
            meta["hasta"] = fechas[-1] if fechas else ""
            meta["avisos"] = datos.get("avisos", [])
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
