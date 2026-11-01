"""Aplica / quita la traducción al español en el juego instalado.

Uso:
  python parche.py aplicar     (en el repo de trabajo, antes ejecuta compilar.py)
  python parche.py quitar
  (o usa el instalador con ventana: app/instalador.py)

data.unity3d (6 GB) no se reescribe: se añaden al final copias nuevas de los
archivos internos modificados (resources.assets con la tabla Gridly traducida,
las escenas con textos fijos y las imágenes) y un índice nuevo; la cabecera
pasa a apuntar a ese índice. Los paquetes pequeños de StreamingAssets se
reescriben enteros. "quitar" recorta lo añadido y repone la cabecera y los
paquetes originales guardados en <juego>/respaldo_traduccion_es.
"""
import sys, os, re, json, struct, shutil, glob, gc
import lz4.block
import UnityPy
from UnityPy.helpers import ImportHelper
from UnityPy.helpers.TypeTreeGenerator import TypeTreeGenerator
from UnityPy.streams import EndianBinaryReader
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bundle import read_header, LectorBundle, Ventana
import gridly
import fuentes
import config

UNITY = "2021.3.24f1"
BLOCK = 0x20000


def rutas():
    data = config.carpeta_juego()
    return (data, os.path.join(data, "data.unity3d"),
            os.path.join(data, "StreamingAssets", "AssetBundles"))


VERSION_PROBADA = {6476759553: "1.1.2"}   # tamaño de data.unity3d original → versión del juego


def juego_abierto():
    """True si LGTS.exe se está ejecutando."""
    import subprocess
    try:
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq LGTS.exe", "/NH"], capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        # la salida viene en la página de códigos de la consola (con acentos en Windows en español)
        return b"lgts.exe" in r.stdout.lower()
    except OSError:
        return False


def estado():
    """Estado del juego instalado: traducido o no, versión y si hay respaldo."""
    data, game, bundles = rutas()
    parchado = bool(read_header(game)[0]["flags"] & 0x80)
    meta_p = os.path.join(config.respaldo(), "meta.json")
    respaldo = json.load(open(meta_p)) if os.path.exists(meta_p) else None
    tam = respaldo["size"] if parchado and respaldo else os.path.getsize(game)
    return dict(parchado=parchado, respaldo=respaldo is not None,
                version=VERSION_PROBADA.get(tam), tam_original=tam if (respaldo or not parchado) else None,
                parche=version_aplicada() if parchado else None)


MARCA = "parche.json"   # en la carpeta del respaldo: qué versión del parche está aplicada


def version_aplicada():
    """Versión del parche aplicado según su marca, o None si no la tiene (1.0.0 o el repo de trabajo)."""
    try:
        return json.load(open(os.path.join(config.respaldo(), MARCA), encoding="utf-8")).get("version")
    except (OSError, ValueError, AttributeError):
        return None


def quitar():
    data, game, bundles = rutas()
    parchado = read_header(game)[0]["flags"] & 0x80
    meta_p = os.path.join(config.respaldo(), "meta.json")
    if not os.path.exists(meta_p):
        if parchado:
            sys.exit("El juego tiene una traducción aplicada, pero no encuentro su respaldo en esta PC "
                     f"({config.respaldo()}). Para volver al original usa Steam: Propiedades → Archivos "
                     "instalados → Verificar integridad. Después puedes volver a instalar la traducción.")
        print("El juego no tiene la traducción aplicada; no hay nada que quitar.")
        return
    meta = json.load(open(meta_p))
    if parchado:
        head = open(os.path.join(config.respaldo(), "head.bin"), "rb").read()
        with open(game, "r+b") as f:
            f.seek(0); f.write(head)
            f.truncate(meta["size"])
    elif os.path.getsize(game) != meta["size"]:
        head = open(os.path.join(config.respaldo(), "head.bin"), "rb").read()
        with open(game, "rb") as f:
            mismo = f.read(len(head)) == head
        if not (mismo and os.path.getsize(game) > meta["size"]):
            # el respaldo es de otra versión del juego: no se toca nada
            print("El juego no tiene la traducción aplicada; no hay nada que quitar.")
            return
        # instalación interrumpida mientras escribía al final del archivo: se recorta lo añadido
        with open(game, "r+b") as f:
            f.truncate(meta["size"])
    # los paquetes y la DLL se reponen siempre: una instalación interrumpida puede haberlos cambiado
    for p in glob.glob(os.path.join(config.respaldo(), "bundles", "*")):
        shutil.copyfile(p, os.path.join(bundles, os.path.basename(p)))
    dll_bak = os.path.join(config.respaldo(), DLL)
    if os.path.exists(dll_bak):
        shutil.copyfile(dll_bak, os.path.join(data, "Managed", DLL))
    marca = os.path.join(config.respaldo(), MARCA)
    if os.path.exists(marca):
        os.remove(marca)
    print("Juego restaurado al original en inglés.")


