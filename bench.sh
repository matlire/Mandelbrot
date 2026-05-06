#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ -z "${IN_NIX_SHELL:-}" ]]; then
  exec nix develop -c "$SCRIPT_DIR/bench.sh" "$@"
fi

require_tool() {
  local tool="$1"
  command -v "$tool" >/dev/null 2>&1 || {
    echo "missing required tool: $tool" >&2
    exit 1
  }
}

require_tool python3
require_tool sudo
require_tool taskset
require_tool turbostat
require_tool cpupower

SUDO_KEEPALIVE_PID=""
CPUPOWER_BIN="$(command -v cpupower)"
CPUPOWER_STATE_CAPTURED=0
CPUPOWER_PLAN_ACTIVE=0
BENCH_ORIG_MIN_KHZ=""
BENCH_ORIG_MAX_KHZ=""
BENCH_ORIG_GOVERNOR=""

: "${BENCH_GOVERNOR:=performance}"
export BENCH_GOVERNOR

capture_cpupower_state() {
  local limits_line

  limits_line="$("$CPUPOWER_BIN" frequency-info -l | tail -n 1)"
  read -r BENCH_ORIG_MIN_KHZ BENCH_ORIG_MAX_KHZ <<<"$limits_line"
  BENCH_ORIG_GOVERNOR="$("$CPUPOWER_BIN" frequency-info -p | sed -n 's/.*The governor "\([^"]*\)".*/\1/p' | tail -n 1)"
  CPUPOWER_STATE_CAPTURED=1
}

apply_cpupower_plan() {
  local min_freq="${BENCH_MIN_FREQ:-}"
  local max_freq="${BENCH_MAX_FREQ:-}"

  if [[ -n "${BENCH_FREQUENCY:-}" ]]; then
    min_freq="$BENCH_FREQUENCY"
    max_freq="$BENCH_FREQUENCY"
  fi

  if [[ -n "$min_freq" || -n "$max_freq" ]]; then
    local -a freq_args=()
    [[ -n "$min_freq" ]] && freq_args+=(-d "$min_freq")
    [[ -n "$max_freq" ]] && freq_args+=(-u "$max_freq")
    sudo -n "$CPUPOWER_BIN" frequency-set "${freq_args[@]}"
  fi

  sudo -n "$CPUPOWER_BIN" frequency-set -g "$BENCH_GOVERNOR"
}

restore_cpupower_plan() {
  if [[ "$CPUPOWER_STATE_CAPTURED" -ne 1 || "$CPUPOWER_PLAN_ACTIVE" -ne 1 ]]; then
    return
  fi

  if [[ -n "$BENCH_ORIG_MIN_KHZ" && -n "$BENCH_ORIG_MAX_KHZ" ]]; then
    sudo -n "$CPUPOWER_BIN" frequency-set -d "$BENCH_ORIG_MIN_KHZ" -u "$BENCH_ORIG_MAX_KHZ" || true
  fi
  if [[ -n "$BENCH_ORIG_GOVERNOR" ]]; then
    sudo -n "$CPUPOWER_BIN" frequency-set -g "$BENCH_ORIG_GOVERNOR" || true
  fi
  CPUPOWER_PLAN_ACTIVE=0
}

cleanup() {
  if [[ "${BENCH_SKIP_CPUPOWER:-0}" != "1" ]]; then
    restore_cpupower_plan
  fi
  if [[ -n "$SUDO_KEEPALIVE_PID" ]]; then
    kill "$SUDO_KEEPALIVE_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

sudo -v
(
  while true; do
    sudo -n true
    sleep 50
  done
) >/dev/null 2>&1 &
SUDO_KEEPALIVE_PID="$!"

if [[ "${BENCH_SKIP_CPUPOWER:-0}" != "1" ]]; then
  capture_cpupower_state
  apply_cpupower_plan
  CPUPOWER_PLAN_ACTIVE=1
fi

PYTHONUNBUFFERED=1 python3 "$SCRIPT_DIR/benchmark.py" --suite cpu
restore_cpupower_plan
PYTHONUNBUFFERED=1 python3 "$SCRIPT_DIR/benchmark.py" --suite present
PYTHONUNBUFFERED=1 python3 "$SCRIPT_DIR/benchmark.py" --suite gpu
PYTHONUNBUFFERED=1 python3 "$SCRIPT_DIR/plot.py"
