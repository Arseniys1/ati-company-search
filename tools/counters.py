"""Пересчитывает счётчики выгрузки по data/*.json.

Запуск: python tools/counters.py
"""

import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")


def digits(value):
    return re.sub(r"\D+", "", value or "")


def main():
    companies = json.load(open(os.path.join(DATA, "companies.json"), encoding="utf-8"))
    loads = json.load(open(os.path.join(DATA, "loads.json"), encoding="utf-8"))

    contacts = [c for company in companies for c in company["contacts"]]
    phones = [p for c in contacts for p in c["phones"]]
    phone_digits = [digits(p) for p in phones]
    emails = [c["email"] for c in contacts if c["email"]]
    skypes = [c["skype"] for c in contacts if c["skype"]]
    rows = loads["rows"]

    with_phone = {i for i, c in enumerate(companies) if any(x["phones"] for x in c["contacts"])}
    with_email = {i for i, c in enumerate(companies) if any(x["email"] for x in c["contacts"])}

    def line(label, value):
        print(f"{label:48}{value:>9,}".replace(",", " "))

    print("Компании и контакты")
    line("компаний", len(companies))
    line("записей контактных лиц", len(contacts))
    line("уникальных имён (strip + lower)", len({c["name"].strip().lower() for c in contacts}))
    line("записанных телефонов", len(phones))
    line("уникальных телефонов по цифрам", len({d for d in phone_digits if d}))
    line("из них >= 10 цифр", len({d for d in phone_digits if len(d) >= 10}))
    line("записанных e-mail", len(emails))
    line("уникальных e-mail", len({e.strip().lower() for e in emails}))
    line("записанных Skype", len(skypes))
    line("уникальных Skype", len({s.strip().lower() for s in skypes}))
    line("подтверждённых контактных записей", sum(1 for c in contacts if c["confirmed"]))
    line("компаний с телефоном", len(with_phone))
    line("компаний с e-mail", len(with_email))
    line("компаний с телефоном или e-mail", len(with_phone | with_email))
    line("компаний и с телефоном, и с e-mail", len(with_phone & with_email))
    line("компаний без телефона и e-mail", len(companies) - len(with_phone | with_email))

    routed = sum(1 for r in rows if r[1] != -1 and r[2] != -1)
    archived = sum(1 for r in rows if r[12] == 1)
    print("\nГрузы")
    line("грузов", len(rows))
    line("активных", len(rows) - archived)
    line("архивных", archived)
    line("с маршрутом (оба конца)", routed)
    line("без маршрута", len(rows) - routed)
    line("уникальных пар маршрутов", len({(r[1], r[2]) for r in rows if r[1] != -1 and r[2] != -1}))
    line("городов", len(loads["cities"]))
    line("наименований грузов", len(loads["cargos"]))
    line("со ставкой", sum(1 for r in rows if r[7] not in (None, 0)))
    line("с расстоянием", sum(1 for r in rows if r[3] not in (None, 0)))


if __name__ == "__main__":
    main()
