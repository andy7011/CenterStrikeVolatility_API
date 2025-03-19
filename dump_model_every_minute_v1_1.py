import schedule
import time
import requests
from datetime import datetime
import pandas as pd
from central_strike import _calculate_central_strike
from supported_base_asset import MAP
import csv
import random

# #
# Максимальное количество попыток: 5
# Базовая задержка: 1 секунда
# Максимальная задержка: 180 секунд
# Случайный джиттер для предотвращения синхронизации запросов
# Отдельная обработка ошибки 502
# Обработка общих ошибок запросов
# Информативные сообщения о повторных попытках
# Таймаут для каждого запроса
# Ограничение максимального времени ожидания
# Экспоненциальное увеличение задержки между попытками
# #

from string import Template

temp_str = 'C:\\Users\\ashadrin\\YandexDisk\\_ИИС\\Position\\$name_file'
temp_obj = Template(temp_str)

def delay(base_delay, retry_count, max_delay, jitter=True):
    """Вычисляет время задержки перед повторным запросом."""
    delay_time = base_delay * (2 ** retry_count)

    if jitter:
        delay_time *= random.uniform(1, 1.5)

    return min(delay_time, max_delay)


def get_object_from_json_endpoint(url, method='GET', params={}, max_retries=5, base_delay=1, max_delay=180):
    """Получает объект из JSON endpoint с поддержкой повторных попыток."""
    for retry in range(max_retries):
        try:
            response = requests.request(method, url, params=params, timeout=max_delay)

            if response.status_code == 200:
                return response.json()

            if response.status_code == 502:
                if retry < max_retries - 1:
                    wait_time = delay(base_delay, retry, max_delay)
                    print(f"Получена ошибка 502. Повторная попытка через {wait_time:.1f} секунд...")
                    time.sleep(wait_time)
                    continue

            raise Exception(f"Error: {response.status_code}")

        except requests.exceptions.RequestException as e:
            if retry < max_retries - 1:
                wait_time = delay(base_delay, retry, max_delay)
                print(f"Ошибка запроса: {str(e)}. Повторная попытка через {wait_time:.1f} секунд...")
                time.sleep(wait_time)
                continue
            raise


def my_function():
    try:
        model_from_api = get_object_from_json_endpoint('https://option-volatility-dashboard.ru/dump_model')

        # Список базовых активов, вычисление и добавление в словарь центрального страйка
        base_asset_list = model_from_api[0]
        with open(temp_obj.substitute(name_file='BaseAssetPriceHistoryDamp.csv'), 'a') as f:
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
        # Close the file explicitly f.close()
        f.close()



        # Список опционов
        option_list = model_from_api[1]
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