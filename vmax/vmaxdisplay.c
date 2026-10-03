/* vmaxdisplay - Panel Gamma Correction autodaemon
 Watches backlight level changes and applies precomputed DSPP PGC curves dictated by user-made calibration points.
 Calibration data is pairs of [display brightness percentage 0-100][darkest calibration square visible on 0-255 test squares]
 Negative values for the second column are also allowed.
 Gamma curves are generated/interpolated for the full range of backlight intensities (usually 512) and full 10 bit range.
 There is the possibility of per color channel curves but currently all channels use the same curve.

 Usage (no root required, run as shell):
   /vendor/bin/vmaxdisplay <path>       Copy <path> in as the active calibration file.
   /vendor/bin/vmaxdisplay current      Print the active calibration file.
   /vendor/bin/vmaxdisplay default      Revert to the ROM default calibration.
   /vendor/bin/vmaxdisplay disable      Force an identity LUT (no correction).
   /vendor/bin/vmaxdisplay resolution <hd|fhd|qhd>   Set preferred panel resolution (720|1080|1440 also accepted).
   Density is scaled from 540 at QHD. Changes are saved and restored after boot completes.
   /vendor/bin/vmaxdisplay resolution restore       Reapply the shared Settings/CLI choice (used by init).
   /vendor/bin/vmaxdisplay              (no args) Run as the daemon itself; started by init.
 The daemon watches its data dir with inotify and reloads in-process.
*/

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <poll.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <sys/inotify.h>

#include <time.h>
#include <android/log.h>

#define __user
#include "msm_mdp.h"

#define LOG_TAG "vmaxdisplay"
#define LOGD(...) __android_log_print(ANDROID_LOG_DEBUG, LOG_TAG, __VA_ARGS__)
#define LOGW(...) __android_log_print(ANDROID_LOG_WARN,  LOG_TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, __VA_ARGS__)

static const char *FB_DEV = "/dev/graphics/fb0";
static const char *BL_EVENT_PATH = "/sys/class/graphics/fb0/bl_event";
static const char *BL_BRIGHTNESS_PATH = "/sys/class/leds/lcd-backlight/brightness";
static const char *BL_MAX_BRIGHTNESS_PATH = "/sys/class/leds/lcd-backlight/max_brightness";

#define CAL_DIR            "/data/vendor/vmaxdisplay"
#define CAL_NAME           "calibration.txt"
#define DISABLED_NAME      "disabled"
#define SESSION_NAME       "calibration.session"
#define SESSION_PATH       CAL_DIR "/" SESSION_NAME
#define STATUS_PATH        CAL_DIR "/calibration.status"
#define CAL_DEST_PATH      CAL_DIR "/" CAL_NAME
#define DISABLED_FLAG_PATH CAL_DIR "/" DISABLED_NAME
#define RESOLUTION_PATH    CAL_DIR "/resolution" /* Legacy CLI state, migrated on restore. */
/* Must match ScreenResolutionFragment.SAVED_RESOLUTION in Settings. */
#define RESOLUTION_SETTING "user_selected_resolution"
#define DEFAULT_CAL_PATH   "/vendor/etc/vmaxdisplay/default_calibration.txt"

#define INOTIFY_POLL_WAIT_MS 50       //Wait for further inotify events before reloading
#define MAX_CAL_POINTS 101

/* add_cal_point() stores darkest_visible (+-255) * 4, so |value| <= 1020 */
_Static_assert(255 * 4 <= PGC_LUT_ENTRIES - 1, "cal value must fit in the LUT range");

struct cal_point {
    uint32_t level; //raw backlight level
    int32_t  value; //signed LUT shift (darkest_visible * 4), -1020..1020
};

static struct cal_point g_cal_points[MAX_CAL_POINTS];
static size_t g_num_cal_points = 0;

static uint32_t (*curve_table)[PGC_LUT_ENTRIES];
static uint32_t g_max_level = 0;
/* A process-held Settings lock bypasses correction without changing saved state. */
static int g_calibrating = 0;

