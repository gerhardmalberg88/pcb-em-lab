/* This subprocess must fail clearly, before returning a null writable array. */
#include <ceed.h>
#include <ceed/backend.h>
#include <stdio.h>

int main(void) {
    Ceed ceed;
    CeedVector vector;
    CeedScalar *data = NULL;
    if (CeedInit("/gpu/cuda/ref", &ceed)) return 10;
    if (CeedSetErrorHandler(ceed, CeedErrorStore)) return 11;
    /* Eight TiB cannot fit on any of the target workstation/server GPUs. */
    if (CeedVectorCreate(ceed, (CeedSize)1 << 40, &vector)) return 12;
    if (CeedVectorGetArrayWrite(vector, CEED_MEM_DEVICE, &data)) return 13;
    fprintf(stderr, "Unexpected allocation success: %p\n", (void *)data);
    return 0;
}
