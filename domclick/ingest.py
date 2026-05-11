from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
import json
import time

def parse_current_browser_tab():
    print("🔌 Подключаемся к открытому браузеру Chrome...")
    
    # Настраиваем подключение к порту 9222
    chrome_options = Options()
    chrome_options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
    
    try:
        driver = webdriver.Chrome(options=chrome_options)
    except Exception as e:
        print("\n❌ Ошибка подключения!")
        print("Убедитесь, что вы закрыли все Хромы и запустили его командой:")
        print('chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\\selenum\\ChromeProfile"')
        print(f"Детали ошибки: {e}")
        return

    # На всякий случай проверяем, та ли страница открыта
    print(f"👀 Вижу страницу: {driver.title}")
    
    # Можно обновить страницу кодом, если нужно, но лучше просто забрать то, что есть
    # driver.refresh() 
    # time.sleep(5)

    # Забираем HTML
    html = driver.page_source
    soup = BeautifulSoup(html, 'html.parser')
    
    # --- Парсинг (ваш старый добрый код) ---
    data = {}
    neighbors_block = soup.find('div', {'data-e2e-id': 'neighbors-stats-block'})
    
    if not neighbors_block:
        print("⚠️ Блок аналитики на странице не найден! (Прокрутите страницу вниз в браузере)")
        return

    # 1. Доход и ЖКУ
    try:
        for label_text in ["Средний доход", "Средняя стоимость ЖКУ"]:
            label_tag = neighbors_block.find(string=label_text)
            if label_tag:
                val = label_tag.find_parent('div').find('b').text.strip()
                data[label_text] = val
    except: pass

    # 2. Возраст
    try:
        age_header = neighbors_block.find(string="Возрастные группы")
        if age_header:
            data['Возрастные группы'] = {}
            parent = age_header.find_parent('div')
            container = parent.find_next_sibling('div')
            if container:
                for bar in container.find_all('div', recursive=False):
                    divs = bar.find_all('div')
                    if len(divs) >= 3:
                        data['Возрастные группы'][divs[-1].text.strip()] = divs[0].text.strip()
    except: pass

    # 3. Доп. параметры
    try:
        for param in ["С детьми", "С животными", "С автомобилем"]:
            lbl = neighbors_block.find(string=param)
            if lbl:
                val = lbl.find_parent('div').find_next_sibling('b').text.strip()
                data[param] = val
    except: pass

    print("\n✅ ДАННЫЕ ПОЛУЧЕНЫ:")
    print(json.dumps(data, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    parse_current_browser_tab()