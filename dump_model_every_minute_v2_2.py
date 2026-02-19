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
clean_old_records(temp_obj.substitute(name_file='OptionsVolaHistoryDamp.csv'))
print(f"Очистка файла исторических данных волатильности опционов на ЦС OptionsVolaHistoryDamp.csv от старых записей (старше 14 дней) завершена")
clean_old_records(temp_obj.substitute(name_file='OptionsSmileNaklonHistory.csv'))
print(f"Очистка файла истории наклона улыбки OptionsSmileNaklonHistory.csv от старых записей (старше 14 дней) завершена")


def my_function():
    """Основная функция обработки данных."""
    if not is_business_time():
        print("Текущее время находится в нерабочих часах или выходной день")
        return

    try:
        model_from_api = get_object_from_json_endpoint('https://option-volatility-dashboard.tech/dump_model')

        base_asset_list = model_from_api[0] # список базовых активов

        # Находим центральный страйк для каждого базового актива, а также страйки смещенные влево и
        # вправо на величину offset и рядом расположенные (adjacent) страйки
        central_strikes_map = {}
        strikes_map_up = {}
        adjacent_strikes_map_up = {}
        strikes_map_down = {}
        adjacent_strikes_map_down = {}
        relative_offset_map = {}
        offset = 3  # количество шагов (strike_step) для смещения вверх и вниз от центрального страйка
        for asset in base_asset_list:
            ticker = asset.get('_ticker')
            strike_step = MAP[ticker]['strike_step']
            base_asset_last_price = asset.get('_last_price')  # последняя цена базового актива
            central_strike = _calculate_central_strike(base_asset_last_price, strike_step)
            central_strikes_map[ticker] = central_strike
            asset.update({'central_strike': central_strike})
            # print('\n')
            # print(f"Последняя цена базового актива для {ticker}: {base_asset_last_price}")
            base_asset_last_price_offset_plus = base_asset_last_price + (strike_step * offset)
            base_asset_last_price_offset_minus = base_asset_last_price - (strike_step * offset)
            offset_strike_plus = _calculate_central_strike(base_asset_last_price_offset_plus,
                                                           strike_step)  # смещенный страйк вверх
            offset_strike_minus = _calculate_central_strike(base_asset_last_price_offset_minus,
                                                            strike_step)  # смещенный страйк вниз
            central_strike = _calculate_central_strike(base_asset_last_price, strike_step)  # центральный страйк
            # print(f"Центральный страйк для {ticker}: {central_strike}")
            offset_asset_last_price = central_strike - base_asset_last_price  # Смещение в пунктах текущей цены базового актива от центрального страйка
            # print(f"Смещение в пунктах текущей цены базового актива от центрального страйка для {ticker}: {offset_asset_last_price}")
            relative_offset = offset_asset_last_price / strike_step  # Относительное смещение цены базового актива от центрального страйка
            # print(f"relative_offset - Относительное смещение цены базового актива от центрального страйка для {ticker}: {relative_offset}")
            relative_offset_map[ticker] = relative_offset
            # Определяем смежный страйк (слева -1 или справа +1)
            if offset_asset_last_price > 0:
                adjacent_strike = -1
            elif offset_asset_last_price <= 0:
                adjacent_strike = 1
            # print(f"Смежный страйк (слева -1 или справа +1) для {ticker}: {adjacent_strike}")

            strikes_map_up[ticker] = offset_strike_plus
            # print(f"Верхний страйк для {ticker}: {offset_strike_plus}")

            adjacent_base_asset_last_price_offset_plus = base_asset_last_price + (
                    strike_step * (offset + adjacent_strike))
            adjacent_offset_strike_plus = _calculate_central_strike(adjacent_base_asset_last_price_offset_plus,
                                                                    strike_step)  # Верхний смежный страйк
            adjacent_strikes_map_up[ticker] = adjacent_offset_strike_plus
            # print(f"Верхний смежный страйк для {ticker}: {adjacent_offset_strike_plus}")

            strikes_map_down[ticker] = offset_strike_minus
            # print(f"Нижний страйк для {ticker}: {offset_strike_minus}")
            adjacent_base_asset_last_price_offset_minus = base_asset_last_price - (
                    strike_step * (offset - adjacent_strike))
            adjacent_offset_strike_minus = _calculate_central_strike(adjacent_base_asset_last_price_offset_minus,
                                                                     strike_step)  # Нижний смежный страйк
            adjacent_strikes_map_down[ticker] = adjacent_offset_strike_minus
            # print(f"Нижний смежный страйк для {ticker}: {adjacent_offset_strike_minus}")

            asset.update({'offset_strike_plus': offset_strike_plus})
            asset.update({'adjacent_offset_strike_plus': adjacent_offset_strike_plus})
            asset.update({'offset_strike_minus': offset_strike_minus})
            asset.update({'adjacent_offset_strike_minus': adjacent_offset_strike_minus})
        # print(f'strikes_map_up: {strikes_map_up}')
        # print(f'adjacent_strikes_map_up: {adjacent_strikes_map_up}')
        # print(f'strikes_map_down: {strikes_map_down}')
        # print(f'adjacent_strikes_map_down: {adjacent_strikes_map_down}')
        # print(f'relative_offset_map: {relative_offset_map}')
        # print('\n')

        current_datetime = datetime.now()
        print(f"Дата и время: {current_datetime.strftime('%Y-%m-%d %H:%M:%S')}")

        option_list = model_from_api[1] # список опционов
        filtered_option_list = []
        filtered_option_list_up = []
        adjacent_filtered_option_list_up = []
        filtered_option_list_down = []
        adjacent_filtered_option_list_down = []
        for option in option_list:
            base_asset_ticker = option['_base_asset_ticker']
            if option['_strike'] == central_strikes_map[base_asset_ticker]:
                option['datetime'] = current_datetime
                date_object = datetime.strptime(option['_expiration_datetime'], "%a, %d %b %Y %H:%M:%S GMT").date()
                option['_expiration_datetime'] = date_object.strftime('%Y-%m-%d')
                filtered_option_list.append(option)
            elif option['_strike'] == strikes_map_up[base_asset_ticker] and option[
                '_type'] == 'C':  # фильтрация опционов по страйкам
                option['datetime'] = current_datetime
                date_object = datetime.strptime(option['_expiration_datetime'], "%a, %d %b %Y %H:%M:%S GMT").date()
                option['_expiration_datetime'] = date_object.strftime('%Y-%m-%d')
                filtered_option_list_up.append(option)
            elif option['_strike'] == adjacent_strikes_map_up[base_asset_ticker] and option[
                '_type'] == 'C':  # фильтрация опционов по смежным страйкам
                option['datetime'] = current_datetime
                date_object = datetime.strptime(option['_expiration_datetime'], "%a, %d %b %Y %H:%M:%S GMT").date()
                option['_expiration_datetime'] = date_object.strftime('%Y-%m-%d')
                adjacent_filtered_option_list_up.append(option)
            elif option['_strike'] == strikes_map_down[base_asset_ticker] and option[
                '_type'] == 'P':  # фильтрация опционов по страйкам
                option['datetime'] = current_datetime
                date_object = datetime.strptime(option['_expiration_datetime'], "%a, %d %b %Y %H:%M:%S GMT").date()
                option['_expiration_datetime'] = date_object.strftime('%Y-%m-%d')
                filtered_option_list_down.append(option)
            elif option['_strike'] == adjacent_strikes_map_down[base_asset_ticker] and option[
                '_type'] == 'P':  # фильтрация опционов по смежным страйкам
                option['datetime'] = current_datetime
                date_object = datetime.strptime(option['_expiration_datetime'], "%a, %d %b %Y %H:%M:%S GMT").date()
                option['_expiration_datetime'] = date_object.strftime('%Y-%m-%d')
                adjacent_filtered_option_list_down.append(option)
        # print(f"Фильтрованный список опционов: {filtered_option_list}")
        # print(f"Фильтрованный список опционов UP: {filtered_option_list_up}")
        # print(f"Фильтрованный список смежных опционов UP: {adjacent_filtered_option_list_up}")
        # print(f"Фильтрованный список опционов DOWN: {filtered_option_list_down}")
        # print(f"Фильтрованный список смежных опционов DOWN: {adjacent_filtered_option_list_down}")

        # Запись в файл волатильности call и put на центральном страйке на текущую минуту
        with open(temp_obj.substitute(name_file='OptionsVolaHistoryDamp.csv'), 'a', newline='') as f:
            writer = csv.writer(f, delimiter=";", lineterminator="\r")
            for option in filtered_option_list:
                current_DateTimestamp = datetime.now()
                currentTimestamp = int(datetime.timestamp(current_DateTimestamp))

                # # Проверяем наличие ключа и что значение не NaN
                # if '_volatility' in option and option['_volatility'] == option['_volatility']:
                # option['_volatility'] = round(option['_volatility'], 2) # округление до двух знаков после запятой

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
                            if option['_ask_iv'] < option['_volatility']:
                                Real_vol = option['_ask_iv']
                            else:
                                if option['_bid_iv'] > option['_volatility']:
                                    Real_vol = option['_bid_iv']
                if Real_vol is None:
                    Real_vol = option['_volatility']

                option['_real_vol'] = Real_vol
                if option['_type'] == 'C':
                    option['_type'] = 'Call'
                elif option['_type'] == 'P':
                    option['_type'] = 'Put'

                data_options_vola = [current_DateTimestamp.strftime('%Y-%m-%d %H:%M:%S'), option['_type'],
                                     option['_expiration_datetime'], option['_base_asset_ticker'], Real_vol,
                                     option['_volatility']]
                writer.writerow(data_options_vola)
        f.close()

        df_vol_history = pd.DataFrame.from_dict(filtered_option_list, orient='columns')
        df_vol_history.set_index('datetime', inplace=True)
        df_vol_history.index = df_vol_history.index.strftime('%Y-%m-%d %H:%M:%S')


        # Запись в файл значений наклона улыбки волатильности на текущую минуту
        with open(temp_obj.substitute(name_file='OptionsSmileNaklonHistory.csv'), 'a', newline='') as f:
            writer = csv.writer(f, delimiter=";", lineterminator="\r")

            for option_up, adjacent_option_up, option_down, adjacent_option_down in zip(filtered_option_list_up,
                                                                                        adjacent_filtered_option_list_up,
                                                                                        filtered_option_list_down,
                                                                                        adjacent_filtered_option_list_down):
                current_DateTimestamp = datetime.now()
                currentTimestamp = int(datetime.timestamp(current_DateTimestamp))

                # print('\n')
                # print(option_up['_base_asset_ticker'], option_up['_expiration_datetime'])

                # print(f"option_up: {option_up['_last_price_iv'], option_up['_last_price_timestamp'], option_up['_ask_iv'], option_up['_bid_iv']}")
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
                # print(f"Real_vol_up: {Real_vol_up, option_up['_strike'], option_up['_base_asset_ticker'], option_up['_expiration_datetime']}")
                # print('\n')

                # print(f"adjacent_option_up: {adjacent_option_up['_last_price_iv'], adjacent_option_up['_last_price_timestamp'], adjacent_option_up['_ask_iv'], adjacent_option_up['_bid_iv']}")
                if adjacent_option_up['_last_price_iv'] is not None and adjacent_option_up[
                    '_last_price_timestamp'] is not None and currentTimestamp - adjacent_option_up[
                    '_last_price_timestamp'] < last_price_lifetime:
                    adjacent_Real_vol_up = adjacent_option_up['_last_price_iv']
                else:
                    if adjacent_option_up['_ask_iv'] is not None and adjacent_option_up['_bid_iv'] is not None and \
                            adjacent_option_up['_ask_iv'] > adjacent_option_up['_volatility'] > adjacent_option_up[
                        '_bid_iv']:
                        adjacent_Real_vol_up = adjacent_option_up['_volatility']
                    else:
                        # Добавляем проверки на None перед сравнениями
                        if (adjacent_option_up['_ask_iv'] is not None and
                                adjacent_option_up['_volatility'] is not None and
                                adjacent_option_up['_bid_iv'] is not None):
                            if adjacent_option_up['_ask_iv'] > adjacent_option_up['_volatility'] > adjacent_option_up[
                                '_bid_iv']:
                                adjacent_Real_vol_up = adjacent_option_up['_volatility']
                            else:
                                # Добавляем проверки на None перед вычислениями
                                if adjacent_option_up['_ask_iv'] is not None and adjacent_option_up[
                                    '_volatility'] is not None and adjacent_option_up['_bid_iv'] is not None:
                                    if (adjacent_option_up['_ask_iv'] < adjacent_option_up['_volatility'] and
                                            adjacent_option_up['_bid_iv'] < adjacent_option_up['_volatility'] or
                                            adjacent_option_up['_volatility'] < adjacent_option_up['_bid_iv']):
                                        adjacent_Real_vol_up = (adjacent_option_up['_ask_iv'] + adjacent_option_up[
                                            '_bid_iv']) / 2
                                        # Добавляем проверку на None перед последним условием
                                        if adjacent_Real_vol_up is not None and adjacent_option_up[
                                            '_volatility'] is not None:
                                            if adjacent_Real_vol_up > adjacent_option_up[
                                                '_volatility'] * 2 or adjacent_Real_vol_up < adjacent_option_up[
                                                '_volatility'] / 2:
                                                adjacent_Real_vol_up = adjacent_option_up['_volatility']
                        else:
                            adjacent_Real_vol_up = adjacent_option_up['_volatility']

                adjacent_option_up['_real_vol'] = adjacent_Real_vol_up
                # print(f"adjacent_Real_vol_up: {adjacent_Real_vol_up, adjacent_option_up['_strike'], adjacent_option_up['_base_asset_ticker'], adjacent_option_up['_expiration_datetime']}")
                # print('\n')

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
                # print(f"Real_vol_down: {Real_vol_down, option_down['_strike'], option_down['_base_asset_ticker'], option_down['_expiration_datetime']}")
                # print('\n')

                if adjacent_option_down['_last_price_iv'] is not None and adjacent_option_down[
                    '_last_price_timestamp'] is not None and currentTimestamp - adjacent_option_down[
                    '_last_price_timestamp'] < last_price_lifetime:
                    adjacent_Real_vol_down = adjacent_option_down['_last_price_iv']
                else:
                    if adjacent_option_down['_ask_iv'] is None or adjacent_option_down['_bid_iv'] is None:
                        adjacent_Real_vol_down = adjacent_option_down['_volatility']
                    else:
                        if adjacent_option_down['_ask_iv'] is not None and adjacent_option_down[
                            '_bid_iv'] is not None and adjacent_option_down['_ask_iv'] > adjacent_option_down[
                            '_volatility'] > adjacent_option_down['_bid_iv']:
                            adjacent_Real_vol_down = adjacent_option_down['_volatility']
                        else:
                            if adjacent_option_down['_ask_iv'] < adjacent_option_down['_volatility'] and \
                                    adjacent_option_down['_bid_iv'] < adjacent_option_down['_volatility'] or \
                                    adjacent_option_down['_volatility'] < adjacent_option_down['_bid_iv']:
                                adjacent_Real_vol_down = (adjacent_option_down['_ask_iv'] + adjacent_option_down[
                                    '_bid_iv']) / 2
                                if adjacent_Real_vol_down > adjacent_option_down[
                                    '_volatility'] * 2 or adjacent_Real_vol_down < adjacent_option_down[
                                    '_volatility'] / 2:
                                    adjacent_Real_vol_down = adjacent_option_down['_volatility']

                adjacent_option_down['_real_vol'] = adjacent_Real_vol_down
                # print(f"adjacent_Real_vol_down: {adjacent_Real_vol_down, adjacent_option_down['_strike'], adjacent_option_down['_base_asset_ticker'], adjacent_option_down['_expiration_datetime']}")
                # print('\n')

                if Real_vol_up is None and adjacent_Real_vol_up is None and Real_vol_down is None and adjacent_Real_vol_down is None:
                    Real = None
                    Quik = None
                else:
                    difference_up = Real_vol_up - adjacent_Real_vol_up
                    # print(f"difference_up: {difference_up}")
                    shifting_vol_up = difference_up * relative_offset_map.get(option_up['_base_asset_ticker'])
                    # print(f"shifting_vol_up: {shifting_vol_up}")
                    if relative_offset_map.get(option_up['_base_asset_ticker']) < 0:
                        Real_vol_up = Real_vol_up + shifting_vol_up
                        Quik_up = option_up['_volatility'] + shifting_vol_up
                    else:
                        Real_vol_up = Real_vol_up - shifting_vol_up
                        Quik_up = option_up['_volatility'] - shifting_vol_up

                    difference_down = Real_vol_down - adjacent_Real_vol_down
                    # print(f"difference_down: {difference_down}")
                    shifting_vol_down = difference_down * relative_offset_map.get(option_up['_base_asset_ticker'])
                    # print(f"shifting_vol_down: {shifting_vol_down}")
                    if relative_offset_map.get(option_up['_base_asset_ticker']) < 0:
                        Real_vol_down = Real_vol_down + shifting_vol_down
                        Quik_down = option_down['_volatility'] + shifting_vol_down
                    else:
                        Real_vol_down = Real_vol_down - shifting_vol_down
                        Quik_down = option_down['_volatility'] - shifting_vol_down

                    Real = None if round(Real_vol_up - Real_vol_down, 2) == 0 else round(Real_vol_up - Real_vol_down, 2)
                    Quik = None if round(Quik_up - Quik_down, 2) == 0 else round(Quik_up - Quik_down, 2)
                # print(f"Real, Quik: {round(Real, 2), round(Quik, 2)}")

                data_options_naklon = [current_DateTimestamp.strftime('%Y-%m-%d %H:%M:%S'),
                                       option_up['_expiration_datetime'], option_up['_base_asset_ticker'],
                                       Real, Quik]
                writer.writerow(data_options_naklon)
        f.close()

    except Exception as e:
        print(f"Ошибка в функции my_function: {str(e)}")


schedule.every(60).seconds.do(my_function)

while True:
    schedule.run_pending()
    time.sleep(1)
