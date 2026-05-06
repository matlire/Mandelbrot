#define _POSIX_C_SOURCE 200809L
#include "bench_common.h"

#include <errno.h>
#include <inttypes.h>
#include <limits.h>
#include <string.h>
#include <stdlib.h>
#include <time.h>

#if defined(__x86_64__) || defined(__i386__)
#include <x86intrin.h>
#endif

uint64_t BenchNowNs(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}

uint64_t BenchReadTicksBegin(void)
{
#if defined(__x86_64__) || defined(__i386__)
    _mm_lfence();
    return __rdtsc();
#else
    return BenchNowNs();
#endif
}

uint64_t BenchReadTicksEnd(void)
{
#if defined(__x86_64__) || defined(__i386__)
    unsigned aux = 0;
    uint64_t ticks = __rdtscp(&aux);
    _mm_lfence();
    return ticks;
#else
    return BenchNowNs();
#endif
}

U64Stats BenchStatsInit(void)
{
    return (U64Stats){ .sum = 0, .min = UINT64_MAX, .max = 0 };
}

void BenchUpdateStats(U64Stats* stats, uint64_t value)
{
    stats->sum += value;
    if (value < stats->min)
        stats->min = value;
    if (value > stats->max)
        stats->max = value;
}

uint64_t BenchChecksumBytes(const void* data, size_t byte_count)
{
    const unsigned char* p = (const unsigned char*)data;
    uint64_t hash = 1469598103934665603ull;

    for (size_t i = 0; i < byte_count; ++i)
    {
        hash ^= (uint64_t)p[i];
        hash *= 1099511628211ull;
    }
    return hash;
}

double BenchTimevalToSeconds(const struct timeval* value)
{
    return (double)value->tv_sec + (double)value->tv_usec / 1e6;
}

const char* BenchKindName(BenchKind kind)
{
    switch (kind)
    {
    case BENCH_KIND_PRESENT:
        return "present";
    case BENCH_KIND_RENDER:
    default:
        return "render";
    }
}

static void BenchPrintUsageAndExit(const char* program_name,
                                   const char* default_out_path,
                                   int default_frames,
                                   int default_warmup,
                                   int exit_code)
{
    FILE* stream = exit_code == 0 ? stdout : stderr;
    fprintf(stream,
            "Usage: %s [--bench render|present] [--out PATH] [--frames N] [--warmup N]\n"
            "          [--center-x VALUE] [--center-y VALUE] [--zoom VALUE]\n"
            "\n"
            "Defaults:\n"
            "  --bench render\n"
            "  --out %s\n"
            "  --frames %d\n"
            "  --warmup %d\n",
            program_name,
            default_out_path,
            default_frames,
            default_warmup);
    exit(exit_code);
}

static const char* BenchRequireValue(int argc, char** argv, int* index)
{
    if ((*index + 1) >= argc)
    {
        fprintf(stderr, "missing value for %s\n", argv[*index]);
        BenchPrintUsageAndExit(argv[0], "bench.csv", 300, 30, 2);
    }
    *index += 1;
    return argv[*index];
}

static BenchKind BenchParseKind(const char* value, const char* program_name)
{
    if (strcmp(value, "render") == 0)
        return BENCH_KIND_RENDER;
    if (strcmp(value, "present") == 0)
        return BENCH_KIND_PRESENT;

    fprintf(stderr, "invalid bench kind: %s\n", value);
    BenchPrintUsageAndExit(program_name, "bench.csv", 300, 30, 2);
    return BENCH_KIND_RENDER;
}

static int BenchParseInt(const char* value, const char* flag_name, const char* program_name)
{
    char* end    = NULL;
    long  parsed = 0;

    errno  = 0;
    parsed = strtol(value, &end, 10);
    if (errno != 0 || end == value || *end != '\0' || parsed < INT_MIN || parsed > INT_MAX)
    {
        fprintf(stderr, "invalid integer for %s: %s\n", flag_name, value);
        BenchPrintUsageAndExit(program_name, "bench.csv", 300, 30, 2);
    }

    return (int)parsed;
}

static float BenchParseFloat(const char* value, const char* flag_name, const char* program_name)
{
    char* end    = NULL;
    float parsed = 0.0f;

    errno  = 0;
    parsed = strtof(value, &end);
    if (errno != 0 || end == value || *end != '\0')
    {
        fprintf(stderr, "invalid float for %s: %s\n", flag_name, value);
        BenchPrintUsageAndExit(program_name, "bench.csv", 300, 30, 2);
    }

    return parsed;
}