static void die(const char *msg) {
    LOGE("%s: %s", msg, strerror(errno));
    exit(1);
}

static int open_fb(void) {
    int fd = open(FB_DEV, O_RDWR);
    if (fd < 0) die("open fb0");
    return fd;
}

static int read_sysfs_uint(const char *path, uint32_t *out) {
    char buf[32];
    int fd = open(path, O_RDONLY);
    if (fd < 0) return -1;
    ssize_t n = read(fd, buf, sizeof(buf) - 1);
    close(fd);
    if (n <= 0) return -1;
    buf[n] = '\0';
    *out = (uint32_t)strtoul(buf, NULL, 10);
    return 0;
}

static uint32_t read_bl_event_counter(int fd) {
    char buf[32];
    if (lseek(fd, 0, SEEK_SET) < 0) return 0;
    ssize_t n = read(fd, buf, sizeof(buf) - 1);
    if (n <= 0) return 0;
    buf[n] = '\0';
    return (uint32_t)strtoul(buf, NULL, 10);
}

static int cal_point_cmp(const void *a, const void *b) {
    const struct cal_point *pa = a, *pb = b;
    if (pa->level < pb->level) return -1;
    if (pa->level > pb->level) return 1;
    return 0;
}

static int32_t clamp_i32(int32_t v, int32_t lo, int32_t hi) {
    return v < lo ? lo : (v > hi ? hi : v);
}

//Convert percentage -> raw level (rounded to nearest using detected max_level)
//and the darkest square brightness -> signed LUT value via the confirmed flat left-shift (magnitude only; see build_lut_for_value)
static void add_cal_point(int32_t pct, int32_t darkest_visible, uint32_t max_level) {
    if (g_num_cal_points >= MAX_CAL_POINTS) return;
    pct = clamp_i32(pct, 0, 100);
    darkest_visible = clamp_i32(darkest_visible, -255, 255);

    uint32_t level = ((uint32_t)pct * max_level + 50) / 100; //round to nearest
    int32_t value = darkest_visible * 4;

    g_cal_points[g_num_cal_points].level = level;
    g_cal_points[g_num_cal_points].value = value;
    g_num_cal_points++;
}

static int load_calibration_file(const char *path, uint32_t max_level) {
    FILE *f = fopen(path, "r");
    if (!f) {
        LOGD("could not open %s: %s", path, strerror(errno));
        return -1;
    }

    char line[128];
    g_num_cal_points = 0;
    while (fgets(line, sizeof(line), f) && g_num_cal_points < MAX_CAL_POINTS) {
        if (line[0] == '#' || line[0] == '\n' || line[0] == '\r')
            continue;

        int32_t pct;
        int32_t darkest_visible;
        if (sscanf(line, "%d %d", &pct, &darkest_visible) == 2)
            add_cal_point(pct, darkest_visible, max_level);
    }
    fclose(f);

    if (g_num_cal_points == 0) {
        LOGW("%s had no valid calibration points", path);
        return -1;
    }
    qsort(g_cal_points, g_num_cal_points, sizeof(g_cal_points[0]), cal_point_cmp); //sort points just in case

    LOGD("%zu calibration point(s) from %s (max_level=%u):",
         g_num_cal_points, path, max_level);
    for (size_t i = 0; i < g_num_cal_points; i++)
        LOGD("  level=%u value=%d", g_cal_points[i].level, g_cal_points[i].value);
    return 0;
}

static void use_identity(uint32_t max_level) {
    g_cal_points[0] = (struct cal_point){0, 4};
    g_cal_points[1] = (struct cal_point){max_level, 4};
    g_num_cal_points = 2;
    LOGD("using identity LUT (no correction)");
}


