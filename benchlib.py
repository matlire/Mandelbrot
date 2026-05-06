#!/usr/bin/env python3
from __future__ import annotations

import csv
import math
import os
import re
import signal
import shutil
import statistics
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parent
REPORT_DIR   = PROJECT_ROOT / "report"
DATA_DIR     = REPORT_DIR   / "data"
RAW_DIR      = DATA_DIR     / "raw"
PRESENT_DIR  = DATA_DIR     / "present"

@dataclass(frozen=True)
class Variant:
    label:    str
    source:   str
    threaded: bool

VARIANTS = [
    Variant("naive", "src/render_floats_no-sse_no-threads_no-acel.c",  False),
    Variant("arrays", "src/render_floats_arrays_no-threads_no-acel.c", False),
    Variant("simd", "src/render_floats_sse_no-threads_no-acel.c",      False),
    Variant("simd_threads", "src/render_floats_sse_threads_no-acel.c", True),
]
GPU_VARIANT   = Variant("gpu", "src/render_floats_sse_threads_acel.c", False)
VARIANT_INDEX = {variant.label: index for index, variant in enumerate(VARIANTS)}

DEFAULT_OPT_LEVELS = ("-O1", "-O2", "-O3")
DEFAULT_SCENE = {
    "center_x": "-0.743643887037151",
    "center_y": "0.131825904205330",
    "zoom": "180.0",
}

THROTTLE_FIELDS = (
    "core_throttle_count",
    "package_throttle_count",
)

TURBOSTAT_COLUMNS = (
    "Core",
    "CPU",
    "Avg_MHz",
    "Busy%",
    "Bzy_MHz",
    "TSC_MHz",
    "CoreTmp",
    "PkgTmp",
    "CoreThr",
)

def parse_cpu_list(cpu_list: str) -> list[int]:
    cpus: list[int] = []
    for chunk in cpu_list.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            start_text, end_text = chunk.split("-", 1)
            start = int(start_text)
            end = int(end_text)
            step = 1 if end >= start else -1
            cpus.extend(range(start, end + step, step))
        else:
            cpus.append(int(chunk))
    return sorted(set(cpus))

def format_cpu_list(cpus: Iterable[int]) -> str:
    ordered = sorted(set(cpus))
    if not ordered:
        return ""

    ranges: list[str] = []
    start = prev = ordered[0]
    for cpu in ordered[1:]:
        if cpu == prev + 1:
            prev = cpu
            continue
        ranges.append(f"{start}-{prev}" if start != prev else str(start))
        start = prev = cpu
    ranges.append(f"{start}-{prev}" if start != prev else str(start))
    return ",".join(ranges)

def detect_online_cpus() -> list[int]:
    return sorted(os.sched_getaffinity(0))

def parse_opt_levels() -> list[str]:
    raw = os.environ.get("OPT_LEVELS", ",".join(DEFAULT_OPT_LEVELS))
    levels = [part.strip() for part in raw.split(",") if part.strip()]
    return levels or list(DEFAULT_OPT_LEVELS)

def scalar_stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {
            "mean":   0.0,
            "stdev":  0.0,
            "median": 0.0,
            "p95": 0.0,
            "min": 0.0,
            "max": 0.0,
        }

    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(0.95 * len(ordered)) - 1))
    return {
        "mean": statistics.fmean(values),
        "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
        "median": statistics.median(ordered),
        "p95": ordered[index],
        "min": ordered[0],
        "max": ordered[-1],
    }

def ensure_clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)

