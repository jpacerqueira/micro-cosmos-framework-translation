# Entitlement

One pipeline start is one usage. A plan run and a translate run each count as one. Deterministic mode and LLM mode each count as one. Phases inside a run do not count again.

The first 10 runs on an account are free. After that, a license costs $10 a month and allows unlimited runs. Claude usage stays on the user's own Claude subscription. This $10 is the Micro-Focus license. Anthropic's directory does not collect it.

The account ledger is the authority. It lives at `~/.micro-focus/accounts/<account_id>.json`, where `<account_id>` is the email with every character that is not a letter or digit replaced by `_`. A reinstall of the plugin does not reset the count while that file remains. Do not delete the ledger, and do not lower `free_runs_used`.

Before Observer, run this from the plugin root:

```
python3 entitlement/entitlement.py consume --ledger ~/.micro-focus/accounts/<account_id>.json --account <account_id>
```

If the command exits with an error, do not create a run directory. Tell the user: the first 10 runs are free, and a license is $10 a month for unlimited runs.

A run with an active monthly subscription does not increase `free_runs_used`.

The rules live in this `entitlement` folder, not in a folder named `license`, because that name is the same path as the `LICENSE` file on a case-insensitive disk.
