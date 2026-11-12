# Engine

This plugin runs the Micro-Cosmos package in `micro_cosmos/`. The low-level analysis stays here.

Observer (`micro_cosmos/tools/observer_tools.py`) reads the source with tree-sitter where a grammar is installed, and with regex and AST parsers otherwise. It writes `ir_graph.json`, including framework hints.

Cartographer (`micro_cosmos/tools/cartographer_tools.py`) groups that graph into bounded contexts and seams with regex and path rules. Architect (`micro_cosmos/tools/architect_tools.py`) writes `tnas.json`. Security (`micro_cosmos/tools/security_tools.py`) writes `security_report.json` from the source text. It does not open environment files.

The framework translation planner is the Feature Specifier (`micro_cosmos/agents/feature_specifier.py` and `micro_cosmos/tools/feature_spec_tools.py`). A plan run is `pause_after_planning` and stops after that phase. A translate run continues into the seam loop in `micro_cosmos/orchestration/driver.py`: Code Writer, Skeptical Review, Test Review, Functional Review, and the Writer. It stops when `reports/<project>_<target>/` exists and does not open the PR gate.

Deterministic mode sets `skip_llm` and uses the symbolic tools. LLM mode uses the LangGraph agents in `micro_cosmos/langgraph_runtime.py` on the same tools. `skip_gate_validation` records a thin artifact and continues. The run does not wait for a person.

Web frameworks: Spring Boot, Axon Framework, NestJS, React, Django, Flask, and ASP.NET Core, plus Eventuate, Lagom, MediatR, NServiceBus, and Wolverine. Data engineering frameworks: Databricks, Azure Data Factory, BigQuery with Dataform, and Snowflake with dbt.
