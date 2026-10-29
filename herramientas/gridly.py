"""Lee y reescribe la tabla de textos "Project" (sistema Gridly) del juego.

Formato (MonoBehaviour serializado de Unity, little-endian, cadenas alineadas a 4 bytes):
  cabecera(28) nombre int0 nGrids
  grid: int nombre int vista nRecords
  record: id nColumnas (idColumna texto)* extra
"""
import struct

GRIDLY_PATH_ID = 13625   # objeto "Project" dentro de resources.assets


class _Lector:
    def __init__(self, d, p=0):
        self.d = d; self.p = p

    def i(self):
        v = struct.unpack_from("<i", self.d, self.p)[0]; self.p += 4; return v

    def s(self):
        n = self.i(); v = self.d[self.p:self.p + n].decode("utf-8"); self.p += n
        self.p = (self.p + 3) & ~3
        return v


def parse(d):
    r = _Lector(d, 28)
    name = r.s(); r.i()
    grids = []
    for _ in range(r.i()):
        g = dict(pre=r.i(), name=r.s(), mid=r.i(), view=r.s(), recs=[])
        for _ in range(r.i()):
            rid = r.s()
            cols = [(r.s(), r.s()) for _ in range(r.i())]
            g["recs"].append((rid, cols, r.s()))
        grids.append(g)
    return name, grids, r.p


def _w_str(b, s):
    e = s.encode("utf-8"); b += struct.pack("<i", len(e)); b += e
    while len(b) % 4:
        b += b"\0"


def build(d, tr):
    """Devuelve la tabla con cada texto pasado por tr(grid, record_id, columna, texto)."""
    name, grids, tail = parse(d)
    b = bytearray(d[:28]); _w_str(b, name)
    b += d[len(b):len(b) + 4]
    b += struct.pack("<i", len(grids))
    for g in grids:
        b += struct.pack("<i", g["pre"]); _w_str(b, g["name"])
        b += struct.pack("<i", g["mid"]); _w_str(b, g["view"])
        b += struct.pack("<i", len(g["recs"]))
        for rid, cols, extra in g["recs"]:
            _w_str(b, rid); b += struct.pack("<i", len(cols))
            for c, t in cols:
                _w_str(b, c); _w_str(b, tr(g["name"], rid, c, t))
            _w_str(b, extra)
    b += d[tail:]
    return bytes(b)
