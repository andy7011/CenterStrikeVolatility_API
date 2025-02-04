import logging  # Выводим лог на консоль и в файл
from datetime import datetime, timedelta  # Дата и время, временной интервал
import pandas as pd
import asyncio
import json
import hashlib
from http.client import responses
import time

import websockets
from central_strike import _calculate_central_strike
from supported_base_asset import MAP
from moex_api import get_futures_series
from moex_api import get_option_series
from moex_api import get_option_list_by_series
from moex_api import get_option_expirations

_APP_ID = 'option_volatility_list'

_REFRESH_TOKEN_URL = 'https://oauth.alor.ru/refresh'
_WEBSOCKET_URL = 'wss://api.alor.ru/ws'
_EXCHANGE_MOEX = "MOEX"

_API_METHOD_QUOTES_SUBSCRIBE = "QuotesSubscribe"
_API_METHOD_INSTRUMENTS_GET_AND_SUBSCRIBE = "InstrumentsGetAndSubscribeV2"

from AlorPy import AlorPy  # Работа с Alor OpenAPI V2
exchange = 'MOEX'
asset_list = ('RTS','Si', 'CNY')
asset_code = 'RTS'
URL_API = f'https://api.alor.ru'

ap_provider = AlorPy()  # Подключаемся ко всем торговым счетам
# Проверяем работу запрос/ответ
seconds_from = ap_provider.get_time()  # Время в Alor OpenAPI V2 передается в секундах, прошедших с 01.01.1970 00:00 UTC
print(f'Дата и время на сервере: {ap_provider.utc_timestamp_to_msk_datetime(seconds_from):%d.%m.%Y %H:%M:%S}')  # В AlorPy это время можно перевести в МСК для удобства восприятия)

# Две ближайшие (текущая и следующая) фьючерсные серии по базовому активу из списка asset_list
list_futures_current = []
list_futures_all = []
for asset_code in asset_list: # Пробегаемся по списку активов
    data_fut = get_futures_series(asset_code)
    info_fut_1 = data_fut[len(data_fut) - 1]
    list_futures_current.append(info_fut_1['secid'])
    list_futures_all.append(info_fut_1['secid'])
    info_fut_2 = data_fut[len(data_fut) - 2]
    list_futures_all.append(info_fut_2['secid'])
# print('\n list_futures_current', '\n', list_futures_current)
# print('list_futures_all', '\n', list_futures_all)

futures_bars = {}

# # noinspection PyShadowingNames
# def log_bar(response):  # Вывод в лог полученного бара
#     seconds = response['data']['time']  # Время в Alor OpenAPI V2 передается в секундах, прошедших с 01.01.1970 00:00 UTC
#     dt_msk = datetime.utcfromtimestamp(seconds) if type(tf) is str else ap_provider.utc_timestamp_to_msk_datetime(seconds)  # Дневные бары и выше ставим на начало дня по UTC. Остальные - по МСК
#     str_dt_msk = dt_msk.strftime('%d.%m.%Y') if type(tf) is str else dt_msk.strftime('%d.%m.%Y %H:%M:%S')  # Для дневных баров и выше показываем только дату. Для остальных - дату и время по МСК
#     guid = response['guid']  # Код подписки
#     subscription = ap_provider.subscriptions[guid]  # Подписка
#     print(f'{subscription["exchange"]}.{subscription["code"]} ({subscription["tf"]}) - {str_dt_msk} - Open = {response["data"]["open"]}, High = {response["data"]["high"]}, Low = {response["data"]["low"]}, Close = {response["data"]["close"]}, Volume = {response["data"]["volume"]}')

results = []
def save_bar(response):
    seconds = response['data']['time']  # Время в Alor OpenAPI V2 передается в секундах, прошедших с 01.01.1970 00:00 UTC
    dt_msk = datetime.utcfromtimestamp(seconds) if type(tf) is str else ap_provider.utc_timestamp_to_msk_datetime(seconds)  # Дневные бары и выше ставим на начало дня по UTC. Остальные - по МСК
    str_dt_msk = dt_msk.strftime('%d.%m.%Y') if type(tf) is str else dt_msk.strftime('%d.%m.%Y %H:%M:%S')  # Для дневных баров и выше показываем только дату. Для остальных - дату и время по МСК
    # opcode = subscription['opcode']  # Разбираем по типу подписки
    # print(f'websocket_handler: Пришли данные подписки {opcode} - {guid} - {response}')
    guid = response['guid']
    response["data"]['time'] = str_dt_msk
    response["data"]['code'] = guid_symbol.get(guid)
    results.append(response["data"])

# Подписываемся на бары текущего фьючерса из списка list_futures_current
guid_symbol = {}
for symbol in list_futures_current:
    tf = 60  # 60 = 1 минута, 300 = 5 минут, 3600 = 1 час, 'D' = день, 'W' = неделя, 'M' = месяц, 'Y' = год
    days = 3  # Кол-во последних календарных дней, за которые берем историю
    seconds_from = ap_provider.msk_datetime_to_utc_timestamp(datetime.now() - timedelta(days=days))  # За последние дни. В секундах, прошедших с 01.01.1970 00:00 UTC
    guid = ap_provider.bars_get_and_subscribe(exchange, symbol, tf, seconds_from, frequency=1_000_000_000)  # Подписываемся на бары, получаем guid подписки
    subscription = ap_provider.subscriptions[guid] # Получаем данные подписки
    # print(symbol, subscription['code'], guid)
    # Создание словаря для сопоставления 'gud' подписки и 'symbol'
    guid_symbol[guid] = symbol
    ap_provider.on_new_bar = save_bar
# print(guid_symbol)


# Формируем кортеж тикеров "datanames" для подписки на котировки
datanames_futures = []
for i in range(len(list_futures_all)):
    datanames_futures.append(f'{exchange}:{list_futures_all[i]}')
# print('\n datanames_futures:', '\n', datanames_futures)

# option_expirations = get_option_expirations(fut_1) + get_option_expirations(fut_2) # Получить список дат окончания действия опционов базовых активов fut_1 + fut_2
# datanames = (f'{exchange}:{symbol}',)

# Опционные серии по базовому активу fut_1 (текущая серия)
option_series_by_name_series = []
for i in range(len(asset_list)):
    data = get_option_series(asset_list[i])
    for item in data:
        if item['underlying_asset'] in list_futures_all:
            option_series_by_name_series.append(item['name'])
# print("\n Опционные серии:", '\n', option_series_by_name_series)

secid_list = []
data = get_option_list_by_series(option_series_by_name_series[0])
for i in range(len(data)):
    secid_list.append(data[i]['secid'])
# print("\n Тикеры опционных серий:", '\n', secid_list)

time.sleep(5)
print(f'Дата и время на сервере: {ap_provider.utc_timestamp_to_msk_datetime(seconds_from):%d.%m.%Y %H:%M:%S}')
df_bars = pd.DataFrame(results, columns = ["code", "time", "open", "high", "low", "close", "volume"])
print(df_bars)
base_asset_price = df_bars['close'].iloc[-1]
print(base_asset_price)
strike_step = MAP['SiH5']['strike_step']
central_strike = _calculate_central_strike(base_asset_price, strike_step)
print(central_strike)



# Выход
input('\nEnter - выход\n')
ap_provider.unsubscribe(guid)  # Отписываемся от получения новых баров
print(f'Отмена подписки {guid}. Закрытие WebSocket по всем правилам займет некоторое время')
ap_provider.close_web_socket()  # Перед выходом закрываем соединение с WebSocket