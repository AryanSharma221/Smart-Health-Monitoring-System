# SQL vs. NoSQL Performance Benchmark Summary

- **Run ID:** `bench_1791921481`
- **Timestamp (UTC):** `2026-10-13T19:58:01.906950+00:00`
- **Environment:** Python 3.12.4 (Windows AMD64)
- **Configuration:** 3 warm-up, 20 measured iterations
- **Equivalence Status:** 7/7 Workloads Passed

## Performance Comparison Table

| Workload ID | Name | Equivalence | SQL Median (ms) | SQL p95 (ms) | Mongo Median (ms) | Mongo p95 (ms) | Speed Ratio (SQL/Mongo) |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **workload_a** | Dataset Overview | [PASS] | 1.67 ms | 2.49 ms | 54.61 ms | 103.22 ms | 0.03x |
| **workload_b** | Patient Vitals Summary | [PASS] | 2.25 ms | 3.23 ms | 72.76 ms | 94.90 ms | 0.03x |
| **workload_c** | Time-Window Filtering | [PASS] | 0.58 ms | 0.91 ms | 60.34 ms | 81.81 ms | 0.01x |
| **workload_d** | Time-Bucket Analytics | [PASS] | 3.81 ms | 5.97 ms | 75.93 ms | 103.83 ms | 0.05x |
| **workload_e** | Filtered Patient History | [PASS] | 9.54 ms | 10.87 ms | 62.77 ms | 70.50 ms | 0.15x |
| **workload_f** | Source & Provenance Summary | [PASS] | 1.24 ms | 1.80 ms | 46.70 ms | 87.58 ms | 0.03x |
| **workload_g** | Clinical Alert Analytics | [PASS] | 0.84 ms | 1.03 ms | 0.06 ms | 0.08 ms | 14.52x |

> [!NOTE]
> Speed Ratio > 1.0 indicates MongoDB demonstrated lower latency; Speed Ratio < 1.0 indicates MySQL demonstrated lower latency.
> In-memory SQLite and mongomock testing verifies execution logic and semantic parity, but does not substitute for live Atlas and MySQL InnoDB network benchmarking.