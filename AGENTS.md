# Engineering Rules & Architecture Standards

All development, pipelines, transformations, and agents operating in this project and all derivative projects must strictly adhere to the following five foundational rules:

---

## 1. Test-Driven Development (TDD)
- **Red-Green-Refactor Cycle**:
  1. Write automated test cases defining the expected behavior before writing the implementation.
  2. Run the test suite and confirm failure for the expected reason.
  3. Implement the minimal clean code to make the test pass.
  4. Refactor for readability, modularity, and performance.
- **Edge Case Coverage**:
  - Always write tests for null/missing values, corrupt schemas, empty inputs, type mismatches, and boundary limits.
- **Zero Regression Policy**:
  - The complete test suite must be 100% green before staging, committing, or pushing code.

---

## 2. Idempotency
- **Deterministic Outcomes**:
  - Executing a pipeline, DAG node, SQL query, or API transformation multiple times with identical inputs must produce the exact same state without duplicate rows, double-counting, or side effects.
- **Safe Write & Swap Semantics**:
  - Use partition overwrites, UPSERTs with primary/composite keys, or atomic staging swaps (`if_exists="replace"`) rather than unbounded appends.
- **Deterministic Checksum Keys**:
  - Hash payloads (SHA-256) to ensure idempotent caching and duplicate submission rejection.

---

## 3. Resiliency
- **Self-Healing Operations**:
  - Automatically recover from transient network glitches, database socket drops, and cloud rate limits.
- **Exponential Backoff with Jitter**:
  - Apply exponential backoff with randomized jitter on all remote HTTP, JDBC, and S3 requests.
- **Circuit Breakers**:
  - Fail fast and open circuit breakers when upstream dependencies become unavailable to prevent resource starvation.
- **Connection Lifecycle Management**:
  - Validate connection health before query execution and re-establish disconnected connection pools.

---

## 4. Fault-Tolerance
- **Failure Isolation**:
  - A single bad record, malformed column, or failed node must never crash the entire engine, pipeline, or cluster.
- **Dead-Letter Queues (DLQ) & Quarantining**:
  - Quarantine invalid records with structured error metadata while allowing healthy records to process cleanly.
- **Atomic State Transitions**:
  - Stage intermediate writes in scoped temporary paths and finalize via atomic rename/swap so halfway failures leave zero partial or corrupted state.
- **Granular Step-Level Telemetry**:
  - Wrap node executions and record duration, row counts, memory footprint, and sanitized error context.

---

## 5. Economic Capacity & ROI (FinOps)
- **High ROI Compute**:
  - Optimize for compute efficiency and cloud cost avoidance.
- **Tiered Workload Routing**:
  - Run small datasets (< 50,000 rows) on zero-overhead in-memory embedded engines (Tier 0: DuckDB, SQLite OLAP, vectorized Pandas) at **0.00 Capacity Units (CU)** and **$0 cloud cluster cost**.
  - Dispatch heavy distributed clusters (Tier 1: PySpark) only when datasets exceed volume thresholds or when explicitly requested for massive distributed shuffles.
- **Resource Governance**:
  - Enforce strict memory ceilings and query timeouts to prevent worker out-of-memory crashes.
- **Columnar Lakehouse Storage**:
  - Store tables in compressed columnar Parquet format (Snappy/ZSTD) with partition directory structuring, reducing storage and I/O costs by 80-90%.
