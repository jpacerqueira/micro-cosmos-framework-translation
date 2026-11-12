# Micro-Focus

Micro-Focus is an application framework translation plugin. Point it at a source folder and it runs the Micro-Cosmos pipeline in Claude: Observer, Cartographer, Architect, Security analysis, Framework translation planner, and, when you ask, Code translation. The run does not stop for a human approval gate. You choose deterministic mode or LLM mode, and you choose whether to stop before code translation or to continue through it.

## Web frameworks

Micro-Focus translates these web frameworks: Spring Boot, Axon Framework, NestJS, React, Django, Flask, and ASP.NET Core. On those stacks it also recognises the CQRS and messaging frameworks Eventuate, Lagom, MediatR, NServiceBus, and Wolverine. An application estate translates onto an application language such as Java 21, Python 3, Go, Kotlin, TypeScript, C#, Rust, Scala, Swift, or JavaScript.

## Data engineering frameworks

Micro-Focus translates these data engineering frameworks: Databricks, Azure Data Factory, BigQuery with Dataform, and Snowflake with dbt. Databricks notebooks and Asset Bundles, Data Factory pipelines, Dataform models, and dbt models are the inputs. A data-engineering estate translates only onto another of those platforms.

## How to use it

Select the source folder. Use the plan command to stop once the framework translation plan is written. Use the translate command to continue into code translation. Name the target once, and choose deterministic or LLM mode once. The first 10 pipeline runs on an account are free. After that, a license is $10 a month for unlimited runs.

## Data

The plugin reads the source folder inside your Claude conversation and writes the run under that folder in `.micro-focus`. The account ledger stores an account id and how many free runs have been used. Source code is not sent to another service.
