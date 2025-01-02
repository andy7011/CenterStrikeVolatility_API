from datetime import datetime


class Option:
    def __init__(self, ticker: str, base_asset_ticker: str, expiration_datetime: datetime, strike: float, option_type: str):
        self._ticker = ticker
        self._base_asset_ticker = base_asset_ticker
        self._expiration_datetime = expiration_datetime
        self._strike = strike
        self._type = option_type
        self._bid = None
        self._ask = None
        self._last_price = None
        self._last_price_timestamp = None
        self._volatility = None
        self._bid_iv = None
        self._ask_iv = None
        self._last_price_iv = None

    @property
    def ticker(self):
        return self._ticker

    @property
    def base_asset_ticker(self):
        return self._base_asset_ticker

    def get_time_to_maturity(self) -> float:
        difference = self._expiration_datetime - datetime.utcnow()
        seconds_in_year = 365 * 24 * 60 * 60
        return difference.total_seconds() / seconds_in_year

    @property
    def expiration_datetime(self):
        return self._expiration_datetime

    @property
    def strike(self) -> float:
        return self._strike

    @property
    def type(self):
        return self._type

    @property
    def bid(self):
        return self._bid

    @bid.setter
    def bid(self, bid):
        self._bid = bid

    @property
    def ask(self):
        return self._ask

    @ask.setter
    def ask(self, ask):
        self._ask = ask

    @property
    def last_price(self):
        return self._last_price

    @last_price.setter
    def last_price(self, last_price):
        self._last_price = last_price

    @property
    def last_price_timestamp(self):
        return self._last_price_timestamp

    @last_price_timestamp.setter
    def last_price_timestamp(self, last_price_timestamp):
        self._last_price_timestamp = last_price_timestamp

    @property
    def volatility(self):
        return self._volatility

    @volatility.setter
    def volatility(self, volatility):
        self._volatility = volatility

    @property
    def bid_iv(self):
        return self._bid_iv

    @bid_iv.setter
    def bid_iv(self, bid_iv):
        self._bid_iv = bid_iv

    @property
    def ask_iv(self):
        return self._ask_iv

    @ask_iv.setter
    def ask_iv(self, ask_iv):
        self._ask_iv = ask_iv

    @property
    def last_price_iv(self):
        return self._last_price_iv

    @last_price_iv.setter
    def last_price_iv(self, last_price_iv):
        self._last_price_iv = last_price_iv
