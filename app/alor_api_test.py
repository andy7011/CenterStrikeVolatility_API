from infrastructure import env_utils
from infrastructure.alor_api import AlorApi


class AlorApiTest:

    def __init__(self):
        print('AlorApiTest')
        alor_client_token = env_utils.get_env_or_exit('ALOR_CLIENT_TOKEN')
        self._alorApi = AlorApi(alor_client_token)

    def run(self):
        self._test_subscribe_to_quotes()
        self._alorApi.run_async_connection(False)

    def _test_subscribe_to_quotes(self):
        print('_test_subscribe_to_quotes')
        self._alorApi.subscribe_to_quotes('RIH5', self._handle_quotes_event)
        self._alorApi.subscribe_to_quotes('RI90000BA5E', self._handle_quotes_event)
        self._alorApi.subscribe_to_instrument('RI90000BA5E', self._handle_option_instrument_event)

    def _handle_quotes_event(self, ticker, data):
        print(ticker, data)

    def _handle_option_instrument_event(self, ticker, data):
        print(ticker, data)