static void load_calibration(uint32_t max_level) {//priority: disabled > custom > default > identity
    struct stat st;
    if (g_calibrating || stat(DISABLED_FLAG_PATH, &st) == 0) {
        LOGD("calibration disabled by user (%s present)", DISABLED_FLAG_PATH);
        use_identity(max_level);
        return;
    }

    if (load_calibration_file(CAL_DEST_PATH, max_level) == 0)
        return;

    if (load_calibration_file(DEFAULT_CAL_PATH, max_level) == 0) {
        LOGD("using built-in ROM default calibration");
        return;
    }

    LOGW("no calibration available, falling back to identity LUT");
    use_identity(max_level);
}


static int32_t get_value_for_level(uint32_t level) {//interpolation
    if (level <= g_cal_points[0].level)
        return g_cal_points[0].value;
    if (level >= g_cal_points[g_num_cal_points - 1].level)
        return g_cal_points[g_num_cal_points - 1].value;
    
    size_t i = 0;
    while (level > g_cal_points[i + 1].level)
        i++;

    uint32_t l0 = g_cal_points[i].level;
    uint32_t l1 = g_cal_points[i + 1].level;
    int64_t v0 = g_cal_points[i].value;
    int64_t v1 = g_cal_points[i + 1].value;
    return (int32_t)(v0 + (v1 - v0) * (int64_t)(level - l0) / (int64_t)(l1 - l0));
}

static void build_lut_for_value(int32_t value, uint32_t *lut) {//builds the curve for a given target value
    lut[0] = 0;//zero always forced to zero for oled black

    uint32_t mag = (uint32_t)(value < 0 ? -value : value);
    int push_down = value < 0;

    if (mag <= 4) {
        for (uint32_t i = 1; i < PGC_LUT_ENTRIES; i++)
            lut[i] = i;
        return;
    }

    uint32_t span = (uint32_t)clamp_i32((int32_t)(mag * 3), 0, PGC_LUT_ENTRIES - 1);

    for (uint32_t i = 1; i < PGC_LUT_ENTRIES; i++) {
        if (i <= span) {
            double ratio = (double)(span - i) / (double)(span - 1);
            double delta = (double)(mag - 1) * (ratio * ratio); //quadratic taper
            if (push_down) {
                int32_t val = (int32_t)i - (int32_t)(delta + 0.5);
                lut[i] = (uint32_t)clamp_i32(val, 0, PGC_LUT_ENTRIES - 1);
            } else {
                int32_t val = (int32_t)i + (int32_t)(delta + 0.5);
                lut[i] = (uint32_t)clamp_i32(val, 0, PGC_LUT_ENTRIES - 1);
            }
        } else {
            lut[i] = i;
        }
    }
}

static void build_curve_table(uint32_t max_level) {//builds the whole table of curves for each brightness level
    uint32_t (*new_table)[PGC_LUT_ENTRIES] = calloc(max_level + 1, sizeof(*new_table));
    if (!new_table) {
        die("allocating curve table");
    }

    for (uint32_t lvl = 0; lvl <= max_level; lvl++) {
        int32_t value = get_value_for_level(lvl);
        build_lut_for_value(value, new_table[lvl]);
    }

    free(curve_table);
    curve_table = new_table;
    g_max_level = max_level;

    LOGD("curve table built (%u profiles, %zu bytes)",
         max_level + 1, (max_level + 1) * sizeof(*new_table));
}

static void reload(uint32_t max_level) {//reloads calibration and rebuilds the curve table
    load_calibration(max_level);
    build_curve_table(max_level);
}

static void get_curve_for_level(uint32_t level, uint32_t **c0, uint32_t **c1, uint32_t **c2) {
    if (level > g_max_level)
        level = g_max_level;

    *c0 = curve_table[level];
    *c1 = curve_table[level];
    *c2 = curve_table[level];
}

static uint32_t g_hw_curve[3][PGC_LUT_ENTRIES]; //last curves written to the hardware
static int g_hw_curve_valid = 0;

static uint64_t now_us(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000u + ts.tv_nsec / 1000;
}

static struct {
    uint64_t start, writes, skips, total, max;
} g_stats;

