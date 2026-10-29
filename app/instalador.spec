# PyInstaller: genera dist/Instalar-Traduccion-LGTS.exe (un solo archivo, con ventana y sin consola).
#   pyinstaller app/instalador.spec --noconfirm
import os
from PyInstaller.utils.hooks import collect_all

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

a = Analysis([os.path.join(SPECPATH, "instalador.py")],
             pathex=[os.path.join(RAIZ, "herramientas")],
             datas=datas, binaries=binaries, hiddenimports=hidden,
             excludes=["matplotlib", "IPython", "pytest"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, name="Instalar-Traduccion-LGTS",
          console=False, upx=False, icon=icono if os.path.exists(icono) else None)
