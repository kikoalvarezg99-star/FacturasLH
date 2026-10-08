"""Correo: descarga de diarios desde una carpeta IMAP y envío de listados por SMTP."""
from __future__ import annotations

import base64
import email
import imaplib
import re
import smtplib
import ssl
import time
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, parseaddr
from pathlib import Path

EXTENSIONES = (".pdf", ".xlsx", ".xlsm", ".csv")


# ------------------------------------------------ nombres de carpeta IMAP (UTF-7 modificado)


def _utf7_decode(s: str) -> str:
    def repl(m):
        txt = m.group(1)
        if txt == "":
            return "&"
        txt = txt.replace(",", "/")
        txt += "=" * (-len(txt) % 4)
        return base64.b64decode(txt).decode("utf-16-be")
    return re.sub(r"&([^-]*)-", repl, s)


def _utf7_encode(s: str) -> str:
    out, buf = [], []

    def flush():
        if buf:
            b = base64.b64encode("".join(buf).encode("utf-16-be")).decode().rstrip("=").replace("/", ",")
            out.append(f"&{b}-")
            buf.clear()
    for ch in s:
        if 0x20 <= ord(ch) <= 0x7E:
            flush()
            out.append("&-" if ch == "&" else ch)
        else:
            buf.append(ch)
    flush()
    return "".join(out)


def _q(nombre: str) -> str:
    return '"' + nombre.replace("\\", "\\\\").replace('"', '\\"') + '"'


# --------------------------------------------------------------- conexión


def _imap(cfg: dict, password: str) -> imaplib.IMAP4:
    c = cfg["correo"]
    host, puerto = c["imap_servidor"].strip(), int(c.get("imap_puerto") or 993)
    if not host:
        raise RuntimeError("Falta el servidor IMAP en Configuración > Correo.")
    if puerto == 993:
        m = imaplib.IMAP4_SSL(host, puerto, ssl_context=ssl.create_default_context(), timeout=30)
    else:
        m = imaplib.IMAP4(host, puerto, timeout=30)
        try:
            m.starttls(ssl_context=ssl.create_default_context())
        except Exception:
            pass
    m.login(c["usuario"], password)
    return m


