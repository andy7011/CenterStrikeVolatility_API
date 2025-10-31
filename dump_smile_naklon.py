import schedule
import time
import requests
from datetime import datetime, timedelta
import pandas as pd
import csv
import random
from string import Template
from app.central_strike import _calculate_central_strike
from app.supported_base_asset import MAP

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
temp_str = 'C:\\Users\\шадрин\\YandexDisk\\_ИИС\\Position\\$name_file'
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


# Функция для очистки файла csv от старых записей (старше 14 дней)
def clean_old_records(file_path):
    try:
        # Создаем временную метку на 14 дней назад
        cutoff_date = datetime.now() - timedelta(days=14)

        # Читаем файл
        df = pd.read_csv(file_path, delimiter=';', parse_dates=['DateTime'])

        # Фильтруем записи новее 14 дней
        df_filtered = df[df['DateTime'] > cutoff_date]

        # Сохраняем результат обратно в файл
        df_filtered.to_csv(file_path, index=False, sep=';', date_format='%Y-%m-%d %H:%M:%S')

    except FileNotFoundError:
        print("Файл не найден. Продолжаем работу...")
    except Exception as e:
        print(f"Произошла ошибка при очистке файла: {str(e)}")


# Выполняем очистку при запуске
clean_old_records(temp_obj.substitute(name_file='OptionsSmileNaklonHistory.csv'))
print(f"Очистка файла OptionsSmileNaklonHistory.csv от старых записей (старше 14 дней) завершена")

def my_function():
    """Основная функция обработки данных."""
    if not is_business_time():
        print("Текущее время находится в нерабочих часах или выходной день")
        return

    try:
        model_from_api = get_object_from_json_endpoint('https://option-volatility-dashboard.tech/dump_model')

        base_asset_list = model_from_api[0]
        strikes_map_up = {}
        strikes_map_down = {}
        offset = 3
        for asset in base_asset_list:
            # DateTime = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            ticker = asset.get('_ticker')
            strike_step = MAP[ticker]['strike_step']
            base_asset_last_price = asset.get('_last_price')
            base_asset_last_price_offset_plus = base_asset_last_price + (strike_step * offset)
            base_asset_last_price_offset_minus = base_asset_last_price - (strike_step * offset)
            offset_strike_plus = _calculate_central_strike(base_asset_last_price_offset_plus, strike_step)
            offset_strike_minus = _calculate_central_strike(base_asset_last_price_offset_minus, strike_step)
            strikes_map_up[ticker] = offset_strike_plus
            # print(f"Смещенный страйк для {ticker}: {offset_strike_plus}")
            strikes_map_down[ticker] = offset_strike_minus
            # print(f"Смещенный страйк для {ticker}: {offset_strike_minus}")
            asset.update({
                'offset_strike_plus': offset_strike_plus
            })
            asset.update({
                'offset_strike_minus': offset_strike_minus
            })
        print(strikes_map_up)
        print(strikes_map_down)

        current_datetime = datetime.now()
        print(f"Дата и время: {current_datetime.strftime('%Y-%m-%d %H:%M:%S')}")

        option_list = model_from_api[1] # отфильтрованный список опционов
        filtered_option_list_up = []
        filtered_option_list_down = []
        for option in option_list:
            base_asset_ticker = option['_base_asset_ticker']
            if option['_strike'] == strikes_map_up[base_asset_ticker]: # фильтрация опционов по страйкам
                option['datetime'] = current_datetime
                date_object = datetime.strptime(option['_expiration_datetime'], "%a, %d %b %Y %H:%M:%S GMT").date()
                option['_expiration_datetime'] = date_object.strftime('%Y-%m-%d')
                filtered_option_list_up.append(option)
            elif option['_strike'] == strikes_map_down[base_asset_ticker]: # фильтрация опционов по страйкам
                option['datetime'] = current_datetime
                date_object = datetime.strptime(option['_expiration_datetime'], "%a, %d %b %Y %H:%M:%S GMT").date()
                option['_expiration_datetime'] = date_object.strftime('%Y-%m-%d')
                filtered_option_list_down.append(option)
        print(f"Фильтрованный список опционов UP: {filtered_option_list_up}")
        print(f"Фильтрованный список опционов DOWN: {filtered_option_list_down}")

        with open(temp_obj.substitute(name_file='OptionsSmileNaklonHistory.csv'), 'a', newline='') as f:
            writer = csv.writer(f, delimiter=";", lineterminator="\r")

            for option in filtered_option_list_up:
                current_DateTimestamp = datetime.now()
                currentTimestamp = int(datetime.timestamp(current_DateTimestamp))

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

                option['_real_vol'] = Real_vol
                if option['_type'] == 'C':
                    option['_type'] = 'Call'
                elif option['_type'] == 'P':
                    option['_type'] = 'Put'



                data_options_vola = [current_DateTimestamp.strftime('%Y-%m-%d %H:%M:%S'), option['_type'],
                                     option['_expiration_datetime'], option['_base_asset_ticker'], Real_vol, option['_volatility']]
                writer.writerow(data_options_vola)
        f.close()

    except Exception as e:
        print(f"Ошибка в функции my_function: {str(e)}")

schedule.every(60).seconds.do(my_function)

while True:
    schedule.run_pending()
    time.sleep(1)
