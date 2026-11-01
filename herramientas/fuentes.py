"""Añade a las fuentes TextMeshPro del juego las letras del español que les faltan.

Varias fuentes del juego son «estáticas»: su atlas solo trae las letras del
inglés. Cuando un texto usa «á» o «ñ», TextMeshPro la saca de otra fuente y se
ve distinta. Aquí se dibujan esas letras en el atlas de la propia fuente, con
el mismo campo de distancia (SDF) que usa TextMeshPro, y se registran en sus
tablas de glifos y caracteres.

Cada letra nueva se saca de una de tres fuentes:
  ttf       el archivo de la fuente (Merriweather es OFL y va en herramientas/fuentes/)
  donante   otra fuente TMP del juego con el mismo diseño que sí tiene la letra
  componer  piezas de la propia fuente (vocal + acento, n + tilde, ? girado...)

Uso desde parche.py: completar(archivos, ubicaciones) con los archivos internos
de un paquete y sus entradas de datos/fuentes_ubicaciones.json.
"""
import os, json, hashlib
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont

import config
DIR = os.path.join(config.RAIZ, "herramientas")   # también funciona dentro del .exe
LETRAS = "áéíóúÁÉÍÓÚñÑüÜ¿¡«»“”‘’—–…"
K = 8          # sobremuestreo al dibujar cada letra
INDICE_BASE = 60000   # índices de glifo nuevos (no chocan con los de la fuente)

RECETAS = {
    "Merriweather-BoldItalic SDF": dict(ttf=os.path.join(DIR, "fuentes", "Merriweather-BoldItalic.ttf")),
    "Adorn Serif SDglowF": dict(donante="Adorn Serif SDF"),
    "Adornwhite": dict(donante="Adorn Serif SDF"),
    "Adornwhite Stroke": dict(donante="Adorn Serif SDF"),
    "Adornwhite brown stroke": dict(donante="Adorn Serif SDF"),
    "adornblack": dict(donante="Adorn Serif SDF"),
    "CustomFont_Mister Pixel Regular_0 SDF": dict(donante="Mister Pixel Regular_0 SDF"),
    # gótica de los títulos: no hay TTF ni otra fuente igual; se arman con sus propias piezas
    "candlebright_sample SDF": dict(componer=True),
    "candlebrightred": dict(componer=True),
}

_cache = {}


# ---------- dibujo de letras ----------

