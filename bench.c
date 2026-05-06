#include "src/bench/bench_common.h"
#include "src/render.h"

#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <sys/resource.h>

#include <raylib.h>

static Color buffer[MANDELBROT_WINDOW_W * MANDELBROT_WINDOW_H] = { 0 };

typedef struct
{
    Texture2D texture;
    int       enabled;
} PresentState;

static void DrawFrame(Texture2D texture)
{
    BeginDrawing();
    ClearBackground(BLACK);

    DrawTexturePro(
        texture,
        (Rectangle){ 0, 0, (float)texture.width, (float)texture.height },
        (Rectangle){ 0, 0, (float)GetRenderWidth(), (float)GetRenderHeight() },
        (Vector2){ 0, 0 },
        0.0f,
        WHITE
    );

    DrawText(GetRendererName(), 10, 10, 20, WHITE);
    DrawText("Benchmark: compute + present", 10, 36, 20, WHITE);
    EndDrawing();
}

static int InitPresentState(PresentState *state)
{
    Image img = {
        .data    = buffer,
        .width   = MANDELBROT_WINDOW_W,
        .height  = MANDELBROT_WINDOW_H,
        .mipmaps = 1,
        .format  = PIXELFORMAT_UNCOMPRESSED_R8G8B8A8,
    };

    SetConfigFlags(FLAG_WINDOW_HIDDEN);
    InitWindow(MANDELBROT_WINDOW_W, MANDELBROT_WINDOW_H, "Mandelbrot present benchmark");
    if (!IsWindowReady())
    {
        fprintf(stderr, "failed to initialize hidden benchmark window\n");
        return 0;
    }

    SetTargetFPS(0);

    state->texture = LoadTextureFromImage(img);
    if (state->texture.id == 0)
    {
        fprintf(stderr, "failed to create benchmark texture\n");
        CloseWindow();
        return 0;
    }

    SetTextureFilter(state->texture, TEXTURE_FILTER_POINT);
    state->enabled = 1;
    return 1;
}

static void DestroyPresentState(PresentState *state)
{
    if (!state->enabled)
        return;

    UnloadTexture(state->texture);
    CloseWindow();
    state->texture = (Texture2D){ 0 };
    state->enabled = 0;
}

int main(int argc, char **argv)
{
    BenchArgs args = BenchParseArgs(argc, argv, BENCH_KIND_RENDER, "bench.csv", 300, 30);
    int with_present = args.kind == BENCH_KIND_PRESENT;

    FILE *out = BenchOpenCsv(args.out_path);
    if (out == NULL)
        return 1;

    PresentState present = { 0 };
    if (with_present && !InitPresentState(&present))
    {
        fclose(out);
        return 1;
    }

    if (with_present)
        fprintf(out, "frame,render_ns,present_ns,total_ns,total_ticks\n");
    else
        fprintf(out, "frame,ticks,ns\n");

    for (int i = 0; i < args.warmup; ++i)
    {
        RenderMandelbrot(buffer,
                         MANDELBROT_WINDOW_W,
                         MANDELBROT_WINDOW_H,
                         args.center_x,
                         args.center_y,
                         args.zoom);

        if (with_present)
        {
            UpdateTexture(present.texture, buffer);
            DrawFrame(present.texture);
        }
    }

    U64Stats ticks      = BenchStatsInit();
    U64Stats ns         = BenchStatsInit();
    U64Stats present_ns = BenchStatsInit();
    U64Stats total_ns   = BenchStatsInit();

    for (int i = 0; i < args.frames; ++i)
    {
        uint64_t c0 = BenchReadTicksBegin();
        uint64_t t0 = BenchNowNs();

        RenderMandelbrot(buffer,
                         MANDELBROT_WINDOW_W,
                         MANDELBROT_WINDOW_H,
                         args.center_x,
                         args.center_y,
                         args.zoom);

        uint64_t t1 = BenchNowNs();

        if (with_present)
        {
            UpdateTexture(present.texture, buffer);
            DrawFrame(present.texture);
        }

        uint64_t t2 = BenchNowNs();
        uint64_t c1 = BenchReadTicksEnd();

        uint64_t frame_ticks      = c1 - c0;
        uint64_t frame_ns         = t1 - t0;
        uint64_t frame_present_ns = t2 - t1;
        uint64_t frame_total_ns   = t2 - t0;

        if (with_present)
        {
            fprintf(out,
                    "%d,%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",%" PRIu64 "\n",
                    i,
                    frame_ns,
                    frame_present_ns,
                    frame_total_ns,
                    frame_ticks);
        }
        else
            fprintf(out, "%d,%" PRIu64 ",%" PRIu64 "\n", i, frame_ticks, frame_ns);

        BenchUpdateStats(&ticks, frame_ticks);
        BenchUpdateStats(&ns, frame_ns);
        if (with_present)
        {
            BenchUpdateStats(&present_ns, frame_present_ns);
            BenchUpdateStats(&total_ns, frame_total_ns);
        }

        if ((i + 1) % 100 == 0 || (i + 1) == args.frames)
        {
            fprintf(stderr,
                    "\r%s%s: %d/%d",
                    GetRendererName(),
                    with_present ? " present" : "",
                    i + 1,
                    args.frames);
            fflush(stderr);
        }
    }

    fprintf(stderr, "\n");
    fclose(out);

    struct rusage usage;
    getrusage(RUSAGE_SELF, &usage);

    double mean_ticks = (double)ticks.sum / (double)args.frames;
    double mean_ns    = (double)ns.sum / (double)args.frames;

    BenchPrintRunConfig(GetRendererName(), &args);
    if (with_present)
    {
        double mean_present_ns = (double)present_ns.sum / (double)args.frames;
        double mean_total_ns   = (double)total_ns.sum / (double)args.frames;

        printf("mean_render_ns=%.0f\n", mean_ns);
        printf("mean_present_ns=%.0f\n", mean_present_ns);
        printf("mean_total_ns=%.0f\n", mean_total_ns);
        printf("mean_render_ms=%.6f\n", mean_ns / 1e6);
        printf("mean_present_ms=%.6f\n", mean_present_ns / 1e6);
        printf("mean_total_ms=%.6f\n", mean_total_ns / 1e6);
        printf("present_pct_total=%.6f\n", mean_total_ns > 0.0 ? 100.0 * mean_present_ns / mean_total_ns : 0.0);
        printf("present_pct_render=%.6f\n", mean_ns > 0.0 ? 100.0 * mean_present_ns / mean_ns : 0.0);
        printf("mean_total_ticks=%.0f\n", mean_ticks);
    }
    else
    {
        printf("mean_ticks=%.0f\n", mean_ticks);
        printf("min_ticks=%" PRIu64 "\n", ticks.min);
        printf("max_ticks=%" PRIu64 "\n", ticks.max);
        printf("mean_ns=%.0f\n", mean_ns);
        printf("min_ns=%" PRIu64 "\n", ns.min);
        printf("max_ns=%" PRIu64 "\n", ns.max);
        printf("mean_ms=%.6f\n", mean_ns / 1e6);
        printf("fps=%.6f\n", 1e9 / mean_ns);
    }

    BenchPrintResourceSummary(&usage, buffer, sizeof(buffer));
    DestroyPresentState(&present);

    return 0;
}
