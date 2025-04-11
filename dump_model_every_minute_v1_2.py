import schedule
import time
import requests
from datetime import datetime
import pandas as pd
import csv
import random
from string import Template
from central_strike import _calculate_central_strike
from supported_base_asset import MAP

"""
функция is_business_time() проверяет:
Выходные дни (суббота, воскресенье)
Нерабочее время (23:51-8:59)
В функции my_function() производится проверка времени в начале:
Если время не рабочее, функция немедленно завершается
Добавлено информативное сообщение в лог
Программа пропускает выполнение функции my_function() в нерабочие часы и выходные дни.
"""

# Конфигурация для работы с файлами
temp_str = 'C:\\Users\\ashadrin\\YandexDisk\\_ИИС\\Position\\$name_file'
temp_obj = Template(temp_str)

last_price_lifetime = 60 * 15 # время жизни последней цены last_price для расчетов (15 минут в секундах)

def is_business_time():
    """Проверяет, находится ли текущее время в рабочих часах."""
    now = datetime.now()
    current_hour = now.hour
    current_minute = now.minute

    # Проверяем выходные дни
    if now.weekday() >= 5:  # 5 - суббота, 6 - воскресенье
        return False

    # Проверяем нерабочее время (23:51-8:59)
    if (current_hour == 23 and current_minute >= 51) or \
            (current_hour < 9):
        return False

    return True

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
    """Основная функция обработки данных."""
    if not is_business_time():
        print("Текущее время находится в нерабочих часах или выходной день")
        return

    try:
        model_from_api = get_object_from_json_endpoint('https://option-volatility-dashboard.ru/dump_model')

        base_asset_list = model_from_api[0]
        central_strikes_map = {}
        with open(temp_obj.substitute(name_file='BaseAssetPriceHistoryDamp.csv'), 'a', newline='') as f:
            writer = csv.writer(f, delimiter=";", lineterminator="\r")
            for asset in base_asset_list:
                DateTime = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                ticker = asset.get('_ticker')
                base_asset_last_price = asset.get('_last_price')
                data_price = [DateTime, ticker, base_asset_last_price]
                writer.writerow(data_price)
                strike_step = MAP[ticker]['strike_step']
                central_strike = _calculate_central_strike(base_asset_last_price, strike_step)
                central_strikes_map[ticker] = central_strike
                asset.update({
                    'central_strike': central_strike
                })
        f.close()

        current_datetime = datetime.now()
        print(f"Дата и время: {current_datetime.strftime('%Y-%m-%d %H:%M:%S')}")

        option_list = model_from_api[1] # отфильтрованный список опционов
        filtered_option_list = []
        for option in option_list:
            base_asset_ticker = option['_base_asset_ticker']
            if option['_strike'] == central_strikes_map[base_asset_ticker]: # фильтрация опционов по центральному страйку
                option['datetime'] = current_datetime
                date_object = datetime.strptime(option['_expiration_datetime'], "%a, %d %b %Y %H:%M:%S GMT").date()
                option['_expiration_datetime'] = date_object.strftime('%Y-%m-%d')
                filtered_option_list.append(option)

        with open(temp_obj.substitute(name_file='OptionsVolaHistoryDamp.csv'), 'a', newline='') as f:
            writer = csv.writer(f, delimiter=";", lineterminator="\r")
            for option in filtered_option_list:
                current_DateTimestamp = datetime.now()
                currentTimestamp = int(datetime.timestamp(current_DateTimestamp))
                # Проверяем наличие ключа и что значение не None
                print(option['_volatility'])
                print(type(option['_volatility']))
                if '_volatility' in option and type(option['_volatility']) == float:
                    option['_volatility'] = round(option['_volatility'], 2)  # округление до двух знаков после запятой

                if option['_last_price_timestamp'] is not None and currentTimestamp - option[
                    '_last_price_timestamp'] < last_price_lifetime:
                    Real_vol = option['_last_price_iv']
                else:
                    if option['_ask_iv'] is None or option['_bid_iv'] is None:
                        Real_vol = option['_volatility']
                    else:
                        if option['_ask_iv'] is not None and option['_bid_iv'] is not None and \
                                option['_ask_iv'] > option['_volatility'] > option['_bid_iv']:
                            Real_vol = option['_volatility']
                        else:
                            if option['_ask_iv'] < option['_volatility'] and option['_bid_iv'] < option['_volatility'] \
                                    or option['_volatility'] < option['_bid_iv']:
                                Real_vol = (option['_ask_iv'] + option['_bid_iv']) / 2
                                if Real_vol > option['_volatility'] * 2 or Real_vol < option['_volatility'] / 2:
                                    Real_vol = option['_volatility']

                if Real_vol == Real_vol:
                    option['_real_vol'] = round(Real_vol, 2)  # округление до двух знаков после запятой
                else:
                    print('Real_vol is not a number', Real_vol)
                    option['_real_vol'] = None
                if option['_type'] == 'C':
                    option['_type'] = 'Call'
                elif option['_type'] == 'P':
                    option['_type'] = 'Put'
                print('Real_vol', Real_vol)
                data_options_vola = [current_DateTimestamp.strftime('%Y-%m-%d %H:%M:%S'), option['_type'],
                                     option['_expiration_datetime'], option['_base_asset_ticker'], option['_real_vol'], option['_volatility']]
                writer.writerow(data_options_vola)
                print(data_options_vola)
        f.close()


    except Exception as e:
        print(f"Ошибка в функции my_function: {str(e)}")



schedule.every(60).seconds.do(my_function)

while True:
    schedule.run_pending()
    time.sleep(1)
