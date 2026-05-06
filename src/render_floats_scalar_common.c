#include <math.h>

#include "render_floats_scalar_common.h"
#include "utils/utils.h"

float CalcMandelbrotScalar(float x0, float y0)
{
    float x = 0.0f;
    float y = 0.0f;

    for (int n = 0; n < MAX_ITERS; ++n)
    {
        float xx = x * x - y * y + x0;
        float yy = 2.0f * x * y + y0;
        float dist = xx * xx + yy * yy;

        if (dist > 100.0f)
        {
            return (float)n + 1.0f - log2f(log2f(sqrtf(dist)));
        }

        x = xx;
        y = yy;
    }

    return (float)MAX_ITERS;
}
