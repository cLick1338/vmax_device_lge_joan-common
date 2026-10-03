#!/usr/bin/env python3
"""Test the real daemon loop with a fake panel and process-held POSIX locks."""

import fcntl
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest


class CalibrationSessionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="vmax-calibration-")
        cls.root = Path(cls.temp.name)
        source_dir = Path(__file__).resolve().parents[1]
        (cls.root / "android").mkdir()
        (cls.root / "android/log.h").write_text("""
#define ANDROID_LOG_DEBUG 3
#define ANDROID_LOG_WARN 5
#define ANDROID_LOG_ERROR 6
static inline int __android_log_print(int p, const char *t, const char *f, ...) { return 0; }
""")
        source = (source_dir / "vmaxdisplay.c").read_text()
        for original, replacement in {
            "/data/vendor/vmaxdisplay": "data",
            "/vendor/etc/vmaxdisplay/default_calibration.txt": "default",
            "/dev/graphics/fb0": "fb",
            "/sys/class/graphics/fb0/bl_event": "event",
            "/sys/class/leds/lcd-backlight/brightness": "brightness",
            "/sys/class/leds/lcd-backlight/max_brightness": "max",
        }.items():
            source = source.replace(original, str(cls.root / replacement))
        # Capture the applied curve in place of the hardware ioctl.
        source = source.replace("int rc = ioctl(fb_fd, MSMFB_MDP_PP, &pp);", f"""
        FILE *capture = fopen("{cls.root / 'curves'}", "a");
        fprintf(capture, "%u\\n", c0[1]);
        fclose(capture);
        int rc = 0;
        """)
        (cls.root / "daemon.c").write_text(source)
        cls.binary = cls.root / "daemon"
        subprocess.run(["cc", "-std=gnu11", "-I", str(cls.root), "-I", str(source_dir),
                        str(cls.root / "daemon.c"), "-o", str(cls.binary)], check=True)
        checkout = source_dir.parents[3]
        session = (checkout / "packages/apps/Settings/src/com/android/settings/display/"
                   "GammaCalibrationSession.java").read_text()
        session = session.replace("/data/vendor/vmaxdisplay", str(cls.root / "data"))
        (cls.root / "GammaCalibrationSession.java").write_text(session)
        (cls.root / "SessionTest.java").write_text("""
package com.android.settings.display;
import java.io.IOException;
public class SessionTest {
    public static void main(String[] args) throws Exception {
        try (GammaCalibrationSession session = new GammaCalibrationSession()) {
            int[] status = session.connect();
            if (status[0] != 511 || status[1] != 102) throw new AssertionError();
            try (GammaCalibrationSession second = new GammaCalibrationSession()) {
                try {
                    second.connect();
                    throw new AssertionError("Second editor opened");
                } catch (IOException expected) { }
            }
            System.out.println("ready");
            System.out.flush();
            System.in.read();
        }
    }
}
""")
        jdk = checkout / "prebuilts/jdk/jdk21/linux-x86/bin"
        javac = shutil.which("javac") or str(jdk / "javac")
        cls.java = shutil.which("java") or str(jdk / "java")
        subprocess.run([javac, "-d", str(cls.root), str(cls.root / "GammaCalibrationSession.java"),
                        str(cls.root / "SessionTest.java")], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        (self.root / "data").mkdir(exist_ok=True)
        for child in (self.root / "data").iterdir():
            child.unlink()
        (self.root / "curves").unlink(missing_ok=True)
        for name, text in {"default": "0 15\n100 15\n", "brightness": "102\n",
                           "max": "511\n", "event": "1\n", "fb": ""}.items():
            (self.root / name).write_text(text)
        self.daemon = subprocess.Popen([str(self.binary)])
        self.session = None
        self.wait_curve(60)

    def tearDown(self):
        if self.session:
            self.session.close()
        self.daemon.terminate()
        self.daemon.wait(timeout=3)

    def wait_for(self, predicate):
        until = time.monotonic() + 3
        while time.monotonic() < until:
            if predicate():
                return
            time.sleep(0.01)
        self.fail("Daemon did not reach the expected state")

    def wait_curve(self, value):
        path = self.root / "curves"
        self.wait_for(lambda: path.exists()
                      and path.read_text().splitlines()[-1:] == [str(value)])

    def begin(self, token="a" * 32):
        self.session = (self.root / "data/calibration.session").open("w")
        fcntl.lockf(self.session, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.session.write(token)
        self.session.flush()
        status = self.root / "data/calibration.status"
        self.wait_for(lambda: status.exists() and status.read_text() == token + " 511 102\n")
        self.wait_curve(1)

    def test_lock_release_restores_without_a_file_event(self):
        self.begin()
        # Like process death: release without deleting or modifying the session file.
        fcntl.lockf(self.session, fcntl.LOCK_UN)
        self.wait_curve(60)
        self.assertFalse((self.root / "data/disabled").exists())

    def test_disabled_state_survives_session(self):
        (self.root / "data/disabled").write_text("")
        self.wait_curve(1)
        self.begin()
        self.session.close()
        time.sleep(0.35)
        self.wait_curve(1)
        self.assertTrue((self.root / "data/disabled").exists())

    def test_save_is_deferred_until_lock_released(self):
        self.begin()
        temporary = self.root / "data/new.tmp"
        temporary.write_text("0 30\n100 30\n")
        temporary.replace(self.root / "data/calibration.txt")
        time.sleep(0.15)
        self.wait_curve(1)
        self.session.close()
        self.wait_curve(120)

    def test_status_uses_actual_brightness_and_new_session_token(self):
        self.begin()
        (self.root / "brightness").write_text("256\n")
        status = self.root / "data/calibration.status"
        self.wait_for(lambda: status.read_text() == "a" * 32 + " 511 256\n")
        self.session.close()
        self.wait_curve(60)
        (self.root / "brightness").write_text("102\n")
        self.begin("b" * 32)

    def test_stale_session_file_does_not_bypass_correction(self):
        (self.root / "data/calibration.session").write_text("c" * 32)
        time.sleep(0.15)
        self.wait_curve(60)
        self.assertFalse((self.root / "data/calibration.status").exists())

    def test_actual_settings_session_process_death_restores_gamma(self):
        with subprocess.Popen([self.java, "-cp", str(self.root),
                               "com.android.settings.display.SessionTest"],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE) as editor:
            try:
                self.assertEqual(editor.stdout.readline(), b"ready\n")
                self.wait_curve(1)
                # A rejected second editor must not release the first editor's POSIX lock.
                time.sleep(0.35)
                self.wait_curve(1)
                editor.kill()
                editor.wait(timeout=3)
                self.wait_curve(60)
            finally:
                editor.kill()
                editor.wait(timeout=3)


if __name__ == "__main__":
    unittest.main()
