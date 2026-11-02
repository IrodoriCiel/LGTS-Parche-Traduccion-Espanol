"""Parche de la traducción al español de Little Goody Two Shoes (interfaz gráfica).

Aplica el parche sobre el juego que tiene el usuario: no distribuye archivos del
juego. Se empaqueta con PyInstaller (ver app/instalador.spec): un .exe para
Windows y un ejecutable para Linux (Steam Deck, donde el juego corre con Proton).

La ventana es app/ui/index.html mostrada con pywebview: motor Edge/WebView2 en
Windows y Qt WebEngine (va dentro del ejecutable) en Linux. Si falla, se abre
una ventana sencilla en tkinter.

  instalador.exe                      abre la ventana
  instalador.exe --estado  [--ruta R] muestra el estado sin ventana
  instalador.exe --aplicar  [--ruta R]   (también --instalar)
  instalador.exe --quitar   [--ruta R]
"""
import os, re, sys, json, queue, shutil, threading, traceback, subprocess, webbrowser, datetime

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(getattr(sys, "_MEIPASS", os.path.join(AQUI, "..")), "herramientas"))
import config  # noqa: E402

VERSION = "1.2.1"
REPO = "https://github.com/IrodoriCiel/LGTS-Parche-Traduccion-Espanol"
STEAM_APPID = 1812370
UI = os.path.join(getattr(sys, "_MEIPASS", os.path.join(AQUI, "..")), "app", "ui")
ICONO = os.path.join(getattr(sys, "_MEIPASS", os.path.join(AQUI, "..")), "app", "icono.ico")
CAMBIOS = os.path.join(getattr(sys, "_MEIPASS", os.path.join(AQUI, "..")), "CHANGELOG.md")
DATOS_APP = config.DATOS_APP
AJUSTES = os.path.join(DATOS_APP, "ajustes.json")
REGISTRO = os.path.join(DATOS_APP, "instalador.log")
ESPACIO_MINIMO = 500 * 1024 * 1024


