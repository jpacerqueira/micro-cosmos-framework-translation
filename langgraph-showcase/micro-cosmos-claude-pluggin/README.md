# Micro-Cosmos

Micro-Cosmos is the application framework translation pipeline. Point it at a source folder and it runs Observer, Cartographer, Architect, Security analysis, the framework translation planner, and, when you ask, Code translation. Deterministic mode uses the AST, tree-sitter, and regex analyzers in this package. LLM mode uses the LangGraph agents on those same analyzers. The run does not wait for a human gate.

## Web frameworks

Micro-Cosmos translates Spring Boot, Axon Framework, NestJS, React, Django, Flask, and ASP.NET Core. On those stacks it also recognises Eventuate, Lagom, MediatR, NServiceBus, and Wolverine. An application estate translates onto an application language such as Java 21, Python 3, Go, Kotlin, TypeScript, C#, Rust, Scala, Swift, or JavaScript.

## Data engineering frameworks

Micro-Cosmos translates Databricks, Azure Data Factory, BigQuery with Dataform, and Snowflake with dbt. A data-engineering estate translates only onto another of those platforms.

## How to use it

Select the source folder. Use the plan command to stop once the framework translation plan is written. Use the translate command to continue into code translation. Name the target once, and choose deterministic or LLM mode once. The first 5 pipeline runs on an account are free. After that, a license is $15 a month for unlimited runs.

## Data

The plugin reads the source folder on your machine and writes the run under that folder in `.micro-cosmos`. Deterministic mode does not call a model. LLM mode sends the phase prompts to the model URL you type for that run. Source code is not sent to any other service.
