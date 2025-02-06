import logging  # Выводим лог на консоль и в файл
from datetime import datetime, timedelta  # Дата и время, временной интервал
import pandas as pd
import asyncio
import json
import hashlib
from http.client import responses
import time

import websockets
from central_strike import get_list_of_strikes
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
asset_list = ('RTS','Si')
asset_code = 'RTS'
URL_API = f'https://api.alor.ru'

ap_provider = AlorPy()  # Подключаемся ко всем торговым счетам
# Проверяем работу запрос/ответ
seconds_from = ap_provider.get_time()  # Время в Alor OpenAPI V2 передается в секундах, прошедших с 01.01.1970 00:00 UTC
print(f'Дата и время на сервере: {ap_provider.utc_timestamp_to_msk_datetime(seconds_from):%d.%m.%Y %H:%M:%S}')  # В AlorPy это время можно перевести в МСК для удобства восприятия)
S_time = datetime.now()
print(f'Текущее время: {S_time.strftime('%d.%m.%Y %H:%M:%S')}')


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

results = []
close_price_by_ticker_dict = {}
# Подписка на свечи
def save_bar(response):
    seconds = response['data']['time']  # Время в Alor OpenAPI V2 передается в секундах, прошедших с 01.01.1970 00:00 UTC
    dt_msk = datetime.utcfromtimestamp(seconds) if type(tf) is str else ap_provider.utc_timestamp_to_msk_datetime(seconds)  # Дневные бары и выше ставим на начало дня по UTC. Остальные - по МСК
    str_dt_msk = dt_msk.strftime('%d.%m.%Y') if type(tf) is str else dt_msk.strftime('%d.%m.%Y %H:%M:%S')  # Для дневных баров и выше показываем только дату. Для остальных - дату и время по МСК
    guid = response['guid']
    # opcode = subscription['opcode']  # Разбираем по типу подписки
    # print(f'websocket_handler: Пришли данные подписки {opcode} - {guid} - {response}')
    # print(f'{subscription["exchange"]}.{guid_symbol.get(guid)} ({subscription["tf"]}) - {str_dt_msk} - Open = {response["data"]["open"]}, High = {response["data"]["high"]}, Low = {response["data"]["low"]}, Close = {response["data"]["close"]}, Volume = {response["data"]["volume"]}')
    response["data"]['time'] = str_dt_msk
    response["data"]['code'] = guid_symbol.get(guid)
    results.append(response["data"])
    close_price_by_ticker_dict[guid_symbol.get(guid)] = response["data"]['close']
    # print(close_price_by_ticker_dict)

# Подписываемся на бары текущего фьючерса из списка list_futures_current
guid_symbol = {}
for symbol in list_futures_all:
    tf = 60  # 60 = 1 минута, 300 = 5 минут, 3600 = 1 час, 'D' = день, 'W' = неделя, 'M' = месяц, 'Y' = год
    days = 3  # Кол-во последних календарных дней, за которые берем историю
    seconds_from = ap_provider.msk_datetime_to_utc_timestamp(datetime.now() - timedelta(days=days))  # За последние дни. В секундах, прошедших с 01.01.1970 00:00 UTC
    guid = ap_provider.bars_get_and_subscribe(exchange, symbol, tf, seconds_from, frequency=1_000_000_000)  # Подписываемся на бары, получаем guid подписки
    subscription = ap_provider.subscriptions[guid] # Получаем данные подписки
    # print(symbol, subscription['code'], guid)
    # Создание словаря для сопоставления 'gud' подписки и 'symbol'
    guid_symbol[guid] = symbol
    ap_provider.on_new_bar = save_bar
# print('\n Словарь для сопоставления подписки получения баров и тикера фьючерса:','\n', guid_symbol)

time.sleep(5)
print(f'Дата и время на сервере: {ap_provider.utc_timestamp_to_msk_datetime(seconds_from):%d.%m.%Y %H:%M:%S}')
df_bars = pd.DataFrame(results, columns = ["code", "time", "open", "high", "low", "close", "volume"])
print(df_bars)

# Формируем кортеж тикеров фьючерсов "datanames_futures" типа MOEX:RIM5 для подписки на котировки
datanames_futures = []
for i in range(len(list_futures_all)):
    datanames_futures.append(f'{exchange}:{list_futures_all[i]}')
# print('\n datanames_futures:', '\n', datanames_futures)

# option_expirations = get_option_expirations(fut_1) # Получить список дат окончания действия опционов базовых активов

# Опционные серии по базовым активам
option_series_by_name_series = {}
for i in range(len(asset_list)):
    data = get_option_series(asset_list[i])
    # print(data)
    for item in data:
        if item['underlying_asset'] in list_futures_all:
            option_series_by_name_series[item['name']] = (item['underlying_asset'])
# print("\n Словарь Опционная серия:Базовый актив", '\n', option_series_by_name_series)

# Формируем кортеж тикеров опционов
secid_list = []
# print(option_series_by_name_series.keys())
# print(len(option_series_by_name_series.keys()))
# print(option_series_by_name_series[1])
for m in option_series_by_name_series.keys(): # Пробегаемся по списку опционных серий
    ticker = option_series_by_name_series[m] # Тикер базового актива
    base_asset_price = close_price_by_ticker_dict[ticker]  # Цена базового актива
    strike_step = MAP[ticker]['strike_step']  # Шаг страйка
    strikes_count = MAP[ticker]['max_strikes_count']  # Кол-во страйков
    data = get_option_list_by_series(m) # Получаем список опционов по опционной серии
    for k in range(len(data)): # Пробегаемся по списку опционов
        strikes = get_list_of_strikes(base_asset_price, strike_step, strikes_count) # Получаем список страйков
        if data[k]['strike'] in strikes: # Если страйк в списке страйков
            secid_list.append(data[k]['secid']) # Добавляем тикер в список
    # print(ticker, m, secid_list)
    # print('Количество опционов в серии: ', len(secid_list))
time.sleep(5)
print("\n Тикеры необходимых опционных серий:", '\n', secid_list)
print('\n Количество тикеров опционов:', len(secid_list))

# Формируем кортеж тикеров опционов "datanames_options" для подписки на котировки
datanames_options = []
for i in range(len(secid_list)):
    datanames_options.append(f'{exchange}:{secid_list[i]}')
# print('\n Кортеж тикеров опционов типа MOEX:RI85000BF5 :', '\n', datanames_options)

# Запрос котировок из списка тикеров (подписка)



# Выход
input('\nEnter - выход\n')
for guid in guid_symbol.keys():
    ap_provider.unsubscribe(guid)  # Отписываемся от получения новых баров
    print(f'Отмена подписки {guid}. Закрытие WebSocket по всем правилам займет некоторое время')
ap_provider.close_web_socket()  # Перед выходом закрываем соединение с WebSocket