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
Вариант кода v2 - расчет наклона улыбки с учетом позиций во всех сериях одновременно
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
    weights = group[weight_col]
    if weights.sum() == 0:
        return pd.Series({col: 0 for col in value_cols})
    return pd.Series({
        col: np.average(group[col], weights=weights) if col in group.columns else 0
        for col in value_cols
    })

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
        # print('\n')
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

            df_MyPosAverage_up.loc[len(df_MyPosAverage_up)] = MyPosAverageLine_up
            df_MyPosAverage_up['expdate'] = pd.to_datetime(df_MyPosAverage_up['expdate'])  # Убедимся, что expdate — это datetime
            # Столбцы, для которых нужно посчитать средневзвешенные
            # Определяем столбцы для "up"
            value_cols_up = ['Real_vol_up', 'QuikVola_up', 'MyPosTilt_up']
            # Группировка и расчёт для одной серии "up"
            result_up = df_MyPosAverage_up.groupby(['optionbase', 'expdate']).apply(
                lambda g: weighted_mean(g, value_cols_up, 'net_pos'),
                include_groups=False
            ).reset_index()
            # print(f'result_up: {result_up}')


            df_MyPosAverage_down.loc[len(df_MyPosAverage_down)] = MyPosAverageLine_down
            df_MyPosAverage_down['expdate'] = pd.to_datetime(df_MyPosAverage_down['expdate'])  # Убедимся, что expdate — это datetime
            # Столбцы, для которых нужно посчитать средневзвешенные для "down"
            value_cols_down = ['Real_vol_down', 'QuikVola_down', 'MyPosTilt_down']
            # Группировка и расчёт для одной серии "down"
            result_down = df_MyPosAverage_down.groupby(['optionbase', 'expdate']).apply(
                lambda g: weighted_mean(g, value_cols_down, 'net_pos'),
                include_groups=False
            ).reset_index()
            # print(result_down)

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

            # === СОБИРАЕМ ВСЕ СТРОКИ В СПИСОК ===
            all_rows_list = []

            # Добавляем строки по expdate
            for idx, row in merged.iterrows():
                all_rows_list.append({
                    'DateTime': current_DateTimestamp.strftime('%Y-%m-%d %H:%M:%S'),
                    'expdate': row['expdate'].strftime('%Y-%m-%d'),
                    'optionbase': row['optionbase'],
                    'RealTilt': row['RealTilt'],
                    'QuikTilt': row['QuikTilt'],
                    'MyPosTilt': row['MyPosTilt']
                })

            # === АГРЕГАЦИЯ ПО ВСЕМ ДАТАМ (ALL) ===
            df_all_up = df_MyPosAverage_up.copy()
            df_all_down = df_MyPosAverage_down.copy()

            df_all_up['net_pos'] = pd.to_numeric(df_all_up['net_pos'], errors='coerce')
            df_all_down['net_pos'] = pd.to_numeric(df_all_down['net_pos'], errors='coerce')

            df_all_up.dropna(subset=['net_pos'], inplace=True)
            df_all_down.dropna(subset=['net_pos'], inplace=True)

            if not df_all_up.empty and not df_all_down.empty:
                w_up = df_all_up['net_pos']
                w_down = df_all_down['net_pos']

                sum_w_up = w_up.sum()
                sum_w_down = w_down.sum()

                result_up_ALL = {
                    'Real_vol_up': np.average(df_all_up['Real_vol_up'], weights=w_up) if sum_w_up != 0 else 0,
                    'QuikVola_up': np.average(df_all_up['QuikVola_up'], weights=w_up) if sum_w_up != 0 else 0,
                    'MyPosTilt_up': np.average(df_all_up['MyPosTilt_up'], weights=w_up) if sum_w_up != 0 else 0
                }

                result_down_ALL = {
                    'Real_vol_down': np.average(df_all_down['Real_vol_down'], weights=w_down) if sum_w_down != 0 else 0,
                    'QuikVola_down': np.average(df_all_down['QuikVola_down'], weights=w_down) if sum_w_down != 0 else 0,
                    'MyPosTilt_down': np.average(df_all_down['MyPosTilt_down'],
                                                 weights=w_down) if sum_w_down != 0 else 0
                }

                RealTilt_ALL = round(result_up_ALL['Real_vol_up'] - result_down_ALL['Real_vol_down'], 2)
                QuikTilt_ALL = round(result_up_ALL['QuikVola_up'] - result_down_ALL['QuikVola_down'], 2)
                MyPosTilt_ALL = round(result_up_ALL['MyPosTilt_up'] - result_down_ALL['MyPosTilt_down'], 2)

                # Замена на "" если один из тилтов нулевой
                RealTilt_ALL_str = "" if RealTilt_ALL == 0 or QuikTilt_ALL == 0 else RealTilt_ALL
                QuikTilt_ALL_str = "" if RealTilt_ALL == 0 or QuikTilt_ALL == 0 else QuikTilt_ALL

                optionbase_ALL = (
                    merged['optionbase'].iloc[0] if not merged.empty
                    else base_asset_list[0] if base_asset_list else "UNKNOWN"
                )

                # Добавляем строку ALL в общий список
                all_rows_list.append({
                    'DateTime': current_DateTimestamp.strftime('%Y-%m-%d %H:%M:%S'),
                    'expdate': 'ALL',
                    'optionbase': optionbase_ALL,
                    'RealTilt': RealTilt_ALL_str,
                    'QuikTilt': QuikTilt_ALL_str,
                    'MyPosTilt': round(MyPosTilt_ALL, 2)
                })
            else:
                print("Недостаточно данных для агрегации ALL")

            # === ФОРМИРУЕМ output_df ОДНИМ СОЗДАНИЕМ ===
            output_df = pd.DataFrame(all_rows_list)
            # print(output_df)

            # Если список пуст — выходим
            if output_df.empty:
                print("Нет данных для записи.")
                return

            # Записываем в файл
            for _, row in output_df.iterrows():
                writer.writerow(row.tolist())
        f.close()

    except Exception as e:
        print(f"Ошибка в функции my_function: {str(e)}")


schedule.every(20).seconds.do(my_function)

while True:
    schedule.run_pending()
    time.sleep(1)
