# -*- coding: utf-8 -*-
"""
ЦИАН → долгосрочная аренда квартир
Зоны: только Москва (весь город).

Чтобы МАКСИМАЛЬНО уменьшить пропуски из-за лимитов выдачи:
  - Делаем «нарезку» по комнатам И по ЦЕНЕ (6 корзин цены).
  - Получается матрица запросов room_bucket × price_bucket.
  - Пагинация до «опустошения» + backoff на 429.
  - Никаких клиентских отбрасываний по региону/полигону — сохраняем ВСЁ, но пишем координаты lon/lat для пост-обрезки.

CSV-поля: все ключевые характеристики + lon, lat.

Зависимости: requests
Python: 3.8+
"""

import csv
import random
import sys
import time
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import requests

API_URL = "https://api.cian.ru/search-offers/v2/search-offers-desktop/"

# --------------------- ЗОНЫ ---------------------
ZONES = [
    {
        "name": "Москва",
        "region_ids": [1],                 # субъект РФ: Москва
        "geo": [],                         # без геофильтра — весь город
    },
]

# ----------------- КОРЗИНЫ ФИЛЬТРОВ -----------------
# Комнаты — коды ЦИАН
ROOM_BUCKETS: List[Tuple[str, List[int]]] = [
    ("studio", [9]),
    ("1", [1]),
    ("2", [2]),
    ("3", [3]),
    ("4", [4]),
    ("5plus", [5, 6, 7]),
]

# Цена, ₽/мес — диапазоны с небольшими перекрытиями по 1₽, чтобы ничего не выпало на границе
# Можно смело настраивать под себя.
PRICE_BUCKETS: List[Tuple[str, Optional[int], Optional[int]]] = [
    ("p0_47",      0,      47_000),
    ("p47_54",     47_001, 54_000),
    ("p54_59",    54_001, 59_000),
    ("p59_64",   59_001, 64_000),
    ("p64_68",   64_001, 68_000),
    ("p68_74", 68_001, 74_000),
    ("p74_80", 74_001, 80_000),
    ("p80_94", 80_001, 94_000),
    ("p94_110", 94_001, 110_000),
    ("p110_140", 110_001, 140_000),
    ("p140_200", 140_001, 200_000),
    ("p200_300", 200_001, 300_000),
    ("p300_plus",  300_001, None),   # верх не ограничиваем
]

# ----------------- CSV -----------------
CSV_HEADERS = [
    "zone", "rooms_bucket", "price_bucket", "offer_id",
    "how_many_rooms", "price_per_month",
    "address", "district", "street",
    "floor", "all_floors",
    "square_meters", "comm_meters", "kitchen_meters",
    "commissions", "year_of_construction",
    "author", "link", "added_ts", "publish_ts",
    "lon", "lat",
]
OUTPUT_CSV = "cian_moscow_rent.csv"

# ----------------- ПАРАМЕТРЫ СЕТИ -----------------
REQUEST_TIMEOUT = 20
FIRST_PAGE = 1
MAX_EMPTY_PAGES_IN_ROW = 2
MAX_NO_NEW_PAGES_IN_ROW = 3

# ----------------- СЕТЕВОЙ СЛОЙ -----------------
def user_agent() -> str:
    UAS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    ]
    return random.choice(UAS)

def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "accept": "*/*",
        "accept-language": "ru-RU,ru;q=0.9",
        "content-type": "application/json;charset=UTF-8",
        "origin": "https://www.cian.ru",
        "referer": "https://www.cian.ru/",
        "user-agent": user_agent(),
    })
    return s

def backoff_sleep(attempt: int) -> None:
    base = min(60, 2 ** attempt)
    time.sleep(base + random.uniform(0.0, 1.5))

