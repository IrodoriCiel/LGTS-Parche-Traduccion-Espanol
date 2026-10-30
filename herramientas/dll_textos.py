"""Lee y reemplaza textos escritos directamente en el código del juego (Assembly-CSharp.dll).

Los textos literales de C# viven en el «#US heap» de los metadatos .NET. Cada
entrada es: longitud comprimida + texto UTF-16 + 1 byte final. No se pueden
alargar sin reconstruir el ensamblado, así que el texto en español debe tener
como máximo el mismo número de caracteres que el inglés; si es más corto, se
rellena con espacios repartidos a ambos lados para que siga centrado.

  python dll_textos.py listar      muestra los textos que parecen de interfaz
"""
import struct, re, sys


def _heap_us(d):
    """(inicio, tamaño) del heap #US."""
    return _flujos(d)["#US"]


def _flujos(d):
    """{nombre: (inicio, tamaño)} de los flujos de metadatos (#~, #Strings, #US...)."""
    pe = struct.unpack_from("<I", d, 0x3C)[0]
    nsec = struct.unpack_from("<H", d, pe + 6)[0]
    opt = pe + 24
    magic = struct.unpack_from("<H", d, opt)[0]
    dirs = opt + (96 if magic == 0x10B else 112)
    cli_rva = struct.unpack_from("<I", d, dirs + 14 * 8)[0]
    secs = opt + struct.unpack_from("<H", d, pe + 20)[0]

    def rva2off(rva):
        for i in range(nsec):
            s = secs + i * 40
            va, vsz, raw = struct.unpack_from("<III", d, s + 8)[0], struct.unpack_from("<I", d, s + 8)[0], struct.unpack_from("<I", d, s + 20)[0]
            va = struct.unpack_from("<I", d, s + 12)[0]
            vsz = struct.unpack_from("<I", d, s + 8)[0]
            if va <= rva < va + max(vsz, struct.unpack_from("<I", d, s + 16)[0]):
                return rva - va + raw
        raise ValueError("RVA fuera de secciones")
    cli = rva2off(cli_rva)
    meta = rva2off(struct.unpack_from("<I", d, cli + 8)[0])
    assert d[meta:meta + 4] == b"BSJB"
    vlen = struct.unpack_from("<I", d, meta + 12)[0]
    p = meta + 16 + vlen + 2
    n = struct.unpack_from("<H", d, p)[0]; p += 2
    flujos = {}
    for _ in range(n):
        off, size = struct.unpack_from("<II", d, p); p += 8
        e = d.index(b"\0", p); nombre = d[p:e].decode(); p = (e + 4) & ~3
        flujos[nombre] = (meta + off, size)
    return flujos


def _tablas(d):
    """Dónde empiezan las tablas TypeDef y Field del flujo #~ y cómo son sus filas (ECMA-335 II.22)."""
    ini, _ = _flujos(d)["#~"]
    tam_heaps = d[ini + 6]
    validas = struct.unpack_from("<Q", d, ini + 8)[0]
    p = ini + 24
    filas = {}
    for t in range(64):
        if validas >> t & 1:
            filas[t] = struct.unpack_from("<I", d, p)[0]; p += 4
    s, g, b = (4 if tam_heaps & bit else 2 for bit in (1, 2, 4))   # índices a #Strings, #GUID, #Blob
    idx = lambda t: 4 if filas.get(t, 0) > 0xFFFF else 2
    cod = lambda ts: 4 if max(filas.get(t, 0) for t in ts) >= 1 << 14 else 2   # índice codificado de 2 bits
    extends = cod((0x02, 0x01, 0x1B))
    tam = {0: 2 + s + 3 * g,                                   # Module
           1: cod((0x00, 0x1A, 0x23, 0x01)) + 2 * s,          # TypeRef
           2: 4 + 2 * s + extends + idx(0x04) + idx(0x06),    # TypeDef
           3: idx(0x04),                                       # FieldPtr
           4: 2 + s + b}                                       # Field
    pos = {}
    for t in range(5):
        pos[t] = p; p += filas.get(t, 0) * tam[t]
    return dict(filas=filas, pos=pos, tam=tam, s=s, campos_de_tipo=4 + 2 * s + extends, idx_campo=idx(0x04))


# Cadenas de #Strings que se pueden sobrescribir para dar nombres más largos que el original:
# nombres de parámetros de código de ejemplo que el juego nunca usa (versión 1.1.2).
ESPACIO_LIBRE = [(116690, "LangName")]   # Example_ChangeLanguage.SetLanguage(LangName)


