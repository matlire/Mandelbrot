#ifndef UTILS_H
#define UTILS_H

#include <raylib.h>
#include <math.h>

#define MAX_ITERS 100

float Clamp01   (float x);
float Fract     (float x);
Color LerpColor (Color a, Color b, float t);

Color PaletteGradient(float t);
Color ColorFromMu    (float mu);

#endif
