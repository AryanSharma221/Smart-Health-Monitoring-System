# SQL vs. NoSQL Performance Benchmark Summary

- **Run ID:** `bench_1791921363`
- **Timestamp (UTC):** `2026-10-13T19:56:03.666061+00:00`
- **Environment:** Python 3.12.4 (Windows AMD64)
- **Configuration:** 1 warm-up, 5 measured iterations
- **Equivalence Status:** 7/7 Workloads Passed

## Performance Comparison Table

| Workload ID | Name | Equivalence | SQL Median (ms) | SQL p95 (ms) | Mongo Median (ms) | Mongo p95 (ms) | Speed Ratio (SQL/Mongo) |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **workload_a** | Dataset Overview | [PASS] | 1.60 ms | 1.90 ms | 57.42 ms | 70.94 ms | 0.03x |
| **workload_b** | Patient Vitals Summary | [PASS] | 2.29 ms | 3.05 ms | 68.19 ms | 76.00 ms | 0.03x |
| **workload_c** | Time-Window Filtering | [PASS] | 0.56 ms | 0.91 ms | 53.85 ms | 65.05 ms | 0.01x |
| **workload_d** | Time-Bucket Analytics | [PASS] | 4.09 ms | 5.64 ms | 71.87 ms | 75.02 ms | 0.06x |
| **workload_e** | Filtered Patient History | [PASS] | 10.12 ms | 10.54 ms | 61.22 ms | 68.24 ms | 0.17x |
| **workload_f** | Source & Provenance Summary | [PASS] | 1.22 ms | 1.25 ms | 61.09 ms | 123.07 ms | 0.02x |
| **workload_g** | Clinical Alert Analytics | [PASS] | 0.58 ms | 0.61 ms | 0.04 ms | 0.05 ms | 12.8x |

> [!NOTE]
> Speed Ratio > 1.0 indicates MongoDB demonstrated lower latency; Speed Ratio < 1.0 indicates MySQL demonstrated lower latency.
> In-memory SQLite and mongomock testing verifies execution logic and semantic parity, but does not substitute for live Atlas and MySQL InnoDB network benchmarking.