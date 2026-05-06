#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import statistics
import shutil
import subprocess
import textwrap
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

PROJECT_ROOT         = Path(__file__).resolve().parent
REPORT_DIR           = PROJECT_ROOT / "report"
RESULTS_PATH         = REPORT_DIR   / "results.json"
PRESENT_RESULTS_PATH = REPORT_DIR   / "presentation_results.json"
GPU_RESULTS_PATH     = REPORT_DIR   / "gpu_results.json"
PLOT_DIR             = PROJECT_ROOT / "img" / "plots"

VARIANT_ORDER = ["naive", "arrays", "simd", "simd_threads"]
PREVIOUS_VARIANT = {
    "naive": None,
    "arrays": "naive",
    "simd": "arrays",
    "simd_threads": "simd",
}

OPT_ORDER = ["-O1", "-O2", "-O3"]
COLORS = {
    "naive": "#4c566a",
    "arrays": "#2a9d8f",
    "simd": "#e76f51",
    "simd_threads": "#264653",
    "gpu": "#6d597a",
}

LSCPU_VULNERABILITY_PREFIX = "Vulnerability "
T_975_BY_DOF = {
    1: 12.706,
    2: 4.303,
    3: 3.182,
    4: 2.776,
    5: 2.571,
    6: 2.447,
    7: 2.365,
    8: 2.306,
    9: 2.262,
    10: 2.228,
    11: 2.201,
    12: 2.179,
    13: 2.160,
    14: 2.145,
    15: 2.131,
    16: 2.120,
    17: 2.110,
    18: 2.101,
    19: 2.093,
    20: 2.086,
    21: 2.080,
    22: 2.074,
    23: 2.069,
    24: 2.064,
    25: 2.060,
    26: 2.056,
    27: 2.052,
    28: 2.048,
    29: 2.045,
    30: 2.042,
    40: 2.021,
    60: 2.000,
    120: 1.980,
}

def ensure_dirs() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    PLOT_DIR.mkdir(parents=True, exist_ok=True)

def load_payload() -> dict:
    return json.loads(RESULTS_PATH.read_text(encoding="utf-8"))

def load_presentation_payload() -> dict | None:
    if not PRESENT_RESULTS_PATH.exists():
        return None
    return json.loads(PRESENT_RESULTS_PATH.read_text(encoding="utf-8"))

def load_gpu_payload() -> dict | None:
    if not GPU_RESULTS_PATH.exists():
        return None
    return json.loads(GPU_RESULTS_PATH.read_text(encoding="utf-8"))

def t_critical_975(dof: int) -> float:
    if dof <= 0:
        return 0.0
    if dof in T_975_BY_DOF:
        return T_975_BY_DOF[dof]
    for limit in sorted(T_975_BY_DOF):
        if dof <= limit:
            return T_975_BY_DOF[limit]
    return 1.960

def add_uncertainty_columns(df: pd.DataFrame,
                            *,
                            mean_col:      str,
                            stdev_col:     str,
                            run_count_col: str,
                            prefix: str = "") -> pd.DataFrame:
    run_counts = df[run_count_col].astype(int)
    means = df[mean_col].astype(float)
    stdevs = df[stdev_col].astype(float)

    sem_values = [
        stdev / math.sqrt(run_count) if run_count > 0 else 0.0
        for stdev, run_count in zip(stdevs, run_counts, strict=False)
    ]
    ci95_values = [
        t_critical_975(run_count - 1) * sem if run_count > 1 else 0.0
        for sem, run_count in zip(sem_values, run_counts, strict=False)
    ]

    df[f"{prefix}sigma_minus_ms"] = means - stdevs
    df[f"{prefix}sigma_plus_ms"] = means + stdevs
    df[f"{prefix}sem_ms"] = sem_values
    df[f"{prefix}ci95_ms"] = ci95_values
    df[f"{prefix}ci95_minus_ms"] = means - df[f"{prefix}ci95_ms"]
    df[f"{prefix}ci95_plus_ms"] = means + df[f"{prefix}ci95_ms"]
    df[f"{prefix}relative_inaccuracy_pct"] = np.where(
        means > 0.0,
        df[f"{prefix}ci95_ms"] / means * 100.0,
        0.0,
    )
    return df

def groups_frame(payload: dict) -> pd.DataFrame:
    rows = []
    for group in payload["groups"]:
        rows.append({
            "opt_level": group["opt_level"],
            "label": group["label"],
            "run_count": group["run_count"],
            "mean_ms": group["mean_ms"],
            "stdev_ms": group["stdev_ms"],
            "cv_between_runs_pct": group["cv_between_runs_pct"],
            "improvement_vs_baseline_pct": group["improvement_vs_baseline_pct"],
            "improvement_vs_arrays_pct": group["improvement_vs_arrays_pct"],
            "avg_freq_mhz": group["avg_freq_mhz"],
            "avg_temp_c": group["avg_temp_c"],
            "peak_rss_mb": group["peak_rss_kb"] / 1024.0,
            "representative": group["representative"],
            "checksum_matches_baseline": group["checksum_matches_baseline"],
            "core_throttle_count": group["total_throttle"]["core_throttle_count"],
            "package_throttle_count": group["total_throttle"]["package_throttle_count"],
        })
    df = pd.DataFrame(rows)
    df["previous_variant_label"] = df["label"].map(PREVIOUS_VARIANT)
    df["improvement_vs_previous_pct"] = np.nan

    for opt_level in OPT_ORDER:
        subset = df[df["opt_level"] == opt_level].set_index("label")
        for label, previous_label in PREVIOUS_VARIANT.items():
            if previous_label is None or label not in subset.index or previous_label not in subset.index:
                continue
            previous_ms = float(subset.loc[previous_label, "mean_ms"])
            current_ms = float(subset.loc[label, "mean_ms"])
            df.loc[
                (df["opt_level"] == opt_level) & (df["label"] == label),
                "improvement_vs_previous_pct",
            ] = (previous_ms - current_ms) / previous_ms * 100.0

    df["label"] = pd.Categorical(df["label"], VARIANT_ORDER, ordered=True)
    df["opt_level"] = pd.Categorical(df["opt_level"], OPT_ORDER, ordered=True)
    df = df.sort_values(["opt_level", "label"]).reset_index(drop=True)
    return add_uncertainty_columns(
        df,
        mean_col="mean_ms",
        stdev_col="stdev_ms",
        run_count_col="run_count",
    )

