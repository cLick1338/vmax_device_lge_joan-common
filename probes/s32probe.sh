#!/system/bin/sh
#Vmax
# PCM on QUAT_TDM_RX_0 (DAC clock master, kernel PCM-master: MASTER_DIV or NCO): stops the HAL, plays <wav>, prints DAC state + logs
# usage: s32probe.sh <wav> <rate enum e.g. KHZ_352P8> [fmt=S32_LE] [atten=80]
D=/data/local/tmp/hifit
WAV=$1; RATE=$2; FMT=${3:-S32_LE}; ATT=${4:-80}
TM=$D/tinymix; TP=$D/tinyplay; SYS=/sys/kernel/es9218_dac
HAL=$(getprop | sed -n 's/^\[init\.svc\.\(vendor\.audio-hal[^]]*\)\]: \[running\]/\1/p' | head -1)
stop audioserver; [ -n "$HAL" ] && stop "$HAL"; sleep 1
DEV=$(sed -n 's/^00-0*\([0-9]*\): MultiMedia2 .*playback.*/\1/p' /proc/asound/pcm | head -1); DEV=${DEV:-1}
regs() { grep -E "^(00|01|06|07|10|3[4-7]|64|72)_" $SYS/registers | sed "s/ *<#[0-9]*>= /=/" | tr '\n' ' '; echo; grep -E "state|dop|rate|bits|osf" $SYS/status | tr '\n' ' '; echo; }
for m in 1 2 4 5 7 9 10; do $TM "QUAT_MI2S_RX Audio Mixer MultiMedia$m" 0 >/dev/null 2>&1; done
$TM "QUAT_TDM SlotNumber" Two; $TM "QUAT_TDM SlotWidth" 32
$TM "QUAT_TDM_RX_0 SampleRate" "$RATE"; $TM "QUAT_TDM_RX_0 Format" "$FMT"
$TM "QUAT_TDM_RX_0 Channels" Two; $TM "QUAT_TDM_RX_0 Data Format" LPCM
$TM "Es9018 Dop" 0; $TM "Es9018 Playback Attenuation" "$ATT" "$ATT"
$TM "QUAT_TDM_RX_0 Audio Mixer MultiMedia2" 1
dmesg -c >/dev/null
$TP "$WAV" -D 0 -d "$DEV" -p 2048 -n 4 & PID=$!; T0=$(date +%s)
for t in 2 5; do sleep 2; echo "--- t=${t}s"; regs; done
wait $PID; echo "tinyplay exit $? after $(( $(date +%s) - T0 ))s"
echo "--- dmesg"; dmesg | grep -iE "es9218|afe|tdm|q6asm|adm|routing|hw_params" | tail -30
$TM "QUAT_TDM_RX_0 Audio Mixer MultiMedia2" 0; $TM "Es9018 Playback Attenuation" 0 0
$TM "QUAT_TDM_RX_0 Format" S24_LE
[ -n "$HAL" ] && start "$HAL"; start audioserver; echo restored