static void stats_report(void) {
    uint64_t now = now_us();
    if (g_stats.start == 0) g_stats.start = now;
    if (now - g_stats.start < 1000000) return;
    LOGD("stats: writes=%llu skips=%llu ioctl avg=%lluus max=%lluus",
         (unsigned long long)g_stats.writes, (unsigned long long)g_stats.skips,
         (unsigned long long)(g_stats.writes ? g_stats.total / g_stats.writes : 0),
         (unsigned long long)g_stats.max);
    memset(&g_stats, 0, sizeof(g_stats));
    g_stats.start = now;
}

static int apply_curve(int fb_fd, uint32_t *c0, uint32_t *c1, uint32_t *c2) {
    uint32_t *c[3] = { c0, c1, c2 };

    if (g_hw_curve_valid) {
        int same = 1;
        for (int i = 0; i < 3 && same; i++)
            same = memcmp(g_hw_curve[i], c[i], sizeof(g_hw_curve[i])) == 0;
        if (same) {
            g_stats.skips++;
            return 1; //skipped write, curve same as already applied one
        }
    }

    struct mdp_pgc_lut_data_v1_7 v17;
    memset(&v17, 0, sizeof(v17));
    v17.len = PGC_LUT_ENTRIES;
    v17.c0_data = c0;
    v17.c1_data = c1;
    v17.c2_data = c2;

    struct msmfb_mdp_pp pp;
    memset(&pp, 0, sizeof(pp));
    pp.op = mdp_op_lut_cfg;
    pp.data.lut_cfg_data.lut_type = mdp_lut_pgc;

    struct mdp_pgc_lut_data *cfg = &pp.data.lut_cfg_data.data.pgc_lut_data;
    cfg->version = mdp_pgc_v1_7;
    cfg->block = MDP_LOGICAL_BLOCK_DISP_0 | MDSS_PP_DSPP_CFG;
    cfg->flags = MDP_PP_OPS_ENABLE | MDP_PP_OPS_WRITE;
    cfg->cfg_payload = &v17;

    uint64_t t0 = now_us();
    int rc = ioctl(fb_fd, MSMFB_MDP_PP, &pp);
    uint64_t dt = now_us() - t0;
    g_stats.writes++;
    g_stats.total += dt;
    if (dt > g_stats.max) g_stats.max = dt;

    if (rc < 0) {
        LOGE("ioctl WRITE curve failed: %s", strerror(errno));
        g_hw_curve_valid = 0; //invalidating to force next apply to write
        return -1; //failure
    }

    for (int i = 0; i < 3; i++)
        memcpy(g_hw_curve[i], c[i], sizeof(g_hw_curve[i]));
    g_hw_curve_valid = 1;
    return 0; //written
}

static int apply_level(int fb_fd, uint32_t level) {//applies curve for requested level 
    uint32_t *c0, *c1, *c2;
    get_curve_for_level(level, &c0, &c1, &c2);

    int applied = apply_curve(fb_fd, c0, c1, c2);
    //if (applied >= 0)
        //LOGD("level=%u, curve %s", level, applied ? "unchanged, skipped" : "applied");
    return applied;
}

static int setup_inotify(const char *path, uint32_t mask) {//returns a nonblocking inotify fd watching path, or -1 with errno set
    int fd = inotify_init1(IN_NONBLOCK | IN_CLOEXEC);
    if (fd < 0) return -1;
    if (inotify_add_watch(fd, path, mask) < 0) {
        int err = errno;
        close(fd);
        errno = err;
        return -1;
    }
    return fd;
}

static int drain_inotify_once(int fd) {//reads inotify queue, returns 1 if relevant to calibration file
    char buf[1024] __attribute__((aligned(__alignof__(struct inotify_event))));
    int relevant = 0;

    for (;;) {
        ssize_t n = read(fd, buf, sizeof(buf));
        if (n <= 0) break; // EAGAIN (drained) or error

        for (char *p = buf; p < buf + n; ) {
            struct inotify_event *ev = (struct inotify_event *)p;
            if (ev->len && (strcmp(ev->name, CAL_NAME) == 0 ||
                            strcmp(ev->name, DISABLED_NAME) == 0 ||
                            strcmp(ev->name, SESSION_NAME) == 0))
                relevant = 1;
            p += sizeof(*ev) + ev->len;
        }
    }
    return relevant;
}

