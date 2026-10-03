"""Fixed invented values, including deliberately difficult privacy probes."""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Case:
    id: str
    group: str
    text: str
    spans: tuple[tuple[int, int], ...]

    def manifest(self):
        return asdict(self)


def sensitive(case_id, group, prefix, value, suffix=""):
    return Case(case_id, group, prefix + value + suffix, ((len(prefix), len(prefix) + len(value)),))


def inn_person(prefix):
    first = sum(int(d) * w for d, w in zip(prefix, (7, 2, 4, 10, 3, 5, 9, 4, 6, 8), strict=True)) % 11 % 10
    value = prefix + str(first)
    last = sum(int(d) * w for d, w in zip(value, (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8), strict=True)) % 11 % 10
    return value + str(last)


def inn_org(prefix):
    check = sum(int(d) * w for d, w in zip(prefix, (2, 4, 10, 3, 5, 9, 4, 6, 8), strict=True)) % 11 % 10
    return prefix + str(check)


CASES = [
    sensitive("name_full", "names", "Сотрудник: ", "Иванов Иван Иванович"),
    sensitive("name_declined", "names", "Передайте ", "Иванову Ивану Ивановичу"),
    sensitive("name_uppercase", "names", "Сотрудник: ", "ИВАНОВ ИВАН ИВАНОВИЧ"),
    sensitive("name_initials_after", "names", "Контакт: ", "Иванов И. И."),
    sensitive("name_initials_before", "names", "Контакт: ", "И. И. Иванов"),
    sensitive("name_yo", "names", "Сотрудник: ", "Фёдоров Пётр Семёнович"),
    sensitive("name_hyphenated", "names", "Сотрудник: ", "Петрова-Водкина Анна Сергеевна"),
    sensitive("name_two_words", "names", "Контакт: ", "Анна Смирнова"),
    sensitive("name_lowercase", "names", "Контакт: ", "иванов иван иванович"),
    sensitive("name_transliterated", "names", "Контакт: ", "Ivanov Ivan Ivanovich"),
    sensitive("name_foreign", "names", "Сотрудник: ", "Смит Джон"),
    sensitive("name_zero_width", "names", "Сотрудник: ", "Ива\u200bнов Иван Иванович"),
    sensitive("address_markers", "addresses", "Адрес: ", "г. Москва, ул. Тестовая, д. 15, кв. 7"),
    sensitive("address_marker_after", "addresses", "Адрес: ", "Тестовый проспект 88"),
    sensitive("address_apartment", "addresses", "Адрес: ", "Тестовая 44 кв 78"),
    sensitive("address_lowercase", "addresses", "Адрес: ", "ул. тестовая, д. 15, кв. 7"),
    sensitive("address_ocr", "addresses", "Адрес: ", "ул. Теcтовая, д. 15, кв. 7"),
    sensitive("address_zero_width", "addresses", "Адрес: ", "ул. Тес\u200bтовая, д. 15, кв. 7"),
    sensitive("email_ascii", "contacts", "Email: ", "synthetic@example.test"),
    sensitive("email_internal", "contacts", "Адрес: ", "synthetic@northstar.corp"),
    sensitive("email_plus", "contacts", "Email: ", "synthetic+demo@example.test"),
    sensitive("email_cyrillic", "contacts", "Почта: ", "синтетика@пример.рф"),
    sensitive("email_spoken", "contacts", "Почта: ", "synthetic собака example точка test"),
    sensitive("phone_plus7", "contacts", "Телефон: ", "+7 (999) 123-45-67"),
    sensitive("phone_eight", "contacts", "Телефон: ", "8 999 123 45 67"),
    sensitive("phone_compact", "contacts", "Телефон: ", "79991234567"),
    sensitive(
        "phone_spoken",
        "contacts",
        "Телефон: ",
        "восемь девять девять девять один два три четыре пять шесть семь",
    ),
    sensitive("phone_ocr", "contacts", "Телефон: ", "+7 (999) I23-45-67"),
    sensitive("snils_valid", "identifiers", "СНИЛС: ", "112-233-445 95"),
    sensitive("snils_bad_checksum", "identifiers", "СНИЛС: ", "112-233-445 94"),
    sensitive("inn_person", "identifiers", "ИНН: ", inn_person("9900123456")),
    sensitive("inn_org", "identifiers", "ИНН: ", inn_org("990012345")),
    sensitive("ogrn", "identifiers", "ОГРН: ", "109990012345" + str(int("109990012345") % 11 % 10)),
    sensitive("ogrnip", "identifiers", "ОГРНИП: ", "39900123456789" + str(int("39900123456789") % 13 % 10)),
    sensitive("passport", "identifiers", "Паспорт: ", "4510 123456"),
    sensitive("passport_ocr", "identifiers", "Паспорт: ", "45I0 I23456"),
    sensitive("card_test", "identifiers", "Карта: ", "4242 4242 4242 4242"),
    sensitive("card_bad_checksum", "identifiers", "Карта: ", "4242 4242 4242 4243"),
    sensitive("iban", "identifiers", "IBAN: ", "DE89 3704 0044 0532 0130 00"),
    sensitive("kpp", "identifiers", "КПП: ", "990001001"),
    sensitive(
        "secret_pem", "secrets", "", "-----BEGIN PRIVATE KEY-----\nSYNTHETIC\n-----END PRIVATE KEY-----"
    ),
    sensitive("secret_github", "secrets", "Token: ", "gh" + "p_" + "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"),
    sensitive("secret_stripe", "secrets", "API key: ", "sk_live_" + "AbCdEfGhIjKlMnOpQrStUvWx"),
    sensitive("secret_npm", "secrets", "Token: ", "npm_" + "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"),
    sensitive(
        "secret_bearer", "secrets", "Authorization: " + "Bearer ", "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
    ),
    sensitive(
        "secret_dsn",
        "secrets",
        "Database: ",
        "postgresql" + "://synthetic:" + "DemoPasswordAbc123!" + "@db.example/demo",
    ),
    sensitive("secret_ru_api_key", "secrets", "API-ключ: ", "AbCdEfGhIjKlMnOpQrStUvWx"),
    sensitive("secret_password_en", "secrets", 'password: "', "DemoPasswordAbc123!", '"'),
    sensitive("secret_password_ru", "secrets", 'пароль: "', "DemoPasswordAbc123!", '"'),
    sensitive("secret_unlabelled", "secrets", "", "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"),
]

BENIGN = [
    ("policy_ru", "Кто согласует доступ к рабочей системе?"),
    ("policy_en", "Explain the approved model gateway policy."),
    ("date", "Дата проверки: 04.10.2026."),
    ("version", "Версия приложения: 1.2.3."),
    ("request_number", "Номер заявки: 12345."),
    ("budget", "Лимит проекта: 250000 рублей."),
    ("password_policy", "Пароль должен быть длинным и уникальным."),
    ("snils_policy", "СНИЛС проверяется по контрольной сумме."),
    ("inn_policy", "ИНН организации состоит из десяти цифр."),
    ("address_policy", "Адрес клиента хранится в защищённом контуре."),
    ("generic_title", "Система Управления Доступом"),
    ("uuid", "Идентификатор: 123e4567-e89b-12d3-a456-426614174000"),
    ("quantity", "Обработано 128 документов за 64 секунды."),
    ("math", "Сумма чисел 42 и 7 равна 49."),
]
CASES.extend(Case(case_id, "benign", text, ()) for case_id, text in BENIGN)
