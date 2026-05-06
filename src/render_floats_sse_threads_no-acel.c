#include <pthread.h>
#include <stdlib.h>
#include <unistd.h>

#include "render_floats_sse_common.h"

typedef struct
{
    Color *buffer;
    int width;
    int height;
    int y_begin;
    int y_end;
    float centerX;
    float centerY;
    float zoom;
} RenderJob;

static void *RenderThread(void *arg)
{
    RenderJob *job = (RenderJob *)arg;

    RenderMandelbrotRowsSSE(job->buffer,
                            job->width,
                            job->height,
                            job->y_begin,
                            job->y_end,
                            job->centerX,
                            job->centerY,
                            job->zoom);
    return NULL;
}

static int ResolveThreadCount(int height)
{
    const char *env_value = getenv("MANDELBROT_THREADS");
    if (env_value != NULL && *env_value != '\0')
    {
        int requested = atoi(env_value);
        if (requested > 0)
        {
            return requested > height ? height : requested;
        }
    }

    long cpu_count = sysconf(_SC_NPROCESSORS_ONLN);
    if (cpu_count < 1)
    {
        cpu_count = 1;
    }

    if (cpu_count > height)
    {
        cpu_count = height;
    }

    return (int)cpu_count;
}

const char *GetRendererName(void)
{
    return "render_floats_sse_threads_no-acel";
}

void RenderMandelbrot(Color *buffer, int width, int height,
                      float centerX, float centerY, float zoom)
{
    int thread_count = ResolveThreadCount(height);
    if (thread_count <= 1)
    {
        RenderMandelbrotRowsSSE(buffer, width, height, 0, height, centerX, centerY, zoom);
        return;
    }

    pthread_t *threads = malloc((size_t)thread_count * sizeof(*threads));
    RenderJob *jobs = malloc((size_t)thread_count * sizeof(*jobs));
    if (threads == NULL || jobs == NULL)
    {
        free(threads);
        free(jobs);
        RenderMandelbrotRowsSSE(buffer, width, height, 0, height, centerX, centerY, zoom);
        return;
    }

    int rows_per_thread = height / thread_count;
    int remainder = height % thread_count;
    int y = 0;
    int created_threads = 0;

    for (int i = 0; i < thread_count; ++i)
    {
        int rows = rows_per_thread + (i < remainder ? 1 : 0);

        jobs[i] = (RenderJob){
            .buffer = buffer,
            .width = width,
            .height = height,
            .y_begin = y,
            .y_end = y + rows,
            .centerX = centerX,
            .centerY = centerY,
            .zoom = zoom,
        };

        if (pthread_create(&threads[i], NULL, RenderThread, &jobs[i]) != 0)
        {
            for (int j = 0; j < created_threads; ++j)
            {
                pthread_join(threads[j], NULL);
            }

            RenderMandelbrotRowsSSE(buffer,
                                    width,
                                    height,
                                    jobs[i].y_begin,
                                    height,
                                    centerX,
                                    centerY,
                                    zoom);
            free(threads);
            free(jobs);
            return;
        }

        ++created_threads;
        y += rows;
    }

    for (int i = 0; i < created_threads; ++i)
    {
        pthread_join(threads[i], NULL);
    }

    free(threads);
    free(jobs);
}
