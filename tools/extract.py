"""Build the static dataset for the ATI company search site.

Reads ati_request_logs from a restored copy of the production dump (see README)
and writes data/companies.json, data/loads.json and data/meta.json.

Only ATI business data is exported: companies, their contacts and their loads.
User accounts, sessions, tokens, payments, per-log user ids and search payloads
never leave the database.
"""

import json
import os
import subprocess
import sys
import tempfile
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

CONTAINER = os.environ.get("PG_CONTAINER", "pgdump")

EXPORT_SQL = """
SELECT jsonb_build_object('el', el)::text
FROM (
    SELECT jsonb_array_elements(response_data -> 'loads') AS el
    FROM ati_request_logs
    WHERE jsonb_typeof(response_data -> 'loads') = 'array'
    UNION ALL
    SELECT response_data
    FROM ati_request_logs
    WHERE request_type = 'load_info' AND response_data ? 'firmInfo'
) s
"""

META_SQL = """
SELECT jsonb_build_object(
    'logs', count(*),
    'from', to_char(min(created_at), 'YYYY-MM-DD'),
    'to', to_char(max(created_at), 'YYYY-MM-DD')
)::text
FROM ati_request_logs
"""

CITY_SQL = """
SELECT jsonb_build_object(
    'id', id,
    'name', name
)::text
FROM (
    SELECT DISTINCT ON (item ->> 'id')
        item ->> 'id' AS id,
        COALESCE(item ->> 'city_name', item ->> 'text') AS name
    FROM (
        SELECT response_item::jsonb AS item
        FROM geo_cities
    ) parsed
    WHERE item ? 'id'
      AND COALESCE(item ->> 'city_name', item ->> 'text') IS NOT NULL
    ORDER BY item ->> 'id', COALESCE(item ->> 'city_name', item ->> 'text')
) s
"""


VERIFY_SQL = """
SELECT jsonb_build_object(
    'logs', (SELECT count(*) FROM ati_request_logs),
    'elements', (
        SELECT count(*) FROM (
            SELECT jsonb_array_elements(response_data -> 'loads') FROM ati_request_logs
            WHERE jsonb_typeof(response_data -> 'loads') = 'array'
            UNION ALL
            SELECT response_data FROM ati_request_logs
            WHERE request_type = 'load_info' AND response_data ? 'firmInfo'
        ) e
    ),
    'load_ids', (
        SELECT count(DISTINCT el ->> 'id') FROM (
            SELECT jsonb_array_elements(response_data -> 'loads') el FROM ati_request_logs
            WHERE jsonb_typeof(response_data -> 'loads') = 'array'
            UNION ALL
            SELECT response_data FROM ati_request_logs
            WHERE request_type = 'load_info' AND response_data ? 'firmInfo'
        ) e
    ),
    'firm_ids', (
        SELECT count(DISTINCT coalesce(el -> 'firm' ->> 'id', el -> 'firmInfo' ->> 'id', el ->> 'firmId')) FROM (
            SELECT jsonb_array_elements(response_data -> 'loads') el FROM ati_request_logs
            WHERE jsonb_typeof(response_data -> 'loads') = 'array'
            UNION ALL
            SELECT response_data FROM ati_request_logs
            WHERE request_type = 'load_info' AND response_data ? 'firmInfo'
        ) e
        WHERE coalesce(el -> 'firm' ->> 'id', el -> 'firmInfo' ->> 'id', el ->> 'firmId') IS NOT NULL
    )
)::text
"""


def psql(sql):
    """Stream JSON lines from psql and fail loudly if the query breaks."""
    with tempfile.TemporaryFile() as errors:
        proc = subprocess.Popen(
            ["docker", "exec", CONTAINER, "psql", "-U", "postgres", "-d", "bot_contacts", "-t", "-A", "-c", sql],
            stdout=subprocess.PIPE,
            stderr=errors,
            text=True,
            encoding="utf-8",
            bufsize=1 << 20,
        )
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("{"):
                yield json.loads(line)
        code = proc.wait()
        if code != 0:
            errors.seek(0)
            message = errors.read().decode("utf-8", "replace").strip()
            sys.exit(f"psql failed (exit {code}):\n{message[:4000]}")


def clean(value):
    if isinstance(value, str):
        return value.strip() or None
    return value


def contacts_of(firm):
    """Normalise both ATI contact shapes (search results and load page)."""
    for c in firm.get("contacts") or []:
        name = clean(c.get("name"))
        if not name:
            continue
        phones = [clean(p.get("number")) for p in (c.get("phones") or [])]
        phones += [clean(c.get("mobile")), clean(c.get("telephone"))]
        email = c.get("email")
        if isinstance(email, bool):
            email = None
        yield name, [p for p in phones if p], clean(email), clean(c.get("skype")), bool(c.get("isConfirmed"))