DLL = "Assembly-CSharp.dll"


def parchar_codigo(data):
    """Traduce los textos escritos directamente en el código (ver dll_textos.py)."""
    import dll_textos
    destino = os.path.join(data, "Managed", DLL)
    bak = os.path.join(config.respaldo(), DLL)
    if not os.path.exists(bak):
        shutil.copyfile(destino, bak)
    codigo = json.load(open(config.CODIGO_ES, encoding="utf-8"))
    mapa = {k: v for k, v in codigo.items() if not k.startswith("_")}
    nuevo, n, largos = dll_textos.reemplazar(open(bak, "rb").read(), mapa)
    nuevo, n_valores, fallidos = dll_textos.renombrar_valores(nuevo, codigo.get("_valores", {}))
    open(destino, "wb").write(nuevo)
    print("Textos del código:", n, "| opciones de ajustes:", n_valores)
    for en, es, a, b in largos:
        print(f"  AVISO: «{es}» tiene {a} caracteres y solo caben {b} (de «{en}»); se dejó en inglés")
    for v in fallidos:
        print(f"  AVISO: no cupo el nombre nuevo de {v}; se dejó en inglés")


def traductor_subtitulos():
    subs = {k.strip(): v for k, v in json.load(open(config.SUBTITULOS_ES, encoding="utf-8")).items()
            if not k.startswith("_")}
    return lambda t: subs.get(t.strip())


_TEXT_GUION = re.compile(r'("Text"\s*:\s*")((?:[^"\\]|\\.)*)(")')


def cambiar_guion(obj, mapa):
    """Traduce los valores "Text" de un guion (TextAsset JSON) sin tocar nada más."""
    t = obj.read()
    txt = t.m_Script if isinstance(t.m_Script, str) else bytes(t.m_Script).decode("utf-8")
    n = [0]

    def rep(m):
        en = json.loads('"' + m.group(2) + '"', strict=False)
        if en not in mapa:
            return m.group(0)
        n[0] += 1
        return m.group(1) + json.dumps(mapa[en], ensure_ascii=False)[1:-1] + m.group(3)
    nuevo = _TEXT_GUION.sub(rep, txt)
    if n[0]:
        t.m_Script = nuevo
        t.save()
    return n[0]


def respaldar(game, data_start):
    """Guarda la cabecera original. Si el juego se actualizó, rehace el respaldo."""
    meta_p = os.path.join(config.respaldo(), "meta.json")
    size = os.path.getsize(game)
    if os.path.exists(meta_p) and json.load(open(meta_p))["size"] == size:
        return
    if os.path.exists(meta_p):
        print("El juego cambió de versión: se rehace el respaldo.")
        shutil.rmtree(config.respaldo())
    os.makedirs(os.path.join(config.respaldo(), "bundles"))
    with open(game, "rb") as f:
        open(os.path.join(config.respaldo(), "head.bin"), "wb").write(f.read(data_start))
    json.dump({"size": size}, open(meta_p, "w"))


def traductor_fijos():
    fijos = json.load(open(config.FIJOS_ES, encoding="utf-8"))
    prefijos = [(k[len("@PREFIX:"):], v) for k, v in fijos.items() if k.startswith("@PREFIX:")]

    def tr(text):
        if text in fijos:
            return fijos[text]
        core = text.strip()
        if core in fijos:
            return text[:len(text) - len(text.lstrip())] + fijos[core] + text[len(text.rstrip()):]
        for p, v in prefijos:
            if core.startswith(p):
                return v
        return None
    return tr


