#include "src/render.h"
#include "src/utils/utils.h"

#define WINDOW_W 1280
#define WINDOW_H 720

static Color buffer[WINDOW_W * WINDOW_H] = { 0 };

int main(void)
{
    InitWindow(WINDOW_W, WINDOW_H, "Mandelbrot set");

    Image img = {
        .data    = buffer,
        .width   = WINDOW_W,
        .height  = WINDOW_H,
        .mipmaps = 1,
        .format  = PIXELFORMAT_UNCOMPRESSED_R8G8B8A8
    };

    Texture2D texture = LoadTextureFromImage(img);
    SetTextureFilter(texture, TEXTURE_FILTER_POINT);

    float centerX = -0.5;
    float centerY =  0.0;
    float zoom    =  1.0;

    while (!WindowShouldClose())
    {
        float dt = GetFrameTime();

        float move_speed = 1.5 / zoom * dt;
        float zoom_speed = 1.0 + 1.5 * dt;

        if (IsKeyDown(KEY_W)) centerY += move_speed;
        if (IsKeyDown(KEY_S)) centerY -= move_speed;
        if (IsKeyDown(KEY_A)) centerX -= move_speed;
        if (IsKeyDown(KEY_D)) centerX += move_speed;

        if (IsKeyDown(KEY_Q)) zoom /= zoom_speed;
        if (IsKeyDown(KEY_E)) zoom *= zoom_speed;

        if (zoom < 1.0) zoom = 1.0;

        RenderMandelbrot(buffer, WINDOW_W, WINDOW_H, centerX, centerY, zoom);
        UpdateTexture(texture, buffer);

        BeginDrawing();
        ClearBackground(BLACK);

        DrawTexturePro(
            texture,
            (Rectangle){ 0, 0, (float)texture.width, (float)texture.height },
            (Rectangle){ 0, 0, (float)GetRenderWidth(), (float)GetRenderHeight() },
            (Vector2){ 0, 0 },
            0.0,
            WHITE
        );

        DrawText(GetRendererName(), 10, 10, 20, WHITE);
        DrawText("WASD move; Q out, E in", 10, 36, 20, WHITE);
        DrawFPS(10, 62);

        EndDrawing();
    }

    UnloadTexture(texture);
    CloseWindow();
    return 0;
}
