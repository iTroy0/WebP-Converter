#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

# ── Colours ──
CYAN='\033[1;36m'
GREEN='\033[1;32m'
RED='\033[1;31m'
YELLOW='\033[1;33m'
DIM='\033[2m'
RESET='\033[0m'

PIPLOG="${TMPDIR:-/tmp}/webp_converter_pip.log"

# ── Locate Python ──
PYBIN="$(command -v python3 || command -v python || true)"
if [ -z "$PYBIN" ]; then
  echo -e "${RED}  [ERROR] Python 3 not found on PATH.${RESET}"
  echo "          Install it via your package manager or https://www.python.org/downloads/"
  exit 1
fi

banner() {
  clear
  echo ""
  echo -e "${CYAN}  ╔══════════════════════════════════════════════════════╗${RESET}"
  echo -e "${CYAN}  ║                                                      ║${RESET}"
  echo -e "${CYAN}  ║        ░██╗░░░░░░░██╗███████╗██████╗░██████╗░        ║${RESET}"
  echo -e "${CYAN}  ║        ░██║░░██╗░░██║██╔════╝██╔══██╗██╔══██╗        ║${RESET}"
  echo -e "${CYAN}  ║        ░╚██╗████╗██╔╝█████╗░░██████╦╝██████╔╝        ║${RESET}"
  echo -e "${CYAN}  ║        ░░████╔═████║░██╔══╝░░██╔══██╗██╔═══╝░        ║${RESET}"
  echo -e "${CYAN}  ║        ░░╚██╔╝░╚██╔╝░███████╗██████╦╝██║░░░░░        ║${RESET}"
  echo -e "${CYAN}  ║        ░░░╚═╝░░░╚═╝░░╚══════╝╚═════╝░╚═╝░░░░░        ║${RESET}"
  echo -e "${CYAN}  ║                                                      ║${RESET}"
  echo -e "${CYAN}  ║           WebP  →  Video  Converter  v2.2           ║${RESET}"
  echo -e "${CYAN}  ║                                                      ║${RESET}"
  echo -e "${CYAN}  ╠══════════════════════════════════════════════════════╣${RESET}"
  echo -e "${CYAN}  ║                                                      ║${RESET}"
  echo -e "${CYAN}  ║   [1]  ▶  Run Application                           ║${RESET}"
  echo -e "${CYAN}  ║   [2]  ⚙  Build Standalone Binary                   ║${RESET}"
  echo -e "${CYAN}  ║   [3]  ✕  Exit                                       ║${RESET}"
  echo -e "${CYAN}  ║                                                      ║${RESET}"
  echo -e "${CYAN}  ╚══════════════════════════════════════════════════════╝${RESET}"
  echo ""
}

install_deps() {
  echo "  Syncing dependencies..."
  if ! "$PYBIN" -m pip install -r requirements.txt >"$PIPLOG" 2>&1; then
    echo -e "${RED}  [ERROR] Dependency install failed:${RESET}"
    echo "  ─────────────────────────────────────────────────────"
    cat "$PIPLOG"
    echo "  ─────────────────────────────────────────────────────"
    return 1
  fi
  echo "         Done."
  return 0
}

pause_key() {
  echo ""
  echo "  ─────────────────────────────────────────────────────"
  echo "   Press any key to return to menu."
  echo "  ─────────────────────────────────────────────────────"
  read -rsn1
}

run_app() {
  clear
  echo ""
  echo -e "${CYAN}  ╔══════════════════════════════════════════════════════╗${RESET}"
  echo -e "${CYAN}  ║   ▶  LAUNCHING APPLICATION                          ║${RESET}"
  echo -e "${CYAN}  ╚══════════════════════════════════════════════════════╝${RESET}"
  echo ""
  echo "  [1/2]"
  install_deps || { pause_key; return; }
  echo ""
  echo "  [2/2]  Starting WebP Converter..."
  echo ""
  "$PYBIN" webp_converter_gui.py
  rc=$?
  if [ $rc -ne 0 ]; then
    echo ""
    echo -e "${YELLOW}  [WARN] Application exited with code $rc.${RESET}"
  fi
  pause_key
}

build_app() {
  clear
  echo ""
  echo -e "${CYAN}  ╔══════════════════════════════════════════════════════╗${RESET}"
  echo -e "${CYAN}  ║   ⚙  BUILDING STANDALONE BINARY                     ║${RESET}"
  echo -e "${CYAN}  ╚══════════════════════════════════════════════════════╝${RESET}"
  echo ""
  echo "  [1/4]"
  install_deps || { pause_key; return; }
  if ! "$PYBIN" -m pip install pyinstaller >>"$PIPLOG" 2>&1; then
    echo -e "${RED}  [ERROR] PyInstaller install failed:${RESET}"
    cat "$PIPLOG"
    pause_key
    return
  fi
  echo ""

  echo "  [2/4]  Removing previous build artifacts..."
  rm -rf build dist ./*.spec 2>/dev/null
  echo "         Done."
  echo ""

  echo "  [3/4]  Compiling — this may take a minute..."
  echo ""

  # Determine add-data separator (: on Linux/macOS, ; on Windows/MSYS)
  SEP=":"
  if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" ]]; then
    SEP=";"
  fi

  "$PYBIN" -m PyInstaller --noconsole --onefile --clean \
    --name "WebP Converter" \
    --add-data "app_icon.ico${SEP}." \
    --hidden-import=imageio_ffmpeg \
    --collect-data=customtkinter \
    --collect-data=imageio_ffmpeg \
    --collect-data=tkinterdnd2 \
    --collect-binaries=tkinterdnd2 \
    webp_converter_gui.py

  echo ""
  echo "  [4/4]  Cleaning up build files..."
  rm -rf build ./*.spec 2>/dev/null
  echo "         Done."
  echo ""

  if [ -f "dist/WebP Converter" ] || [ -f "dist/WebP Converter.exe" ]; then
    echo -e "${GREEN}  ╔══════════════════════════════════════════════════════╗${RESET}"
    echo -e "${GREEN}  ║   ✔  BUILD SUCCESSFUL                               ║${RESET}"
    echo -e "${GREEN}  ║      Binary is in the dist/ folder                   ║${RESET}"
    echo -e "${GREEN}  ╚══════════════════════════════════════════════════════╝${RESET}"
  else
    echo -e "${RED}  ╔══════════════════════════════════════════════════════╗${RESET}"
    echo -e "${RED}  ║   ✖  BUILD FAILED — check output above              ║${RESET}"
    echo -e "${RED}  ╚══════════════════════════════════════════════════════╝${RESET}"
  fi
  pause_key
}

while true; do
  banner
  read -rp "   Enter choice (1/2/3): " choice
  case "$choice" in
    1) run_app ;;
    2) build_app ;;
    3)
      clear
      echo ""
      echo -e "${CYAN}  Goodbye!${RESET}"
      echo ""
      exit 0
      ;;
    *) ;;
  esac
done
