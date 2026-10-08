"""Interfaz gráfica de Facturas LH (tkinter)."""
from __future__ import annotations

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
from tkinter import colorchooser, filedialog, messagebox, ttk

from . import actualizador
from .almacen import Almacen
from .config import (cargar_config, guardar_config, guardar_password, leer_password,
                     ruta_documentos, ruta_recursos)
from .informe import eur, fecha_es, texto_periodo
from .modelo import IVA_TIPOS, TIPOS_FACTURA, Cliente
from .version import NOMBRE_APP, VERSION

# ------------------------------------------------------------------ estilo
C = {
    "lateral": "#1F2328",
    "lateral_hover": "#2D333B",
    "lateral_texto": "#C9D1D9",
    "fondo": "#F3F4F6",
    "tarjeta": "#FFFFFF",
    "borde": "#E5E7EB",
    "texto": "#1F2328",
    "suave": "#6B7280",
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


# ---------------------------------------------------------------- widgets


class Boton(tk.Label):
    """Botón plano con hover (los botones ttk no permiten este acabado en Windows)."""

    def __init__(self, master, texto, comando, tipo="secundario", icono="", **kw):
        estilos = {
            "primario": (C["acento"], "#FFFFFF", C["acento_hover"], C["acento"]),
            "secundario": (C["tarjeta"], C["texto"], "#F3F4F6", C["borde"]),
            "peligro": (C["tarjeta"], C["error"], "#FEE2E2", "#FCA5A5"),
            "lateral": (C["lateral"], C["lateral_texto"], C["lateral_hover"], C["lateral"]),
        }
        self._bg, fg, self._hover, borde = estilos[tipo]
        super().__init__(master, text=(f"{icono}  {texto}" if icono else texto), bg=self._bg, fg=fg,
                         font=(FUENTE, 10, "bold" if tipo == "primario" else "normal"),
                         padx=14, pady=7, cursor="hand2", highlightthickness=1,
                         highlightbackground=borde, highlightcolor=borde, **kw)
        self._cmd = comando
        self._fg = fg
        self._activo = True
        self.bind("<Enter>", lambda e: self._activo and self.config(bg=self._hover))
        self.bind("<Leave>", lambda e: self.config(bg=self._bg))
        self.bind("<Button-1>", lambda e: self._activo and self._cmd and self._cmd())

    def activar(self, si: bool) -> None:
        self._activo = si
        self.config(fg=self._fg if si else "#9CA3AF", cursor="hand2" if si else "watch")


class Tarjeta(tk.Frame):
    def __init__(self, master, titulo: str = "", **kw):
        super().__init__(master, bg=C["tarjeta"], highlightthickness=1,
                         highlightbackground=C["borde"], **kw)
        if titulo:
            tk.Label(self, text=titulo.upper(), bg=C["tarjeta"], fg=C["acento"],
                     font=(FUENTE, 8, "bold")).pack(anchor="w", padx=16, pady=(12, 4))


def tabla(master, columnas: list[tuple[str, str, int, str]], altura=10, seleccion="browse"):
    """columnas: [(id, título, ancho, alineación 'w'|'e'|'center')]"""
    marco = tk.Frame(master, bg=C["tarjeta"])
    tv = ttk.Treeview(marco, columns=[c[0] for c in columnas], show="headings", height=altura,
                      selectmode=seleccion)
    for cid, tit, ancho, al in columnas:
        tv.heading(cid, text=tit, anchor=al)
        tv.column(cid, width=ancho, minwidth=40, anchor=al, stretch=cid in (columnas[0][0], "email", "aviso"))
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
        row=fila, column=col, sticky="w", padx=(16, 8), pady=4)
    e = ttk.Entry(master, textvariable=var, width=ancho, show=mostrar or "")
    e.grid(row=fila, column=col + 1, sticky="we", padx=(0, 16), pady=4)
    if ayuda:
        tk.Label(master, text=ayuda, bg=C["tarjeta"], fg="#9CA3AF", font=(FUENTE, 8)).grid(
            row=fila, column=col + 2, sticky="w", padx=(0, 16))
    return e


# ================================================================ aplicación


