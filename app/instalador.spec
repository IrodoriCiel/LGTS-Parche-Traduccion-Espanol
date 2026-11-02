# PyInstaller: genera dist/Instalar-Traduccion-LGTS-<version>.exe (un solo archivo, con ventana y sin consola).
# En Linux genera dist/Instalar-Traduccion-LGTS-<version>-SteamDeck, el ejecutable para la Steam Deck.
#   pyinstaller app/instalador.spec --noconfirm
import os, re, sys
from PyInstaller.utils.hooks import collect_all

WINDOWS = sys.platform == "win32"

RAIZ = os.path.abspath(os.path.join(SPECPATH, ".."))
datas, binaries = [], []
hidden = ["parche", "config", "gridly", "bundle", "fuentes", "dll_textos"]
ventana = ("pythonnet", "clr_loader") if WINDOWS else ()   # ventana: pywebview + WebView2 en Windows o Qt WebEngine
                                                          # en Linux (Qt lo recogen los hooks de PyInstaller)
for paquete in ("UnityPy", "TypeTreeGeneratorAPI", "etcpak", "texture2ddecoder", "archspec", "brotli", "numpy", "cv2",
                "fmod_toolkit", "pyfmodex",
                "webview", "proxy_tools", "bottle") + ventana:
    d, b, h = collect_all(paquete)
    datas += d; binaries += b; hidden += h
datas += [(os.path.join(RAIZ, "traduccion"), "traduccion"),
          (os.path.join(RAIZ, "datos"), "datos"),
          (os.path.join(RAIZ, "herramientas", "fuentes"), os.path.join("herramientas", "fuentes")),
          (os.path.join(SPECPATH, "ui"), os.path.join("app", "ui")),
          (os.path.join(SPECPATH, "icono.ico"), "app"),              # icono de la ventana en Linux y en tkinter
          (os.path.join(RAIZ, "CHANGELOG.md"), ".")]           # las novedades que muestra la ventana
icono = os.path.join(SPECPATH, "icono.ico")

# La versión la manda instalador.py: va en el nombre del archivo y en sus propiedades de Windows,
# para que al descargar varias publicaciones se sepa cuál es cada una.
VERSION = re.search(r'^VERSION = "([^"]+)"',
                    open(os.path.join(SPECPATH, "instalador.py"), encoding="utf-8").read(), re.M).group(1)
NOMBRE = f"Instalar-Traduccion-LGTS-{VERSION}" + ("" if WINDOWS else "-SteamDeck")
propiedades = None                                           # las propiedades de archivo son solo de Windows
if WINDOWS:
    from PyInstaller.utils.win32.versioninfo import (VSVersionInfo, FixedFileInfo, StringFileInfo,
                                                     StringTable, StringStruct, VarFileInfo, VarStruct)
    numeros = tuple((list(int(n) for n in VERSION.split(".")) + [0, 0, 0, 0])[:4])
    propiedades = VSVersionInfo(
        ffi=FixedFileInfo(filevers=numeros, prodvers=numeros, mask=0x3F, flags=0x0,
                          OS=0x40004, fileType=0x1, subtype=0x0),
        kids=[StringFileInfo([StringTable("080a04b0", [          # 080a: español de México; 04b0: Unicode
            StringStruct("CompanyName", "Iro"),
            StringStruct("FileDescription", "Traducción al español de Little Goody Two Shoes (no oficial)"),
            StringStruct("FileVersion", VERSION),
            StringStruct("InternalName", "Instalar-Traduccion-LGTS"),
            StringStruct("LegalCopyright", "Traducción: CC BY-NC-SA 4.0 · Herramientas: MIT"),
            StringStruct("OriginalFilename", NOMBRE + ".exe"),
            StringStruct("ProductName", "Parche de traducción al español de Little Goody Two Shoes"),
            StringStruct("ProductVersion", VERSION)])]),
            VarFileInfo([VarStruct("Translation", [0x080A, 1200])])])

