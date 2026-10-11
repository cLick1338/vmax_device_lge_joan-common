#!/system/bin/sh
#Vmax
# T32 HAL check: play a 32-bit WAV through HiFiTest, print the route, TDM format and DAC registers
F=$1; SECS=${2:-8}; SYS=/sys/kernel/es9218_dac; TM=/data/local/tmp/hifit/tinymix
logcat -c
am start -W -n org.vmax.hifitest/.Main --es mode wav --es file $F --ei secs $SECS >/dev/null
sleep 3
grep -E "^(00|10|3[4-7]|64|72)_" $SYS/registers | sed "s/ *<#[0-9]*>= /=/" | tr '\n' ' '; echo
grep -E "state|rate|bits|dop=|osf" $SYS/status | tr '\n' ' '; echo
$TM "QUAT_TDM_RX_0 SampleRate" | grep -o ">[A-Z0-9_]*"; $TM "QUAT_TDM_RX_0 Format" | grep -o ">[A-Z0-9_]*"
$TM "QUAT_MI2S_RX SampleRate" 2>/dev/null | grep -o ">[A-Z0-9_]*"
logcat -d | grep -E "takes the Hi-Fi DAC|leaves the Hi-Fi DAC|becf: afe: .*(mixer set|Hi-Fi DAC backend)|enable_snd_device: snd_device\(|select_devices.*headphones|hifitest.*wav|AudioTrack.*(error|fail)|hw_params|-EINVAL" | cut -c19- | tail -12
sleep $((SECS - 2))
