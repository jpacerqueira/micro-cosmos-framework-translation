# Frameworks Micro-Cosmos translates

Micro-Cosmos is an application framework translation. Name the source framework and the target in the run record. Do not claim support for a framework that is not in this list.

## Web frameworks

- Spring Boot, including Spring MVC, Spring Data, and Spring Batch
- Axon Framework
- NestJS
- React
- Django
- Flask
- ASP.NET Core

CQRS and messaging frameworks recognised on those web stacks:

- Eventuate
- Lagom
- MediatR
- NServiceBus
- Wolverine

An application estate translates onto an application language: `java21`, `python3`, `go`, `kotlin`, `typescript`, `csharp`, `rust`, `scala`, `swift`, or `javascript`. It does not translate onto a data-engineering platform.

## Data engineering frameworks

- Databricks, including notebooks and Databricks Asset Bundles
- Azure Data Factory
- BigQuery with Dataform
- Snowflake with dbt

A data-engineering estate translates only onto another platform in this list: `databricks`, `bigquery_dataform`, or `snowflake_dbt`. It does not translate onto an application language, and it does not translate onto itself.

## How a run uses this list

Observer records which of these frameworks the source folder actually uses, with the file or manifest that shows it, on `ir_graph.json` as `cqrs_framework_hints`. The framework translation planner maps each detected framework to the chosen target in `framework_translation_plan.md`. If the source matches none of these, say so in `gaps.md` and continue with a language translation only. Do not invent a framework name.