class App(tk.Tk):
    def __init__(self, minimizado: bool = False):
        super().__init__()
        self.cfg = cargar_config()
        self.almacen = Almacen()
        self._cola: queue.Queue = queue.Queue()
        self._comprobando = False
        self.title(f"{NOMBRE_APP} · {self.cfg['empresa']['nombre']}")
        self.geometry("1320x800")
        self.minsize(1080, 640)
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
        self.mostrar("diarios")
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
        s.configure("TCombobox", padding=5, arrowsize=14)
        s.configure("TCheckbutton", background=C["tarjeta"], font=(FUENTE, 10))
        s.configure("Vertical.TScrollbar", background="#E5E7EB", troughcolor=C["tarjeta"],
                    bordercolor=C["tarjeta"], arrowcolor=C["suave"], relief="flat")
        s.configure("TPanedwindow", background=C["fondo"])
        s.configure("Horizontal.TProgressbar", background=C["acento"], troughcolor="#E5E7EB",
                    bordercolor="#E5E7EB", lightcolor=C["acento"], darkcolor=C["acento"])

    # ------------------------------------------------------------- estructura
    def _construir(self):
        lateral = tk.Frame(self, bg=C["lateral"], width=220)
        lateral.pack(side="left", fill="y")
        lateral.pack_propagate(False)
        try:
            self._logo = tk.PhotoImage(file=str(ruta_recursos() / "logo_sidebar.png"))
            tk.Label(lateral, image=self._logo, bg=C["lateral"]).pack(pady=(26, 6))
        except Exception:
            tk.Label(lateral, text="FERRETERÍA LH", bg=C["lateral"], fg="white",
                     font=(FUENTE, 14, "bold")).pack(pady=(26, 6))
        tk.Label(lateral, text="Listados de facturas", bg=C["lateral"], fg="#8B949E",
                 font=(FUENTE, 9)).pack(pady=(0, 24))

        self._nav = {}
        for clave, texto, icono in [("diarios", "Diarios", "▤"), ("clientes", "Clientes", "◎"),
                                    ("config", "Configuración", "⚙")]:
            b = tk.Label(lateral, text=f"   {icono}   {texto}", anchor="w", bg=C["lateral"],
                         fg=C["lateral_texto"], font=(FUENTE, 11), pady=11, cursor="hand2")
            b.pack(fill="x", padx=12, pady=2)
            b.bind("<Button-1>", lambda e, k=clave: self.mostrar(k))
            b.bind("<Enter>", lambda e, w=b, k=clave: self._pagina != k and w.config(bg=C["lateral_hover"]))
            b.bind("<Leave>", lambda e, w=b, k=clave: self._pagina != k and w.config(bg=C["lateral"]))
            self._nav[clave] = b

        pie = tk.Frame(lateral, bg=C["lateral"])
        pie.pack(side="bottom", fill="x", padx=18, pady=16)
        self.lbl_estado = tk.Label(pie, text="", bg=C["lateral"], fg="#8B949E", font=(FUENTE, 8),
                                   justify="left", wraplength=180, anchor="w")
        self.lbl_estado.pack(fill="x")
        self.lbl_version = tk.Label(pie, text=f"Versión {VERSION}", bg=C["lateral"], fg="#6E7681",
                                    font=(FUENTE, 8), anchor="w", cursor="hand2")
        self.lbl_version.pack(fill="x", pady=(6, 0))
        self.lbl_version.bind("<Button-1>", lambda e: self.buscar_actualizacion())

        self.contenido = tk.Frame(self, bg=C["fondo"])
        self.contenido.pack(side="left", fill="both", expand=True)
        self.paginas = {
            "diarios": PaginaDiarios(self.contenido, self),
            "clientes": PaginaClientes(self.contenido, self),
            "config": PaginaConfig(self.contenido, self),
        }
        self._pagina = None
        self._aviso = None

    def mostrar(self, clave: str):
        for k, p in self.paginas.items():
            p.pack_forget()
            self._nav[k].config(bg=C["lateral"], fg=C["lateral_texto"], font=(FUENTE, 11))
        self._nav[clave].config(bg=C["acento"], fg="white", font=(FUENTE, 11, "bold"))
        self._pagina = clave
        self.paginas[clave].pack(fill="both", expand=True)
        self.paginas[clave].al_mostrar()

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

    def estado(self, texto: str):
        self.lbl_estado.config(text=texto)

    # ------------------------------------------------------------- correo
    def password(self) -> str:
        return leer_password(self.cfg["correo"]["usuario"])

    def _ciclo_correo(self):
        c = self.cfg["correo"]
        if c.get("comprobar_auto") and c.get("imap_servidor") and self.password():
            self.comprobar_correo(silencioso=True)
        elif not c.get("imap_servidor"):
            self.estado("Correo sin configurar.\nVe a Configuración.")
        minutos = max(2, int(c.get("intervalo_min") or 10))
        self.after(minutos * 60 * 1000, self._ciclo_correo)

    def comprobar_correo(self, silencioso: bool = False):
        if self._comprobando:
            return
        if not self.cfg["correo"].get("imap_servidor") or not self.password():
            if not silencioso:
                messagebox.showinfo(NOMBRE_APP, "Primero configura el correo (servidor y contraseña) "
                                    "en Configuración > Correo.", parent=self)
                self.mostrar("config")
            return
        self._comprobando = True
        self.estado("Comprobando correo…")
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
            self.estado(f"Correo comprobado a las {datetime.now():%H:%M}")
            if procesados:
                facts = sum(len(d.facturas) for _, d in procesados)
                clis = sum(len(d.clientes) for _, d in procesados)
                self.notificar(f"✉ {len(procesados)} diario(s) nuevo(s) recibido(s)\n"
                               f"{facts} facturas de {clis} clientes listas para enviar.")
                self.paginas["diarios"].recargar(seleccionar=procesados[0][0])
                if self.state() == "iconic":
                    self.title(f"● Nuevo diario · {NOMBRE_APP}")
                    self.bell()
            elif not silencioso:
                self.notificar("No hay diarios nuevos en el correo.", "info")
            if fallidos:
                self.notificar("No se pudo leer:\n" + "\n".join(fallidos), "aviso", 10)

        def fallo(e):
            self._comprobando = False
            self.estado(f"Error de correo ({datetime.now():%H:%M})")
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


# ================================================================ páginas


class Pagina(tk.Frame):
    def __init__(self, master, app: App, titulo: str, subtitulo: str = ""):
        super().__init__(master, bg=C["fondo"])
        self.app = app
        cab = tk.Frame(self, bg=C["fondo"])
        cab.pack(fill="x", padx=28, pady=(22, 12))
        izq = tk.Frame(cab, bg=C["fondo"])
        izq.pack(side="left")
        tk.Label(izq, text=titulo, bg=C["fondo"], fg=C["texto"], font=(FUENTE, 19, "bold")).pack(anchor="w")
        if subtitulo:
            tk.Label(izq, text=subtitulo, bg=C["fondo"], fg=C["suave"], font=(FUENTE, 10)).pack(anchor="w")
        self.acciones = tk.Frame(cab, bg=C["fondo"])
        self.acciones.pack(side="right")

    def al_mostrar(self):
        pass


# ------------------------------------------------------------------ diarios


