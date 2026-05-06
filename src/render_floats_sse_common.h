#ifndef MANDELBROT_RENDER_FLOATS_SSE_COMMON_H
#define MANDELBROT_RENDER_FLOATS_SSE_COMMON_H

#include "render.h"

void RenderMandelbrotRowsSSE(Color *buffer,
                             int width,
                             int height,
                             int y_begin,
                             int y_end,
                             float centerX,
                             float centerY,
                             float zoom);

#endif