# Linux: solo las partes de Qt que usa la ventana de pywebview; el resto de Qt (multimedia, SQL, 3D...)
# haría el ejecutable mucho más grande.
QT_USADO = ["QtCore", "QtGui", "QtWidgets", "QtNetwork", "QtWebChannel", "QtWebEngineCore", "QtWebEngineWidgets"]
QT_SOBRA = ["Qt3DAnimation", "Qt3DCore", "Qt3DExtras", "Qt3DInput", "Qt3DLogic", "Qt3DRender", "QtBluetooth",
            "QtCharts", "QtDataVisualization", "QtDesigner", "QtHelp", "QtMultimedia", "QtMultimediaWidgets", "QtNfc",
            "QtOpenGLWidgets", "QtPdf", "QtPdfWidgets", "QtPositioning", "QtQuick3D", "QtQuickWidgets",
            "QtRemoteObjects", "QtSensors", "QtSerialPort", "QtSpatialAudio", "QtSql", "QtStateMachine", "QtSvgWidgets",
            "QtTest", "QtTextToSpeech", "QtWebEngineQuick", "QtWebSockets", "QtXml", "QtBluetooth"]
if not WINDOWS:
    hidden += ["qtpy", "webview.platforms.qt"] + [f"PyQt6.{m}" for m in QT_USADO]

a = Analysis([os.path.join(SPECPATH, "instalador.py")],
             pathex=[os.path.join(RAIZ, "herramientas")],
             datas=datas, binaries=binaries, hiddenimports=hidden,
             excludes=["matplotlib", "IPython", "pytest"] + ([] if WINDOWS else ["PyQt5", "PySide2", "PySide6", "gi"] + [f"PyQt6.{m}" for m in QT_SOBRA]))
if not WINDOWS:
    import fnmatch
    # Archivos de Qt que la ventana no usa: traducciones de Qt (salvo las de Chromium en español e inglés),
    # QML/Quick 3D, PDF y el tema de GTK, que además arrastraría GTK e ICU del sistema donde se compila.
    SOBRA = ["PyQt6/Qt6/translations/*", "PyQt6/Qt6/qml/*", "PyQt6/Qt6/lib/libQt6Quick3D*", "PyQt6/Qt6/lib/libQt6Pdf*",
             "PyQt6/Qt6/plugins/platformthemes/libqgtk3*", "PyQt6/Qt6/plugins/sqldrivers/*",
             "PyQt6/Qt6/plugins/multimedia/*", "PyQt6/Qt6/plugins/position/*", "PyQt6/Qt6/plugins/sensors/*"]
    QUEDA = ["PyQt6/Qt6/translations/qtwebengine_locales/en-US.pak", "PyQt6/Qt6/translations/qtwebengine_locales/es*.pak"]
    util = lambda nombre: not any(fnmatch.fnmatch(nombre, p) for p in SOBRA) or any(fnmatch.fnmatch(nombre, p) for p in QUEDA)
    a.binaries = [x for x in a.binaries if util(x[0])]
    a.datas = [x for x in a.datas if util(x[0])]
    # Lo quitado deja huérfanas bibliotecas de Qt y del sistema (QML, multimedia, GTK, PulseAudio...): solo se
    # quedan las que necesita lo demás. ldd da las dependencias de cada archivo, también las indirectas.
    from PyInstaller.depend.bindepend import get_imports
    suelta = lambda n: n.startswith("PyQt6/Qt6/lib/") or ("/" not in n and n.startswith("lib") and not n.startswith("libpython"))
    usadas = set()
    for nombre, origen, _ in a.binaries:
        if not suelta(nombre):
            usadas.update(os.path.basename(ref) for ref, _ in get_imports(origen))
    a.binaries = [x for x in a.binaries if not suelta(x[0]) or os.path.basename(x[0]) in usadas]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, name=NOMBRE, version=propiedades,
          console=False, upx=False, icon=icono if WINDOWS and os.path.exists(icono) else None)
