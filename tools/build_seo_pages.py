"""Генерирует статические страницы компаний, каталог и sitemap для поисковиков.

Запуск: python tools/build_seo_pages.py

Страницы кладутся в company/<id>.html, каталог — catalog.html и catalog/<буква>.html.
Данные берутся из data/companies.json и data/loads.json.
"""

import datetime
import html
import json
import os
import re
import shutil
from collections import defaultdict
from urllib.parse import quote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
BASE = "https://arseniys1.github.io/ati-company-search/"

PERIOD = "24.04.2026 — 11.11.2026"
LOADS_ON_PAGE = 10
CITY_LINKS = 8
OTHER_LETTER = "прочее"
ALPHABET = "абвгдеёжзийклмнопрстуфхцчшщъыьэюяabcdefghijklmnopqrstuvwxyz0123456789"


def esc(value):
    return html.escape(str(value if value is not None else ""), quote=True)


def norm(value):
    return re.sub(r"\s+", " ", str(value or "").strip().lower().replace("ё", "е"))


def slug_letter(name):
    first = norm(name)[:1]
    return first if first and first in ALPHABET else OTHER_LETTER


def fmt_money(value):
    if not value:
        return ""
    return f"{round(value):,}".replace(",", " ")


def fmt_num(value):
    if value in (None, 0, ""):
        return ""
    number = round(float(value) * 100) / 100
    text = f"{number:,.2f}".rstrip("0").rstrip(".")
    return text.replace(",", " ")


def fmt_date(value):
    if not value:
        return ""
    parts = value.split("-")
    return f"{parts[2]}.{parts[1]}.{parts[0]}" if len(parts) == 3 else value


def head(prefix, title, description, canonical, json_ld):
    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<meta name="robots" content="index, follow">
<meta name="geo.region" content="RU">
<link rel="canonical" href="{esc(canonical)}">
<link rel="icon" href="{prefix}assets/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="{prefix}assets/page.css">
<script type="application/ld+json">{json.dumps(json_ld, ensure_ascii=False)}</script>
</head>
<body>
<header class="bar">
  <a class="logo" href="{prefix}index.html">ATI</a>
  <a href="{prefix}index.html">поиск по базе грузовладельцев</a>
  <a class="right" href="{prefix}catalog.html">каталог компаний</a>
</header>
"""


FOOT = """<footer class="foot">
  <p>База собрана с сайта ati.su по грузовладельцам. Период сбора данных: 24.04.2026 — 11.11.2026.</p>
  <p>Связаться: <a href="https://t.me/Arseniys11" rel="noopener">@Arseniys11</a></p>
