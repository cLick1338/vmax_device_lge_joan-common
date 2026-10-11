#!/system/bin/sh
#Vmax
# PCM master on QUAT_TDM_RX_0 with the NCO: start as DoP64, then R0 0x00, NCO_NUM (R34 LSB .. R37 MSB), clear DoP_ENABLE
# usage: s32nco.sh <wav> <rate enum> <fmt> <nco hex 32-bit> [atten=80] [r7 hex, 0x28 = OSF bypass above 192 kHz]
D=/data/local/tmp/hifit
WAV=$1; RATE=$2; FMT=$3; NCO=$(($4)); ATT=${5:-80}; R7=$6
TM=$D/tinymix; TP=$D/tinyplay; SYS=/sys/kernel/es9218_dac; R=$SYS/registers
HAL=$(getprop | sed -n 's/^\[init\.svc\.\(vendor\.audio-hal[^]]*\)\]: \[running\]/\1/p' | head -1)
stop audioserver; [ -n "$HAL" ] && stop "$HAL"; sleep 1
DEV=$(sed -n 's/^00-0*\([0-9]*\): MultiMedia2 .*playback.*/\1/p' /proc/asound/pcm | head -1); DEV=${DEV:-1}
regs() { grep -E "^(00|01|06|07|10|3[4-7]|64|72)_" $R | tr '\n' ' '; echo; grep -E "state|dop|rate|bits|osf" $SYS/status | tr '\n' ' '; echo; }
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
[ -n "$R7" ] && w 07_FIILTER_BANDWIDTH_\&_SYSTEM_MUTE $R7
w 00_SYSTEM_REGISTERS 0x00
w 34_PROGRAMMABLE_NCO_4 $(printf 0x%02x $((NCO & 255)))
w 35_PROGRAMMABLE_NCO_3 $(printf 0x%02x $((NCO >> 8 & 255)))
w 36_PROGRAMMABLE_NCO_2 $(printf 0x%02x $((NCO >> 16 & 255)))
w 37_PROGRAMMABLE_NCO_1 $(printf 0x%02x $((NCO >> 24 & 255)))
w 06_DoP_\&_VOLUME_RAMP_RATE 0x43
for t in 3 5 8; do sleep 2; echo "--- t=${t}s PCM master"; regs; done
wait $PID; echo "tinyplay exit $? after $(( $(date +%s) - T0 ))s"
echo "--- dmesg"; dmesg | grep -iE "es9218|afe|tdm|q6asm|adm|hw_params|i2c" | tail -30
$TM "QUAT_TDM_RX_0 Audio Mixer MultiMedia2" 0; $TM "Es9018 Dop" 0; $TM "Es9018 Playback Attenuation" 0 0
w 37_PROGRAMMABLE_NCO_1 0x00; w 36_PROGRAMMABLE_NCO_2 0x00; w 35_PROGRAMMABLE_NCO_3 0x00; w 34_PROGRAMMABLE_NCO_4 0x00
$TM "QUAT_TDM_RX_0 Format" S24_LE
[ -n "$HAL" ] && start "$HAL"; start audioserver; echo restored
