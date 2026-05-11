# Offers limit is 2 000
# pip install playwright

import csv
import json
import os
import re
import uuid
import requests
from playwright.sync_api import Browser
from playwright.sync_api import BrowserContext
from playwright.sync_api import sync_playwright
from tqdm import tqdm

from core.utils import get_key_chain, walk_input_json

COMMON_PARAMS = {
    "address": "1d1463ae-c80f-4d19-9331-a1b68a85b553",  # Moscow UUID
    "limit": 20,
    "sort": "qi",
    "sort_dir": "desc",
    "deal_type": "sale",
    "category": "living",
    "offer_type": "flat",
    "aids": "2299",
}

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,ru;q=0.8,uk;q=0.7",
    "Connection": "keep-alive",
    "DNT": "1",
    "Origin": "https://domclick.ru",
    "Referer": "https://domclick.ru/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
    "sec-ch-ua": '"Chromium";v="143", "Not A(Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
}

COOKIES = {
    # "ns_session": "763f4bd3-78d7-40aa-9cd4-fa6ae1f7ba26",
    # "RETENTION_COOKIES_NAME": "ac46b673fa6042fc8f2b7798c65d1e6a:jZf5ddZcxsi7ir2NjTrA5jPWq0s",
    # "sessionId": "8c5f74b4255f43a4ab4606d45ab87777:6XmaZ_U9pSmOs2R0yhaXD1wFyMM",
    # "UNIQ_SESSION_ID": "055965bc1d4940c382ff4df5943dec04:Iie8RGkGgwAaZVt6vDxQgxpGKJE",
    # "is-green-day-banner-hidden": "true",
    # "is-ddf-banner-hidden": "true",
    # "logoSuffix": "-new-year-2026",
    # "iosAppLink": "https://redirect.appmetrica.yandex.com/serve/750201081333614354",
    # "_sa": "SA1.e19dbe01-c602-48de-8f83-97cedf045d2e.1766064339",
    # "region": "{%22data%22:{%22name%22:%22%D0%9C%D0%BE%D1%81%D0%BA%D0%B2%D0%B0%22%2C%22kladr%22:%2277%22%2C%22guid%22:%221d1463ae-c80f-4d19-9331-a1b68a85b553%22}%2C%22isAutoResolved%22:true}",
    # "_sas.2c534172f17069dd8844643bb4eb639294cd4a7a61de799648e70dc86bc442b9": "SA1.e19dbe01-c602-48de-8f83-97cedf045d2e.1766064339.1766073304",
    # "_sas": "SA1.e19dbe01-c602-48de-8f83-97cedf045d2e.1766064339.1766073304",
    # "qrator_jsid2": "v2.0.1766064337.007.594381c27qXkxFzY|NKtakzOfzVpKx8uM|kVSiIPx/J4AwWFSEDbEIfuVSTSlKO5LDBUGcm13W0FuvvWL7gavOnIYJm/hxc20qqdc3C8V2lbirhgJSsOUKXf8NxO1YSFIW9VM1zFIS6A9CcYi82tOcOEUym54on1hAoTEj/YDS/YxijOORifOIbAQscE+QL/XpyRV6a3kohuQ=-J1/zXty+Lst9BfM/+bfGzYc9nOc=",
    # "_visitId": "9b93048c-8832-4c3c-9ebe-1d73eed6cc9c-f4f0dcc432ac8ba6",
    # "cookieAlert": "true",
}

BROWSER_COOKIES = [
    {
        "name": "qrator_jsid2",
        "value": "v2.0.1766243080.234.594381c2fdy79K8S|mNDTabD6DTIFKb8c|Pn+AWyAXUAHvbpCH1q3Zz7vAywtD0e04TfsEiCQkNqeGS/1JV5iD+NdBlQO0VGHyydVNcMXFuq8M5vkDagf3F32p3zhBbyQb8fdp90uziTCAYFW6T4IBAdGPBJnyzJM3GSTfXnCYqWilbV/SoCG4Wqhfe+ETyevYmoGsyjSQREg=-TUQna4u/k9RBnjuEo/tsXi3RSnE=",
        "domain": ".domclick.ru",
        "path": "/",
        "httpOnly": True,
        "secure": True,
        "sameSite": "Lax",
    },
]


def _get_count(**params) -> int:
    response = requests.get(
        "https://bff-search-web.domclick.ru/api/offers/count/v1",
        params={**COMMON_PARAMS, **params},
        headers=HEADERS,
        cookies=COOKIES,
    )
    return response.json()["result"]["offersCount"]


def _get_items(offset: int, **params) -> dict:
    response = requests.get(
        "https://bff-search-web.domclick.ru/api/offers/v1",
        params={**COMMON_PARAMS, "offset": offset, **params},
        headers=HEADERS,
        cookies=COOKIES,
    )
    return response.json()["result"]["items"]


def _parse_all_offers():
    starting_price = 0
    ending_price = 2_000_000_000
    step = 1_000_000

    for i in tqdm(range(starting_price, ending_price, step), desc="parsing all offers"):
        price_gte = i
        price_lte = i + step
        count_info = _get_count(
            sale_price__gte=str(price_gte), sale_price__lte=str(price_lte)
        )
        print(f"{price_gte:,} - {price_lte:,} : {count_info}")
        if count_info == 0:
            continue

        for offset in tqdm(range(0, count_info, 20), desc="getting items"):
            items = _get_items(
                offset,
                sale_price__gte=str(price_gte),
                sale_price__lte=str(price_lte),
            )
            page_filename = f"{price_gte}-{price_lte}-{offset}.json"
            with open(
                f"/Users/denysbondarenko/Projects/Pets/swimming-pool-summer/domclick/storage/pages/{page_filename}",
                "wt",
                encoding="utf-8",
            ) as file:
                file.write(json.dumps(items, ensure_ascii=False))