def archivos_internos(env):
    out = {}
    for f in env.files.values():
        for name, sub in getattr(f, "files", {}).items():
            out[name] = sub
    return out


class ArchivosPerezosos(dict):
    """Archivos internos de un bundle, abiertos a medida que se piden.

    Hace de env.cabs, que es por donde UnityPy resuelve tanto las referencias
    entre archivos (PPtr -> Environment.find_file) como los datos de texturas y
    audio guardados en los .resS (ResourceReader): con esto todo se lee por
    demanda. Da igual cómo vengan las mayúsculas, como en UnityPy.
    """

    def __init__(self, env, lector, nodes):
        super().__init__()
        self.env, self.lector = env, lector
        self.ubic = {n[3].lower(): (n[0], n[1], n[3]) for n in nodes}
        self.reales = {k: v[2] for k, v in self.ubic.items()}   # minúsculas -> nombre real

    def __missing__(self, nombre):
        clave = nombre.lower()
        if clave in self:
            return dict.__getitem__(self, clave)
        if clave not in self.ubic:
            raise KeyError(nombre)
        inicio, tam, real = self.ubic[clave]
        r = EndianBinaryReader(Ventana(self.lector, inicio, tam))
        # los .resS no son archivos serializados: se dejan como flujo para leer trozos
        f = r if real.endswith((".resS", ".resource")) else ImportHelper.parse_file(r, self.env, real)
        self[clave] = f
        return f

    def get(self, nombre, default=None):
        try:
            return self[nombre]
        except KeyError:
            return default

    def cerrar(self):
        self.lector.close()


def abrir_perezoso(game, blocks, nodes, data_start, gen):
    """(env, archivos) de UnityPy sobre un bundle, leyendo solo lo que se pida.

    UnityPy.load() no sirve con data.unity3d: descomprimiría sus 18 GB en memoria
    y encima copiaría cada archivo interno (ver LectorBundle en bundle.py). El
    parche solo modifica 44 de los 341 archivos internos, 257 MB en total.
    """
    env = UnityPy.Environment()
    env.typetree_generator = gen
    archivos = ArchivosPerezosos(env, LectorBundle(game, blocks, data_start), nodes)
    env.cabs = archivos
    return env, archivos


def cambiar_texto(obj, tr, campo="m_text"):
    """Traduce el campo de texto de un componente (m_text en TextMeshPro, m_Text en UI.Text...)."""
    t = obj.read_typetree()
    es = tr(t[campo])
    if es and es != t[campo]:
        t[campo] = es
        # una sola palabra que no cabe: TMP la parte letra por letra («MOVE» → «MOVE/R»); mejor que se salga un poco
        if t.get("m_enableWordWrapping") and una_palabra(es):
            t["m_enableWordWrapping"] = 0
        guardar(obj, t)
        return True
    return False


def una_palabra(texto):
    return not re.search(r"\s", re.sub(r"<[^>]*>", "", texto).strip())


def no_partir(obj, es):
    """Igual que en cambiar_texto, para los textos que Gridly pone al vuelo (componente Translator)."""
    t = obj.read_typetree()
    if t.get("m_enableWordWrapping") and una_palabra(es):
        t["m_enableWordWrapping"] = 0
        guardar(obj, t)
        return True
    return False


def guardar(obj, t):
    """Guarda el árbol de tipos de un componente."""
    # en data.unity3d el árbol de tipos lee desalineada la cabecera (28 bytes): se conserva tal cual
    cabecera = bytes(obj.get_raw_data()[:28])
    obj.save_typetree(t)
    obj.set_raw_data(cabecera + bytes(obj.data[28:]))


QUESTLOG = ("level0", 6914)   # componente QuestLog: tipos de misión del registro de quehaceres


