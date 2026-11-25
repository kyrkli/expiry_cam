#!/usr/bin/env bash
# Copy one part of the project to its Raspberry Pi and restart its service(s).
#
#   ./deploy.sh scanner             copy scanner/ to the hand scanner, restart expiry-cam
#   ./deploy.sh server              copy server/ to the Pi 5, restart expiry-server + expiry-bot
#   ./deploy.sh scanner --dry-run   only show what would change, copy nothing
#
# Hosts come from ~/.ssh/config (Host scanner / Host pi5) or SCANNER_HOST / SERVER_HOST.
# Device-only files (venv, photos, database, bot.env, ...) are excluded: they are
# never copied and never deleted. Everything else on the device mirrors the repo
# (files removed from the repo are removed there too, see "deleting" in the output).
set -euo pipefail
cd "$(dirname "$0")"

part="${1:-}"
dry=""
[[ "${2:-}" == "--dry-run" ]] && dry="--dry-run"

case "$part" in
  scanner)
    host="${SCANNER_HOST:-scanner}"
    services=(expiry-cam)
    excludes=(venv/ captures/ ".lgd-nfy*")          # .lgd-nfy* = gpio pipes of the running app
    ;;
  server)
    host="${SERVER_HOST:-pi5}"
    services=(expiry-server expiry-bot)
    excludes=(.venv/ venv/ uploads/ dataset/ unsuccessful_parse/ bot.env "*.db" "*.db-wal" "*.db-shm")
    ;;
  *)
    echo "usage: $0 scanner|server [--dry-run]" >&2
    exit 1
    ;;
esac
[[ -d "$part" ]] || { echo "folder $part/ not found" >&2; exit 1; }

args=(-av --delete --exclude "__pycache__/" --exclude ".git/")
for e in "${excludes[@]}"; do
  args+=(--exclude "$e")
done

rsync "${args[@]}" $dry "$part/" "$host:expiry_cam/"

if [[ -n "$dry" ]]; then
  echo "(dry run: nothing was changed)"
  exit 0
fi
for s in "${services[@]}"; do
  ssh -t "$host" sudo systemctl restart "$s"
done
echo "deployed $part/ to $host"
