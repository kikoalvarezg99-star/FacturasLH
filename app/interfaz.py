"""Interfaz gráfica de Facturas LH (tkinter)."""
from __future__ import annotations

import calendar
import os
import queue
import subprocess
import sys
import threading
import traceback
import webbrowser
from datetime import date, datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import actualizador
from .almacen import Almacen
from .config import (PIN_CONFIGURACION, cargar_config, guardar_config, guardar_password,
                     leer_password, ruta_documentos, ruta_recursos)
from .informe import MESES, eur, fecha_es, texto_periodo
from .modelo import IVA_TIPOS, TIPOS_FACTURA, Cliente
from .modelo347 import UMBRAL, calcular
from .version import NOMBRE_APP, VERSION

# ------------------------------------------------------------------ estilo
C = {
    "lateral": "#1F2328",
    "lateral_hover": "#2D333B",
    "lateral_texto": "#C9D1D9",
    "fondo": "#F4F5F7",
    "tarjeta": "#FFFFFF",
    "borde": "#E6E8EB",
    "texto": "#1F2328",
    "suave": "#6B7280",
    "tenue": "#9CA3AF",
    "acento": "#C2410C",
    "acento_hover": "#9A3412",
    "acento_claro": "#FFF1E8",
    "ok": "#15803D",
    "aviso": "#B45309",
    "aviso_fondo": "#FEF3C7",
    "error": "#B91C1C",
    "fila_par": "#FAFAFB",
}
FUENTE = "Segoe UI" if os.name == "nt" else "DejaVu Sans"
PERIODOS = (["Año completo", "1er trimestre", "2º trimestre", "3er trimestre", "4º trimestre"]
            + [m.capitalize() for m in MESES])


def abrir_archivo(ruta) -> None:
    ruta = str(ruta)
    if os.name == "nt":
        os.startfile(ruta)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", ruta])
    else:
        subprocess.Popen(["xdg-open", ruta])


def imprimir_archivo(ruta) -> None:
    if os.name == "nt":
        try:
            os.startfile(str(ruta), "print")  # type: ignore[attr-defined]
            return
        except OSError:
            pass
    abrir_archivo(ruta)


class _Seguro(dict):
    def __missing__(self, k):
        return "{" + k + "}"


def rango_periodo(anio: int, periodo: str) -> tuple[date, date]:
    i = PERIODOS.index(periodo)
    if i == 0:
        return date(anio, 1, 1), date(anio, 12, 31)
    if i <= 4:
        m0 = (i - 1) * 3 + 1
        return date(anio, m0, 1), date(anio, m0 + 2, calendar.monthrange(anio, m0 + 2)[1])
    m = i - 4
    return date(anio, m, 1), date(anio, m, calendar.monthrange(anio, m)[1])


def etiqueta_periodo(anio: int, periodo: str) -> str:
    i = PERIODOS.index(periodo)
    if i > 4:
        return f"{anio}-{i - 4:02d} {periodo}"
    return f"{anio} {periodo}"


# ---------------------------------------------------------------- widgets


class Boton(tk.Label):
    """Botón plano con hover (los botones ttk no permiten este acabado en Windows)."""

    def __init__(self, master, texto, comando, tipo="secundario", icono="", **kw):
        estilos = {
            "primario": (C["acento"], "#FFFFFF", C["acento_hover"], C["acento"]),
            "secundario": (C["tarjeta"], C["texto"], "#F3F4F6", C["borde"]),
            "enlace": (C["tarjeta"], C["acento"], C["acento_claro"], C["tarjeta"]),
            "peligro": (C["tarjeta"], C["error"], "#FEE2E2", "#FCA5A5"),
            "lateral": (C["lateral"], "#8B949E", C["lateral_hover"], C["lateral"]),
        }
        self._bg, fg, self._hover, borde = estilos[tipo]
        bg = kw.pop("bg", None)
        if bg:
            self._bg = bg
        super().__init__(master, text=(f"{icono}  {texto}" if icono else texto), bg=self._bg, fg=fg,
                         font=(FUENTE, 9 if tipo in ("enlace", "lateral") else 10, "bold" if tipo == "primario" else "normal"),
                         padx=8 if tipo in ("enlace", "lateral") else 14, pady=4 if tipo in ("enlace", "lateral") else 7,
                         cursor="hand2", highlightthickness=0 if tipo in ("enlace", "lateral") else 1,
                         highlightbackground=borde, highlightcolor=borde, **kw)
        self._cmd = comando
        self._fg = fg
        self._activo = True
        self.bind("<Enter>", lambda e: self._activo and self.config(bg=self._hover))
        self.bind("<Leave>", lambda e: self.config(bg=self._bg))
        self.bind("<Button-1>", lambda e: self._activo and self._cmd and self._cmd())

    def activar(self, si: bool) -> None:
        self._activo = si
        self.config(fg=self._fg if si else C["tenue"], cursor="hand2" if si else "watch")


class Tarjeta(tk.Frame):
    def __init__(self, master, titulo: str = "", **kw):
        super().__init__(master, bg=C["tarjeta"], highlightthickness=1,
                         highlightbackground=C["borde"], **kw)
        if titulo:
            tk.Label(self, text=titulo.upper(), bg=C["tarjeta"], fg=C["acento"],
                     font=(FUENTE, 8, "bold")).pack(anchor="w", padx=18, pady=(14, 4))


def tabla(master, columnas: list[tuple[str, str, int, str]], altura=10, seleccion="browse"):
    """columnas: [(id, título, ancho, alineación 'w'|'e'|'center')]"""
    marco = tk.Frame(master, bg=C["tarjeta"])
    tv = ttk.Treeview(marco, columns=[c[0] for c in columnas], show="headings", height=altura,
                      selectmode=seleccion)
    for cid, tit, ancho, al in columnas:
        tv.heading(cid, text=tit, anchor=al)
        tv.column(cid, width=ancho, minwidth=36, anchor=al, stretch=cid in (columnas[0][0], "email", "aviso", "cliente"))
    sb = ttk.Scrollbar(marco, orient="vertical", command=tv.yview)
    tv.configure(yscrollcommand=sb.set)
    tv.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    tv.tag_configure("par", background=C["fila_par"])
    tv.tag_configure("aviso", foreground=C["aviso"])
    tv.tag_configure("enviado", foreground=C["ok"])
    tv.tag_configure("sinemail", foreground=C["suave"])
    return marco, tv


def campo(master, etiqueta, var, fila, col=0, ancho=34, mostrar=None, ayuda=""):
    tk.Label(master, text=etiqueta, bg=C["tarjeta"], fg=C["suave"], font=(FUENTE, 9)).grid(
        row=fila, column=col, sticky="w", padx=(18, 8), pady=4)
    e = ttk.Entry(master, textvariable=var, width=ancho, show=mostrar or "")
    e.grid(row=fila, column=col + 1, sticky="we", padx=(0, 18), pady=4)
    if ayuda:
        tk.Label(master, text=ayuda, bg=C["tarjeta"], fg=C["tenue"], font=(FUENTE, 8)).grid(
            row=fila, column=col + 2, sticky="w", padx=(0, 18))
    return e


def etiqueta(master, texto, tam=9, color=None, negrita=False, bg=None, **kw):
    return tk.Label(master, text=texto, bg=bg or C["tarjeta"], fg=color or C["suave"],
                    font=(FUENTE, tam, "bold" if negrita else "normal"), **kw)


# ================================================================ aplicación


