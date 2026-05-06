#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import statistics
import subprocess
import sys
import time
from pathlib import Path

from benchlib import DEFAULT_SCENE
from benchlib import GPU_VARIANT
from benchlib import PRESENT_DIR
from benchlib import PROJECT_ROOT
from benchlib import RAW_DIR
from benchlib import REPORT_DIR
from benchlib import THROTTLE_FIELDS
from benchlib import TURBOSTAT_COLUMNS
from benchlib import VARIANT_INDEX
from benchlib import VARIANTS
from benchlib import benchmark_binary_path
from benchlib import build_bench_command
from benchlib import compile_variant
from benchlib import cpupower_snapshot
from benchlib import detect_online_cpus
from benchlib import display_environment
from benchlib import ensure_clean_dir
from benchlib import format_cpu_list
from benchlib import parse_cpu_list
from benchlib import parse_opt_levels
from benchlib import parse_summary
from benchlib import parse_turbostat_samples
from benchlib import read_frames
from benchlib import read_text
from benchlib import run_command
from benchlib import scalar_stats
from benchlib import sudo_prefix
from benchlib import write_samples

CPU_OUTPUT_PATH     = REPORT_DIR  / "results.json"
PRESENT_OUTPUT_PATH = REPORT_DIR  / "presentation_results.json"
GPU_OUTPUT_PATH     = REPORT_DIR  / "gpu_results.json"
GPU_DIR             = PRESENT_DIR / "gpu"

