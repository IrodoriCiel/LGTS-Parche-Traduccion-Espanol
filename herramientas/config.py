"""Rutas del proyecto y del juego."""
import os, sys, re, shutil

# Dentro del .exe (PyInstaller) los datos están en sys._MEIPASS
CONGELADO = getattr(sys, "frozen", False)
RAIZ = sys._MEIPASS if CONGELADO else os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
TRAD = os.path.join(RAIZ, "traduccion")
EN_DIR = os.path.join(TRAD, "en")
ES_DIR = os.path.join(TRAD, "es")
FIJOS_EN = os.path.join(TRAD, "textos_fijos", "en.json")
FIJOS_ES = os.path.join(TRAD, "textos_fijos", "es.json")
IMAGENES = os.path.join(TRAD, "imagenes")
UBICACIONES = os.path.join(RAIZ, "datos", "textos_fijos_ubicaciones.json")
COMPILADO = os.path.join(RAIZ, "datos", "compilado", "traduccion_es.json")
ESTADO = os.path.join(TRAD, "estado.json")
SUBTITULOS_ES = os.path.join(TRAD, "subtitulos", "es.json")
SUBTITULOS_UBIC = os.path.join(RAIZ, "datos", "subtitulos_ubicaciones.json")
CODIGO_ES = os.path.join(TRAD, "codigo", "es.json")
FUENTES_UBIC = os.path.join(RAIZ, "datos", "fuentes_ubicaciones.json")
GUIONES_ES = os.path.join(TRAD, "guiones", "es.json")
GUIONES_UBIC = os.path.join(RAIZ, "datos", "guiones_ubicaciones.json")

# El respaldo de los originales vive dentro de la carpeta del juego: así lo encuentra cualquier copia del
# instalador, desde cualquier cuenta de Windows (Steam no borra carpetas extra al verificar o actualizar).
CARPETA_RESPALDO = "respaldo_traduccion_es"
# Donde lo guardaban versiones anteriores; si está ahí, se copia a la carpeta del juego.
RESPALDOS_VIEJOS = [os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "LGTS-Parche-Traduccion-Espanol", "respaldo"),
                    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "respaldo")]

CARPETA_JUEGO = "Little Goody Two Shoes"
JUEGO = None   # la app lo fija cuando el usuario elige la carpeta


def es_juego(ruta):
    """¿Es `ruta` la carpeta de instalación del juego?"""
    return bool(ruta) and os.path.isfile(os.path.join(ruta, "LGTS.exe")) \
        and os.path.isfile(os.path.join(ruta, "LGTS_Data", "data.unity3d"))


def bibliotecas_steam():
    """Carpetas de bibliotecas de Steam (registro de Windows + libraryfolders.vdf)."""
    raices = []
    try:
        import winreg
        for raiz, clave, valor in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                                   (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath")):
            try:
                with winreg.OpenKey(raiz, clave) as k:
                    raices.append(os.path.normpath(winreg.QueryValueEx(k, valor)[0]))
            except OSError:
                pass
    except ImportError:
        pass
    raices += [r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"]
    libs = []
    for r in raices:
        libs.append(r)
        vdf = os.path.join(r, "steamapps", "libraryfolders.vdf")
        if os.path.isfile(vdf):
            for m in re.finditer(r'"path"\s+"([^"]+)"', open(vdf, encoding="utf-8", errors="replace").read()):
                libs.append(os.path.normpath(m.group(1).replace("\\\\", "\\")))
    vistas = []
    for l in libs:
        if l.lower() not in (v.lower() for v in vistas):
            vistas.append(l)
    return vistas


def detectar_juego():
    """Carpeta de instalación del juego o None: ruta_juego.txt, luego las bibliotecas de Steam."""
    candidatos = []
    base = os.path.dirname(sys.executable) if CONGELADO else RAIZ
    archivo = os.path.join(base, "ruta_juego.txt")
    if os.path.exists(archivo):
        candidatos.append(open(archivo, encoding="utf-8").read().strip().strip('"'))
    candidatos += [os.path.join(l, "steamapps", "common", CARPETA_JUEGO) for l in bibliotecas_steam()]
    candidatos += [rf"{u}:\SteamLibrary\steamapps\common\{CARPETA_JUEGO}" for u in "DEFGH"]
    for c in candidatos:
        if es_juego(c):
            return os.path.realpath(c)   # con las mayúsculas reales (el registro de Steam la da en minúsculas)
    return None


def carpeta_juego():
    """Carpeta LGTS_Data del juego (la elegida en la app, ruta_juego.txt o Steam)."""
    juego = JUEGO if es_juego(JUEGO) else detectar_juego()
    if juego:
        return os.path.join(juego, "LGTS_Data")
    sys.exit("No encontré el juego. Crea el archivo ruta_juego.txt en la carpeta del proyecto "
             "con la ruta de instalación, por ejemplo:\n"
             r"D:\SteamLibrary\steamapps\common\Little Goody Two Shoes")


def respaldo():
    """Carpeta del respaldo de los originales, dentro de la carpeta del juego."""
    destino = os.path.join(os.path.dirname(carpeta_juego()), CARPETA_RESPALDO)
    if not os.path.exists(os.path.join(destino, "meta.json")):
        for viejo in RESPALDOS_VIEJOS:
            if os.path.isfile(os.path.join(viejo, "meta.json")):
                shutil.rmtree(destino, ignore_errors=True)
                shutil.copytree(viejo, destino)
                break
    return destino
