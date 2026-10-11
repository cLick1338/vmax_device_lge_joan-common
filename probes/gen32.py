# Vmax
import struct, math, sys
rate=int(sys.argv[1]); out=sys.argv[2]; amp=float(sys.argv[3]); secs=int(sys.argv[4])
n=rate*secs; ch=2
data=bytearray()
for i in range(n):
    v=int(amp*(2**31-1)*math.sin(2*math.pi*1000*i/rate))
    data+=struct.pack('<ii',v,v)
hdr=b'RIFF'+struct.pack('<I',36+len(data))+b'WAVEfmt '+struct.pack('<IHHIIHH',16,1,ch,rate,rate*ch*4,ch*4,32)+b'data'+struct.pack('<I',len(data))
open(out,'wb').write(hdr+data)
