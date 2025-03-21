import asyncio
import json
import hashlib
import websockets
import requests
from datetime import datetime

from infrastructure.alor_api_event import AlorApiEvent
from infrastructure.api_utils import get_object_from_json_endpoint

# TODO: возможно, для случая с несколькими одновременно работающими экземплярами приложения одинаковый
#  id может стать проблемой: разные инстансы будут создавать в API подписки на события с одинаковым GUID.
#  Если это создаст проблемы, то в таком случае APP ID нужно будет брать из окружения
#  и делать уникальным для каждого инстанса.
_APP_ID = 'CentralStrikeVola_API_v1'

_REFRESH_TOKEN_URL = 'https://oauth.alor.ru/refresh'
_WEBSOCKET_URL = 'wss://api.alor.ru/ws'
_REST_API_URL = f'https://api.alor.ru'
_EXCHANGE_MOEX = "MOEX"

_API_METHOD_QUOTES_SUBSCRIBE = "QuotesSubscribe"
_API_METHOD_INSTRUMENTS_GET_AND_SUBSCRIBE = "InstrumentsGetAndSubscribeV2"
_API_METHOD_BARS_GET_AND_SUBSCRIBE = 'BarsGetAndSubscribe'


# Generate guid string for given api_method and ticker
# guid string must be deterministic because otherwise Alor API may block requests.
# This is because of it's anti-spam system
def _get_guid(api_method: str, ticker: str):
    input_string = ';'.join([_APP_ID, api_method, ticker])
    sha256_hash = hashlib.sha256()
    sha256_hash.update(input_string.encode())
    return sha256_hash.hexdigest()

def _get_authorization_token(client_token):
    params = {'token': client_token}

    response = get_object_from_json_endpoint(_REFRESH_TOKEN_URL, 'POST', params)
    authorization_token = None
    if response and 'AccessToken' in response:
        authorization_token = response['AccessToken']
    return authorization_token


class AlorApi:
    def __init__(self, client_token):
        self._async_queue = asyncio.Queue()
        self._api_events = {}
        self._auth_token = _get_authorization_token(client_token)

    def run_async_connection(self, is_debug: bool):
        asyncio.run(self._connect_to_websocket(), debug=is_debug)

    def subscribe_to_instrument(self, ticker, callback):
        self._subscribe_to_event(_API_METHOD_INSTRUMENTS_GET_AND_SUBSCRIBE, ticker, callback)

    def subscribe_to_bars(self, ticker, callback):
        self._subscribe_to_event_bars(_API_METHOD_BARS_GET_AND_SUBSCRIBE, ticker, callback)

    def subscribe_to_quotes(self, ticker: str, callback: callable):
        self._subscribe_to_event(_API_METHOD_QUOTES_SUBSCRIBE, ticker, callback)

    def _handle_data(self, guid, data):
        api_event = self._get_api_event(guid)
        ticker = api_event.ticker
        callback = api_event.callback
        callback(ticker, data)

    def get_securities_quotes(self, symbols):
        # Котировки для выбранных инструментов symbols
        url = f'{_REST_API_URL}/md/v2/securities/{symbols}/quotes'
        return self._send_rest_request(url)

    # def get_securities_history(self, symbols):
    def get_securities_history(self, exchange, symbol, tf, seconds_from=1, seconds_to=32536799999, untraded=False, format='Simple'):
        # Запрос возвращает исторические данные о состоянии рынка для выбранных биржи и финансового инструмента symbols
        url = f'{_REST_API_URL}/md/v2/history/{symbol}'
        url = "https://apidev.alor.ru/md/v2/history?symbol=RIM5&exchange=MOEX&tf=60&from=1741929520&to=1741941840"
        return self._send_rest_request(url)

    def _send_rest_request(self, url):
        payload = {}
        headers = {
            'Accept': 'application/json',
            'Authorization': f"Bearer {self._auth_token}"
        }
        response = requests.request("GET", url, headers=headers, data=payload)
        return response.json()

    def _get_api_event(self, guid: str) -> AlorApiEvent:
        return self._api_events[guid]

    def _add_api_event(self, guid: str, api_event: AlorApiEvent):
        self._api_events[guid] = api_event

    async def _connect_to_websocket(self):
        async with websockets.connect(_WEBSOCKET_URL) as websocket:
            await self._handler(websocket)

    async def _consumer(self, message):
        message_dict = json.loads(message)
        if 'data' in message_dict and 'guid' in message_dict:
            guid = message_dict['guid']
            data = message_dict['data']
            self._handle_data(guid, data)

    async def _consumer_handler(self, websocket):
        async for message in websocket:
            await self._consumer(message)

    async def _producer_handler(self, websocket):
        while True:
            message = await self._async_queue.get()
            await websocket.send(message)

    async def _handler(self, websocket):
        consumer_task = asyncio.create_task(self._consumer_handler(websocket))
        producer_task = asyncio.create_task(self._producer_handler(websocket))
        done, pending = await asyncio.wait(
            [consumer_task, producer_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()

    def _subscribe_to_event(self, api_method: str, ticker: str, callback: callable):
        guid = _get_guid(api_method, ticker)
        event = AlorApiEvent(ticker, callback)
        self._add_api_event(guid, event)
        subscribe_json = self._get_json_to_subscribe(api_method, ticker, guid)
        self._async_queue.put_nowait(subscribe_json)

    def _get_json_to_subscribe(self, api_method: str, ticker: str, guid: str):
        return json.dumps({
            "opcode": api_method,
            "code": ticker,
            "exchange": _EXCHANGE_MOEX,
            "guid": guid,
            "token": self._auth_token
        })

    def _subscribe_to_event_bars(self, api_method: str, ticker: str, callback: callable):
        guid = _get_guid(api_method, ticker)
        event = AlorApiEvent(ticker, callback)
        self._add_api_event(guid, event)
        subscribe_json = self._get_json_to_subscribe_bars(api_method, ticker, guid)
        self._async_queue.put_nowait(subscribe_json)

    def _get_json_to_subscribe_bars(self, api_method: str, ticker: str, guid: str):
        current_DateTime = datetime.now()
        currentTimestamp = int(datetime.timestamp(current_DateTime))  # текущее время в секундах UTC
        time_from = currentTimestamp - (24 * 60 * 7 * 60)  # минус одна неделя в секундах UTC
        return json.dumps({
            "opcode": api_method,
            "code": ticker,
            "tf": '60',
            "from": time_from,
            "exchange": _EXCHANGE_MOEX,
            "guid": guid,
            "token": self._auth_token
        })