def presentation_frame(payload: dict | None) -> pd.DataFrame | None:
    if payload is None or not payload.get("available", False):
        return None

    rows = []
    for group in payload["groups"]:
        render_ms = [float(run["summary"]["mean_render_ms"]) for run in group["runs"]]
        present_ms = [float(run["summary"]["mean_present_ms"]) for run in group["runs"]]
        total_ms = [float(run["summary"]["mean_total_ms"]) for run in group["runs"]]
        rows.append({
            "label": group["label"],
            "threaded": group["threaded"],
            "run_count": group["run_count"],
            "mean_render_ms": group["mean_render_ms"],
            "stdev_render_ms": statistics.stdev(render_ms) if len(render_ms) > 1 else 0.0,
            "mean_present_ms": group["mean_present_ms"],
            "stdev_present_ms": statistics.stdev(present_ms) if len(present_ms) > 1 else 0.0,
            "mean_total_ms": group["mean_total_ms"],
            "mean_present_pct_total": group["mean_present_pct_total"],
            "stdev_total_ms": statistics.stdev(total_ms) if len(total_ms) > 1 else 0.0,
        })

    df = pd.DataFrame(rows)
    df["label"] = pd.Categorical(df["label"], VARIANT_ORDER, ordered=True)
    df = df.sort_values(["label"]).reset_index(drop=True)
    df = add_uncertainty_columns(
        df,
        mean_col="mean_render_ms",
        stdev_col="stdev_render_ms",
        run_count_col="run_count",
        prefix="render_",
    )
    df = add_uncertainty_columns(
        df,
        mean_col="mean_present_ms",
        stdev_col="stdev_present_ms",
        run_count_col="run_count",
        prefix="present_",
    )
    return add_uncertainty_columns(
        df,
        mean_col="mean_total_ms",
        stdev_col="stdev_total_ms",
        run_count_col="run_count",
        prefix="total_",
    )

def gpu_frame(payload: dict | None) -> pd.DataFrame | None:
    if payload is None or not payload.get("available", False):
        return None

    summary = payload["summary"]
    df = pd.DataFrame([{
        "label": summary["label"],
        "run_count": summary["run_count"],
        "mean_render_ms": summary["mean_render_ms"],
        "stdev_render_ms": summary["stdev_render_ms"],
        "mean_present_ms": summary["mean_present_ms"],
        "stdev_present_ms": summary["stdev_present_ms"],
        "mean_total_ms": summary["mean_total_ms"],
        "stdev_total_ms": summary["stdev_total_ms"],
        "mean_present_pct_total": summary["mean_present_pct_total"],
    }])
    df = add_uncertainty_columns(
        df,
        mean_col="mean_render_ms",
        stdev_col="stdev_render_ms",
        run_count_col="run_count",
        prefix="render_",
    )
    return add_uncertainty_columns(
        df,
        mean_col="mean_total_ms",
        stdev_col="stdev_total_ms",
        run_count_col="run_count",
        prefix="total_",
    )

def load_o3_frame_times(payload: dict) -> pd.DataFrame:
    rows = []
    for run in payload["runs"]:
        if run["opt_level"] != "-O3":
            continue
        path = PROJECT_ROOT / run["frames_csv"]
        frame_df = pd.read_csv(path)
        frame_df["label"] = run["label"]
        frame_df["run_index"] = run["run_index"]
        frame_df["ms"] = frame_df["ns"] / 1e6
        rows.append(frame_df[["label", "run_index", "ms"]])
    if not rows:
        return pd.DataFrame(columns=["label", "run_index", "ms"])
    df = pd.concat(rows, ignore_index=True)
    df["label"] = pd.Categorical(df["label"], VARIANT_ORDER, ordered=True)
    return df.sort_values(["label", "run_index"]).reset_index(drop=True)

def format_ms_number(value: float) -> str:
    if abs(value) >= 100.0:
        return f"{value:.1f}"
    return f"{value:.2f}"

def format_ms_value(mean_ms: float) -> str:
    return f"{format_ms_number(mean_ms)} ms"

