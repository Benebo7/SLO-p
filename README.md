# SLO-P

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![Prometheus](https://img.shields.io/badge/prometheus-rules%20%26%20promql-orange)

A lightweight CLI for calibrating SLO objectives against Prometheus historical metrics and generating Prometheus recording and multi-window burn-rate alerting rules.

Instead of guessing targets like `0.999` blindly, `slop` queries your actual Prometheus history (`7` or `30` days), computes how often your service met its good-event threshold, applies an error-budget safety margin, updates your YAML in place (preserving comments and formatting), and compiles standard Prometheus rule files.

## Features

- **Historical calibration (`slop check`):** Queries `/api/v1/query_range` concurrently (up to 4 workers sharing an `httpx.Client` session) and suggests realistic objectives with a safety buffer below observed compliance.
- **Format-preserving YAML updates:** Uses `ruamel.yaml` round-trip parsing so `--write` updates `objective` values without wiping comments, indentation, or producing noisy `git diff`s.
- **Prometheus rule generation (`slop gen`):** Outputs one rule group per SLO containing `sli_good` recording rules, rolling `error_ratio*` / `compliance_*` series, and Google SRE Workbook fast/slow multi-window burn-rate alerts.

## Installation

Requires Python 3.10+.

Using `uv`:

```bash
uv venv
source .venv/bin/activate
uv pip install -e .
```

Using `pip`:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Configuration

Define your Prometheus endpoint and SLO list in a YAML file (see [example.yaml](example.yaml)):

```yaml
prometheus:
  url: http://localhost:9090
  token:

slos:
  - name: api-latency
    query: histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket[5m])))
    operator: <
    threshold: 0.09
    objective: 0.99
```

| Field | Required | Description |
| :--- | :--- | :--- |
| `prometheus.url` | Yes | Base URL of your Prometheus / Thanos / Mimir HTTP API. |
| `prometheus.token` | No | Optional Bearer token sent in the `Authorization` header. |
| `slos[].name` | Yes | Human-readable SLO name (sanitized into metric/alert names). |
| `slos[].query` | Yes | PromQL expression returning a numeric series (no comparison suffix). |
| `slos[].operator` | Yes | Good-sample operator: `<`, `<=`, `>`, `>=`, `==`, or `!=`. |
| `slos[].threshold` | Yes | Numeric threshold paired with `operator` to classify a good sample. |
| `slos[].objective` | For `gen` | Target compliance ratio strictly between `0` and `1` (populated by `check -w`). |

## Usage

### Calibrate objectives (`check`)

```bash
# Dry-run calibration over the last 7 days
slop check example.yaml

# Calibrate over 30 days and write objectives back to the YAML file
slop check example.yaml --days 30 --write
```

| Option | Short | Default | Description |
| :--- | :--- | :--- | :--- |
| `--days` | `-d` | `7` | History window to query (`7` or `30` days). |
| `--write` | `-w` | `false` | Persist calibrated `objective` values back into the input YAML. |

### Generate Prometheus rules (`gen`)

```bash
# Generate rules.yaml from already-calibrated objectives
slop gen example.yaml

# Calibrate over 30 days, update the input YAML, and generate custom output
slop gen example.yaml -d 30 -c -o slo_rules.yaml
```

| Option | Short | Default | Description |
| :--- | :--- | :--- | :--- |
| `--days` | `-d` | `7` | Window used for calibration (with `-c`) and the `compliance_<days>d` rule. |
| `--check` | `-c` | `false` | Run `check` with `--write` before generating rules. |
| `--output` | `-o` | `rules.yaml` | Destination path for the generated Prometheus rules YAML. |

## How It Works

### Calibration math (`slop check`)

1. Fetches samples from `/api/v1/query_range` using `step="1m"` for 7 days (`10,080` samples) and `step="5m"` for 30 days (`8,640` samples) to stay within Prometheus's default 11,000-point-per-series limit.
2. Filters non-finite values (`NaN`, `Inf`) and measures `compliance = good / total` using the SLO's good-condition operator and threshold.
3. Subtracts a proportional error-budget buffer:
   ```text
   margin = max(0.0001, (1.0 - compliance) * 0.25)
   adjusted = max(0.0, compliance - margin)
   ```
4. Floors `adjusted` according to target precision (`4` decimals for `>= 0.999`, `3` for `>= 0.99`, `2` below `0.99`), capping a `100%` clean window at `0.9999`.

### Generated Prometheus rules (`slop gen`)

For each SLO, `slop` emits an isolated rule group (`slop_<slug>`, `interval: 1m`) — see [rules.yaml](rules.yaml) for a complete output example:

- **Recording rules:**
  - `slop:<slug>:sli_good`: evaluates `(<query>) <op> bool <threshold>` to emit `1` (good) or `0` (bad) each minute.
  - `slop:<slug>:error_ratio{5m,30m,1h,6h}`: `1 - avg_over_time(...:sli_good[window])`.
  - `slop:<slug>:compliance_<days>d` and `slop:<slug>:objective`: rolling compliance and target reference for Grafana dashboards.
- **Alerting rules** (based on Google *The SRE Workbook*, Ch. 5 multi-window burn-rate alerts, with `error_budget = 1 - objective`):
  - **Fast burn (`severity: page`, `for: 2m`):** `error_ratio1h` and `error_ratio5m` both exceed `min(0.99, 14.4 * error_budget)`.
  - **Slow burn (`severity: ticket`, `for: 15m`):** `error_ratio6h` and `error_ratio30m` both exceed `min(0.99, 6 * error_budget)`.

## Loading Rules in Prometheus

Add the generated file to `prometheus.yml`:

```yaml
rule_files:
  - "rules.yaml"
```

You can validate syntax before reloading Prometheus with:

```bash
promtool check rules rules.yaml
```

## Design References

The calibration workflow and generated alerting logic are grounded in Google's *The SRE Workbook*:

- **Chapter 2 (*Implementing SLOs*):** separates the SLI good-sample criteria (`query`, `operator`, `threshold`) from the historical `objective`, using real baseline data (`7d`/`30d`) rather than arbitrary targets.
- **Chapter 5 (*Alerting on SLOs*):** uses multi-window, multi-burn-rate alerts (`14.4x` over `1h`/`5m` for `page`, `6x` over `6h`/`30m` for `ticket`) to balance fast detection, clean reset times, and low noise.

## Contributing

Issues and pull requests are welcome. If you spot a bug, want to suggest improvements to the calibration model, or want to add support for other rule formats, feel free to open an issue or submit a PR.

