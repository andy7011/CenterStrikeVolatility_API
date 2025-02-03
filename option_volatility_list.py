import logging  # Выводим лог на консоль и в файл
from datetime import datetime, timedelta  # Дата и время, временной интервал
import asyncio
import json
import hashlib
import websockets
from moex_api import get_futures_series
from moex_api import get_option_expirations

_APP_ID = 'option_volatility_list'

_REFRESH_TOKEN_URL = 'https://oauth.alor.ru/refresh'
_WEBSOCKET_URL = 'wss://api.alor.ru/ws'
_EXCHANGE_MOEX = "MOEX"

_API_METHOD_QUOTES_SUBSCRIBE = "QuotesSubscribe"
_API_METHOD_INSTRUMENTS_GET_AND_SUBSCRIBE = "InstrumentsGetAndSubscribeV2"

from AlorPy import AlorPy  # Работа с Alor OpenAPI V2
exchange = 'MOEX'
asset_code = 'RTS'
URL_API = f'https://api.alor.ru'

ap_provider = AlorPy()  # Подключаемся ко всем торговым счетам
# Проверяем работу запрос/ответ
seconds_from = ap_provider.get_time()  # Время в Alor OpenAPI V2 передается в секундах, прошедших с 01.01.1970 00:00 UTC
print(f'Дата и время на сервере: {ap_provider.utc_timestamp_to_msk_datetime(seconds_from):%d.%m.%Y %H:%M:%S}')  # В AlorPy это время можно перевести в МСК для удобства восприятия)

# Две ближайшие (текущая и следующая) фьючерсные серии по базовому активу asset_code
data = get_futures_series(asset_code)
info_fut_1 = data[len(data) - 1]
info_fut_2 = data[len(data) - 2]
fut_1 = info_fut_1['secid'] # Текущий фьючерс
fut_2 = info_fut_2['secid'] # Следующий фьючерс1
symbol = fut_1

# noinspection PyShadowingNames
def log_bar(response):  # Вывод в лог полученного бара
    seconds = response['data']['time']  # Время в Alor OpenAPI V2 передается в секундах, прошедших с 01.01.1970 00:00 UTC
    dt_msk = datetime.utcfromtimestamp(seconds) if type(tf) is str else ap_provider.utc_timestamp_to_msk_datetime(seconds)  # Дневные бары и выше ставим на начало дня по UTC. Остальные - по МСК
    str_dt_msk = dt_msk.strftime('%d.%m.%Y') if type(tf) is str else dt_msk.strftime('%d.%m.%Y %H:%M:%S')  # Для дневных баров и выше показываем только дату. Для остальных - дату и время по МСК
    guid = response['guid']  # Код подписки
    subscription = ap_provider.subscriptions[guid]  # Подписка
    print(f'{subscription["exchange"]}.{subscription["code"]} ({subscription["tf"]}) - {str_dt_msk} - Open = {response["data"]["open"]}, High = {response["data"]["high"]}, Low = {response["data"]["low"]}, Close = {response["data"]["close"]}, Volume = {response["data"]["volume"]}')


# Подписываемся на бары текущего фьючерса
tf = 60  # 60 = 1 минута, 300 = 5 минут, 3600 = 1 час, 'D' = день, 'W' = неделя, 'M' = месяц, 'Y' = год
days = 3  # Кол-во последних календарных дней, за которые берем историю
seconds_from = ap_provider.msk_datetime_to_utc_timestamp(datetime.now() - timedelta(days=days))  # За последние дни. В секундах, прошедших с 01.01.1970 00:00 UTC
guid = ap_provider.bars_get_and_subscribe(exchange, symbol, tf, seconds_from, frequency=1_000_000_000)  # Подписываемся на бары, получаем guid подписки
ap_provider.on_new_bar = log_bar  # Перед подпиской перехватим ответы

# Подписываемся на котировки фьючерсов fut_1, fut_2
symbol = fut_1
# guid = ap_provider.quotes_subscribe(exchange, symbol)

# Выход
input('\nEnter - выход\n')
ap_provider.unsubscribe(guid)  # Отписываемся от получения новых баров
print(f'Отмена подписки {guid}. Закрытие WebSocket по всем правилам займет некоторое время')
ap_provider.close_web_socket()  # Перед выходом закрываем соединение с WebSocket