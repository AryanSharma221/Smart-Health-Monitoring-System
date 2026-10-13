# SQL vs. NoSQL Performance Benchmark Summary

- **Run ID:** `bench_1791921303`
- **Timestamp (UTC):** `2026-10-13T19:55:03.080502+00:00`
- **Environment:** Python 3.12.4 (Windows AMD64)
- **Configuration:** 1 warm-up, 5 measured iterations
- **Equivalence Status:** 6/7 Workloads Passed

## Performance Comparison Table

| Workload ID | Name | Equivalence | SQL Median (ms) | SQL p95 (ms) | Mongo Median (ms) | Mongo p95 (ms) | Speed Ratio (SQL/Mongo) |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **workload_a** | Dataset Overview | ❌ FAIL | 1.62 ms | 2.27 ms | 52.31 ms | 55.22 ms | 0.03x |
| **workload_b** | Patient Vitals Summary | ✅ PASS | 2.20 ms | 2.63 ms | 67.28 ms | 68.69 ms | 0.03x |
| **workload_c** | Time-Window Filtering | ✅ PASS | 0.68 ms | 0.74 ms | 75.75 ms | 85.68 ms | 0.01x |
| **workload_d** | Time-Bucket Analytics | ✅ PASS | 3.79 ms | 4.97 ms | 72.89 ms | 73.74 ms | 0.05x |
| **workload_e** | Filtered Patient History | ✅ PASS | 9.82 ms | 15.13 ms | 64.57 ms | 96.11 ms | 0.15x |
| **workload_f** | Source & Provenance Summary | ✅ PASS | 1.21 ms | 1.27 ms | 52.97 ms | 142.55 ms | 0.02x |
| **workload_g** | Clinical Alert Analytics | ✅ PASS | 0.71 ms | 0.83 ms | 0.05 ms | 0.06 ms | 13.32x |

> [!NOTE]
> Speed Ratio > 1.0 indicates MongoDB demonstrated lower latency; Speed Ratio < 1.0 indicates MySQL demonstrated lower latency.
> In-memory SQLite and mongomock testing verifies execution logic and semantic parity, but does not substitute for live Atlas and MySQL InnoDB network benchmarking.