def format_speedup_data_label(base_pct: float,
                              previous_pct: float | None,
                              mean_ms: float,
                              sigma_ms: float,
                              ci95_ms: float) -> str:
    prev_text = "--" if previous_pct is None or math.isnan(previous_pct) else f"{previous_pct:+.1f}"
    return (
        f"base% {base_pct:+.1f}\n"
        f"prev% {prev_text}\n"
        f"data {format_ms_value(mean_ms)}\n"
        f"1sig +/-{format_ms_number(sigma_ms)} | 95ci +/-{format_ms_number(ci95_ms)}"
    )


def format_present_data_label(present_pct: float,
                              mean_present_ms: float,
                              stdev_render_ms: float,
                              stdev_present_ms: float,
                              stdev_total_ms: float,
                              ci95_total_ms: float) -> str:
    return (
        f"present {present_pct:.1f}% | mean {format_ms_number(mean_present_ms)} ms\n"
        f"1sig r/p/t {format_ms_number(stdev_render_ms)}/{format_ms_number(stdev_present_ms)}/{format_ms_number(stdev_total_ms)} | 95ci +/-{format_ms_number(ci95_total_ms)}"
    )


def format_uncertainty_label(mean_ms: float, sigma_ms: float, ci95_ms: float) -> str:
    return (
        f"data {format_ms_value(mean_ms)}\n"
        f"1sig +/-{format_ms_number(sigma_ms)} | 95ci +/-{format_ms_number(ci95_ms)}"
    )

def sanitize_lscpu_report(text: str) -> str:
    lines = [
        line
        for line in text.splitlines()
        if not line.lower().startswith(LSCPU_VULNERABILITY_PREFIX.lower())
        and not line.lower().startswith("flags:")
        and not line.lower().startswith("numa")
    ]
    return "\n".join(lines)

def wrap_verbatim_lines(text: str, width: int = 88) -> str:
    wrapped: list[str] = []
    for line in text.splitlines():
        if len(line) <= width:
            wrapped.append(line)
            continue
        wrapped.extend(textwrap.wrap(
            line,
            width=width,
            subsequent_indent="    ",
            break_long_words=False,
            break_on_hyphens=False,
        ))
    return "\n".join(wrapped)

def plot_all_opts(df: pd.DataFrame) -> Path:
    fig, ax = plt.subplots(figsize=(12, 6))
    x = np.arange(len(VARIANT_ORDER))
    width = 0.22
    max_mean = max(float(df["mean_ms"].max()), 1.0)
    label_offset = max_mean * 0.035
    label_tops: list[float] = []

    for index, opt_level in enumerate(OPT_ORDER):
        subset = df[df["opt_level"] == opt_level].set_index("label").reindex(VARIANT_ORDER)
        offset = (index - 1) * width
        bars = ax.bar(
            x + offset,
            subset["mean_ms"],
            width,
            yerr=subset["stdev_ms"],
            capsize=5,
            label=opt_level,
            alpha=0.9,
        )
        for bar, base_pct, previous_pct, mean_ms, sigma_ms, ci95_ms in zip(
            bars,
            subset["improvement_vs_baseline_pct"],
            subset["improvement_vs_previous_pct"],
            subset["mean_ms"],
            subset["stdev_ms"],
            subset["ci95_ms"],
            strict=False,
        ):
            if pd.isna(base_pct):
                continue
            previous_value = None if pd.isna(previous_pct) else float(previous_pct)
            label_y = float(bar.get_height()) + float(sigma_ms) + label_offset
            label_tops.append(label_y)
            ax.text(
                bar.get_x() + bar.get_width() / 2.0,
                label_y,
                format_speedup_data_label(
                    float(base_pct),
                    previous_value,
                    float(mean_ms),
                    float(sigma_ms),
                    float(ci95_ms),
                ),
                ha="center",
                va="bottom",
                fontsize=4.9,
                bbox={
                    "boxstyle": "round,pad=0.22",
                    "facecolor": "white",
                    "edgecolor": "#d9d9d9",
                    "alpha": 0.96,
                },
                clip_on=False,
            )

    ax.set_xticks(x)
    ax.set_xticklabels(VARIANT_ORDER)
    ax.set_ylabel("Mean frame time, ms")
    ax.set_title("Mandelbrot CPU variants across optimization levels (labels = base%, prev%, mean, 1sig, 95ci)")
    ax.grid(axis="y", alpha=0.25)
    ax.legend()
    if label_tops:
        ax.set_ylim(0.0, max(label_tops) + label_offset * 2.0)
    fig.tight_layout()

    out_path = PLOT_DIR / "benchmark_all_opts.png"
    fig.savefig(out_path, dpi=250)
    plt.close(fig)
    return out_path

