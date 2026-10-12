#!/usr/bin/env python3
# Vmax
"""Generate per-locale Vmax string overlays from upstream translations.

For every string overridden in an overlay's default values/strings.xml, copy the
upstream translation for each locale and replace "LineageOS" with "Vmax".
Re-run after merging upstream so new translations are picked up.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
COMMON = ROOT / "device/lge/joan-common"
# (upstream res dir, overlay res dir)
TARGETS = [
    ("lineage-sdk/lineage/res/res", "overlay-lineage/lineage-sdk/lineage/res/res"),
    ("packages/apps/Updater/app/src/main/res", "overlay/packages/apps/Updater/app/src/main/res"),
    ("packages/apps/SetupWizard/res", "overlay/packages/apps/SetupWizard/res"),
    ("packages/apps/LineageParts/res", "overlay/packages/apps/LineageParts/res"),
]
# Keys that use the subscript form
SUB_KEYS = {"lineage_version", "lineage_updates"}
STRING = re.compile(r'<string\s+name="([^"]+)"[^>]*>.*?</string>', re.S)
HEADER = ('<?xml version="1.0" encoding="utf-8"?>\n<!-- //Vmax -->\n'
          '<resources xmlns:xliff="urn:oasis:names:tc:xliff:document:1.2">\n')


def main():
    total = 0
    for upstream, overlay in TARGETS:
        up, ov = ROOT / upstream, COMMON / overlay
        default = (ov / "values/strings.xml").read_text()
        keys = {m.group(1) for m in STRING.finditer(default)}
        for loc in sorted(up.glob("values-*")):
            # English variants are hand-copied from the default overlay
            if loc.name.startswith("values-en") or not (loc / "strings.xml").exists():
                continue
            src = (loc / "strings.xml").read_text()
            out = []
            for m in STRING.finditer(src):
                key, text = m.group(1), m.group(0)
                if key in keys and "LineageOS" in text:
                    sub = "V<sub>max</sub>" if key in SUB_KEYS else "Vmax"
                    out.append("    " + text.replace("LineageOS", sub))
            target = ov / loc.name / "strings.xml"
            if out:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(HEADER + "\n".join(out) + "\n</resources>\n")
                total += len(out)
            elif target.exists():
                target.unlink()
    print(f"wrote {total} strings")


if __name__ == "__main__":
    sys.exit(main())
