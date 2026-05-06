#ifndef MANDELBROT_BENCH_COMMON_H
#define MANDELBROT_BENCH_COMMON_H

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <sys/resource.h>

#define MANDELBROT_WINDOW_W 1280
#define MANDELBROT_WINDOW_H 720

typedef struct
{
    uint64_t sum;
    uint64_t min;
    uint64_t max;
} U64Stats;

typedef enum
{
    BENCH_KIND_RENDER  = 0,
    BENCH_KIND_PRESENT = 1,
} BenchKind;

typedef struct
{
    BenchKind   kind;
    const char *out_path;
    int         frames;
    int         warmup;
    float       center_x;
    float       center_y;
    float       zoom;
} BenchArgs;

uint64_t BenchNowNs         (void);
uint64_t BenchReadTicksBegin(void);
uint64_t BenchReadTicksEnd  (void);

U64Stats BenchStatsInit    (void);
void     BenchUpdateStats  (U64Stats* stats, uint64_t value);
uint64_t BenchChecksumBytes(const void* data, size_t byte_count);
double   BenchTimevalToSeconds(const struct timeval* value);

const char* BenchKindName     (BenchKind kind);

BenchArgs BenchParseArgs(int          argc,
                         char**       argv,
                         BenchKind    default_kind,
                         const char*  default_out_path,
                         int          default_frames,
                         int          default_warmup);

FILE* BenchOpenCsv             (const char* path);
void  BenchPrintRunConfig      (const char* renderer_name, const BenchArgs* args);
void  BenchPrintResourceSummary(const struct rusage* usage,
                                const void* buffer,
                                size_t byte_count);

#endif