</footer>
</body>
</html>
"""


def company_page(company, loads, neighbours):
    name = company["name"] or company["short"] or f"Компания {company['id']}"
    city = company["city"] or ""
    region = company["region"] or ""
    place = ", ".join(x for x in (city, region) if x)
    load_count = company["loads"] or 0
    canonical = f"{BASE}company/{company['id']}.html"

    title = f"{name} — контакты грузовладельца{', ' + city if city else ''} | база ATI"
    description = (f"{name}{', ' + place if place else ''}: телефоны, e-mail и контакты. "
                   f"{load_count} грузов в базе ATI за {PERIOD}.")

    org = {"@context": "https://schema.org", "@type": "Organization", "name": name, "url": canonical}
    if place:
        org["address"] = {"@type": "PostalAddress", "addressLocality": city,
                          "addressRegion": region, "addressCountry": "RU"}
    phones = [p for c in company["contacts"] for p in c["phones"]]
    if phones:
        org["telephone"] = phones[0]
    emails = [c["email"] for c in company["contacts"] if c["email"]]
    if emails:
        org["email"] = emails[0]

    rows = []
    if company.get("kind"):
        rows.append(("Тип", esc(company["kind"])))
    if place:
        rows.append(("Город", esc(place)))
    if company.get("rating"):
        rating = fmt_num(company["rating"])
        if company.get("ratingPct"):
            rating += f" ({company['ratingPct']}%)"
        rows.append(("Рейтинг ATI", esc(rating)))
    if company.get("recs"):
        rows.append(("Рекомендаций", f"{company['recs']:,}".replace(",", " ")))
    if company.get("docs"):
        rows.append(("Документы", esc(company["docs"])))
    rows.append(("Грузов в базе", f"{load_count:,}".replace(",", " ")))
    if company.get("first"):
        rows.append(("Период в логах", f"{fmt_date(company['first'])} — {fmt_date(company['last'] or company['first'])}"))
    rows.append(("ID в ATI", esc(company["id"])))

    contacts = []
    for contact in company["contacts"]:
        phones_html = " ".join(
            f'<a href="tel:{re.sub(r"[^0-9+]", "", phone)}">{esc(phone)}</a>' for phone in contact["phones"])
        email_html = (f'<a href="mailto:{esc(contact["email"])}">{esc(contact["email"])}</a>'
                      if contact.get("email") else "")
        extra = f'<span class="muted">skype: {esc(contact["skype"])}</span>' if contact.get("skype") else ""
        mark = " ✔" if contact.get("confirmed") else ""
        contacts.append(f'<tr><td>{esc(contact["name"])}{mark}</td><td>{phones_html}</td>'
                        f'<td>{email_html}{extra}</td></tr>')
    contacts_html = ('<table class="contacts"><tbody>' + "".join(contacts) + "</tbody></table>"
                     if contacts else "<p>Контакты не указаны.</p>")

    load_rows = []
    for load in loads[:LOADS_ON_PAGE]:
        route = " → ".join(x for x in (load["from"], load["to"]) if x) or "маршрут не указан"
        parts = [
            load["cargo"],
            f"{fmt_num(load['weight'])} т" if load["weight"] else "",
            f"ставка {fmt_money(load['price'])}" if load["price"] else "",
            f"{load['distance']:,} км".replace(",", " ") if load["distance"] else "",
        ]
        details = " · ".join(x for x in parts if x)
        load_rows.append(f'<tr><td>{fmt_date(load["add"])}</td><td>{esc(route)}</td>'
                         f'<td>{esc(details)}</td><td>{"архив" if load["archived"] else ""}</td></tr>')
    loads_html = ('<table class="loads"><tbody>' + "".join(load_rows) + "</tbody></table>"
                  if load_rows else "<p>Грузов этой компании в базе нет.</p>")

    neighbours_html = "".join(
        f'<li><a href="{other["id"]}.html">{esc(other["name"] or other["short"])}</a></li>' for other in neighbours)
    city_block = (f'<h2>Другие грузовладельцы в городе {esc(city)}</h2>'
                  f'<ul class="links">{neighbours_html}</ul>') if neighbours_html else ""

    body = f"""<main>
