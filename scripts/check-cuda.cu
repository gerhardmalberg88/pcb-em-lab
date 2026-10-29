#include <cuda_runtime.h>
#include <cstdio>

__global__ void write_value(int *value) { *value = 42; }
static bool checked(cudaError_t code, const char *operation) {
  if (code == cudaSuccess) return true;
  std::fprintf(stderr, "%s: %s\n", operation, cudaGetErrorString(code));
  return false;
}
int main() {
  int count = 0;
  if (!checked(cudaGetDeviceCount(&count), "CUDA device discovery") || count < 1) return 1;
  for (int index = 0; index < count; ++index) {
    cudaDeviceProp properties{};
    int *device = nullptr, value = 0;
    if (!checked(cudaSetDevice(index), "CUDA device selection") ||
        !checked(cudaGetDeviceProperties(&properties, index), "CUDA device properties") ||
        !checked(cudaMalloc(&device, sizeof(int)), "CUDA allocation")) return 1;
    write_value<<<1, 1>>>(device);
    if (!checked(cudaGetLastError(), "CUDA kernel launch") ||
        !checked(cudaDeviceSynchronize(), "CUDA kernel execution") ||
        !checked(cudaMemcpy(&value, device, sizeof(int), cudaMemcpyDeviceToHost), "CUDA copy") ||
        !checked(cudaFree(device), "CUDA free") || value != 42) return 1;
    std::printf("CUDA device %d: %s, architecture %d%d, kernel/copy passed\n",
                index, properties.name, properties.major, properties.minor);
  }
  return 0;
}