static int drain_inotify(int fd) {//polls inotify queue for INOTIFY_POLL_WAIT_MS
    int relevant = drain_inotify_once(fd);
    struct pollfd p = { .fd = fd, .events = POLLIN };
    while (poll(&p, 1, INOTIFY_POLL_WAIT_MS) > 0 && (p.revents & POLLIN)) {
        if (drain_inotify_once(fd))
            relevant = 1;
    }
    return relevant;
}

static int cmd_submit(const char *src_path) {
    FILE *in = fopen(src_path, "r");
    if (!in) {
        fprintf(stderr, "cannot open %s: %s\n", src_path, strerror(errno));
        return 1;
    }

    const char *temporary = CAL_DIR "/calibration.cli.tmp";
    FILE *out = fopen(temporary, "w");
    if (!out) {
        fprintf(stderr, "cannot write %s: %s\n", CAL_DEST_PATH, strerror(errno));
        fclose(in);
        return 1;
    }    
    if (fchmod(fileno(out), 0644) != 0)
        fprintf(stderr, "warning: chmod failed: %s\n", strerror(errno));

    char buf[4096];
    size_t n;
    while ((n = fread(buf, 1, sizeof(buf), in)) > 0) {
        if (fwrite(buf, 1, n, out) != n) {
            fprintf(stderr, "write error: %s\n", strerror(errno));
            fclose(in);
            fclose(out);
            return 1;
        }
    }
    fclose(in);
    if (fclose(out) != 0) {
        fprintf(stderr, "write error: %s\n", strerror(errno));
        return 1;
    }

    if (rename(temporary, CAL_DEST_PATH) != 0) {
        fprintf(stderr, "cannot replace calibration: %s\n", strerror(errno));
        unlink(temporary);
        return 1;
    }
    if (unlink(DISABLED_FLAG_PATH) != 0 && errno != ENOENT)
        fprintf(stderr, "warning: could not clear disabled flag: %s\n", strerror(errno));
    printf("calibration updated from %s\n", src_path);
    return 0;
}

static int cmd_current(void) {
    struct stat st;
    if (stat(DISABLED_FLAG_PATH, &st) == 0) {
        printf("# calibration disabled (identity LUT)\n");
        return 0;
    }

    int using_default = (stat(CAL_DEST_PATH, &st) != 0);
    const char *path = using_default ? DEFAULT_CAL_PATH : CAL_DEST_PATH;
    FILE *f = fopen(path, "r");
    if (!f) {
        fprintf(stderr, "cannot open %s: %s\n", path, strerror(errno));
        return 1;
    }
    printf("# %s%s:\n", path, using_default ? " (ROM default, none submitted)" : "");
    char buf[256];
    size_t n;
    while ((n = fread(buf, 1, sizeof(buf), f)) > 0)
        fwrite(buf, 1, n, stdout);
    fclose(f);
    return 0;
}

static int cmd_default(void) {
    unlink(CAL_DEST_PATH);
    unlink(DISABLED_FLAG_PATH);
    printf("reverted to ROM default calibration\n");
    return 0;
}

static int cmd_disable(void) {
    /* Settings may already have created this flag. Do not overwrite another owner's file. */
    int fd = open(DISABLED_FLAG_PATH, O_WRONLY | O_CREAT | O_EXCL, 0644);
    if (fd < 0 && errno != EEXIST) {
        fprintf(stderr, "cannot write %s: %s\n", DISABLED_FLAG_PATH, strerror(errno));
        return 1;
    }
    if (fd >= 0) close(fd);

    printf("calibration disabled (identity LUT)\n");
    return 0;
}

