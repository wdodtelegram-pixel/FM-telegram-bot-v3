#!/usr/bin/env bash
# FM Control launcher for macOS and Linux. Double-click Start-Mac.command (it calls this).
#
# First run: checks Docker, asks for your Telegram bot token, generates the secrets,
# starts everything, creates the first admin login, and opens the website.
# Every later run: starts (and updates) everything and opens the website.
# Safe to run again at any time.

set -u
cd "$(dirname "$0")/.." || exit 1
ROOT="$(pwd)"
ENV_FILE="$ROOT/.env"

say()  { printf '%s\n' "$*"; }
step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✔\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }

pause_and_exit() {
  local code="${1:-1}"
  if [ -t 0 ] && [ -z "${FM_NO_PAUSE:-}" ]; then
    printf '\nPress Enter to close this window. '
    read -r _
  fi
  exit "$code"
}

fail() { printf '\n\033[31m✖ %s\033[0m\n' "$*"; pause_and_exit 1; }

open_url() {
  case "$(uname -s)" in
    Darwin) open "$1" >/dev/null 2>&1 ;;
    *)      (xdg-open "$1" >/dev/null 2>&1 || true) ;;
  esac
}

random_hex() {   # random_hex <bytes>
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex "$1"
  else
    LC_ALL=C tr -dc 'a-f0-9' </dev/urandom | head -c "$(( $1 * 2 ))"
  fi
}

env_get() { [ -f "$ENV_FILE" ] && sed -n "s/^$1=//p" "$ENV_FILE" | head -n1; }

port_in_use() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

compose() { docker compose "$@"; }

# ---------------------------------------------------------------------------
say "FM Control"
say "Telegram bot + master-control website"

# 1. Docker -----------------------------------------------------------------
step "Checking Docker"
if ! command -v docker >/dev/null 2>&1; then
  # Docker Desktop on a Mac keeps its CLI here; a freshly installed one may not be on PATH yet.
  for dir in /Applications/Docker.app/Contents/Resources/bin /usr/local/bin /opt/homebrew/bin; do
    [ -x "$dir/docker" ] && PATH="$dir:$PATH" && break
  done
fi
if ! command -v docker >/dev/null 2>&1; then
  warn "Docker is not installed."
  say  "  FM Control runs inside Docker Desktop, which is free for personal and small-business use."
  say  "  1. Install it from:  https://www.docker.com/products/docker-desktop/"
  say  "  2. Open Docker Desktop once and accept its terms."
  say  "  3. Double-click this launcher again."
  open_url "https://www.docker.com/products/docker-desktop/"
  pause_and_exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  fail "Your Docker is too old (no 'docker compose'). Please update Docker Desktop."
fi

if ! docker info >/dev/null 2>&1; then
  warn "Docker is installed but not running. Starting it..."
  case "$(uname -s)" in
    Darwin) open -a Docker >/dev/null 2>&1 ;;
    *)      (systemctl --user start docker-desktop >/dev/null 2>&1 || sudo systemctl start docker >/dev/null 2>&1 || true) ;;
  esac
  waited=0
  until docker info >/dev/null 2>&1; do
    [ "$waited" -ge "${FM_DOCKER_WAIT:-240}" ] && fail "Docker did not start. Open Docker Desktop yourself, wait until it says it is running, then try again."
    printf '.'; sleep 3; waited=$(( waited + 3 ))
  done
  say ""
fi
ok "Docker is running"

