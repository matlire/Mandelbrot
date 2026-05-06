#include "utils.h"

float Clamp01(float x)
{
    if (x < 0.0) return 0.0;
    if (x > 1.0) return 1.0;
    return x;
}

float Fract(float x)
{
    return x - floorf(x);
}

Color LerpColor(Color a, Color b, float t)
{
    t = Clamp01(t);

    Color c = { 0 };
    c.r = (unsigned char)(a.r + (b.r - a.r) * t);
    c.g = (unsigned char)(a.g + (b.g - a.g) * t);
    c.b = (unsigned char)(a.b + (b.b - a.b) * t);
    c.a = 255;
    return c;
}

Color PaletteGradient(float t)
{
    static const Color stops[] = {
        {  5,   7,  20, 255 },
        { 32,  18,  77, 255 },
        { 88,  28, 135, 255 },
        {180,  55, 120, 255 },
        {255, 140,  80, 255 },
        {255, 210, 110, 255 },
        {255, 245, 220, 255 }
    };

    const int count = (int)(sizeof(stops) / sizeof(stops[0]));

    t = Clamp01(t);

    if (t <= 0.0) return stops[0];
    if (t >= 1.0) return stops[count - 1];

    float scaled = t * (count - 1);
    int i = (int)scaled;
    float localT = scaled - (float)i;

    return LerpColor(stops[i], stops[i + 1], localT);
}

Color ColorFromMu(float mu)
{
    if (mu >= (float)MAX_ITERS)
        return (Color){ 4, 4, 10, 255 };

    float t = Fract(mu * 0.035f);
    t = sqrtf(t);
    return PaletteGradient(t);
}