#define RES_BASE_WIDTH   1440   /* stock QHD width */
#define RES_BASE_DENSITY 540    /* stock density at QHD */

static const struct {
    const char *name, *alias;
    int width, height;
} RES_MODES[] = {
    { "hd",  "720",  720,  1440 },
    { "fhd", "1080", 1080, 2160 },
    { "qhd", "1440", 1440, 2880 },
};

static size_t find_resolution(const char *arg) {
    size_t i;
    for (i = 0; i < sizeof(RES_MODES) / sizeof(RES_MODES[0]); i++) {
        char dimensions[32];
        snprintf(dimensions, sizeof(dimensions), "%dx%d", RES_MODES[i].width, RES_MODES[i].height);
        if (!strcmp(arg, RES_MODES[i].name) || !strcmp(arg, RES_MODES[i].alias) ||
            !strcmp(arg, dimensions))
            break;
    }
    return i;
}

static int run_android_command(char *const argv[]) {
    pid_t pid = fork();
    if (pid < 0) {
        perror("fork");
        return 1;
    }
    if (pid == 0) {
        execv("/system/bin/cmd", argv);
        perror("exec cmd");
        _exit(127);
    }
    int status;
    pid_t waited;
    do {
        waited = waitpid(pid, &status, 0);
    } while (waited < 0 && errno == EINTR);
    if (waited < 0 || !WIFEXITED(status) || WEXITSTATUS(status) != 0) {
        fprintf(stderr, "cmd %s failed\n", argv[1]);
        return 1;
    }
    return 0;
}

static int apply_resolution(size_t i) {
    char w[16], h[16];
    snprintf(w, sizeof(w), "%d", RES_MODES[i].width);
    snprintf(h, sizeof(h), "%d", RES_MODES[i].height);
    /* WIDTH HEIGHT REFRESH-RATE DISPLAY_ID; 0 refresh = resolution-only, display 0 = internal panel */
    char *const argv[] = { "cmd", "display", "set-user-preferred-display-mode", w, h, "0", "0", NULL };
    if (run_android_command(argv) != 0)
        return 1;

    /* wm density, scaled from the stock QHD density to preserve apparent UI size. */
    char density[16];
    snprintf(density, sizeof(density), "%d",
             (RES_BASE_DENSITY * RES_MODES[i].width + RES_BASE_WIDTH / 2) / RES_BASE_WIDTH);
    char *const density_argv[] = { "cmd", "window", "density", density, NULL };
    if (run_android_command(density_argv) != 0) {
        fprintf(stderr, "resolution applied but density adjustment failed\n");
        return 1;
    }
    return 0;
}

static int save_resolution(size_t i) {
    char dimensions[32];
    snprintf(dimensions, sizeof(dimensions), "%dx%d", RES_MODES[i].width, RES_MODES[i].height);
    char *const argv[] = { "cmd", "settings", "put", "global", RESOLUTION_SETTING, dimensions, NULL };
    return run_android_command(argv);
}

static int cmd_resolution(const char *arg) {
    size_t i = find_resolution(arg);
    if (i == sizeof(RES_MODES) / sizeof(RES_MODES[0])) {
        fprintf(stderr, "unknown resolution '%s' (hd|fhd|qhd or 720|1080|1440)\n", arg);
        return 1;
    }
    if (apply_resolution(i) != 0)
        return 1;
    if (save_resolution(i) != 0) {
        fprintf(stderr, "resolution applied but could not save Settings.Global.%s\n",
                RESOLUTION_SETTING);
        return 1;
    }

    printf("resolution %dx%d, density %d applied and saved\n",
           RES_MODES[i].width, RES_MODES[i].height,
           (RES_BASE_DENSITY * RES_MODES[i].width + RES_BASE_WIDTH / 2) / RES_BASE_WIDTH);
    return 0;
}