def listar_carpetas(m: imaplib.IMAP4) -> list[tuple[str, str, str]]:
    """Devuelve [(nombre_imap, nombre_legible, flags)]."""
    typ, datos = m.list()
    out = []
    for linea in datos or []:
        if not linea:
            continue
        t = linea.decode(errors="replace")
        mm = re.match(r'\((?P<flags>[^)]*)\)\s+(?:"(?P<sep>[^"]*)"|NIL)\s+(?P<nombre>.+)$', t)
        if not mm:
            continue
        nombre = mm.group("nombre").strip()
        if nombre.startswith('"') and nombre.endswith('"'):
            nombre = nombre[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        out.append((nombre, _utf7_decode(nombre), mm.group("flags")))
    return out


def _buscar_carpeta(m: imaplib.IMAP4, buscada: str) -> str:
    """Localiza la carpeta aunque el servidor la llame INBOX.Diarios o INBOX/Diarios."""
    objetivo = buscada.strip().lower()
    carpetas = listar_carpetas(m)
    for imap_n, legible, _ in carpetas:
        if legible.lower() == objetivo:
            return imap_n
    for imap_n, legible, _ in carpetas:
        if re.split(r"[./]", legible)[-1].lower() == objetivo:
            return imap_n
    disponibles = ", ".join(l for _, l, _ in carpetas)
    raise RuntimeError(f"No encuentro la carpeta «{buscada}» en el correo. Carpetas disponibles: {disponibles}")


def _decodificar(valor: str | None) -> str:
    if not valor:
        return ""
    try:
        return str(make_header(decode_header(valor)))
    except Exception:
        return valor


def probar_conexion(cfg: dict, password: str) -> str:
    """Comprueba IMAP y SMTP. Devuelve un texto con el resultado."""
    partes = []
    m = _imap(cfg, password)
    try:
        carpeta = _buscar_carpeta(m, cfg["correo"]["carpeta"])
        m.select(_q(carpeta), readonly=True)
        typ, d = m.uid("search", None, "ALL")
        n = len(d[0].split()) if d and d[0] else 0
        partes.append(f"✔ IMAP correcto. Carpeta «{_utf7_decode(carpeta)}» con {n} correo(s).")
    finally:
        try:
            m.logout()
        except Exception:
            pass
    s = _smtp(cfg, password)
    s.quit()
    partes.append("✔ SMTP correcto: se pueden enviar correos.")
    return "\n".join(partes)


# --------------------------------------------------------- recepción


def comprobar_correo(cfg: dict, password: str, destino: Path, estado: dict) -> list[dict]:
    """Descarga los adjuntos de los correos nuevos de la carpeta configurada.

    `estado` guarda {"uidvalidity": ..., "ultimo_uid": ...} para no procesar dos veces
    el mismo correo, aunque alguien lo abra antes desde Outlook o el móvil.
    """
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    nuevos: list[dict] = []
    m = _imap(cfg, password)
    try:
        carpeta = _buscar_carpeta(m, cfg["correo"]["carpeta"])
        typ, _ = m.select(_q(carpeta))
        if typ != "OK":
            raise RuntimeError(f"No se pudo abrir la carpeta {carpeta}")
        uv = m.untagged_responses.get("UIDVALIDITY", [b"0"])[0]
        uidvalidity = int(uv) if uv else 0
        if estado.get("uidvalidity") != uidvalidity:
            estado["uidvalidity"] = uidvalidity
            estado["ultimo_uid"] = 0
        ultimo = int(estado.get("ultimo_uid", 0))
        typ, d = m.uid("search", None, f"UID {ultimo + 1}:*")
        uids = [int(x) for x in (d[0].split() if d and d[0] else []) if int(x) > ultimo]
        for uid in sorted(uids):
            typ, msg_data = m.uid("fetch", str(uid), "(BODY.PEEK[])")
            if typ != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            asunto = _decodificar(msg.get("Subject"))
            remitente = parseaddr(_decodificar(msg.get("From")))[1]
            for parte in msg.walk():
                nombre = parte.get_filename()
                if not nombre:
                    continue
                nombre = _decodificar(nombre)
                if not nombre.lower().endswith(EXTENSIONES):
                    continue
                datos = parte.get_payload(decode=True)
                if not datos:
                    continue
                seguro = re.sub(r'[\\/:*?"<>|]+', "_", nombre)
                ruta = destino / f"{time.strftime('%Y%m%d-%H%M%S')}_{uid}_{seguro}"
                ruta.write_bytes(datos)
                nuevos.append({"ruta": str(ruta), "asunto": asunto, "remitente": remitente,
                               "uid": uid, "nombre": nombre})
            m.uid("store", str(uid), "+FLAGS", "(\\Seen)")
            estado["ultimo_uid"] = max(int(estado.get("ultimo_uid", 0)), uid)
    finally:
        try:
            m.logout()
        except Exception:
            pass
    return nuevos


# ------------------------------------------------------------- envío


def _smtp(cfg: dict, password: str) -> smtplib.SMTP:
    c = cfg["correo"]
    host, puerto = c["smtp_servidor"].strip(), int(c.get("smtp_puerto") or 465)
    if not host:
        raise RuntimeError("Falta el servidor SMTP en Configuración > Correo.")
    seg = (c.get("smtp_seguridad") or "SSL").upper()
    ctx = ssl.create_default_context()
    if seg == "SSL":
        s = smtplib.SMTP_SSL(host, puerto, context=ctx, timeout=30)
    else:
        s = smtplib.SMTP(host, puerto, timeout=30)
        s.ehlo()
        if seg == "STARTTLS":
            s.starttls(context=ctx)
            s.ehlo()
    s.login(c["usuario"], password)
    return s


def enviar_email(cfg: dict, password: str, para: list[str], asunto: str, cuerpo: str,
                 adjuntos: list[Path], copia_oculta: list[str] | None = None) -> None:
    c = cfg["correo"]
    msg = EmailMessage()
    msg["From"] = formataddr((c.get("remitente_nombre") or "", c["usuario"]))
    msg["To"] = ", ".join(para)
    msg["Subject"] = asunto
    msg["Message-ID"] = make_msgid(domain=c["usuario"].split("@")[-1] or None)
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg.set_content(cuerpo)
    html = "<br>".join(
        cuerpo.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").splitlines())
    msg.add_alternative(
        f'<div style="font-family:Segoe UI,Arial,sans-serif;font-size:14px;color:#1f2328">{html}</div>',
        subtype="html")
    tipos = {".pdf": ("application", "pdf"),
             ".xlsx": ("application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
             ".csv": ("text", "csv")}
    for ruta in adjuntos:
        ruta = Path(ruta)
        mt, st = tipos.get(ruta.suffix.lower(), ("application", "octet-stream"))
        msg.add_attachment(ruta.read_bytes(), maintype=mt, subtype=st, filename=ruta.name)
    destinatarios = list(para) + list(copia_oculta or [])
    s = _smtp(cfg, password)
    try:
        s.send_message(msg, to_addrs=destinatarios)
    finally:
        try:
            s.quit()
        except Exception:
            pass
    # Copia en "Enviados" (muchos servidores no la guardan al enviar por SMTP)
    try:
        m = _imap(cfg, password)
        try:
            enviados = None
            for imap_n, legible, flags in listar_carpetas(m):
                if "\\Sent" in flags or re.split(r"[./]", legible)[-1].lower() in (
                        "sent", "enviados", "elementos enviados", "sent items", "sent messages"):
                    enviados = imap_n
                    break
            if enviados:
                m.append(_q(enviados), "(\\Seen)", imaplib.Time2Internaldate(time.time()), msg.as_bytes())
        finally:
            m.logout()
    except Exception:
        pass
