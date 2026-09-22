# Engineering Standards: TDD, Idempotency, Resiliency, Fault-Tolerance & ROI

All agentic and human code changes must adhere to these five pillars:

1. **Test-Driven Development (TDD)**: Test first, code second, verify zero regressions.
2. **Idempotency**: Deterministic results on every re-run without duplicate rows or ghost state.
3. **Resiliency**: Graceful recovery with exponential backoff and circuit breakers.
4. **Fault-Tolerance**: Failure isolation, dead-letter quarantining, and atomic staging swaps.
5. **Economic Capacity & ROI**: Tiered compute routing (Tier 0 Embedded vs Tier 1 Spark), CU metering, and memory bounds.