def etiquetas_misiones(ql, mapa):
    """Pone en español las claves de las etiquetas de misión («StoryEvent», «ChoreEvent»...).

    Al crear una misión, QuestLogEntry.SetupNewEntry busca la clave en Gridly (UI/StoryEvent),
    pero al cargar una partida LoadEntry la muestra tal cual. Con el texto en español como
    clave, LoadEntry lo muestra bien; SetupNewEntry lo encuentra en los registros UI/<español>
    que devuelve esta función para añadirlos a Gridly.
    """
    t = ql.read_typetree()
    nuevos = []
    for config in ("storyConfig", "romanticConfig", "taskConfig", "smallGoalConfig"):
        es = mapa.get("UI/" + t[config]["questTypeInfo"])
        if es:
            t[config]["questTypeInfo"] = es
            nuevos.append((es, [("enUS", es)], ""))
    guardar(ql, t)
    return nuevos


def destinos_imagenes():
    """[(paquete, archivo, path_id, png)] según traduccion/imagenes/imagenes.json.

    Cada entrada es {"png": ..., "destinos": [{"paquete", "file", "path_id"}, ...]}:
    una misma imagen traducida puede reemplazar varias copias del juego.
    Por compatibilidad también acepta {"png", "file", "path_id"} (en data.unity3d).
    """
    out = []
    for it in json.load(open(os.path.join(config.IMAGENES, "imagenes.json"), encoding="utf-8")):
        png = os.path.join(config.IMAGENES, it["png"])
        for d in it.get("destinos") or [dict(paquete="data.unity3d", file=it["file"], path_id=it["path_id"])]:
            out.append((d.get("paquete", "data.unity3d"), d["file"], int(d["path_id"]), png))
    return out


_TAM_FORMATO = {0: 4, 1: 2, 2: 1, 3: 1, 4: 2, 5: 2, 6: 1, 7: 1, 8: 2, 9: 2, 10: 4, 11: 4}
_sprites_por_archivo = {}


def _sprites_de(sf):
    """{path_id de textura: [objetos Sprite]} de un archivo interno (con caché)."""
    clave = id(sf)
    if clave not in _sprites_por_archivo:
        idx = {}
        for o in sf.objects.values():
            if o.type.name == "Sprite":
                try:
                    t = o.read_typetree()
                except Exception:
                    continue
                tx = t["m_RD"]["texture"]
                if tx["m_FileID"] == 0:
                    idx.setdefault(tx["m_PathID"], []).append(o)
        _sprites_por_archivo[clave] = idx
    return _sprites_por_archivo[clave]


def malla_rectangular(sprite, ancho_tex, alto_tex):
    """Cambia la malla del sprite por un rectángulo que cubre toda su imagen.

    Unity recorta muchos sprites con una malla «ajustada» a la silueta del
    dibujo original; si la imagen traducida tiene las letras en otro sitio, lo
    que cae fuera de esa silueta no se ve.
    """
    t = sprite.read_typetree()
    rd = t["m_RD"]
    tr, off, piv, ppu = rd["textureRect"], rd["textureRectOffset"], t["m_Pivot"], t["m_PixelsToUnits"]
    x0 = (off["x"] - piv["x"] * t["m_Rect"]["width"]) / ppu
    y0 = (off["y"] - piv["y"] * t["m_Rect"]["height"]) / ppu
    x1, y1 = x0 + tr["width"] / ppu, y0 + tr["height"] / ppu
    u0, v0 = tr["x"] / ancho_tex, tr["y"] / alto_tex
    u1, v1 = (tr["x"] + tr["width"]) / ancho_tex, (tr["y"] + tr["height"]) / alto_tex
    esquinas = [((x0, y0), (u0, v0)), ((x1, y0), (u1, v0)), ((x0, y1), (u0, v1)), ((x1, y1), (u1, v1))]
    canales = rd["m_VertexData"]["m_Channels"]
    pasos = {}
    for c in canales:
        if c["dimension"]:
            fin = c["offset"] + _TAM_FORMATO[c["format"]] * (c["dimension"] & 0xF)
            pasos[c["stream"]] = max(pasos.get(c["stream"], 0), fin)
    datos = bytearray()
    for s in sorted(pasos):
        while len(datos) % 16:
            datos += b"\0"
        for (px, py), (u, v) in esquinas:
            vert = bytearray(pasos[s])
            for i, c in enumerate(canales):
                if c["stream"] != s or not c["dimension"]:
                    continue
                if i == 0:                      # posición
                    struct.pack_into("<3f", vert, c["offset"], px, py, 0.0)
                elif i == 4:                    # texcoord0
                    struct.pack_into("<2f", vert, c["offset"], u, v)
                elif i == 12 and c["format"] == 0:   # peso del hueso
                    struct.pack_into("<f", vert, c["offset"], 1.0)
            datos += vert
    rd["m_VertexData"]["m_VertexCount"] = 4
    rd["m_VertexData"]["m_DataSize"] = bytes(datos)
    rd["m_IndexBuffer"] = list(struct.pack("<6H", 0, 2, 1, 1, 2, 3))
    sub = rd["m_SubMeshes"][0]
    sub.update(firstByte=0, indexCount=6, firstVertex=0, vertexCount=4, baseVertex=0)
    sub["localAABB"] = {"m_Center": {"x": (x0 + x1) / 2, "y": (y0 + y1) / 2, "z": 0.0},
                        "m_Extent": {"x": (x1 - x0) / 2, "y": (y1 - y0) / 2, "z": 0.0}}
    rd["m_SubMeshes"] = [sub]
    sprite.save_typetree(t)


