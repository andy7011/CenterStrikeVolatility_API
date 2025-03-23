import schedule
import time
import requests
from datetime import datetime
import pandas as pd

# from Dash_Example import last_price
from central_strike import _calculate_central_strike
from supported_base_asset import MAP
import csv
import random
from string import Template

# Конфигурация для работы с файлами
temp_str = 'C:\\Users\\Андрей\\YandexDisk\\_ИИС\\Position\\$name_file'
temp_obj = Template(temp_str)

last_price_lifetime = 60 * 15 # время жизни последней цены last_price для расчетов (15 минут в секундах)

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
                central_strike = _calculate_central_strike(base_asset_last_price, strike_step)  # вычисление центрального страйка
                central_strikes_map[ticker] = central_strike
                asset.update({
                    'central_strike': central_strike
                })
        f.close()

        current_datetime = datetime.now()
        print(f"Дата и время: {current_datetime.strftime('%Y-%m-%d %H:%M:%S')}")

        # Список опционов
        option_list = model_from_api[1]
        filtered_option_list = []
        for option in option_list:
            base_asset_ticker = option['_base_asset_ticker']
            if option['_strike'] == central_strikes_map[base_asset_ticker]:
                option['datetime'] = current_datetime
                date_object = datetime.strptime(option['_expiration_datetime'], "%a, %d %b %Y %H:%M:%S GMT").date()
                option['_expiration_datetime'] = date_object.strftime('%d.%m.%Y')
                filtered_option_list.append(option)

        # print(filtered_option_list)
        with open(temp_obj.substitute(name_file='OptionsVolaHistoryDamp.csv'), 'a', newline='') as f:
            writer = csv.writer(f, delimiter=";", lineterminator="\r")
            # Вычисление/определение реальной волатильности Real_vol
            for option in filtered_option_list:
                current_DateTimestamp = datetime.now()
                currentTimestamp = int(datetime.timestamp(current_DateTimestamp))  # текущее время в секундах UTC
                if option['_last_price_timestamp'] is not None and currentTimestamp - option['_last_price_timestamp'] < last_price_lifetime: # если есть LastPrice и время жизни его не истекло
                    Real_vol = option['_last_price_iv']
                    # print('Last Vola Real_vol=', Real_vol, option['_ticker'], option['_type'], option['_expiration_datetime'], 'bid=', option['_bid_iv'], 'last=', option['_last_price_iv'], 'ask=', option['_ask_iv'], 'quik_vol=', option['_volatility'])
                else:
                    if option['_ask_iv'] is None or option['_bid_iv'] is None: # нет бида или нет аска
                        Real_vol = option['_volatility']
                        # print('QUIK Vola (нет бида или аска) Real_vol=', Real_vol, option['_ticker'], option['_type'], option['_expiration_datetime'], 'bid=', option['_bid_iv'], 'last=', option['_last_price_iv'], 'ask=', option['_ask_iv'], 'quik_vol=', option['_volatility'])
                    else:
                        if option['_ask_iv'] is not None and option['_bid_iv'] is not None and option['_ask_iv'] > option['_volatility'] > option['_bid_iv']: # в пределах спреда bid-ask
                            Real_vol = option['_volatility']
                            # print('QUIK Vola в пределах спреда Real_vol=', Real_vol, option['_ticker'], option['_type'], option['_expiration_datetime'], 'bid=', option['_bid_iv'], 'last=', option['_last_price_iv'], 'ask=', option['_ask_iv'], 'quik_vol=', option['_volatility'])
                        else:
                            if option['_ask_iv'] < option['_volatility'] and option['_bid_iv'] < option['_volatility'] and option['_ask_iv'] < option['_volatility'] or option['_volatility'] < option['_bid_iv']: # вне пределов спреда bid-ask
                                Real_vol = (option['_ask_iv'] + option['_bid_iv']) / 2
                                # print('Середина спреда (вола квика вне пределов bid-ask) Real_vol=', Real_vol, option['_ticker'], option['_type'], option['_expiration_datetime'], 'bid=', option['_bid_iv'], 'last=', option['_last_price_iv'], 'ask=', option['_ask_iv'], 'quik_vol=', option['_volatility'])
                            else:
                                # Real_vol = option['_volatility']
                                print('None', option['_ticker'], option['_type'], option['_expiration_datetime'], 'bid=', option['_bid_iv'], 'last=', option['_last_price_iv'], 'ask=', option['_ask_iv'], 'quik_vol=', option['_volatility'])
                option['_real_vol'] = Real_vol
                if option['_type'] == 'C':
                    option['_type'] = 'Call'
                elif option['_type'] == 'P':
                    option['_type'] = 'Put'

                # print(current_DateTimestamp.strftime('%Y-%m-%d %H:%M:%S'), option['_ticker'], option['_type'], option['_strike'],
                #                      option['_expiration_datetime'], option['_base_asset_ticker'], option['_ask'],
                #                      option['_ask_iv'], option['_bid'], option['_bid_iv'], option['_last_price'],
                #                      option['_last_price_iv'], option['_last_price_timestamp'], Real_vol)
                data_options_vola = [current_DateTimestamp.strftime('%Y-%m-%d %H:%M:%S'), option['_ticker'], option['_type'], option['_strike'],
                                     option['_expiration_datetime'], option['_base_asset_ticker'], option['_ask'],
                                     option['_ask_iv'], option['_bid'], option['_bid_iv'], option['_last_price'],
                                     option['_last_price_iv'], option['_last_price_timestamp'], Real_vol]
                writer.writerow(data_options_vola)
        f.close()

        df_vol_history = pd.DataFrame.from_dict(filtered_option_list, orient='columns')
        df_vol_history.set_index('datetime', inplace=True)
        df_vol_history.index = df_vol_history.index.strftime('%d.%m.%Y %H:%M:%S')  # Reformat the date index using strftime()
        # print(df_vol_history[['_ticker', '_type', '_expiration_datetime', '_real_vol']])

    except Exception as e:
        print(f"Ошибка в функции my_function: {str(e)}")


schedule.every(60).seconds.do(my_function)

while True:
    schedule.run_pending()
    time.sleep(1)