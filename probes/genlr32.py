# Vmax
# 32-bit stereo test: 1 kHz left-only, right-only, then both: genlr32.py <rate> <out.wav> <amp> <secs per part>
import struct, math, sys, array
rate=int(sys.argv[1]); out=sys.argv[2]; amp=float(sys.argv[3]); secs=int(sys.argv[4])
n=rate*secs; full=amp*(2**31-1)
tone=[int(round(full*math.sin(2*math.pi*1000*i/rate))) for i in range(n)]
pcm=array.array('i',[0])*(n*6)
pcm[0:2*n:2]=array.array('i',tone)
pcm[2*n+1:4*n:2]=array.array('i',tone)
pcm[4*n::2]=array.array('i',tone); pcm[4*n+1::2]=array.array('i',tone)
data=pcm.tobytes()
hdr=b'RIFF'+struct.pack('<I',36+len(data))+b'WAVEfmt '+struct.pack('<IHHIIHH',16,1,2,rate,rate*8,8,32)+b'data'+struct.pack('<I',len(data))
open(out,'wb').write(hdr+data)
