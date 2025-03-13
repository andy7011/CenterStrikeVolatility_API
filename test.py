from infrastructure import env_utils
from infrastructure.alor_api import AlorApi
from supported_base_asset import MAP
from infrastructure import env_utils
from model import option_repository


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
        print(ticker, data)
        # # print(datetime.now(), ticker, 'last_price:', data['last_price'], 'last_price_timestamp:', data['last_price_timestamp'], 'bid:', data['bid'], 'ask:', data['ask'])
        # if ticker in MAP.keys():
        #     base_asset_last_price = data['last_price']
        #     last_price_futures[ticker] = base_asset_last_price
        # print(last_price_futures)

if __name__ == '__main__':
    AlorApiTest().run()