def plot_o3_focus(df: pd.DataFrame) -> Path:
    subset = df[df["opt_level"] == "-O3"].set_index("label").reindex(VARIANT_ORDER)

    fig, ax = plt.subplots(figsize=(10, 5))
    max_mean = max(float(subset["mean_ms"].max()), 1.0)
    label_offset = max_mean * 0.05
    label_tops: list[float] = []
    bars = ax.bar(
        subset.index.tolist(),
        subset["mean_ms"],
        yerr=subset["stdev_ms"],
        capsize=6,
        color=[COLORS[label] for label in subset.index],
    )

    for bar, base_pct, previous_pct, mean_ms, sigma_ms, ci95_ms in zip(
        bars,
        subset["improvement_vs_baseline_pct"],
        subset["improvement_vs_previous_pct"],
        subset["mean_ms"],
        subset["stdev_ms"],
        subset["ci95_ms"],
        strict=False,
    ):
        previous_value = None if pd.isna(previous_pct) else float(previous_pct)
        label_y = float(bar.get_height()) + float(sigma_ms) + label_offset
        label_tops.append(label_y)
        ax.text(
            bar.get_x() + bar.get_width() / 2.0,
            label_y,
            format_speedup_data_label(
                float(base_pct),
                previous_value,
                float(mean_ms),
                float(sigma_ms),
                float(ci95_ms),
            ),
            ha="center",
            va="bottom",
            fontsize=6.0,
            bbox={
                "boxstyle": "round,pad=0.24",
                "facecolor": "white",
                "edgecolor": "#d9d9d9",
                "alpha": 0.96,
            },
            clip_on=False,
        )

    ax.set_ylabel("Mean frame time, ms")
    ax.set_title("Focused -O3 comparison (labels = base%, prev%, mean, 1sig, 95ci)")
    ax.grid(axis="y", alpha=0.25)
    if label_tops:
        ax.set_ylim(0.0, max(label_tops) + label_offset * 2.0)
    fig.tight_layout()

    out_path = PLOT_DIR / "benchmark_o3_focus.png"
    fig.savefig(out_path, dpi=250)
    plt.close(fig)
    return out_path

def plot_o3_boxplot(frame_df: pd.DataFrame) -> Path | None:
    if frame_df.empty:
        return None

    fig, ax = plt.subplots(figsize=(10, 5))
    data = [frame_df[frame_df["label"] == label]["ms"].to_numpy() for label in VARIANT_ORDER]

    ax.boxplot(data, tick_labels=VARIANT_ORDER, showfliers=False)
    ax.set_ylabel("Per-frame time, ms")
    ax.set_title("Frame-time distribution at -O3")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()

    out_path = PLOT_DIR / "benchmark_o3_boxplot.png"
    fig.savefig(out_path, dpi=250)
    plt.close(fig)
    return out_path

def plot_o3_telemetry(df: pd.DataFrame) -> Path:
    subset = df[df["opt_level"] == "-O3"].set_index("label").reindex(VARIANT_ORDER)

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5))

    axes[0].bar(subset.index.tolist(), subset["avg_freq_mhz"], color="#457b9d")
    axes[0].set_title("Average frequency")
    axes[0].set_ylabel("MHz")
    axes[0].grid(axis="y", alpha=0.25)

    axes[1].bar(subset.index.tolist(), subset["peak_rss_mb"], color="#6a994e")
    axes[1].set_title("Peak resident memory")
    axes[1].set_ylabel("MiB")
    axes[1].grid(axis="y", alpha=0.25)

    temp_values = subset["avg_temp_c"]
    if temp_values.notna().any():
        axes[2].bar(subset.index.tolist(), temp_values, color="#bc4749")
        axes[2].set_ylabel("C")
        axes[2].set_title("Average temperature")
    else:
        throttle = subset["core_throttle_count"] + subset["package_throttle_count"]
        axes[2].bar(subset.index.tolist(), throttle, color="#bc4749")
        axes[2].set_ylabel("Count")
        axes[2].set_title("Throttle events")
    axes[2].grid(axis="y", alpha=0.25)

    fig.suptitle("-O3 telemetry summary")
    fig.tight_layout()

    out_path = PLOT_DIR / "benchmark_o3_telemetry.png"
    fig.savefig(out_path, dpi=250)
    plt.close(fig)
    return out_path

def plot_presentation_overhead(df: pd.DataFrame) -> Path:
    fig, ax = plt.subplots(figsize=(10, 5))
    labels = df["label"].tolist()
    render = df["mean_render_ms"].to_numpy(dtype=float)
    present = df["mean_present_ms"].to_numpy(dtype=float)
    totals = render + present

    ax.bar(
        labels,
        render,
        yerr=df["stdev_render_ms"],
        capsize=4,
        label="RenderMandelbrot only",
        color="#457b9d",
    )
    bars = ax.bar(
        labels,
        present,
        bottom=render,
        yerr=df["stdev_present_ms"],
        capsize=4,
        label="Texture upload + draw",
        color="#f4a261",
    )

    max_total = max(float(np.max(totals)), 1.0)
    label_offset = max_total * 0.08
    label_tops: list[float] = []

    for bar, pct, mean_present_ms, stdev_render_ms, stdev_present_ms, stdev_total_ms, ci95_total_ms in zip(
        bars,
        df["mean_present_pct_total"],
        df["mean_present_ms"],
        df["stdev_render_ms"],
        df["stdev_present_ms"],
        df["stdev_total_ms"],
        df["total_ci95_ms"],
        strict=False,
    ):
        total_height = float(bar.get_y() + bar.get_height())
        uncertainty_pad = max(
            float(stdev_render_ms),
            float(stdev_present_ms),
            float(stdev_total_ms),
            float(ci95_total_ms),
        )
        label_y = total_height + uncertainty_pad + label_offset
        label_tops.append(label_y)
        ax.text(
            bar.get_x() + bar.get_width() / 2.0,
            label_y,
            format_present_data_label(
                float(pct),
                float(mean_present_ms),
                float(stdev_render_ms),
                float(stdev_present_ms),
                float(stdev_total_ms),
                float(ci95_total_ms),
            ),
            ha="center",
            va="bottom",
            fontsize=7,
            bbox={
                "boxstyle": "round,pad=0.28",
                "facecolor": "white",
                "edgecolor": "#d9d9d9",
                "alpha": 0.96,
            },
            clip_on=False,
        )

    ax.set_ylabel("Mean frame time, ms")
    ax.set_title("Hidden-window presentation overhead at -O3 (labels = present%, 1sig, 95ci)")
    ax.grid(axis="y", alpha=0.25)
    ax.legend()
    if label_tops:
        ax.set_ylim(0.0, max(label_tops) + label_offset * 1.8)
    fig.tight_layout()

    out_path = PLOT_DIR / "benchmark_present_overhead.png"
    fig.savefig(out_path, dpi=250)
    plt.close(fig)
    return out_path

