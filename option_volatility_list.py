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

