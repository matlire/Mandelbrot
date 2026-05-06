#include "render.h"
#include "render_floats_scalar_common.h"
#include "utils/utils.h"

const char *GetRendererName(void)
{
    return "render_floats_no-sse_no-threads_no-acel";
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

        for (int px = 0; px < width; ++px)
        {
            float x0 = startX + (float)px * dx;
            float mu = CalcMandelbrotScalar(x0, y0);

            buffer[py * width + px] = ColorFromMu(mu);
        }
    }
}
