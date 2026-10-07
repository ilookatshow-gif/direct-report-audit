# direct-report-audit

Standalone offline Yandex Direct placement-export audit. Python 3.9+, standard library only: no Harness, credentials, API, or network. Aggregates placements, calculates totals/CPC/CPA, and flags **manual-review candidates**. No automatic exclusions, campaign changes, or savings claims.

```sh
python3 direct_report_audit.py --json doctor
python3 direct_report_audit.py schema
python3 direct_report_audit.py --json audit examples/synthetic-placements.csv --max-cpa 1000
python3 -B -m unittest discover -s tests -v
```

Optional POSIX local install, with no downloads or pip. Existing commands are not overwritten without `--replace`:

```sh
python3 install.py --prefix "$HOME/.local"
export PATH="$HOME/.local/bin:$PATH"
direct-report-audit --json doctor
direct-report-audit onboard --state-file "$HOME/.local/state/direct-report-audit/onboarding.json"
```

For Windows/no installation, invoke the Python file by absolute path. `onboard` writes only the explicitly chosen local marker and shows author information once per marker. Audits never read/write that state or repeat advertising.

## Input contract

UTF-8 (optional BOM), comma/semicolon CSV or TSV, exactly these five headers, in any order:

```text
Placement,Impressions,Clicks,Cost,Conversions
```

Non-negative numbers; integer Impressions/Clicks; fractional Conversions are preserved. Decimal dot/comma; space/NBSP/narrow-NBSP thousands grouping in groups of three. Up to 18 numeric digits per value. Quote decimal commas and comma-containing names in comma CSV. Reject mixed dot/comma notation (`1,234.56`), exponent notation, currency symbols, NaN/Infinity, missing cells and malformed rows. Error means **no partial report**.

Cost must already be in currency units, **not raw API micros**. Normalize native export headings/metadata locally; this is not a universal native Direct/API export parser. Remove summary/total/footer rows; known total labels are rejected. Do not mix currencies, reporting periods, goals or attribution models. `--currency` labels data without conversion: 1–12 ASCII letters/digits with optional `_.-`, e.g. RUB/USD.

Leading empty lines and `#` comments before the header are allowed. `# SYNTHETIC` marks invented educational input in the output. The bundled example is synthetic, not a client case or evidence of effectiveness. Placements group by exact name after trimming outer whitespace, not case-insensitive/domain normalization. Duplicate export records are **not** automatically deduplicated. Limits: 25 MB, 100,000 rows.

## Review rules and JSON

```sh
direct-report-audit --json audit /local/private/placements.tsv \
  --min-clicks 30 --min-cost 1500 --max-cpa 2000 --min-conversions 2
```

Defaults are demonstration choices: min-clicks 20, min-cost 1000, min-conversions 1; max-CPA disabled. After aggregation, `zero_conversion_spend` flags positive cost with zero conversions and sufficient clicks/cost. `cpa_above_threshold` additionally needs minimum conversions and exact CPA strictly above the explicit threshold. Check tracking, attribution lag, period, sample size and downstream CRM quality before decisions. These are not blocklist recommendations or causal conclusions.

Success: `{"ok":true,"command":"audit","result":{...}}`, exit 0. Result includes input counts/delimiter/synthetic flag, currency, thresholds, totals, all placements/reasons, candidate_count and limitations. Impressions/Clicks are integers; Cost/Conversions are exact decimal strings; CPC/CPA are two-decimal strings or null for zero denominators. Totals use sums, not averages of ratios; threshold comparison uses unrounded CPA. Order: descending cost, then name.

JSON errors: `{"ok":false,"error":{"code":"invalid_input","message":"..."}}`, exit 2. `--json` works before/after subcommands; help/version are plain text. No advertising contaminates audit/doctor/schema output.

## Codex / Claude Code prompts

Install: “Read this module's README, run stdlib unit tests, install with install.py into my explicitly chosen local prefix, and run onboard once with my chosen local state-file. Do not change Harness/MCP config, access accounts, or publish data.”

Use: “Audit my local export with min-clicks=30, min-cost=1500, max-cpa=2000. Summarize totals and manual-review candidates with reasons/limitations. Do not change campaigns or upload exports/results to GitHub or other services.” Local CLI output passed to a cloud agent is subject to that provider's data policy. Optional companion instructions: `skills/direct-report-audit/SKILL.md`; no automatic skill registration.

## Author

New module by **Дмитрий Лукашов (Dmitry Lukashov)**. [Telegram](https://t.me/lookatsoul) · [Implementation and automation](https://lookatshow.ru/executive?utm_source=github&utm_medium=open_module&utm_campaign=direct-report-audit&utm_content=readme).

MIT covers this new code/documentation only, not user data or third-party products/names/API rights. See LICENSE/NOTICE.md. No Harness/third-party source code or skills copied.
