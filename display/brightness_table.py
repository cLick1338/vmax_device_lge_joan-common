#!/usr/bin/env python3
#Vmax
# Generate config_screenBrightnessBacklight/Nits from the joan luminance measurements (BRIGHTNESS.md).
# Usage (from the checkout root): brightness_table.py [dtsi] [--report]
import bisect
import math
import re
import sys

DTSI = 'kernel/lge/msm8998/arch/arm64/boot/dts/lge/dsi-panel-sw43402-dsc-qhd-cmd-dv4_0.dtsi'
NITS_PER_LUX = 420 / 60.5  # review: 420 nits at register 239
MIN_REG, MIN_NITS = 30, 3.3  # review minimum
SLIDER_MIN, SLIDER_MAX = 9, 207  # 207: first b at reg 255 (HBM top)
HBM_TRANSITION = 179  # first b at reg 251, normal slider top
MAX_ERR = 0.02  # max relative error of linear interpolation between samples

# Full-white ALS lux by register, run 2 (reg 105-239, normal range)
LUX = {105: 10, 114: 14, 122: 16, 128: 17.5, 140: 21.5, 153: 27, 163: 31, 181: 37,
       199: 45, 216: 51, 239: 60.5}
# Boost range relative to reg 239, run 3 (2026-10-16, two passes averaged)
BOOST = {240: 1.0474, 241: 1.0751, 242: 1.0925, 243: 1.1222, 244: 1.1376, 245: 1.1718,
         246: 1.1981, 247: 1.2139, 248: 1.2407, 249: 1.2746, 250: 1.2919, 251: 1.3256,
         252: 1.3613, 253: 1.3743, 254: 1.4046, 255: 1.4109}


def blmap(path):
    m = re.search(r'lge,blmap_v1\s*=\s*<([^>]*)>', open(path, encoding='utf-8').read())
    vals = [int(v) for v in m.group(1).split()]
    if len(vals) != 512:
        sys.exit(f'blmap_v1 has {len(vals)} entries')
    return vals


def nits_model():
    pts = sorted((r, l * NITS_PER_LUX) for r, l in LUX.items())
    pts += [(r, ratio * pts[-1][1]) for r, ratio in sorted(BOOST.items())]
    lo_r, lo_n = pts[0]
    exp_lo = math.log(lo_n / MIN_NITS) / math.log(lo_r / MIN_REG)
    regs = [r for r, _ in pts]

    def nits(reg):
        if reg > regs[-1]:
            sys.exit(f'register {reg} is above the measured range')
        if reg < lo_r:
            return MIN_NITS * (reg / MIN_REG) ** exp_lo
        i = min(bisect.bisect_right(regs, reg), len(pts) - 1)
        (r0, n0), (r1, n1) = pts[i - 1], pts[i]
        if r0 >= 239:  # boost range: linear in nits
            return n0 + (n1 - n0) * (reg - r0) / (r1 - r0)
        t = math.log(reg / r0) / math.log(r1 / r0)  # normal range: log-log
        return math.exp(math.log(n0) + t * math.log(n1 / n0))
    return nits


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    bl = blmap(args[0] if args else DTSI)
    nits = nits_model()
    reg_of = lambda b: bl[b * 511 // 255]  # lights HAL scaleBrightness
    curve = {b: nits(reg_of(b)) for b in range(SLIDER_MIN, SLIDER_MAX + 1)}

    # Candidates: first backlight of each register step; keep the fewest that interpolate within MAX_ERR
    cands = [b for b in curve if b == SLIDER_MIN or reg_of(b) != reg_of(b - 1)]
    keep = [cands[0]]
    i = 0
    while i < len(cands) - 1:
        j = i + 1
        while j + 1 < len(cands):
            a, c = cands[i], cands[j + 1]
            if any(abs(curve[a] + (curve[c] - curve[a]) * (b - a) / (c - a) - curve[b]) > MAX_ERR * curve[b]
                   for b in range(a, c + 1)):
                break
            j += 1
        keep.append(cands[j])
        i = j
    keep = sorted(set(keep) | {HBM_TRANSITION, SLIDER_MAX})

    if '--report' in sys.argv:
        for b in range(SLIDER_MIN, SLIDER_MAX + 1):
            print(f'b {b:3d} level {b * 511 // 255:3d} reg {reg_of(b):3d} nits {curve[b]:6.1f}'
                  + ('  *' if b in keep else ''))
        return
    print('    <integer-array name="config_screenBrightnessBacklight">')
    for b in keep:
        print(f'        <item>{b}</item>')
    print('    </integer-array>\n')
    print('    <array name="config_screenBrightnessNits">')
    for b in keep:
        print(f'        <item>{curve[b]:.2f}</item>  <!-- reg {reg_of(b)} -->')
    print('    </array>')
    print(f'\nHBM transitionPoint (backlight): {(HBM_TRANSITION - 1) / 254:.6f}, '
          f'{curve[HBM_TRANSITION]:.2f} nits; top {curve[SLIDER_MAX]:.2f} nits', file=sys.stderr)


main()