class PaginaDiarios(Pagina):
    def __init__(self, master, app):
        super().__init__(master, app, "Diarios de facturación",
                         "Los diarios que llegan al correo se procesan solos. Elige un cliente para ver, imprimir o enviar su listado.")
        Boton(self.acciones, "Importar diario", self.importar, icono="+").pack(side="right", padx=(8, 0))
        Boton(self.acciones, "Comprobar correo", lambda: app.comprobar_correo(), "primario", icono="⟳").pack(side="right")

        cuerpo = ttk.PanedWindow(self, orient="horizontal")
        cuerpo.pack(fill="both", expand=True, padx=28, pady=(0, 24))

        # --- lista de diarios
        izq = Tarjeta(cuerpo, "Diarios recibidos")
        izq.configure(width=330)
        marco, self.tv_diarios = tabla(izq, [("periodo", "Periodo", 130, "w"),
                                             ("recibido", "Recibido", 110, "w"),
                                             ("facturas", "Fact.", 44, "e")], altura=20)
        marco.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self.tv_diarios.bind("<<TreeviewSelect>>", lambda e: self._diario_elegido())
        pie = tk.Frame(izq, bg=C["tarjeta"])
        pie.pack(fill="x", padx=12, pady=(0, 12))
        Boton(pie, "Ver original", self.ver_original).pack(side="left")
        Boton(pie, "Eliminar", self.eliminar_diario, "peligro").pack(side="right")
        cuerpo.add(izq, weight=1)

        # --- detalle
        der = tk.Frame(cuerpo, bg=C["fondo"])
        cuerpo.add(der, weight=4)

        self.t_cli = Tarjeta(der)
        self.t_cli.pack(fill="both", expand=True, padx=(16, 0))
        cab = tk.Frame(self.t_cli, bg=C["tarjeta"])
        cab.pack(fill="x", padx=16, pady=(14, 4))
        self.lbl_diario = tk.Label(cab, text="Selecciona un diario", bg=C["tarjeta"], fg=C["texto"],
                                   font=(FUENTE, 13, "bold"))
        self.lbl_diario.pack(side="left")
        self.lbl_diario_info = tk.Label(cab, text="", bg=C["tarjeta"], fg=C["suave"], font=(FUENTE, 9))
        self.lbl_diario_info.pack(side="left", padx=12)
        self.lbl_avisos = tk.Label(self.t_cli, text="", bg=C["aviso_fondo"], fg=C["aviso"],
                                   font=(FUENTE, 9), anchor="w", justify="left", padx=10, pady=6)

        barra = tk.Frame(self.t_cli, bg=C["tarjeta"])
        barra.pack(fill="x", padx=16, pady=(6, 8))
        self.botones = [
            Boton(barra, "Ver", self.ver, "primario"),
            Boton(barra, "Imprimir", self.imprimir),
            Boton(barra, "Enviar por email", self.enviar, icono="✉"),
            Boton(barra, "Excel", lambda: self.exportar("xlsx"), icono="⬇"),
            Boton(barra, "CSV", lambda: self.exportar("csv"), icono="⬇"),
        ]
        for b in self.botones:
            b.pack(side="left", padx=(0, 6))
        Boton(barra, "Abrir carpeta", self.abrir_carpeta).pack(side="right")
        Boton(barra, "Enviar a todos", self.enviar_todos, icono="✉").pack(side="right", padx=6)

        marco, self.tv_cli = tabla(self.t_cli, [
            ("cliente", "Cliente", 220, "w"), ("nif", "NIF/CIF", 92, "w"), ("n", "Fact.", 44, "e"),
            ("base", "Base", 92, "e"), ("total", "Total", 100, "e"),
            ("email", "Email", 170, "w"), ("enviado", "Enviado", 100, "w")], altura=9)
        marco.pack(fill="both", expand=True, padx=16)
        self.tv_cli.bind("<<TreeviewSelect>>", lambda e: self._cliente_elegido())
        self.tv_cli.bind("<Double-1>", lambda e: self.ver())

        tk.Label(self.t_cli, text="FACTURAS DEL CLIENTE", bg=C["tarjeta"], fg=C["acento"],
                 font=(FUENTE, 8, "bold")).pack(anchor="w", padx=16, pady=(12, 4))
        marco, self.tv_fact = tabla(self.t_cli, [
            ("tipo", "Tipo", 95, "w"), ("num", "Nº factura", 110, "w"), ("fecha", "Fecha", 86, "w"),
            ("base", "Base", 90, "e"), ("iva", "IVA", 80, "e"), ("re", "Recargo", 76, "e"),
            ("irpf", "IRPF", 76, "e"), ("total", "Total", 96, "e"), ("aviso", "Observaciones", 200, "w")],
            altura=7)
        marco.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self.tv_fact.bind("<Button-3>", self._menu_factura)
        self.tv_fact.bind("<Double-1>", self._menu_factura)

        self.vacio = tk.Label(self.t_cli, text="", bg=C["tarjeta"], fg=C["suave"], font=(FUENTE, 11))
        self.ident = None
        self.diario = None

    def al_mostrar(self):
        self.recargar()

    # ----------------------------------------------------------- carga
    def recargar(self, seleccionar=None):
        actual = seleccionar or self.ident
        self.tv_diarios.delete(*self.tv_diarios.get_children())
        lista = self.app.almacen.lista_diarios()
        for i, m in enumerate(lista):
            rec = datetime.fromisoformat(m["recibido"]).strftime("%d/%m/%Y %H:%M")
            desde = date.fromisoformat(m["desde"]) if m["desde"] else None
            hasta = date.fromisoformat(m["hasta"]) if m["hasta"] else None
            periodo = texto_periodo(desde, hasta) or "—"
            tags = ("par",) if i % 2 else ()
            if m.get("avisos"):
                tags += ("aviso",)
            self.tv_diarios.insert("", "end", iid=m["id"], values=(periodo, rec, m["num_facturas"]), tags=tags)
        if not lista:
            self.ident, self.diario = None, None
            self.lbl_diario.config(text="Todavía no hay diarios")
            self.lbl_diario_info.config(text="Configura el correo o pulsa «Importar diario» para cargar uno.")
            self._pintar_clientes()
            return
        if actual not in self.tv_diarios.get_children():
            actual = lista[0]["id"]
        self.tv_diarios.selection_set(actual)
        self.tv_diarios.see(actual)
        self._diario_elegido(forzar=True)

    def _diario_elegido(self, forzar=False):
        sel = self.tv_diarios.selection()
        if not sel:
            return
        if sel[0] == self.ident and not forzar:
            return
        self.ident = sel[0]
        self.diario = self.app.almacen.diario(self.ident)
        meta = self.app.almacen.meta(self.ident)
        periodo = texto_periodo(self.diario.fecha_desde, self.diario.fecha_hasta)
        self.lbl_diario.config(text=f"Diario {periodo}" if periodo else "Diario")
        origen = "recibido por correo" if meta.get("origen") == "correo" else "importado a mano"
        self.lbl_diario_info.config(text=f"{len(self.diario.facturas)} facturas · {len(self.diario.clientes)} clientes · "
                                         f"{meta.get('archivo', '')} ({origen})")
        if self.diario.avisos:
            self.lbl_avisos.config(text="⚠  " + "\n⚠  ".join(self.diario.avisos))
            self.lbl_avisos.pack(fill="x", padx=16, pady=(4, 0), after=self.lbl_diario.master)
        else:
            self.lbl_avisos.pack_forget()
        self._pintar_clientes()

    def _pintar_clientes(self):
        seleccion = self.tv_cli.selection()
        self.tv_cli.delete(*self.tv_cli.get_children())
        self.tv_fact.delete(*self.tv_fact.get_children())
        if not self.diario:
            return
        maestro = self.app.almacen.clientes()
        envios = self.app.almacen.meta(self.ident).get("envios", {})
        filas = []
        for clave, c in self.diario.clientes.items():
            c = maestro.get(clave, c)
            fs = self.diario.facturas_de(clave)
            filas.append((c.nombre.lower(), clave, c, fs))
        for i, (_, clave, c, fs) in enumerate(sorted(filas)):
            env = envios.get(clave)
            enviado = datetime.fromisoformat(env[-1]["fecha"]).strftime("%d/%m %H:%M") if env else ""
            tags = ("par",) if i % 2 else ()
            if env:
                tags += ("enviado",)
            elif not c.email:
                tags += ("sinemail",)
            if any(f.aviso for f in fs):
                tags += ("aviso",)
            self.tv_cli.insert("", "end", iid=clave, tags=tags, values=(
                c.nombre, c.nif, len(fs), eur(sum(f.base for f in fs)), eur(sum(f.importe_total for f in fs)),
                c.email or "— sin email —", ("✔ " + enviado) if enviado else ""))
        hijos = self.tv_cli.get_children()
        objetivo = [s for s in seleccion if s in hijos] or list(hijos[:1])
        if objetivo:
            self.tv_cli.selection_set(objetivo)
            self._cliente_elegido()

    def _cliente_elegido(self):
        self.tv_fact.delete(*self.tv_fact.get_children())
        clave = self._clave()
        if not clave or not self.diario:
            return
        for i, f in enumerate(self.diario.facturas_de(clave)):
            tags = ("par",) if i % 2 else ()
            if f.aviso:
                tags += ("aviso",)
            ivas = ", ".join(sorted({f"{l.iva_pct:g}%" for l in f.lineas}))
            self.tv_fact.insert("", "end", iid=f.numero + "|" + str(i), tags=tags, values=(
                f.tipo, f.numero, fecha_es(f.fecha), eur(f.base), f"{eur(f.cuota_iva)}",
                eur(f.cuota_re) if f.cuota_re else "", ("-" + eur(f.irpf)) if f.irpf else "",
                eur(f.importe_total), f.aviso or (f"IVA {ivas}" if len(f.lineas) > 1 else (
                    "Varios tipos de IVA" if f.lineas and f.lineas[0].iva_pct not in IVA_TIPOS else ""))))

    def _clave(self):
        sel = self.tv_cli.selection()
        return sel[0] if sel else None

    def _menu_factura(self, evento):
        fila = self.tv_fact.identify_row(evento.y)
        if not fila:
            return
        self.tv_fact.selection_set(fila)
        numero = fila.rsplit("|", 1)[0]
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label=f"Factura {numero} — cambiar tipo:", state="disabled")
        for t in TIPOS_FACTURA:
            menu.add_command(label=f"   {t}", command=lambda t=t: self._cambiar_tipo(numero, t))
        menu.tk_popup(evento.x_root, evento.y_root)

    def _cambiar_tipo(self, numero, tipo):
        for f in self.diario.facturas:
            if f.numero == numero:
                f.tipo = tipo
        self.app.almacen.guardar_diario(self.ident, self.diario)
        self._cliente_elegido()

    # -------------------------------------------------------- acciones
    def _necesita_cliente(self):
        if not self.diario:
            messagebox.showinfo(NOMBRE_APP, "Primero selecciona un diario.", parent=self)
            return None
        clave = self._clave()
        if not clave:
            messagebox.showinfo(NOMBRE_APP, "Selecciona un cliente de la lista.", parent=self)
        return clave

    def _pdf(self, clave):
        return self.app.almacen.generar_pdf(self.ident, self.diario, clave, self.app.cfg)

    def ver(self):
        clave = self._necesita_cliente()
        if clave:
            VisorPDF(self.app, self._pdf(clave), self, clave)

    def imprimir(self, clave=None):
        clave = clave or self._necesita_cliente()
        if clave:
            imprimir_archivo(self._pdf(clave))
            self.app.notificar("Enviado a la impresora predeterminada.", "info", 4)

    def enviar(self, clave=None):
        clave = clave or self._necesita_cliente()
        if clave:
            DialogoEnvio(self.app, self, clave)

    def exportar(self, formato):
        clave = self._necesita_cliente()
        if not clave:
            return
        if formato == "xlsx":
            ruta = self.app.almacen.generar_excel(self.ident, self.diario, clave, self.app.cfg)
        else:
            ruta = self.app.almacen.generar_csv(self.ident, self.diario, clave, self.app.cfg)
        self.app.notificar(f"Guardado: {ruta.name}", "ok", 4)
        abrir_archivo(ruta)

    def abrir_carpeta(self):
        if self.diario:
            abrir_archivo(self.app.almacen.carpeta_salida(self.ident, self.diario))
        else:
            abrir_archivo(ruta_documentos())

    def enviar_todos(self):
        if not self.diario:
            return
        maestro = self.app.almacen.clientes()
        envios = self.app.almacen.meta(self.ident).get("envios", {})
        con, sin, ya = [], [], []
        for clave, c in self.diario.clientes.items():
            c = maestro.get(clave, c)
            if clave in envios:
                ya.append(c)
            elif c.email:
                con.append(c)
            else:
                sin.append(c)
        if not con:
            messagebox.showinfo(NOMBRE_APP, "No hay clientes pendientes con email. "
                                "Añade los emails en la pestaña Clientes.", parent=self)
            return
        texto = f"Se enviará el listado a {len(con)} cliente(s):\n\n" + \
                "\n".join(f"  • {c.nombre}  <{c.email}>" for c in con[:15])
        if len(con) > 15:
            texto += f"\n  … y {len(con) - 15} más"
        if ya:
            texto += f"\n\n{len(ya)} ya enviado(s) antes: no se repiten."
        if sin:
            texto += f"\n{len(sin)} sin email: se omiten."
        if not messagebox.askyesno(NOMBRE_APP, texto + "\n\n¿Enviar ahora?", parent=self):
            return
        cfg, pw, almacen, ident, diario = self.app.cfg, self.app.password(), self.app.almacen, self.ident, self.diario
        if not pw:
            messagebox.showwarning(NOMBRE_APP, "Falta la contraseña del correo en Configuración.", parent=self)
            return

        def trabajo():
            from .correo import enviar_email
            ok, mal = 0, []
            for c in con:
                try:
                    asunto, cuerpo = textos_envio(cfg, diario, c)
                    adj = [almacen.generar_pdf(ident, diario, c.clave, cfg)]
                    if cfg["envio"].get("adjuntar_excel"):
                        adj.append(almacen.generar_excel(ident, diario, c.clave, cfg))
                    if cfg["envio"].get("adjuntar_csv"):
                        adj.append(almacen.generar_csv(ident, diario, c.clave, cfg))
                    para = [x.strip() for x in c.email.replace(";", ",").split(",") if x.strip()]
                    bcc = [cfg["correo"]["usuario"]] if cfg["correo"].get("copia_a_mi") else []
                    enviar_email(cfg, pw, para, asunto, cuerpo, adj, bcc)
                    almacen.registrar_envio(ident, c.clave, para)
                    ok += 1
                except Exception as e:  # noqa: BLE001
                    mal.append(f"{c.nombre}: {e}")
            return ok, mal

        def fin(res):
            ok, mal = res
            self._pintar_clientes()
            if mal:
                messagebox.showwarning(NOMBRE_APP, f"Enviados: {ok}\nCon error:\n" + "\n".join(mal), parent=self)
            else:
                self.app.notificar(f"✔ Listados enviados a {ok} cliente(s).")

        self.app.notificar(f"Enviando {len(con)} correo(s)…", "info", 3)
        self.app.en_fondo(trabajo, fin)

    def importar(self):
        rutas = filedialog.askopenfilenames(parent=self, title="Selecciona el diario de facturación",
                                            filetypes=[("Diarios", "*.pdf *.xlsx *.xlsm *.csv"),
                                                       ("Todos", "*.*")])
        if not rutas:
            return
        ultimo = None
        for r in rutas:
            try:
                ultimo, d = self.app.almacen.procesar(r, self.app.cfg, "manual")
                tipo = "aviso" if d.avisos else "ok"
                self.app.notificar(f"{Path(r).name}: {len(d.facturas)} facturas de {len(d.clientes)} clientes."
                                   + ("\n" + "\n".join(d.avisos) if d.avisos else ""), tipo)
            except Exception as e:  # noqa: BLE001
                self.app.error(f"No se pudo leer {Path(r).name}:\n{e}")
        if ultimo:
            self.recargar(seleccionar=ultimo)

    def ver_original(self):
        if self.ident:
            abrir_archivo(self.app.almacen.ruta_original(self.ident))

    def eliminar_diario(self):
        if not self.ident:
            return
        if messagebox.askyesno(NOMBRE_APP, "¿Eliminar este diario del programa?\n"
                               "(Los PDF ya generados en Documentos no se borran.)", parent=self):
            self.app.almacen.eliminar_diario(self.ident)
            self.ident = None
            self.recargar()


