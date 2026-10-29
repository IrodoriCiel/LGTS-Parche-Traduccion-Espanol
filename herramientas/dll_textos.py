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
    for _ in range(n):
        off, size = struct.unpack_from("<II", d, p); p += 8
        e = d.index(b"\0", p); nombre = d[p:e].decode(); p = (e + 4) & ~3
        if nombre == "#US":
            return meta + off, size
    raise ValueError("sin #US")


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
