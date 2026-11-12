# Legacy estate (example)

A small Python 2 credit-decisioning codebase used as the default demo input.
Point the pipeline at any directory containing source files in a supported
language — the Observer will detect the dominant language automatically.

```bash
micro-cosmos run examples/legacy_estate --target-lang python3
# or
micro-cosmos run /path/to/your/source --source-lang java8 --target-lang kotlin
```

In a real engagement this would be the root of any legacy codebase being
modernised. The Observer tool walks the directory, extracts an IR property
graph from the source files, and all subsequent agents operate on that IR —
never on the raw source again.
