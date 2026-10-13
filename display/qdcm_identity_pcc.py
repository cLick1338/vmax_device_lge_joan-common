#!/usr/bin/env python3
#Vmax
# Replace the LG virtual PCC (QDCM feature 25) in hal_hdr with an identity matrix.
import re
import struct
import sys

src, dst = sys.argv[1], sys.argv[2]
xml = open(src, encoding='utf-8').read()

vals = []
for row in range(3):
    coeffs = [0.0] * 11  # c, r, g, b, then cross terms
    coeffs[1 + row] = 1.0
    vals += coeffs
payload = (b'\x00' * 8 + struct.pack('<33d', *vals)).hex().upper()

m = re.search(r'(<Mode [^>]*Name="hal_hdr".*?<Feature FeatureType="25"[^>]*>)([0-9A-Fa-f]+)(</Feature>)',
              xml, re.S)
if not m or len(m.group(2)) != len(payload):
    sys.exit('qdcm_identity_pcc: hal_hdr feature 25 not found or unexpected size')

with open(dst, 'w', encoding='utf-8') as f:
    f.write(xml[:m.start(2)] + payload + xml[m.end(2):])