def cambiar_imagen(obj, png):
    from PIL import Image
    tex = obj.read()
    tex.image = Image.open(png).convert("RGBA")
    tex.save()
    for sp in _sprites_de(obj.assets_file).get(obj.path_id, []):
        malla_rectangular(sp, tex.m_Width, tex.m_Height)


def ubicaciones_fuentes():
    """{paquete: [entradas]} de datos/fuentes_ubicaciones.json."""
    out = {}
    for u in json.load(open(config.FUENTES_UBIC, encoding="utf-8"))["fuentes"]:
        out.setdefault(u["paquete"], []).append(u)
    return out


def parchar_paquetes(gen, ubic, tr, bundles, imagenes, fuentes_ubic):
    textos, imgs = {}, {}
    for r in ubic:
        if r["bundle"] != "data.unity3d":
            textos.setdefault(r["bundle"], set()).add((r["file"], r["pid"], r.get("campo", "m_text")))
    for paquete, f, pid, png in imagenes:
        if paquete != "data.unity3d":
            imgs.setdefault(paquete, []).append((f, pid, png))
    fts = {k: v for k, v in fuentes_ubic.items() if k != "data.unity3d"}
    n_txt = n_img = n_fuentes = 0
    for name in sorted(set(textos) | set(imgs) | set(fts)):
        path = os.path.join(bundles, name)
        bak = os.path.join(config.respaldo(), "bundles", name)
        if not os.path.exists(bak):
            shutil.copyfile(path, bak)
        env = UnityPy.load(bak); env.typetree_generator = gen
        sfs = archivos_internos(env)
        n = sum(cambiar_texto(sfs[f].objects[pid], tr, c) for f, pid, c in textos.get(name, ()))
        for f, pid, png in imgs.get(name, ()):
            cambiar_imagen(sfs[f].objects[pid], png)
        cambiadas, letras = fuentes.completar(sfs, fts.get(name, ()))
        if n or imgs.get(name) or cambiadas:
            open(path, "wb").write(env.file.save(packer="lz4"))
        n_txt += n; n_img += len(imgs.get(name, ())); n_fuentes += letras
    print(f"Paquetes pequeños: {n_txt} textos fijos, {n_img} imágenes, {n_fuentes} letras añadidas a fuentes")


