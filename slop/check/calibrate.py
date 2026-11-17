import math
import operator
import time

import httpx

OPERATORS = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
}

# Margin settings used to keep a safety buffer below observed historical compliance.
MIN_MARGIN = 0.0001
ERROR_BUDGET_BUFFER = 0.25
REQUEST_TIMEOUT = 15.0


def _fetch_metric_values(prom_url, prom_token, query, days, client=None):
    """Query Prometheus query_range and return all finite numeric sample values."""
    end_ts = int(time.time())
    start_ts = end_ts - (days * 86400)
    url = f"{prom_url.rstrip('/')}/api/v1/query_range"
    step = "1m" if days == 7 else "5m"

    headers = {}
    if prom_token:
        headers["Authorization"] = f"Bearer {prom_token}"

    params = {
        "query": query,
        "start": start_ts,
        "end": end_ts,
        "step": step,
    }

    requester = client or httpx
    response = requester.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
    if response.is_error:
        try:
            err_msg = response.json().get("error")
        except ValueError:
            err_msg = None
        if err_msg:
            raise ValueError(f"Prometheus API error ({response.status_code}): {err_msg}")
        response.raise_for_status()

    payload = response.json()
    if payload.get("status") != "success":
        raise ValueError(payload.get("error") or "Prometheus query did not succeed.")

    values = []
    for series in payload.get("data", {}).get("result", []):
        for _, raw_value in series.get("values", []):
            try:
                numeric = float(raw_value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(numeric):
                values.append(numeric)

    if not values:
        raise ValueError("No valid metric samples returned by Prometheus.")

    return values


def calibrate_slo(prom_url, prom_token, slo, days, client=None):
    """Query historical metrics in Prometheus and return a calibrated SLO objective."""
    query = slo.get("query")
    op = slo.get("operator")
    threshold = slo.get("threshold")

    if (
        not isinstance(query, str)
        or not query.strip()
        or op not in OPERATORS
        or isinstance(threshold, bool)
        or not isinstance(threshold, (int, float))
        or not math.isfinite(threshold)
    ):
        raise ValueError(f"Invalid SLO data: {slo}")

    values = _fetch_metric_values(prom_url, prom_token, query, days, client=client)

    is_good = OPERATORS[op]
    good = sum(1 for val in values if is_good(val, float(threshold)))
    compliance = good / len(values)

    margin = max(MIN_MARGIN, (1.0 - compliance) * ERROR_BUDGET_BUFFER)
    adjusted = max(0.0, compliance - margin)

    if adjusted >= 0.999:
        decimals = 4
    elif adjusted >= 0.99:
        decimals = 3
    else:
        decimals = 2

    scale = 10**decimals
    # Small epsilon avoids IEEE-754 representations (e.g. 94.99999999999999) flooring down by 1 unit.
    return round(math.floor(adjusted * scale + 1e-9) / scale, decimals)
