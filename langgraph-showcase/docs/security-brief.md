# Security Coverage in the Micro-Cosmos Pipeline

A plain-language explanation of what the pipeline's Security phase actually checks for, aimed at a reader with a CS background but not a security specialism.

## There is a dedicated Security phase

`SECURITY` is one of the pipeline's phases, running after Architect and before Feature Specifier:

```
Observer → Gate 1 → Cartographer → Gate 2 → Architect → Gate 3
→ Security → Gate 4 → Feature Specifier → Gate 4.5 → ...
```

- **Agent:** `security_agent`
- **Output artifact:** `security_report.json` — findings with CWE IDs, severity, confirmed/affects_migration flags, risk ranking, and remediation notes
- **Gate:** `GATE_4`, a human security-architect sign-off, reviewing `security_report.json` plus an optional `trivy_report.json`

There are actually **two** security checkpoints across a full run: this source-side Security phase at Gate 4, and a second Trivy scan on the *generated* output feeding Gate 5 — so translation-introduced vulnerabilities are checked too, not just ones inherited from the original codebase.

## Two independent tools feed one LLM reviewer

Rather than trusting a single method, three things happen and get cross-checked:

1. **A hand-written pattern scanner** (regex-based) — cheap, deterministic, looks for known-bad code shapes.
2. **Trivy** — an industry-standard external tool that checks your dependencies (npm/Maven/pip packages, etc.) against public CVE databases, and separately scans for accidentally-committed secrets (API keys, passwords in plaintext files).
3. **An LLM agent** that reads the output of both, then goes and *reads the actual code* to confirm each finding is real (not a false positive) and to catch things the mechanical tools miss — auth logic, business-context risk.

This hybrid matters because pure LLM analysis can hallucinate or miss things, and pure pattern-matching can't understand context (e.g. "is this SQL string concatenation actually reachable by user input?"). Having the LLM confirm mechanical findings against real code is the mitigation for both failure modes.

## What's actually checked (grouped in plain terms)

| Category | What it means in practice |
|---|---|
| **Secrets exposed in code** | Passwords, API keys, tokens hardcoded as string literals instead of pulled from a vault/env var |
| **Injection attacks** | Places where user input gets concatenated straight into a SQL query, a shell command, or a template — the classic "attacker types code where you expected data" family |
| **Weak cryptography** | Use of broken/outdated algorithms (MD5, SHA1) or insecure random-number generation for things like session tokens |
| **Path traversal** | File paths built from user-supplied input without sanitisation — could let someone read `../../etc/passwd`-style files |
| **Insecure deserialization** | Code that reconstructs objects from untrusted data (Python `pickle`, Java's `ObjectInputStream`) — a well-known route to remote code execution |
| **Information leakage** | Debug mode left on in production, stack traces shown to users, sensitive data written to logs |
| **Auth/access-control gaps** | Missing permission-check annotations, CSRF protection disabled, overly permissive CORS (any website can call your API), wildcard allowed hosts |
| **SSRF** | Server-side code that fetches a URL supplied by the user — a way to trick your server into hitting internal-only systems |
| **Dependency vulnerabilities (supply chain)** | Known CVEs in the third-party libraries you depend on — this is Trivy's job, not the regex scanner's |

Each finding carries a **CWE ID** (Common Weakness Enumeration — the industry-standard taxonomy number, e.g. CWE-89 for SQL injection) and a severity from CRITICAL down to INFO, so findings map cleanly onto how security teams and compliance frameworks already talk about risk.

## What's explicitly not covered

Worth being upfront about this with a client:

- **No memory-safety analysis** (buffer overflows, use-after-free, out-of-bounds access) — relevant for C specifically, and not checked by either the pattern scanner or Trivy. This is a real gap for C source estates, not a theoretical one.
- **No business-logic flaws** — e.g. "can user A access user B's order by changing an ID in the URL" (IDOR) isn't something a static scanner catches; it requires understanding what the application is *for*.
- **No rate-limiting / brute-force protection checks.**
- **No infrastructure/container misconfiguration** — Trivy is deliberately run in vulnerability+secrets mode only, not its misconfig-scanning mode.
- **No penetration testing** — this is static analysis of source code, not a live attack simulation.

## One honest caveat

If a run is in **deterministic mode** (no LLM calls — the fast, free default), the security phase only produces raw, unconfirmed pattern-matches — nobody has read the code to confirm they're real or assessed how they matter for the migration. That distinction is worth stating explicitly to a client evaluating output quality, since it changes how much weight the findings should carry.
