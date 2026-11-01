import struct, lz4.block, io, bisect, collections
def rs(f):
    b=b''
    while True:
        c=f.read(1)
        if c==b'\0': return b.decode()
        b+=c
def read_header(path):
    f=open(path,'rb')
    h={}
    h['sig']=rs(f); h['ver']=struct.unpack('>I',f.read(4))[0]; h['uver']=rs(f); h['urev']=rs(f)
    h['size'],h['csize'],h['usize'],h['flags']=struct.unpack('>qIII',f.read(20))
    hdr_end=f.tell()
    if h['ver']>=7: hdr_end=(hdr_end+15)&~15
    f.seek(hdr_end)
    if h['flags']&0x80:
        f.seek(h['size']-h['csize']); cinfo=f.read(h['csize'])
    else:
        cinfo=f.read(h['csize'])
    ct=h['flags']&0x3f
    info=lz4.block.decompress(cinfo,uncompressed_size=h['usize']) if ct in(2,3) else cinfo
    p=16  # hash
    nb=struct.unpack_from('>i',info,p)[0]; p+=4
    blocks=[]
    for _ in range(nb):
        u,c,fl=struct.unpack_from('>IIH',info,p); p+=10; blocks.append([u,c,fl])
    nn=struct.unpack_from('>i',info,p)[0]; p+=4
    nodes=[]
    for _ in range(nn):
        off,sz,fl=struct.unpack_from('>qqI',info,p); p+=20
        e=info.index(b'\0',p); nodes.append([off,sz,fl,info[p:e].decode()]); p=e+1
    data_start=hdr_end if h['flags']&0x80 else hdr_end+h['csize']
    if h['flags']&0x200: data_start=(data_start+15)&~15
    return h,info[:16],blocks,nodes,hdr_end,data_start
class LectorBundle(io.RawIOBase):
    """Flujo sobre el contenido descomprimido de un bundle, descomprimiendo por bloque.

    UnityPy.load() junta el bundle entero descomprimido en memoria y encima copia
    aparte cada archivo interno: con data.unity3d son 18 GB dos veces, y en una PC
    normal eso termina en MemoryError. Aquí solo se descomprimen los bloques que
    se piden, y se guardan los últimos en una caché: leer un archivo interno de
    20 MB toca unos 170 bloques de los 148.000 que tiene data.unity3d.

    blocks y data_start son los que devuelve read_header().
    """

    def __init__(self, path, blocks, data_start, cache=128):
        self.f = open(path, "rb")
        self.blocks = blocks
        self.cache = {}
        self.recientes = collections.deque()
        self.max = cache
        # inicio de cada bloque: u_ini en el flujo descomprimido, c_ini dentro del archivo
        self.u_ini, self.c_ini = [0], [data_start]
        for u, c, fl in blocks:
            self.u_ini.append(self.u_ini[-1] + u)
            self.c_ini.append(self.c_ini[-1] + c)
        self.size = self.u_ini[-1]
        self.pos = 0

    def bloque(self, i):
        """Contenido descomprimido del bloque i (de la caché si ya se leyó)."""
        if i in self.cache:
            return self.cache[i]
        u, c, fl = self.blocks[i]
        self.f.seek(self.c_ini[i])
        datos = self.f.read(c)
        if fl & 0x3f in (2, 3):
            datos = lz4.block.decompress(datos, uncompressed_size=u)
        self.cache[i] = datos
        self.recientes.append(i)
        if len(self.recientes) > self.max:
            self.cache.pop(self.recientes.popleft(), None)
        return datos

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else (self.pos + off if whence == 1 else self.size + off)
        return self.pos

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.size - self.pos
        n = max(0, min(n, self.size - self.pos))
        trozos = []
        while n > 0:
            i = bisect.bisect_right(self.u_ini, self.pos) - 1
            datos = self.bloque(i)
            dentro = self.pos - self.u_ini[i]
            toma = min(n, len(datos) - dentro)
            trozos.append(datos[dentro:dentro + toma])
            self.pos += toma
            n -= toma
        return trozos[0] if len(trozos) == 1 else b"".join(trozos)

    def readinto(self, b):
        d = self.read(len(b))
        b[:len(d)] = d
        return len(d)

    def close(self):
        if not self.closed:
            self.f.close()
            self.cache.clear()
        super().close()


class Ventana(io.RawIOBase):
    """Un archivo interno del bundle (un nodo de read_header), como archivo aparte.

    Comparten el mismo LectorBundle: cada lectura se posiciona antes, así que la
    caché de bloques sirve para todos.
    """

    def __init__(self, lector, inicio, tam):
        self.lector, self.inicio, self.size, self.pos = lector, inicio, tam, 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else (self.pos + off if whence == 1 else self.size + off)
        return self.pos

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.size - self.pos
        n = max(0, min(n, self.size - self.pos))
        self.lector.seek(self.inicio + self.pos)
        d = self.lector.read(n)
        self.pos += len(d)
        return d

    def readinto(self, b):
        d = self.read(len(b))
        b[:len(d)] = d
        return len(d)


if __name__=="__main__":
    import sys
    h,_,b,n,he,ds=read_header(sys.argv[1])
    print(h,he,ds,len(b)); 
    from collections import Counter; print(Counter((x[2]) for x in b), b[:3])
    for x in n: print(x)
