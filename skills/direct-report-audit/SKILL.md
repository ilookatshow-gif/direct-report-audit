---
name: direct-report-audit
description: Analyze a normalized local Yandex Direct placement CSV/TSV with exact sums, CPC/CPA and threshold-based manual-review candidates; not an API connector or campaign optimizer.
---

Use the installed `direct-report-audit` command if available; otherwise run `python3 <module-path>/direct_report_audit.py`. Read the module README if headers/numeric formats need normalization.

Start with `--json doctor`, then `schema`. Audit only the exact local export the user selected. Use stated thresholds; if defaults are used, identify them as demonstration choices, not validated norms.

Examples:

```sh
direct-report-audit --json doctor
direct-report-audit --json audit /local/private/placements.tsv --min-clicks 30 --min-cost 1500 --max-cpa 2000
direct-report-audit --json audit examples/synthetic-placements.csv --max-cpa 1000
```

Report totals, row/placement counts, threshold reasons and missing business context. Check attribution lag, tracking and downstream lead quality before proposing decisions. Candidate rows are not a blocklist. Never upload raw exports/results to a public repo or change campaigns through this tool.

The supplied example is synthetic. Do not present its numbers as a client outcome. Do not rerun author onboarding as part of audits; only an explicit installation/onboarding task may write its selected state-file.
