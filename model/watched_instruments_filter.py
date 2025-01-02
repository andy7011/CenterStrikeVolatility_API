class WatchedInstrumentsFilter:
    def __init__(self):
        self._base_asset_tickers = []
        self._option_tickers = []

    @property
    def base_asset_tickers(self):
        return self._base_asset_tickers

    @property
    def option_tickers(self):
        return self._option_tickers

    def add_base_asset_ticker(self, base_asset_ticker: str):
        if not self.has_base_asset_ticker(base_asset_ticker):
            self._base_asset_tickers.append(base_asset_ticker)

    def add_option_ticker(self, option_ticker: str):
        if not self.has_option_ticker(option_ticker):
            self._option_tickers.append(option_ticker)

    def has_base_asset_ticker(self, base_asset_ticker):
        return base_asset_ticker in self._base_asset_tickers

    def has_option_ticker(self, option_ticker):
        return option_ticker in self._option_tickers