#define BENCH_PARSE_VALUE_OPTION(opt, action)                      \
    {                                                              \
        enum { bench_opt_len = sizeof(opt) - 1 };                  \
        if (strcmp(arg, opt) == 0)                                 \
        {                                                          \
            const char *value = BenchRequireValue(argc, argv, &i); \
            action;                                                \
            continue;                                              \
        }                                                          \
        if (strncmp(arg, opt "=", bench_opt_len + 1) == 0)         \
        {                                                          \
            const char *value = arg + bench_opt_len + 1;           \
            action;                                                \
            continue;                                              \
        }                                                          \
    }

BenchArgs BenchParseArgs(int         argc,
                         char**      argv,
                         BenchKind   default_kind,
                         const char* default_out_path,
                         int default_frames,
                         int default_warmup)
{
    BenchArgs args = {
        .kind = default_kind,
        .out_path = default_out_path,
        .frames = default_frames,
        .warmup = default_warmup,
        .center_x = -0.743643887037151f,
        .center_y = 0.131825904205330f,
        .zoom = 180.0f,
    };

    for (int i = 1; i < argc; ++i)
    {
        const char* arg = argv[i];

        if (strcmp(arg, "-h") == 0 || strcmp(arg, "--help") == 0)
            BenchPrintUsageAndExit(argv[0], default_out_path, default_frames, default_warmup, 0);
        if (strcmp(arg, "--bench") == 0 || strcmp(arg, "--mode") == 0)
        {
            args.kind = BenchParseKind(BenchRequireValue(argc, argv, &i), argv[0]);
            continue;
        }

        BENCH_PARSE_VALUE_OPTION("--bench", args.kind = BenchParseKind(value, argv[0]));

        BENCH_PARSE_VALUE_OPTION("--mode", args.kind = BenchParseKind(value, argv[0]));

        BENCH_PARSE_VALUE_OPTION("--out", args.out_path = value);

        BENCH_PARSE_VALUE_OPTION("--frames", args.frames = BenchParseInt(value, "--frames", argv[0]));

        BENCH_PARSE_VALUE_OPTION("--warmup", args.warmup = BenchParseInt(value, "--warmup", argv[0]));

        BENCH_PARSE_VALUE_OPTION("--center-x", args.center_x = BenchParseFloat(value, "--center-x", argv[0]));

        BENCH_PARSE_VALUE_OPTION("--center-y", args.center_y = BenchParseFloat(value, "--center-y", argv[0]));

        BENCH_PARSE_VALUE_OPTION("--zoom", args.zoom = BenchParseFloat(value, "--zoom", argv[0]));

        fprintf(stderr, "unknown argument: %s\n", arg);
        BenchPrintUsageAndExit(argv[0], default_out_path, default_frames, default_warmup, 2);
    }

    if (args.frames <= 0)
        args.frames = default_frames;
    if (args.warmup < 0)
        args.warmup = default_warmup;
    if (args.zoom <= 0.0f)
        args.zoom = 180.0f;

    return args;
}

FILE* BenchOpenCsv(const char* path)
{
    FILE* out = fopen(path, "w");
    if (out == NULL)
        perror("fopen");
    return out;
}

void BenchPrintRunConfig(const char* renderer_name, const BenchArgs* args)
{
    printf("renderer=%s\n", renderer_name);
    printf("bench_kind=%s\n", BenchKindName(args->kind));
    printf("frames=%d\n", args->frames);
    printf("warmup=%d\n", args->warmup);
    printf("scene_center_x=%.9f\n", args->center_x);
    printf("scene_center_y=%.9f\n", args->center_y);
    printf("scene_zoom=%.3f\n", args->zoom);
}

void BenchPrintResourceSummary(const struct rusage* usage,
                               const void* buffer,
                               size_t byte_count)
{
    printf("maxrss_kb=%ld\n", usage->ru_maxrss);
    printf("minor_faults=%ld\n", usage->ru_minflt);
    printf("major_faults=%ld\n", usage->ru_majflt);
    printf("voluntary_ctx_switches=%ld\n", usage->ru_nvcsw);
    printf("involuntary_ctx_switches=%ld\n", usage->ru_nivcsw);
    printf("user_cpu_s=%.6f\n", BenchTimevalToSeconds(&usage->ru_utime));
    printf("sys_cpu_s=%.6f\n", BenchTimevalToSeconds(&usage->ru_stime));
    printf("checksum=%016" PRIx64 "\n", BenchChecksumBytes(buffer, byte_count));
}
