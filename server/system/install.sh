#!/bin/sh
# One-time system setup on the Pi 5, run on the Pi from ~/expiry_cam:
#     sudo system/install.sh
# Installs the server and bot services and a sudo rule that lets deploy.sh restart
# them without a password. bot.env (the Telegram token) is never touched.
set -e
cd "$(dirname "$0")"
USER_NAME="${SUDO_USER:-rasient}"

install -m 644 expiry-server.service /etc/systemd/system/expiry-server.service
install -m 644 expiry-bot.service /etc/systemd/system/expiry-bot.service

RULE=/etc/sudoers.d/expiry-server
TMP=$(mktemp)
CMDS=""
for svc in expiry-server expiry-bot; do
  for action in restart stop start; do
    CMDS="$CMDS${CMDS:+, }/usr/bin/systemctl $action $svc"
  done
done
echo "$USER_NAME ALL=(root) NOPASSWD: $CMDS" > "$TMP"
visudo -cf "$TMP"                    # never install a broken sudoers file
install -m 440 "$TMP" "$RULE"
rm -f "$TMP"

systemctl daemon-reload
systemctl enable expiry-server expiry-bot
[ -f ../bot.env ] || echo "Note: ~/expiry_cam/bot.env is missing (copy bot.env.example and add the token)"
echo "Done. Restart with: sudo systemctl restart expiry-server expiry-bot"
