from datetime import datetime


class BaseAsset:

    def __init__(self, ticker):
        self._ticker = ticker
        self._short_name = None
        self._base_asset_code = None
        self._last_price = None
        self._expiration_datetimes = []

    @property
    def ticker(self):
        return self._ticker

    @property
    def last_price(self):
        return self._last_price

    @last_price.setter
    def last_price(self, last_price):
        self._last_price = last_price

    @property
    def expiration_datetimes(self):
        return self._expiration_datetimes

    @expiration_datetimes.setter
    def expiration_datetimes(self, expiration_datetimes):
        self._expiration_datetimes = expiration_datetimes

    def add_expiration_datetime(self, expiration_datetime: datetime):
        self._expiration_datetimes.append(expiration_datetime)

    @property
    def short_name(self):
        return self._short_name

    @short_name.setter
    def short_name(self, short_name):
        self._short_name = short_name

    @property
    def base_asset_code(self):
        return self._base_asset_code

    @base_asset_code.setter
    def base_asset_code(self, base_asset_code):
        self._base_asset_code = base_asset_code

