// Temporary M2.0 (#50) diagnostic, not production code.
// Lists ggml backend devices and runs a deterministic synthetic fp32 matmul on a
// chosen device, verifying sampled outputs against a CPU double-precision
// reference. Needs no model weights. Usage:
//   ggml-diag list
//   ggml-diag matmul <device-index> [n=1024] [iters=20]
#include "ggml.h"
#include "ggml-alloc.h"
#include "ggml-backend.h"

#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

static const char * type_name(enum ggml_backend_dev_type t) {
    switch (t) {
        case GGML_BACKEND_DEVICE_TYPE_CPU:  return "CPU";
        case GGML_BACKEND_DEVICE_TYPE_GPU:  return "GPU";
        case GGML_BACKEND_DEVICE_TYPE_IGPU: return "IGPU";
        case GGML_BACKEND_DEVICE_TYPE_ACCEL: return "ACCEL";
        default: return "OTHER";
    }
}

static int list_devices() {
    size_t n = ggml_backend_dev_count();
    std::printf("device_count=%zu\n", n);
    for (size_t i = 0; i < n; ++i) {
        ggml_backend_dev_t dev = ggml_backend_dev_get(i);
        size_t free_b = 0, total_b = 0;
        ggml_backend_dev_memory(dev, &free_b, &total_b);
        std::printf("device[%zu] name=%s type=%s description=\"%s\" memory_free=%zu memory_total=%zu\n",
                    i, ggml_backend_dev_name(dev), type_name(ggml_backend_dev_type(dev)),
                    ggml_backend_dev_description(dev), free_b, total_b);
    }
    return 0;
}

static float a_val(int k, int i) { return (float) (((i * 31 + k * 17) % 13) - 6) / 16.0f; }
static float b_val(int k, int j) { return (float) (((j * 29 + k * 11) % 11) - 5) / 16.0f; }

static int run_matmul(size_t index, int n, int iters) {
    if (index >= ggml_backend_dev_count()) {
        std::fprintf(stderr, "ERROR: requested device index %zu does not exist (count=%zu); refusing to fall back\n",
                     index, ggml_backend_dev_count());
        return 2;
    }
    ggml_backend_dev_t dev = ggml_backend_dev_get(index);
    std::printf("requested device[%zu] name=%s type=%s description=\"%s\"\n", index,
                ggml_backend_dev_name(dev), type_name(ggml_backend_dev_type(dev)),
                ggml_backend_dev_description(dev));
    ggml_backend_t backend = ggml_backend_dev_init(dev, nullptr);
    if (!backend) {
        std::fprintf(stderr, "ERROR: backend init failed for requested device\n");
        return 3;
    }
    std::printf("actual backend=%s\n", ggml_backend_name(backend));

    struct ggml_init_params ip = { ggml_tensor_overhead() * 8 + ggml_graph_overhead(), nullptr, true };
    struct ggml_context * ctx = ggml_init(ip);
    struct ggml_tensor * a = ggml_new_tensor_2d(ctx, GGML_TYPE_F32, n, n);
    struct ggml_tensor * b = ggml_new_tensor_2d(ctx, GGML_TYPE_F32, n, n);
    struct ggml_tensor * c = ggml_mul_mat(ctx, a, b);
    struct ggml_cgraph * gf = ggml_new_graph(ctx);
    ggml_build_forward_expand(gf, c);
    if (!ggml_backend_dev_supports_op(dev, c)) {
        std::fprintf(stderr, "ERROR: device does not support MUL_MAT for this graph\n");
        return 4;
    }
    ggml_backend_buffer_t buf = ggml_backend_alloc_ctx_tensors(ctx, backend);
    if (!buf) {
        std::fprintf(stderr, "ERROR: buffer allocation failed\n");
        return 5;
    }
    std::vector<float> av((size_t) n * n), bv((size_t) n * n);
    for (int i = 0; i < n; ++i)
        for (int k = 0; k < n; ++k) {
            av[(size_t) i * n + k] = a_val(k, i);   // a[k,i]: ne0 = k
            bv[(size_t) i * n + k] = b_val(k, i);   // b[k,j]
        }
    ggml_backend_tensor_set(a, av.data(), 0, ggml_nbytes(a));
    ggml_backend_tensor_set(b, bv.data(), 0, ggml_nbytes(b));

    auto t0 = std::chrono::steady_clock::now();
    if (ggml_backend_graph_compute(backend, gf) != GGML_STATUS_SUCCESS) {
        std::fprintf(stderr, "ERROR: graph compute failed\n");
        return 6;
    }
    auto t1 = std::chrono::steady_clock::now();
    for (int it = 1; it < iters; ++it) ggml_backend_graph_compute(backend, gf);
    auto t2 = std::chrono::steady_clock::now();

    std::vector<float> cv((size_t) n * n);
    ggml_backend_tensor_get(c, cv.data(), 0, ggml_nbytes(c));
    // c[i + m*j]... ggml_mul_mat result: ne0 = rows of a (m), ne1 = rows of b; C[m=i, j] = sum_k a[k,i]*b[k,j]
    double max_rel = 0.0;
    int samples = 64;
    for (int s = 0; s < samples; ++s) {
        int i = (s * 37 + 3) % n, j = (s * 53 + 7) % n;
        double ref = 0.0;
        for (int k = 0; k < n; ++k) ref += (double) a_val(k, i) * (double) b_val(k, j);
        double got = cv[(size_t) j * n + i];
        double rel = std::fabs(got - ref) / (std::fabs(ref) + 1.0);
        if (rel > max_rel) max_rel = rel;
    }
    double first_ms = std::chrono::duration<double, std::milli>(t1 - t0).count();
    double rest_ms = iters > 1 ? std::chrono::duration<double, std::milli>(t2 - t1).count() / (iters - 1) : 0.0;
    double gflops = rest_ms > 0.0 ? 2.0 * n * n * (double) n / (rest_ms * 1e6) : 0.0;
    std::printf("n=%d iters=%d first_ms=%.3f warm_avg_ms=%.3f gflops=%.1f max_rel_err=%.3e verdict=%s\n", n,
                iters, first_ms, rest_ms, gflops, max_rel, max_rel < 5e-3 ? "OK" : "MISMATCH");
    ggml_backend_buffer_free(buf);
    ggml_free(ctx);
    ggml_backend_free(backend);
    return max_rel < 5e-3 ? 0 : 7;
}

int main(int argc, char ** argv) {
    ggml_backend_load_all();
    if (argc >= 2 && std::strcmp(argv[1], "list") == 0) return list_devices();
    if (argc >= 3 && std::strcmp(argv[1], "matmul") == 0) {
        size_t idx = (size_t) std::strtoull(argv[2], nullptr, 10);
        int n = argc >= 4 ? std::atoi(argv[3]) : 1024;
        int iters = argc >= 5 ? std::atoi(argv[4]) : 20;
        return run_matmul(idx, n, iters);
    }
    std::fprintf(stderr, "usage: ggml-diag list | matmul <device-index> [n] [iters]\n");
    return 1;
}
