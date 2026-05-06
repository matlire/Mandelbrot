# Mandelbrot

This project renders the Mandelbrot set with several CPU and GPU implementations, then benchmarks the CPU variants under controlled conditions.

The main goal is to compare different ways to compute the same Mandelbrot image.

## Useful commands

Commands assume Nix dev shell:

```bash
nix develop
```

Or start scripts with `nix develop -c`.

### Interactive Viewer

Build one renderer with the normal windowed app:

```bash
./compile.sh --interactive -f src/render_floats_sse_threads_acel.c -O3
./dist/render_floats_sse_threads_acel
```

Controls:

- `W` `A` `S` `D` move
- `Q` zoom out
- `E` zoom in

### Automated Benchmark


```bash
./bench.sh
```

Main outputs:

- `report/results.json` for CPU suite
- `report/presentation_results.json` for present suite
- `report/gpu_results.json` for GPU suite
- `img/plots/` for generated figures

### Common Environment Variables

CPU suite:

- `RUNS`, `FRAMES`, `WARMUP`
- `OPT_LEVELS`
- `SINGLE_AFFINITY`, `THREAD_AFFINITY`
- `CENTER_X`, `CENTER_Y`, `ZOOM`

Present suite:

- `PRESENT_RUNS`, `PRESENT_FRAMES`, `PRESENT_WARMUP`, `PRESENT_OPT_LEVEL`

GPU suite:

- `GPU_RUNS`, `GPU_FRAMES`, `GPU_WARMUP`, `GPU_OPT_LEVEL`

Bench shell:

- `BENCH_SKIP_CPUPOWER=1` disables temporary cpupower changes
- `BENCH_GOVERNOR`, `BENCH_FREQUENCY`, `BENCH_MIN_FREQ`, `BENCH_MAX_FREQ` tune the temporary CPU policy
