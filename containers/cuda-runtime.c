/* Runtime policy for the pinned HYPRE 3.2 / libCEED 1.0 CUDA stack.
 * HYPRE's initial Umpire device pool is 4 GiB; start smaller on workstation GPUs.
 * libCEED's CeedCall assumes success even with its returning error handler.
 * Abort on an allocation error before that assumption can hide a null buffer.
 * Neither policy changes the physical model or selects a different solver.
 */
#define _GNU_SOURCE
#include <HYPRE_utilities.h>
#include <ceed.h>
#include <ceed/backend.h>
#include <dlfcn.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void *required_symbol(const char *name) {
    void *symbol = dlsym(RTLD_NEXT, name);
    if (!symbol) {
        fprintf(stderr, "pcb-em CUDA runtime: required symbol %s unavailable\n", name);
        abort();
    }
    return symbol;
}

HYPRE_Int HYPRE_Initialize(void) {
    HYPRE_Int (*initialize)(void) = required_symbol("HYPRE_Initialize");
    HYPRE_Int rc = initialize();
    if (rc) return rc;
    const char *setting = getenv("PCB_EM_HYPRE_POOL_MIB");
    unsigned long long mib = 256;
    if (setting) {
        char *end;
        errno = 0;
        mib = strtoull(setting, &end, 10);
        if (errno || !*setting || *setting == '-' || *end || !mib ||
            mib > SIZE_MAX / (1024 * 1024)) {
            fprintf(stderr, "pcb-em: PCB_EM_HYPRE_POOL_MIB must be a positive MiB count\n");
            abort();
        }
    }
    HYPRE_Int (*set_pool)(size_t) = required_symbol("HYPRE_SetUmpireDevicePoolSize");
    rc = set_pool((size_t)mib * 1024 * 1024);
    if (!rc) fprintf(stderr, "pcb-em: HYPRE initial GPU pool %llu MiB (can grow)\n", mib);
    return rc;
}

int CeedErrorStore(Ceed ceed, const char *file, int line, const char *function,
                   int code, const char *format, va_list *args) {
    if (format && strstr(format, "CUDA_ERROR_OUT_OF_MEMORY")) {
        fprintf(stderr, "pcb-em: GPU memory exhausted. Reduce the model/ranks, use a "
                        "larger GPU, or explicitly select --backend cpu.\n");
        int (*fatal)(Ceed, const char *, int, const char *, int, const char *, va_list *) =
            required_symbol("CeedErrorAbort");
        fatal(ceed, file, line, function, code, format, args);
        abort();
    }
    int (*store)(Ceed, const char *, int, const char *, int, const char *, va_list *) =
        required_symbol("CeedErrorStore");
    return store(ceed, file, line, function, code, format, args);
}
