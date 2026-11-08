"""Small synthetic live scanner contract check; not a production recall benchmark."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/rag-assistant"))
from secure_rag.cloudru_pii import CloudruScanClient, ScanUnavailable

# These are invented fixtures and public test-card values, never customer data.
CASES = [
    ("ru_full_name", "Сотрудник: Иванов Иван Иванович", 5),
    ("ru_declined_name", "Передайте Иванову Ивану Ивановичу", 5),
    ("ru_initials", "Контакт: Иванов И. И.", 5),
    ("ru_phone", "Телефон: +7 (999) 123-45-67", 5),
    ("internal_email", "Адрес: synthetic@northstar.corp", 5),
    ("ru_snils", "СНИЛС: 112-233-445 95", 5),
    ("ru_passport", "Паспорт: 4510 123456", 5),
    ("ru_address", "Адрес: г. Москва, ул. Тестовая, д. 15, кв. 7", 5),
    ("test_card", "Карта: 4242 4242 4242 4242", 5),
    ("private_key", "-----BEGIN PRIVATE KEY-----\nSYNTHETIC\n-----END PRIVATE KEY-----", 3),
    ("benign_ru", "Кто согласует доступ к рабочей системе?", None),
    ("benign_en", "Explain the approved model gateway policy.", None),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://cloudru-filter:9080")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    client = CloudruScanClient(args.url)
    results = []
    for case_id, text, category in CASES:
        try:
            summary = client.scan([text])
            passed = (
                category in summary.data_types and summary.changed_text_count == 1
                if category is not None else summary.match_count == 0 and summary.changed_text_count == 0
            )
            result = {"id": case_id, "passed": passed, **summary.event()}
        except ScanUnavailable as error:
            result = {"id": case_id, "passed": False, "status": "unavailable", "reason": str(error)}
        results.append(result)
    report = {
        "scope": "12 fixed synthetic scanner cases; no production quality claim",
        "passed": sum(item["passed"] for item in results), "total": len(results), "cases": results,
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