class App(tk.Tk):
    def __init__(self, minimizado: bool = False):
        super().__init__()
        self.cfg = cargar_config()
        self.almacen = Almacen()
        self._cola: queue.Queue = queue.Queue()
        self._comprobando = False
        self.config_desbloqueada = False
        self.title(f"{NOMBRE_APP} · {self.cfg['empresa']['nombre']}")
        self.geometry("1320x820")
        self.minsize(1100, 660)
        self.configure(bg=C["fondo"])
        try:
            if os.name == "nt":
                self.iconbitmap(default=str(ruta_recursos() / "logo.ico"))
            else:
                self._icono = tk.PhotoImage(file=str(ruta_recursos() / "icono64.png"))
                self.iconphoto(True, self._icono)
        except Exception:
            pass
        self._estilos()
        self._construir()
        self.after(100, self._procesar_cola)
        self.mostrar("listados")
        if minimizado:
            self.iconify()
        self.after(1500, self._ciclo_correo)
        if self.cfg["actualizaciones"].get("comprobar_al_iniciar"):
            self.after(3000, lambda: self.buscar_actualizacion(silencioso=True))

    # ------------------------------------------------------------ estilos ttk
    def _estilos(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure(".", font=(FUENTE, 10), background=C["tarjeta"], foreground=C["texto"])
        s.configure("Treeview", rowheight=30, background=C["tarjeta"], fieldbackground=C["tarjeta"],
                    borderwidth=0, font=(FUENTE, 10))
        s.configure("Treeview.Heading", font=(FUENTE, 9, "bold"), background="#F9FAFB",
                    foreground=C["suave"], relief="flat", borderwidth=0, padding=(8, 7))
        s.map("Treeview.Heading", background=[("active", "#F3F4F6")])
        s.map("Treeview", background=[("selected", C["acento_claro"])],
              foreground=[("selected", C["texto"])])
        s.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        s.configure("TEntry", padding=6, fieldbackground="#FFFFFF", bordercolor=C["borde"],
                    lightcolor=C["borde"], darkcolor=C["borde"])
        s.map("TEntry", bordercolor=[("focus", C["acento"])], lightcolor=[("focus", C["acento"])])
        s.configure("TCombobox", padding=5, arrowsize=14, fieldbackground="#FFFFFF",
                    bordercolor=C["borde"], lightcolor=C["borde"], darkcolor=C["borde"])
        s.map("TCombobox", fieldbackground=[("readonly", "#FFFFFF")], selectbackground=[("readonly", "#FFFFFF")],
              selectforeground=[("readonly", C["texto"])])
        s.configure("TCheckbutton", background=C["tarjeta"], font=(FUENTE, 10))
        s.configure("Vertical.TScrollbar", background="#E5E7EB", troughcolor=C["tarjeta"],
                    bordercolor=C["tarjeta"], arrowcolor=C["suave"], relief="flat")
        s.configure("Horizontal.TProgressbar", background=C["acento"], troughcolor="#E5E7EB",
                    bordercolor="#E5E7EB", lightcolor=C["acento"], darkcolor=C["acento"])

    # ------------------------------------------------------------- estructura
    def _construir(self):
        lateral = tk.Frame(self, bg=C["lateral"], width=220)
        lateral.pack(side="left", fill="y")
        lateral.pack_propagate(False)
        try:
            self._logo = tk.PhotoImage(file=str(ruta_recursos() / "logo_sidebar.png"))
            tk.Label(lateral, image=self._logo, bg=C["lateral"]).pack(pady=(26, 30))
        except Exception:
            tk.Label(lateral, text="FERRETERÍA LH", bg=C["lateral"], fg="white",
                     font=(FUENTE, 14, "bold")).pack(pady=(26, 30))

        self._nav = {}
        for clave, texto in [("listados", "Listados de facturas"), ("m347", "Modelo 347"),
                             ("clientes", "Clientes"), ("config", "Configuración")]:
            b = tk.Label(lateral, text=f"   {texto}", anchor="w", bg=C["lateral"],
                         fg=C["lateral_texto"], font=(FUENTE, 11), pady=11, cursor="hand2")
            b.pack(fill="x", padx=12, pady=2)
            b.bind("<Button-1>", lambda e, k=clave: self.mostrar(k))
            b.bind("<Enter>", lambda e, w=b, k=clave: self._pagina != k and w.config(bg=C["lateral_hover"]))
            b.bind("<Leave>", lambda e, w=b, k=clave: self._pagina != k and w.config(bg=C["lateral"]))
            self._nav[clave] = b

        pie = tk.Frame(lateral, bg=C["lateral"])
        pie.pack(side="bottom", fill="x", padx=14, pady=16)
        self.lbl_estado = tk.Label(pie, text="", bg=C["lateral"], fg="#8B949E", font=(FUENTE, 8),
                                   justify="left", wraplength=190, anchor="w")
        self.lbl_estado.pack(fill="x", padx=4)
        Boton(pie, "Comprobar correo ahora", lambda: self.comprobar_correo(), "lateral", icono="⟳").pack(anchor="w", pady=(4, 0))
        self.lbl_version = tk.Label(pie, text=f"Versión {VERSION}", bg=C["lateral"], fg="#6E7681",
                                    font=(FUENTE, 8), anchor="w", cursor="hand2")
        self.lbl_version.pack(fill="x", padx=4, pady=(8, 0))
        self.lbl_version.bind("<Button-1>", lambda e: self.buscar_actualizacion())

        self.contenido = tk.Frame(self, bg=C["fondo"])
        self.contenido.pack(side="left", fill="both", expand=True)
        self.paginas = {
            "listados": PaginaListados(self.contenido, self),
            "m347": Pagina347(self.contenido, self),
            "clientes": PaginaClientes(self.contenido, self),
            "config": PaginaConfig(self.contenido, self),
        }
        self._pagina = None
        self._aviso = None
        self._estado_recepcion()

    def mostrar(self, clave: str):
        if clave == "config" and not self.config_desbloqueada:
            if not DialogoPin(self).ok:
                return
            self.config_desbloqueada = True
        for k, p in self.paginas.items():
            p.pack_forget()
            self._nav[k].config(bg=C["lateral"], fg=C["lateral_texto"], font=(FUENTE, 11))
        self._nav[clave].config(bg=C["acento"], fg="white", font=(FUENTE, 11, "bold"))
        self._pagina = clave
        self.paginas[clave].pack(fill="both", expand=True)
        self.paginas[clave].al_mostrar()

    def datos_cambiados(self):
        """Tras recibir un diario o importar clientes, refresca la pantalla visible."""
        self._estado_recepcion()
        if self._pagina:
            self.paginas[self._pagina].al_mostrar()

    def _estado_recepcion(self, extra: str = ""):
        ultima = self.almacen.ultima_recepcion()
        txt = (f"Último diario recibido:\n{datetime.fromisoformat(ultima):%d/%m/%Y %H:%M}" if ultima
               else "Todavía no ha llegado ningún diario.")
        if not self.cfg["correo"].get("imap_servidor") or not self.password():
            txt += "\nCorreo sin configurar."
        self.lbl_estado.config(text=txt + (f"\n{extra}" if extra else ""))

    # ----------------------------------------------------- tareas de fondo
    def en_fondo(self, funcion, al_terminar=None, al_fallar=None):
        def trabajo():
            try:
                res = funcion()
                self._cola.put((al_terminar, res, None))
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                self._cola.put((al_fallar, None, e))
        threading.Thread(target=trabajo, daemon=True).start()

    def _procesar_cola(self):
        try:
            while True:
                cb, res, err = self._cola.get_nowait()
                try:
                    if err is not None:
                        (cb or self.error)(err)
                    elif cb:
                        cb(res)
                except Exception as e:  # noqa: BLE001
                    traceback.print_exc()
                    self.error(e)
        except queue.Empty:
            pass
        self.after(120, self._procesar_cola)

    def error(self, e):
        messagebox.showerror(NOMBRE_APP, str(e), parent=self)

    def notificar(self, texto: str, tipo: str = "ok", segundos: int = 6):
        """Aviso flotante en la esquina inferior derecha."""
        if self._aviso is not None:
            self._aviso.destroy()
        colores = {"ok": ("#ECFDF5", C["ok"]), "aviso": (C["aviso_fondo"], C["aviso"]),
                   "error": ("#FEF2F2", C["error"]), "info": ("#EFF6FF", "#1D4ED8")}
        fondo, borde = colores.get(tipo, colores["info"])
        f = tk.Frame(self, bg=fondo, highlightthickness=1, highlightbackground=borde)
        tk.Label(f, text=texto, bg=fondo, fg=C["texto"], font=(FUENTE, 10), justify="left",
                 wraplength=380, padx=16, pady=12).pack()
        f.place(relx=1.0, rely=1.0, x=-24, y=-24, anchor="se")
        f.bind("<Button-1>", lambda e: f.destroy())
        self._aviso = f
        self.after(segundos * 1000, lambda: f.winfo_exists() and f.destroy())

    # ------------------------------------------------------------- correo
    def password(self) -> str:
        return leer_password(self.cfg["correo"]["usuario"])

    def password_envio(self) -> str:
        from .correo import usuario_envio
        return leer_password(usuario_envio(self.cfg))

    def _ciclo_correo(self):
        c = self.cfg["correo"]
        if c.get("comprobar_auto") and c.get("imap_servidor") and self.password():
            self.comprobar_correo(silencioso=True)
        minutos = max(2, int(c.get("intervalo_min") or 10))
        self.after(minutos * 60 * 1000, self._ciclo_correo)

    def comprobar_correo(self, silencioso: bool = False):
        if self._comprobando:
            return
        if not self.cfg["correo"].get("imap_servidor") or not self.password():
            if not silencioso:
                messagebox.showinfo(NOMBRE_APP, "Falta configurar el correo (Configuración > Correo).", parent=self)
            return
        self._comprobando = True
        self._estado_recepcion("Comprobando correo…")
        cfg, pw, almacen = self.cfg, self.password(), self.almacen

        def trabajo():
            from .correo import comprobar_correo
            estado = almacen.estado_correo()
            nuevos = comprobar_correo(cfg, pw, almacen.dir_entrada, estado)
            almacen.guardar_estado_correo(estado)
            procesados, fallidos = [], []
            for n in nuevos:
                try:
                    ident, diario = almacen.procesar(n["ruta"], cfg, "correo", n["asunto"], n["remitente"])
                    procesados.append((ident, diario))
                except Exception as e:  # noqa: BLE001
                    fallidos.append(f"{n['nombre']}: {e}")
            return procesados, fallidos

        def fin(res):
            self._comprobando = False
            procesados, fallidos = res
            self.datos_cambiados()
            if procesados:
                facts = sum(len(d.facturas) for _, d in procesados)
                self.notificar(f"✉ Diario de facturación recibido: {facts} facturas actualizadas.")
                if self.state() == "iconic":
                    self.title(f"● Diario recibido · {NOMBRE_APP}")
                    self.bell()
            elif not silencioso:
                self.notificar("No hay diarios nuevos en el correo.", "info")
            if fallidos:
                self.notificar("No se pudo leer:\n" + "\n".join(fallidos), "aviso", 10)

        def fallo(e):
            self._comprobando = False
            self._estado_recepcion(f"Error de correo ({datetime.now():%H:%M})")
            if not silencioso:
                self.error(e)

        self.en_fondo(trabajo, fin, fallo)

    # ------------------------------------------------------- actualizaciones
    def buscar_actualizacion(self, silencioso: bool = False):
        a = self.cfg["actualizaciones"]

        def fin(info):
            if info is None:
                if not silencioso:
                    messagebox.showinfo(NOMBRE_APP, f"Tienes la última versión ({VERSION}).", parent=self)
                return
            self.lbl_version.config(text=f"Versión {VERSION} · ⬆ {info.version} disponible", fg="#F59E0B")
            DialogoActualizacion(self, info)

        def fallo(e):
            if not silencioso:
                self.error(e)

        self.en_fondo(lambda: actualizador.buscar_actualizacion(a.get("repo", ""), a.get("token", "")),
                      fin, fallo)

    # ------------------------------------------------------------- envíos
    def enviar_varios(self, pendientes, preparar, grupo, al_terminar):
        """pendientes: [Cliente]; preparar(cliente) -> (asunto, cuerpo, [adjuntos])."""
        cfg, pw, almacen = self.cfg, self.password_envio(), self.almacen
        if not pw:
            messagebox.showwarning(NOMBRE_APP, "Falta la contraseña de la cuenta de envío en Configuración.", parent=self)
            return

        def trabajo():
            from .correo import enviar_email, usuario_envio
            ok, mal = 0, []
            for c in pendientes:
                try:
                    asunto, cuerpo, adj = preparar(c)
                    para = [x.strip() for x in c.email.replace(";", ",").split(",") if x.strip()]
                    bcc = [usuario_envio(cfg)] if cfg["correo"].get("copia_a_mi") else []
                    enviar_email(cfg, pw, para, asunto, cuerpo, adj, bcc)
                    almacen.registrar_envio(grupo, c.clave, para)
                    ok += 1
                except Exception as e:  # noqa: BLE001
                    mal.append(f"{c.nombre}: {e}")
            return ok, mal

        def fin(res):
            ok, mal = res
            al_terminar()
            if mal:
                messagebox.showwarning(NOMBRE_APP, f"Enviados: {ok}\nCon error:\n" + "\n".join(mal[:20]), parent=self)
            else:
                self.notificar(f"✔ Enviado a {ok} cliente(s).")

        self.notificar(f"Enviando {len(pendientes)} correo(s)…", "info", 4)
        self.en_fondo(trabajo, fin)


# ================================================================ páginas


class Pagina(tk.Frame):
    def __init__(self, master, app: App, titulo: str, subtitulo: str = ""):
        super().__init__(master, bg=C["fondo"])
        self.app = app
        cab = tk.Frame(self, bg=C["fondo"])
        cab.pack(fill="x", padx=28, pady=(24, 14))
        izq = tk.Frame(cab, bg=C["fondo"])
        izq.pack(side="left")
        tk.Label(izq, text=titulo, bg=C["fondo"], fg=C["texto"], font=(FUENTE, 20, "bold")).pack(anchor="w")
        self.lbl_sub = tk.Label(izq, text=subtitulo, bg=C["fondo"], fg=C["suave"], font=(FUENTE, 10))
        self.lbl_sub.pack(anchor="w")
        self.acciones = tk.Frame(cab, bg=C["fondo"])
        self.acciones.pack(side="right", anchor="s")

    def al_mostrar(self):
        pass


class PaginaPorCliente(Pagina):
    """Lista de clientes a la izquierda y ficha con acciones a la derecha."""

    COLS_LISTA: list = []
    COLS_FACT: list = []

    def __init__(self, master, app, titulo, subtitulo):
        self._filas: dict = {}
        super().__init__(master, app, titulo, subtitulo)
        cuerpo = tk.Frame(self, bg=C["fondo"])
        cuerpo.pack(fill="both", expand=True, padx=28, pady=(0, 24))

        # --- lista
        izq = Tarjeta(cuerpo, width=400)
        izq.pack(side="left", fill="y")
        izq.pack_propagate(False)
        bus = tk.Frame(izq, bg=C["tarjeta"])
        bus.pack(fill="x", padx=16, pady=(16, 10))
        self.v_busca = tk.StringVar()
        self.v_busca.trace_add("write", lambda *a: self.pintar_lista())
        e = ttk.Entry(bus, textvariable=self.v_busca)
        e.pack(fill="x")
        self._marcador(e, "Buscar cliente o NIF…")
        pie = tk.Frame(izq, bg=C["tarjeta"])
        pie.pack(side="bottom", fill="x", padx=16, pady=12)
        marco, self.tv = tabla(izq, self.COLS_LISTA, altura=8)
        marco.pack(fill="both", expand=True, padx=16)
        self.tv.bind("<<TreeviewSelect>>", lambda ev: self.pintar_ficha())
        self.tv.bind("<Double-1>", lambda ev: self.ver())
        self.lbl_resumen = etiqueta(pie, "", 8, C["tenue"], anchor="w", justify="left", wraplength=360)
        self.lbl_resumen.pack(fill="x", pady=(0, 8))
        self.pie_botones = tk.Frame(pie, bg=C["tarjeta"])
        self.pie_botones.pack(fill="x")
        Boton(self.pie_botones, "Enviar a todos", self.enviar_todos, icono="✉").pack(side="left")

        # --- ficha
        self.ficha = Tarjeta(cuerpo)
        self.ficha.pack(side="left", fill="both", expand=True, padx=(16, 0))
        cab = tk.Frame(self.ficha, bg=C["tarjeta"])
        cab.pack(fill="x", padx=24, pady=(20, 0))
        self.lbl_nombre = etiqueta(cab, "", 16, C["texto"], True, anchor="w")
        self.lbl_nombre.pack(fill="x")
        datos = tk.Frame(cab, bg=C["tarjeta"])
        datos.pack(fill="x", pady=(2, 0))
        self.lbl_datos = etiqueta(datos, "", 9, anchor="w")
        self.lbl_datos.pack(side="left")
        self.b_email = Boton(datos, "Cambiar email", self.cambiar_email, "enlace")
        self.b_email.pack(side="left", padx=6)

        self.kpis = tk.Frame(self.ficha, bg=C["tarjeta"])
        self.kpis.pack(fill="x", padx=24, pady=(16, 0))

        acc = tk.Frame(self.ficha, bg=C["tarjeta"])
        acc.pack(fill="x", padx=24, pady=(16, 0))
        Boton(acc, "Ver", self.ver, "primario").pack(side="left")
        Boton(acc, "Imprimir", self.imprimir).pack(side="left", padx=8)
        Boton(acc, "Enviar por email", self.enviar, icono="✉").pack(side="left")
        self.acc_extra = tk.Frame(acc, bg=C["tarjeta"])
        self.acc_extra.pack(side="right")
        self.lbl_envio = etiqueta(self.ficha, "", 9, C["ok"], anchor="w")
        self.lbl_envio.pack(fill="x", padx=24, pady=(10, 0))

        marco, self.tv_f = tabla(self.ficha, self.COLS_FACT, altura=6)
        marco.pack(fill="both", expand=True, padx=24, pady=(10, 22))
        self.tv_f.bind("<Button-3>", self._menu_factura)
        self.tv_f.bind("<Double-1>", self._menu_factura)

    @staticmethod
    def _marcador(entry: ttk.Entry, texto: str):
        """Texto de ayuda dentro del cuadro de búsqueda."""
        var = entry.cget("textvariable")

        def poner(_=None):
            if not entry.get():
                entry.configure(foreground=C["tenue"])
                entry.insert(0, texto)
                entry._marcador = True

        def quitar(_=None):
            if getattr(entry, "_marcador", False):
                entry._marcador = False
                entry.delete(0, "end")
                entry.configure(foreground=C["texto"])
        entry.bind("<FocusIn>", quitar)
        entry.bind("<FocusOut>", poner)
        entry._marcador = False
        poner()
        del var

    def busqueda(self) -> str:
        e = self.v_busca.get()
        return "" if e.startswith("Buscar cliente") else e.strip().lower()

    # --- a implementar por cada página
    def datos(self) -> list[tuple[str, Cliente, list]]:
        return []

    def fila_lista(self, clave, cliente, facturas, enviado) -> tuple:
        return ()

    def pintar_kpis(self, clave, cliente, facturas):
        pass

    def fila_factura(self, f) -> tuple:
        return ()

    def grupo_envio(self) -> str:
        return ""

    def generar_pdf(self, clave) -> Path:
        raise NotImplementedError

    def textos(self, cliente, facturas) -> tuple[str, str]:
        return "", ""

    def adjuntos_extra(self, clave, excel: bool, csv: bool) -> list:
        return []

    def permite_extra(self) -> bool:
        return False

    # --- común
    def al_mostrar(self):
        self.recargar()

    def recargar(self):
        self._filas = {clave: (c, fs) for clave, c, fs in self.datos()}
        self.pintar_lista()

    def pintar_lista(self):
        if not hasattr(self, "tv_f"):
            return  # aún construyendo la página
        sel = self.tv.selection()
        self.tv.delete(*self.tv.get_children())
        q = self.busqueda()
        envios = self.app.almacen.envios(self.grupo_envio())
        filas = sorted(self._filas.items(), key=lambda x: x[1][0].nombre.lower())
        for i, (clave, (c, fs)) in enumerate(filas):
            if q and q not in f"{c.nombre} {c.nif} {c.codigo}".lower():
                continue
            env = envios.get(clave)
            tags = ("par",) if i % 2 else ()
            tags += ("enviado",) if env else (("sinemail",) if not c.email else ())
            self.tv.insert("", "end", iid=clave, values=self.fila_lista(clave, c, fs, env), tags=tags)
        hijos = self.tv.get_children()
        objetivo = [s for s in sel if s in hijos] or list(hijos[:1])
        if objetivo:
            self.tv.selection_set(objetivo)
            self.tv.see(objetivo[0])
        self.pintar_ficha()

    def clave(self):
        sel = self.tv.selection()
        return sel[0] if sel else None

    def pintar_ficha(self):
        for w in self.kpis.winfo_children():
            w.destroy()
        self.tv_f.delete(*self.tv_f.get_children())
        clave = self.clave()
        if not clave or clave not in self._filas:
            self.lbl_nombre.config(text="Sin datos" if not self._filas else "Selecciona un cliente")
            self.lbl_datos.config(text=self.mensaje_vacio() if not self._filas else "")
            self.lbl_envio.config(text="")
            return
        c, fs = self._filas[clave]
        c = self.app.almacen.clientes().get(clave, c)
        self._filas[clave] = (c, fs)
        self.lbl_nombre.config(text=c.nombre)
        partes = [x for x in [f"NIF {c.nif}" if c.nif else "", c.email or "sin email",
                              f"Cód. {c.codigo}" if c.codigo else ""] if x]
        self.lbl_datos.config(text="   ·   ".join(partes), fg=C["suave"] if c.email else C["aviso"])
        self.pintar_kpis(clave, c, fs)
        env = self.app.almacen.envios(self.grupo_envio()).get(clave)
        self.lbl_envio.config(text=(f"✔ Enviado el {datetime.fromisoformat(env[-1]['fecha']):%d/%m/%Y a las %H:%M} "
                                    f"a {', '.join(env[-1]['para'])}") if env else "")
        for i, f in enumerate(fs):
            tags = ("par",) if i % 2 else ()
            if getattr(f, "aviso", ""):
                tags += ("aviso",)
            self.tv_f.insert("", "end", iid=str(i), values=self.fila_factura(f), tags=tags)

    def mensaje_vacio(self) -> str:
        return "Todavía no ha llegado ningún diario de facturación."

    def kpi(self, valor, texto, destacado=False):
        bg = C["acento_claro"] if destacado else "#F9FAFB"
        f = tk.Frame(self.kpis, bg=bg, padx=14, pady=9)
        f.pack(side="left", padx=(0, 10))
        tk.Label(f, text=valor, bg=bg, fg=C["texto"], font=(FUENTE, 13, "bold")).pack(anchor="w")
        tk.Label(f, text=texto.upper(), bg=bg, fg=C["suave"], font=(FUENTE, 7)).pack(anchor="w")

    def _menu_factura(self, evento):
        pass

    def _necesita(self):
        clave = self.clave()
        if not clave:
            messagebox.showinfo(NOMBRE_APP, "Selecciona un cliente de la lista.", parent=self)
        return clave

    def ver(self):
        clave = self._necesita()
        if clave:
            VisorPDF(self.app, self.generar_pdf(clave), lambda: self.imprimir(clave), lambda: self.enviar(clave))

    def imprimir(self, clave=None):
        clave = clave or self._necesita()
        if clave:
            imprimir_archivo(self.generar_pdf(clave))
            self.app.notificar("Enviado a la impresora predeterminada.", "info", 4)

    def enviar(self, clave=None):
        clave = clave or self._necesita()
        if not clave:
            return
        c, fs = self._filas[clave]
        asunto, cuerpo = self.textos(c, fs)
        DialogoEnvio(self.app, c, asunto, cuerpo,
                     lambda pdf, xl, cs: ([self.generar_pdf(clave)] if pdf else []) + self.adjuntos_extra(clave, xl, cs),
                     self.grupo_envio(), self.permite_extra(), self.pintar_lista)

    def cambiar_email(self):
        clave = self.clave()
        if not clave:
            return
        c = self._filas[clave][0]
        DialogoEmail(self.app, c, self.pintar_lista)

    def enviar_todos(self):
        if not self._filas:
            return
        envios = self.app.almacen.envios(self.grupo_envio())
        con = [c for k, (c, _) in self._filas.items() if c.email and k not in envios]
        ya = sum(1 for k in self._filas if k in envios)
        sin = sum(1 for k, (c, _) in self._filas.items() if not c.email and k not in envios)
        if not con:
            messagebox.showinfo(NOMBRE_APP, "No queda ningún cliente con email pendiente de envío.", parent=self)
            return
        texto = f"Se enviará a {len(con)} cliente(s) con email."
        if ya:
            texto += f"\n{ya} ya enviado(s) antes: no se repiten."
        if sin:
            texto += f"\n{sin} sin email: se omiten."
        if not messagebox.askyesno(NOMBRE_APP, texto + "\n\n¿Enviar ahora?", parent=self):
            return
        filas = dict(self._filas)

        def preparar(c):
            fs = filas[c.clave][1]
            asunto, cuerpo = self.textos(c, fs)
            return asunto, cuerpo, [self.generar_pdf(c.clave)] + self.adjuntos_extra(
                c.clave, self.app.cfg["envio"].get("adjuntar_excel"), self.app.cfg["envio"].get("adjuntar_csv"))

        self.app.enviar_varios(con, preparar, self.grupo_envio(), self.pintar_lista)


# --------------------------------------------------------------- listados


class PaginaListados(PaginaPorCliente):
    COLS_LISTA = [("cliente", "Cliente", 190, "w"), ("n", "Fact.", 44, "e"), ("total", "Total", 92, "e"),
                  ("est", "", 30, "center")]
    COLS_FACT = [("tipo", "Tipo", 92, "w"), ("num", "Nº factura", 92, "w"), ("fecha", "Fecha", 86, "w"),
                 ("base", "Base", 84, "e"), ("iva", "IVA", 76, "e"),
                 ("total", "Total", 88, "e"), ("aviso", "Observaciones", 90, "w")]

    def __init__(self, master, app):
        super().__init__(master, app, "Listados de facturas", "")
        etiqueta(self.acciones, "Año", 9, bg=C["fondo"]).pack(side="left", padx=(0, 6))
        self.v_anio = tk.StringVar()
        self.cb_anio = ttk.Combobox(self.acciones, textvariable=self.v_anio, width=6, state="readonly")
        self.cb_anio.pack(side="left")
        etiqueta(self.acciones, "Periodo", 9, bg=C["fondo"]).pack(side="left", padx=(16, 6))
        self.v_periodo = tk.StringVar()
        cb = ttk.Combobox(self.acciones, textvariable=self.v_periodo, values=PERIODOS, width=15, state="readonly")
        cb.pack(side="left")
        for w in (self.cb_anio, cb):
            w.bind("<<ComboboxSelected>>", lambda e: self.recargar())
        Boton(self.acc_extra, "Excel", lambda: self.exportar("xlsx")).pack(side="left", padx=(0, 6))
        Boton(self.acc_extra, "CSV", lambda: self.exportar("csv")).pack(side="left")
        Boton(self.pie_botones, "Excel de todo el periodo", self.exportar_todo).pack(side="right")
        self.vista = None
        self._inicial = False

    def _periodo_inicial(self, reg):
        fechas = [f.fecha for f in reg.facturas if f.fecha]
        anios = sorted({d.year for d in fechas}, reverse=True) or [date.today().year]
        self.cb_anio.config(values=[str(a) for a in anios])
        if self._inicial:
            if self.v_anio.get() not in self.cb_anio.cget("values"):
                self.v_anio.set(str(anios[0]))
            return
        self._inicial = True
        ultima = max(fechas) if fechas else date.today()
        hoy = date.today()
        a, m = ultima.year, ultima.month
        if (a, m) == (hoy.year, hoy.month) and hoy.day <= 10:
            a, m = (a, m - 1) if m > 1 else (a - 1, 12)
        self.v_anio.set(str(a))
        self.v_periodo.set(PERIODOS[4 + m])

    def datos(self):
        reg = self.app.almacen.registro()
        self._periodo_inicial(reg)
        anio, periodo = int(self.v_anio.get()), self.v_periodo.get()
        desde, hasta = rango_periodo(anio, periodo)
        self.vista = reg.filtrar(desde, hasta)
        self.vista.desde, self.vista.hasta = desde, hasta
        maestro = self.app.almacen.clientes()
        ultima = self.app.almacen.ultima_recepcion()
        sub = f"{texto_periodo(desde, hasta).capitalize()} · {len(self.vista.facturas)} facturas de {len(self.vista.clientes)} clientes"
        if ultima:
            sub += f" · datos recibidos el {datetime.fromisoformat(ultima):%d/%m/%Y %H:%M}"
        self.lbl_sub.config(text=sub)
        out = []
        for clave, c in self.vista.clientes.items():
            out.append((clave, maestro.get(clave, c), self.vista.facturas_de(clave)))
        con_email = sum(1 for _, c, _ in out if c.email)
        self.lbl_resumen.config(text=f"{len(out)} clientes · {con_email} con email · "
                                     f"total {eur(sum(f.importe_total for f in self.vista.facturas))}")
        return out

    def etiqueta(self):
        return etiqueta_periodo(int(self.v_anio.get()), self.v_periodo.get())

    def grupo_envio(self):
        return f"listado:{self.vista.desde}:{self.vista.hasta}" if self.vista else ""

    def fila_lista(self, clave, c, fs, env):
        return (c.nombre, len(fs), eur(sum(f.importe_total for f in fs)), "✔" if env else ("✉" if c.email else "—"))

    def pintar_kpis(self, clave, c, fs):
        self.kpi(str(len(fs)), "Facturas")
        self.kpi(eur(sum(f.base for f in fs)), "Base imponible")
        self.kpi(eur(sum(f.cuota_iva + f.cuota_re for f in fs)), "IVA + recargo")
        self.kpi(eur(sum(f.importe_total for f in fs)), "Total", True)

    def fila_factura(self, f):
        obs = f.aviso or ("Varios tipos de IVA" if f.lineas and f.lineas[0].iva_pct not in IVA_TIPOS else "")
        if not obs and f.cuota_re:
            obs = f"Incluye recargo {eur(f.cuota_re)}"
        return (f.tipo, f.numero, fecha_es(f.fecha), eur(f.base), eur(f.cuota_iva + f.cuota_re),
                eur(f.importe_total), obs)

    def generar_pdf(self, clave):
        return self.app.almacen.generar_pdf(self.vista, clave, self.app.cfg, self.etiqueta())

    def adjuntos_extra(self, clave, excel, csv):
        out = []
        if excel:
            out.append(self.app.almacen.generar_excel(self.vista, clave, self.app.cfg, self.etiqueta()))
        if csv:
            out.append(self.app.almacen.generar_csv(self.vista, clave, self.app.cfg, self.etiqueta()))
        return out

    def permite_extra(self):
        return True

    def textos(self, c, fs):
        cfg = self.app.cfg
        datos = _Seguro(cliente=c.nombre, periodo=texto_periodo(self.vista.desde, self.vista.hasta),
                        num_facturas=len(fs), total=eur(sum(f.importe_total for f in fs)),
                        empresa=cfg["empresa"]["nombre"], empresa_telefono=cfg["empresa"].get("telefono", ""))
        return cfg["envio"]["asunto"].format_map(datos), cfg["envio"]["cuerpo"].format_map(datos).rstrip()

    def exportar(self, formato):
        clave = self._necesita()
        if clave:
            f = (self.app.almacen.generar_excel if formato == "xlsx" else self.app.almacen.generar_csv)
            abrir_archivo(f(self.vista, clave, self.app.cfg, self.etiqueta()))

    def exportar_todo(self):
        if self.vista and self.vista.facturas:
            abrir_archivo(self.app.almacen.generar_excel(self.vista, None, self.app.cfg, self.etiqueta()))

    def _menu_factura(self, evento):
        fila = self.tv_f.identify_row(evento.y)
        clave = self.clave()
        if not fila or not clave:
            return
        self.tv_f.selection_set(fila)
        f = self._filas[clave][1][int(fila)]
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label=f"Factura {f.numero} — cambiar tipo:", state="disabled")
        for t in TIPOS_FACTURA:
            menu.add_command(label=f"   {t}", command=lambda t=t: (self.app.almacen.cambiar_tipo(f, t), self.pintar_ficha()))
        menu.tk_popup(evento.x_root, evento.y_root)


