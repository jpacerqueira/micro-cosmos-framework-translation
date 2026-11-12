# Entitlement

One pipeline start is one usage. A plan run and a translate run each count as one. Deterministic mode and LLM mode each count as one.

The first 5 runs on an account are free. After that, a license costs $15 a month and allows unlimited runs. This $15 is the Micro-Cosmos license. Anthropic's directory does not collect it. Claude usage stays on the user's own Claude subscription.

The ledger is `<source>/.micro-cosmos/account-ledger.json`. Before the pipeline starts, run:

```
python3 entitlement/entitlement.py consume --ledger "<source>/.micro-cosmos/account-ledger.json" --account "<account id>"
```

Ask the user for the account id. If the command exits with an error, do not start the pipeline. Tell the user: the first 5 runs are free, and a license is $15 a month for unlimited runs.

A run with an active monthly subscription does not increase `free_runs_used`.