<h1>{esc(name)}</h1>
<p class="lead">{esc(" · ".join(x for x in (company.get("kind"), place) if x))}</p>
<h2>Контакты</h2>
{contacts_html}
<h2>Данные компании</h2>
<dl class="kv">{"".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows)}</dl>
<h2>Грузы компании ({load_count})</h2>
{loads_html}
<p class="more"><a href="../index.html#q={esc(quote(name))}">Найти компанию в поиске и посмотреть все грузы</a></p>
{city_block}
</main>
"""
    return head("../", title, description, canonical, org) + body + FOOT


def catalog_pages(companies):
    groups = defaultdict(list)
    for company in companies:
        groups[slug_letter(company["name"] or company["short"])].append(company)

    folder = os.path.join(ROOT, "catalog")
    if os.path.isdir(folder):
        shutil.rmtree(folder)
    os.makedirs(folder)

    index_items = []
    for letter in sorted(groups):
        items = sorted(groups[letter], key=lambda c: norm(c["name"] or c["short"]))
        index_items.append(
            f'<li><a href="catalog/{letter}.html">{esc(letter.upper())}</a> — {len(items):,}</li>'.replace(",", " "))

        rows = "".join(
            f'<tr><td><a href="../company/{c["id"]}.html">{esc(c["name"] or c["short"])}</a></td>'
            f'<td>{esc(c["city"] or "")}</td><td>{c["loads"]}</td></tr>' for c in items)
        page = head(
            "../",
            f"Каталог грузовладельцев на «{letter.upper()}» — база ATI",
            f"Список компаний-грузовладельцев на букву {letter.upper()} из базы ati.su: "
            f"{len(items)} компаний с контактами.",
            f"{BASE}catalog/{quote(letter)}.html",
            {"@context": "https://schema.org", "@type": "CollectionPage",
             "name": f"Каталог грузовладельцев на «{letter.upper()}»", "inLanguage": "ru-RU"})
        body = (f'<main><h1>Грузовладельцы на «{letter.upper()}»</h1>'
                f'<p class="lead">{len(items)} компаний из базы ati.su.</p>'
                f'<table class="catalog"><tbody>{rows}</tbody></table>'
                f'<p class="more"><a href="../index.html">← Поиск по базе</a></p></main>')
        with open(os.path.join(folder, f"{letter}.html"), "w", encoding="utf-8") as fh:
            fh.write(page + body + FOOT)

    page = head(
        "",
        "Каталог грузовладельцев — база ati.su с контактами",
        "Каталог компаний-грузовладельцев по алфавиту: контакты, телефоны, e-mail и грузы из базы ati.su.",
        f"{BASE}catalog.html",
        {"@context": "https://schema.org", "@type": "CollectionPage",
         "name": "Каталог грузовладельцев", "inLanguage": "ru-RU"})
    body = (f'<main><h1>Каталог грузовладельцев</h1>'
            f'<p class="lead">{len(companies):,} компаний из базы ati.su. Выберите букву.</p>'.replace(",", " ") +
            f'<ul class="letters">{"".join(index_items)}</ul>'
            f'<p class="more"><a href="index.html">← Поиск по базе</a></p></main>')
    with open(os.path.join(ROOT, "catalog.html"), "w", encoding="utf-8") as fh:
        fh.write(page + body + FOOT)
    return sorted(groups)


def sitemap(companies, letters, today):
    urls = ([f"{BASE}", f"{BASE}catalog.html"] +
            [f"{BASE}catalog/{quote(letter)}.html" for letter in letters] +
            [f"{BASE}company/{company['id']}.html" for company in companies])
    body = "".join(f"<url><loc>{esc(url)}</loc><lastmod>{today}</lastmod></url>" for url in urls)
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + body + "</urlset>\n")
    with open(os.path.join(ROOT, "sitemap.xml"), "w", encoding="utf-8") as fh:
        fh.write(xml)
    return len(urls)


def main():
    companies = json.load(open(os.path.join(DATA, "companies.json"), encoding="utf-8"))
    loads = json.load(open(os.path.join(DATA, "loads.json"), encoding="utf-8"))
    cities, cargos, rows = loads["cities"], loads["cargos"], loads["rows"]

    by_company = defaultdict(list)
    for row in rows:
        by_company[row[0]].append({
            "from": cities[row[1]] if row[1] >= 0 else "",
            "to": cities[row[2]] if row[2] >= 0 else "",
            "distance": row[3],
            "cargo": cargos[row[4]] if row[4] >= 0 else "",
            "weight": row[5],
            "price": row[7],
            "add": row[9] or row[10] or "",
            "archived": row[12] == 1,
        })

    by_city = defaultdict(list)
    for company in companies:
        if company["city"]:
            by_city[norm(company["city"])].append(company)

    folder = os.path.join(ROOT, "company")
    if os.path.isdir(folder):
        shutil.rmtree(folder)
    os.makedirs(folder)

    for position, company in enumerate(companies):
        loads_of_company = sorted(by_company.get(position, []), key=lambda x: x["add"], reverse=True)
        neighbours = []
        if company["city"]:
            same_city = [c for c in by_city[norm(company["city"])] if c["id"] != company["id"]]
            same_city.sort(key=lambda c: c["loads"] or 0, reverse=True)
            neighbours = same_city[:CITY_LINKS]
        with open(os.path.join(folder, f"{company['id']}.html"), "w", encoding="utf-8") as fh:
            fh.write(company_page(company, loads_of_company, neighbours))

    letters = catalog_pages(companies)
    count = sitemap(companies, letters, datetime.date.today().isoformat())
    print(f"companies: {len(companies)} pages, catalog letters: {len(letters)}, sitemap urls: {count}")


if __name__ == "__main__":
    main()