def renombrar_valores(d, nombres):
    """Cambia nombres de valores de enum: {"Level.LOW": "BAJA"}.

    Los menús de ajustes muestran las opciones con ToString() (Toggle.YES, Level.MEDIUM,
    ScreenMode.WINDOWED...). Los ajustes se guardan como número, así que el nombre solo se ve.
    El nombre nuevo se escribe en el mismo lugar de #Strings si cabe; si no, en ESPACIO_LIBRE.
    Devuelve (bytes nuevos, cuántos se cambiaron, [nombres que no se pudieron cambiar]).
    """
    d = bytearray(d)
    m = _tablas(d)
    cad, _ = _flujos(d)["#Strings"]
    s = m["s"]

    def leer(p, n):
        return struct.unpack_from("<I" if n == 4 else "<H", d, p)[0]

    def texto(o):
        return bytes(d[cad + o:d.index(b"\0", cad + o)])
    libres = [o for o, viejo in ESPACIO_LIBRE if texto(o) == viejo.encode()]
    tipos, n_campos = m["filas"].get(0x02, 0), m["filas"].get(0x04, 0)
    hechos, fallidos = 0, []
    for i in range(tipos):
        fila = m["pos"][0x02] + i * m["tam"][0x02]
        tipo = texto(leer(fila + 4, s)).decode()
        if not any(k.startswith(tipo + ".") for k in nombres):
            continue
        primero = leer(fila + m["campos_de_tipo"], m["idx_campo"])
        ultimo = leer(fila + m["tam"][0x02] + m["campos_de_tipo"], m["idx_campo"]) if i + 1 < tipos else n_campos + 1
        for c in range(primero, ultimo):
            fc = m["pos"][0x04] + (c - 1) * m["tam"][0x04]
            o = leer(fc + 2, s)
            nuevo = nombres.get(f"{tipo}.{texto(o).decode()}")
            if nuevo is None:
                continue
            nuevo, viejo = nuevo.encode(), texto(o)
            if len(nuevo) <= len(viejo):
                d[cad + o:cad + o + len(viejo)] = nuevo.ljust(len(viejo), b"\0")
            elif libres and len(nuevo) <= len(texto(libres[0])):
                o = libres.pop(0)
                d[cad + o:cad + o + len(nuevo) + 1] = nuevo + b"\0"
                struct.pack_into("<I" if s == 4 else "<H", d, fc + 2, o)
            else:
                fallidos.append(f"{tipo}.{viejo.decode()}")
                continue
            hechos += 1
    return bytes(d), hechos, fallidos


def _longitud(d, p):
    b = d[p]
    if b & 0x80 == 0:
        return b, 1
    if b & 0xC0 == 0x80:
        return ((b & 0x3F) << 8) | d[p + 1], 2
    return ((b & 0x1F) << 24) | (d[p + 1] << 16) | (d[p + 2] << 8) | d[p + 3], 4


def entradas(d):
    """[(posición del texto, número de bytes UTF-16, texto)]"""
    ini, tam = _heap_us(d)
    p, fin, out = ini + 1, ini + tam, []
    while p < fin:
        n, k = _longitud(d, p)
        if n == 0:
            p += k; continue
        texto = d[p + k:p + k + n - 1].decode("utf-16-le", "replace")
        out.append((p + k, n - 1, texto))
        p += k + n
    return out


def reemplazar(d, mapa):
    """Devuelve (bytes nuevos, cuántos se cambiaron, [textos que no cupieron])."""
    d = bytearray(d)
    hechos, largos = 0, []
    for pos, nbytes, texto in entradas(d):
        if texto not in mapa:
            continue
        es = mapa[texto]
        maximo = nbytes // 2
        if len(es) > maximo:
            largos.append((texto, es, len(es), maximo))
            continue
        falta = maximo - len(es)
        es = " " * (falta // 2) + es + " " * (falta - falta // 2)
        d[pos:pos + nbytes] = es.encode("utf-16-le")
        d[pos + nbytes] = 1 if any(ord(c) > 0x7E for c in es) else 0
        hechos += 1
    return bytes(d), hechos, largos


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "listar":
    sys.stdout.reconfigure(encoding="utf-8")
    datos = open(sys.argv[2], "rb").read()
    for pos, n, t in entradas(datos):
        if re.search(r"[a-z]{2,} [a-z]{2,}", t) and not re.search(r"[/\\{}<>_=]|\.cs|http|^[a-z]", t):
            print(repr(t))
