"""Estructuras de datos: facturas, líneas de impuestos y clientes."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Optional

TIPOS_FACTURA = ["Contado", "Crédito", "Simplificada", "Rectificativa", "Factura"]

IVA_TIPOS = [21.0, 10.0, 5.0, 4.0, 2.0, 0.0]
RE_TIPOS = [5.2, 1.75, 1.4, 0.62, 0.5, 0.26, 0.0]
IRPF_TIPOS = [19.0, 15.0, 7.0, 2.0, 1.0, 0.0]


def r2(x: float) -> float:
    return round(x + 0.0, 2)


@dataclass
class LineaImpuesto:
    base: float = 0.0
    iva_pct: float = 0.0
    iva: float = 0.0
    re_pct: float = 0.0
    re: float = 0.0


@dataclass
class Factura:
    numero: str
    fecha: Optional[date]
    tipo: str = "Factura"
    lineas: list[LineaImpuesto] = field(default_factory=list)
    irpf_pct: float = 0.0
    irpf: float = 0.0
    total: Optional[float] = None
    cliente_clave: str = ""
    aviso: str = ""

    @property
    def base(self) -> float:
        return r2(sum(l.base for l in self.lineas))

    @property
    def cuota_iva(self) -> float:
        return r2(sum(l.iva for l in self.lineas))

    @property
    def cuota_re(self) -> float:
        return r2(sum(l.re for l in self.lineas))

    @property
    def total_calculado(self) -> float:
        return r2(self.base + self.cuota_iva + self.cuota_re - self.irpf)

    @property
    def importe_total(self) -> float:
        return self.total if self.total is not None else self.total_calculado

    def to_dict(self) -> dict:
        d = asdict(self)
        d["fecha"] = self.fecha.isoformat() if self.fecha else None
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Factura":
        d = dict(d)
        d["lineas"] = [LineaImpuesto(**l) for l in d.get("lineas", [])]
        d["fecha"] = date.fromisoformat(d["fecha"]) if d.get("fecha") else None
        return cls(**d)


@dataclass
class Cliente:
    clave: str  # NIF si existe; si no, código o nombre
    nombre: str = ""
    nif: str = ""
    codigo: str = ""
    direccion: str = ""
    cp: str = ""
    poblacion: str = ""
    provincia: str = ""
    email: str = ""
    telefono: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Cliente":
        campos = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in d.items() if k in campos})


def clave_cliente(nombre: str, nif: str, codigo: str = "") -> str:
    nif = (nif or "").replace(" ", "").replace("-", "").upper()
    if nif:
        return nif
    if codigo:
        return "COD:" + codigo.strip()
    return "NOM:" + " ".join((nombre or "SIN CLIENTE").upper().split())


def aproximar(valor: float, candidatos: list[float], tolerancia: float = 0.35) -> float:
    """Ajusta un porcentaje calculado al tipo legal más cercano."""
    mejor = min(candidatos, key=lambda c: abs(c - valor))
    return mejor if abs(mejor - valor) <= tolerancia else r2(valor)