def textos_envio(cfg, diario, cliente: Cliente) -> tuple[str, str]:
    fs = diario.facturas_de(cliente.clave)
    emp = cfg["empresa"]
    datos = _Seguro(
        cliente=cliente.nombre, periodo=texto_periodo(diario.fecha_desde, diario.fecha_hasta),
        num_facturas=len(fs), total=eur(sum(f.importe_total for f in fs)),
        empresa=emp.get("nombre", ""), empresa_telefono=emp.get("telefono", ""),
        empresa_email=emp.get("email", ""))
    asunto = cfg["envio"]["asunto"].format_map(datos)
    cuerpo = cfg["envio"]["cuerpo"].format_map(datos).rstrip()
    return asunto, cuerpo


# ------------------------------------------------------------------ visor


class VisorPDF(tk.Toplevel):
    def __init__(self, app: App, ruta: Path, pagina: PaginaDiarios, clave: str):
        super().__init__(app)
        self.app, self.ruta, self.pagina, self.clave = app, Path(ruta), pagina, clave
        self.title(f"{self.ruta.name} · {NOMBRE_APP}")
        self.geometry("900x900")
        self.configure(bg="#525659")
        barra = tk.Frame(self, bg=C["tarjeta"])
        barra.pack(fill="x")
        tk.Label(barra, text=self.ruta.stem, bg=C["tarjeta"], fg=C["texto"],
                 font=(FUENTE, 11, "bold")).pack(side="left", padx=16, pady=10)
        Boton(barra, "Enviar por email", lambda: pagina.enviar(clave), "primario", icono="✉").pack(side="right", padx=(6, 12), pady=8)
        Boton(barra, "Imprimir", lambda: pagina.imprimir(clave)).pack(side="right", padx=6)
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
        for i in range(len(pdf)):
            pag = pdf[i]
            w_pt = pag.get_width()
            img = pag.render(scale=objetivo / w_pt).to_pil()
            foto = ImageTk.PhotoImage(img)
            self._imgs.append(foto)
            x = max(ancho / 2, img.width / 2 + 20)
            self.canvas.create_rectangle(x - img.width / 2 + 3, y + 3, x + img.width / 2 + 3,
                                         y + img.height + 3, fill="#3b3e41", outline="")
            self.canvas.create_image(x, y, image=foto, anchor="n")
            y += img.height + 20
        pdf.close()
        self.canvas.configure(scrollregion=(0, 0, max(ancho, objetivo + 40), y))


