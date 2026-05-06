#version 330

out vec4 finalColor;

uniform vec2  uResolution;
uniform vec2  uCenter;
uniform float uZoom;
uniform int   uMaxIter;

vec3 lerp3(vec3 a, vec3 b, float t)
{
    return mix(a, b, clamp(t, 0.0, 1.0));
}

vec3 palette(float t)
{
    const vec3 c0 = vec3(5.0,   7.0,   20.0)  / 255.0;
    const vec3 c1 = vec3(32.0,  18.0,  77.0)  / 255.0;
    const vec3 c2 = vec3(88.0,  28.0,  135.0) / 255.0;
    const vec3 c3 = vec3(180.0, 55.0,  120.0) / 255.0;
    const vec3 c4 = vec3(255.0, 140.0,  80.0) / 255.0;
    const vec3 c5 = vec3(255.0, 210.0, 110.0) / 255.0;
    const vec3 c6 = vec3(255.0, 245.0, 220.0) / 255.0;

    t = clamp(t, 0.0, 1.0);
    if (t <= 0.0) return c0;
    if (t >= 1.0) return c6;

    float scaled = t * 6.0;
    int i = int(floor(scaled));
    float ft = fract(scaled);

    if (i == 0) return lerp3(c0, c1, ft);
    if (i == 1) return lerp3(c1, c2, ft);
    if (i == 2) return lerp3(c2, c3, ft);
    if (i == 3) return lerp3(c3, c4, ft);
    if (i == 4) return lerp3(c4, c5, ft);
    return lerp3(c5, c6, ft);
}

void main()
{
    vec2 uv = gl_FragCoord.xy / uResolution.xy;
    uv = uv * 2.0 - 1.0;
    uv.x *= uResolution.x / uResolution.y;

    vec2 c = uCenter + uv * (2.0 / uZoom);
    vec2 z = vec2(0.0);

    float mu = float(uMaxIter);
    bool escaped = false;

    for (int i = 0; i < uMaxIter; ++i)
    {
        float x = z.x * z.x - z.y * z.y + c.x;
        float y = 2.0 * z.x * z.y + c.y;
        z = vec2(x, y);

        float r2 = dot(z, z);
        if (r2 > 100.0)
        {
            float dist = sqrt(r2);
            mu = float(i) + 1.0 - log2(log2(max(dist, 1.000001)));
            escaped = true;
            break;
        }
    }

    if (!escaped)
    {
        finalColor = vec4(4.0 / 255.0, 4.0 / 255.0, 10.0 / 255.0, 1.0);
        return;
    }

    float t = fract(mu * 0.035);
    t = sqrt(t);
    vec3 col = palette(t);
    finalColor = vec4(col, 1.0);
}
