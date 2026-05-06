#include <stdlib.h>
#include <string.h>

#include <raylib.h>

#include "render.h"
#include "utils/utils.h"

static Shader g_shader = { 0 };
static RenderTexture2D g_target = { 0 };
static int g_w = 0;
static int g_h = 0;
static int g_ready = 0;
static int g_atexit_registered = 0;
static int g_loc_resolution = -1;
static int g_loc_center = -1;
static int g_loc_zoom = -1;
static int g_loc_max_iter = -1;

typedef struct
{
    const char *vertex_path;
    const char *fragment_path;
} ShaderPathPair;

static const ShaderPathPair kShaderCandidates[] = {
    { "src/shaders/mandelbrot_gpu.vert", "src/shaders/mandelbrot_gpu.frag" },
    { "../src/shaders/mandelbrot_gpu.vert", "../src/shaders/mandelbrot_gpu.frag" },
};

static void ShutdownGpuRenderer(void)
{
    if (g_target.id != 0)
    {
        UnloadRenderTexture(g_target);
        g_target = (RenderTexture2D){ 0 };
    }

    if (g_shader.id != 0)
    {
        UnloadShader(g_shader);
        g_shader = (Shader){ 0 };
    }

    g_loc_resolution = -1;
    g_loc_center = -1;
    g_loc_zoom = -1;
    g_loc_max_iter = -1;
    g_ready = 0;
    g_w = 0;
    g_h = 0;
}

static int FindShaderPair(const char **vertex_path, const char **fragment_path)
{
    size_t candidate_count = sizeof(kShaderCandidates) / sizeof(kShaderCandidates[0]);
    for (size_t i = 0; i < candidate_count; ++i)
    {
        if (!FileExists(kShaderCandidates[i].vertex_path))
        {
            continue;
        }
        if (!FileExists(kShaderCandidates[i].fragment_path))
        {
            continue;
        }

        *vertex_path = kShaderCandidates[i].vertex_path;
        *fragment_path = kShaderCandidates[i].fragment_path;
        return 1;
    }

    return 0;
}

static int EnsureGpuRenderer(int width, int height)
{
    if (g_ready && g_w == width && g_h == height)
    {
        return 1;
    }

    ShutdownGpuRenderer();

    const char *vertex_path = NULL;
    const char *fragment_path = NULL;
    if (!FindShaderPair(&vertex_path, &fragment_path))
    {
        return 0;
    }

    g_shader = LoadShader(vertex_path, fragment_path);
    if (g_shader.id == 0)
    {
        return 0;
    }

    g_target = LoadRenderTexture(width, height);
    if (g_target.id == 0)
    {
        UnloadShader(g_shader);
        g_shader = (Shader){ 0 };
        return 0;
    }

    g_loc_resolution = GetShaderLocation(g_shader, "uResolution");
    g_loc_center = GetShaderLocation(g_shader, "uCenter");
    g_loc_zoom = GetShaderLocation(g_shader, "uZoom");
    g_loc_max_iter = GetShaderLocation(g_shader, "uMaxIter");

    g_w = width;
    g_h = height;
    g_ready = 1;

    if (!g_atexit_registered)
    {
        atexit(ShutdownGpuRenderer);
        g_atexit_registered = 1;
    }
    return 1;
}

const char *GetRendererName(void)
{
    return "render_gpu_glsl_accel";
}

void RenderMandelbrot(Color *buffer, int width, int height,
                      float centerX, float centerY, float zoom)
{
    if (!IsWindowReady())
    {
        memset(buffer, 0, (size_t)width * (size_t)height * sizeof(Color));
        return;
    }

    if (!EnsureGpuRenderer(width, height))
    {
        memset(buffer, 0, (size_t)width * (size_t)height * sizeof(Color));
        return;
    }

    float resolution[2] = { (float)width, (float)height };
    float center[2] = { centerX, centerY };
    int max_iter = MAX_ITERS;

    SetShaderValue(g_shader, g_loc_resolution, resolution, SHADER_UNIFORM_VEC2);
    SetShaderValue(g_shader, g_loc_center, center, SHADER_UNIFORM_VEC2);
    SetShaderValue(g_shader, g_loc_zoom, &zoom, SHADER_UNIFORM_FLOAT);
    SetShaderValue(g_shader, g_loc_max_iter, &max_iter, SHADER_UNIFORM_INT);

    BeginTextureMode(g_target);
    ClearBackground(BLACK);

    BeginShaderMode(g_shader);
    DrawRectangle(0, 0, width, height, WHITE);
    EndShaderMode();

    EndTextureMode();

    Image img = LoadImageFromTexture(g_target.texture);
    ImageFlipVertical(&img);

    if (img.data != NULL)
    {
        memcpy(buffer, img.data, (size_t)width * (size_t)height * sizeof(Color));
        UnloadImage(img);
    }
    else
    {
        memset(buffer, 0, (size_t)width * (size_t)height * sizeof(Color));
    }
}