def _sdf(mascara, origen, bx, by, w, h, pad):
    """Campo de distancia de una letra (alto+2pad x ancho+2pad, de arriba abajo)."""
    m = (mascara > 127).astype(np.uint8)
    d = (cv2.distanceTransform(m, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
         - cv2.distanceTransform(1 - m, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)) / K
    ox, oy = origen
    cols = np.round(ox + (bx - pad + np.arange(w + 2 * pad) + 0.5) * K).astype(int)
    filas = np.round(oy - (by + pad - np.arange(h + 2 * pad) - 0.5) * K).astype(int)
    cols, filas = np.clip(cols, 0, m.shape[1] - 1), np.clip(filas, 0, m.shape[0] - 1)
    v = 0.5 + d[np.ix_(filas, cols)] / (2 * (pad + 1))
    return np.round(np.clip(v, 0, 1) * 255).astype(np.uint8)


def _caja(mascara, origen):
    ys, xs = np.nonzero(mascara > 127)
    if not len(xs):
        return None
    ox, oy = origen
    return (xs.min() - ox) / K, (oy - ys.min()) / K, (xs.max() + 1 - xs.min()) / K, (ys.max() + 1 - ys.min()) / K


def _desde_ttf(ttf, letra, puntos):
    f = ImageFont.truetype(ttf, puntos * K)
    lado = puntos * K * 3
    img = Image.new("L", (lado, lado), 0)
    origen = (puntos * K, int(puntos * K * 1.8))
    ImageDraw.Draw(img).text(origen, letra, font=f, fill=255, anchor="ls")
    return np.array(img), origen, f.getlength(letra) / K


def _desde_donante(don, letra, puntos):
    """Agranda (o achica) el SDF de la letra en la fuente donante y lo vuelve silueta."""
    g = don["glifos"].get(don["caracteres"].get(ord(letra)))
    if not g or not g["m_GlyphRect"]["m_Width"]:
        return None
    r, m, pad = g["m_GlyphRect"], g["m_Metrics"], don["pad"]
    H = don["atlas"].shape[0]
    zona = don["atlas"][H - r["m_Y"] - r["m_Height"] - pad:H - r["m_Y"] + pad,
                        r["m_X"] - pad:r["m_X"] + r["m_Width"] + pad].astype(np.float32)
    s = puntos / don["puntos"] * K
    zona = cv2.resize(zona, (round(zona.shape[1] * s), round(zona.shape[0] * s)), interpolation=cv2.INTER_CUBIC)
    marco = int(puntos * K)
    img = np.zeros((zona.shape[0] + 2 * marco, zona.shape[1] + 2 * marco), np.uint8)
    img[marco:marco + zona.shape[0], marco:marco + zona.shape[1]] = (zona > 127.5) * 255
    # el pixel (0,0) de la zona está en x = bearingX - pad, y = bearingY + pad (unidades de la donante)
    ox = marco - (m["m_HorizontalBearingX"] - pad) * s
    oy = marco + (m["m_HorizontalBearingY"] + pad) * s
    return img, (ox, oy), m["m_HorizontalAdvance"] * puntos / don["puntos"]


def _pieza(don, letra, puntos):
    """Silueta recortada de una letra de la fuente: (máscara, izquierda, arriba, avance), en píxeles ×K
    relativos al origen (arriba es negativo: por encima de la línea base)."""
    res = _desde_donante(don, letra, puntos)
    if not res:
        return None
    img, (ox, oy), avance = res
    ys, xs = np.nonzero(img)
    m = img[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    return m, xs.min() - ox, ys.min() - oy, avance


def _girar(m, grados, escala=1.0):
    h, w = m.shape
    M = cv2.getRotationMatrix2D((w / 2, h / 2), grados, escala)
    c, s = abs(M[0, 0]), abs(M[0, 1])
    W, H = int(h * s + w * c) + 2, int(h * c + w * s) + 2
    M[0, 2] += W / 2 - w / 2; M[1, 2] += H / 2 - h / 2
    r = cv2.warpAffine(m, M, (W, H), flags=cv2.INTER_LINEAR)
    ys, xs = np.nonzero(r > 127)
    return ((r > 127) * 255).astype(np.uint8)[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def _componer(don, letra, puntos):
    """Arma la letra con piezas de la propia fuente: vocal + acento (apóstrofo inclinado),
    n + tilde dibujada, u + dos puntos, y ¿ ¡ girando ? y !."""
    import unicodedata
    base, marca = None, None
    nfd = unicodedata.normalize("NFD", letra)
    if len(nfd) == 2 and nfd[1] in "́̃̈":
        base, marca = nfd[0], {"́": "agudo", "̃": "tilde", "̈": "dieresis"}[nfd[1]]
    elif letra in "¿¡":
        base, marca = {"¿": "?", "¡": "!"}[letra], "girar"
    else:
        return None
    p = _pieza(don, base, puntos)
    if not p:
        return None
    m, x0, y0, avance = p
    if base == "i" and marca:
        # i sin punto: se queda la pieza más grande
        n, lab, st, _ = cv2.connectedComponentsWithStats((m > 127).astype(np.uint8))
        if n > 2:
            m = ((lab == 1 + np.argmax(st[1:, cv2.CC_STAT_AREA])) * 255).astype(np.uint8)
            ys, xs = np.nonzero(m); y0 += ys.min(); x0 += xs.min()
            m = m[ys.min():, xs.min():xs.max() + 1]
    piezas = [(m, x0, y0)]
    alto = m.shape[0]
    centro = x0 + m.shape[1] / 2
    hueco = 0.08 * puntos * K
    if marca == "girar":
        g = np.rot90(m, 2)
        piezas = [(g, x0, y0 + 0.2 * alto)]
    elif marca == "agudo":
        ap = _pieza(don, "'", puntos)
        if not ap:
            return None
        a = _girar(ap[0], -35, 0.85)
        piezas.append((a, centro - a.shape[1] / 2 + 0.06 * puntos * K, y0 - hueco - a.shape[0]))
    elif marca == "dieresis":
        pt = _pieza(don, ".", puntos)
        if not pt:
            return None
        d = _girar(pt[0], 0, 0.8)
        sep = d.shape[1] * 0.7
        for x in (centro - sep / 2 - d.shape[1], centro + sep / 2):
            piezas.append((d, x, y0 - hueco - d.shape[0]))
    elif marca == "tilde":
        dt = cv2.distanceTransform((m > 127).astype(np.uint8), cv2.DIST_L2, 5)
        grosor = max(2, int(np.percentile(dt[m > 127], 90) * 1.6))
        ancho, amp = m.shape[1] * 0.75, 0.05 * puntos * K
        t = np.linspace(0, 1, 60)
        pts = np.stack([t * ancho, amp * (1 - np.sin(t * 2 * np.pi))], 1) + grosor
        lienzo = np.zeros((int(2 * amp + 2 * grosor) + 2, int(ancho + 2 * grosor) + 2), np.uint8)
        cv2.polylines(lienzo, [pts.astype(np.int32)], False, 255, grosor, cv2.LINE_AA)
        lienzo = ((lienzo > 127) * 255).astype(np.uint8)
        piezas.append((lienzo, centro - lienzo.shape[1] / 2, y0 - hueco - lienzo.shape[0]))
    lado = puntos * K * 4
    img = np.zeros((lado, lado), np.uint8)
    origen = (puntos * K * 1.5, puntos * K * 2.5)
    for pm, px, py in piezas:
        x, y = int(round(origen[0] + px)), int(round(origen[1] + py))
        img[y:y + pm.shape[0], x:x + pm.shape[1]] = np.maximum(img[y:y + pm.shape[0], x:x + pm.shape[1]], pm)
    return img, origen, avance


# ---------- atlas ----------

def _ocupado(t, alto, ancho):
    ocup = np.zeros((alto, ancho), bool)
    pad = t["m_AtlasPadding"]
    for g in t["m_GlyphTable"]:
        r = g["m_GlyphRect"]
        if r["m_Width"]:
            y0 = max(0, alto - r["m_Y"] - r["m_Height"] - pad - 1)
            ocup[y0:alto - r["m_Y"] + pad + 1, max(0, r["m_X"] - pad - 1):r["m_X"] + r["m_Width"] + pad + 1] = True
    return ocup


def _hueco(ocup, h, w):
    """Busca un rectángulo libre de h x w (de arriba abajo). Devuelve (fila, col) o None."""
    H, W = ocup.shape
    if h > H or w > W:
        return None
    integ = np.pad(ocup.astype(np.int32).cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    suma = integ[h:, w:] - integ[:-h, w:] - integ[h:, :-w] + integ[:-h, :-w]
    libres = np.argwhere(suma == 0)
    if not len(libres):
        return None
    f, c = libres[np.lexsort((libres[:, 1], -libres[:, 0]))][0]   # lo más abajo posible
    return int(f), int(c)


def huella(t):
    return hashlib.md5(json.dumps([t["m_GlyphTable"], t["m_CharacterTable"]], sort_keys=True, default=str).encode()).hexdigest()


def generar(t, atlas, receta, donante=None):
    """Devuelve (t nuevo, atlas nuevo de arriba abajo, letras añadidas). No modifica los originales."""
    t = json.loads(json.dumps(t, default=str))
    atlas = atlas.copy()
    pad, puntos = t["m_AtlasPadding"], t["m_FaceInfo"]["m_PointSize"]
    tiene = {c["m_Unicode"] for c in t["m_CharacterTable"]}
    nuevas = []
    for letra in LETRAS:
        if ord(letra) in tiene:
            continue
        if "ttf" in receta:
            res = _desde_ttf(receta["ttf"], letra, puntos)
        elif receta.get("componer"):
            res = _componer(donante, letra, puntos)
        else:
            res = _desde_donante(donante, letra, puntos)
        if not res:
            continue
        mascara, origen, avance = res
        caja = _caja(mascara, origen)
        if not caja:
            continue
        bx, by, w, h = caja
        w, h = int(np.ceil(w)), int(np.ceil(h))
        nuevas.append((letra, _sdf(mascara, origen, bx, by, w, h, pad), bx, by, w, h, avance))

    ocup = _ocupado(t, *atlas.shape)
    for crecer in range(3):
        colocadas, prueba = [], ocup.copy()
        for letra, img, *_ in sorted(nuevas, key=lambda n: -n[1].shape[0]):
            pos = _hueco(prueba, img.shape[0] + 2, img.shape[1] + 2)
            if pos is None:
                break
            prueba[pos[0]:pos[0] + img.shape[0] + 2, pos[1]:pos[1] + img.shape[1] + 2] = True
            colocadas.append((letra, pos))
        if len(colocadas) == len(nuevas):
            break
        # no caben: se duplica el alto; lo viejo queda abajo (las coordenadas de TMP cuentan desde abajo)
        atlas = np.vstack([np.zeros_like(atlas), atlas])
        ocup = np.vstack([np.zeros_like(ocup), ocup])
    else:
        raise RuntimeError(f"No caben las letras nuevas en el atlas de {t['m_Name']}")

    H = atlas.shape[0]
    pos = dict(colocadas)
    indice = max([INDICE_BASE - 1] + [g["m_Index"] for g in t["m_GlyphTable"]]) + 1
    for letra, img, bx, by, w, h, avance in nuevas:
        f, c = pos[letra]
        f, c = f + 1, c + 1
        atlas[f:f + img.shape[0], c:c + img.shape[1]] = img
        x, y = c + pad, H - (f + pad) - h
        t["m_GlyphTable"].append(dict(m_Index=indice, m_Metrics=dict(
            m_Width=float(w), m_Height=float(h), m_HorizontalBearingX=float(bx), m_HorizontalBearingY=float(by),
            m_HorizontalAdvance=float(avance)), m_GlyphRect=dict(m_X=x, m_Y=y, m_Width=w, m_Height=h),
            m_Scale=1.0, m_AtlasIndex=0, m_ClassDefinitionType=0))
        t["m_CharacterTable"].append(dict(m_ElementType=1, m_Unicode=ord(letra), m_GlyphIndex=indice, m_Scale=1.0))
        t["m_UsedGlyphRects"].append(dict(m_X=x - pad, m_Y=y - pad, m_Width=w + 2 * pad, m_Height=h + 2 * pad))
        indice += 1
    t["m_AtlasHeight"] = H
    t["m_CreationSettings"]["atlasHeight"] = H
    return t, atlas, "".join(n[0] for n in nuevas)


# ---------- lectura y escritura en los archivos del juego ----------

def _indice(archivos):
    """(buscar, real): consultar `archivos` por nombre sin recorrerlo.

    Para data.unity3d parche.py pasa un mapa perezoso (341 archivos internos,
    18 GB descomprimidos): recorrerlo los abriría todos. Su atributo `reales`
    dice qué nombres hay sin abrir ninguno; los paquetes chicos de
    StreamingAssets llegan como dict normal.
    """
    reales = getattr(archivos, "reales", None) or {k.lower(): k for k in archivos}
    return (lambda n: archivos.get(reales.get(n, n))), (lambda n: reales.get(n, n))


def _obj(buscar, sf, ptr):
    if not ptr["m_PathID"]:
        return None
    if ptr["m_FileID"]:
        sf = buscar(os.path.basename(sf.externals[ptr["m_FileID"] - 1].path).lower())
    return sf.objects.get(ptr["m_PathID"]) if sf else None


def _leer_atlas(obj_tex):
    tex = obj_tex.read()
    return np.array(tex.image.getchannel("A"))


def _escribir_atlas(obj_tex, atlas):
    t = obj_tex.read_typetree()
    if t["m_TextureFormat"] != 1:
        raise RuntimeError("El atlas no es Alpha8")
    t["m_Width"], t["m_Height"] = atlas.shape[1], atlas.shape[0]
    t["m_MipCount"] = 1
    t["m_CompleteImageSize"] = atlas.size
    t["image data"] = np.flipud(atlas).tobytes()     # Unity guarda las filas de abajo arriba
    t["m_StreamData"] = dict(offset=0, size=0, path="")
    obj_tex.save_typetree(t)


def _ajustar_material(obj_mat, alto):
    t = obj_mat.read_typetree()
    flotantes = t["m_SavedProperties"]["m_Floats"]
    for i, par in enumerate(flotantes):
        nombre = par[0] if isinstance(par, (list, tuple)) else par.get("first")
        if nombre == "_TextureHeight":
            flotantes[i] = (nombre, float(alto)) if isinstance(par, (list, tuple)) else dict(first=nombre, second=float(alto))
    obj_mat.save_typetree(t)


def _donante(buscar, ubic):
    sf = buscar(ubic["file"].lower())
    o = sf.objects.get(ubic["pid"]) if sf else None
    if not o:
        return None
    t = o.read_typetree()
    return dict(atlas=_leer_atlas(_obj(buscar, sf, t["m_AtlasTextures"][0])),
                glifos={g["m_Index"]: g for g in t["m_GlyphTable"]},
                caracteres={c["m_Unicode"]: c["m_GlyphIndex"] for c in t["m_CharacterTable"]},
                pad=t["m_AtlasPadding"], puntos=t["m_FaceInfo"]["m_PointSize"])


def completar(archivos, ubicaciones):
    """Completa las fuentes de `ubicaciones` (entradas de datos/fuentes_ubicaciones.json) dentro de `archivos`.

    Devuelve el conjunto de archivos internos modificados (con el nombre tal como viene en `archivos`).
    """
    buscar, real = _indice(archivos)
    modificados, letras_total = set(), 0
    for u in ubicaciones:
        nombre, f = u["nombre"], u["file"].lower()
        sf = buscar(f)
        o = sf.objects.get(u["pid"]) if sf else None
        if not o:
            print(f"  AVISO: no encontré la fuente {nombre} ({u['file']}:{u['pid']})")
            continue
        t = o.read_typetree()
        if t.get("m_Name") != nombre:
            print(f"  AVISO: en {u['file']}:{u['pid']} está «{t.get('m_Name')}», no «{nombre}»; se omite")
            continue
        clave = (nombre, huella(t))
        if clave not in _cache:
            receta = RECETAS[nombre]
            don = None
            if receta.get("componer"):
                don = _donante(buscar, u)            # la propia fuente
            elif "donante" in receta:
                don = _donante(buscar, u["donante"]) if "donante" in u else None
                if not don:
                    print(f"  AVISO: no encontré la fuente {receta['donante']} para completar {nombre}")
                    continue
            atlas = _leer_atlas(_obj(buscar, sf, t["m_AtlasTextures"][0]))
            _cache[clave] = generar(t, atlas, receta, don)
        nuevo, atlas, letras = _cache[clave]
        if not letras:
            continue
        # solo se copian las tablas: las referencias (script, material, atlas) son propias de cada copia
        alto_original = t["m_AtlasHeight"]
        for campo in ("m_GlyphTable", "m_CharacterTable", "m_UsedGlyphRects", "m_AtlasHeight"):
            t[campo] = nuevo[campo]
        t["m_CreationSettings"]["atlasHeight"] = nuevo["m_AtlasHeight"]
        # En data.unity3d el árbol de tipos generado lee la cabecera (m_GameObject, m_Enabled,
        # m_Script: 28 bytes) desalineada; se conservan los bytes originales tal cual.
        cabecera = bytes(o.get_raw_data()[:28])
        o.save_typetree(t)
        o.set_raw_data(cabecera + bytes(o.data[28:]))   # o.data: lo que acaba de escribir save_typetree
        _escribir_atlas(_obj(buscar, sf, t["m_AtlasTextures"][0]), atlas)
        if atlas.shape[0] != alto_original:
            mat = _obj(buscar, sf, t["material"])
            if mat:
                _ajustar_material(mat, atlas.shape[0])
        modificados.add(real(f))
        letras_total += len(letras)
    return modificados, letras_total
