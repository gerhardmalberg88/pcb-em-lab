#!/bin/bash
set -euo pipefail
if [ -f /input/check-cuda.cu ]; then
    # NVIDIA's toolkit-only installer links libxml2 even when no driver is
    # installed. Keep this OS dependency exclusive to the CUDA profile.
    apt-get update
    apt-get install -y --no-install-recommends libxml2
fi
# Spack requires this native filename; the maintained manifest is JSON.
if [ -f /opt/environment/spack.yaml ] && ! cmp -s /input/spack.json /opt/environment/spack.yaml; then
    rm -rf /opt/environment
fi
mkdir -p /opt/environment /export
cp /input/spack.json /opt/environment/spack.yaml
if [ -f /input/spack.lock ] && [ ! -f /opt/environment/spack.lock ]; then
    cp /input/spack.lock /opt/environment/spack.lock
fi
spack -e /opt/environment concretize
cp /opt/environment/spack.lock /export/spack.lock
spack -e /opt/environment install -j "${BUILD_JOBS:-2}" --fail-fast
if [ -x /opt/view/bin/nvcc ]; then
    cuda_flags=()
    IFS=, read -ra cuda_arches <<< "${CUDA_ARCH:-75}"
    for cuda_arch in "${cuda_arches[@]}"; do
        cuda_flags+=("-gencode=arch=compute_${cuda_arch},code=sm_${cuda_arch}")
    done
    /opt/view/bin/nvcc -O2 "${cuda_flags[@]}" /input/check-cuda.cu -o /usr/local/bin/pcb-em-cuda-check
    gcc -shared -fPIC -O2 -Wall -Wextra -I/opt/view/include \
        /input/cuda-runtime.c -o /usr/local/lib/pcb-em-cuda-runtime.so -ldl
    gcc -O2 -I/opt/view/include /input/check-cuda-memory.c -L/opt/view/lib \
        -Wl,-rpath,/opt/view/lib -Wl,--allow-shlib-undefined -lceed \
        -o /usr/local/bin/pcb-em-cuda-memory-check
fi
spack -e /opt/environment find --json > /export/packages.json
cp /input/spack.json /export/spack.json
cp /opt/environment/spack.lock /export/spack.lock
dpkg-query -W > /export/apt-packages.txt
if [ -f /input/check-cuda.cu ]; then
    # CUDA-linked Palace loads libcuda.so.1 even for --version. Build containers
    # intentionally have no host driver or GPU; validate it in the CDI runtime.
    test -x /opt/view/bin/palace
    printf '%s\n' 'CUDA solver installed; runtime validation requires GPU access.'
else
    palace --serial --version
fi