def plot_gpu_vs_fastest_cpu(df: pd.DataFrame, gpu_df: pd.DataFrame) -> Path:
    o3 = df[df["opt_level"] == "-O3"].reset_index(drop=True)
    fastest_idx = o3["mean_ms"].astype(float).idxmin()
    fastest = o3.loc[fastest_idx]
    gpu = gpu_df.iloc[0]

    compare = pd.DataFrame([
        {
            "label": f"{fastest['label']} CPU",
            "mean_ms": float(fastest["mean_ms"]),
            "stdev_ms": float(fastest["stdev_ms"]),
            "ci95_ms": float(fastest["ci95_ms"]),
            "color": COLORS[str(fastest["label"])],
        },
        {
            "label": "gpu render",
            "mean_ms": float(gpu["mean_render_ms"]),
            "stdev_ms": float(gpu["stdev_render_ms"]),
            "ci95_ms": float(gpu["render_ci95_ms"]),
            "color": COLORS["gpu"],
        },
    ])

    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar(
        compare["label"],
        compare["mean_ms"],
        yerr=compare["stdev_ms"],
        capsize=6,
        color=compare["color"],
    )

    max_mean = max(float(compare["mean_ms"].max()), 1.0)
    label_offset = max_mean * 0.08
    label_tops: list[float] = []
    for bar, mean_ms, sigma_ms, ci95_ms in zip(
        bars,
        compare["mean_ms"],
        compare["stdev_ms"],
        compare["ci95_ms"],
        strict=False,
    ):
        label_y = float(bar.get_height()) + float(sigma_ms) + label_offset
        label_tops.append(label_y)
        ax.text(
            bar.get_x() + bar.get_width() / 2.0,
            label_y,
            format_uncertainty_label(float(mean_ms), float(sigma_ms), float(ci95_ms)),
            ha="center",
            va="bottom",
            fontsize=7,
            bbox={
                "boxstyle": "round,pad=0.28",
                "facecolor": "white",
                "edgecolor": "#d9d9d9",
                "alpha": 0.96,
            },
            clip_on=False,
        )

    ax.set_ylabel("Mean frame time, ms")
    ax.set_title("Fastest -O3 CPU render vs hidden-window GPU render")
    ax.grid(axis="y", alpha=0.25)
    if label_tops:
        ax.set_ylim(0.0, max(label_tops) + label_offset * 1.8)
    fig.tight_layout()

    out_path = PLOT_DIR / "benchmark_gpu_vs_cpu.png"
    fig.savefig(out_path, dpi=250)
    plt.close(fig)
    return out_path

