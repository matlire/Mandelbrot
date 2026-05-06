#ifndef MANDELBROT_RENDER_H
#define MANDELBROT_RENDER_H

#include <raylib.h>

const char *GetRendererName(void);

void RenderMandelbrot(Color *buffer, int width, int height,
                      float centerX, float centerY, float zoom);

#endif
