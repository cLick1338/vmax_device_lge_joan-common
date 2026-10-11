#!/system/bin/sh
#Vmax
# PCM master on QUAT_TDM_RX_0 at any 44.1-family rate: start as DoP64 (R0 0x04, R10 0x82), then set R10 MASTER_DIV, clear DoP_ENABLE
# usage: s32div.sh <wav> <rate enum> <fmt> <r10 hex> [r0 0x00|0x04] [atten=80]
D=/data/local/tmp/hifit
WAV=$1; RATE=$2; FMT=$3; R10=$4; R0=$5; ATT=${6:-80}
case "$R0" in ""|0x00|0x04) ;; *) echo "R0 must be 0x00 or 0x04 (CLK_GEAR /1 or /2)"; exit 1;; esac
TM=$D/tinymix; TP=$D/tinyplay; SYS=/sys/kernel/es9218_dac; R=$SYS/registers
HAL=$(getprop | sed -n 's/^\[init\.svc\.\(vendor\.audio-hal[^]]*\)\]: \[running\]/\1/p' | head -1)
stop audioserver; [ -n "$HAL" ] && stop "$HAL"; sleep 1
DEV=$(sed -n 's/^00-0*\([0-9]*\): MultiMedia2 .*playback.*/\1/p' /proc/asound/pcm | head -1); DEV=${DEV:-1}
regs() { grep -E "^(00|01|06|07|10|64|72)_" $R | tr '\n' ' '; echo; grep -E "state|dop|rate|bits|osf" $SYS/status | tr '\n' ' '; echo; }
w() { echo "$1 $2" > $R; }
for m in 1 2 4 5 7 9 10; do $TM "QUAT_MI2S_RX Audio Mixer MultiMedia$m" 0 >/dev/null 2>&1; done
$TM "QUAT_TDM SlotNumber" Two; $TM "QUAT_TDM SlotWidth" 32
$TM "QUAT_TDM_RX_0 SampleRate" "$RATE"; $TM "QUAT_TDM_RX_0 Format" "$FMT"
$TM "QUAT_TDM_RX_0 Channels" Two; $TM "QUAT_TDM_RX_0 Data Format" LPCM
$TM "Es9018 Dop" 64; $TM "Es9018 Playback Attenuation" "$ATT" "$ATT"
$TM "QUAT_TDM_RX_0 Audio Mixer MultiMedia2" 1
dmesg -c >/dev/null
$TP "$WAV" -D 0 -d "$DEV" -p 2048 -n 4 & PID=$!; T0=$(date +%s)
sleep 1; echo "--- t=1s DoP master"; regs
w 10_MASTER_MODE_\&_SYNC_CONFIGURATION $R10
[ -n "$R0" ] && w 00_SYSTEM_REGISTERS $R0
w 06_DoP_\&_VOLUME_RAMP_RATE 0x43
for t in 3 5 8; do sleep 2; echo "--- t=${t}s PCM master"; regs; done
wait $PID; echo "tinyplay exit $? after $(( $(date +%s) - T0 ))s"
echo "--- dmesg"; dmesg | grep -iE "es9218|afe|tdm|q6asm|adm|hw_params|i2c" | tail -30
$TM "QUAT_TDM_RX_0 Audio Mixer MultiMedia2" 0; $TM "Es9018 Dop" 0; $TM "Es9018 Playback Attenuation" 0 0
$TM "QUAT_TDM_RX_0 Format" S24_LE
[ -n "$HAL" ] && start "$HAL"; start audioserver; echo restored
