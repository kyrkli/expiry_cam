#!/bin/sh
# I2C reliability test: 300 transfers to one device, counts errors.
# Usage (from ~/expiry_cam):  tools/i2c_test.sh 0x48   (ADS1115)
#                             tools/i2c_test.sh 0x3c   (OLED)
# Healthy wiring gives err=0.
addr="${1:?usage: $0 0x48|0x3c}"
ok=0; err=0
for i in $(seq 300); do
  if [ "$addr" = "0x48" ]; then
    /usr/sbin/i2cget -y 1 0x48 0x00 w >/dev/null 2>&1
  else
    /usr/sbin/i2cset -y 1 "$addr" 0x40 0x00 2>/dev/null
  fi && ok=$((ok+1)) || err=$((err+1))
done
echo "$addr: ok=$ok err=$err"
