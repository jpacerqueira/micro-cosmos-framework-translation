---
name: project-owner-profile
description: Project owner profile — role, knowledge level, and working style on Micro-Cosmos
metadata:
  type: user
---

The project owner is a senior engineer and product owner at Qodea. They own the end-to-end design of the pipeline — gate definitions, phase ordering, agent responsibilities, and UI. Comfortable with Python, FastAPI, async code, ADK internals, and the full Docker-based container setup.

They run live LLM and deterministic pipeline executions locally and interpret Docker container logs directly. They identify bugs from raw ADK tracebacks and container output without needing translation.

They work at the feature-architecture level: plans new phases (like Gate 4.5), reviews them before implementation, and expects the assistant to propose changes first and implement only after explicit approval ("go" / "yes apply"). They monitor running containers and ask for diagnostic analysis when issues appear in logs.

They drive the project from a product angle: ask about edge cases (seam bonding, concurrent runs, ASK tab impact) and expect architectural safety analysis, not just code fixes.
