from infrastructure import env_utils
from infrastructure.alor_api import AlorApi
from supported_base_asset import MAP
from moex_api import get_option_series
from moex_api import get_option_list_by_series
from moex_api import get_security_description
from central_strike import get_list_of_strikes
from datetime import datetime, timedelta  # Дата и время, временной интервал
from pytz import timezone, utc  # Работаем с временнОй зоной и UTC
import time
import schedule
from option_repository import OptionRepository

class AlorApiTest:
    tz_msk = timezone('Europe/Moscow')  # Время UTC будем приводить к московскому времени

    def __init__(self):
        print('AlorApiTest')
        alor_client_token = env_utils.get_env_or_exit('ALOR_CLIENT_TOKEN')
        self._alorApi = AlorApi(alor_client_token)

    def run(self):
        self._test_subscribe_to_quotes()
        self._alorApi.run_async_connection(False)

    def msk_datetime_to_utc_timestamp(self, dt) -> int:
        """Перевод московского времени в кол-во секунд, прошедших с 01.01.1970 00:00 UTC

        :param datetime dt: Московское время
        :return: Кол-во секунд, прошедших с 01.01.1970 00:00 UTC
        """
        dt_msk = self.tz_msk.localize(dt)  # Заданное время ставим в зону МСК
        return int(dt_msk.timestamp())  # Переводим в кол-во секунд, прошедших с 01.01.1970 в UTC

    def utc_timestamp_to_msk_datetime(self, seconds) -> datetime:
        """Перевод кол-ва секунд, прошедших с 01.01.1970 00:00 UTC в московское время

        :param int seconds: Кол-во секунд, прошедших с 01.01.1970 00:00 UTC
        :return: Московское время без временнОй зоны
        """
        dt_utc = datetime.utcfromtimestamp(seconds)  # Переводим кол-во секунд, прошедших с 01.01.1970 в UTC
        return self.utc_to_msk_datetime(dt_utc)  # Переводим время из UTC в московское

    def msk_to_utc_datetime(self, dt, tzinfo=False) -> datetime:
        """Перевод времени из московского в UTC

        :param datetime dt: Московское время
        :param bool tzinfo: Отображать временнУю зону
        :return: Время UTC
        """
        dt_msk = self.tz_msk.localize(dt)  # Задаем временнУю зону МСК
        dt_utc = dt_msk.astimezone(utc)  # Переводим в UTC
        return dt_utc if tzinfo else dt_utc.replace(tzinfo=None)

    def utc_to_msk_datetime(self, dt, tzinfo=False) -> datetime:
        """Перевод времени из UTC в московское

        :param datetime dt: Время UTC
        :param bool tzinfo: Отображать временнУю зону
        :return: Московское время
        """
        dt_utc = utc.localize(dt)  # Задаем временнУю зону UTC
        dt_msk = dt_utc.astimezone(self.tz_msk)  # Переводим в МСК
        return dt_msk if tzinfo else dt_msk.replace(tzinfo=None)

    def _test_subscribe_to_quotes(self):
        print('\n _test_subscribe_to_quotes')
        for ticker in MAP.keys():
            self._alorApi.subscribe_to_quotes(ticker, self._handle_quotes_event)
        # for ticker in secid_list:
        #     self._alorApi.subscribe_to_quotes(ticker, self._handle_quotes_event)
        #     self._alorApi.subscribe_to_instrument(ticker, self._handle_option_instrument_event)

    def _handle_quotes_event(self, ticker, data):
        print(datetime.now(), ticker, 'last_price:', data['last_price'], 'last_price_timestamp:', data['last_price_timestamp'], 'bid:', data['bid'], 'ask:', data['ask'])
        if ticker in MAP.keys():
            base_asset_last_price = data['last_price']
            last_price_futures[ticker] = base_asset_last_price
        print(last_price_futures)

        if ticker in secid_list:
            ask = data['ask']
            bid = data['bid']
            option = ticker
            # base_asset_last_price = last_price_futures['RIH5']
            # if ask:
            #     ask_iv = get_iv_for_option_price(base_asset_last_price, option, ask)
            # if bid:
            #     bid_iv = get_iv_for_option_price(base_asset_last_price, option, bid)
            # print(ticker, 'last_price:', data['last_price'], 'last_price_timestamp:', data['last_price_timestamp'], 'bid:',
            #     data['bid'], 'bid_iv:', bid_iv, 'ask:', data['ask'], 'ask_iv:', ask_iv)

            # print(datetime.now(), ticker, 'last_price:', data['last_price'], 'last_price_timestamp:', data['last_price_timestamp'],
            #       'bid:', data['bid'], 'ask:', data['ask'])
            secid_list_dict = {'DateTime': datetime.now(), 'Ticker': ticker, 'LastPrice': data['last_price'],
                               'LastPriceTimestamp': data['last_price_timestamp'], 'Bid': data['bid'],
                               'Ask': data['ask']}
            print(secid_list_dict)

    def _handle_option_instrument_event(self, ticker, data):
        if ticker in secid_list:
            secid_list_instrument_dict = {'TheorPrice': data['theorPrice'], 'Volatility': data['volatility']}
            secid_list_dict.update(secid_list_instrument_dict)
            # print(datetime.now(), ticker, 'theorPrice:', data['theorPrice'], 'volatility:', data['volatility'])
            print(secid_list_dict)

# Определяем список базовых активов
asset_list = []
for map_ticker in MAP.keys():
    asset_list.append(map_ticker)
asset_list = list(set(asset_list))
print('asset_list: ', asset_list)


# # Определяем опционные серии по базовым активам
# option_series_by_name_series = {}
# for i in range(len(asset_list)):
#     data = get_option_series(asset_list[i])
#     print(data)
#     for item in data:
#         if item['underlying_asset'] in MAP.keys():
#             option_series_by_name_series[item['name']] = item['underlying_asset'], item['expiration_date'], item['series_type'], item['central_strike']
# print("\n Словарь опционная серия:Базовый актив, дата экспирации, тип серии W/M/Q, центральный страйк", '\n', option_series_by_name_series)

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
#         if data[k]['strike'] in strikes: # Если страйк в списке страйков
#             secid_list.append(data[k]['secid']) # Добавляем тикер в список
#     # print(ticker, m, secid_list)
#     # print('Количество опционов в серии: ', len(secid_list))
#
# print("\n Тикеры необходимых опционных серий:", '\n', secid_list)
# print('\n Количество тикеров опционов:', len(secid_list))

time.sleep(7)

def job():
    print(datetime.now(), "I'm working...")


schedule.every().minute.do(job)
while True:
    schedule.run_pending()
    time.sleep(1)