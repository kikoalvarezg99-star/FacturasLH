"""Rutas, configuración y almacenamiento de contraseñas."""
import copy
import json
import os
import sys
from pathlib import Path

from .version import GITHUB_REPO

# ----------------------------------------------------------------- rutas


def ruta_recursos() -> Path:
    """Carpeta con los recursos empaquetados (logo, iconos)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "assets"
    return Path(__file__).resolve().parent.parent / "assets"


def ruta_datos() -> Path:
    """Carpeta de datos del usuario (configuración, clientes, diarios)."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path.home() / ".local" / "share"
    p = Path(os.environ.get("FACTURASLH_DATOS", base / "FacturasLH"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def ruta_documentos() -> Path:
    """Carpeta visible donde se guardan los listados PDF / Excel."""
    p = Path(os.environ.get("FACTURASLH_DOCS", Path.home() / "Documents" / "Facturas LH"))
    p.mkdir(parents=True, exist_ok=True)
    return p


ARCHIVO_CONFIG = "config.json"

# Datos fijos de la empresa: no se pueden cambiar desde el programa.
EMPRESA = {
    "nombre": "Ferretería LH S.L.",
    "cif": "B90430356",
    "direccion": "Polg. Ind. La Campiña, calle Castilla la Mancha 12",
    "cp": "41400",
    "poblacion": "Écija",
    "provincia": "Sevilla",
    "telefono": "954 96 86 21",
    "email": "facturacion@ferreterialashuertas.es",
    "web": "",
    "logo": "",
    "color": "#C2410C",
}

PIN_CONFIGURACION = "2706"

DEFAULTS = {
    "empresa": dict(EMPRESA),
    "correo": {
        "usuario": "contabilidad@ferreterialashuertas.es",  # buzón donde llegan los diarios
        "smtp_usuario": "facturacion@ferreterialashuertas.es",  # cuenta que envía a los clientes
        "imap_servidor": "imap.ionos.es",
        "imap_puerto": 993,
        "smtp_servidor": "smtp.ionos.es",
        "smtp_puerto": 465,
        "smtp_seguridad": "SSL",  # SSL | STARTTLS | Ninguna
        "carpeta": "Diarios",
        "comprobar_auto": True,
        "intervalo_min": 10,
        "remitente_nombre": "Ferretería LH S.L. - Facturación",
        "copia_a_mi": True,
    },
    "envio": {
        "asunto": "Listado de facturas {periodo} - {empresa}",
        "cuerpo": (
            "Estimado/a {cliente}:\n\n"
            "Le adjuntamos el listado de facturas correspondiente a {periodo}, "
            "con {num_facturas} factura(s) por un importe total de {total}.\n\n"
            "Para cualquier consulta puede responder a este correo.\n\n"
            "Un saludo,\n{empresa}\nDpto. Administración\nTel. {empresa_telefono}"
        ),
        "adjuntar_excel": False,
        "adjuntar_csv": False,
    },
    "envio347": {
        "asunto": "Declaración anual Modelo 347 - Ejercicio {ejercicio} - {empresa}",
        "cuerpo": (
            "Estimado/a {cliente}:\n\n"
            "Le remitimos adjunto el detalle de las facturas realizadas durante el ejercicio {ejercicio} "
            "que figuran en nuestros archivos, por un importe total de {total}, "
            "a efectos de la declaración anual de operaciones con terceras personas (Modelo 347).\n\n"
            "Le agradeceríamos que, en caso de existir alguna discrepancia, nos lo indicara lo antes posible. "
            "En caso de no recibir respuesta, tomaremos estos datos como correctos y procederemos a su declaración.\n\n"
            "Un saludo,\n{empresa}\nDpto. Administración\nTel. {empresa_telefono}"
        ),
    },
    "modelo347": {
        "umbral": 3005.06,
    },
    "tipos": {
        # prefijo de serie -> tipo de factura (se usa si el diario no indica el tipo)
        "series": {
            "FS": "Simplificada",
            "TK": "Simplificada",
            "T": "Simplificada",
            "FR": "Rectificativa",
            "R": "Rectificativa",
            "CR": "Crédito",
            "FC": "Contado",
            "C": "Contado",
        },
        "por_defecto": "Crédito",
    },
    "actualizaciones": {
        "repo": GITHUB_REPO,
        "token": "",
        "comprobar_al_iniciar": True,
    },
    "general": {
        "iniciar_con_windows": False,
    },
}


def _fusionar(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            # "series" es un diccionario libre: se reemplaza entero
            out[k] = dict(v) if k == "series" else _fusionar(out[k], v)
        else:
            out[k] = v
    return out


def cargar_config() -> dict:
    f = ruta_datos() / ARCHIVO_CONFIG
    datos = {}
    if f.exists():
        try:
            datos = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            datos = {}
    cfg = _fusionar(DEFAULTS, datos)
    cfg["empresa"] = dict(EMPRESA)  # siempre los datos oficiales
    return cfg


def guardar_config(cfg: dict) -> None:
    f = ruta_datos() / ARCHIVO_CONFIG
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(f)


def ruta_logo(cfg: dict) -> Path:
    personal = cfg["empresa"].get("logo")
    if personal and Path(personal).exists():
        return Path(personal)
    return ruta_recursos() / "logo.png"


# ------------------------------------------------------- contraseña segura
_SERVICIO = "FacturasLH"


def guardar_password(usuario: str, password: str) -> None:
    """Guarda la contraseña en el Administrador de credenciales de Windows."""
    try:
        import keyring

        keyring.set_password(_SERVICIO, usuario, password)
        return
    except Exception:
        pass
    # Respaldo: archivo en la carpeta de datos del usuario (solo si no hay keyring)
    (ruta_datos() / ".pw").write_text(json.dumps({usuario: password}), encoding="utf-8")


def leer_password(usuario: str) -> str:
    try:
        import keyring

        pw = keyring.get_password(_SERVICIO, usuario)
        if pw:
            return pw
    except Exception:
        pass
    f = ruta_datos() / ".pw"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8")).get(usuario, "")
        except Exception:
            return ""
    return ""
