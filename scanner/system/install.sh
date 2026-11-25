#!/bin/sh
# One-time system setup on the scanner, run on the Pi from ~/expiry_cam:
#     sudo system/install.sh
# Installs the systemd service, the "Safe to switch OFF" shutdown hook and a sudo
# rule that lets deploy.sh restart the service without a password.
set -e
cd "$(dirname "$0")"
USER_NAME="${SUDO_USER:-rasient}"

install -m 644 expiry-cam.service /etc/systemd/system/expiry-cam.service
install -d /usr/lib/systemd/system-shutdown
install -m 755 oled-safe /usr/lib/systemd/system-shutdown/oled-safe

RULE=/etc/sudoers.d/expiry-cam
TMP=$(mktemp)
echo "$USER_NAME ALL=(root) NOPASSWD: /usr/bin/systemctl restart expiry-cam, /usr/bin/systemctl stop expiry-cam, /usr/bin/systemctl start expiry-cam" > "$TMP"
visudo -cf "$TMP"                    # never install a broken sudoers file
install -m 440 "$TMP" "$RULE"
rm -f "$TMP"

systemctl daemon-reload
systemctl enable expiry-cam
echo "Done. Restart the app with: sudo systemctl restart expiry-cam"
