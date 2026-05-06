#include "render_floats_sse_common.h"

const char *GetRendererName(void)
{
    return "render_floats_sse_no-threads_no-acel";
}

void RenderMandelbrot(Color *buffer, int width, int height,
                      float centerX, float centerY, float zoom)
{
    RenderMandelbrotRowsSSE(buffer, width, height, 0, height, centerX, centerY, zoom);
}