def abrir(destino):
    """Abre un archivo, carpeta, página o enlace steam:// con el programa que el sistema tenga para eso."""
    if config.WINDOWS:
        os.startfile(destino); return
    subprocess.Popen(["xdg-open", destino], env=entorno_sistema(), stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def entorno_sistema():
    """Las variables de entorno con las que se abrió el programa, sin las que añade el ejecutable.

    Dentro del ejecutable de PyInstaller, LD_LIBRARY_PATH, QT_PLUGIN_PATH y otras apuntan a las bibliotecas
    y al Qt que lleva dentro. En la Steam Deck, xdg-open abre los enlaces con kde-open, que también es de Qt:
    con esas variables se cae y el botón «Jugar» no hacía nada.
    """
    if not getattr(sys, "frozen", False):
        return None
    try:
        crudo = open("/proc/self/environ", "rb").read()      # las de inicio, sin las que puso Python después
        entorno = dict(v.decode("utf-8", "surrogateescape").split("=", 1) for v in crudo.split(b"\0") if b"=" in v)
    except OSError:
        entorno = {k: v for k, v in os.environ.items() if not k.startswith(("QT_", "QML", "QTWEBENGINE"))}
    original = entorno.pop("LD_LIBRARY_PATH_ORIG", None)
    entorno.pop("LD_LIBRARY_PATH", None)
    if original is not None:
        entorno["LD_LIBRARY_PATH"] = original
    return {k: v for k, v in entorno.items() if not k.startswith(("_PYI_", "_MEI"))}


def abrir_web(url):
    abrir(url) if not config.WINDOWS else webbrowser.open(url)


class Salida:
    """Recibe los print() del parche: los guarda en el registro y los pasa a la ventana."""

    def __init__(self, destino=None):
        os.makedirs(DATOS_APP, exist_ok=True)
        self.log = open(REGISTRO, "a", encoding="utf-8")
        self.log.write(f"\n=== {datetime.datetime.now():%Y-%m-%d %H:%M:%S} · instalador {VERSION} ===\n")
        self.destino = destino

    def write(self, s):
        self.log.write(s); self.log.flush()
        if self.destino:
            self.destino(s)

    def flush(self):
        self.log.flush()


def leer_ajustes():
    try:
        return json.load(open(AJUSTES, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def guardar_ajustes(**kw):
    a = leer_ajustes(); a.update(kw)
    os.makedirs(DATOS_APP, exist_ok=True)
    json.dump(a, open(AJUSTES, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def ruta_inicial():
    r = leer_ajustes().get("juego")
    return os.path.realpath(r) if config.es_juego(r) else config.detectar_juego()


def relacion(aplicada):
    """Cómo es el parche aplicado respecto a este instalador: "igual", "anterior" o "posterior".

    Las versiones anteriores a 1.1.0 no dejaban marca de versión: sin marca se toma como anterior.
    """
    if not aplicada:
        return "anterior"
    num = lambda v: tuple(int(x) for x in re.findall(r"\d+", v))
    a, b = num(aplicada), num(VERSION)
    return "igual" if a == b else "anterior" if a < b else "posterior"


def novedades_de(notas):
    """Los puntos de «## Novedades…» en las notas de una publicación de GitHub (las arma el workflow con CHANGELOG.md)."""
    cambios, dentro = [], False
    for linea in notas.replace("\r\n", "\n").split("\n"):
        if linea.startswith("## "):
            if dentro:
                break
            dentro = linea[3:].lower().startswith("novedades")
        elif dentro and linea.strip() == "---":
            break
        elif dentro and linea.startswith("- "):
            cambios.append(linea[2:].strip())
        elif dentro and cambios and linea.startswith("  ") and linea.strip():
            cambios[-1] += " " + linea.strip()
    return cambios


def describir(e):
    """Texto corto sobre el parche aplicado («Parche 1.2.0 aplicado», «… se puede actualizar»)."""
    rel = relacion(e.get("parche"))
    if rel == "igual":
        return f"Parche {VERSION} aplicado (juego en español)"
    if rel == "anterior":
        cual = f"Parche {e['parche']}" if e.get("parche") else "Parche de una versión anterior"
        return f"{cual} aplicado · se puede actualizar a la {VERSION}"
    return f"Parche {e['parche']} aplicado (más nuevo que este programa, {VERSION})"


def comprobar(ruta):
    """Devuelve (estado, problema). problema es None si se puede aplicar o quitar el parche."""
    if not config.es_juego(ruta):
        return None, "Esa carpeta no es la del juego: debe contener LGTS.exe y la carpeta LGTS_Data."
    config.JUEGO = ruta
    try:
        import parche
        e = parche.estado()
    except Exception as ex:  # cabecera ilegible, permisos, módulo que falta...
        traceback.print_exc(file=sys.stdout)
        return None, f"No pude leer los archivos del juego: {ex}"
    if parche.juego_abierto():
        return e, "El juego está abierto. Ciérralo antes de continuar."
    return e, None


def ejecutar(accion, ruta):
    """Aplica o quita el parche. Lanza SystemExit/Exception con el motivo si falla."""
    config.JUEGO = ruta
    import parche
    if parche.juego_abierto():
        raise SystemExit("El juego está abierto. Ciérralo antes de continuar.")
    if accion == "aplicar":
        libre = shutil.disk_usage(ruta).free
        if libre < ESPACIO_MINIMO:
            raise SystemExit(f"Hay poco espacio libre en el disco del juego ({libre // 2**20} MB). Se necesitan unos 500 MB.")
        try:
            parche.aplicar(VERSION)
        except BaseException:
            # si algo falla a medias, se deja el juego como estaba
            traceback.print_exc(file=sys.stdout)
            print("\nNo se pudo aplicar el parche; devolviendo el juego a su estado original...")
            try:
                parche.quitar()
            except BaseException:
                traceback.print_exc(file=sys.stdout)
                raise SystemExit("No se pudo aplicar el parche ni deshacer los cambios. Usa «Verificar integridad» "
                                 f"en Steam para reparar el juego. Detalles en:\n{REGISTRO}")
            raise SystemExit(f"No se pudo aplicar el parche; el juego quedó como estaba. Detalles en:\n{REGISTRO}")
    else:
        parche.quitar()


# ---------------------------------------------------------------- modo sin ventana

def consola(argv):
    sys.stdout = Salida(lambda s: sys.__stdout__ and sys.__stdout__.write(s))
    ruta = argv[argv.index("--ruta") + 1] if "--ruta" in argv else ruta_inicial()
    print("Juego:", ruta)
    e, problema = comprobar(ruta)
    print("Estado:", e)
    if e and e["parchado"]:
        print(describir(e))
    if "--estado" in argv:
        return 0 if e else 1
    if problema:
        print("ERROR:", problema); return 1
    try:
        ejecutar("aplicar" if ("--aplicar" in argv or "--instalar" in argv) else "quitar", ruta)
    except SystemExit as ex:
        print("ERROR:", ex); return 1
    except Exception:
        traceback.print_exc(file=sys.stdout); return 1
    return 0


# ---------------------------------------------------------------- ventana (pywebview)

# Líneas que imprime parche.py → (paso que se muestra, porcentaje de avance)
PASOS = [
    ("El juego ya tiene una traducción", "Quitando la traducción anterior…", 3),
    ("Juego restaurado", "Archivos originales restaurados.", 6),
    ("Paquetes pequeños", "Ventanas, minijuegos y pantallas de carga listos.", 25),
    ("Leyendo data.unity3d", "Leyendo los archivos principales del juego…", 28),
    ("Textos de diálogos", "Diálogos, menús, objetos y misiones traducidos.", 50),
    ("Textos fijos en escenas", "Textos de pantallas traducidos.", 56),
    ("Subtítulos de cinemáticas", "Subtítulos de cinemáticas traducidos.", 60),
    ("Textos en guiones", "Guiones traducidos.", 63),
    ("Imágenes en escenas", "Imágenes con texto reemplazadas.", 68),
    ("Letras añadidas a fuentes", "Letras con tilde y ñ añadidas. Guardando los cambios en el juego…", 72),
    ("Textos del código", "Textos del código traducidos.", 96),
]


class Api:
    """Funciones que la página (app/ui/index.html) llama con pywebview.api.*"""

    def __init__(self):
        self._win = None
        self._ruta = ruta_inicial()
        self._ocupado = False
        self._portapapeles = None if config.WINDOWS else portapapeles_qt()

    # --- estado
    def info(self):
        import parche
        return dict(version=VERSION, juego_probado=", ".join(sorted(set(parche.VERSION_PROBADA.values()))),
                    sistema="windows" if config.WINDOWS else "linux")

    def estado(self):
        ruta = self._ruta
        if not ruta:
            return dict(ruta=None, juego_ok=False)
        if not config.es_juego(ruta):
            return dict(ruta=ruta, juego_ok=False, problema="Esa carpeta no es la del juego: debe contener LGTS.exe y LGTS_Data.")
        config.JUEGO = ruta
        try:
            import parche
            e = parche.estado()
            e.update(ruta=ruta, juego_ok=True, abierto=parche.juego_abierto(), instalador=VERSION,
                     relacion=relacion(e["parche"]) if e["parchado"] else None)
            return e
        except Exception as ex:
            return dict(ruta=ruta, juego_ok=False, problema=f"No pude leer los archivos del juego: {ex}")

    def buscar(self):
        import webview
        r = self._win.create_file_dialog(webview.FOLDER_DIALOG,
                                         directory=self._ruta or ("C:\\" if config.WINDOWS else os.path.expanduser("~")))
        if not r:
            return None
        r = os.path.normpath(r[0] if isinstance(r, (list, tuple)) else r)
        if not config.es_juego(r) and config.es_juego(os.path.dirname(r)):
            r = os.path.dirname(r)              # eligió LGTS_Data
        self._ruta = r
        if config.es_juego(r):
            guardar_ajustes(juego=r)
        return self.estado()

    def detectar(self):
        r = config.detectar_juego()
        if r:
            self._ruta = r; guardar_ajustes(juego=r)
        return self.estado()

    def novedades(self):
        """Las versiones publicadas en GitHub más nuevas que este programa, o None si no hay.

        {version, url} de la última e historial: [{version, fecha, cambios}] de todas las más
        nuevas, con sus novedades sacadas de las notas de cada publicación (así se ve si ya se
        arregló algo aunque el jugador se haya saltado versiones). Solo pide la lista pública
        de publicaciones; sin internet, o si GitHub tarda, no hay aviso.
        """
        import urllib.request
        api = REPO.replace("https://github.com/", "https://api.github.com/repos/") + "/releases?per_page=30"
        try:
            pet = urllib.request.Request(api, headers={"User-Agent": "Instalar-Traduccion-LGTS/" + VERSION,
                                                       "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(pet, timeout=4) as r:
                publicaciones = json.load(r)
        except Exception:
            return None
        nuevas = []
        for p in publicaciones:
            version = str(p.get("tag_name", "")).lstrip("vV")
            if p.get("draft") or p.get("prerelease") or not re.fullmatch(r"\d+(\.\d+)*", version):
                continue
            if relacion(version) == "posterior":
                nuevas.append(dict(version=version, fecha=str(p.get("published_at") or "")[:10],
                                   cambios=novedades_de(p.get("body") or ""), url=p.get("html_url")))
        if not nuevas:
            return None
        nuevas.sort(key=lambda n: tuple(int(x) for x in n["version"].split(".")), reverse=True)
        return dict(version=nuevas[0]["version"], url=nuevas[0]["url"] or REPO + "/releases/latest", historial=nuevas)

    def historial(self):
        """Las novedades de CHANGELOG.md: [{version, fecha, cambios: [...]}], la más nueva primero."""
        out = []
        try:
            for linea in open(CAMBIOS, encoding="utf-8"):
                m = re.match(r"## (\d+(?:\.\d+)*)\s*(?:—\s*(.+))?$", linea.strip())
                if m:
                    out.append(dict(version=m.group(1), fecha=(m.group(2) or "").strip(), cambios=[]))
                elif out and linea.startswith("- "):
                    out[-1]["cambios"].append(linea[2:].strip())
                elif out and out[-1]["cambios"] and linea.startswith("  ") and linea.strip():
                    out[-1]["cambios"][-1] += " " + linea.strip()      # punto partido en varias líneas
        except OSError:
            pass
        return out

    # --- acciones
    def abrir_url(self, url):
        if url.startswith(REPO + "/"):        # solo páginas del proyecto
            abrir_web(url)

    def aplicar(self):
        self._lanzar("aplicar")

    def quitar(self):
        self._lanzar("quitar")

    def _evento(self, **ev):
        try:
            self._win.evaluate_js(f"ui.evento({json.dumps(ev, ensure_ascii=False)})")
        except Exception:
            pass

    def _lanzar(self, accion):
        if self._ocupado:
            return
        self._ocupado = True
        ruta = self._ruta
        pendiente = [""]

        def linea(texto):
            texto = texto.strip()
            if not texto:
                return
            for clave, paso, pct in PASOS:
                if texto.startswith(clave):
                    if accion == "quitar" and clave == "Juego restaurado":
                        return
                    self._evento(tipo="paso", texto=paso, pct=pct)
                    break
            self._evento(tipo="linea", texto=texto)

        def recibir(s):
            pendiente[0] += s
            while "\n" in pendiente[0]:
                l, pendiente[0] = pendiente[0].split("\n", 1)
                linea(l)

        def trabajo():
            sys.stdout = Salida(recibir)
            try:
                self._evento(tipo="paso", pct=4, texto="Creando el respaldo y traduciendo los paquetes pequeños…"
                             if accion == "aplicar" else "Restaurando los archivos originales…")
                ejecutar(accion, ruta)
                linea(pendiente[0])
                self._evento(tipo="fin", accion=accion, texto="¡Parche aplicado! Ya puedes jugar en español."
                             if accion == "aplicar" else "Parche quitado. El juego vuelve a estar en inglés.")
            except SystemExit as ex:
                self._evento(tipo="error", texto=str(ex))
            except Exception:
                traceback.print_exc(file=sys.stdout)
                self._evento(tipo="error", texto=f"Ocurrió un error inesperado. Los detalles están en {REGISTRO}")
            finally:
                self._ocupado = False
        threading.Thread(target=trabajo, daemon=True).start()

    # --- utilidades
    def jugar(self):
        abrir(f"steam://rungameid/{STEAM_APPID}")

    def abrir_steam(self):
        try:
            abrir(f"steam://store/{STEAM_APPID}")
        except OSError:                          # sin Steam: la tienda en el navegador
            abrir_web(f"https://store.steampowered.com/app/{STEAM_APPID}")

    def abrir_proyecto(self, sub=""):
        abrir_web(REPO + ("/" + sub if sub else ""))

    def abrir_registro(self):
        if os.path.exists(REGISTRO):
            abrir(REGISTRO)

    def abrir_respaldo(self):
        carpeta = os.path.join(config.JUEGO or "", config.CARPETA_RESPALDO)
        abrir(carpeta if os.path.isdir(carpeta) else (config.JUEGO or DATOS_APP))

    def copiar(self, texto):
        if config.WINDOWS:
            subprocess.run(["clip"], input=texto.encode("utf-16-le"), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            self._portapapeles.texto.emit(texto)       # el portapapeles de Qt solo se toca desde su hilo
        return True

    def minimizar(self):
        self._win.minimize()

    def cerrar(self):
        if self._ocupado and not self._win.create_confirmation_dialog(
                "Trabajando", "Todavía se está aplicando el cambio. Si cierras ahora, el juego puede quedar dañado "
                              "y tendrías que usar «Verificar integridad» en Steam.\n\n¿Cerrar de todos modos?"):
            return
        self._ocupado = False
        self._win.destroy()

    def _al_cerrar(self):
        # Alt+F4 o cerrar desde la barra de tareas
        if self._ocupado:
            return bool(self._win.create_confirmation_dialog(
                "Trabajando", "Todavía se está aplicando el cambio. ¿Cerrar de todos modos?"))
        return True


def portapapeles_qt():
    """Objeto de Qt creado en el hilo principal: su señal lleva el texto al portapapeles desde cualquier hilo."""
    from qtpy.QtCore import QObject, Signal
    from qtpy.QtWidgets import QApplication

    class Portapapeles(QObject):
        texto = Signal(str)

    p = Portapapeles()
    p.texto.connect(lambda t: QApplication.clipboard().setText(t))
    return p


def ventana():
    """Ventana con el diseño HTML. Si no hay WebView2 / Qt WebEngine (o falla), usa la de tkinter."""
    try:
        if not config.WINDOWS:
            # En la Steam Deck, Qt WebEngine dibuja con la GPU una ventana vacía («Backend texture is not a
            # Vulkan texture»); la página es sencilla y sin GPU se ve bien.
            os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
            # El aislamiento de Chromium puede no arrancar desde la carpeta temporal del ejecutable;
            # la ventana solo muestra la página local del programa.
            os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
        import webview
        sys.stdout = Salida()
        api = Api()
        win = webview.create_window("Traducción al español · Little Goody Two Shoes", url=os.path.join(UI, "index.html"),
                                    js_api=api, width=840, height=720, resizable=False, frameless=True,
                                    easy_drag=False, background_color="#0b0f2a")
        api._win = win
        win.events.closing += api._al_cerrar
        webview.start(gui="edgechromium" if config.WINDOWS else "qt", http_server=True,
                      icon=None if config.WINDOWS else ICONO)     # en Windows el icono ya va en el .exe
    except Exception:
        traceback.print_exc(file=sys.stdout)
        ventana_tk()


# ---------------------------------------------------------------- ventana sencilla (tkinter)

def ventana_tk():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, scrolledtext

    raiz = tk.Tk()
    raiz.title("Traducción al español · Little Goody Two Shoes")
    raiz.geometry("720x560"); raiz.minsize(600, 480)
    try:
        raiz.iconbitmap(ICONO)
    except Exception:
        pass
    est = ttk.Style()
    if "vista" in est.theme_names():
        est.theme_use("vista")
    est.configure("Titulo.TLabel", font=("Segoe UI", 15, "bold"))
    est.configure("Grande.TButton", font=("Segoe UI", 11), padding=(14, 8))

    cola = queue.Queue()
    ocupado = {"v": False}
    ruta_var = tk.StringVar(value=ruta_inicial() or "")
    estado_var = tk.StringVar()

    marco = ttk.Frame(raiz, padding=16); marco.pack(fill="both", expand=True)
    ttk.Label(marco, text="Little Goody Two Shoes — Traducción al español", style="Titulo.TLabel").pack(anchor="w")
    ttk.Label(marco, text="Traducción no oficial hecha para fans. Necesitas el juego original de Steam. "
                          "No se modifica nada hasta que presiones «Aplicar parche».", wraplength=660,
              foreground="#555").pack(anchor="w", pady=(2, 12))

    caja = ttk.LabelFrame(marco, text=" Carpeta del juego ", padding=10); caja.pack(fill="x")
    fila = ttk.Frame(caja); fila.pack(fill="x")
    ttk.Entry(fila, textvariable=ruta_var, state="readonly").pack(side="left", fill="x", expand=True)

    def buscar():
        r = filedialog.askdirectory(title="Elige la carpeta «Little Goody Two Shoes»",
                                    initialdir=ruta_var.get() or ("C:\\" if config.WINDOWS else os.path.expanduser("~")))
        if r:
            r = os.path.normpath(r)
            if not config.es_juego(r) and config.es_juego(os.path.dirname(r)):
                r = os.path.dirname(r)          # eligió LGTS_Data
            ruta_var.set(r); actualizar()

    def detectar():
        r = config.detectar_juego()
        if r:
            ruta_var.set(r); actualizar()
        else:
            messagebox.showinfo("No encontrado", "No encontré el juego en las bibliotecas de Steam.\n"
                                "Usa «Buscar…» para elegir la carpeta «Little Goody Two Shoes».")

    ttk.Button(fila, text="Buscar…", command=buscar).pack(side="left", padx=(8, 0))
    ttk.Button(fila, text="Detectar", command=detectar).pack(side="left", padx=(6, 0))
    ttk.Label(caja, textvariable=estado_var, wraplength=660, padding=(0, 8, 0, 0)).pack(anchor="w")

    botones = ttk.Frame(marco, padding=(0, 12)); botones.pack(fill="x")
    b_inst = ttk.Button(botones, text="Aplicar parche", style="Grande.TButton", command=lambda: lanzar("aplicar"))
    b_quit = ttk.Button(botones, text="Quitar parche (volver al inglés)", style="Grande.TButton", command=lambda: lanzar("quitar"))
    b_inst.pack(side="left"); b_quit.pack(side="left", padx=8)
    barra = ttk.Progressbar(botones, mode="indeterminate", length=180); barra.pack(side="right")

    log = scrolledtext.ScrolledText(marco, height=12, font=("Consolas", 9), state="disabled", wrap="word")
    log.pack(fill="both", expand=True)
    pie = ttk.Frame(marco); pie.pack(fill="x", pady=(8, 0))
    ttk.Label(pie, text=f"Parche {VERSION} · por Iro", foreground="#777").pack(side="left")
    enlace = ttk.Label(pie, text="Reportar un error o ver el proyecto", foreground="#0a5fb4", cursor="hand2")
    enlace.pack(side="right"); enlace.bind("<Button-1>", lambda e: abrir_web(REPO + "/issues"))

    def escribir(s):
        log.configure(state="normal"); log.insert("end", s); log.see("end"); log.configure(state="disabled")

    def actualizar():
        ruta = ruta_var.get()
        if not ruta:
            estado_var.set("⚠ No encontré el juego. Usa «Buscar…» para elegir su carpeta.")
            b_inst.state(["disabled"]); b_quit.state(["disabled"]); return
        e, problema = comprobar(ruta)
        if e is None:
            estado_var.set("⚠ " + problema); b_inst.state(["disabled"]); b_quit.state(["disabled"]); return
        guardar_ajustes(juego=ruta)
        version = f"versión {e['version']}" if e["version"] else "versión no probada (puede que una actualización de Steam cambie algo)"
        trad = ("✅ " + describir(e)) if e["parchado"] else "Parche no aplicado (el juego está en inglés)"
        texto = f"Juego encontrado · {version}\n{trad}"
        if e["parchado"] and not e["respaldo"]:
            texto += "\n⚠ No encontré el respaldo de los archivos originales: para volver al inglés usa «Verificar integridad» en Steam."
        if problema:
            texto += "\n⚠ " + problema
        estado_var.set(texto)
        b_inst.state(["!disabled"])
        b_quit.state(["!disabled"] if e["parchado"] and e["respaldo"] else ["disabled"])
        rel = relacion(e["parche"]) if e["parchado"] else None
        b_inst.configure(text="Actualizar parche" if rel == "anterior" else "Reaplicar parche" if e["parchado"] else "Aplicar parche")

    def lanzar(accion):
        ruta = ruta_var.get()
        e, problema = comprobar(ruta)
        if problema:
            messagebox.showwarning("No se puede continuar", problema); actualizar(); return
        if accion == "aplicar" and not e["version"]:
            if not messagebox.askyesno("Versión no probada",
                                       "Esta versión del juego no se ha probado con la traducción "
                                       "(quizá Steam la actualizó). ¿Intentar de todos modos?"):
                return
        rel = relacion(e["parche"]) if e["parchado"] else None
        cual = f"el parche {e['parche']}" if e.get("parche") else "el parche anterior"
        aviso = (f"Se reemplazará {cual} por la versión {VERSION}. " if rel == "anterior"
                 else f"El juego tiene {cual}, más nuevo que este programa. Se pondrá la versión {VERSION}. " if rel == "posterior"
                 else "Se aplicará el parche en español. ")
        if accion == "aplicar" and not messagebox.askokcancel(
                "Actualizar parche" if rel == "anterior" else "Aplicar parche",
                aviso + "Tarda menos de un minuto y usa 1–2 GB de memoria.\n\nNo abras el juego hasta que termine."):
            return
        ocupado["v"] = True
        b_inst.state(["disabled"]); b_quit.state(["disabled"]); barra.start(12)
        escribir(f"\n— {'Aplicando el parche' if accion == 'aplicar' else 'Quitando el parche'} —\n")

        def trabajo():
            sys.stdout = Salida(lambda s: cola.put(("texto", s)))
            try:
                ejecutar(accion, ruta)
                cola.put(("fin", None))
            except SystemExit as ex:
                cola.put(("error", str(ex)))
            except Exception:
                traceback.print_exc(file=sys.stdout)
                cola.put(("error", f"Ocurrió un error inesperado. Los detalles están en:\n{REGISTRO}"))
        threading.Thread(target=trabajo, daemon=True).start()
        revisar(accion)

    def revisar(accion):
        try:
            while True:
                tipo, dato = cola.get_nowait()
                if tipo == "texto":
                    escribir(dato)
                else:
                    ocupado["v"] = False; barra.stop(); actualizar()
                    if tipo == "fin":
                        messagebox.showinfo("Listo", "¡Parche aplicado! Ya puedes abrir el juego desde Steam."
                                            if accion == "aplicar" else "Listo: el juego volvió al inglés original.")
                    else:
                        messagebox.showerror("No se pudo completar", dato)
                    return
        except queue.Empty:
            pass
        raiz.after(150, lambda: revisar(accion))

    def cerrar():
        if ocupado["v"] and not messagebox.askyesno(
                "Trabajando", "Todavía se está aplicando el cambio. Si cierras ahora, el juego puede quedar dañado "
                              "y tendrías que usar «Verificar integridad» en Steam.\n\n¿Cerrar de todos modos?"):
            return
        raiz.destroy()

    raiz.protocol("WM_DELETE_WINDOW", cerrar)
    actualizar()
    raiz.mainloop()


if __name__ == "__main__":
    if any(a in sys.argv for a in ("--estado", "--aplicar", "--instalar", "--quitar")):
        try:
            sys.exit(consola(sys.argv))
        except SystemExit:
            raise
        except BaseException:
            traceback.print_exc(file=sys.stdout); sys.exit(1)
    ventana()
