# Vmax
# left-only 1 kHz tone: genleft.py <rate> <bits 24|32> <out.wav> <amp> <secs>
import struct, math, sys
rate=int(sys.argv[1]); bits=int(sys.argv[2]); out=sys.argv[3]; amp=float(sys.argv[4]); secs=int(sys.argv[5])
full=2**(bits-1)-1; data=bytearray()
for i in range(rate*secs):
    v=int(amp*full*math.sin(2*math.pi*1000*i/rate))
    data+=(v.to_bytes(bits//8,'little',signed=True)+(0).to_bytes(bits//8,'little',signed=True))
hdr=b'RIFF'+struct.pack('<I',36+len(data))+b'WAVEfmt '+struct.pack('<IHHIIHH',16,1,2,rate,rate*2*bits//8,2*bits//8,bits)+b'data'+struct.pack('<I',len(data))
open(out,'wb').write(hdr+data)