def cargar_traduccion(raw_gridly):
    """Mapa «Categoría/ID» → español (más «\\0en:texto» → español para registros repetidos).

    Usa datos/compilado/traduccion_es.json si existe (lo crea compilar.py). Si no
    (la versión pública no trae el inglés), lee traduccion/es/*.json y saca el
    inglés de la propia tabla del juego.
    """
    if os.path.exists(config.COMPILADO):
        return json.load(open(config.COMPILADO, encoding="utf-8"))
    mapa = {}
    for f in sorted(glob.glob(os.path.join(config.ES_DIR, "*.json"))):
        for x in json.load(open(f, encoding="utf-8")):
            mapa[x["id"]] = x["es"]
    _, grids, _ = gridly.parse(raw_gridly)
    for g in grids:
        for rid, cols, _ in g["recs"]:
            es = mapa.get(f"{g['name']}/{rid}")
            if es is not None:
                for _, texto in cols:
                    mapa.setdefault("\0en:" + texto, es)
    return mapa


def aplicar(version=None):
    """Aplica la traducción. version: la del instalador, que queda anotada en el respaldo (MARCA)."""
    if not os.path.exists(config.COMPILADO) and not glob.glob(os.path.join(config.ES_DIR, "*.json")):
        sys.exit("No encontré la traducción (traduccion/es).")
    data, game, bundles = rutas()
    if read_header(game)[0]["flags"] & 0x80:
        print("El juego ya tiene una traducción aplicada; quitándola primero...")
        quitar()
    h, hash16, blocks, nodes, hdr_end, data_start = read_header(game)
    respaldar(game, data_start)

    gen = TypeTreeGenerator(UNITY)
    gen.load_local_dll_folder(os.path.join(data, "Managed"))
    ubic = json.load(open(config.UBICACIONES, encoding="utf-8"))
    tr_fijos = traductor_fijos()
    imagenes = destinos_imagenes()
    fuentes_ubic = ubicaciones_fuentes()
    parchar_paquetes(gen, ubic, tr_fijos, bundles, imagenes, fuentes_ubic)

    print("Leyendo data.unity3d...")
    env, sfs = abrir_perezoso(game, blocks, nodes, data_start, gen)
    modificados = set()

    # 1) tabla Gridly: diálogos, menús, objetos, misiones...
    obj = sfs["resources.assets"].objects[gridly.GRIDLY_PATH_ID]
    raw = obj.get_raw_data()
    mapa = cargar_traduccion(raw)
    usados = [0]

    def tr(grid, rid, col, text):
        es = mapa.get(f"{grid}/{rid}")
        if es is None:
            es = mapa.get("\0en:" + text)
        if es is None:
            return text
        usados[0] += 1
        # se conservan los espacios del inicio y del final del inglés (el juego pega textos)
        return text[:len(text) - len(text.lstrip())] + es.strip() + text[len(text.rstrip()):]
    nuevos = etiquetas_misiones(sfs[QUESTLOG[0]].objects[QUESTLOG[1]], mapa)
    obj.set_raw_data(gridly.build(raw, tr, {"UI": nuevos}))
    modificados.update(("resources.assets", QUESTLOG[0]))
    print("Textos de diálogos y menús:", usados[0])
    print("Etiquetas de misiones:", len(nuevos))

    # 2) textos fijos en escenas
    n = 0
    cambiados = set()
    for r in ubic:
        if r["bundle"] == "data.unity3d" and cambiar_texto(sfs[r["file"]].objects[r["pid"]], tr_fijos, r.get("campo", "m_text")):
            n += 1; modificados.add(r["file"]); cambiados.add((r["file"], r["pid"]))
    print("Textos fijos en escenas:", n)

    # 2a) textos que pone Gridly al abrir la pantalla («Moderno» en Controles): que no se partan.
    # Los que ya cambió el paso 2 tienen su propia regla (UnityPy los releería sin ese cambio).
    n = 0
    for r in json.load(open(config.TRADUCTORES_UBIC, encoding="utf-8")):
        es = mapa.get(r["clave"])
        if es and (r["file"], r["pid"]) not in cambiados and no_partir(sfs[r["file"]].objects[r["pid"]], es):
            n += 1; modificados.add(r["file"])
    print("Textos de Gridly sin partir palabras:", n)

    # 2b) subtítulos de cinemáticas (SubtitleClip)
    tr_subs = traductor_subtitulos()
    n = 0
    for r in json.load(open(config.SUBTITULOS_UBIC, encoding="utf-8")):
        o = sfs[r["file"]].objects[r["pid"]]
        t = o.read_typetree()
        es = tr_subs(t["subtitleText"])
        if es:
            t["subtitleText"] = es; o.save_typetree(t); n += 1
            modificados.add(r["file"])
    print("Subtítulos de cinemáticas:", n)

    # 2c) guiones con texto en inglés escrito directamente (TextAsset)
    guiones = {k: v for k, v in json.load(open(config.GUIONES_ES, encoding="utf-8")).items() if not k.startswith("_")}
    n = 0
    for r in json.load(open(config.GUIONES_UBIC, encoding="utf-8"))["guiones"]:
        if r["paquete"] == "data.unity3d":
            c = cambiar_guion(sfs[r["file"]].objects[r["pid"]], guiones)
            if c:
                n += c; modificados.add(r["file"])
    print("Textos en guiones:", n)

    # 3) imágenes con texto
    n = 0
    for paquete, f, pid, png in imagenes:
        if paquete == "data.unity3d":
            cambiar_imagen(sfs[f].objects[pid], png)
            modificados.add(f); n += 1
    print("Imágenes en escenas:", n)

    # 4) letras del español que les faltan a algunas fuentes (ver fuentes.py)
    cambiadas, letras = fuentes.completar(sfs, fuentes_ubic.get("data.unity3d", ()))
    modificados |= cambiadas
    print("Letras añadidas a fuentes:", letras)

    nuevos = {name: sfs[name].save() for name in modificados}
    sfs.cerrar()
    del env, sfs, obj
    gc.collect()

    # 5) añadir al final del bundle y escribir un índice nuevo
    relleno = data_start - hdr_end            # bytes del índice viejo -> bloque de relleno
    orig_u = sum(b[0] for b in blocks)
    new_blocks = [[relleno, relleno, 0]] + [list(b) for b in blocks]
    payload = bytearray()
    colocados = {}
    cur = relleno + orig_u
    for name, d in nuevos.items():
        colocados[name.lower()] = (cur, len(d))
        for i in range(0, len(d), BLOCK):
            chunk = d[i:i + BLOCK]
            c = lz4.block.compress(chunk, mode="high_compression", store_size=False)
            payload += c
            new_blocks.append([len(chunk), len(c), 3])
        cur += len(d)

    info = bytearray(hash16)
    info += struct.pack(">i", len(new_blocks))
    for u, c, fl in new_blocks:
        info += struct.pack(">IIH", u, c, fl)
    info += struct.pack(">i", len(nodes))
    for off, sz, fl, name in nodes:
        off, sz = colocados.get(name.lower(), (relleno + off, sz))
        info += struct.pack(">qqI", off, sz, fl) + name.encode() + b"\0"
    cinfo = lz4.block.compress(bytes(info), mode="high_compression", store_size=False)

    orig_size = json.load(open(os.path.join(config.respaldo(), "meta.json")))["size"]
    total = orig_size + len(payload) + len(cinfo)
    flags = (h["flags"] & ~0x3f) | 3 | 0x80
    with open(game, "rb") as f:
        head = bytearray(f.read(hdr_end))
    p = head.index(h["urev"].encode() + b"\0") + len(h["urev"]) + 1
    head[p:p + 20] = struct.pack(">qIII", total, len(cinfo), len(info), flags)

    with open(game, "r+b") as f:
        f.seek(orig_size)
        f.write(payload)
        f.write(cinfo)
        f.truncate(total)
        f.seek(0)
        f.write(head)
    parchar_codigo(data)
    import datetime
    json.dump({"version": version, "fecha": f"{datetime.datetime.now():%Y-%m-%d %H:%M}"},
              open(os.path.join(config.respaldo(), MARCA), "w", encoding="utf-8"))
    print("Traducción aplicada. ¡Listo para jugar!")


if __name__ == "__main__":
    accion = sys.argv[1] if len(sys.argv) > 1 else ""
    if accion == "aplicar":
        aplicar()
    elif accion == "quitar":
        quitar()
    else:
        print(__doc__)
