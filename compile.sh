#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: ./compile.sh -f|--file <renderer.c|all> [--interactive|--bench] [-O1|-O2|-O3]

Examples:
  ./compile.sh --interactive -f src/render_floats_no-sse_no-threads_no-acel.c -O3
  ./compile.sh --bench -f all -O3
USAGE
  exit 1
}

SOURCE=""
OPT_LEVEL=""
BENCH_MODE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    -f|--file)
      [[ $# -ge 2 ]] || usage
      SOURCE="$2"
      shift 2
      ;;
    -O1|-O2|-O3)
      OPT_LEVEL="$1"
      shift
      ;;
    --bench)
      BENCH_MODE=1
      shift
      ;;
    --interactive)
      BENCH_MODE=0
      shift
      ;;
    -h|--help)
      usage
      ;;
    *)
      echo "Unknown argument: $1"
      usage
      ;;
  esac
done

[[ -n "$SOURCE" ]] || usage

if [[ "$SOURCE" == "all" ]]; then
  mapfile -t SOURCES < <(find src -maxdepth 1 -type f -name 'render_*.c' ! -name '*_common.c' | sort)
  [[ "${#SOURCES[@]}" -gt 0 ]] || { echo "No renderer sources found in src"; exit 1; }
else
  [[ -f "$SOURCE" ]] || { echo "File not found: $SOURCE"; exit 1; }
  SOURCES=("$SOURCE")
fi

MAIN_SOURCE="main.c"
if [[ "$BENCH_MODE" -eq 1 ]]; then
  MAIN_SOURCE="bench.c"
fi

[[ -f "$MAIN_SOURCE" ]] || { echo "$MAIN_SOURCE not found in project root"; exit 1; }

mkdir -p build dist dist/bench

MAIN_OBJ="build/$(basename "${MAIN_SOURCE%.*}").o"
UTILS_SOURCE="src/utils/utils.c"
UTILS_OBJ="build/utils.o"
BENCH_COMMON_OBJ=""

BASE_CFLAGS=(-std=c11 -Wall -Wextra -I. -I./src -I./src/utils)
LDFLAGS=(-lraylib -lGL -lm -pthread -ldl -lrt -lX11)

if command -v pkg-config >/dev/null 2>&1 && pkg-config --exists raylib; then
  read -r -a RAYLIB_CFLAGS <<< "$(pkg-config --cflags raylib)"
  read -r -a RAYLIB_LIBS   <<< "$(pkg-config --libs raylib)"
  BASE_CFLAGS+=("${RAYLIB_CFLAGS[@]}")
  LDFLAGS=("${RAYLIB_LIBS[@]}" -lm -pthread -ldl -lrt)
fi

if [[ -n "$OPT_LEVEL" ]]; then
  BASE_CFLAGS+=("$OPT_LEVEL")
fi

compile_object() {
  local source_file="$1"
  local object_file="$2"
  shift 2
  local -a extra_cflags=("$@")
  gcc "${BASE_CFLAGS[@]}" "${extra_cflags[@]}" -c "$source_file" -o "$object_file"
}

build_source() {
  local source_file="$1"
  local filename name render_obj bin mode_label support_source support_filename support_obj
  local -a cflags=() support_sources=() support_objs=() support_cflags=() link_objs=()

  filename="$(basename "$source_file")"
  name="${filename%.*}"
  render_obj="build/${name}.o"
  if [[ "$BENCH_MODE" -eq 1 ]]; then
    bin="dist/bench/${name}"
  else
    bin="dist/${name}"
  fi

  cflags=()
  case "$filename" in
    render_floats_no-sse_no-threads_no-acel.c)
      support_sources+=("src/render_floats_scalar_common.c")
      ;;
    render_floats_arrays_no-threads_no-acel.c)
      support_sources+=("src/render_floats_scalar_common.c")
      ;;
    render_floats_sse_no-threads_no-acel.c)
      support_sources+=("src/render_floats_scalar_common.c" "src/render_floats_sse_common.c")
      ;;
    render_floats_sse_threads_no-acel.c)
      support_sources+=("src/render_floats_scalar_common.c" "src/render_floats_sse_common.c")
      ;;
    render_floats_sse_threads_acel.c)
      ;;
  esac

  mode_label="CPU"
  if [[ "$filename" == *_acel.c ]]; then
    mode_label="GPU"
  fi

  compile_object "$source_file" "$render_obj" "${cflags[@]}"
  for support_source in "${support_sources[@]}"; do
    [[ -f "$support_source" ]] || { echo "Support source not found: $support_source"; exit 1; }
    support_filename="$(basename "$support_source")"
    support_obj="build/${support_filename%.*}.o"
    support_cflags=()
    if [[ "$support_filename" == render_floats_sse_* ]]; then
      support_cflags+=(-mavx2 -mfma)
    fi
    compile_object "$support_source" "$support_obj" "${support_cflags[@]}"
    support_objs+=("$support_obj")
  done

  link_objs=("$MAIN_OBJ" "$render_obj" "${support_objs[@]}" "$UTILS_OBJ")
  if [[ -n "$BENCH_COMMON_OBJ" ]]; then
    link_objs+=("$BENCH_COMMON_OBJ")
  fi

  gcc "${link_objs[@]}" -o "$bin" "${LDFLAGS[@]}"

  echo "Built object: $MAIN_OBJ"
  echo "Built object: $render_obj"
  for support_obj in "${support_objs[@]}"; do
    echo "Built object: $support_obj"
  done
  echo "Built object: $UTILS_OBJ"
  if [[ -n "$BENCH_COMMON_OBJ" ]]; then
    echo "Built object: $BENCH_COMMON_OBJ"
  fi
  echo "Built binary: $bin"
  [[ -n "$OPT_LEVEL" ]] && echo "Optimization: $OPT_LEVEL" || echo "Optimization: none"
  if [[ "$BENCH_MODE" -eq 1 ]]; then
    echo "Entry: benchmark"
  else
    echo "Entry: interactive"
  fi
  echo "Mode: $mode_label"
}

compile_object "$MAIN_SOURCE" "$MAIN_OBJ"
compile_object "$UTILS_SOURCE" "$UTILS_OBJ"
if [[ "$BENCH_MODE" -eq 1 ]]; then
  BENCH_COMMON_OBJ="build/bench_common.o"
  compile_object "src/bench/bench_common.c" "$BENCH_COMMON_OBJ"
fi

for source_file in "${SOURCES[@]}"; do
  build_source "$source_file"
done