def tex_escape(text: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text

def build_findings(payload: dict,
                   df: pd.DataFrame,
                   present_payload: dict | None,
                   present_df: pd.DataFrame | None,
                   gpu_payload: dict | None,
                   gpu_df: pd.DataFrame | None) -> list[str]:
    findings: list[str] = []
    o3 = df[df["opt_level"] == "-O3"].set_index("label")
    fastest_label = o3["mean_ms"].idxmin()
    fastest_ms = o3.loc[fastest_label, "mean_ms"]
    fastest_sigma = float(o3.loc[fastest_label, "stdev_ms"])
    fastest_ci95 = float(o3.loc[fastest_label, "ci95_ms"])
    findings.append(
        f"Fastest -O3 variant: {fastest_label} at {fastest_ms:.3f} ms/frame "
        f"(sigma {fastest_sigma:.3f} ms, 95% CI +/- {fastest_ci95:.3f} ms)."
    )

    simd_ms = float(o3.loc["simd", "mean_ms"])
    arrays_ms = float(o3.loc["arrays", "mean_ms"])
    delta_pct = (arrays_ms - simd_ms) / arrays_ms * 100.0
    if delta_pct >= 0.0:
        findings.append(f"SIMD beats arrays at -O3 by {delta_pct:.2f}%.")
    else:
        findings.append(f"SIMD is still slower than arrays at -O3 by {abs(delta_pct):.2f}%.")

    representative_count = int(df["representative"].sum())
    findings.append(
        f"Representative groups: {representative_count}/{len(df)} according to the configured CV, checksum, and throttling checks."
    )

    if present_payload is not None:
        if present_payload.get("available", False) and present_df is not None and not present_df.empty:
            min_pct = float(present_df["mean_present_pct_total"].min())
            max_pct = float(present_df["mean_present_pct_total"].max())
            findings.append(
                f"A separate hidden-window measurement puts texture upload plus drawing at {min_pct:.1f}% to {max_pct:.1f}% of total frame time at -O3."
            )

    if gpu_payload is not None and gpu_payload.get("available", False) and gpu_df is not None and not gpu_df.empty:
        gpu_render_ms = float(gpu_df.iloc[0]["mean_render_ms"])
        ratio = gpu_render_ms / float(fastest_ms) if float(fastest_ms) > 0.0 else 0.0
        findings.append(
            f"A separate hidden-window GPU render benchmark measured {gpu_render_ms:.3f} ms/frame render-only, which is {ratio:.2f}x the fastest -O3 CPU frame time under this repository's CPU-buffer interface."
        )

    return findings

def summary_table(df: pd.DataFrame) -> str:
    lines = [
        r"\begin{longtable}{llllrrrrll}",
        r"Opt & Variant & Mean ms & Std ms & CV \% & Base \% & Prev \% & RSS MiB & Rep & Match \\ \hline",
        r"\endfirsthead",
        r"Opt & Variant & Mean ms & Std ms & CV \% & Base \% & Prev \% & RSS MiB & Rep & Match \\ \hline",
        r"\endhead",
    ]

    for _, row in df.iterrows():
        prev_pct = row["improvement_vs_previous_pct"]
        prev_text = "--" if pd.isna(prev_pct) else f"{prev_pct:+.1f}"
        lines.append(
            f"{tex_escape(row['opt_level'])} & "
            f"{tex_escape(row['label'])} & "
            f"{row['mean_ms']:.3f} & "
            f"{row['stdev_ms']:.3f} & "
            f"{row['cv_between_runs_pct']:.2f} & "
            f"{row['improvement_vs_baseline_pct']:+.1f} & "
            f"{prev_text} & "
            f"{row['peak_rss_mb']:.2f} & "
            f"{'yes' if row['representative'] else 'no'} & "
            f"{'yes' if row['checksum_matches_baseline'] else 'no'} \\\\"
        )

    lines.append(r"\end{longtable}")
    return "\n".join(lines)

def presentation_summary_table(df: pd.DataFrame | None) -> str | None:
    if df is None or df.empty:
        return None

    lines = [
        r"\begin{longtable}{lrrrrr}",
        r"Variant & n & Render ms & Present ms & Total ms & Present \% total \\ \hline",
        r"\endfirsthead",
        r"Variant & n & Render ms & Present ms & Total ms & Present \% total \\ \hline",
        r"\endhead",
    ]

    for _, row in df.iterrows():
        lines.append(
            f"{tex_escape(str(row['label']))} & "
            f"{int(row['run_count'])} & "
            f"{row['mean_render_ms']:.3f} & "
            f"{row['mean_present_ms']:.3f} & "
            f"{row['mean_total_ms']:.3f} & "
            f"{row['mean_present_pct_total']:.2f} \\\\"
        )

    lines.append(r"\end{longtable}")
    return "\n".join(lines)

def gpu_summary_table(df: pd.DataFrame | None) -> str | None:
    if df is None or df.empty:
        return None

    row = df.iloc[0]
    return "\n".join([
        r"\begin{longtable}{lrr}",
        r"Variant & n & Render ms \\ \hline",
        r"\endfirsthead",
        r"Variant & n & Render ms \\ \hline",
        r"\endhead",
        (
            f"{tex_escape(str(row['label']))} & "
            f"{int(row['run_count'])} & "
            f"{row['mean_render_ms']:.3f} \\\\"
        ),
        r"\end{longtable}",
    ])

def uncertainty_table(df: pd.DataFrame) -> str:
    lines = [
        r"\begin{longtable}{lllrrrrrr}",
        r"Opt & Variant & n & Mean ms & $-\sigma$ ms & $+\sigma$ ms & SEM ms & 95\% $\pm$ ms & Inacc. \% \\ \hline",
        r"\endfirsthead",
        r"Opt & Variant & n & Mean ms & $-\sigma$ ms & $+\sigma$ ms & SEM ms & 95\% $\pm$ ms & Inacc. \% \\ \hline",
        r"\endhead",
    ]

    for _, row in df.iterrows():
        lines.append(
            f"{tex_escape(row['opt_level'])} & "
            f"{tex_escape(row['label'])} & "
            f"{int(row['run_count'])} & "
            f"{row['mean_ms']:.3f} & "
            f"{row['sigma_minus_ms']:.3f} & "
            f"{row['sigma_plus_ms']:.3f} & "
            f"{row['sem_ms']:.3f} & "
            f"{row['ci95_ms']:.3f} & "
            f"{row['relative_inaccuracy_pct']:.2f} \\\\"
        )

    lines.append(r"\end{longtable}")
    return "\n".join(lines)

def presentation_uncertainty_table(df: pd.DataFrame | None) -> str | None:
    if df is None or df.empty:
        return None

    lines = [
        r"\begin{longtable}{llrrrrrrrr}",
        r"Variant & n & Render ms & $\sigma_R$ & Present ms & $\sigma_P$ & Total ms & $\sigma_T$ & 95\% $\pm_T$ & Inacc. \% \\ \hline",
        r"\endfirsthead",
        r"Variant & n & Render ms & $\sigma_R$ & Present ms & $\sigma_P$ & Total ms & $\sigma_T$ & 95\% $\pm_T$ & Inacc. \% \\ \hline",
        r"\endhead",
    ]

    for _, row in df.iterrows():
        lines.append(
            f"{tex_escape(row['label'])} & "
            f"{int(row['run_count'])} & "
            f"{row['mean_render_ms']:.3f} & "
            f"{row['stdev_render_ms']:.3f} & "
            f"{row['mean_present_ms']:.3f} & "
            f"{row['stdev_present_ms']:.3f} & "
            f"{row['mean_total_ms']:.3f} & "
            f"{row['stdev_total_ms']:.3f} & "
            f"{row['total_ci95_ms']:.3f} & "
            f"{row['total_relative_inaccuracy_pct']:.2f} \\\\"
        )

    lines.append(r"\end{longtable}")
    return "\n".join(lines)

def gpu_uncertainty_table(df: pd.DataFrame | None) -> str | None:
    if df is None or df.empty:
        return None

    row = df.iloc[0]
    return "\n".join([
        r"\begin{longtable}{lrrrrrr}",
        r"Variant & n & Render ms & $\sigma_R$ & SEM ms & 95\% $\pm_R$ & Inacc. \% \\ \hline",
        r"\endfirsthead",
        r"Variant & n & Render ms & $\sigma_R$ & SEM ms & 95\% $\pm_R$ & Inacc. \% \\ \hline",
        r"\endhead",
        (
            f"{tex_escape(str(row['label']))} & "
            f"{int(row['run_count'])} & "
            f"{row['mean_render_ms']:.3f} & "
            f"{row['stdev_render_ms']:.3f} & "
            f"{row['render_sem_ms']:.3f} & "
            f"{row['render_ci95_ms']:.3f} & "
            f"{row['render_relative_inaccuracy_pct']:.2f} \\\\"
        ),
        r"\end{longtable}",
    ])

def unavailable_note(payload: dict | None, label: str) -> str | None:
    if payload is None or payload.get("available", False):
        return None
    error = str(payload.get("error", "no error message recorded"))
    return f"{label} unavailable: {error}."

def write_report(payload: dict,
                 df: pd.DataFrame,
                 plots: list[Path],
                 present_payload: dict | None,
                 present_df: pd.DataFrame | None,
                 gpu_payload: dict | None,
                 gpu_df: pd.DataFrame | None) -> Path:
    config = payload["config"]
    scene = config["scene"]
    power_plan = config.get("power_plan", {})
    environment = payload["environment"]
    report_lscpu = wrap_verbatim_lines(sanitize_lscpu_report(str(environment["lscpu"])))
    report_cpupower = wrap_verbatim_lines(str(environment.get("cpupower_policy", "")))
    cooldown_seconds = config.get("cooldown_seconds", 0.0)
    present_summary = presentation_summary_table(present_df)
    present_uncertainty = presentation_uncertainty_table(present_df)
    gpu_summary = gpu_summary_table(gpu_df)
    gpu_uncertainty = gpu_uncertainty_table(gpu_df)
    present_unavailable = unavailable_note(present_payload, "Hidden-window benchmark")
    gpu_unavailable = unavailable_note(gpu_payload, "GPU benchmark")

    plot_blocks = []
    for plot in plots:
        plot_blocks.append(
            "\n".join([
                r"\begin{figure}[H]",
                r"\centering",
                rf"\includegraphics[width=0.95\linewidth]{{../{plot.relative_to(PROJECT_ROOT)}}}",
                r"\end{figure}",
                "",
            ])
        )
    plot_includes = "\n".join(plot_blocks)

    summary_sections = [
        "\n".join([
            r"\subsection*{CPU Compute}",
            summary_table(df),
        ]),
    ]
    if present_summary is not None:
        summary_sections.append(
            "\n".join([
                r"\subsection*{Hidden-Window Presentation}",
                present_summary,
            ])
        )
    elif present_unavailable is not None:
        summary_sections.append(
            "\n".join([
                r"\subsection*{Hidden-Window Presentation}",
                tex_escape(present_unavailable),
            ])
        )
    if gpu_summary is not None:
        summary_sections.append(
            "\n".join([
                r"\subsection*{GPU Render}",
                gpu_summary,
            ])
        )
    elif gpu_unavailable is not None:
        summary_sections.append(
            "\n".join([
                r"\subsection*{GPU Render}",
                tex_escape(gpu_unavailable),
            ])
        )
    summary_section = "\n\n".join(summary_sections)

    uncertainty_sections = [
        "\n".join([
            r"\subsection*{CPU Compute}",
            uncertainty_table(df),
        ]),
    ]
    if present_uncertainty is not None:
        uncertainty_sections.append(
            "\n".join([
                r"\subsection*{Hidden-Window Presentation}",
                present_uncertainty,
            ])
        )
    elif present_unavailable is not None:
        uncertainty_sections.append(
            "\n".join([
                r"\subsection*{Hidden-Window Presentation}",
                tex_escape(present_unavailable),
            ])
        )
    if gpu_uncertainty is not None:
        uncertainty_sections.append(
            "\n".join([
                r"\subsection*{GPU Render}",
                gpu_uncertainty,
            ])
        )
    elif gpu_unavailable is not None:
        uncertainty_sections.append(
            "\n".join([
                r"\subsection*{GPU Render}",
                tex_escape(gpu_unavailable),
            ])
        )
    uncertainty_section = "\n\n".join(uncertainty_sections)

    report_tex = REPORT_DIR / "mandelbrot_benchmark_report.tex"
    content = f"""
\\documentclass[11pt]{{article}}
\\usepackage[margin=1in]{{geometry}}
\\usepackage{{amsmath}}
\\usepackage{{graphicx}}
\\usepackage{{float}}
\\usepackage{{longtable}}
\\usepackage{{verbatim}}
\\title{{Mandelbrot Float Renderer Benchmark Report}}
\\date{{{tex_escape(environment["timestamp_utc"])}}}
\\begin{{document}}
\\maketitle

\\section*{{Method}}
This report benchmarks the CPU renderers in this repository with a fixed scene centered at
({scene["center_x"]}, {scene["center_y"]}) and zoom {scene["zoom"]}. Each configuration runs
{config["runs_per_variant"]} times, with {config["warmup"]} warmup frames and {config["frames"]}
measured frames per run. Single-threaded variants are pinned to CPU list
\\texttt{{{tex_escape(environment["single_affinity"])}}}; the threaded renderer is pinned to
\\texttt{{{tex_escape(environment["threaded_affinity"])}}}. Telemetry is sampled every
{config["sample_interval_s"]:.2f} seconds, with a configured cooldown of
{cooldown_seconds:.1f} seconds between runs.
The benchmark shell requested governor \\texttt{{{tex_escape(str(power_plan.get("governor", "")))}}}
{f' and fixed frequency \\texttt{{{tex_escape(str(power_plan.get("frequency", "")))}}}' if power_plan.get("frequency") else ''}
{f' with min/max \\texttt{{{tex_escape(str(power_plan.get("min_frequency", "")))}}} / \\texttt{{{tex_escape(str(power_plan.get("max_frequency", "")))}}}' if (power_plan.get("min_frequency") or power_plan.get("max_frequency")) and not power_plan.get("frequency") else ''}
before running the measurements.

Representative data requires at least {config["representative_rule"]["min_runs"]} runs, matching
checksums, at least {config["representative_rule"]["min_frames_per_run"]} measured frames per run,
no thermal-throttle counter increments, and a between-run coefficient of variation no higher than
{config["representative_rule"]["max_cv_pct"]}\\%.

\\section*{{Summary Table}}
{summary_section}

\\section*{{Uncertainty}}
Repeated-run uncertainty is reported for CPU, hidden-window, and GPU measurements using:
\\[
\\sigma = \\sqrt{{\\frac{{1}}{{n - 1}} \\sum_{{i=1}}^{{n}} (x_i - \\bar{{x}})^2}}
\\]
\\[
\\mathrm{{SEM}} = \\frac{{\\sigma}}{{\\sqrt{{n}}}}, \\quad
\\mathrm{{CI}}_{{95}} = t_{{0.975, n-1}} \\cdot \\frac{{\\sigma}}{{\\sqrt{{n}}}}, \\quad
\\mathrm{{Inacc.\\%}} = 100 \\cdot \\frac{{\\mathrm{{CI}}_{{95}}}}{{\\bar{{x}}}}
\\]

{uncertainty_section}

\\section*{{Environment}}
BogoMIPS in \\texttt{{lscpu}} is the kernel delay-loop calibration value, not a Mandelbrot performance score.
\\begin{{verbatim}}
{report_cpupower}
\\end{{verbatim}}
\\begin{{verbatim}}
{report_lscpu}
\\end{{verbatim}}

\\section*{{Plots}}
{plot_includes}

\\end{{document}}
"""
    report_tex.write_text(content.strip() + "\n", encoding="utf-8")
    return report_tex

def compile_pdf(report_tex: Path) -> Path | None:
    if not shutil.which("pdflatex"):
        print("pdflatex not found; wrote TeX only")
        return None

    cmd = [
        "pdflatex",
        "-interaction=nonstopmode",
        "-halt-on-error",
        report_tex.name,
    ]
    for _ in range(2):
        completed = subprocess.run(
            cmd,
            cwd=REPORT_DIR,
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr or completed.stdout)

    return REPORT_DIR / "mandelbrot_benchmark_report.pdf"

def main() -> int:
    ensure_dirs()
    payload         = load_payload()
    present_payload = load_presentation_payload()
    gpu_payload     = load_gpu_payload()
    df              = groups_frame(payload)
    present_df      = presentation_frame(present_payload)
    gpu_df          = gpu_frame(gpu_payload)
    frame_df        = load_o3_frame_times(payload)

    all_opts_plot     = plot_all_opts(df)
    o3_focus_plot     = plot_o3_focus(df)
    o3_box_plot       = plot_o3_boxplot(frame_df)
    o3_telemetry_plot = plot_o3_telemetry(df)

    plots = [all_opts_plot, o3_focus_plot, o3_telemetry_plot]
    if o3_box_plot is not None:
        plots.append(o3_box_plot)
    if present_df is not None and not present_df.empty:
        plots.append(plot_presentation_overhead(present_df))
    if gpu_df is not None and not gpu_df.empty:
        plots.append(plot_gpu_vs_fastest_cpu(df, gpu_df))

    report_tex = write_report(
        payload,
        df,
        plots,
        present_payload,
        present_df,
        gpu_payload,
        gpu_df,
    )
    report_pdf = compile_pdf(report_tex)

    print(f"wrote {report_tex.relative_to(PROJECT_ROOT)}")
    if report_pdf is not None:
        print(f"wrote {report_pdf.relative_to(PROJECT_ROOT)}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