def start_turbostat(raw_path: Path, affinity: str, sample_interval: float) -> subprocess.Popen[str]:
    turbostat_bin = shutil.which("turbostat")
    if turbostat_bin is None:
        raise RuntimeError("turbostat is required")

    cmd = sudo_prefix(turbostat_bin) + [
        "--quiet",
        "--interval",
        f"{sample_interval:.3f}",
        "--header_iterations",
        "1",
        "--cpu",
        affinity,
        "--show",
        ",".join(TURBOSTAT_COLUMNS),
        "--out",
        str(raw_path),
    ]

    process = subprocess.Popen(
        cmd,
        cwd=PROJECT_ROOT,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    time.sleep(min(sample_interval, 0.20))
    if process.poll() is not None:
        _, stderr = process.communicate()
        raise RuntimeError(stderr.strip() or "turbostat exited immediately")
    return process

def stop_turbostat(process: subprocess.Popen[str]) -> str:
    if process.poll() is None:
        process.send_signal(signal.SIGINT)
    try:
        _, stderr = process.communicate(timeout=5.0)
    except subprocess.TimeoutExpired:
        process.kill()
        _, stderr = process.communicate(timeout=5.0)
    return stderr

def run_cpu_variant(variant,
                    opt_level: str,
                    run_index: int,
                    frames:    int,
                    warmup:    int,
                    min_representative_frames: int,
                    center_x:  str,
                    center_y:  str,
                    zoom:      str,
                    sample_interval: float,
                    single_affinity: str,
                    threaded_affinity: str) -> dict[str, object]:
    variant_dir = RAW_DIR / opt_level.lstrip("-") / variant.label / f"run_{run_index:02d}"
    variant_dir.mkdir(parents=True, exist_ok=True)

    frames_path = variant_dir / "frames.csv"
    samples_path = variant_dir / "samples.csv"
    summary_path = variant_dir / "summary.txt"
    turbostat_path = variant_dir / "turbostat.txt"

    affinity = threaded_affinity if variant.threaded else single_affinity
    cpus = parse_cpu_list(affinity)
    env = os.environ.copy()
    if variant.threaded:
        env.setdefault("MANDELBROT_THREADS", str(len(cpus)))

    cmd = [
        "taskset",
        "--cpu-list",
        affinity,
        *build_bench_command(
            variant.source,
            "render",
            frames_path,
            frames,
            warmup,
            center_x,
            center_y,
            zoom,
        ),
    ]

    turbostat_proc = start_turbostat(turbostat_path, affinity, sample_interval)
    try:
        process = subprocess.Popen(
            cmd,
            cwd=PROJECT_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, stderr = process.communicate()
    finally:
        turbostat_stderr = stop_turbostat(turbostat_proc)

    if turbostat_stderr and "Guessing tjMax" not in turbostat_stderr:
        sys.stderr.write(turbostat_stderr)

    summary_path.write_text(stdout, encoding="utf-8")
    if stderr:
        sys.stderr.write(stderr)

    if process.returncode != 0:
        raise RuntimeError(f"benchmark failed for {variant.label} {opt_level} run {run_index}")

    raw_turbostat = read_text(turbostat_path)
    if raw_turbostat is None:
        raise RuntimeError(f"missing turbostat output for {variant.label} {opt_level} run {run_index}")

    samples = parse_turbostat_samples(raw_turbostat, cpus, sample_interval)
    write_samples(samples_path, samples)

    summary = parse_summary(stdout)
    ticks, ns = read_frames(frames_path)

    freq_values = [float(sample["freq_mhz"]) for sample in samples if sample["freq_mhz"] is not None]
    temp_values = [float(sample["temp_c"]) for sample in samples if sample["temp_c"] is not None]
    busy_values = [float(sample["busy_pct"]) for sample in samples if sample["busy_pct"] is not None]
    bzy_values = [float(sample["bzy_mhz"]) for sample in samples if sample["bzy_mhz"] is not None]
    tsc_values = [float(sample["tsc_mhz"]) for sample in samples if sample["tsc_mhz"] is not None]

    throttle_delta = {
        "core_throttle_count": sum(int(sample["core_throttle_count"]) for sample in samples),
        "package_throttle_count": sum(int(sample["package_throttle_count"]) for sample in samples),
    }
    throttle_detected = any(value > 0 for value in throttle_delta.values())

    return {
        "label": variant.label,
        "source": variant.source,
        "threaded": variant.threaded,
        "opt_level": opt_level,
        "run_index": run_index,
        "affinity": affinity,
        "binary": str(benchmark_binary_path(variant.source).relative_to(PROJECT_ROOT)),
        "frames_csv": str(frames_path.relative_to(PROJECT_ROOT)),
        "samples_csv": str(samples_path.relative_to(PROJECT_ROOT)),
        "summary_txt": str(summary_path.relative_to(PROJECT_ROOT)),
        "turbostat_txt": str(turbostat_path.relative_to(PROJECT_ROOT)),
        "summary": summary,
        "tick_stats": scalar_stats(ticks),
        "ns_stats": scalar_stats(ns),
        "sample_count": len(samples),
        "freq_mhz": scalar_stats(freq_values) if freq_values else None,
        "temp_c": scalar_stats(temp_values) if temp_values else None,
        "busy_pct": scalar_stats(busy_values) if busy_values else None,
        "bzy_mhz": scalar_stats(bzy_values) if bzy_values else None,
        "tsc_mhz": scalar_stats(tsc_values) if tsc_values else None,
        "peak_rss_kb": int(summary.get("maxrss_kb", "0")),
        "throttle_delta": throttle_delta,
        "throttle_detected": throttle_detected,
        "representative_run": (not throttle_detected) and len(ns) >= min_representative_frames,
    }

def aggregate_cpu_runs(runs: list[dict[str, object]], min_runs: int, max_cv_pct: float) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
    for run in runs:
        grouped.setdefault((str(run["opt_level"]), str(run["label"])), []).append(run)

    groups: list[dict[str, object]] = []
    for (opt_level, label), group_runs in sorted(grouped.items()):
        mean_ns = [float(run["summary"]["mean_ns"]) for run in group_runs]
        mean_ms = [float(run["summary"]["mean_ms"]) for run in group_runs]
        peak_rss = [int(run["peak_rss_kb"]) for run in group_runs]
        checksums = [str(run["summary"]["checksum"]) for run in group_runs]
        freq_means = [
            float(run["freq_mhz"]["mean"])
            for run in group_runs
            if run["freq_mhz"] is not None
        ]
        temp_means = [
            float(run["temp_c"]["mean"])
            for run in group_runs
            if run["temp_c"] is not None
        ]
        run_cv_pct = (
            statistics.stdev(mean_ns) / statistics.fmean(mean_ns) * 100.0
            if len(mean_ns) > 1 and statistics.fmean(mean_ns) > 0.0
            else 0.0
        )

        total_throttle = {field: 0 for field in THROTTLE_FIELDS}
        for run in group_runs:
            for field in THROTTLE_FIELDS:
                total_throttle[field] += int(run["throttle_delta"][field])

        checksum_match = len(set(checksums)) == 1
        representative = (
            len(group_runs) >= min_runs
            and checksum_match
            and run_cv_pct <= max_cv_pct
            and all(bool(run["representative_run"]) for run in group_runs)
            and total_throttle["core_throttle_count"] == 0
            and total_throttle["package_throttle_count"] == 0
        )

        groups.append({
            "opt_level": opt_level,
            "label": label,
            "source": group_runs[0]["source"],
            "threaded": group_runs[0]["threaded"],
            "runs": group_runs,
            "run_count": len(group_runs),
            "checksum": checksums[0] if checksums else "",
            "checksum_match": checksum_match,
            "mean_ns": statistics.fmean(mean_ns),
            "stdev_ns": statistics.stdev(mean_ns) if len(mean_ns) > 1 else 0.0,
            "mean_ms": statistics.fmean(mean_ms),
            "stdev_ms": statistics.stdev(mean_ms) if len(mean_ms) > 1 else 0.0,
            "cv_between_runs_pct": run_cv_pct,
            "avg_freq_mhz": statistics.fmean(freq_means) if freq_means else None,
            "avg_temp_c": statistics.fmean(temp_means) if temp_means else None,
            "peak_rss_kb": max(peak_rss) if peak_rss else 0,
            "total_throttle": total_throttle,
            "representative": representative,
        })

    baselines = {group["opt_level"]: group for group in groups if group["label"] == "naive"}
    arrays = {group["opt_level"]: group for group in groups if group["label"] == "arrays"}
    groups_by_opt = {
        opt_level: {group["label"]: group for group in groups if group["opt_level"] == opt_level}
        for opt_level in baselines
    }

    for group in groups:
        baseline = baselines[group["opt_level"]]
        baseline_ns = float(baseline["mean_ns"])
        group_ns = float(group["mean_ns"])
        group["improvement_vs_baseline_pct"] = (baseline_ns - group_ns) / baseline_ns * 100.0
        group["checksum_matches_baseline"] = group["checksum"] == baseline["checksum"]

        previous_index = VARIANT_INDEX[group["label"]] - 1
        if previous_index >= 0:
            previous_label = VARIANTS[previous_index].label
            previous_group = groups_by_opt[group["opt_level"]].get(previous_label)
            group["previous_variant_label"] = previous_label
            if previous_group is not None:
                previous_ns = float(previous_group["mean_ns"])
                group["improvement_vs_previous_pct"] = (previous_ns - group_ns) / previous_ns * 100.0
            else:
                group["improvement_vs_previous_pct"] = None
        else:
            group["previous_variant_label"] = None
            group["improvement_vs_previous_pct"] = None

        arrays_group = arrays.get(group["opt_level"])
        if arrays_group is not None:
            arrays_ns = float(arrays_group["mean_ns"])
            group["improvement_vs_arrays_pct"] = (arrays_ns - group_ns) / arrays_ns * 100.0
        else:
            group["improvement_vs_arrays_pct"] = None

    return groups

def collect_cpu_environment(single_affinity: str, threaded_affinity: str) -> dict[str, object]:
    lscpu = run_command(["lscpu"])
    power = cpupower_snapshot()
    return {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python": sys.version,
        "single_affinity": single_affinity,
        "threaded_affinity": threaded_affinity,
        "online_cpus": detect_online_cpus(),
        "pdflatex": shutil.which("pdflatex"),
        "taskset": shutil.which("taskset"),
        "turbostat": shutil.which("turbostat"),
        "cpupower": shutil.which("cpupower"),
        "cpupower_policy": power["policy"],
        "cpupower_hwlimits": power["hwlimits"],
        "cpupower_governors": power["available_governors"],
        "cpupower_current_governor": power["current_governor"],
        "lscpu": lscpu.stdout.strip(),
    }

def present_frames_path(label: str, run_index: int) -> Path:
    return PRESENT_DIR / label / f"run_{run_index:02d}" / "frames.csv"

def gpu_frames_path(run_index: int) -> Path:
    return GPU_DIR / f"run_{run_index:02d}" / "frames.csv"

def run_hidden_window_variant(variant,
                              run_index:   int,
                              frames_path: Path,
                              frames:      int,
                              warmup:      int,
                              center_x:    str,
                              center_y:    str,
                              zoom:        str,
                              gui_env:     dict[str, str],
                              affinity:    str | None) -> dict[str, object]:
    env = gui_env.copy()
    frames_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = build_bench_command(
        variant.source,
        "present",
        frames_path,
        frames,
        warmup,
        center_x,
        center_y,
        zoom,
    )

    if affinity is not None:
        if variant.threaded:
            env.setdefault("MANDELBROT_THREADS", str(len(parse_cpu_list(affinity))))
        cmd = [
            "taskset",
            "--cpu-list",
            affinity,
            *cmd,
        ]

    completed = run_command(cmd, env=env)
    sys.stderr.write(completed.stderr)
    if completed.returncode != 0:
        label = getattr(variant, "label", "benchmark")
        raise RuntimeError(f"present benchmark failed for {label} run {run_index}")

    result = {
        "label": variant.label,
        "threaded": variant.threaded,
        "run_index": run_index,
        "binary": str(benchmark_binary_path(variant.source).relative_to(PROJECT_ROOT)),
        "frames_csv": str(frames_path.relative_to(PROJECT_ROOT)),
        "summary": parse_summary(completed.stdout),
    }
    if affinity is not None:
        result["affinity"] = affinity
    return result

def aggregate_present_runs(runs: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for run in runs:
        grouped.setdefault(str(run["label"]), []).append(run)

    groups: list[dict[str, object]] = []
    for label, group_runs in sorted(grouped.items()):
        render_ms = [float(run["summary"]["mean_render_ms"]) for run in group_runs]
        present_ms = [float(run["summary"]["mean_present_ms"]) for run in group_runs]
        total_ms = [float(run["summary"]["mean_total_ms"]) for run in group_runs]
        present_pct_total = [float(run["summary"]["present_pct_total"]) for run in group_runs]

        groups.append({
            "label": label,
            "threaded": bool(group_runs[0]["threaded"]),
            "run_count": len(group_runs),
            "mean_render_ms": statistics.fmean(render_ms),
            "mean_present_ms": statistics.fmean(present_ms),
            "mean_total_ms": statistics.fmean(total_ms),
            "mean_present_pct_total": statistics.fmean(present_pct_total),
            "stdev_total_ms": statistics.stdev(total_ms) if len(total_ms) > 1 else 0.0,
            "runs": group_runs,
        })

    return groups

def aggregate_gpu_runs(runs: list[dict[str, object]]) -> dict[str, object]:
    render_ms = [float(run["summary"]["mean_render_ms"]) for run in runs]
    present_ms = [float(run["summary"]["mean_present_ms"]) for run in runs]
    total_ms = [float(run["summary"]["mean_total_ms"]) for run in runs]
    present_pct_total = [float(run["summary"]["present_pct_total"]) for run in runs]

    return {
        "label": GPU_VARIANT.label,
        "run_count": len(runs),
        "mean_render_ms": statistics.fmean(render_ms),
        "stdev_render_ms": statistics.stdev(render_ms) if len(render_ms) > 1 else 0.0,
        "mean_present_ms": statistics.fmean(present_ms),
        "stdev_present_ms": statistics.stdev(present_ms) if len(present_ms) > 1 else 0.0,
        "mean_total_ms": statistics.fmean(total_ms),
        "stdev_total_ms": statistics.stdev(total_ms) if len(total_ms) > 1 else 0.0,
        "mean_present_pct_total": statistics.fmean(present_pct_total),
        "runs": runs,
    }

def run_cpu_suite() -> int:
    required_tools = {
        "taskset": shutil.which("taskset"),
        "turbostat": shutil.which("turbostat"),
        "cpupower": shutil.which("cpupower"),
        "sudo": shutil.which("sudo"),
    }
    missing = sorted(name for name, path in required_tools.items() if path is None)
    if missing:
        print(f"missing required tools: {', '.join(missing)}", file=sys.stderr)
        return 1

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ensure_clean_dir(REPORT_DIR / "data")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PRESENT_DIR.mkdir(parents=True, exist_ok=True)

    online_cpus = detect_online_cpus()
    default_single_cpu = str(online_cpus[min(3, len(online_cpus) - 1)])
    default_threaded_affinity = format_cpu_list(online_cpus)

    opt_levels = parse_opt_levels()
    runs_per_variant = int(os.environ.get("RUNS", "5"))
    frames = int(os.environ.get("FRAMES", "240"))
    warmup = int(os.environ.get("WARMUP", "40"))
    min_runs = int(os.environ.get("MIN_REPRESENTATIVE_RUNS", "5"))
    min_representative_frames = int(os.environ.get("MIN_REPRESENTATIVE_FRAMES", "60"))
    max_cv_pct = float(os.environ.get("MAX_REPRESENTATIVE_CV_PCT", "5.0"))
    sample_interval = float(os.environ.get("TURBOSTAT_INTERVAL", os.environ.get("SAMPLE_INTERVAL", "0.5")))
    cooldown_seconds = float(os.environ.get("COOLDOWN_SECONDS", "0.0"))
    center_x = os.environ.get("CENTER_X", DEFAULT_SCENE["center_x"])
    center_y = os.environ.get("CENTER_Y", DEFAULT_SCENE["center_y"])
    zoom = os.environ.get("ZOOM", DEFAULT_SCENE["zoom"])
    single_affinity = os.environ.get("SINGLE_AFFINITY", default_single_cpu)
    threaded_affinity = os.environ.get("THREAD_AFFINITY", default_threaded_affinity)

    all_runs: list[dict[str, object]] = []
    for opt_level in opt_levels:
        print(f"== {opt_level} ==")
        for variant in VARIANTS:
            print(f"-- build {variant.label}")
            compile_variant(variant, opt_level, "--bench")

            for run_index in range(1, runs_per_variant + 1):
                print(f"-- run {variant.label} {opt_level} [{run_index}/{runs_per_variant}]")
                result = run_cpu_variant(
                    variant,
                    opt_level,
                    run_index,
                    frames,
                    warmup,
                    min_representative_frames,
                    center_x,
                    center_y,
                    zoom,
                    sample_interval,
                    single_affinity,
                    threaded_affinity,
                )
                all_runs.append(result)

                if cooldown_seconds > 0.0:
                    print(f"-- cooldown {cooldown_seconds:.1f}s")
                    time.sleep(cooldown_seconds)

    groups = aggregate_cpu_runs(all_runs, min_runs, max_cv_pct)
    environment = collect_cpu_environment(single_affinity, threaded_affinity)

    payload = {
        "config": {
            "opt_levels": opt_levels,
            "runs_per_variant": runs_per_variant,
            "frames": frames,
            "warmup": warmup,
            "sample_interval_s": sample_interval,
            "cooldown_seconds": cooldown_seconds,
            "scene": {
                "center_x": center_x,
                "center_y": center_y,
                "zoom": zoom,
            },
            "power_plan": {
                "governor": os.environ.get("BENCH_GOVERNOR", "performance"),
                "frequency": os.environ.get("BENCH_FREQUENCY", ""),
                "min_frequency": os.environ.get("BENCH_MIN_FREQ", ""),
                "max_frequency": os.environ.get("BENCH_MAX_FREQ", ""),
                "cpupower_enabled": os.environ.get("BENCH_SKIP_CPUPOWER", "0") != "1",
            },
            "representative_rule": {
                "min_runs": min_runs,
                "min_frames_per_run": min_representative_frames,
                "max_cv_pct": max_cv_pct,
                "throttle_free_required": True,
                "checksum_match_required": True,
            },
        },
        "environment": environment,
        "variants": [variant.__dict__ for variant in VARIANTS],
        "runs": all_runs,
        "groups": groups,
    }

    CPU_OUTPUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {CPU_OUTPUT_PATH.relative_to(PROJECT_ROOT)}")
    return 0

def run_present_suite() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ensure_clean_dir(PRESENT_DIR)

    opt_level = os.environ.get("PRESENT_OPT_LEVEL", "-O3")
    runs = int(os.environ.get("PRESENT_RUNS", "2"))
    frames = int(os.environ.get("PRESENT_FRAMES", "30"))
    warmup = int(os.environ.get("PRESENT_WARMUP", "5"))
    center_x = os.environ.get("CENTER_X", DEFAULT_SCENE["center_x"])
    center_y = os.environ.get("CENTER_Y", DEFAULT_SCENE["center_y"])
    zoom = os.environ.get("ZOOM", DEFAULT_SCENE["zoom"])

    online_cpus = detect_online_cpus()
    single_affinity = os.environ.get("SINGLE_AFFINITY", str(online_cpus[min(3, len(online_cpus) - 1)]))
    threaded_affinity = os.environ.get("THREAD_AFFINITY", format_cpu_list(online_cpus))

    for variant in VARIANTS:
        compile_variant(variant, opt_level, "--bench")

    try:
        with display_environment() as gui_env:
            all_runs: list[dict[str, object]] = []
            for variant in VARIANTS:
                for run_index in range(1, runs + 1):
                    print(f"-- present {variant.label} [{run_index}/{runs}]")
                    affinity = threaded_affinity if variant.threaded else single_affinity
                    result = run_hidden_window_variant(
                        variant,
                        run_index,
                        present_frames_path(variant.label, run_index),
                        frames,
                        warmup,
                        center_x,
                        center_y,
                        zoom,
                        gui_env,
                        affinity,
                    )
                    result["opt_level"] = opt_level
                    all_runs.append(result)
    except Exception as exc:
        payload = {
            "available": False,
            "error": str(exc),
            "config": {
                "opt_level": opt_level,
                "runs": runs,
                "frames": frames,
                "warmup": warmup,
            },
        }
        PRESENT_OUTPUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"wrote {PRESENT_OUTPUT_PATH.relative_to(PROJECT_ROOT)}")
        return 0

    payload = {
        "available": True,
        "config": {
            "opt_level": opt_level,
            "runs": runs,
            "frames": frames,
            "warmup": warmup,
            "single_affinity": single_affinity,
            "threaded_affinity": threaded_affinity,
        },
        "runs": all_runs,
        "groups": aggregate_present_runs(all_runs),
    }
    PRESENT_OUTPUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {PRESENT_OUTPUT_PATH.relative_to(PROJECT_ROOT)}")
    return 0

def run_gpu_suite() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ensure_clean_dir(GPU_DIR)

    opt_level = os.environ.get("GPU_OPT_LEVEL", "-O3")
    runs = int(os.environ.get("GPU_RUNS", "3"))
    frames = int(os.environ.get("GPU_FRAMES", "60"))
    warmup = int(os.environ.get("GPU_WARMUP", "10"))
    center_x = os.environ.get("CENTER_X", DEFAULT_SCENE["center_x"])
    center_y = os.environ.get("CENTER_Y", DEFAULT_SCENE["center_y"])
    zoom = os.environ.get("ZOOM", DEFAULT_SCENE["zoom"])

    compile_variant(GPU_VARIANT, opt_level, "--bench")

    try:
        with display_environment() as gui_env:
            all_runs: list[dict[str, object]] = []
            for run_index in range(1, runs + 1):
                print(f"-- gpu [{run_index}/{runs}]")
                result = run_hidden_window_variant(
                    GPU_VARIANT,
                    run_index,
                    gpu_frames_path(run_index),
                    frames,
                    warmup,
                    center_x,
                    center_y,
                    zoom,
                    gui_env,
                    None,
                )
                result["opt_level"] = opt_level
                all_runs.append(result)
    except Exception as exc:
        payload = {
            "available": False,
            "error": str(exc),
            "config": {
                "opt_level": opt_level,
                "runs": runs,
                "frames": frames,
                "warmup": warmup,
                "scene": {
                    "center_x": center_x,
                    "center_y": center_y,
                    "zoom": zoom,
                },
            },
        }
        GPU_OUTPUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"wrote {GPU_OUTPUT_PATH.relative_to(PROJECT_ROOT)}")
        return 0

    payload = {
        "available": True,
        "config": {
            "opt_level": opt_level,
            "runs": runs,
            "frames": frames,
            "warmup": warmup,
            "scene": {
                "center_x": center_x,
                "center_y": center_y,
                "zoom": zoom,
            },
            "notes": "GPU benchmark uses the hidden-window renderer path and records render-only frame time without cpupower or turbostat controls.",
        },
        "variant": GPU_VARIANT.__dict__,
        "runs": all_runs,
        "summary": aggregate_gpu_runs(all_runs),
    }
    GPU_OUTPUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {GPU_OUTPUT_PATH.relative_to(PROJECT_ROOT)}")
    return 0

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Mandelbrot benchmark suites.")
    parser.add_argument(
        "--suite",
        choices=("cpu", "present", "gpu", "all"),
        default="cpu",
        help="Benchmark suite to run. Defaults to the historical CPU benchmark.",
    )
    return parser.parse_args()

def main() -> int:
    args = parse_args()

    if args.suite == "cpu":
        return run_cpu_suite()
    if args.suite == "present":
        return run_present_suite()
    if args.suite == "gpu":
        return run_gpu_suite()

    for runner in (run_cpu_suite, run_present_suite, run_gpu_suite):
        exit_code = runner()
        if exit_code != 0:
            return exit_code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