# -------------------------------------------------------------- modelo 347


class Pagina347(PaginaPorCliente):
    COLS_LISTA = [("cliente", "Cliente", 160, "w"), ("nif", "NIF", 86, "w"), ("total", "Importe", 90, "e"),
                  ("est", "", 30, "center")]
    COLS_FACT = [("num", "Factura", 110, "w"), ("fecha", "Fecha factura", 110, "w"),
                 ("cont", "Fecha contabilización", 140, "w"), ("tipo", "Tipo", 100, "w"),
                 ("total", "Importe", 100, "e"), ("aviso", "", 20, "w")]

    def __init__(self, master, app):
        super().__init__(master, app, "Modelo 347",
                         f"Clientes con operaciones superiores a {eur(UMBRAL)} en el año (IVA incluido).")
        etiqueta(self.acciones, "Ejercicio", 9, bg=C["fondo"]).pack(side="left", padx=(0, 6))
        self.v_anio = tk.StringVar()
        self.cb_anio = ttk.Combobox(self.acciones, textvariable=self.v_anio, width=6, state="readonly")
        self.cb_anio.pack(side="left")
        self.cb_anio.bind("<<ComboboxSelected>>", lambda e: self.recargar())
        Boton(self.pie_botones, "Resumen en Excel", self.exportar_resumen).pack(side="right")
        self._lineas347 = {}

    def datos(self):
        reg = self.app.almacen.registro()
        anios = sorted({f.fecha.year for f in reg.facturas if f.fecha}, reverse=True) or [date.today().year]
        self.cb_anio.config(values=[str(a) for a in anios])
        if self.v_anio.get() not in self.cb_anio.cget("values"):
            previo = date.today().year - 1
            self.v_anio.set(str(previo if previo in anios else anios[0]))
        anio = int(self.v_anio.get())
        maestro = {**reg.clientes, **self.app.almacen.clientes()}
        umbral = float(self.app.cfg.get("modelo347", {}).get("umbral", UMBRAL))
        incluidos, sin_nif = calcular(reg.facturas, maestro, anio, umbral)
        self._lineas347 = {fl.clave: fl for fl in incluidos}
        con_email = sum(1 for fl in incluidos if fl.cliente.email)
        txt = (f"{len(incluidos)} clientes a declarar · {con_email} con email · "
               f"total {eur(sum(fl.total for fl in incluidos))}")
        if sin_nif:
            txt += (f"\n{len(sin_nif)} cliente(s) superan el importe pero no tienen NIF y no se incluyen "
                    f"(p. ej. {sin_nif[0].cliente.nombre}).")
        self.lbl_resumen.config(text=txt)
        return [(fl.clave, fl.cliente, fl.facturas) for fl in incluidos]

    def mensaje_vacio(self):
        return "Ningún cliente supera el importe en este ejercicio, o aún no hay datos del año."

    def grupo_envio(self):
        return f"347:{self.v_anio.get()}"

    def fila_lista(self, clave, c, fs, env):
        return (c.nombre, c.nif, eur(sum(f.importe_total for f in fs)), "✔" if env else ("✉" if c.email else "—"))

    def pintar_kpis(self, clave, c, fs):
        fl = self._lineas347[clave]
        for i, t in enumerate(fl.trimestres):
            self.kpi(eur(t), f"{i + 1}º trimestre")
        self.kpi(eur(fl.total), f"Total {self.v_anio.get()}", True)

    def fila_factura(self, f):
        return (f.numero, fecha_es(f.fecha), fecha_es(f.fecha), f.tipo, eur(f.importe_total), "")

    def generar_pdf(self, clave):
        fl = self._lineas347[clave]
        fl.cliente = self.app.almacen.clientes().get(clave, fl.cliente)
        return self.app.almacen.generar_347(fl, int(self.v_anio.get()), self.app.cfg)

    def textos(self, c, fs):
        cfg = self.app.cfg
        datos = _Seguro(cliente=c.nombre, ejercicio=self.v_anio.get(), total=eur(sum(f.importe_total for f in fs)),
                        num_facturas=len(fs), empresa=cfg["empresa"]["nombre"],
                        empresa_telefono=cfg["empresa"].get("telefono", ""))
        return cfg["envio347"]["asunto"].format_map(datos), cfg["envio347"]["cuerpo"].format_map(datos).rstrip()

    def exportar_resumen(self):
        if self._lineas347:
            filas = sorted(self._lineas347.values(), key=lambda x: x.cliente.nombre.lower())
            abrir_archivo(self.app.almacen.exportar_347(filas, int(self.v_anio.get()), self.app.cfg))