def _parse_unique_item_ids() -> list[str]:
    unique_item_ids = set()
    for data in walk_input_json("domclick/storage/pages"):
        unique_item_ids.update((str(item["id"]) for item in data))
    return sorted(unique_item_ids)


def _parse_offers_html():
    unique_item_ids = _parse_unique_item_ids()
    print(f"total unique item ids = {len(unique_item_ids)}")

    print("starting playwright...")
    with sync_playwright() as p:
        print("launching browser...")
        browser: Browser = p.chromium.launch(headless=False)

        print("configuring browser...")
        context: BrowserContext = browser.new_context()
        context.add_cookies(BROWSER_COOKIES)
        context.new_page()  # Keeping an empty page in the context

        for item_id in tqdm(unique_item_ids, desc="parsing offers html"):
            filename = f"/Users/denysbondarenko/Projects/Pets/swimming-pool-summer/domclick/storage/objects/{item_id}.json"
            if os.path.exists(filename):
                continue

            ssr_state = _get_offer_ssr_state(context, item_id)
            with open(filename, "wt", encoding="utf-8") as file:
                file.write(json.dumps(ssr_state, ensure_ascii=False))

        browser.close()


def _get_offer_ssr_state(browser: BrowserContext, offer_id: str) -> dict:
    url = f"https://domclick.ru/card/sale__flat__{offer_id}"

    # Opening a new page
    page = browser.new_page()

    # Intercepting __SSR_STATE__ to get the state before the page is loaded
    page.add_init_script("""
        (function() {
            let backup = null;
            const originalDescriptor = Object.getOwnPropertyDescriptor(window, '__SSR_STATE__') || {};
            
            Object.defineProperty(window, '__SSR_STATE__', {
                set: function(value) {
                    backup = value;
                    if (originalDescriptor.set) {
                        originalDescriptor.set.call(window, value);
                    } else {
                        window._ssrState = value;
                    }
                },
                get: function() {
                    if (originalDescriptor.get) {
                        return originalDescriptor.get.call(window);
                    }
                    return window._ssrState;
                },
                configurable: true
            });
            
            window.__SSR_STATE__BACKUP__ = function() { return backup; };
        })();
    """)

    # Opening the page and waiting for the DOM to be loaded
    page.goto(url, wait_until="domcontentloaded")

    # Additional timeout just in case
    page.wait_for_timeout(1_000)

    # Extracting the __SSR_STATE__ from the backup created by the init script
    ssr_state = page.evaluate("""
        () => {
            if (window.__SSR_STATE__BACKUP__) {
                const backup = window.__SSR_STATE__BACKUP__();
                if (backup) return backup;
            }
            if (typeof window.__SSR_STATE__ !== 'undefined' && window.__SSR_STATE__ !== null) {
                return window.__SSR_STATE__;
            }
            return null;
        }
    """)

    if ssr_state is None:
        raise RuntimeError("Failed to get __SSR_STATE__ via evaluate()")

    page.close()
    return ssr_state


def _parse_offers_json():
    rows = []
    for data in tqdm(
        walk_input_json(
            "/Users/denysbondarenko/Projects/Pets/swimming-pool-summer/domclick/storage/objects"
        ),
        desc="processing files",
    ):
        if not (item_id := get_key_chain(data, "productCard", "_id")):
            rows.append({"url": "UNKNOWN"})
            continue
        if not get_key_chain(
            data, "productCard", "originalProduct", "address", "position"
        ):
            rows.append({"url": "UNKNOWN"})
            continue

        age_buckets = {
            stat["key"]: stat["value"]
            for stat in data["houseInfo"]["neighborsStats"]["age"]
        }
        gender_buckets = {
            stat["key"]: stat["value"]
            for stat in data["houseInfo"]["neighborsStats"]["gender"]
        }

        rows.append(
            {
                "url": f"https://domclick.ru/card/sale__flat__{item_id}",
                "address": data["productCard"]["originalProduct"]["address"][
                    "display_name"
                ],
                "lat": data["productCard"]["originalProduct"]["address"]["position"][
                    "lat"
                ],
                "lon": data["productCard"]["originalProduct"]["address"]["position"][
                    "lon"
                ],
                "district": get_key_chain(
                    data["productCard"]["originalProduct"]["address"],
                    "districts",
                    0,
                    "short_name",
                ),
                "year": data["houseInfo"]["info"].get("buildYear"),
                "wall_type": data["houseInfo"]["info"].get("wallType"),
                "total_apartments": data["houseInfo"]["info"].get(
                    "livingQuartersCount"
                ),
                "floors": data["houseInfo"]["info"].get("floors"),
                "median_income": data["houseInfo"]["neighborsStats"].get(
                    "median_income"
                ),
                **age_buckets,
                **gender_buckets,
            }
        )

    with open("domclick/offers.csv", "wt") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=(
                "url",
                "address",
                "lat",
                "lon",
                "district",
                "year",
                "wall_type",
                "total_apartments",
                "floors",
                "median_income",
                "under_24",
                "between_25_34",
                "between_35_44",
                "between_45_54",
                "between_55_64",
                "over_65",
                "men",
                "women",
            ),
        )
        writer.writeheader()
        writer.writerows(rows)


def main():
    # _parse_all_offers()
    # _parse_offers_html()
    _parse_offers_json()
    print("completed")


if __name__ == "__main__":
    main()
