# PyInstaller: genera dist/Instalar-Traduccion-LGTS-<version>.exe (un solo archivo, con ventana y sin consola).
#   pyinstaller app/instalador.spec --noconfirm
import os, re
from PyInstaller.utils.hooks import collect_all
from PyInstaller.utils.win32.versioninfo import (VSVersionInfo, FixedFileInfo, StringFileInfo,
                                                 StringTable, StringStruct, VarFileInfo, VarStruct)

RAIZ = os.path.abspath(os.path.join(SPECPATH, ".."))
datas, binaries = [], []
hidden = ["parche", "config", "gridly", "bundle", "fuentes", "dll_textos"]
for paquete in ("UnityPy", "TypeTreeGeneratorAPI", "etcpak", "texture2ddecoder", "archspec", "brotli", "numpy", "cv2",
                "fmod_toolkit", "pyfmodex",
                "webview", "pythonnet", "clr_loader", "proxy_tools", "bottle"):   # ventana (pywebview + WebView2)
    d, b, h = collect_all(paquete)
    datas += d; binaries += b; hidden += h
datas += [(os.path.join(RAIZ, "traduccion"), "traduccion"),
          (os.path.join(RAIZ, "datos"), "datos"),
          (os.path.join(RAIZ, "herramientas", "fuentes"), os.path.join("herramientas", "fuentes")),
          (os.path.join(SPECPATH, "ui"), os.path.join("app", "ui"))]
icono = os.path.join(SPECPATH, "icono.ico")

# La versión la manda instalador.py: va en el nombre del archivo y en sus propiedades de Windows,
# para que al descargar varias publicaciones se sepa cuál es cada una.
VERSION = re.search(r'^VERSION = "([^"]+)"',
                    open(os.path.join(SPECPATH, "instalador.py"), encoding="utf-8").read(), re.M).group(1)
NOMBRE = f"Instalar-Traduccion-LGTS-{VERSION}"
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

a = Analysis([os.path.join(SPECPATH, "instalador.py")],
             pathex=[os.path.join(RAIZ, "herramientas")],
             datas=datas, binaries=binaries, hiddenimports=hidden,
             excludes=["matplotlib", "IPython", "pytest"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, name=NOMBRE, version=propiedades,
          console=False, upx=False, icon=icono if os.path.exists(icono) else None)