# ------------------------------------------------------------------ visor


class VisorPDF(tk.Toplevel):
    def __init__(self, app: App, ruta: Path, al_imprimir, al_enviar):
        super().__init__(app)
        self.app, self.ruta = app, Path(ruta)
        self.title(f"{self.ruta.name} · {NOMBRE_APP}")
        self.geometry("900x900")
        self.configure(bg="#525659")
        barra = tk.Frame(self, bg=C["tarjeta"])
        barra.pack(fill="x")
        tk.Label(barra, text=self.ruta.stem, bg=C["tarjeta"], fg=C["texto"],
                 font=(FUENTE, 11, "bold")).pack(side="left", padx=16, pady=10)
        Boton(barra, "Enviar por email", al_enviar, "primario", icono="✉").pack(side="right", padx=(6, 12), pady=8)
        Boton(barra, "Imprimir", al_imprimir).pack(side="right", padx=6)
        Boton(barra, "Abrir en lector PDF", lambda: abrir_archivo(self.ruta)).pack(side="right", padx=6)
        Boton(barra, " − ", lambda: self._zoom(-0.15)).pack(side="right", padx=(6, 0))
        Boton(barra, " + ", lambda: self._zoom(0.15)).pack(side="right")

        marco = tk.Frame(self, bg="#525659")
        marco.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(marco, bg="#525659", highlightthickness=0)
        sb = ttk.Scrollbar(marco, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-e.delta / 120), "units"))
        self.canvas.bind("<Button-4>", lambda e: self.canvas.yview_scroll(-3, "units"))
        self.canvas.bind("<Button-5>", lambda e: self.canvas.yview_scroll(3, "units"))
        self.canvas.bind("<Configure>", lambda e: self._pintar())
        self.escala = 1.0
        self._imgs = []
        self._ancho_previo = 0
        self.focus_set()

    def _zoom(self, d):
        self.escala = max(0.5, min(2.5, self.escala + d))
        self._ancho_previo = 0
        self._pintar()

    def _pintar(self):
        ancho = self.canvas.winfo_width()
        if ancho < 50 or abs(ancho - self._ancho_previo) < 20:
            return
        self._ancho_previo = ancho
        try:
            import pypdfium2 as pdfium
            from PIL import ImageTk
        except ImportError:
            self.destroy()
            abrir_archivo(self.ruta)
            return
        self.canvas.delete("all")
        self._imgs.clear()
        pdf = pdfium.PdfDocument(str(self.ruta))
        y = 20
        objetivo = min(ancho - 60, 1000) * self.escala
        for i in range(min(len(pdf), 40)):
            pag = pdf[i]
            img = pag.render(scale=objetivo / pag.get_width()).to_pil()
            foto = ImageTk.PhotoImage(img)
            self._imgs.append(foto)
            x = max(ancho / 2, img.width / 2 + 20)
            self.canvas.create_rectangle(x - img.width / 2 + 3, y + 3, x + img.width / 2 + 3,
                                         y + img.height + 3, fill="#3b3e41", outline="")
            self.canvas.create_image(x, y, image=foto, anchor="n")
            y += img.height + 20
        if len(pdf) > 40:
            self.canvas.create_text(ancho / 2, y + 10, fill="white", font=(FUENTE, 10),
                                    text=f"… {len(pdf) - 40} páginas más. Ábrelo en el lector PDF para verlas todas.")
            y += 40
        pdf.close()
        self.canvas.configure(scrollregion=(0, 0, max(ancho, objetivo + 40), y))