def post_query(session: requests.Session, payload: Dict[str, Any]) -> Dict[str, Any]:
    attempts = 0
    while True:
        try:
            resp = session.post(API_URL, json=payload, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 429:
                attempts += 1
                print(f"[warn] 429 Too Many Requests — backoff {attempts}", file=sys.stderr)
                backoff_sleep(attempts)
                session.headers.update({"user-agent": user_agent()})
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            attempts += 1
            print(f"[warn] сеть/API ошибка: {e} — попытка {attempts}", file=sys.stderr)
            if attempts >= 6:
                raise
            backoff_sleep(attempts)

# ----------------- JSON Query -----------------
def build_payload(region_ids: List[int],
                  geo_filters: List[Dict[str, int]],
                  rooms: List[int],
                  page: int,
                  price_min: Optional[int],
                  price_max: Optional[int]) -> Dict[str, Any]:
    jq: Dict[str, Any] = {
        "_type": "flatrent",
        "engine_version": {"type": "term", "value": 2},
        "page": {"type": "term", "value": page},
        "with_neighbors": {"type": "term", "value": False},
        "for_day": {"type": "term", "value": "!1"},   # без посуточной
        "room": {"type": "terms", "value": rooms},
        "sort": {"type": "term", "value": "creation_date_desc"},
        "region": {"type": "terms", "value": region_ids},
    }
    if geo_filters:
        jq["geo"] = {"type": "geo", "value": geo_filters}
    if price_min is not None or price_max is not None:
        rng: Dict[str, int] = {}
        if price_min is not None:
            rng["gte"] = int(price_min)
        if price_max is not None:
            rng["lte"] = int(price_max)
        jq["price"] = {"type": "range", "value": rng}
    return {"jsonQuery": jq}

# ----------------- ВСПОМОГАТЕЛЬНОЕ -----------------
def safe_get(d: Dict[str, Any], path: Iterable[str], default=None):
    cur = d
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur

def extract_commission_percent(bargain_terms: Dict[str, Any]) -> int:
    if not isinstance(bargain_terms, dict):
        return 0
    for key in ("commission", "agentFee"):
        node = bargain_terms.get(key)
        if isinstance(node, dict):
            if isinstance(node.get("percent"), (int, float)):
                return int(node["percent"])
            if isinstance(node.get("size"), (int, float)) and str(node.get("unit", "")).lower().startswith("percent"):
                return int(node["size"])
    return 0

def try_parse_street_from_address(address: Optional[str]) -> str:
    if not address or not isinstance(address, str):
        return ""
    parts = [p.strip() for p in address.split(",")]
    return parts[-2] if len(parts) >= 2 else ""

def get_offer_lonlat(item: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    geo = item.get("geo") or {}
    coords = geo.get("coordinates")
    # dict {'lat':..., 'lng':...}
    if isinstance(coords, dict):
        lat = coords.get("lat") or coords.get("latitude")
        lon = coords.get("lng") or coords.get("lon") or coords.get("longitude")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            return float(lon), float(lat)
    # list [lon, lat]
    if isinstance(coords, list) and len(coords) >= 2:
        lon, lat = coords[0], coords[1]
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            return float(lon), float(lat)
    # бывает geo['point'] = {'lat':..,'lng':..}
    point = geo.get("point")
    if isinstance(point, dict):
        lat = point.get("lat")
        lon = point.get("lng") or point.get("lon")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            return float(lon), float(lat)
    return None, None

def normalize_offer_id(oid_raw: Any) -> Optional[str]:
    if oid_raw is None:
        return None
    s = str(oid_raw).strip()
    return s if s.isdigit() else None

def offer_to_row(zone_name: str, rooms_bucket: str, price_bucket: str, item: Dict[str, Any]) -> List[Any]:
    bargain = item.get("bargainTerms", {}) or {}
    building = item.get("building", {}) or {}
    geo = item.get("geo", {}) or {}

    rooms_count = item.get("roomsCount")
    price = bargain.get("priceRur") or bargain.get("price") or safe_get(bargain, ("prices", "total", "value"))
    addr = geo.get("userInput")
    district_name = geo.get("districtName") or ""
    street = try_parse_street_from_address(addr)
    floor_num = item.get("floorNumber")
    floors_cnt = building.get("floorsCount")
    total_area = item.get("totalArea")
    living_area = item.get("livingArea")
    kitchen_area = item.get("kitchenArea")
    build_year = building.get("buildYear") or building.get("houseYear")
    commission_pct = extract_commission_percent(bargain)
    lon, lat = get_offer_lonlat(item)

    # автор
    author = ""
    for path in (("user", "name"), ("owner", "name"), ("agent", "name"), ("agency", "name")):
        val = safe_get(item, path)
        if isinstance(val, str) and val.strip():
            author = val.strip()
            break

    link = item.get("fullUrl")
    if not link:
        oid = normalize_offer_id(item.get("id"))
        if oid:
            link = f"https://www.cian.ru/rent/flat/{oid}/"

    return [
        zone_name, rooms_bucket, price_bucket, item.get("id"),
        rooms_count, price, addr, district_name, street,
        floor_num, floors_cnt, total_area, living_area, kitchen_area,
        commission_pct, build_year, author,
        link, item.get("addedTimestamp"), item.get("publishTimestamp"),
        lon, lat,
    ]

# ----------------- ОСНОВНОЙ ОБХОД -----------------
def crawl_zone(session: requests.Session,
               zone_name: str,
               region_ids: List[int],
               geo_filters: List[Dict[str, int]],
               writer: csv.writer,
               seen_ids: Set[str]) -> int:

    total_written = 0

    for rooms_name, room_vals in ROOM_BUCKETS:
        for price_name, pmin, pmax in PRICE_BUCKETS:
            print(f"[crawl] {zone_name} — комнаты: {rooms_name} — цена: {price_name}")
            empty_in_row = 0
            no_new_in_row = 0
            page = FIRST_PAGE

            while True:
                payload = build_payload(region_ids, geo_filters, room_vals, page, pmin, pmax)
                print(f"[list] page {page} | region={region_ids} geo={geo_filters} rooms={room_vals} price=({pmin},{pmax})")
                data = post_query(session, payload)

                offers = (data.get("data") or {}).get("offersSerialized") or []
                if not offers:
                    empty_in_row += 1
                    if empty_in_row >= MAX_EMPTY_PAGES_IN_ROW:
                        print("[list] пусто — конец выдачи по этому срезу")
                        break
                    time.sleep(0.6)
                    page += 1
                    continue
                empty_in_row = 0

                new_in_page = 0
                for it in offers:
                    oid = normalize_offer_id(it.get("id"))
                    if not oid or oid in seen_ids:
                        continue

                    writer.writerow(offer_to_row(zone_name, rooms_name, price_name, it))
                    seen_ids.add(oid)
                    total_written += 1
                    new_in_page += 1

                print(f"[list] найдено: {len(offers)} | записано новых: {new_in_page}")

                if new_in_page == 0:
                    no_new_in_row += 1
                    if no_new_in_row >= MAX_NO_NEW_PAGES_IN_ROW:
                        print("[list] нет нового несколько страниц подряд — выхожу из этого среза")
                        break
                else:
                    no_new_in_row = 0

                page += 1
                time.sleep(random.uniform(0.4, 1.0))

    return total_written

def main():
    session = make_session()
    seen: Set[str] = set()

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        wr.writerow(CSV_HEADERS)

        grand = 0
        for z in ZONES:
            written = crawl_zone(
                session=session,
                zone_name=z["name"],
                region_ids=z["region_ids"],
                geo_filters=z["geo"],
                writer=wr,
                seen_ids=seen,
            )
            grand += written

    print(f"[done] сохранено: {OUTPUT_CSV}, строк (включая заголовок): {grand + 1}")

if __name__ == "__main__":
    main()