# ----------------------------------------------------------------- envío


class DialogoEnvio(tk.Toplevel):
    def __init__(self, app: App, pagina: PaginaDiarios, clave: str):
        super().__init__(app)
        self.app, self.pagina, self.clave = app, pagina, clave
        self.cliente = app.almacen.cliente(clave, pagina.diario)
        self.title("Enviar listado por email")
        self.configure(bg=C["tarjeta"])
        self.geometry("640x600")
        self.transient(app)
        self.grab_set()

        tk.Label(self, text="Enviar listado por email", bg=C["tarjeta"], fg=C["texto"],
                 font=(FUENTE, 15, "bold")).pack(anchor="w", padx=22, pady=(18, 0))
        tk.Label(self, text=self.cliente.nombre, bg=C["tarjeta"], fg=C["suave"],
                 font=(FUENTE, 10)).pack(anchor="w", padx=22)

        f = tk.Frame(self, bg=C["tarjeta"])
        f.pack(fill="both", expand=True, padx=6, pady=10)
        f.columnconfigure(1, weight=1)
        asunto, cuerpo = textos_envio(app.cfg, pagina.diario, self.cliente)
        self.v_para = tk.StringVar(value=self.cliente.email)
        self.v_asunto = tk.StringVar(value=asunto)
        e = campo(f, "Para", self.v_para, 0, ancho=50)
        tk.Label(f, text="Varios destinatarios separados por coma", bg=C["tarjeta"], fg="#9CA3AF",
                 font=(FUENTE, 8)).grid(row=1, column=1, sticky="w")
        self.v_guardar = tk.BooleanVar(value=not self.cliente.email)
        ttk.Checkbutton(f, text="Guardar este email en la ficha del cliente", variable=self.v_guardar).grid(
            row=2, column=1, sticky="w", pady=(0, 6))
        campo(f, "Asunto", self.v_asunto, 3, ancho=50)
        tk.Label(f, text="Mensaje", bg=C["tarjeta"], fg=C["suave"], font=(FUENTE, 9)).grid(
            row=4, column=0, sticky="nw", padx=(16, 8), pady=6)
        self.txt = tk.Text(f, height=10, wrap="word", font=(FUENTE, 10), relief="flat",
                           highlightthickness=1, highlightbackground=C["borde"], padx=8, pady=6)
        self.txt.grid(row=4, column=1, sticky="nsew", padx=(0, 16), pady=6)
        self.txt.insert("1.0", cuerpo)
        f.rowconfigure(4, weight=1)

        adj = tk.Frame(f, bg=C["tarjeta"])
        adj.grid(row=5, column=1, sticky="w", pady=(4, 0))
        tk.Label(f, text="Adjuntos", bg=C["tarjeta"], fg=C["suave"], font=(FUENTE, 9)).grid(
            row=5, column=0, sticky="w", padx=(16, 8))
        self.v_pdf = tk.BooleanVar(value=True)
        self.v_xlsx = tk.BooleanVar(value=app.cfg["envio"].get("adjuntar_excel", False))
        self.v_csv = tk.BooleanVar(value=app.cfg["envio"].get("adjuntar_csv", False))
        for txt, v in [("PDF", self.v_pdf), ("Excel", self.v_xlsx), ("CSV", self.v_csv)]:
            ttk.Checkbutton(adj, text=txt, variable=v).pack(side="left", padx=(0, 14))
        self.v_copia = tk.BooleanVar(value=app.cfg["correo"].get("copia_a_mi", True))
        ttk.Checkbutton(f, text=f"Enviarme copia oculta ({app.cfg['correo']['usuario']})",
                        variable=self.v_copia).grid(row=6, column=1, sticky="w", pady=6)

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
        pw = self.app.password()
        if not pw or not self.app.cfg["correo"].get("smtp_servidor"):
            messagebox.showwarning(NOMBRE_APP, "Configura antes el correo (servidor SMTP y contraseña).", parent=self)
            return
        if not (self.v_pdf.get() or self.v_xlsx.get() or self.v_csv.get()):
            messagebox.showwarning(NOMBRE_APP, "Marca al menos un adjunto.", parent=self)
            return
        if self.v_guardar.get():
            self.cliente.email = ", ".join(para)
            self.app.almacen.guardar_cliente(self.cliente)
        cfg, almacen, pagina, clave = self.app.cfg, self.app.almacen, self.pagina, self.clave
        ident, diario = pagina.ident, pagina.diario
        asunto, cuerpo = self.v_asunto.get(), self.txt.get("1.0", "end").strip()
        quiere = (self.v_pdf.get(), self.v_xlsx.get(), self.v_csv.get())
        bcc = [cfg["correo"]["usuario"]] if self.v_copia.get() else []
        self.b_enviar.activar(False)
        self.lbl.config(text="Enviando…")

        def trabajo():
            from .correo import enviar_email
            adj = []
            if quiere[0]:
                adj.append(almacen.generar_pdf(ident, diario, clave, cfg))
            if quiere[1]:
                adj.append(almacen.generar_excel(ident, diario, clave, cfg))
            if quiere[2]:
                adj.append(almacen.generar_csv(ident, diario, clave, cfg))
            enviar_email(cfg, pw, para, asunto, cuerpo, adj, bcc)
            almacen.registrar_envio(ident, clave, para)

        def fin(_):
            self.app.notificar(f"✔ Listado enviado a {', '.join(para)}")
            pagina._pintar_clientes()
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
        super().__init__(master, app, "Clientes",
                         "Se crean solos al leer los diarios. Completa su email y dirección para que salgan en el PDF.")
        cuerpo = tk.Frame(self, bg=C["fondo"])
        cuerpo.pack(fill="both", expand=True, padx=28, pady=(0, 24))
        izq = Tarjeta(cuerpo)
        busq = tk.Frame(izq, bg=C["tarjeta"])
        busq.pack(fill="x", padx=16, pady=14)
        tk.Label(busq, text="Buscar", bg=C["tarjeta"], fg=C["suave"], font=(FUENTE, 9)).pack(side="left")
        self.v_buscar = tk.StringVar()
        self.v_buscar.trace_add("write", lambda *a: self.pintar())
        ttk.Entry(busq, textvariable=self.v_buscar, width=40).pack(side="left", padx=8)
        self.v_solo = tk.BooleanVar()
        ttk.Checkbutton(busq, text="Solo sin email", variable=self.v_solo, command=self.pintar).pack(side="left", padx=8)
        marco, self.tv = tabla(izq, [("nombre", "Cliente", 280, "w"), ("nif", "NIF/CIF", 110, "w"),
                                     ("email", "Email", 220, "w"), ("tel", "Teléfono", 110, "w"),
                                     ("pob", "Población", 140, "w")], altura=18)
        marco.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self.tv.bind("<<TreeviewSelect>>", lambda e: self.cargar())

        der = Tarjeta(cuerpo, "Ficha del cliente")
        der.pack(side="right", fill="y", padx=(16, 0))
        izq.pack(side="left", fill="both", expand=True)
        der.columnconfigure(1, weight=1)
        frm = tk.Frame(der, bg=C["tarjeta"])
        frm.pack(fill="both")
        self.vars = {k: tk.StringVar() for k, _ in self.CAMPOS}
        for i, (k, et) in enumerate(self.CAMPOS):
            campo(frm, et, self.vars[k], i, ancho=26)
        Boton(der, "Guardar cambios", self.guardar, "primario").pack(anchor="e", padx=16, pady=16)
        self.clave = None

    def al_mostrar(self):
        self.pintar()

    def pintar(self):
        sel = self.clave
        self.tv.delete(*self.tv.get_children())
        q = self.v_buscar.get().lower().strip()
        for i, c in enumerate(sorted(self.app.almacen.clientes().values(), key=lambda c: c.nombre.lower())):
            if q and q not in f"{c.nombre} {c.nif} {c.email} {c.codigo}".lower():
                continue
            if self.v_solo.get() and c.email:
                continue
            self.tv.insert("", "end", iid=c.clave, values=(c.nombre, c.nif, c.email, c.telefono, c.poblacion),
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
        super().__init__(master, app, "Configuración", "Datos de la empresa, correo y actualizaciones.")
        Boton(self.acciones, "Guardar configuración", self.guardar, "primario", icono="✔").pack(side="right")

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

    def _tarjeta(self, titulo):
        t = Tarjeta(self.interior, titulo)
        t.pack(fill="x", pady=(0, 14))
        f = tk.Frame(t, bg=C["tarjeta"])
        f.pack(fill="x", pady=(0, 12))
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

        # Empresa
        f = self._tarjeta("Datos de la empresa (aparecen en el PDF)")
        filas = [("nombre", "Nombre"), ("cif", "CIF"), ("direccion", "Dirección"), ("cp", "Código postal"),
                 ("poblacion", "Población"), ("provincia", "Provincia"), ("telefono", "Teléfono"),
                 ("email", "Email"), ("web", "Web")]
        for i, (k, et) in enumerate(filas):
            campo(f, et, var("empresa", k), i // 2, col=(i % 2) * 2, ancho=30)
        fila = len(filas) // 2 + 1
        tk.Label(f, text="Logo", bg=C["tarjeta"], fg=C["suave"], font=(FUENTE, 9)).grid(
            row=fila, column=0, sticky="w", padx=(16, 8), pady=4)
        lf = tk.Frame(f, bg=C["tarjeta"])
        lf.grid(row=fila, column=1, columnspan=3, sticky="w")
        self.v_logo = var("empresa", "logo")
        self.lbl_logo = tk.Label(lf, text=self._texto_logo(), bg=C["tarjeta"], fg=C["texto"], font=(FUENTE, 9))
        self.lbl_logo.pack(side="left")
        Boton(lf, "Cambiar…", self._elegir_logo).pack(side="left", padx=8)
        Boton(lf, "Usar el incluido", lambda: (self.v_logo.set(""), self.lbl_logo.config(text=self._texto_logo()))).pack(side="left")
        tk.Label(f, text="Color", bg=C["tarjeta"], fg=C["suave"], font=(FUENTE, 9)).grid(
            row=fila + 1, column=0, sticky="w", padx=(16, 8), pady=4)
        self.v_color = var("empresa", "color")
        self.muestra = tk.Label(f, text="      ", bg=self.v_color.get() or C["acento"], cursor="hand2",
                                highlightthickness=1, highlightbackground=C["borde"])
        self.muestra.grid(row=fila + 1, column=1, sticky="w", pady=4)
        self.muestra.bind("<Button-1>", lambda e: self._elegir_color())

        # Correo
        f = self._tarjeta("Correo (recepción de diarios y envío a clientes)")
        campo(f, "Usuario / email", var("correo", "usuario"), 0, ancho=30)
        self.v_pw = tk.StringVar(value=leer_password(cfg["correo"]["usuario"]))
        campo(f, "Contraseña", self.v_pw, 0, col=2, ancho=24, mostrar="•")
        campo(f, "Servidor IMAP", var("correo", "imap_servidor"), 1, ancho=30, ayuda="")
        campo(f, "Puerto IMAP", var("correo", "imap_puerto"), 1, col=2, ancho=8)
        campo(f, "Servidor SMTP", var("correo", "smtp_servidor"), 2, ancho=30)
        campo(f, "Puerto SMTP", var("correo", "smtp_puerto"), 2, col=2, ancho=8)
        tk.Label(f, text="Seguridad SMTP", bg=C["tarjeta"], fg=C["suave"], font=(FUENTE, 9)).grid(
            row=3, column=2, sticky="w", padx=(16, 8))
        ttk.Combobox(f, textvariable=var("correo", "smtp_seguridad"), values=["SSL", "STARTTLS", "Ninguna"],
                     state="readonly", width=12).grid(row=3, column=3, sticky="w")
        campo(f, "Carpeta de diarios", var("correo", "carpeta"), 3, ancho=30)
        campo(f, "Nombre remitente", var("correo", "remitente_nombre"), 4, ancho=30)
        campo(f, "Revisar cada (min)", var("correo", "intervalo_min"), 4, col=2, ancho=8)
        ops = tk.Frame(f, bg=C["tarjeta"])
        ops.grid(row=5, column=0, columnspan=4, sticky="w", padx=16, pady=(8, 0))
        ttk.Checkbutton(ops, text="Revisar el correo automáticamente", variable=var("correo", "comprobar_auto", tk.BooleanVar)).pack(side="left")
        ttk.Checkbutton(ops, text="Enviarme copia oculta de cada envío", variable=var("correo", "copia_a_mi", tk.BooleanVar)).pack(side="left", padx=20)
        Boton(ops, "Probar conexión", self._probar).pack(side="left", padx=10)
        tk.Label(f, text="Tu proveedor de correo te indica los servidores (IONOS: imap.ionos.es puerto 993 y smtp.ionos.es puerto 465 con SSL; "
                         "si no conecta, prueba imap.ionos.com y smtp.ionos.com). La contraseña se guarda cifrada en Windows.",
                 bg=C["tarjeta"], fg="#9CA3AF", font=(FUENTE, 8), wraplength=900, justify="left").grid(
            row=6, column=0, columnspan=4, sticky="w", padx=16, pady=(6, 0))

        # Mensaje
        f = self._tarjeta("Mensaje para los clientes")
        campo(f, "Asunto", var("envio", "asunto"), 0, ancho=70)
        tk.Label(f, text="Texto", bg=C["tarjeta"], fg=C["suave"], font=(FUENTE, 9)).grid(
            row=1, column=0, sticky="nw", padx=(16, 8), pady=6)
        self.txt_cuerpo = tk.Text(f, height=8, wrap="word", font=(FUENTE, 10), relief="flat",
                                  highlightthickness=1, highlightbackground=C["borde"], padx=8, pady=6)
        self.txt_cuerpo.grid(row=1, column=1, columnspan=3, sticky="we", padx=(0, 16), pady=6)
        self.txt_cuerpo.insert("1.0", cfg["envio"]["cuerpo"])
        tk.Label(f, text="Puedes usar: {cliente} {periodo} {num_facturas} {total} {empresa} {empresa_telefono}",
                 bg=C["tarjeta"], fg="#9CA3AF", font=(FUENTE, 8)).grid(row=2, column=1, columnspan=3, sticky="w")
        ops = tk.Frame(f, bg=C["tarjeta"])
        ops.grid(row=3, column=1, columnspan=3, sticky="w", pady=(6, 0))
        tk.Label(ops, text="Adjuntar además por defecto:", bg=C["tarjeta"], fg=C["suave"], font=(FUENTE, 9)).pack(side="left")
        ttk.Checkbutton(ops, text="Excel", variable=var("envio", "adjuntar_excel", tk.BooleanVar)).pack(side="left", padx=10)
        ttk.Checkbutton(ops, text="CSV", variable=var("envio", "adjuntar_csv", tk.BooleanVar)).pack(side="left")

        # Tipos
        f = self._tarjeta("Tipo de factura según la serie")
        tk.Label(f, text="Si el diario no indica el tipo (contado, crédito…), se deduce por el inicio del número "
                         "o serie de la factura. Una regla por línea: SERIE = Tipo",
                 bg=C["tarjeta"], fg=C["suave"], font=(FUENTE, 9), wraplength=900, justify="left").grid(
            row=0, column=0, columnspan=4, sticky="w", padx=16)
        self.txt_series = tk.Text(f, height=6, width=40, font=("Consolas" if os.name == "nt" else "DejaVu Sans Mono", 10),
                                  relief="flat", highlightthickness=1, highlightbackground=C["borde"], padx=8, pady=6)
        self.txt_series.grid(row=1, column=0, columnspan=2, sticky="w", padx=16, pady=6)
        self.txt_series.insert("1.0", "\n".join(f"{k} = {v}" for k, v in cfg["tipos"]["series"].items()))
        tk.Label(f, text="Tipo si no coincide ninguna", bg=C["tarjeta"], fg=C["suave"], font=(FUENTE, 9)).grid(
            row=1, column=2, sticky="nw", padx=(16, 8), pady=10)
        ttk.Combobox(f, textvariable=var("tipos", "por_defecto"), values=TIPOS_FACTURA, state="readonly",
                     width=16).grid(row=1, column=3, sticky="nw", pady=10)

        # Actualizaciones
        f = self._tarjeta("Actualizaciones (GitHub)")
        campo(f, "Repositorio", var("actualizaciones", "repo"), 0, ancho=40, ayuda="usuario/repositorio")
        campo(f, "Token (solo si es privado)", var("actualizaciones", "token"), 1, ancho=40, mostrar="•")
        ops = tk.Frame(f, bg=C["tarjeta"])
        ops.grid(row=2, column=0, columnspan=4, sticky="w", padx=16, pady=(8, 0))
        ttk.Checkbutton(ops, text="Buscar actualizaciones al abrir el programa",
                        variable=var("actualizaciones", "comprobar_al_iniciar", tk.BooleanVar)).pack(side="left")
        Boton(ops, f"Buscar ahora (instalada: {VERSION})", lambda: self.app.buscar_actualizacion()).pack(side="left", padx=16)

        # General
        f = self._tarjeta("General")
        ops = tk.Frame(f, bg=C["tarjeta"])
        ops.grid(row=0, column=0, columnspan=4, sticky="w", padx=16)
        ttk.Checkbutton(ops, text="Abrir el programa al iniciar Windows (minimizado, revisando el correo)",
                        variable=var("general", "iniciar_con_windows", tk.BooleanVar)).pack(side="left")
        Boton(ops, "Abrir carpeta de listados", lambda: abrir_archivo(ruta_documentos())).pack(side="left", padx=16)

    def _texto_logo(self):
        return Path(self.v_logo.get()).name if self.v_logo.get() else "Logo de Ferretería LH (incluido)"

    def _elegir_logo(self):
        r = filedialog.askopenfilename(parent=self, filetypes=[("Imágenes", "*.png *.jpg *.jpeg")])
        if r:
            self.v_logo.set(r)
            self.lbl_logo.config(text=self._texto_logo())

    def _elegir_color(self):
        c = colorchooser.askcolor(self.v_color.get(), parent=self)[1]
        if c:
            self.v_color.set(c)
            self.muestra.config(bg=c)

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
        _iniciar_con_windows(cfg["general"].get("iniciar_con_windows", False))
        self.app.title(f"{NOMBRE_APP} · {cfg['empresa']['nombre']}")
        self.app.notificar("✔ Configuración guardada", "ok", 3)

    def _probar(self):
        cfg = self._volcar()
        pw = self.v_pw.get()
        self.app.notificar("Probando conexión…", "info", 3)

        def trabajo():
            from .correo import probar_conexion
            return probar_conexion(cfg, pw)
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
            exe = sys.executable if getattr(sys, "frozen", False) else f'"{sys.executable}" "{Path(sys.argv[0]).resolve()}"'
            valor = f'"{exe}" --minimizado' if getattr(sys, "frozen", False) else f"{exe} --minimizado"
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
        tk.Label(self, text="⬆  Nueva versión disponible", bg=C["tarjeta"], fg=C["texto"],
                 font=(FUENTE, 15, "bold")).pack(anchor="w", padx=22, pady=(20, 2))
        tk.Label(self, text=f"Instalada: {VERSION}   →   Nueva: {info.version}", bg=C["tarjeta"],
                 fg=C["suave"], font=(FUENTE, 10)).pack(anchor="w", padx=22)
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
