#!/usr/bin/env bash
# Copy one part of the project to its Raspberry Pi and restart its service(s).
#
#   ./deploy.sh scanner             scanner/      -> scanner:~/expiry_cam/,  restart expiry-cam
#   ./deploy.sh server              server/       -> pi5:~/expiry_cam/,      restart expiry-server + expiry-bot
#   ./deploy.sh research            ocr_research/ -> pi5:~/expiry_cam/ocr_research/  (no restart)
#   ./deploy.sh <part> --dry-run    only show what would change, copy nothing
#
# Hosts come from ~/.ssh/config (Host scanner / Host pi5) or SCANNER_HOST / SERVER_HOST.
# Device-only files (venv, photos, database, bot.env, dataset, ...) are excluded: they are
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
    dest="expiry_cam/"
    services=(expiry-cam)
    excludes=(venv/ captures/ ".lgd-nfy*")          # .lgd-nfy* = gpio pipes of the running app
    ;;
  server)
    host="${SERVER_HOST:-pi5}"
    dest="expiry_cam/"
    services=(expiry-server expiry-bot)
    excludes=(.venv/ venv/ uploads/ ocr_research/ dataset/ unsuccessful_parse/ dont_track/ debug_output/
              bot.env "*.db" "*.db-wal" "*.db-shm" "*.jpg" "*.png")
    ;;
  research)
    host="${SERVER_HOST:-pi5}"
    dest="expiry_cam/ocr_research/"
    services=()
    excludes=(dataset/ unsuccessful_parse/ debug_output/ "*.db" "*.db-wal" "*.db-shm" "*.jpg" "*.png")
    ;;
  *)
    echo "usage: $0 scanner|server|research [--dry-run]" >&2
    exit 1
    ;;
esac
src="$part/"
[[ "$part" == "research" ]] && src="ocr_research/"
[[ -d "$src" ]] || { echo "folder $src not found" >&2; exit 1; }

args=(-av --delete --exclude "__pycache__/" --exclude ".git/")
for e in "${excludes[@]}"; do
  args+=(--exclude "$e")
done

rsync "${args[@]}" $dry "$src" "$host:$dest"

if [[ -n "$dry" ]]; then
  echo "(dry run: nothing was changed)"
  exit 0
fi
for s in "${services[@]}"; do
  ssh -t "$host" sudo systemctl restart "$s"
done
echo "deployed $src to $host:$dest"
