from curl_cffi import requests
import pandas as pd
import time
import random
import math

# Настройки API
URL = 'https://api.cian.ru/search-offers/v2/search-offers-desktop/'
HEADERS = {
    'Accept': '*/*',
    'Content-Type': 'application/json',
    'Origin': 'https://www.cian.ru',
    'Referer': 'https://www.cian.ru/',
}

ROOM_TYPES = [1, 2, 3, 4, 5, 6, 9] # 9 - студия

def get_payload(room_type, price_min, price_max, page):
    return {
        "jsonQuery": {
            "_type": "flatsale",
            "sort": {"type": "term", "value": "price_object_order"},
            "engine_version": {"type": "term", "value": 2},
            "region": {"type": "terms", "value": [1]}, # 1 - Москва
            "page": {"type": "term", "value": page},
            "room": {"type": "terms", "value": [room_type]},
            "price": {"type": "range", "value": {"gte": price_min, "lte": price_max}}
        },
        "_liquiditySource": "web_serp"
    }

def extract_offer_data(item, room):
    """Извлекает нужные поля из одного объявления (чтобы не дублировать код)"""
    geo = item.get('geo', {})
    coords = geo.get('coordinates', {})
    undergrounds = geo.get('undergrounds', [])
    metro_name = undergrounds[0].get('name') if undergrounds else None
    
    building = item.get('building', {})
    bargain = item.get('bargainTerms', {})
    
    return {
        "id": item.get('id'),
        "url": item.get('fullUrl'),
        "roomsCount": item.get('roomsCount') or (0 if room == 9 else room),
        "totalArea": item.get('totalArea'),
        "livingArea": item.get('livingArea'),
        "kitchenArea": item.get('kitchenArea'),
        "floorNumber": item.get('floorNumber'),
        "floorsCount": building.get('floorsCount'),
        "buildYear": building.get('buildYear'),
        "materialType": building.get('materialType'),
        "price": bargain.get('priceRur') or bargain.get('price'),
        "latitude": coords.get('lat'),
        "longitude": coords.get('lng'),
        "metro_name": metro_name,
        "address": geo.get('userInput'),
        "isNew": item.get('isNew', False)
    }

def parse_cian_adaptive():
    all_offers = []
    
    for room in ROOM_TYPES:
        print(f"\n{'='*40}\nСТАРТ: Комнатность {room}\n{'='*40}")
        price_min = 0
        step = 5_000_000  # Начинаем с широкого шага в 5 млн руб.
        
        while price_min <= 500_000_000:
            price_max = price_min + step - 1
            
            # Для элитки ставим потолок в 10 млрд
            if price_min >= 500_000_000:
                price_max = 10_000_000_000
                
            payload = get_payload(room, price_min, price_max, 1)
            
            try:
                response = requests.post(URL, json=payload, headers=HEADERS, impersonate="chrome110")
                
                # Защита от капчи/блокировки
                if response.status_code != 200 or 'application/json' not in response.headers.get('Content-Type', ''):
                    print(f"ВНИМАНИЕ: Капча или ошибка. Пауза 30 секунд...")
                    time.sleep(30)
                    continue # Пробуем этот же бакет еще раз
                
                data = response.json()
                
                # Получаем ОБЩЕЕ количество предложений в этом ценовом бакете
                offer_count = data.get('data', {}).get('offerCount', 0)
                
                # 1. Если объектов слишком много (>1500) и мы можем сузить шаг
                if offer_count > 1500 and step > 100_000 and price_max != 10_000_000_000:
                    step = step // 2
                    print(f"[*] Бакет {price_min/10**6:.1f}M-{price_max/10**6:.1f}M: Найдено {offer_count} кв. Сужаем шаг до {step/10**6:.1f}M")
                    time.sleep(1)
                    continue # Повторяем поиск с меньшим диапазоном цен
                    
                # 2. Если объектов нет вообще - перепрыгиваем быстрее
                if offer_count == 0:
                    price_min = price_max + 1
                    step = int(step * 1.5) # Увеличиваем шаг, раз тут пусто
                    continue
                
                # 3. Идеальный бакет (0 < offer_count <= 1500)
                print(f"[+] Парсим: {price_min/10**6:.1f}M - {price_max/10**6:.1f}M | Найдено: {offer_count} шт.")
                
                # Сохраняем объекты с уже загруженной 1-й страницы
                offers = data.get('data', {}).get('offersSerialized', [])
                for item in offers:
                    all_offers.append(extract_offer_data(item, room))
                
                # Вычисляем, сколько ЕЩЕ страниц нужно загрузить (по 28 объявлений на страницу)
                total_pages = min(54, math.ceil(offer_count / 28))
                
                # Проходимся только по нужным страницам!
                for page in range(2, total_pages + 1):
                    payload = get_payload(room, price_min, price_max, page)
                    resp = requests.post(URL, json=payload, headers=HEADERS, impersonate="chrome110")
                    
                    if resp.status_code == 200 and 'application/json' in resp.headers.get('Content-Type', ''):
                        page_data = resp.json().get('data', {}).get('offersSerialized', [])
                        for item in page_data:
                            all_offers.append(extract_offer_data(item, room))
                    
                    time.sleep(random.uniform(1.5, 3.0)) # Анти-бан задержка между страницами
                
                print(f"    Собрано! Всего в базе: {len(all_offers)}")
                
                # Переходим к следующему бакету
                price_min = price_max + 1
                
                # Самообучение: если квартир было мало, в следующий раз берем шаг пошире
                if offer_count < 500:
                    step = int(step * 1.5)
                # Если квартир было плотненько, чуть сужаем, чтобы в следующем не перевалить за 1500
                elif offer_count > 1200:
                    step = int(step * 0.8)
                    
                # Выходим из элитного сегмента
                if price_min >= 500_000_000 and price_max == 10_000_000_000:
                    break

            except Exception as e:
                print(f"Ошибка парсинга: {e}. Перезапуск бакета через 10с.")
                time.sleep(10)
                
    # Сохраняем итоговый датасет
    if all_offers:
        df = pd.DataFrame(all_offers)
        df = df.drop_duplicates(subset=['id']) # Убираем возможные дубли на стыках
        df.to_csv('cian_moscow_flats_smart.csv', index=False, encoding='utf-8-sig')
        print(f"\n🎉 ГОТОВО! Собрано уникальных объявлений: {len(df)}")
        return df
    else:
        print("\nПарсинг завершен, данных нет.")

if __name__ == "__main__":
    df = parse_cian_adaptive()