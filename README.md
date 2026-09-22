# OpenFlow Engine

The first runnable slice of OpenFlow: a pure Python DAG engine with safe filter expressions, multi-input nodes, cycle detection, per-node execution logs, and tenant-scoped connector keys.

## Quick start

```bash
python -m pip install -e '.[test]'
pytest
```

The engine has no HTTP or worker dependency. Applications can call `PipelineRunner.run()` from an API task or a Celery task later.
