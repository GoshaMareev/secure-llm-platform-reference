"""Export the measured synthetic pilot as a report and portfolio evidence snapshot."""

import argparse
import hashlib
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GROUP_LABELS = {
    "names": "Names",
    "addresses": "Addresses",
    "contacts": "Contacts",
    "identifiers": "Russian identifiers & cards",
    "secrets": "Secrets",
    "benign": "Benign text",
}


def comparison_rows(report):
    rows = []
    for group, values in report["groups"].items():
        field, denominator = (
            ("benign_unchanged", "benign_cases")
            if group == "benign"
            else ("protected_values", "sensitive_values")
        )
        cells = [f"{values[name][field]}/{values[name][denominator]}" for name in ("cloudru", "presidio")]
        rows.append((GROUP_LABELS[group], *cells))
    return rows


def export(report, callbacks, date, portfolio):
    if any(value["unavailable"] for value in report["summary"].values()):
        raise ValueError("Cannot publish an incomplete scanner comparison")
    if callbacks["passed"] != callbacks["total"] or not callbacks["total"]:
        raise ValueError("Cannot publish failed callback checks")
    for relative, digest in report["source_sha256"].items():
        if hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() != digest:
            raise ValueError("Source changed after measurement: " + relative)
    evidence = {
        **report,
        "evaluation_date": date,
        "callbacks": callbacks,
        "callback_source_sha256": hashlib.sha256(
            (ROOT / "scripts/smoke_cloudru_pii.py").read_bytes()
        ).hexdigest(),
    }
    encoded = json.dumps(evidence, ensure_ascii=False, indent=2) + "\n"
    destination = ROOT / "docs/verification/cloudru-pii-results.json"
    destination.write_text(encoded)
    cloudru = evidence["summary"]["cloudru"]
    presidio = evidence["summary"]["presidio"]
    residual = evidence["residual"]
    proof = {
        "date": date,
        "cases": cloudru["cases"],
        "sensitiveValues": cloudru["sensitive_values"],
        "cloudruProtectedValues": cloudru["protected_values"],
        "benignCases": cloudru["benign_cases"],
        "benignUnchanged": cloudru["benign_unchanged"],
        "residualCases": residual["detected_cases"],
        "callbackPassed": callbacks["passed"],
        "callbackTotal": callbacks["total"],
        "mode": "shadow",
        "reportUrl": "/evidence/cloudru-pii.html",
        "suiteSha256": evidence["suite_sha256"],
        "reportSha256": hashlib.sha256(encoded.encode()).hexdigest(),
    }
    rows = comparison_rows(evidence)
    md_table = "\n".join(f"| {group} | {cloud} | {pres} |" for group, cloud, pres in rows)
    missed = ", ".join(cloudru["miss_ids"])
    markdown = f"""# Russian PII and secret pilot: measured results

Measured {date}. Local pinned Cloud.ru scanner, configured EN/RU Presidio adapter,
and native gateway callbacks. No hosted model inference. Mode remains **shadow**.

- Cloud.ru: **{cloudru["protected_values"]}/{cloudru["sensitive_values"]}** annotated values fully masked.
- Benign text: **{cloudru["benign_unchanged"]}/{cloudru["benign_cases"]}** unchanged.
- Residual scan: **{residual["detected_cases"]}/{residual["checked_cases"]}** cases after Presidio.
- Live callback and fault checks: **{callbacks["passed"]}/{callbacks["total"]}** passed.

| Group | Cloud.ru | Configured Presidio |
|---|---|---|
{md_table}

Counts mean complete annotated-value masking; the benign row means unchanged text.
Partial masking is a miss. Span annotations include formatting characters. Every
miss and benign false positive is retained in [the complete JSON](cloudru-pii-results.json).
Cloud.ru misses: {missed}.

The 64-case set has 50 sensitive values and 14 benign probes. It includes deliberate
OCR, lowercase, spoken and Unicode stress cases. This is an authored synthetic
probe suite, not independent production recall or F1. Secrets and addresses are
outside the configured Presidio policy, so aggregate totals do not rank the tools
in general. Presidio covers 7/10 contact probes versus Cloud.ru's 5/10.

Warm sequential local HTTP measurements (64 samples/backend): Cloud.ru p50
{cloudru["latency_p50_ms"]} ms / p95 {cloudru["latency_p95_ms"]} ms; Presidio p50
{presidio["latency_p50_ms"]} ms / p95 {presidio["latency_p95_ms"]} ms; residual scan
p95 {residual["latency_p95_ms"]} ms. These include local transport and adapters,
not hosted generation or a production latency SLA.

Residual findings are observations, not extra redaction or validated leak rates.
Callback checks use synthetic signed identities and call hooks directly; they
do not exercise browser SSO or paid inference. Checks cover input/output and audit,
embedding/rerank, scanner outage with mandatory Presidio preserved, capacity,
input count limits and denial before scan for unsigned identity.

Suite SHA-256: `{evidence["suite_sha256"]}`. The JSON records runtime image IDs,
source fingerprints and callback scope. [Reproduce the pilot](../cloudru-pii-pilot.md).
"""
    (ROOT / "docs/verification/cloudru-pii-results.md").write_text(markdown)
    if portfolio is None:
        return
    public = portfolio / "public/evidence"
    public.mkdir(parents=True, exist_ok=True)
    (public / "cloudru-pii-results.json").write_text(encoded)
    (portfolio / "src/data/cloudruPii.generated.json").write_text(json.dumps(proof, indent=2) + "\n")
    table = "".join(
        "<tr>"
        + "".join(
            f"<{'th' if index == 0 else 'td'}>{html.escape(cell)}</{'th' if index == 0 else 'td'}>"
            for index, cell in enumerate(row)
        )
        + "</tr>"
        for row in rows
    )
    misses = "".join(f"<li><code>{html.escape(case_id)}</code></li>" for case_id in cloudru["miss_ids"])
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Russian PII &amp; secrets — measured pilot</title><style>
:root{{color-scheme:dark}}*{{box-sizing:border-box}}body{{margin:0;background:#111411;color:#e9ece3;
font:16px/1.65 system-ui,sans-serif}}main{{max-width:1040px;margin:auto;padding:48px 24px 72px}}
a{{color:#bfce9f;text-underline-offset:4px}}a:focus-visible{{outline:2px solid #bfce9f;outline-offset:5px}}
h1{{font:clamp(2.5rem,7vw,4rem)/1.1 Georgia,serif;margin:18px 0 24px}}
h2{{font:1.8rem Georgia,serif;margin-top:40px}}
.kicker{{font:12px ui-monospace,monospace;text-transform:uppercase;letter-spacing:.15em;color:#bfce9f}}
.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin:32px 0}}
.metric{{border:1px solid #384334;padding:20px}}.metric strong{{display:block;font:2.4rem Georgia,serif}}
.metric span{{font-size:13px;color:#bbc2b5}}.table{{overflow-x:auto}}
table{{width:100%;border-collapse:collapse}}
th,td{{padding:14px 12px;text-align:left;border-bottom:1px solid #384334}}thead{{color:#bfce9f}}
code{{font-size:13px;overflow-wrap:anywhere}}.note{{color:#bbc2b5}}
li{{margin:5px 0}}details{{margin-top:24px}}
@media(max-width:500px){{main{{padding:28px 18px}}.metrics{{grid-template-columns:1fr 1fr;gap:10px}}
.metric{{padding:14px}}th,td{{padding:10px 8px;font-size:14px}}}}
</style></head><body><main>
<a href="/#production">← Portfolio</a>
<p class="kicker">Local synthetic evaluation · {html.escape(date)} · shadow</p>
<h1>Russian PII &amp; secrets,<br>measured.</h1>
<p>Cloud.ru guardrails-llm-filter runs after mandatory Presidio at the native LiteLLM gateway.
The pilot records aggregate detections. Enforcement remains a separate validation step.</p>
<div class="metrics">
<div class="metric"><strong>{cloudru["protected_values"]}/{cloudru["sensitive_values"]}</strong>
<span>Values fully masked by Cloud.ru</span></div>
<div class="metric"><strong>{cloudru["benign_unchanged"]}/{cloudru["benign_cases"]}</strong>
<span>Benign texts unchanged</span></div>
<div class="metric"><strong>{residual["detected_cases"]}/{residual["checked_cases"]}</strong>
<span>Cases with residual detections</span></div>
<div class="metric"><strong>{callbacks["passed"]}/{callbacks["total"]}</strong>
<span>Live callback checks passed</span></div>
</div>
<h2>Where each configured control helps</h2><div class="table"><table>
<caption>Complete annotated values masked; benign row counts unchanged texts.</caption>
<thead><tr><th scope="col">Group</th><th scope="col">Cloud.ru</th>
<th scope="col">Configured Presidio</th></tr></thead>
<tbody>{table}</tbody></table></div>
<p class="note">The 64-case suite contains 50 sensitive values and 14 benign probes, including difficult
OCR, lowercase, spoken and Unicode forms. Secrets and addresses are outside this Presidio policy.
Aggregate totals do not establish a general tool ranking or production recall. Partial masking is a miss;
annotations include formatting characters.</p>
<h2>Observed limits</h2><p>Cloud.ru missed lowercase and unusual names, some address/OCR forms,
Cyrillic or spoken email, compact/spoken/OCR phones, an invalid-checksum SNILS, an OCR passport and
a Russian password label. Presidio protected more contact probes: 7/10 versus 5/10.</p>
<details><summary>All {len(cloudru["miss_ids"])} Cloud.ru miss IDs</summary><ul>{misses}</ul></details>
<h2>Local performance and fault behavior</h2><p>Warm sequential HTTP p95: Cloud.ru
{cloudru["latency_p95_ms"]} ms, configured Presidio {presidio["latency_p95_ms"]} ms,
residual scan {residual["latency_p95_ms"]} ms. This excludes model inference and is not a production SLA.</p>
<p>Seven direct callback checks cover input/output and private audit, embedding/rerank, scanner outage,
capacity, input limits and unsigned identity denial. Presidio stays mandatory during scanner failure.
Residual detections do not change the returned content in shadow mode.</p>
<h2>Reproducible evidence</h2><p><a href="cloudru-pii-results.json">Download the full aggregate report</a>
 · <a href="https://github.com/cloud-ru-tech/guardrails-llm-filter">Upstream scanner</a></p>
<p class="note">No customer data, hosted model calls or real user identities were used.
The JSON includes miss IDs, runtime image IDs and source fingerprints; no prompts or original values.</p>
<p>Suite SHA-256<br><code>{html.escape(evidence["suite_sha256"])}</code></p>
</main></body></html>"""
    (public / "cloudru-pii.html").write_text(page)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--callbacks", type=Path, required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--portfolio-root", type=Path)
    args = parser.parse_args()
    export(
        json.loads(args.report.read_text()),
        json.loads(args.callbacks.read_text()),
        args.date,
        args.portfolio_root,
    )
    print("Exported measured Cloud.ru evidence with source fingerprint checks.")


if __name__ == "__main__":
    main()
