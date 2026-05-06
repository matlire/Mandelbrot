#include <immintrin.h>
#include <math.h>
#include <stddef.h>

#include "render_floats_scalar_common.h"
#include "render_floats_sse_common.h"
#include "utils/utils.h"

static __m256 SelectPS(__m256 old_value, __m256 new_value, __m256 mask)
{
    return _mm256_blendv_ps(old_value, new_value, mask);
}

static void CalcMandelbrot8SIMD(__m256 x0, __m256 y0v, float out_mu[8])
{
    const __m256 max_dist = _mm256_set1_ps(100.0f);

    __m256 x = _mm256_setzero_ps();
    __m256 y = _mm256_setzero_ps();

    __m256 active_mask = _mm256_castsi256_ps(_mm256_set1_epi32(-1));
    __m256 escape_iter = _mm256_set1_ps(-1.0f);
    __m256 escape_dist = _mm256_setzero_ps();

    for (int n = 0; n < MAX_ITERS; ++n)
    {
        __m256 x2 = _mm256_mul_ps(x, x);
        __m256 y2 = _mm256_mul_ps(y, y);

        __m256 xx = _mm256_add_ps(_mm256_sub_ps(x2, y2), x0);
        __m256 yy = _mm256_fmadd_ps(_mm256_add_ps(x, x), y, y0v);
        __m256 dist = _mm256_fmadd_ps(yy, yy, _mm256_mul_ps(xx, xx));

        __m256 still_active = _mm256_and_ps(
            active_mask,
            _mm256_cmp_ps(dist, max_dist, _CMP_LE_OQ)
        );
        __m256 escaped_now = _mm256_andnot_ps(still_active, active_mask);

        escape_iter = SelectPS(escape_iter, _mm256_set1_ps((float)n + 1.0f), escaped_now);
        escape_dist = SelectPS(escape_dist, dist, escaped_now);

        x = SelectPS(x, xx, still_active);
        y = SelectPS(y, yy, still_active);
        active_mask = still_active;

        if (_mm256_movemask_ps(active_mask) == 0)
        {
            break;
        }
    }

    float iter_lane[8];
    float dist_lane[8];

    _mm256_storeu_ps(iter_lane, escape_iter);
    _mm256_storeu_ps(dist_lane, escape_dist);

    for (int i = 0; i < 8; ++i)
    {
        if (iter_lane[i] < 0.0f)
        {
            out_mu[i] = (float)MAX_ITERS;
            continue;
        }

        out_mu[i] = iter_lane[i] - log2f(log2f(sqrtf(dist_lane[i])));
    }
}

void RenderMandelbrotRowsSSE(Color *buffer,
                             int width,
                             int height,
                             int y_begin,
                             int y_end,
                             float centerX,
                             float centerY,
                             float zoom)
{
    const float aspect = (float)width / (float)height;
    const float scaleX = 4.0f * aspect / zoom;
    const float scaleY = 4.0f / zoom;

    const float dx = scaleX / (float)width;
    const float dy = scaleY / (float)height;
    const float startX = centerX - 0.5f * scaleX;
    const float startY = centerY - 0.5f * scaleY;

    for (int py = y_begin; py < y_end; ++py)
    {
        float y0 = startY + (float)py * dy;

        int px = 0;
        for (; px <= width - 8; px += 8)
        {
            float x0_base = startX + (float)px * dx;
            __m256 x0 = _mm256_setr_ps(
                x0_base,
                x0_base + dx,
                x0_base + 2.0f * dx,
                x0_base + 3.0f * dx,
                x0_base + 4.0f * dx,
                x0_base + 5.0f * dx,
                x0_base + 6.0f * dx,
                x0_base + 7.0f * dx
            );
            __m256 y0v = _mm256_set1_ps(y0);
            float mu[8];

            CalcMandelbrot8SIMD(x0, y0v, mu);

            size_t row_offset = (size_t)py * (size_t)width + (size_t)px;
            buffer[row_offset + 0] = ColorFromMu(mu[0]);
            buffer[row_offset + 1] = ColorFromMu(mu[1]);
            buffer[row_offset + 2] = ColorFromMu(mu[2]);
            buffer[row_offset + 3] = ColorFromMu(mu[3]);
            buffer[row_offset + 4] = ColorFromMu(mu[4]);
            buffer[row_offset + 5] = ColorFromMu(mu[5]);
            buffer[row_offset + 6] = ColorFromMu(mu[6]);
            buffer[row_offset + 7] = ColorFromMu(mu[7]);
        }

        for (; px < width; ++px)
        {
            float x_scalar = startX + (float)px * dx;
            float mu = CalcMandelbrotScalar(x_scalar, y0);
            buffer[(size_t)py * (size_t)width + (size_t)px] = ColorFromMu(mu);
        }
    }
}