static int cmd_restore_resolution(void) {
    /* Read the same value Settings writes, not DisplayManager's possibly reset boot mode. */
    FILE *f = popen("/system/bin/cmd settings get global " RESOLUTION_SETTING, "r");
    if (!f) {
        LOGE("could not read saved resolution: %s", strerror(errno));
        return 1;
    }

    char mode[32], extra;
    int count = fscanf(f, "%31s %c", mode, &extra);
    int read_error = ferror(f);
    int status = pclose(f);
    if (read_error || count != 1 || status == -1 ||
        !WIFEXITED(status) || WEXITSTATUS(status) != 0) {
        LOGE("could not read Settings.Global.%s", RESOLUTION_SETTING);
        return 1;
    }

    int legacy = !strcmp(mode, "null");
    if (legacy) {
        /* One-time migration for users who saved a mode with the old CLI. Never let a
         * stale legacy file override a newer Settings or CLI selection. */
        f = fopen(RESOLUTION_PATH, "r");
        if (!f) {
            if (errno == ENOENT) return 0; /* No preference saved yet. */
            LOGE("could not read legacy resolution: %s", strerror(errno));
            return 1;
        }
        count = fscanf(f, "%31s %c", mode, &extra);
        read_error = ferror(f);
        fclose(f);
    }

    size_t i = count == 1 ? find_resolution(mode) : sizeof(RES_MODES) / sizeof(RES_MODES[0]);
    if (read_error || i == sizeof(RES_MODES) / sizeof(RES_MODES[0])) {
        LOGE("invalid saved resolution");
        return 1;
    }

    if (apply_resolution(i) != 0) {
        LOGE("could not restore resolution %s", RES_MODES[i].name);
        return 1;
    }
    if (legacy && save_resolution(i) != 0) {
        LOGE("restored legacy resolution but could not migrate it to Settings.Global");
        return 1;
    }
    LOGD("restored resolution %s", RES_MODES[i].name);
    return 0;
}

/* POSIX locks are released by the kernel on process death. A leftover file is inert. */
static char g_session_token[33];

static int calibration_session(void) {
    int fd = open(SESSION_PATH, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0) return 0;
    struct flock lock = { .l_type = F_RDLCK, .l_whence = SEEK_SET, .l_start = 0, .l_len = 0 };
    int active = fcntl(fd, F_GETLK, &lock) == 0 && lock.l_type == F_WRLCK;
    char token[33] = {0};
    if (active) {
        ssize_t n = read(fd, token, 32);
        active = n == 32 && strspn(token, "0123456789abcdef") == 32;
    }
    close(fd);
    if (active) memcpy(g_session_token, token, sizeof(token));
    return active;
}

static void calibration_status(uint32_t max_level, uint32_t level) {
    /* The token prevents an old acknowledgement from activating a new editor session. */
    static char last_reply[80];
    char reply[80];
    int len = snprintf(reply, sizeof(reply), "%s %u %u\n", g_session_token, max_level, level);
    if (strcmp(last_reply, reply) == 0) return;
    int fd = open(STATUS_PATH, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC | O_NOFOLLOW, 0644);
    if (fd < 0) {
        LOGW("cannot write calibration status: %s", strerror(errno));
        return;
    }
    if (write(fd, reply, len) == len)
        memcpy(last_reply, reply, len + 1);
    else
        LOGW("cannot write complete calibration status");
    close(fd);
}