# 2. Configuration ----------------------------------------------------------
if [ ! -f "$ENV_FILE" ]; then
  step "First-time setup"
  say "You need a Telegram bot. It takes one minute:"
  say "  1. In Telegram, open  @BotFather  and send  /newbot"
  say "  2. Pick a name and a username ending in 'bot'"
  say "  3. Copy the token it gives you (it looks like 123456789:AAH...)"
  say ""
  TOKEN=""
  while :; do
    printf 'Paste your bot token (typing is hidden), or press Enter to quit: '
    read -rs TOKEN; printf '\n'
    TOKEN="$(printf '%s' "$TOKEN" | tr -d '[:space:]')"
    [ -z "$TOKEN" ] && { say "No problem. Run this again when you have a token."; pause_and_exit 0; }
    if ! printf '%s' "$TOKEN" | grep -Eq '^[0-9]{6,16}:[A-Za-z0-9_-]{30,}$'; then
      warn "That does not look like a bot token (expected digits, a colon, then letters and digits). Copy the whole line from @BotFather."
      continue
    fi
    # Ask Telegram if it knows this token (skipped quietly when offline).
    reply="$(curl -fsS --max-time 10 "https://api.telegram.org/bot${TOKEN}/getMe" 2>/dev/null || true)"
    if [ -n "$reply" ] && printf '%s' "$reply" | grep -q '"ok":true'; then
      BOT_NAME="$(printf '%s' "$reply" | sed -n 's/.*"username":"\([^"]*\)".*/\1/p')"
      ok "Telegram accepted it: @${BOT_NAME}"
      break
    elif [ -n "$reply" ] || curl -fsS --max-time 5 https://api.telegram.org >/dev/null 2>&1; then
      warn "Telegram rejected that token. Check it, or send /token to @BotFather for a fresh one."
      continue
    else
      warn "Could not reach Telegram to check it (no internet?). Continuing anyway."
      break
    fi
  done

  DEFAULT_TZ="UTC"
  if [ -L /etc/localtime ]; then
    DEFAULT_TZ="$(readlink /etc/localtime | sed 's|.*/zoneinfo/||')"
  elif [ -r /etc/timezone ]; then
    DEFAULT_TZ="$(cat /etc/timezone)"
  fi
  printf 'Timezone for "today" in the bot and website [%s]: ' "$DEFAULT_TZ"
  read -r TZ_IN
  TZ_VALUE="${TZ_IN:-$DEFAULT_TZ}"

  WEB_PORT=3000
  while port_in_use "$WEB_PORT" && [ "$WEB_PORT" -lt 3020 ]; do WEB_PORT=$(( WEB_PORT + 1 )); done
  [ "$WEB_PORT" != "3000" ] && warn "Port 3000 is busy, so the website will use port $WEB_PORT."

  umask 077
  {
    echo "# Written by the FM Control launcher. Keep this file private: it holds your bot token."
    echo "TELEGRAM_BOT_TOKEN=$TOKEN"
    echo "SECRET_KEY=$(random_hex 32)"
    echo "POSTGRES_PASSWORD=$(random_hex 16)"
    echo "TZ=$TZ_VALUE"
    echo "WEB_PORT=$WEB_PORT"
  } > "$ENV_FILE"
  chmod 600 "$ENV_FILE" 2>/dev/null || true
  ok "Saved your settings to .env"
fi
WEB_PORT="$(env_get WEB_PORT)"; WEB_PORT="${WEB_PORT:-3000}"
SITE="http://localhost:${WEB_PORT}"

# 3. Images -----------------------------------------------------------------
step "Getting the application (the first time takes a few minutes)"
if compose pull --quiet >/dev/null 2>&1; then
  ok "Downloaded the latest version"
else
  warn "Prebuilt images are not available, so building from the included source."
  compose build || fail "The build failed. Scroll up for the reason, or send it to whoever set this up."
  ok "Built from source"
fi

# 4. Start ------------------------------------------------------------------
step "Starting"
compose up -d || fail "Could not start. Scroll up for the reason (a busy port is the usual cause: edit WEB_PORT in .env)."

waited=0
printf '  Waiting for the website'
until curl -fsS --max-time 3 "$SITE/api/health" >/dev/null 2>&1; do
  [ "$waited" -ge "${FM_START_WAIT:-180}" ] && { say ""; compose ps; fail "It did not become ready. Run 'docker compose logs' in this folder to see why."; }
  printf '.'; sleep 3; waited=$(( waited + 3 ))
done
printf '\n'
ok "Website is up at $SITE"
if compose ps --status running --services 2>/dev/null | grep -qx bot; then ok "Bot is running"; else warn "The bot is not running. Run 'docker compose logs bot' to see why."; fi

# 5. First admin ------------------------------------------------------------
if ! compose run --rm -T migrate python -m botapp.admin setup-status >/dev/null 2>&1; then
  step "Create your admin login"
  say "This is the login you will use on the website. The first person to claim it in Telegram becomes master control."
  say ""
  compose run --rm migrate python -m botapp.admin first-run || fail "Could not create the setup code."
  say ""
  say "Waiting for you to send the code to your bot (Ctrl+C to skip; run this launcher again later)..."
  waited=0
  until compose run --rm -T migrate python -m botapp.admin setup-status >/dev/null 2>&1; do
    [ "$waited" -ge 900 ] && { warn "Still waiting. Run this launcher again when you have sent the code."; break; }
    sleep 5; waited=$(( waited + 5 ))
  done
  compose run --rm -T migrate python -m botapp.admin setup-status >/dev/null 2>&1 && ok "You are master control."
fi

# 6. Done -------------------------------------------------------------------
step "Ready"
say "  Website:  $SITE"
say "  Bot:      open your bot in Telegram and send /start"
say ""
say "  Stop it:        double-click Stop-Mac.command"
say "  Start it again: double-click Start-Mac.command (it also installs updates)"
say "  Keep it running: it works while this computer is on and Docker Desktop is running."
say "                   In Docker Desktop > Settings, tick 'Start Docker Desktop when you sign in'."
open_url "$SITE"
pause_and_exit 0
