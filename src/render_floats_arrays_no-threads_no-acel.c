#include <math.h>

#include "render.h"
#include "render_floats_scalar_common.h"
#include "utils/utils.h"

typedef struct
{
    float lane[4];
} Vec4f;

typedef struct
{
    int lane[4];
} Vec4i;

static inline Vec4f V4Set(float a0, float a1, float a2, float a3)
{
    Vec4f r = { { a0, a1, a2, a3 } };
    return r;
}

static inline Vec4f V4Set1(float a)
{
    Vec4f r = { { a, a, a, a } };
    return r;
}

static inline Vec4f V4Add(Vec4f a, Vec4f b)
{
    Vec4f r;
    for (int i = 0; i < 4; ++i) r.lane[i] = a.lane[i] + b.lane[i];
    return r;
}

static inline Vec4f V4Sub(Vec4f a, Vec4f b)
{
    Vec4f r;
    for (int i = 0; i < 4; ++i) r.lane[i] = a.lane[i] - b.lane[i];
    return r;
}

static inline Vec4f V4Mul(Vec4f a, Vec4f b)
{
    Vec4f r;
    for (int i = 0; i < 4; ++i) r.lane[i] = a.lane[i] * b.lane[i];
    return r;
}

static inline Vec4f V4Select(Vec4f oldValue, Vec4f newValue, Vec4i mask)
{
    Vec4f r;
    for (int i = 0; i < 4; ++i)
        r.lane[i] = mask.lane[i] ? newValue.lane[i] : oldValue.lane[i];
    return r;
}

static inline int V4Any(Vec4i mask)
{
    return mask.lane[0] | mask.lane[1] | mask.lane[2] | mask.lane[3];
}

static void CalcMandelbrot4_Array(float x0Base, float y0, float dx, float outMu[4])
{
    const Vec4f x0 = V4Set(
        x0Base,
        x0Base + dx,
        x0Base + 2.0f * dx,
        x0Base + 3.0f * dx
    );

    const Vec4f y0v = V4Set1(y0);
    const Vec4f two = V4Set1(2.0f);

    Vec4f x = V4Set1(0.0f);
    Vec4f y = V4Set1(0.0f);

    Vec4i active = { { -1, -1, -1, -1 } };

    int   escapeIter[4] = { -1, -1, -1, -1 };
    float escapeMag[4]  = {  0,  0,  0,  0 };

    for (int n = 0; n < MAX_ITERS; ++n)
    {
        Vec4f x2 = V4Mul(x, x);
        Vec4f y2 = V4Mul(y, y);
        Vec4f xy = V4Mul(x, y);

        Vec4f xx = V4Add(V4Sub(x2, y2), x0);
        Vec4f yy = V4Add(V4Mul(two, xy), y0v);

        Vec4f dist = V4Add(V4Mul(xx, xx), V4Mul(yy, yy));

        Vec4i stillActive = { { 0, 0, 0, 0 } };

        for (int i = 0; i < 4; ++i)
        {
            if (active.lane[i] && dist.lane[i] <= 100.0f)
                stillActive.lane[i] = -1;
            else if (active.lane[i])
            {
                escapeIter[i] = n;
                escapeMag[i]  = sqrtf(dist.lane[i]);
            }
        }

        x = V4Select(x, xx, stillActive);
        y = V4Select(y, yy, stillActive);

        active = stillActive;

        if (!V4Any(active))
            break;
    }

    for (int i = 0; i < 4; ++i)
    {
        if (escapeIter[i] < 0)
            outMu[i] = (float)MAX_ITERS;
        else
            outMu[i] = (float)escapeIter[i] + 1.0f - log2f(log2f(escapeMag[i]));
    }
}

const char *GetRendererName(void)
{
    return "render_floats_arrays_no-threads_no-acel";
}

void RenderMandelbrot(Color *buffer, int width, int height,
                      float centerX, float centerY, float zoom)
{
    const float aspect = (float)width / (float)height;
    const float scaleX = 4.0f * aspect / zoom;
    const float scaleY = 4.0f / zoom;

    const float dx = scaleX / (float)width;
    const float dy = scaleY / (float)height;

    const float startX = centerX - 0.5f * scaleX;
    const float startY = centerY - 0.5f * scaleY;

    for (int py = 0; py < height; ++py)
    {
        float y0 = startY + (float)py * dy;

        int px = 0;
        for (; px <= width - 4; px += 4)
        {
            float mu[4];
            float x0Base = startX + (float)px * dx;

            CalcMandelbrot4_Array(x0Base, y0, dx, mu);

            buffer[py * width + (px + 0)] = ColorFromMu(mu[0]);
            buffer[py * width + (px + 1)] = ColorFromMu(mu[1]);
            buffer[py * width + (px + 2)] = ColorFromMu(mu[2]);
            buffer[py * width + (px + 3)] = ColorFromMu(mu[3]);
        }

        for (; px < width; ++px)
        {
            float x0 = startX + (float)px * dx;
            float mu = CalcMandelbrotScalar(x0, y0);

            buffer[py * width + px] = ColorFromMu(mu);
        }
    }
}
