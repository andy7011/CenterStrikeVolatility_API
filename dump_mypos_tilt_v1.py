import schedule
import time
import requests
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import csv
import random
from string import Template
from app.central_strike import _calculate_central_strike
from app.supported_base_asset import MAP

"""
В данном примере программа проверяет, находится ли текущее время в рабочих часах.
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

last_price_lifetime = 60 * 15  # время жизни последней цены last_price для расчетов (15 минут в секундах)


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
clean_old_records(temp_obj.substitute(name_file='MyPosTilt.csv'))
print(f"Очистка файла MyPosTilt.csv от старых записей (старше 14 дней) завершена")

rows_up = []

# Функция для вычисления взвешенного среднего
def weighted_mean(group, value_cols, weight_col):
    weights = group[weight_col].abs()
    if weights.sum() == 0:
        return pd.Series([float('nan')] * len(value_cols), index=value_cols)
    weighted_vals = {}
    for col in value_cols:
        weighted_vals[col] = (group[col] * weights).sum() / weights.sum()
    return pd.Series(weighted_vals)

def my_function():
    """Основная функция обработки данных."""
    if not is_business_time():
        print("Текущее время находится в нерабочих часах или выходной день")
        return

    try:
        # My positions data
        with open(temp_obj.substitute(name_file='MyPos.csv'), 'r') as file:
            df_table = pd.read_csv(file, sep=';')
        # # Close the file explicitly file.close()
        # file.close()
        # print('\n df_table.columns:\n', df_table.columns)
        # print('df_table:\n', df_table)
        base_asset_list = df_table['optionbase'].unique()
        # print('base_asset_list:\n', base_asset_list)
        tickers_list = df_table['ticker'].tolist()
        # print('tickers_list:\n', tickers_list)

        model_from_api = get_object_from_json_endpoint('https://option-volatility-dashboard.tech/dump_model')

        current_datetime = datetime.now()
        print('\n')
        print(f"Дата и время: {current_datetime.strftime('%Y-%m-%d %H:%M:%S')}")

        option_list = model_from_api[1]  # список опционов

        filtered_option_list_up = []
        filtered_option_list_down = []
        for option in option_list:
            base_asset_ticker = option['_base_asset_ticker']
            if option['_ticker'] in tickers_list and option['_type'] == 'C':  # фильтрация опционов Call из MyPos
                option['datetime'] = current_datetime
                date_object = datetime.strptime(option['_expiration_datetime'], "%a, %d %b %Y %H:%M:%S GMT").date()
                option['_expiration_datetime'] = date_object.strftime('%Y-%m-%d')
                option['net_pos'] = df_table.loc[df_table['ticker'] == option['_ticker'], 'net_pos'].item()
                option['price_pos'] = df_table.loc[df_table['ticker'] == option['_ticker'], 'price_pos'].item()
                option['OpenData'] = df_table.loc[df_table['ticker'] == option['_ticker'], 'OpenData'].item()
                option['OpenPrice'] = df_table.loc[df_table['ticker'] == option['_ticker'], 'OpenPrice'].item()
                option['OpenIV'] = df_table.loc[df_table['ticker'] == option['_ticker'], 'OpenIV'].item()
                filtered_option_list_up.append(option)
            elif option['_ticker'] in tickers_list and option['_type'] == 'P':  # фильтрация опционов Put из MyPos
                option['datetime'] = current_datetime
                date_object = datetime.strptime(option['_expiration_datetime'], "%a, %d %b %Y %H:%M:%S GMT").date()
                option['_expiration_datetime'] = date_object.strftime('%Y-%m-%d')
                option['net_pos'] = df_table.loc[df_table['ticker'] == option['_ticker'], 'net_pos'].item()
                option['price_pos'] = df_table.loc[df_table['ticker'] == option['_ticker'], 'price_pos'].item()
                option['OpenData'] = df_table.loc[df_table['ticker'] == option['_ticker'], 'OpenData'].item()
                option['OpenPrice'] = df_table.loc[df_table['ticker'] == option['_ticker'], 'OpenPrice'].item()
                option['OpenIV'] = df_table.loc[df_table['ticker'] == option['_ticker'], 'OpenIV'].item()
                filtered_option_list_down.append(option)
        # print(f"Фильтрованный список опционов UP: {filtered_option_list_up}")
        # print(f"Фильтрованный список опционов DOWN: {filtered_option_list_down}")

        with open(temp_obj.substitute(name_file='MyPosTilt.csv'), 'a', newline='') as f:
            writer = csv.writer(f, delimiter=";", lineterminator="\r")

            df_MyPosAverage_up = pd.DataFrame(columns=['optionbase', 'expdate', 'net_pos', 'Real_vol_up', 'QuikVola_up', 'MyPosTilt_up'])
            df_MyPosAverage_down = pd.DataFrame(columns=['optionbase', 'expdate', 'net_pos', 'Real_vol_down', 'QuikVola_down', 'MyPosTilt_down'])

            for option_up in filtered_option_list_up:
                current_DateTimestamp = datetime.now()
                currentTimestamp = int(datetime.timestamp(current_DateTimestamp))
                if option_up['_last_price_iv'] is not None and option_up[
                    '_last_price_timestamp'] is not None and currentTimestamp - option_up[
                    '_last_price_timestamp'] < last_price_lifetime:
                    Real_vol_up = option_up['_last_price_iv']
                else:
                    if option_up['_ask_iv'] is None or option_up['_bid_iv'] is None:
                        Real_vol_up = option_up['_volatility']
                    else:
                        if option_up['_ask_iv'] is not None and option_up['_bid_iv'] is not None and \
                                option_up['_ask_iv'] > option_up['_volatility'] > option_up['_bid_iv']:
                            Real_vol_up = option_up['_volatility']
                        else:
                            if option_up['_ask_iv'] < option_up['_volatility'] and option_up['_bid_iv'] < option_up[
                                '_volatility'] or option_up['_volatility'] < option_up['_bid_iv']:
                                Real_vol_up = (option_up['_ask_iv'] + option_up['_bid_iv']) / 2
                                if Real_vol_up > option_up['_volatility'] * 2 or Real_vol_up < option_up[
                                    '_volatility'] / 2:
                                    Real_vol_up = option_up['_volatility']

                option_up['_real_vol'] = Real_vol_up
                MyPosTilt_up = option_up['OpenIV']
                base_asset_ticker = option_up['_base_asset_ticker']
                MyPosAverageLine_up = {
                    'optionbase': option_up['_base_asset_ticker'],
                    'expdate': option_up['_expiration_datetime'],
                    'net_pos': option_up['net_pos'],
                    'Real_vol_up': Real_vol_up,
                    'QuikVola_up': option_up['_volatility'],
                    'MyPosTilt_up': MyPosTilt_up
                }
                df_MyPosAverage_up.loc[len(df_MyPosAverage_up)] = MyPosAverageLine_up
            # print('\n')
            # print('df_MyPosAverage_up')
            # print(df_MyPosAverage_up)

            for option_down in filtered_option_list_down:
                # print(option_down['_base_asset_ticker'], option_down['_expiration_datetime'])
                if option_down['_last_price_iv'] is not None and option_down[
                    '_last_price_timestamp'] is not None and currentTimestamp - option_down[
                    '_last_price_timestamp'] < last_price_lifetime:
                    Real_vol_down = option_down['_last_price_iv']
                else:
                    if option_down['_ask_iv'] is None or option_down['_bid_iv'] is None:
                        Real_vol_down = option_down['_volatility']
                    else:
                        if option_down['_ask_iv'] is not None and option_down['_bid_iv'] is not None and \
                                option_down['_ask_iv'] > option_down['_volatility'] > option_down['_bid_iv']:
                            Real_vol_down = option_down['_volatility']
                        else:
                            if option_down['_ask_iv'] < option_down['_volatility'] and option_down['_bid_iv'] < \
                                    option_down['_volatility'] or option_down['_volatility'] < option_down['_bid_iv']:
                                Real_vol_down = (option_down['_ask_iv'] + option_down['_bid_iv']) / 2
                                if Real_vol_down > option_down['_volatility'] * 2 or Real_vol_down < option_down[
                                    '_volatility'] / 2:
                                    Real_vol_down = option_down['_volatility']

                option_down['_real_vol'] = Real_vol_down
                MyPosTilt_down = option_down['OpenIV']
                MyPosAverageLine_down = {'optionbase': option_down['_base_asset_ticker'], 'expdate': option_down['_expiration_datetime'], 'net_pos': option_down['net_pos'], 'Real_vol_down': Real_vol_down, 'QuikVola_down':option_down['_volatility'], 'MyPosTilt_down': MyPosTilt_down}
                df_MyPosAverage_down.loc[len(df_MyPosAverage_down)] = MyPosAverageLine_down
                df_MyPosAverage_down['expdate'] = pd.to_datetime(df_MyPosAverage_down['expdate'])  # Убедимся, что expdate — это datetime
                # print(df_MyPosAverage_down)

            # print('df_MyPosAverage_down')
            # print(df_MyPosAverage_down)

            df_MyPosAverage_up.loc[len(df_MyPosAverage_up)] = MyPosAverageLine_up
            df_MyPosAverage_up['expdate'] = pd.to_datetime(df_MyPosAverage_up['expdate'])  # Убедимся, что expdate — это datetime
            # Столбцы, для которых нужно посчитать средневзвешенные
            # Определяем столбцы для "up"
            value_cols_up = ['Real_vol_up', 'QuikVola_up', 'MyPosTilt_up']
            # Группировка и расчёт
            result_up = df_MyPosAverage_up.groupby(['optionbase', 'expdate']).apply(
                lambda g: weighted_mean(g, value_cols_up, 'net_pos'),
                include_groups=False
            ).reset_index()
            # print(f'result_up: {result_up}')

            df_MyPosAverage_down.loc[len(df_MyPosAverage_down)] = MyPosAverageLine_down
            df_MyPosAverage_down['expdate'] = pd.to_datetime(df_MyPosAverage_down['expdate'])  # Убедимся, что expdate — это datetime
            # Столбцы, для которых нужно посчитать средневзвешенные
            value_cols_down = ['Real_vol_down', 'QuikVola_down', 'MyPosTilt_down']
            result_down = df_MyPosAverage_down.groupby(['optionbase', 'expdate']).apply(
                lambda g: weighted_mean(g, value_cols_down, 'net_pos'),
                include_groups=False
            ).reset_index()
            # print(f'result_down: {result_down}')

            # Слияние по optionbase и expdate
            merged = pd.merge(
                result_up,
                result_down,
                on=['optionbase', 'expdate'],
                suffixes=('_up', '_down'),
                how='inner'  # только где есть и up, и down
            )

            # Вычисляем тилты
            merged['RealTilt'] = round((merged['Real_vol_up'] - merged['Real_vol_down']), 2)
            merged['QuikTilt'] = round((merged['QuikVola_up'] - merged['QuikVola_down']), 2)
            merged['MyPosTilt'] = round((merged['MyPosTilt_up'] - merged['MyPosTilt_down']), 2)

            # Меняем тип, чтобы можно было вставлять строки
            merged = merged.astype({'RealTilt': 'object', 'QuikTilt': 'object', 'MyPosTilt': 'object'})

            # Заменяем на пустую строку, где тилт равен 0
            mask = (merged['RealTilt'] == 0) | (merged['QuikTilt'] == 0) | (merged['MyPosTilt'] == 0)
            merged.loc[mask, 'RealTilt'] = ""
            merged.loc[mask, 'QuikTilt'] = ""
            merged.loc[mask, 'MyPosTilt'] = ""

            # Формируем итоговый DataFrame
            output_df = pd.DataFrame({
                'DateTime': current_DateTimestamp.strftime('%Y-%m-%d %H:%M:%S'),
                'expdate': pd.to_datetime(merged['expdate']).dt.strftime('%Y-%m-%d'),
                'optionbase': merged['optionbase'],
                'RealTilt': merged['RealTilt'],
                'QuikTilt': merged['QuikTilt'],
                'MyPosTilt': merged['MyPosTilt']
            })

            print(output_df)
            # Записываем строки из output_df без заголовков
            for _, row in output_df.iterrows():
                writer.writerow(row.tolist())
        f.close()

    except Exception as e:
        print(f"Ошибка в функции my_function: {str(e)}")


schedule.every(20).seconds.do(my_function)

while True:
    schedule.run_pending()
    time.sleep(1)
