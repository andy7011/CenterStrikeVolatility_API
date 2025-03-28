import asyncio
from queue import Queue
import threading
import pandas as pd
import option_repository
from infrastructure import env_utils
from infrastructure.alor_api import AlorApi
from model.option_repository import OptionRepository
from model.option import Option
from supported_base_asset import MAP
from moex_api import get_option_series
from moex_api import get_option_list_by_series
from moex_api import get_security_description
from central_strike import get_list_of_strikes
from datetime import datetime, timedelta  # Дата и время, временной интервал
from pytz import timezone, utc  # Работаем с временнОй зоной и UTC
import time
from DashBoard_volatility import get_dash_app
from string import Template
import schedule

temp_str = 'C:\\Users\\ashadrin\\YandexDisk\\_ИИС\\Position\\$name_file'
temp_obj = Template(temp_str)

def utc_to_msk_datetime(dt, tzinfo=False):
    """Перевод времени из UTC в московское

    :param datetime dt: Время UTC
    :param bool tzinfo: Отображать временнУю зону
    :return: Московское время
    """
    dt_utc = utc.localize(dt)  # Задаем временнУю зону UTC
    # dt_msk = dt_utc.astimezone(tz_msk)  # Переводим в МСК
    dt_msk = dt_utc # Не требуется перевод в МСК
    return dt_msk if tzinfo else dt_msk.replace(tzinfo=None)

def utc_timestamp_to_msk_datetime(seconds) -> datetime:
    """Перевод кол-ва секунд, прошедших с 01.01.1970 00:00 UTC в московское время

    :param int seconds: Кол-во секунд, прошедших с 01.01.1970 00:00 UTC
    :return: Московское время без временнОй зоны
    """
    dt_utc = datetime.fromtimestamp(seconds)  # Переводим кол-во секунд, прошедших с 01.01.1970 в UTC
    return utc_to_msk_datetime(dt_utc)  # Переводим время из UTC в московское

class AlorApiTest:

    def __init__(self):
        self._async_queue = asyncio.Queue()
        alor_client_token = env_utils.get_env_or_exit('ALOR_CLIENT_TOKEN')
        self._alorApi = AlorApi(alor_client_token)
        self._df_candles = pd.DataFrame(columns=['time', 'open', 'high', 'low', 'close', 'volume', 'ticker'])
        self._data_queue = Queue()  # Очередь для обмена данными между потоками
        self._stop_event = threading.Event()  # Событие для остановки потоков

    def run(self):
        print('RUN')
        # self._test_subscribe_to_quotes()
        # self._start_dash_app()
        self._test_subscribe_to_candle()
        self._alorApi.run_async_connection(False)

    def _start_dash_app(self):
        dash_app = get_dash_app()
        dash_app.set_option_app(self)
        print('thread')
        dash_app.start_app_in_thread()


    def _test_subscribe_to_quotes(self):
        print('\n _test_subscribe_to_quotes')
        for ticker in MAP.keys():
            self._alorApi.subscribe_to_quotes(ticker, self._handle_quotes_event)
        for ticker in secid_list:
            self._alorApi.subscribe_to_quotes(ticker, self._handle_quotes_event)
            self._alorApi.subscribe_to_instrument(ticker, self._handle_option_instrument_event)

    def _test_subscribe_to_candle(self):
        print('\n _test_subscribe_to_candle')
        """Поток сбора данных с API"""
        for ticker in MAP.keys():
            self._alorApi.subscribe_to_bars(ticker, self._handle_quotes_event_bars)
            time.sleep(1)  # Пауза между запросами

    def _handle_quotes_event_bars(self, ticker, data):
        data['ticker'] = ticker
        print(data)
        current_DateTime = datetime.now()
        currentTimestamp = int(datetime.timestamp(current_DateTime))  # текущее время в секундах UTC
        time_from = currentTimestamp - (24 * 60 * 7 * 60)  # минус одна неделя в секундах UTC
        if data['time'] > time_from:
            # MSK_time = utc_timestamp_to_msk_datetime(data['time'])
            # time_from_MSK = utc_timestamp_to_msk_datetime(time_from)
            # data['time'] = MSK_time.strftime('%Y-%m-%d %H:%M:%S')
            # time_from_MSK = time_from_MSK.strftime('%Y-%m-%d %H:%M:%S')

            df_candle = pd.DataFrame.from_dict([data])
            # print('df_candle', df_candle)
            self._df_candles = self._df_candles._append(df_candle, ignore_index=True)
            self._df_candles = self._df_candles.drop(self._df_candles[self._df_candles['time'] < time_from].index)  # Удаляем строки с временем старше одной недели (time_from)
        print(len(self._df_candles))


        #
        # # # df_candle = df_candle.drop(df_candle[df_candle['time'] < time_from].index) # Удаляем строки с временем старше одной недели (time_from)
        # #
        # # # df_candle['time'] = df_candle['time'].replace(MSK_time.strftime('%Y-%m-%d %H:%M:%S'))
        # # # df_candle['time'] = pd.to_datetime(df_candle['time'])
        # # self._df_candles = self._df_candles._append(df_candle, ignore_index=True)
        # # print(self._df_candles)

    def _handle_quotes_event(self, ticker, data):
        print(data)
        # if ticker in MAP.keys():
        #     base_asset_last_price = data['last_price']
        #     last_price_futures[ticker] = base_asset_last_price
        # print(last_price_futures)

        # if ticker in secid_list:
        #     ask = data['ask']
        #     bid = data['bid']
        #     option = ticker
        #     # base_asset_last_price = last_price_futures['RIH5']
        #     # if ask:
        #     #     ask_iv = get_iv_for_option_price(base_asset_last_price, option, ask)
        #     # if bid:
        #     #     bid_iv = get_iv_for_option_price(base_asset_last_price, option, bid)
        #     # print(ticker, 'last_price:', data['last_price'], 'last_price_timestamp:', data['last_price_timestamp'], 'bid:',
        #     #     data['bid'], 'bid_iv:', bid_iv, 'ask:', data['ask'], 'ask_iv:', ask_iv)
        #
        #     # print(datetime.now(), ticker, 'last_price:', data['last_price'], 'last_price_timestamp:', data['last_price_timestamp'],
        #     #       'bid:', data['bid'], 'ask:', data['ask'])
        #     secid_list_dict = {'DateTime': datetime.now(), 'Ticker': ticker, 'LastPrice': data['last_price'],
        #                        'LastPriceTimestamp': data['last_price_timestamp'], 'Bid': data['bid'],
        #                        'Ask': data['ask']}
        #     print(secid_list_dict)

    def _handle_option_instrument_event(self, ticker, data):
        if ticker in secid_list:
            secid_list_instrument_dict = {'TheorPrice': data['theorPrice'], 'Volatility': data['volatility']}
            secid_list_dict.update(secid_list_instrument_dict)
            # print(datetime.now(), ticker, 'theorPrice:', data['theorPrice'], 'volatility:', data['volatility'])

            print(secid_list_dict)

