#!/usr/bin/env python3
# Vmax
"""Generate the Vmax brand string overlays from the upstream strings.

The brand is defined once here. For each listed string key, the upstream text
of every locale (including the English default) has "LineageOS" replaced with
the brand. Re-run after merging upstream so new translations are picked up.
Hand-written, non-brand overrides (URLs, onboarding text) live in separate files and are kept.
"""
import re
import sys
from pathlib import Path

BRAND_DISPLAY = "Vₘₐₓ"  # titles, headers and labels
BRAND_PLAIN = "Vmax"                    # running text

ROOT = Path(__file__).resolve().parents[4]
COMMON = ROOT / "device/lge/joan-common"
TARGETS = [
    dict(upstream="lineage-sdk/lineage/res/res",
         overlay="overlay-lineage/lineage-sdk/lineage/res/res",
         display={"lineage_version", "lineage_updates", "lineageos_system_label"},
         plain=set()),
    dict(upstream="packages/apps/Updater/app/src/main/res",
         overlay="overlay/packages/apps/Updater/app/src/main/res",
         display={"header_title_text", "list_build_version", "list_build_version_date"},
         plain={"info_dialog_message"}),
    dict(upstream="packages/apps/SetupWizard/res",
         overlay="overlay/packages/apps/SetupWizard/res",
         display={"os_name", "setup_services"},
         plain=set()),
    dict(upstream="packages/apps/LineageParts/res",
         overlay="overlay/packages/apps/LineageParts/res",
         display={"lineageparts_title", "egg_title", "anonymous_statistics_title"},
         plain={"privacy_settings_category", "anonymous_statistics_summary",
                "anonymous_statistics_warning"}),
]
STRING = re.compile(r'<string\s+name="([^"]+)"[^>]*>.*?</string>', re.S)
HEADER = ('<?xml version="1.0" encoding="utf-8"?>\n<!-- //Vmax -->\n'
          '<resources xmlns:xliff="urn:oasis:names:tc:xliff:document:1.2">\n')


def render(src, forms):
    out = []
    for m in STRING.finditer(src):
        key, text = m.group(1), m.group(0)
        if key in forms and "LineageOS" in text:
            out.append("    " + text.replace("LineageOS", forms[key]))
    return out


def main():
    total = 0
    for t in TARGETS:
        up, ov = ROOT / t["upstream"], COMMON / t["overlay"]
        forms = {k: BRAND_DISPLAY for k in t["display"]}
        forms.update({k: BRAND_PLAIN for k in t["plain"]})
        for old in ov.glob("values*/strings.xml"):
            old.unlink()
        for loc in [up / "values", *sorted(up.glob("values-*"))]:
            if not (loc / "strings.xml").exists():
                continue
            out = render((loc / "strings.xml").read_text(), forms)
            if out:
                target = ov / loc.name / "strings.xml"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(HEADER + "\n".join(out) + "\n</resources>\n")
                total += len(out)
        for d in ov.glob("values*"):
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
    print(f"wrote {total} strings")


if __name__ == "__main__":
    sys.exit(main())
