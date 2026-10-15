# SQL vs. NoSQL Performance Benchmark Summary

- **Run ID:** `bench_1792017299`
- **Timestamp (UTC):** `2026-10-14T22:34:59.110338+00:00`
- **Environment:** Python 3.12.4 (Windows AMD64)
- **Configuration:** 3 warm-up, 20 measured iterations
- **Equivalence Status:** 1/7 Workloads Passed

## Performance Comparison Table

| Workload ID | Name | Equivalence | SQL Median (ms) | SQL p95 (ms) | Mongo Median (ms) | Mongo p95 (ms) | Speed Ratio (SQL/Mongo) |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **workload_a** | Dataset Overview | [FAIL] | 3.11 ms | 4.73 ms | 64.12 ms | 75.26 ms | 0.05x |
| **workload_b** | Patient Vitals Summary | [FAIL] | 5.71 ms | 6.48 ms | 63.82 ms | 73.04 ms | 0.09x |
| **workload_c** | Time-Window Filtering | [PASS] | 1.11 ms | 1.56 ms | 59.36 ms | 71.91 ms | 0.02x |
| **workload_d** | Time-Bucket Analytics | [FAIL] | 9.21 ms | 11.97 ms | 138.69 ms | 157.43 ms | 0.07x |
| **workload_e** | Filtered Patient History | [FAIL] | 45.55 ms | 79.17 ms | 63.74 ms | 74.69 ms | 0.71x |
| **workload_f** | Source & Provenance Summary | [FAIL] | 3.81 ms | 4.84 ms | 60.09 ms | 69.50 ms | 0.06x |
| **workload_g** | Clinical Alert Analytics | [FAIL] | 3.36 ms | 6.68 ms | 52.08 ms | 68.14 ms | 0.06x |

> [!NOTE]
> Speed Ratio > 1.0 indicates MongoDB demonstrated lower latency; Speed Ratio < 1.0 indicates MySQL demonstrated lower latency.
> In-memory SQLite and mongomock testing verifies execution logic and semantic parity, but does not substitute for live Atlas and MySQL InnoDB network benchmarking.