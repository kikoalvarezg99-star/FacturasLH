"""Actualizaciones automáticas desde las "Releases" de GitHub.

Flujo:
1. Se consulta https://api.github.com/repos/<repo>/releases/latest
2. Si la etiqueta (p. ej. v1.2.0) es mayor que la versión instalada, se ofrece actualizar.
3. Se descarga FacturasLH.exe a una carpeta temporal y un pequeño .bat espera a que el
   programa se cierre, sustituye el .exe y lo vuelve a abrir.
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .version import VERSION

NOMBRE_EXE = "FacturasLH.exe"


@dataclass
class InfoVersion:
    version: str
    notas: str
    url_descarga: str
    url_api_asset: str
    pagina: str
    tamano: int


def _tupla(v: str) -> tuple:
    nums = re.findall(r"\d+", v or "")
    return tuple(int(x) for x in nums[:4]) or (0,)


def es_mas_nueva(remota: str, local: str = VERSION) -> bool:
    return _tupla(remota) > _tupla(local)


def _peticion(url: str, token: str = "", accept: str = "application/vnd.github+json"):
    req = urllib.request.Request(url, headers={
        "Accept": accept, "User-Agent": "FacturasLH-actualizador",
        "X-GitHub-Api-Version": "2022-11-28"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    return urllib.request.urlopen(req, timeout=20)


def buscar_actualizacion(repo: str, token: str = "") -> Optional[InfoVersion]:
    """Devuelve la información de la nueva versión, o None si ya está al día."""
    repo = (repo or "").strip().strip("/")
    repo = re.sub(r"^https?://github\.com/", "", repo)
    if not re.match(r"^[\w.-]+/[\w.-]+$", repo):
        raise RuntimeError("Repositorio de GitHub no válido (formato usuario/repositorio).")
    try:
        with _peticion(f"https://api.github.com/repos/{repo}/releases/latest", token) as r:
            datos = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise RuntimeError("Todavía no hay ninguna versión publicada en GitHub "
                               "(o el repositorio es privado y falta el token).") from e
        raise
    etiqueta = datos.get("tag_name", "")
    if not es_mas_nueva(etiqueta):
        return None
    asset = next((a for a in datos.get("assets", []) if a["name"].lower() == NOMBRE_EXE.lower()), None)
    if not asset:
        asset = next((a for a in datos.get("assets", []) if a["name"].lower().endswith(".exe")), None)
    if not asset:
        raise RuntimeError(f"La versión {etiqueta} no incluye {NOMBRE_EXE}.")
    return InfoVersion(
        version=etiqueta.lstrip("vV"), notas=datos.get("body") or "",
        url_descarga=asset["browser_download_url"], url_api_asset=asset["url"],
        pagina=datos.get("html_url", ""), tamano=int(asset.get("size") or 0))


def descargar(info: InfoVersion, token: str = "",
              progreso: Optional[Callable[[int, int], None]] = None) -> Path:
    destino = Path(tempfile.gettempdir()) / f"FacturasLH-{info.version}.exe"
    if token:  # repos privados: descarga a través de la API
        resp = _peticion(info.url_api_asset, token, accept="application/octet-stream")
    else:
        resp = _peticion(info.url_descarga, accept="application/octet-stream")
    total = int(resp.headers.get("Content-Length") or info.tamano or 0)
    leido = 0
    with resp, open(destino, "wb") as fh:
        while True:
            bloque = resp.read(256 * 1024)
            if not bloque:
                break
            fh.write(bloque)
            leido += len(bloque)
            if progreso:
                progreso(leido, total)
    if total and leido != total:
        raise RuntimeError("La descarga se ha interrumpido. Inténtalo de nuevo.")
    with open(destino, "rb") as fh:
        if fh.read(2) != b"MZ":
            raise RuntimeError("El archivo descargado no es un ejecutable válido.")
    return destino


def puede_autoinstalar() -> bool:
    return os.name == "nt" and getattr(sys, "frozen", False)


def instalar_y_reiniciar(nuevo_exe: Path) -> None:
    """Sustituye el .exe en cuanto este programa se cierre y lo vuelve a abrir.

    Se hace con PowerShell oculto (sin ventana negra): espera a que termine este
    proceso, reintenta mover el .exe nuevo hasta que Windows lo libera y lo arranca.
    """
    import base64

    lanzar_sustitucion(os.getpid(), nuevo_exe, Path(sys.executable), arrancar=True)


def lanzar_sustitucion(pid: int, nuevo: Path, actual: Path, arrancar: bool = True) -> subprocess.Popen:
    q = lambda p: str(p).replace("'", "''")  # noqa: E731
    script = (
        "$ErrorActionPreference = 'SilentlyContinue'\n"
        f"Wait-Process -Id {pid} -Timeout 60\n"
        "for ($i = 0; $i -lt 90; $i++) {\n"
        f"  try {{ Move-Item -LiteralPath '{q(nuevo)}' -Destination '{q(actual)}' -Force -ErrorAction Stop; break }}\n"
        "  catch { Start-Sleep -Milliseconds 700 }\n"
        "}\n"
        + (f"Start-Process -FilePath '{q(actual)}'\n" if arrancar else "")
    )
    codificado = base64.b64encode(script.encode("utf-16-le")).decode()
    flags = 0x08000000 | 0x00000200  # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    return subprocess.Popen(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                             "-WindowStyle", "Hidden", "-EncodedCommand", codificado],
                            creationflags=flags, close_fds=True)


def salir_para_actualizar() -> None:
    """Cierra el programa del todo para que el .exe quede libre."""
    os._exit(0)
