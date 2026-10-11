# Vmax
# stereo test: 1 kHz left-only, right-only, then both: genlr32.py <rate> <out.wav> <amp> <secs per part> [bits 32|24]
import struct, math, sys, array
rate=int(sys.argv[1]); out=sys.argv[2]; amp=float(sys.argv[3]); secs=int(sys.argv[4])
bits=int(sys.argv[5]) if len(sys.argv) > 5 else 32
n=rate*secs; full=amp*(2**(bits-1)-1)
tone=[int(round(full*math.sin(2*math.pi*1000*i/rate))) for i in range(n)]
pcm=array.array('i',[0])*(n*6)
pcm[0:2*n:2]=array.array('i',tone)
pcm[2*n+1:4*n:2]=array.array('i',tone)
pcm[4*n::2]=array.array('i',tone); pcm[4*n+1::2]=array.array('i',tone)
data=pcm.tobytes()
if bits == 24:  # pack to 3 bytes per sample
    data=b''.join(data[i:i+3] for i in range(0,len(data),4))
bps=bits//8
hdr=b'RIFF'+struct.pack('<I',36+len(data))+b'WAVEfmt '+struct.pack('<IHHIIHH',16,1,2,rate,rate*2*bps,2*bps,bits)+b'data'+struct.pack('<I',len(data))
open(out,'wb').write(hdr+data)
