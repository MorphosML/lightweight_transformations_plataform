# Antigravity Rules — Engineering Standards

The following five rules are unconditionally active for this workspace and all projects:

1. **Test-Driven Development (TDD)**:
   - Always write tests first before implementation.
   - Run tests to confirm the initial failure.
   - Implement the minimal clean code to achieve green status.
   - Refactor and ensure all automated tests pass before committing.

2. **Idempotency**:
   - Every transformation, pipeline, node, and database operation must be repeatable with zero side-effects and zero duplicate records.
   - Use deterministic keys, UPSERT / replace semantics, and SHA-256 payload checksums.

3. **Resiliency**:
   - Handle transient network, database, and API errors with exponential backoff and randomized jitter.
   - Implement circuit breakers and automatic socket re-connection.

4. **Fault-Tolerance**:
   - Isolate failures at the record and node level.
   - Route corrupt data to Dead-Letter Queues (DLQ) without aborting entire pipeline batches.
   - Use atomic staging writes to ensure no partial or corrupted data is saved on failure.

5. **ROI & Economic Capacity (FinOps)**:
   - Route small workloads (< 50,000 rows) to Tier 0 embedded micro-OLAP engines (0.00 CU, $0 cloud cost) instead of provisioning expensive distributed clusters.
   - Enforce memory ceilings and query timeouts.
   - Use compressed columnar Parquet storage for 80-90% I/O and storage savings.