def company_from_firm(firm):
    rating = firm.get("rating") or {}
    location = firm.get("location") or {}
    return {
        "id": str(firm["id"]),
        "name": clean(firm.get("firmFullName")) or clean(firm.get("fullFirmName")) or clean(firm.get("name")) or clean(
            firm.get("firmName")),
        "short": clean(firm.get("name")) or clean(firm.get("firmName")),
        "city": clean(location.get("cityName")) or clean(firm.get("city")),
        "region": clean(location.get("regionName")),
        "country": clean(location.get("countryName")),
        "kind": clean(firm.get("profile")) or clean(firm.get("firmType")),
        "rating": rating.get("score"),
        "ratingPct": rating.get("scorePercent"),
        "vip": bool(rating.get("vip")),
        "recs": firm.get("recommendations", firm.get("recommendationsCount")),
        "claims": firm.get("claims", firm.get("claimsCount")),
        "docs": clean(firm.get("docs")),
        "contacts": [],
        "loads": 0,
        "first": None,
        "last": None,
    }


def merge_company(dst, src, from_search):
    """Search results carry the canonical company card, so they win over the load page."""
    for key, value in src.items():
        if key in ("contacts", "loads", "first", "last"):
            continue
        if value in (None, "", 0, False):
            continue
        if from_search or dst.get(key) in (None, "", 0, False):
            dst[key] = value


def date_of(value):
    return value[:10] if isinstance(value, str) and len(value) >= 10 else None


def load_from_search(el):
    loading = el.get("loading") or {}
    unloading = el.get("unloading") or {}
    load = el.get("load") or {}
    rate = el.get("rate") or {}
    cargos = loading.get("loadingCargos") or []
    return {
        "id": el.get("id"),
        "company": str((el.get("firm") or {}).get("id") or "") or None,
        "number": clean(el.get("loadNumber")),
        "from": clean((loading.get("location") or {}).get("city")),
        "to": clean((unloading.get("location") or {}).get("city")),
        "distance": (el.get("route") or {}).get("distance"),
        "cargo": clean(load.get("cargoType")) or clean(cargos[0].get("name") if cargos else None),
        "weight": load.get("weight") or (cargos[0].get("weight") if cargos else None),
        "volume": load.get("volume") or (cargos[0].get("volume") if cargos else None),
        "price": rate.get("priceNds") or rate.get("priceNoNds") or rate.get("price") or None,
        "payDays": rate.get("payDays") or None,
        "add": date_of(el.get("addDate")),
        "first": date_of(loading.get("firstDate")),
        "last": date_of(loading.get("lastDate")),
        "archived": bool(el.get("isArchived")),
    }


def load_from_info(el, city_names):
    # The load page carries two firm ids: `firmId` (the firm that opened the page)
    # and `firmInfo.id` (the firm that owns the load, confirmed by the search
    # results for the same load). The owner is the one we attribute the load to.
    loading = el.get("loading") or {}
    unloading = el.get("unloading") or {}
    payment = el.get("payment") or {}
    cargos = loading.get("loadingCargos") or []
    firm = el.get("firmInfo") or {}
    return {
        "id": el.get("id"),
        "company": str(firm.get("id") or el.get("firmId") or "") or None,
        "number": clean(el.get("loadNumber")),
        "from": city_names.get(str(loading.get("cityId"))),
        "to": city_names.get(str(unloading.get("cityId"))),
        "distance": el.get("distance"),
        "cargo": clean(cargos[0].get("name") if cargos else None),
        "weight": cargos[0].get("weight") if cargos else None,
        "volume": cargos[0].get("volume") if cargos else None,
        "price": payment.get("sumWithNDS") or payment.get("sumWithoutNDS") or payment.get("rateSum") or None,
        "payDays": payment.get("payDays") or None,
        "add": date_of(el.get("addedAt")),
        "first": date_of(el.get("firstDate")) or date_of(loading.get("firstDate")),
        "last": date_of(el.get("lastDate")) or date_of(loading.get("lastDate")),
        "archived": bool(el.get("isArchived")),
    }


