#!/usr/bin/env python3
# Vmax
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
files = {'user_selected_resolution': root / 'saved', 'user_selected_density': root / 'density_state'}
wm_density = root / 'wm_density'
if args[:2] == ['settings', 'get']:
    state = files[args[3]]
    print(state.read_text() if state.exists() else 'null')
elif args[:2] == ['settings', 'put']:
    files[args[3]].write_text(args[4])
elif args == ['window', 'density']:
    # Physical 540 until something overrides it, like the real shell command.
    print('Physical density: 540')
    if wm_density.exists():
        print('Override density: ' + wm_density.read_text())
elif args == ['window', 'size']:
    width = (root / 'wm_width').read_text() if (root / 'wm_width').exists() else '1440'
    print('Physical size: ' + width + 'x2880')
elif args[:2] == ['window', 'density']:
    wm_density.write_text(args[2])
elif args[:2] == ['display', 'set-user-preferred-display-mode']:
    (root / 'wm_width').write_text(args[2])
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
        for name in ("saved", "commands", "fail", "legacy/resolution", "density_state", "wm_density", "wm_width"):
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
                commands = self.commands()
                self.assertEqual(commands[0], ["settings", "get", "global", "user_selected_resolution"])
                self.assertIn(["display", "set-user-preferred-display-mode", width, height, "0", "0"],
                              commands)
                self.assertIn(["window", "density", density], commands)

    def test_settings_selection_overrides_stale_cli_file(self):
        (self.root / "legacy/resolution").write_text("qhd\n")
        (self.root / "saved").write_text("720x1440")  # Settings.Global.putString
        self.run_cli("restore")
        self.assertIn(["display", "set-user-preferred-display-mode", "720", "1440", "0", "0"],
                      self.commands())
        self.assertIn(["window", "density", "270"], self.commands())

    def test_cli_selection_overrides_settings_selection(self):
        (self.root / "saved").write_text("720x1440")
        self.run_cli("fhd")
        self.run_cli("restore")
        commands = self.commands()
        self.assertEqual(commands[-3][2:4], ["1080", "2160"])
        self.assertEqual(commands[-2], ["window", "density", "405"])

    def test_legacy_file_migrates_to_shared_setting(self):
        (self.root / "legacy/resolution").write_text("fhd\n")
        self.run_cli("restore")
        self.assertEqual((self.root / "saved").read_text(), "1080x2160")

    def test_no_saved_selection_defaults_to_full_hd(self):
        self.run_cli("restore")
        self.assertEqual((self.root / "saved").read_text(), "1080x2160")
        self.assertIn(["display", "set-user-preferred-display-mode", "1080", "2160", "0", "0"],
                      self.commands())
        self.assertEqual(self.wm_density(), "405")
        self.run_cli("qhd")
        self.run_cli("restore")
        self.assertEqual((self.root / "saved").read_text(), "1440x2880")
        self.assertEqual(self.wm_density(), "540")

    def wm_density(self):
        return (self.root / "wm_density").read_text()

    def test_custom_density_is_scaled_and_survives_round_trips_without_drift(self):
        (self.root / "wm_density").write_text("450")  # user-set at QHD
        for _ in range(5):
            self.run_cli("fhd")
            self.assertEqual(self.wm_density(), "338")  # 337.5 rounds up
            self.run_cli("hd")
            self.assertEqual(self.wm_density(), "225")
            self.run_cli("qhd")
            self.assertEqual(self.wm_density(), "450")

    def test_density_changed_by_user_between_switches_becomes_new_base(self):
        self.run_cli("fhd")
        self.assertEqual(self.wm_density(), "405")
        (self.root / "wm_density").write_text("360")  # Display size changed at FHD
        self.run_cli("hd")
        self.assertEqual(self.wm_density(), "240")
        self.run_cli("qhd")
        self.assertEqual(self.wm_density(), "480")

    def test_restore_keeps_user_density_set_since_last_switch(self):
        self.run_cli("fhd")
        (self.root / "wm_density").write_text("360")
        (self.root / "wm_width").write_text("1440")  # boot-time width must not be trusted
        self.run_cli("restore")
        self.assertEqual(self.wm_density(), "360")

    def test_first_switch_adopts_existing_density_at_current_width(self):
        (self.root / "wm_width").write_text("1080")
        (self.root / "wm_density").write_text("405")  # applied by an older build
        self.run_cli("hd")
        self.assertEqual(self.wm_density(), "270")

    def test_failed_density_state_save_reports_failure(self):
        (self.root / "fail").write_text(json.dumps(["settings", "put", "global", "user_selected_density"]))
        self.run_cli("hd", success=False)
        self.assertFalse((self.root / "saved").exists())

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
