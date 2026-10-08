#!/usr/bin/env bash
# One-time setup check for macOS and Linux.
#
#   ./setup.sh              check everything, offer to install/start what is missing, build the image
#   ./setup.sh --yes        answer "yes" to every install question (no prompts)
#   ./setup.sh --no-build   skip the (slow) image build at the end
#
# Windows users: run setup.ps1 instead.

set -u
cd "$(dirname "$0")"

ASSUME_YES=0
DO_BUILD=1
for arg in "$@"; do
  case "$arg" in
    -y|--yes) ASSUME_YES=1 ;;
    --no-build) DO_BUILD=0 ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg (try --help)"; exit 2 ;;
  esac
done

# ---- tiny helpers for readable output ---------------------------------------
if [ -t 1 ]; then G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; B=$'\033[1m'; N=$'\033[0m'; else G=""; Y=""; R=""; B=""; N=""; fi
ok()   { echo "${G}[ok]${N}   $*"; }
warn() { echo "${Y}[warn]${N} $*"; }
fail() { echo "${R}[fail]${N} $*"; }
step() { echo; echo "${B}$*${N}"; }
ask() { # ask "question" -> returns 0 for yes
  [ "$ASSUME_YES" -eq 1 ] && return 0
  [ -t 0 ] || return 1
  read -r -p "$1 [y/N] " reply
  case "$reply" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}
have() { command -v "$1" >/dev/null 2>&1; }

OS="$(uname -s)"
echo "${B}Internship Agent: setup check${N}  (detected: $OS)"

# ---- 1. Is Docker installed? --------------------------------------------------
step "1/5  Checking that Docker is installed"
if have docker; then
  ok "Docker found: $(docker --version 2>/dev/null)"
else
  warn "Docker is not installed."
  case "$OS" in
    Darwin)
      if have brew && ask "Install Docker Desktop with Homebrew now?"; then
        brew install --cask docker || { fail "Homebrew install failed."; exit 1; }
        ok "Docker Desktop installed."
      else
        fail "Install Docker Desktop from https://www.docker.com/products/docker-desktop/ then run ./setup.sh again."
        exit 1
      fi ;;
    Linux)
      if ask "Install Docker Engine with the official script (needs sudo)?"; then
        have curl || { fail "curl is required to download the installer."; exit 1; }
        curl -fsSL https://get.docker.com | sudo sh || { fail "Docker install failed."; exit 1; }
        sudo usermod -aG docker "$USER" 2>/dev/null && \
          warn "Added you to the 'docker' group. Log out and back in (or run: newgrp docker), then run ./setup.sh again."
        have docker || exit 1
      else
        fail "Install Docker from https://docs.docker.com/engine/install/ then run ./setup.sh again."
        exit 1
      fi ;;
    *)
      fail "Unsupported system for this script. On Windows, run setup.ps1 instead."
      exit 1 ;;
  esac
fi

# ---- 2. Is the Docker engine running? ------------------------------------------
step "2/5  Checking that Docker is running"
if docker info >/dev/null 2>&1; then
  ok "Docker engine is running."
else
  if [ "$OS" = "Darwin" ]; then
    warn "Docker Desktop is not running. Starting it..."
    open -a Docker 2>/dev/null || { fail "Could not open Docker Desktop. Start it from Applications, then run ./setup.sh again."; exit 1; }
    printf "Waiting for Docker to start (up to 2 minutes)"
    for _ in $(seq 1 60); do
      docker info >/dev/null 2>&1 && break
      printf "."; sleep 2
    done
    echo
    docker info >/dev/null 2>&1 || { fail "Docker did not start in time. Open Docker Desktop, wait for it to say 'running', then run ./setup.sh again."; exit 1; }
    ok "Docker engine is running."
  else
    if docker info 2>&1 | grep -qi "permission denied"; then
      fail "Docker is running but your user is not allowed to use it."
      echo "      Fix: sudo usermod -aG docker \$USER   then log out and back in."
    else
      fail "Docker is installed but not running."
      echo "      Fix: sudo systemctl start docker"
    fi
    exit 1
  fi
fi

# ---- 3. Docker Compose v2 -------------------------------------------------------
step "3/5  Checking Docker Compose"
if docker compose version >/dev/null 2>&1; then
  ok "Docker Compose found: $(docker compose version --short 2>/dev/null)"
else
  fail "'docker compose' (v2) is missing. Update Docker Desktop, or on Linux install the 'docker-compose-plugin' package."
  exit 1
fi

# ---- 4. .env file ---------------------------------------------------------------
step "4/5  Checking the .env settings file"
if [ -f .env ]; then
  ok ".env already exists (leaving it alone)."
else
  cp .env.example .env && ok "Created .env from .env.example (works as-is in mock mode, no keys needed)."
fi
if grep -Eq '^OPENAI_API_KEY=.+' .env; then
  ok "OPENAI_API_KEY is set: the agent will use the LLM."
else
  warn "No OPENAI_API_KEY in .env: the agent will run in mock/keyword mode (that is fine for a first run)."
fi

# ---- 5. Port 8000 + build ---------------------------------------------------------
step "5/5  Checking port 8000 and building the image"
if docker compose ps --status running --services 2>/dev/null | grep -qx api; then
  ok "The API is already running from this project."
elif have lsof && lsof -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
  warn "Port 8000 is used by another program. Stop it, or change \"8000:8000\" in docker-compose.yml (e.g. \"8001:8000\")."
else
  ok "Port 8000 is free."
fi

if [ "$DO_BUILD" -eq 1 ]; then
  echo "Building the image (first time takes a few minutes)..."
  if docker compose build; then
    ok "Image built."
  else
    fail "Build failed. Check your internet connection and the error above."
    exit 1
  fi
else
  warn "Skipped the build (--no-build). It will build on first 'docker compose up --build'."
fi

echo
echo "${G}${B}You are ready.${N} Run these two commands in two separate terminals:"
echo
echo "  ${B}Terminal 1:${N}  docker compose up"
echo "  ${B}Terminal 2:${N}  docker compose run --rm tui"
echo
echo "Then press 'r' in the UI. API docs: http://localhost:8000/docs"