static int run_daemon(void) { //main function
    int bl_event_fd = open(BL_EVENT_PATH, O_RDONLY);
    if (bl_event_fd < 0) die("open bl_event");

    uint32_t max_level = 511;
    if (read_sysfs_uint(BL_MAX_BRIGHTNESS_PATH, &max_level) < 0)
        LOGW("couldn't read max_brightness, assuming %u", max_level);
    LOGD("max_level=%u", max_level);

    /* Watch before loading/reading, so a change landing in between isn't missed. */
    int cal_inotify_fd = setup_inotify(CAL_DIR, IN_MODIFY | IN_CLOSE_WRITE | IN_DELETE | IN_MOVED_TO);
    if (cal_inotify_fd < 0)
        LOGW("inotify on %s failed: %s (live reload disabled)", CAL_DIR, strerror(errno));

    /* Fires whenever userspace (the light HAL) writes the backlight level. */
    int bl_inotify_fd = setup_inotify(BL_BRIGHTNESS_PATH, IN_MODIFY | IN_CLOSE_WRITE);
    if (bl_inotify_fd < 0) die("inotify on brightness");

    g_calibrating = calibration_session();
    reload(max_level);

    int fb_fd = open_fb();

    /* Arm the pollable dirent: an initial read is needed before poll()
     * will correctly block on/wake for later changes. */
    read_bl_event_counter(bl_event_fd);

    int last_applied_level = -1;
    uint32_t level;
    int screen_on = 1; /* refined against the actual initial level below */

    /* Apply once for whatever the level already is at startup, rather
     * than waiting for the first change after the daemon comes up. */
    if (read_sysfs_uint(BL_BRIGHTNESS_PATH, &level) == 0) {
        screen_on = (level != 0);
        LOGD("initial level=%u (screen_on=%d)", level, screen_on);
        if (apply_level(fb_fd, level) >= 0) {
            last_applied_level = (int)level;
            if (g_calibrating) calibration_status(g_max_level, level);
        }
    }

    /* A negative fd (inotify unavailable) is ignored by poll(). */
    struct pollfd pfds[3] = {
        { .fd = bl_event_fd,     .events = POLLPRI | POLLERR },
        { .fd = cal_inotify_fd,  .events = POLLIN },
        { .fd = bl_inotify_fd,   .events = POLLIN },
    };

    for (;;) {
        /* Only calibration sessions need a timer to detect a released/crashed lock.
         * Normal operation still sleeps until a display or calibration event. */
        if (poll(pfds, 3, g_calibrating ? 250 : -1) < 0) {
            if (errno == EINTR) continue;
            die("poll");
        }

        if (pfds[0].revents)
            read_bl_event_counter(bl_event_fd); /* re-arm on a real event */

        if ((pfds[1].revents & POLLIN) && drain_inotify(cal_inotify_fd)) {
            LOGD("calibration changed, reloading");
            reload(g_max_level);
            last_applied_level = -1; /* force reapply with new table */
        }

        if (pfds[2].revents & POLLIN)
            drain_inotify_once(bl_inotify_fd); /* only the wakeup matters; level is read below */

        int calibrating = calibration_session();
        if (calibrating != g_calibrating) {
            g_calibrating = calibrating;
            reload(g_max_level);
            last_applied_level = -1;
        }

        if (read_sysfs_uint(BL_BRIGHTNESS_PATH, &level) < 0) {
            LOGW("brightness read failed, skipping");
            continue;
        }

        if ((int)level == last_applied_level || (int)level == 0) {
            if (g_calibrating && (int)level == last_applied_level)
                calibration_status(g_max_level, level);
            continue;
        }

        if (apply_level(fb_fd, level) < 0)
            continue; /* last_applied_level untouched, so the next event retries */
        last_applied_level = (int)level;
        if (g_calibrating) calibration_status(g_max_level, level);
        stats_report();
    }
}

static int usage(const char *prog) {
    fprintf(stderr, "usage: %s [<calibration file> | current | default | disable | resolution <hd|fhd|qhd|restore>]\n", prog);
    return 1;
}

int main(int argc, char **argv) {
    if (argc >= 2 && strcmp(argv[1], "resolution") == 0) {
        if (argc != 3) return usage(argv[0]);
        if (strcmp(argv[2], "restore") == 0) return cmd_restore_resolution();
        return cmd_resolution(argv[2]);
    }

    if (argc > 2)
        return usage(argv[0]);

    if (argc == 2) {
        if (strcmp(argv[1], "disable") == 0) return cmd_disable();
        if (strcmp(argv[1], "default") == 0) return cmd_default();
        if (strcmp(argv[1], "current") == 0) return cmd_current();
        return cmd_submit(argv[1]);
    }
    return run_daemon();
}
