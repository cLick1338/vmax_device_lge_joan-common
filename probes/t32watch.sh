#!/system/bin/sh
#Vmax
# Log route + DAC state once a second while a 32-bit stream plays; usage: t32watch.sh <wav> <secs>
SYS=/sys/kernel/es9218_dac; TM=/data/local/tmp/hifit/tinymix; LOG=/data/local/tmp/hifit/t32watch.log
logcat -c; : > $LOG
am start -n org.vmax.hifitest/.Main --es mode wav --es file $1 --ei secs $2 >/dev/null
i=0; while [ $i -lt $(($2 + 2)) ]; do
  echo "t=$i $(grep -E '^(10|64)_' $SYS/registers | sed 's/ *<#[0-9]*>= /=/;s/_[A-Z_&]*=/=/' | tr '\n' ' ')$(grep -E 'state|rate|bits|headset_type' $SYS/status | tr '\n' ' ') tdm=$($TM 'QUAT_TDM_RX_0 Format' | grep -o '>[A-Z0-9_]*') hifi=$(getprop persist.vendor.audio.hifi.enabled)" >> $LOG
  sleep 1; i=$((i + 1))
done
logcat -d | grep -E "HiFiTest: (done|failed)|takes the Hi-Fi|leaves the Hi-Fi|output device from|becf: afe: (Hi-Fi DAC backend|.*mixer set)|restarting it|hifi_dac=|Attenuation|error" | grep -vE "Thermal|Bluetooth|WindowManager" | cut -c7-18,31- >> $LOG