def collect():
    companies = {}
    company_contacts = defaultdict(dict)
    loads = {}
    entries = 0
    city_names = {str(row["id"]): clean(row.get("name")) for row in psql(CITY_SQL) if row.get("id")}

    for row in psql(EXPORT_SQL):
        el = row["el"]
        entries += 1
        firm = el.get("firm") or el.get("firmInfo")
        if not firm or not firm.get("id"):
            continue

        firm_id = str(firm["id"])
        company = company_from_firm(firm)
        if firm_id in companies:
            merge_company(companies[firm_id], company, el.get("firm") is not None)
        else:
            companies[firm_id] = company

        for name, phones, email, skype, confirmed in contacts_of(firm):
            contact = company_contacts[firm_id].setdefault(
                name.lower(), {"name": name, "phones": [], "email": None, "skype": None, "confirmed": False}
            )
            for phone in phones:
                if phone not in contact["phones"]:
                    contact["phones"].append(phone)
            contact["email"] = contact["email"] or email
            contact["skype"] = contact["skype"] or skype
            contact["confirmed"] = contact["confirmed"] or confirmed

        load = load_from_search(el) if el.get("firm") else load_from_info(el, city_names)
        key = load.pop("id")
        if not key or not load["company"]:
            continue
        existing = loads.get(key)
        if existing:
            for field, value in load.items():
                if existing.get(field) in (None, "", 0) and value not in (None, "", 0):
                    existing[field] = value
            existing["archived"] = existing["archived"] or load["archived"]
        else:
            loads[key] = load

    for firm_id, contacts in company_contacts.items():
        companies[firm_id]["contacts"] = list(contacts.values())

    for load in loads.values():
        company = companies.get(load["company"])
        if company:
            company["loads"] += 1
            stamp = load["add"] or load["first"]
            if stamp:
                if not company["first"] or stamp < company["first"]:
                    company["first"] = stamp
                if not company["last"] or stamp > company["last"]:
                    company["last"] = stamp

    return companies, loads, entries


LOAD_FIELDS = ("company", "from", "to", "distance", "cargo", "weight", "volume", "price", "payDays", "add",
               "first", "last", "archived", "number")


def write(companies, loads, entries):
    ordered = sorted(companies.values(), key=lambda c: (c["name"] or "").lower())
    company_index = {c["id"]: i for i, c in enumerate(ordered)}

    cities = sorted({v for load in loads.values() for v in (load["from"], load["to"]) if v})
    city_index = {city: i for i, city in enumerate(cities)}
    cargos = sorted({load["cargo"] for load in loads.values() if load["cargo"]})
    cargo_index = {cargo: i for i, cargo in enumerate(cargos)}

    rows = [
        [
            company_index.get(load["company"], -1),
            city_index.get(load["from"], -1),
            city_index.get(load["to"], -1),
            load["distance"],
            cargo_index.get(load["cargo"], -1),
            load["weight"],
            load["volume"],
            load["price"],
            load["payDays"],
            load["add"],
            load["first"],
            load["last"],
            1 if load["archived"] else 0,
            load["number"],
        ]
        for load in loads.values()
        if load["company"] in company_index
    ]
    rows.sort(key=lambda row: row[9] or row[10] or "", reverse=True)

    meta = next(psql(META_SQL))
    meta.update({"companies": len(ordered), "loads": len(rows), "fields": list(LOAD_FIELDS)})

    os.makedirs(DATA, exist_ok=True)
    outputs = {
        "companies.json": ordered,
        "loads.json": {"companies": [c["id"] for c in ordered], "cities": cities, "cargos": cargos, "rows": rows},
        "meta.json": meta,
    }
    for name, payload in outputs.items():
        path = os.path.join(DATA, name)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
        print(f"{name}: {os.path.getsize(path) / 1048576:.1f} MB")

    print(f"companies: {len(ordered)}, loads: {len(rows)}, load entries read: {entries}")
    report(next(psql(VERIFY_SQL)), ordered, rows)


def report(db, companies, rows):
    """Compare what the database holds with what was written, so a short export is impossible to miss."""
    print("\ncoverage: database -> published")
    print(f"  logs            {db['logs']:>7}")
    print(f"  load records    {db['elements']:>7} -> {len(rows):>7} unique loads")
    print(f"  unique load ids {db['load_ids']:>7} -> {len(rows):>7}")
    print(f"  companies       {db['firm_ids']:>7} -> {len(companies):>7}")
    covered = sum(1 for company in companies if company["loads"] > 0)
    print(f"  companies with loads: {covered}")
    missing_ids = db["load_ids"] - len(rows)
    if missing_ids > 20:
        sys.exit(f"export looks incomplete: {missing_ids} load ids are missing")
    if db["firm_ids"] != len(companies):
        sys.exit(f"export looks incomplete: {db['firm_ids'] - len(companies)} companies are missing")


if __name__ == "__main__":
    write(*collect())
