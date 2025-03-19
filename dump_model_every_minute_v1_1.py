import schedule
import time
import requests
from datetime import datetime
import pandas as pd

from Dash_Example import last_price
from central_strike import _calculate_central_strike
from supported_base_asset import MAP
import csv
import random
from string import Template

# Конфигурация для работы с файлами
temp_str = 'C:\\Users\\ashadrin\\YandexDisk\\_ИИС\\Position\\$name_file'
temp_obj = Template(temp_str)

last_price_lifetime = 60 * 10 # время жизни последней цены last_price для расчетов 10 минут в секундах


def delay(base_delay=1, retry_count=None, max_delay=180, jitter=True):
    """Вычисляет время задержки перед повторным запросом."""
    if retry_count is None:
        retry_count = float('inf')

    delay_time = min(base_delay * (2 ** retry_count), max_delay)

    if jitter:
        delay_time *= random.uniform(1, 1.5)

    return delay_time


def get_object_from_json_endpoint(url, method='GET', params={}, max_delay=180):
    """Получает объект из JSON endpoint с поддержкой повторных попыток."""
    retry_count = 0
    while True:
        try:
            response = requests.request(method, url, params=params, timeout=max_delay)

            if response.status_code == 200:
                return response.json()

            if response.status_code == 502:
                wait_time = delay(max_delay=max_delay, retry_count=retry_count)
                print(f"Получена ошибка 502. Повторная попытка через {wait_time:.1f} секунд...")
                time.sleep(wait_time)
                retry_count += 1
                continue

            raise Exception(f"Error: {response.status_code}")

        except requests.exceptions.RequestException as e:
            wait_time = delay(max_delay=max_delay, retry_count=retry_count)
            print(f"Ошибка запроса: {str(e)}. Повторная попытка через {wait_time:.1f} секунд...")
            time.sleep(wait_time)
            retry_count += 1


def my_function():
    try:
        model_from_api = get_object_from_json_endpoint('https://option-volatility-dashboard.ru/dump_model')

        # Список базовых активов, вычисление и добавление в словарь центрального страйка
        base_asset_list = model_from_api[0]
        with open(temp_obj.substitute(name_file='BaseAssetPriceHistoryDamp.csv'), 'a', newline='') as f:
            writer = csv.writer(f, delimiter=";", lineterminator="\r")
            for asset in base_asset_list:
                DateTime = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                ticker = asset.get('_ticker')
                last_price = asset.get('_last_price')
                data_price = [DateTime, ticker, last_price]
                writer.writerow(data_price)
                strike_step = MAP[ticker]['strike_step']
                central_strike = _calculate_central_strike(last_price, strike_step)  # вычисление центрального страйка
                asset.update({
                    'central_strike': central_strike
                })
        f.close()

        # Список опционов
        option_list = model_from_api[1]
        print(option_list)
        # for base_asset_ticker in option_list['_base_asset_ticker']:
        #     return
        current_datetime = datetime.now()
        for option in option_list:
            option['datetime'] = current_datetime
        df = pd.DataFrame.from_dict(option_list, orient='columns')
        df.set_index('datetime', inplace=True)
        df.index = df.index.strftime('%d.%m.%Y %H:%M:%S')  # Reformat the date index using strftime()
        print(df.columns)
        # print(df)

    except Exception as e:
        print(f"Ошибка в функции my_function: {str(e)}")


schedule.every(60).seconds.do(my_function)

while True:
    schedule.run_pending()
    time.sleep(1)