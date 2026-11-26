#!/usr/bin/env bash
# Stops FM Control. Your data is kept; start it again with Start-Mac.command.
cd "$(dirname "$0")/.." || exit 1
if ! command -v docker >/dev/null 2>&1; then
  for dir in /Applications/Docker.app/Contents/Resources/bin /usr/local/bin /opt/homebrew/bin; do
    [ -x "$dir/docker" ] && PATH="$dir:$PATH" && break
  done
fi
if ! docker info >/dev/null 2>&1; then
  echo "Docker is not running, so FM Control is already stopped."
else
  docker compose stop && echo "Stopped. Your data is kept. Double-click Start-Mac.command to start again."
fi
if [ -t 0 ] && [ -z "${FM_NO_PAUSE:-}" ]; then printf '\nPress Enter to close this window. '; read -r _; fi
