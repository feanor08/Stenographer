#!/usr/bin/env bash
set -euo pipefail

PYTHON_CMD=""

is_python3_command() {
  local candidate="$1"
  if ! command -v "$candidate" >/dev/null 2>&1; then
    return 1
  fi

  "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info.major == 3 else 1)' >/dev/null 2>&1
}

set_python_cmd() {
  if is_python3_command python3; then
    PYTHON_CMD="python3"
    return 0
  fi

  if is_python3_command python; then
    PYTHON_CMD="python"
    return 0
  fi

  return 1
}

run_as_root() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
    return
  fi

  if command -v sudo >/dev/null 2>&1; then
    sudo "$@"
    return
  fi

  echo "Need root privileges to install Python, but sudo is not available."
  return 1
}

enable_homebrew_path() {
  local brew_bin=""

  if command -v brew >/dev/null 2>&1; then
    brew_bin="$(command -v brew)"
  elif [ -x /opt/homebrew/bin/brew ]; then
    brew_bin="/opt/homebrew/bin/brew"
  elif [ -x /usr/local/bin/brew ]; then
    brew_bin="/usr/local/bin/brew"
  fi

  if [ -n "$brew_bin" ]; then
    eval "$("$brew_bin" shellenv)"
  fi
}

install_python_macos() {
  enable_homebrew_path

  if ! command -v brew >/dev/null 2>&1; then
    echo "python3 not found."
    echo "On macOS this script can auto-install Python only when Homebrew is already installed."
    echo "Install Homebrew from https://brew.sh and then rerun ./install."
    return 1
  fi

  echo "python3 not found. Installing Python with Homebrew ..."
  brew install python
  enable_homebrew_path
}

install_python_linux() {
  echo "python3 not found. Installing Python with the system package manager ..."

  if command -v apt-get >/dev/null 2>&1; then
    run_as_root apt-get update
    run_as_root apt-get install -y python3 python3-venv python3-pip
    return
  fi

  if command -v dnf >/dev/null 2>&1; then
    run_as_root dnf install -y python3 python3-pip
    return
  fi

  if command -v yum >/dev/null 2>&1; then
    run_as_root yum install -y python3 python3-pip
    return
  fi

  if command -v pacman >/dev/null 2>&1; then
    run_as_root pacman -Sy --noconfirm python python-pip
    return
  fi

  echo "Unsupported Linux package manager."
  echo "Install Python 3 manually and rerun ./install."
  return 1
}

ensure_python3() {
  if set_python_cmd; then
    return 0
  fi

  case "$(uname -s)" in
    Darwin)
      install_python_macos
      ;;
    Linux)
      install_python_linux
      ;;
    *)
      echo "Unsupported OS. Please install Python 3 manually."
      return 1
      ;;
  esac

  if set_python_cmd; then
    return 0
  fi

  echo "Python 3 still could not be found after the install attempt."
  return 1
}
