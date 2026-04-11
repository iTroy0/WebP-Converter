#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ── Colours ──
CYAN='\033[1;36m'
GREEN='\033[1;32m'
RED='\033[1;31m'
YELLOW='\033[1;33m'
DIM='\033[2m'
RESET='\033[0m'

menu() {
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
  echo -e "${CYAN}  ║           WebP  →  Video  Converter  v2.0           ║${RESET}"
  echo -e "${CYAN}  ║                                                      ║${RESET}"
  echo -e "${CYAN}  ╠══════════════════════════════════════════════════════╣${RESET}"
  echo -e "${CYAN}  ║                                                      ║${RESET}"
  echo -e "${CYAN}  ║   [1]  ▶  Run Application                           ║${RESET}"
  echo -e "${CYAN}  ║   [2]  ⚙  Build Standalone Binary                   ║${RESET}"
  echo -e "${CYAN}  ║   [3]  ✕  Exit                                       ║${RESET}"
  echo -e "${CYAN}  ║                                                      ║${RESET}"
  echo -e "${CYAN}  ╚══════════════════════════════════════════════════════╝${RESET}"
  echo ""
  read -rp "   Enter choice (1/2/3): " choice

  case "$choice" in
    1) run_app ;;
    2) build_app ;;
    3) exit_app ;;
    *) menu ;;
  esac
}

# ─────────────────────────────────────────
run_app() {
  clear
  echo ""
  echo -e "${CYAN}  ╔══════════════════════════════════════════════════════╗${RESET}"
  echo -e "${CYAN}  ║   ▶  LAUNCHING APPLICATION                          ║${RESET}"
  echo -e "${CYAN}  ╚══════════════════════════════════════════════════════╝${RESET}"
  echo ""

  echo "  [1/2]  Syncing dependencies..."
  pip install --upgrade pip > /dev/null 2>&1 || true
  pip install -r requirements.txt > /dev/null 2>&1
  echo "         Done."
  echo ""

  echo "  [2/2]  Starting WebP Converter..."
  echo ""
  python3 webp_converter_gui.py || python webp_converter_gui.py

  echo ""
  echo "  ─────────────────────────────────────────────────────"
  echo "   Application closed. Press any key to return to menu."
  echo "  ─────────────────────────────────────────────────────"
  read -rsn1
  menu
}

# ─────────────────────────────────────────
build_app() {
  clear
  echo ""
  echo -e "${CYAN}  ╔══════════════════════════════════════════════════════╗${RESET}"
  echo -e "${CYAN}  ║   ⚙  BUILDING STANDALONE BINARY                     ║${RESET}"
  echo -e "${CYAN}  ╚══════════════════════════════════════════════════════╝${RESET}"
  echo ""

  echo "  [1/4]  Syncing dependencies..."
  pip install --upgrade pip > /dev/null 2>&1 || true
  pip install -r requirements.txt > /dev/null 2>&1
  pip install pyinstaller > /dev/null 2>&1
  echo "         Done."
  echo ""

  echo "  [2/4]  Removing previous build artifacts..."
  rm -rf build dist *.spec 2>/dev/null || true
  echo "         Done."
  echo ""

  echo "  [3/4]  Compiling — this may take a minute..."
  echo ""

  # Determine add-data separator (: on Linux/macOS, ; on Windows/MSYS)
  SEP=":"
  if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" ]]; then
    SEP=";"
  fi

  pyinstaller --noconsole --onefile --clean \
    --name "WebP Converter" \
    --add-data "app_icon.ico${SEP}." \
    --hidden-import=imageio_ffmpeg \
    --collect-data=customtkinter \
    --collect-data=imageio_ffmpeg \
    webp_converter_gui.py

  echo ""
  echo "  [4/4]  Cleaning up build files..."
  rm -rf build *.spec 2>/dev/null || true
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

  echo ""
  echo "  ─────────────────────────────────────────────────────"
  echo "   Press any key to return to menu."
  echo "  ─────────────────────────────────────────────────────"
  read -rsn1
  menu
}

# ─────────────────────────────────────────
exit_app() {
  clear
  echo ""
  echo -e "${CYAN}  ╔══════════════════════════════════════════════════════╗${RESET}"
  echo -e "${CYAN}  ║   Goodbye!                                          ║${RESET}"
  echo -e "${CYAN}  ╚══════════════════════════════════════════════════════╝${RESET}"
  echo ""
  sleep 1
  exit 0
}

menu