# # Определяем список базовых активов
# asset_list = []
# futures_ticker_list = []
# for map_ticker in MAP.keys():
#     data = get_security_description(map_ticker)
#     # print(map_ticker, '\n', data[7])
#     asset_list.append(data[7]['value'])
#     futures_ticker_list.append(map_ticker)
# asset_list = list(set(asset_list))
# # print('asset_list: ', asset_list)
# print('futures_ticker_list: ', futures_ticker_list)
#
# # Определяем опционные серии по базовым активам
# option_series_by_name_series = {}
# for i in range(len(asset_list)):
#     data = get_option_series(asset_list[i])
#     # print(data)
#     for item in data:
#         if item['underlying_asset'] in MAP.keys():
#             option_series_by_name_series[item['name']] = item['underlying_asset'], item['expiration_date'], item['series_type'], item['central_strike']
# # print("\n Словарь опционная серия:Базовый актив, дата экспирации, тип серии W/M/Q, центральный страйк", '\n', option_series_by_name_series)
#
# # Формируем кортеж тикеров опционов
# last_price_futures = {}
# secid_list_dict = {}
# secid_list = []
# for m in option_series_by_name_series.keys(): # Пробегаемся по списку опционных серий
#     ticker = option_series_by_name_series[m][0] # Тикер базового актива
#     # base_asset_price = close_price_by_ticker_dict[ticker]  # Цена базового актива
#     # base_asset_price = base_asset_last_price  # Цена базового актива
#     strike_step = MAP[ticker]['strike_step']  # Шаг страйка
#     strikes_count = MAP[ticker]['max_strikes_count']  # Кол-во страйков
#     base_asset_price = option_series_by_name_series[m][3]  # Центральный страйк
#     data = get_option_list_by_series(m) # Получаем список опционов по опционной серии
#     for k in range(len(data)): # Пробегаемся по списку опционов
#         strikes = get_list_of_strikes(base_asset_price, strike_step, strikes_count) # Получаем список страйков
#         # if data[k]['strike'] in strikes: # Если страйк в списке страйков
#         if data[k]['strike'] == base_asset_price:  # Если страйк центральный
#             secid_list.append(data[k]['secid']) # Добавляем тикер в список
#     # print(ticker, m, secid_list)
#     # print('Количество опционов в серии: ', len(secid_list))
#
# print("\n Тикеры необходимых опционных серий secid_list:", '\n', secid_list)
# print('\n Количество тикеров опционов:', len(secid_list))


# time.sleep(7)
#

# def job(data):
#     print(datetime.now(), "I'm working...")
#
#
#     # print(MSK_time, ticker, data['close'], data['open'], data['high'], data['low'], data['volume'])
#
#     print(data)
#
# schedule.every(10).seconds.do(job)
#
# while True:
#     schedule.run_pending()
#     time.sleep(1)