# ------------------------------------------------------------------ diálogos


class DialogoPin(tk.Toplevel):
    def __init__(self, app: App):
        super().__init__(app)
        self.ok = False
        self.title("Configuración")
        self.configure(bg=C["tarjeta"])
        self.resizable(False, False)
        self.transient(app)
        tk.Label(self, text="Configuración protegida", bg=C["tarjeta"], fg=C["texto"],
                 font=(FUENTE, 13, "bold")).pack(padx=40, pady=(24, 2))
        etiqueta(self, "Introduce el código de acceso").pack()
        self.v = tk.StringVar()
        e = ttk.Entry(self, textvariable=self.v, show="•", width=12, justify="center", font=(FUENTE, 16))
        e.pack(pady=14)
        self.lbl = etiqueta(self, "", 9, C["error"])
        self.lbl.pack()
        pie = tk.Frame(self, bg=C["tarjeta"])
        pie.pack(pady=(6, 20))
        Boton(pie, "Cancelar", self.destroy).pack(side="left", padx=4)
        Boton(pie, "Entrar", self.comprobar, "primario").pack(side="left", padx=4)
        e.bind("<Return>", lambda ev: self.comprobar())
        e.focus_set()
        self.update_idletasks()
        x = app.winfo_rootx() + (app.winfo_width() - self.winfo_width()) // 2
        y = app.winfo_rooty() + (app.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.grab_set()
        self.wait_window()

    def comprobar(self):
        if self.v.get().strip() == PIN_CONFIGURACION:
            self.ok = True
            self.destroy()
        else:
            self.lbl.config(text="Código incorrecto")
            self.v.set("")


class DialogoEmail(tk.Toplevel):
    def __init__(self, app: App, cliente: Cliente, al_guardar):
        super().__init__(app)
        self.title("Email del cliente")
        self.configure(bg=C["tarjeta"])
        self.transient(app)
        tk.Label(self, text=cliente.nombre, bg=C["tarjeta"], fg=C["texto"], font=(FUENTE, 12, "bold")).pack(
            anchor="w", padx=22, pady=(18, 2))
        etiqueta(self, "Varios emails separados por coma").pack(anchor="w", padx=22)
        v = tk.StringVar(value=cliente.email)
        e = ttk.Entry(self, textvariable=v, width=50)
        e.pack(padx=22, pady=12)
        pie = tk.Frame(self, bg=C["tarjeta"])
        pie.pack(anchor="e", padx=22, pady=(0, 18))

        def guardar():
            cliente.email = v.get().strip()
            app.almacen.guardar_cliente(cliente)
            self.destroy()
            al_guardar()
        Boton(pie, "Cancelar", self.destroy).pack(side="left", padx=4)
        Boton(pie, "Guardar", guardar, "primario").pack(side="left")
        e.bind("<Return>", lambda ev: guardar())
        e.focus_set()
        self.grab_set()


class DialogoEnvio(tk.Toplevel):
    def __init__(self, app: App, cliente: Cliente, asunto: str, cuerpo: str, generar, grupo: str,
                 permite_extra: bool, al_enviar):
        super().__init__(app)
        self.app, self.cliente, self.generar, self.grupo, self.al_enviar = app, cliente, generar, grupo, al_enviar
        self.title("Enviar por email")
        self.configure(bg=C["tarjeta"])
        self.geometry("640x580")
        self.transient(app)
        self.grab_set()
        tk.Label(self, text="Enviar por email", bg=C["tarjeta"], fg=C["texto"],
                 font=(FUENTE, 15, "bold")).pack(anchor="w", padx=22, pady=(18, 0))
        from .correo import usuario_envio
        etiqueta(self, f"{cliente.nombre}   ·   desde {usuario_envio(app.cfg)}", 10).pack(anchor="w", padx=22)

        f = tk.Frame(self, bg=C["tarjeta"])
        f.pack(fill="both", expand=True, padx=4, pady=10)
        f.columnconfigure(1, weight=1)
        self.v_para = tk.StringVar(value=cliente.email)
        self.v_asunto = tk.StringVar(value=asunto)
        e = campo(f, "Para", self.v_para, 0, ancho=50)
        self.v_guardar = tk.BooleanVar(value=not cliente.email)
        ttk.Checkbutton(f, text="Guardar este email en la ficha del cliente", variable=self.v_guardar).grid(
            row=1, column=1, sticky="w", pady=(0, 6))
        campo(f, "Asunto", self.v_asunto, 2, ancho=50)
        etiqueta(f, "Mensaje").grid(row=3, column=0, sticky="nw", padx=(18, 8), pady=6)
        self.txt = tk.Text(f, height=10, wrap="word", font=(FUENTE, 10), relief="flat",
                           highlightthickness=1, highlightbackground=C["borde"], padx=8, pady=6)
        self.txt.grid(row=3, column=1, sticky="nsew", padx=(0, 18), pady=6)
        self.txt.insert("1.0", cuerpo)
        f.rowconfigure(3, weight=1)
        self.v_pdf = tk.BooleanVar(value=True)
        self.v_xlsx = tk.BooleanVar(value=bool(app.cfg["envio"].get("adjuntar_excel")) and permite_extra)
        self.v_csv = tk.BooleanVar(value=bool(app.cfg["envio"].get("adjuntar_csv")) and permite_extra)
        adj = tk.Frame(f, bg=C["tarjeta"])
        adj.grid(row=4, column=1, sticky="w", pady=(4, 0))
        etiqueta(f, "Adjuntos").grid(row=4, column=0, sticky="w", padx=(18, 8))
        opciones = [("PDF", self.v_pdf)] + ([("Excel", self.v_xlsx), ("CSV", self.v_csv)] if permite_extra else [])
        for txt, v in opciones:
            ttk.Checkbutton(adj, text=txt, variable=v).pack(side="left", padx=(0, 14))
        self.v_copia = tk.BooleanVar(value=app.cfg["correo"].get("copia_a_mi", True))
        ttk.Checkbutton(f, text="Enviarme copia oculta", variable=self.v_copia).grid(row=5, column=1, sticky="w", pady=6)

        pie = tk.Frame(self, bg="#F9FAFB")
        pie.pack(fill="x", side="bottom")
        self.b_enviar = Boton(pie, "Enviar", self.enviar, "primario", icono="✉")
        self.b_enviar.pack(side="right", padx=(6, 18), pady=12)
        Boton(pie, "Cancelar", self.destroy).pack(side="right", pady=12)
        self.lbl = tk.Label(pie, text="", bg="#F9FAFB", fg=C["suave"], font=(FUENTE, 9))
        self.lbl.pack(side="left", padx=18)
        e.focus_set()

    def enviar(self):
        para = [x.strip() for x in self.v_para.get().replace(";", ",").split(",") if x.strip()]
        if not para or any("@" not in x for x in para):
            messagebox.showwarning(NOMBRE_APP, "Escribe un email válido.", parent=self)
            return
        pw = self.app.password_envio()
        if not pw or not self.app.cfg["correo"].get("smtp_servidor"):
            messagebox.showwarning(NOMBRE_APP, "Falta configurar la cuenta de envío (Configuración > Correo).", parent=self)
            return
        if not (self.v_pdf.get() or self.v_xlsx.get() or self.v_csv.get()):
            messagebox.showwarning(NOMBRE_APP, "Marca al menos un adjunto.", parent=self)
            return
        if self.v_guardar.get():
            self.cliente.email = ", ".join(para)
            self.app.almacen.guardar_cliente(self.cliente)
        from .correo import enviar_email, usuario_envio
        cfg, almacen, grupo, clave = self.app.cfg, self.app.almacen, self.grupo, self.cliente.clave
        asunto, cuerpo = self.v_asunto.get(), self.txt.get("1.0", "end").strip()
        quiere = (self.v_pdf.get(), self.v_xlsx.get(), self.v_csv.get())
        bcc = [usuario_envio(cfg)] if self.v_copia.get() else []
        adjuntos = self.generar(*quiere)  # se generan aquí (rápido) para no tocar la interfaz desde otro hilo
        self.b_enviar.activar(False)
        self.lbl.config(text="Enviando…")

        def trabajo():
            enviar_email(cfg, pw, para, asunto, cuerpo, adjuntos, bcc)
            almacen.registrar_envio(grupo, clave, para)

        def fin(_):
            self.app.notificar(f"✔ Enviado a {', '.join(para)}")
            self.al_enviar()
            if self.winfo_exists():
                self.destroy()

        def fallo(e):
            if self.winfo_exists():
                self.b_enviar.activar(True)
                self.lbl.config(text="")
            messagebox.showerror(NOMBRE_APP, f"No se pudo enviar:\n{e}", parent=self if self.winfo_exists() else self.app)

        self.app.en_fondo(trabajo, fin, fallo)


# --------------------------------------------------------------- clientes


class PaginaClientes(Pagina):
    CAMPOS = [("nombre", "Nombre / Razón social"), ("nif", "NIF / CIF"), ("codigo", "Código"),
              ("email", "Email"), ("telefono", "Teléfono"), ("direccion", "Dirección"),
              ("cp", "Código postal"), ("poblacion", "Población"), ("provincia", "Provincia")]

    def __init__(self, master, app):
        self.clave = None
        super().__init__(master, app, "Clientes",
                         "Datos que salen en los listados y en las cartas del 347.")
        Boton(self.acciones, "Importar ficha de clientes", self.importar, icono="+").pack(side="right")
        cuerpo = tk.Frame(self, bg=C["fondo"])
        cuerpo.pack(fill="both", expand=True, padx=28, pady=(0, 24))
        izq = Tarjeta(cuerpo)
        busq = tk.Frame(izq, bg=C["tarjeta"])
        busq.pack(fill="x", padx=16, pady=14)
        self.v_buscar = tk.StringVar()
        self.v_buscar.trace_add("write", lambda *a: self.pintar())
        e = ttk.Entry(busq, textvariable=self.v_buscar, width=40)
        e.pack(side="left")
        PaginaPorCliente._marcador(e, "Buscar cliente o NIF…")
        self.v_solo = tk.BooleanVar()
        ttk.Checkbutton(busq, text="Solo sin email", variable=self.v_solo, command=self.pintar).pack(side="left", padx=12)
        marco, self.tv = tabla(izq, [("nombre", "Cliente", 280, "w"), ("nif", "NIF/CIF", 110, "w"),
                                     ("email", "Email", 220, "w"), ("pob", "Población", 130, "w")], altura=18)
        marco.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self.tv.bind("<<TreeviewSelect>>", lambda e: self.cargar())

        der = Tarjeta(cuerpo, "Ficha del cliente")
        der.pack(side="right", fill="y", padx=(16, 0))
        izq.pack(side="left", fill="both", expand=True)
        frm = tk.Frame(der, bg=C["tarjeta"])
        frm.pack(fill="both")
        self.vars = {k: tk.StringVar() for k, _ in self.CAMPOS}
        for i, (k, et) in enumerate(self.CAMPOS):
            campo(frm, et, self.vars[k], i, ancho=26)
        Boton(der, "Guardar cambios", self.guardar, "primario").pack(anchor="e", padx=18, pady=16)
        self.clave = None

    def al_mostrar(self):
        self.pintar()

    def importar(self):
        ruta = filedialog.askopenfilename(parent=self, title="Fichero de clientes exportado del programa de gestión",
                                          filetypes=[("Clientes", "*.csv *.txt *.xlsx"), ("Todos", "*.*")])
        if not ruta:
            return
        almacen = self.app.almacen

        def fin(r):
            self.pintar()
            messagebox.showinfo(NOMBRE_APP, f"Clientes importados.\n\nNuevos: {r['nuevos']}\nActualizados: {r['actualizados']}\n"
                                f"Con email: {r['con_email']}\nOmitidos (clientes varios / de baja): {r['omitidos']}", parent=self)

        self.app.en_fondo(lambda: almacen.importar_clientes(ruta), fin)

    def pintar(self):
        if not hasattr(self, "tv"):
            return
        sel = self.clave
        self.tv.delete(*self.tv.get_children())
        q = self.v_buscar.get()
        q = "" if q.startswith("Buscar cliente") else q.lower().strip()
        for i, c in enumerate(sorted(self.app.almacen.clientes().values(), key=lambda c: c.nombre.lower())):
            if q and q not in f"{c.nombre} {c.nif} {c.email} {c.codigo}".lower():
                continue
            if self.v_solo.get() and c.email:
                continue
            self.tv.insert("", "end", iid=c.clave, values=(c.nombre, c.nif, c.email, c.poblacion),
                           tags=("par",) if i % 2 else ())
        if sel and sel in self.tv.get_children():
            self.tv.selection_set(sel)

    def cargar(self):
        sel = self.tv.selection()
        if not sel:
            return
        self.clave = sel[0]
        c = self.app.almacen.clientes().get(self.clave)
        for k, _ in self.CAMPOS:
            self.vars[k].set(getattr(c, k, "") if c else "")

    def guardar(self):
        if not self.clave:
            return
        c = self.app.almacen.clientes().get(self.clave) or Cliente(clave=self.clave)
        for k, _ in self.CAMPOS:
            setattr(c, k, self.vars[k].get().strip())
        self.app.almacen.guardar_cliente(c)
        self.pintar()
        self.app.notificar("✔ Cliente guardado", "ok", 3)


# ---------------------------------------------------------- configuración


class PaginaConfig(Pagina):
    def __init__(self, master, app):
        super().__init__(master, app, "Configuración", "Zona interna. Los cambios se aplican al guardar.")
        Boton(self.acciones, "Guardar", self.guardar, "primario", icono="✔").pack(side="right")
        Boton(self.acciones, "Bloquear", self.bloquear).pack(side="right", padx=8)

        cont = tk.Frame(self, bg=C["fondo"])
        cont.pack(fill="both", expand=True, padx=28, pady=(0, 16))
        canvas = tk.Canvas(cont, bg=C["fondo"], highlightthickness=0)
        sb = ttk.Scrollbar(cont, orient="vertical", command=canvas.yview)
        self.interior = tk.Frame(canvas, bg=C["fondo"])
        self.interior.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        ventana = canvas.create_window((0, 0), window=self.interior, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(ventana, width=e.width))
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        def rueda(e):
            if self.winfo_ismapped():
                canvas.yview_scroll(int(-e.delta / 120) if e.delta else (-3 if e.num == 4 else 3), "units")
        self.bind_all("<MouseWheel>", rueda, add="+")
        self.bind_all("<Button-4>", rueda, add="+")
        self.bind_all("<Button-5>", rueda, add="+")
        self._construir()

    def bloquear(self):
        self.app.config_desbloqueada = False
        self.app.mostrar("listados")

    def al_mostrar(self):
        self.pintar_diarios()

    def _tarjeta(self, titulo, explicacion=""):
        t = Tarjeta(self.interior, titulo)
        t.pack(fill="x", pady=(0, 14))
        if explicacion:
            etiqueta(t, explicacion, 9, C["tenue"], wraplength=900, justify="left").pack(anchor="w", padx=18)
        f = tk.Frame(t, bg=C["tarjeta"])
        f.pack(fill="x", pady=(6, 14))
        f.columnconfigure(1, weight=1)
        f.columnconfigure(3, weight=1)
        return f

    def _construir(self):
        cfg = self.app.cfg
        self.v = {}

        def var(seccion, clave, tipo=tk.StringVar):
            v = tipo(value=cfg[seccion].get(clave, "" if tipo is tk.StringVar else False))
            self.v[(seccion, clave)] = v
            return v

        # Empresa (fija)
        emp = cfg["empresa"]
        f = self._tarjeta("Datos de la empresa", "Fijos: aparecen así en todos los listados y cartas.")
        txt = (f"{emp['nombre']}   ·   CIF {emp['cif']}\n{emp['direccion']}\n"
               f"{emp['cp']} {emp['poblacion']} ({emp['provincia']})   ·   {emp['email']}")
        etiqueta(f, txt, 10, C["texto"], justify="left").grid(row=0, column=0, sticky="w", padx=18)

        # Recepción
        f = self._tarjeta("Correo · recepción de diarios",
                          "Buzón donde el programa de gestión deja el Diario de facturación ampliado.")
        campo(f, "Cuenta", var("correo", "usuario"), 0, ancho=30)
        self.v_pw = tk.StringVar(value=leer_password(cfg["correo"]["usuario"]))
        campo(f, "Contraseña", self.v_pw, 0, col=2, ancho=22, mostrar="•")
        campo(f, "Servidor IMAP", var("correo", "imap_servidor"), 1, ancho=30)
        campo(f, "Puerto", var("correo", "imap_puerto"), 1, col=2, ancho=8)
        campo(f, "Carpeta", var("correo", "carpeta"), 2, ancho=30)
        campo(f, "Revisar cada (min)", var("correo", "intervalo_min"), 2, col=2, ancho=8)
        ttk.Checkbutton(f, text="Revisar el correo automáticamente",
                        variable=var("correo", "comprobar_auto", tk.BooleanVar)).grid(row=3, column=1, sticky="w", pady=(6, 0))

        # Envío
        f = self._tarjeta("Correo · envío a clientes", "Cuenta desde la que salen los listados y las cartas del 347.")
        campo(f, "Cuenta", var("correo", "smtp_usuario"), 0, ancho=30)
        self.v_pw_envio = tk.StringVar(value=leer_password(cfg["correo"].get("smtp_usuario") or cfg["correo"]["usuario"]))
        campo(f, "Contraseña", self.v_pw_envio, 0, col=2, ancho=22, mostrar="•")
        campo(f, "Servidor SMTP", var("correo", "smtp_servidor"), 1, ancho=30)
        campo(f, "Puerto", var("correo", "smtp_puerto"), 1, col=2, ancho=8)
        campo(f, "Nombre remitente", var("correo", "remitente_nombre"), 2, ancho=30)
        etiqueta(f, "Seguridad").grid(row=2, column=2, sticky="w", padx=(18, 8))
        ttk.Combobox(f, textvariable=var("correo", "smtp_seguridad"), values=["SSL", "STARTTLS", "Ninguna"],
                     state="readonly", width=12).grid(row=2, column=3, sticky="w")
        ops = tk.Frame(f, bg=C["tarjeta"])
        ops.grid(row=3, column=1, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Checkbutton(ops, text="Enviarme copia oculta de cada envío",
                        variable=var("correo", "copia_a_mi", tk.BooleanVar)).pack(side="left")
        Boton(ops, "Probar conexión", self._probar).pack(side="left", padx=16)

        # Mensajes
        f = self._tarjeta("Mensaje de los listados",
                          "Puedes usar: {cliente} {periodo} {num_facturas} {total} {empresa} {empresa_telefono}")
        campo(f, "Asunto", var("envio", "asunto"), 0, ancho=70)
        self.txt_cuerpo = self._texto(f, 1, cfg["envio"]["cuerpo"])
        ops = tk.Frame(f, bg=C["tarjeta"])
        ops.grid(row=2, column=1, columnspan=3, sticky="w", pady=(6, 0))
        etiqueta(ops, "Adjuntar además:").pack(side="left")
        ttk.Checkbutton(ops, text="Excel", variable=var("envio", "adjuntar_excel", tk.BooleanVar)).pack(side="left", padx=10)
        ttk.Checkbutton(ops, text="CSV", variable=var("envio", "adjuntar_csv", tk.BooleanVar)).pack(side="left")

        f = self._tarjeta("Mensaje del Modelo 347", "Puedes usar: {cliente} {ejercicio} {total} {empresa} {empresa_telefono}")
        campo(f, "Asunto", var("envio347", "asunto"), 0, ancho=70)
        self.txt_347 = self._texto(f, 1, cfg["envio347"]["cuerpo"])

        # Diarios recibidos (interno)
        t = Tarjeta(self.interior, "Diarios recibidos")
        t.pack(fill="x", pady=(0, 14))
        etiqueta(t, "Cada diario actualiza las facturas de su periodo. Si hace falta, se puede importar uno a mano o volver a leerlo.",
                 9, C["tenue"], wraplength=900, justify="left").pack(anchor="w", padx=18)
        marco, self.tv_d = tabla(t, [("rec", "Recibido", 140, "w"), ("arch", "Archivo", 330, "w"),
                                     ("per", "Periodo", 200, "w"), ("n", "Facturas", 80, "e"),
                                     ("orig", "Origen", 90, "w")], altura=6)
        marco.pack(fill="x", padx=18, pady=8)
        b = tk.Frame(t, bg=C["tarjeta"])
        b.pack(fill="x", padx=18, pady=(0, 14))
        Boton(b, "Importar diario…", self.importar_diario, icono="+").pack(side="left")
        Boton(b, "Volver a leer", self.releer).pack(side="left", padx=8)
        Boton(b, "Ver original", self.ver_original).pack(side="left")
        Boton(b, "Eliminar", self.eliminar_diario, "peligro").pack(side="right")

        # Tipos
        f = self._tarjeta("Tipo de factura según la serie",
                          "Solo se usa si el diario no indica el tipo. Una regla por línea: SERIE = Tipo")
        self.txt_series = tk.Text(f, height=5, width=36, font=("Consolas" if os.name == "nt" else "DejaVu Sans Mono", 10),
                                  relief="flat", highlightthickness=1, highlightbackground=C["borde"], padx=8, pady=6)
        self.txt_series.grid(row=0, column=0, columnspan=2, sticky="w", padx=18)
        self.txt_series.insert("1.0", "\n".join(f"{k} = {v}" for k, v in cfg["tipos"]["series"].items()))
        etiqueta(f, "Si no coincide").grid(row=0, column=2, sticky="nw", padx=(18, 8))
        ttk.Combobox(f, textvariable=var("tipos", "por_defecto"), values=TIPOS_FACTURA, state="readonly",
                     width=16).grid(row=0, column=3, sticky="nw")

        # Actualizaciones y general
        f = self._tarjeta("Programa")
        campo(f, "Repositorio GitHub", var("actualizaciones", "repo"), 0, ancho=40)
        campo(f, "Token (solo privado)", var("actualizaciones", "token"), 1, ancho=40, mostrar="•")
        ops = tk.Frame(f, bg=C["tarjeta"])
        ops.grid(row=2, column=0, columnspan=4, sticky="w", padx=18, pady=(8, 0))
        ttk.Checkbutton(ops, text="Buscar actualizaciones al abrir",
                        variable=var("actualizaciones", "comprobar_al_iniciar", tk.BooleanVar)).pack(side="left")
        ttk.Checkbutton(ops, text="Abrir al iniciar Windows (minimizado)",
                        variable=var("general", "iniciar_con_windows", tk.BooleanVar)).pack(side="left", padx=20)
        Boton(ops, f"Buscar actualización (v{VERSION})", lambda: self.app.buscar_actualizacion()).pack(side="left", padx=4)
        Boton(ops, "Carpeta de documentos", lambda: abrir_archivo(ruta_documentos())).pack(side="left", padx=8)

    def _texto(self, f, fila, contenido):
        etiqueta(f, "Texto").grid(row=fila, column=0, sticky="nw", padx=(18, 8), pady=6)
        t = tk.Text(f, height=7, wrap="word", font=(FUENTE, 10), relief="flat",
                    highlightthickness=1, highlightbackground=C["borde"], padx=8, pady=6)
        t.grid(row=fila, column=1, columnspan=3, sticky="we", padx=(0, 18), pady=6)
        t.insert("1.0", contenido)
        return t

    # --- diarios
    def pintar_diarios(self):
        self.tv_d.delete(*self.tv_d.get_children())
        for i, m in enumerate(self.app.almacen.lista_diarios()):
            d = date.fromisoformat(m["desde"]) if m.get("desde") else None
            h = date.fromisoformat(m["hasta"]) if m.get("hasta") else None
            self.tv_d.insert("", "end", iid=m["id"], tags=("par",) if i % 2 else (), values=(
                datetime.fromisoformat(m["recibido"]).strftime("%d/%m/%Y %H:%M"), m.get("archivo", ""),
                texto_periodo(d, h) or "—", m.get("num_facturas", 0),
                "correo" if m.get("origen") == "correo" else "a mano"))

    def _diario_sel(self):
        s = self.tv_d.selection()
        if not s:
            messagebox.showinfo(NOMBRE_APP, "Selecciona un diario de la lista.", parent=self)
        return s[0] if s else None

    def importar_diario(self):
        rutas = filedialog.askopenfilenames(parent=self, title="Diario de facturación",
                                            filetypes=[("Diarios", "*.pdf *.xlsx *.xlsm *.csv"), ("Todos", "*.*")])
        if not rutas:
            return
        almacen, cfg = self.app.almacen, self.app.cfg
        self.app.notificar("Leyendo el diario… (los grandes tardan hasta un minuto)", "info", 60)

        def trabajo():
            return [almacen.procesar(r, cfg, "manual")[1] for r in rutas]

        def fin(ds):
            self.pintar_diarios()
            self.app.datos_cambiados()
            self.app.notificar(f"✔ {sum(len(d.facturas) for d in ds)} facturas leídas.")

        self.app.en_fondo(trabajo, fin)

    def releer(self):
        ident = self._diario_sel()
        if not ident:
            return
        almacen, cfg = self.app.almacen, self.app.cfg
        self.app.notificar("Volviendo a leer el diario…", "info", 60)

        def fin(d):
            self.pintar_diarios()
            self.app.datos_cambiados()
            self.app.notificar(f"✔ {len(d.facturas)} facturas leídas.", "aviso" if d.avisos else "ok")

        self.app.en_fondo(lambda: almacen.reprocesar(ident, cfg), fin)

    def ver_original(self):
        ident = self._diario_sel()
        if ident:
            abrir_archivo(self.app.almacen.ruta_original(ident))

    def eliminar_diario(self):
        ident = self._diario_sel()
        if ident and messagebox.askyesno(NOMBRE_APP, "¿Eliminar este diario?\nSus facturas se quitarán salvo que "
                                         "otro diario las incluya.", parent=self):
            self.app.almacen.eliminar_diario(ident)
            self.pintar_diarios()
            self.app._estado_recepcion()

    # --- guardar
    def _volcar(self) -> dict:
        cfg = self.app.cfg
        for (sec, k), v in self.v.items():
            val = v.get()
            if k in ("imap_puerto", "smtp_puerto", "intervalo_min"):
                try:
                    val = int(str(val).strip())
                except ValueError:
                    val = cfg[sec][k]
            elif isinstance(val, str):
                val = val.strip()
            cfg[sec][k] = val
        cfg["envio"]["cuerpo"] = self.txt_cuerpo.get("1.0", "end").rstrip()
        cfg["envio347"]["cuerpo"] = self.txt_347.get("1.0", "end").rstrip()
        series = {}
        for linea in self.txt_series.get("1.0", "end").splitlines():
            if "=" in linea:
                a, b = linea.split("=", 1)
                b = b.strip()
                tipo = next((t for t in TIPOS_FACTURA if t.lower() == b.lower()), b)
                if a.strip():
                    series[a.strip().upper()] = tipo
        cfg["tipos"]["series"] = series
        return cfg

    def guardar(self):
        cfg = self._volcar()
        guardar_config(cfg)
        if self.v_pw.get():
            guardar_password(cfg["correo"]["usuario"], self.v_pw.get())
        if self.v_pw_envio.get():
            guardar_password(cfg["correo"].get("smtp_usuario") or cfg["correo"]["usuario"], self.v_pw_envio.get())
        _iniciar_con_windows(cfg["general"].get("iniciar_con_windows", False))
        self.app._estado_recepcion()
        self.app.notificar("✔ Configuración guardada", "ok", 3)

    def _probar(self):
        cfg = self._volcar()
        pw, pw2 = self.v_pw.get(), self.v_pw_envio.get()
        self.app.notificar("Probando conexión…", "info", 3)

        def trabajo():
            from .correo import probar_conexion
            return probar_conexion(cfg, pw, pw2)
        self.app.en_fondo(trabajo, lambda r: messagebox.showinfo(NOMBRE_APP, r, parent=self),
                          lambda e: messagebox.showerror(NOMBRE_APP, f"Error de conexión:\n{e}", parent=self))


def _iniciar_con_windows(activar: bool) -> None:
    if os.name != "nt":
        return
    try:
        import winreg
        clave = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run",
                               0, winreg.KEY_SET_VALUE)
        if activar:
            if getattr(sys, "frozen", False):
                valor = f'"{sys.executable}" --minimizado'
            else:
                valor = f'"{sys.executable}" "{Path(sys.argv[0]).resolve()}" --minimizado'
            winreg.SetValueEx(clave, "FacturasLH", 0, winreg.REG_SZ, valor)
        else:
            try:
                winreg.DeleteValue(clave, "FacturasLH")
            except FileNotFoundError:
                pass
        winreg.CloseKey(clave)
    except Exception:
        traceback.print_exc()


# --------------------------------------------------------- actualización


class DialogoActualizacion(tk.Toplevel):
    def __init__(self, app: App, info: actualizador.InfoVersion):
        super().__init__(app)
        self.app, self.info = app, info
        self.title("Actualización disponible")
        self.configure(bg=C["tarjeta"])
        self.geometry("520x400")
        self.transient(app)
        tk.Label(self, text="Nueva versión disponible", bg=C["tarjeta"], fg=C["texto"],
                 font=(FUENTE, 15, "bold")).pack(anchor="w", padx=22, pady=(20, 2))
        etiqueta(self, f"Instalada: {VERSION}   →   Nueva: {info.version}", 10).pack(anchor="w", padx=22)
        txt = tk.Text(self, height=9, wrap="word", font=(FUENTE, 9), relief="flat", bg="#F9FAFB",
                      padx=10, pady=8)
        txt.pack(fill="both", expand=True, padx=22, pady=12)
        txt.insert("1.0", info.notas or "Mejoras y correcciones.")
        txt.config(state="disabled")
        self.barra = ttk.Progressbar(self, mode="determinate", maximum=100)
        pie = tk.Frame(self, bg=C["tarjeta"])
        pie.pack(fill="x", side="bottom", pady=(0, 16))
        self.b = Boton(pie, "Actualizar ahora", self.actualizar, "primario")
        self.b.pack(side="right", padx=(6, 22))
        Boton(pie, "Más tarde", self.destroy).pack(side="right")

    def actualizar(self):
        if not actualizador.puede_autoinstalar():
            webbrowser.open(self.info.pagina)
            self.destroy()
            return
        self.b.activar(False)
        self.barra.pack(fill="x", padx=22, pady=(0, 10))
        token = self.app.cfg["actualizaciones"].get("token", "")

        def progreso(leido, total):
            if total:
                self.app._cola.put((lambda _: self.barra.winfo_exists() and self.barra.configure(value=leido * 100 / total), None, None))

        def fin(ruta):
            self.app.notificar("Instalando la actualización… el programa se reiniciará.", "info", 5)
            actualizador.instalar_y_reiniciar(ruta)
            self.app.after(800, self.app.destroy)

        def fallo(e):
            self.b.activar(True)
            self.app.error(f"No se pudo descargar la actualización:\n{e}")

        self.app.en_fondo(lambda: actualizador.descargar(self.info, token, progreso), fin, fallo)


def iniciar():
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    app = App(minimizado="--minimizado" in sys.argv)
    app.mainloop()
