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
import schedule
from option_repository import OptionRepository

class AlorApiTest:

    def __init__(self):
        print('AlorApiTest')
        alor_client_token = env_utils.get_env_or_exit('ALOR_CLIENT_TOKEN')
        self._alorApi = AlorApi(alor_client_token)

    def run(self):
        self._test_subscribe_to_quotes()
        self._alorApi.run_async_connection(False)

    def _test_subscribe_to_quotes(self):
        print('\n _test_subscribe_to_quotes')
        for ticker in MAP.keys():
            self._alorApi.subscribe_to_quotes(ticker, self._handle_quotes_event)
        for ticker in secid_list:
            self._alorApi.subscribe_to_quotes(ticker, self._handle_quotes_event)
            self._alorApi.subscribe_to_instrument(ticker, self._handle_option_instrument_event)

    def _handle_quotes_event(self, ticker, data):
        # print(datetime.now(), ticker, 'last_price:', data['last_price'], 'last_price_timestamp:', data['last_price_timestamp'], 'bid:', data['bid'], 'ask:', data['ask'])
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
futures_ticker_list = []
for map_ticker in MAP.keys():
    data = get_security_description(map_ticker)
    # print(map_ticker, '\n', data[7])
    asset_list.append(data[7]['value'])
    futures_ticker_list.append(map_ticker)
asset_list = list(set(asset_list))
# print('asset_list: ', asset_list)
print('futures_ticker_list: ', futures_ticker_list)

# Определяем опционные серии по базовым активам
option_series_by_name_series = {}
for i in range(len(asset_list)):
    data = get_option_series(asset_list[i])
    # print(data)
    for item in data:
        if item['underlying_asset'] in MAP.keys():
            option_series_by_name_series[item['name']] = item['underlying_asset'], item['expiration_date'], item['series_type'], item['central_strike']
# print("\n Словарь опционная серия:Базовый актив, дата экспирации, тип серии W/M/Q, центральный страйк", '\n', option_series_by_name_series)

# Формируем кортеж тикеров опционов
last_price_futures = {}
secid_list_dict = {}
secid_list = []
for m in option_series_by_name_series.keys(): # Пробегаемся по списку опционных серий
    ticker = option_series_by_name_series[m][0] # Тикер базового актива
    # base_asset_price = close_price_by_ticker_dict[ticker]  # Цена базового актива
    # base_asset_price = base_asset_last_price  # Цена базового актива
    strike_step = MAP[ticker]['strike_step']  # Шаг страйка
    strikes_count = MAP[ticker]['max_strikes_count']  # Кол-во страйков
    base_asset_price = option_series_by_name_series[m][3]  # Центральный страйк
    data = get_option_list_by_series(m) # Получаем список опционов по опционной серии
    for k in range(len(data)): # Пробегаемся по списку опционов
        strikes = get_list_of_strikes(base_asset_price, strike_step, strikes_count) # Получаем список страйков
        # if data[k]['strike'] in strikes: # Если страйк в списке страйков
        if data[k]['strike'] == base_asset_price:  # Если страйк центральный
            secid_list.append(data[k]['secid']) # Добавляем тикер в список
    # print(ticker, m, secid_list)
    # print('Количество опционов в серии: ', len(secid_list))

print("\n Тикеры необходимых опционных серий secid_list:", '\n', secid_list)
print('\n Количество тикеров опционов:', len(secid_list))


time.sleep(7)

def job():
    print(datetime.now(), "I'm working...")

    print(OptionRepository)

    # print(OptionRepository.get_option_list())

schedule.every().minute.do(job)

while True:
    schedule.run_pending()
    time.sleep(1)