def run_command(cmd: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

@contextmanager
def display_environment() -> dict[str, str]:
    env = os.environ.copy()
    use_xvfb = env.get("PRESENT_USE_XVFB", "1") != "0"
    xvfb_proc: subprocess.Popen[str] | None = None

    if use_xvfb and shutil.which("Xvfb") is not None:
        display = env.get("PRESENT_XVFB_DISPLAY", ":99")
        xvfb_cmd = [
            shutil.which("Xvfb") or "Xvfb",
            display,
            "-screen",
            "0",
            "1280x720x24",
            "-nolisten",
            "tcp",
        ]
        xvfb_proc = subprocess.Popen(
            xvfb_cmd,
            cwd=PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        time.sleep(1.0)
        env["DISPLAY"] = display
    elif "DISPLAY" not in env or not env["DISPLAY"]:
        raise RuntimeError("No DISPLAY available and Xvfb is not enabled")

    try:
        yield env
    finally:
        if xvfb_proc is not None:
            xvfb_proc.send_signal(signal.SIGTERM)
            try:
                xvfb_proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                xvfb_proc.kill()
                xvfb_proc.wait(timeout=5.0)

def compile_variant(variant: Variant, opt_level: str, mode: str) -> None:
    cmd = ["./compile.sh", mode, "-f", variant.source, opt_level]
    completed = run_command(cmd)
    sys.stdout.write(completed.stdout)
    sys.stderr.write(completed.stderr)
    if completed.returncode != 0:
        raise RuntimeError(f"compile failed for {variant.label} {opt_level} ({mode})")

def parse_summary(stdout: str) -> dict[str, str]:
    summary: dict[str, str] = {}
    for line in stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        summary[key.strip()] = value.strip()
    return summary

def bench_binary_path(source: str) -> Path:
    return PROJECT_ROOT / "dist" / "bench" / Path(source).stem

def benchmark_binary_path(source: str) -> Path:
    return bench_binary_path(source)

def build_bench_command(source:      str,
                        bench_kind:  str,
                        frames_path: Path,
                        frames:      int,
                        warmup:      int,
                        center_x:    str,
                        center_y:    str,
                        zoom: str) -> list[str]:
    return [
        str(bench_binary_path(source)),
        "--bench",
        bench_kind,
        "--out",
        str(frames_path),
        "--frames",
        str(frames),
        "--warmup",
        str(warmup),
        "--center-x",
        center_x,
        "--center-y",
        center_y,
        "--zoom",
        zoom,
    ]

def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None

def read_frames(path: Path) -> tuple[list[float], list[float]]:
    ticks: list[float] = []
    ns: list[float] = []

    with path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            ticks.append(float(row["ticks"]))
            ns.append(float(row["ns"]))

    return ticks, ns

def parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    text = value.strip()
    if not text or text == "-":
        return None
    try:
        return float(text)
    except ValueError:
        return None

def parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    text = value.strip()
    if not text or text == "-":
        return None
    try:
        return int(text)
    except ValueError:
        return None

def cpupower_snapshot() -> dict[str, str]:
    policy = run_command(["cpupower", "frequency-info", "-p"])
    limits = run_command(["cpupower", "frequency-info", "-l"])
    governors = run_command(["cpupower", "frequency-info", "-g"])

    governor_match = re.search(r'The governor "([^"]+)"', policy.stdout)

    return {
        "policy": policy.stdout.strip(),
        "hwlimits": limits.stdout.strip(),
        "available_governors": governors.stdout.strip(),
        "current_governor": governor_match.group(1) if governor_match else "",
    }

def sudo_prefix(binary_path: str) -> list[str]:
    sudo_bin = shutil.which("sudo")
    if sudo_bin is None:
        raise RuntimeError("sudo is required for turbostat")
    return [sudo_bin, "-n", binary_path]

def parse_turbostat_samples(raw_text: str, cpus: list[int], sample_interval: float) -> list[dict[str, float | int | None]]:
    cpu_set = set(cpus)
    header: list[str] | None = None
    block_rows: list[dict[str, str]] = []
    samples: list[dict[str, float | int | None]] = []

    def flush_block() -> None:
        if header is None or not block_rows:
            return

        summary_row: dict[str, str] | None = None
        cpu_rows: list[dict[str, str]] = []
        for row in block_rows:
            cpu_text = row.get("CPU", "")
            if cpu_text == "-":
                summary_row = row
                continue
            cpu_id = parse_int(cpu_text)
            if cpu_id is not None and cpu_id in cpu_set:
                cpu_rows.append(row)

        if not cpu_rows:
            return

        def collect(column: str) -> list[float]:
            values: list[float] = []
            for row in cpu_rows:
                value = parse_float(row.get(column))
                if value is not None:
                    values.append(value)
            return values

        avg_freq = collect("Avg_MHz")
        if not avg_freq:
            avg_freq = collect("TSC_MHz")
        busy_values = collect("Busy%")
        bzy_values = collect("Bzy_MHz")
        tsc_values = collect("TSC_MHz")

        temp_values = collect("PkgTmp")
        if not temp_values:
            temp_values = collect("CoreTmp")
        if not temp_values and summary_row is not None:
            summary_temp = parse_float(summary_row.get("PkgTmp")) or parse_float(summary_row.get("CoreTmp"))
            if summary_temp is not None:
                temp_values = [summary_temp]

        core_throttle = sum(parse_int(row.get("CoreThr")) or 0 for row in cpu_rows)

        samples.append({
            "elapsed_s": (len(samples) + 1) * sample_interval,
            "freq_mhz": statistics.fmean(avg_freq) if avg_freq else None,
            "busy_pct": statistics.fmean(busy_values) if busy_values else None,
            "bzy_mhz": statistics.fmean(bzy_values) if bzy_values else None,
            "tsc_mhz": statistics.fmean(tsc_values) if tsc_values else None,
            "temp_c": statistics.fmean(temp_values) if temp_values else None,
            "core_throttle_count": core_throttle,
            "package_throttle_count": 0,
            "sampled_cpu_count": len(cpu_rows),
        })

    for raw_line in raw_text.splitlines():
        line = raw_line.strip("\n")
        if not line or "\t" not in line:
            continue

        parts = [part.strip() for part in line.split("\t")]
        if "CPU" in parts:
            flush_block()
            header = parts
            block_rows = []
            continue
        if header is None:
            continue

        if len(parts) < len(header):
            parts += [""] * (len(header) - len(parts))
        block_rows.append(dict(zip(header, parts)))

    flush_block()
    return samples

def write_samples(path: Path, samples: list[dict[str, float | int | None]]) -> None:
    fieldnames = [
        "elapsed_s",
        "freq_mhz",
        "busy_pct",
        "bzy_mhz",
        "tsc_mhz",
        "temp_c",
        "core_throttle_count",
        "package_throttle_count",
        "sampled_cpu_count",
    ]

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in samples:
            writer.writerow(row)
