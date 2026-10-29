import struct, lz4.block
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
if __name__=="__main__":
    import sys
    h,_,b,n,he,ds=read_header(sys.argv[1])
    print(h,he,ds,len(b)); 
    from collections import Counter; print(Counter((x[2]) for x in b), b[:3])
    for x in n: print(x)
