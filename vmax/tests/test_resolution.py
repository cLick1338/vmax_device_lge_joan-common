#!/usr/bin/env python3
"""Host regression tests: python3 device/lge/joan-common/vmax/tests/test_resolution.py.

Compile the actual CLI with only Android command/data paths and logging redirected.
No device or Android service is needed; command arguments and persistent state are checked.
"""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest


class ResolutionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="vmax-resolution-")
        cls.root = Path(cls.temp.name)
        source_dir = Path(__file__).resolve().parents[1]
        (cls.root / "android").mkdir()
        (cls.root / "android/log.h").write_text("""
#define ANDROID_LOG_DEBUG 3
#define ANDROID_LOG_WARN 5
#define ANDROID_LOG_ERROR 6
static inline int __android_log_print(int priority, const char *tag,
                                     const char *fmt, ...) { return 0; }
""")
        fake_cmd = cls.root / "cmd"
        fake_cmd.write_text("""#!/usr/bin/env python3
import json
from pathlib import Path
import sys
root = Path(__file__).parent
args = sys.argv[1:]
with (root / 'commands').open('a') as log:
    log.write(json.dumps(args) + '\\n')
failure = root / 'fail'
if failure.exists() and args[:len(json.loads(failure.read_text()))] == json.loads(failure.read_text()):
    sys.exit(1)
state = root / 'saved'
if args[:2] == ['settings', 'get']:
    assert args[2:] == ['global', 'user_selected_resolution']
    print(state.read_text() if state.exists() else 'null')
elif args[:2] == ['settings', 'put']:
    assert args[2:4] == ['global', 'user_selected_resolution']
    state.write_text(args[4])
elif args[0] not in ('display', 'window'):
    sys.exit(2)
""")
        fake_cmd.chmod(0o755)
        source = (source_dir / "vmaxdisplay.c").read_text()
        source = source.replace("/system/bin/cmd", str(fake_cmd))
        source = source.replace("/data/vendor/vmaxdisplay", str(cls.root / "legacy"))
        (cls.root / "vmaxdisplay.c").write_text(source)
        cls.binary = cls.root / "vmaxdisplay"
        subprocess.run([
            "cc", "-std=gnu11", "-I", str(cls.root), "-I", str(source_dir),
            str(cls.root / "vmaxdisplay.c"), "-o", str(cls.binary),
        ], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        for name in ("saved", "commands", "fail", "legacy/resolution"):
            (self.root / name).unlink(missing_ok=True)
        (self.root / "legacy").mkdir(exist_ok=True)

    def run_cli(self, choice, success=True):
        result = subprocess.run([str(self.binary), "resolution", choice],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, success, result.stderr)

    def commands(self):
        return [json.loads(line) for line in (self.root / "commands").read_text().splitlines()]

    def test_cli_saves_and_restores_all_resolutions_and_densities(self):
        for choice, width, height, density in (
            ("hd", "720", "1440", "270"),
            ("fhd", "1080", "2160", "405"),
            ("qhd", "1440", "2880", "540"),
        ):
            with self.subTest(choice=choice):
                self.setUp()
                self.run_cli(choice)
                self.assertEqual((self.root / "saved").read_text(), f"{width}x{height}")
                (self.root / "commands").unlink()
                self.run_cli("restore")
                self.assertEqual(self.commands(), [
                    ["settings", "get", "global", "user_selected_resolution"],
                    ["display", "set-user-preferred-display-mode", width, height, "0", "0"],
                    ["window", "density", density],
                ])

    def test_settings_selection_overrides_stale_cli_file(self):
        (self.root / "legacy/resolution").write_text("qhd\n")
        (self.root / "saved").write_text("720x1440")  # Settings.Global.putString
        self.run_cli("restore")
        self.assertEqual(self.commands()[1][2:4], ["720", "1440"])
        self.assertEqual(self.commands()[2], ["window", "density", "270"])

    def test_cli_selection_overrides_settings_selection(self):
        (self.root / "saved").write_text("720x1440")
        self.run_cli("fhd")
        self.run_cli("restore")
        self.assertEqual(self.commands()[-2][2:4], ["1080", "2160"])
        self.assertEqual(self.commands()[-1], ["window", "density", "405"])

    def test_legacy_file_migrates_to_shared_setting(self):
        (self.root / "legacy/resolution").write_text("fhd\n")
        self.run_cli("restore")
        self.assertEqual((self.root / "saved").read_text(), "1080x2160")

    def test_no_saved_selection_does_not_change_display(self):
        self.run_cli("restore")
        self.assertEqual(len(self.commands()), 1)

    def test_invalid_saved_setting_does_not_fall_back_to_stale_file(self):
        for value in ("720x2880", "720x1440 extra", ""):
            with self.subTest(value=value):
                self.setUp()
                (self.root / "legacy/resolution").write_text("qhd\n")
                (self.root / "saved").write_text(value)
                self.run_cli("restore", success=False)
                self.assertEqual(len(self.commands()), 1)

    def test_failed_read_does_not_restore_stale_file(self):
        (self.root / "legacy/resolution").write_text("qhd\n")
        (self.root / "fail").write_text(json.dumps(["settings", "get"]))
        self.run_cli("restore", success=False)
        self.assertEqual(len(self.commands()), 1)

    def test_failed_display_or_density_change_does_not_save(self):
        for command in (["display"], ["window"]):
            with self.subTest(command=command):
                self.setUp()
                (self.root / "saved").write_text("1440x2880")
                (self.root / "fail").write_text(json.dumps(command))
                self.run_cli("hd", success=False)
                self.assertEqual((self.root / "saved").read_text(), "1440x2880")

    def test_failed_save_reports_failure(self):
        (self.root / "saved").write_text("1440x2880")
        (self.root / "fail").write_text(json.dumps(["settings", "put"]))
        self.run_cli("hd", success=False)
        self.assertEqual((self.root / "saved").read_text(), "1440x2880")

    def test_gamma_disable_is_idempotent_and_reenable_preserves_calibration(self):
        calibration = self.root / 'legacy/calibration.txt'
        flag = self.root / 'legacy/disabled'
        try:
            calibration.write_text('10 3\n90 -2\n')
            subprocess.run([str(self.binary), 'disable'], check=True, capture_output=True)
            self.assertTrue(flag.exists())
            # A Settings-owned/read-only flag must not need rewriting by the CLI.
            flag.write_text('sentinel')
            flag.chmod(0o444)
            subprocess.run([str(self.binary), 'disable'], check=True, capture_output=True)
            self.assertEqual(flag.read_text(), 'sentinel')
            disabled = subprocess.run([str(self.binary), 'current'], check=True,
                                      capture_output=True, text=True)
            self.assertIn('calibration disabled (identity LUT)', disabled.stdout)
            flag.unlink()  # Same operation as the Settings switch's enable action.
            enabled = subprocess.run([str(self.binary), 'current'], check=True,
                                     capture_output=True, text=True)
            self.assertIn('10 3\n90 -2\n', enabled.stdout)
            self.assertNotIn('calibration disabled', enabled.stdout)
        finally:
            flag.unlink(missing_ok=True)
            calibration.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
