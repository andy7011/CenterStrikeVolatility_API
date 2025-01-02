from datetime import datetime

from model.option import Option


class OptionRepository:

    def __init__(self):
        self._options_list = []

    def dump(self):
        return [vars(option) for option in self._options_list]

    def insert_option(self, option: Option):
        self._options_list.append(option)

    def get_all(self) -> [Option]:
        return self._options_list

    def get_by_ticker(self, ticker) -> Option:
        for option in self._options_list:
            if option.ticker == ticker:
                return option

        return None

    def get_by_strike(self, base_asset_ticker, strike) -> [Option]:
        options_by_strike = []
        for option in self._options_list:
            if option.base_asset_ticker == base_asset_ticker and option.strike == strike:
                options_by_strike.append(option)
        return options_by_strike

    def get_by_strikes(self, base_asset_ticker, strikes: [int]) -> [Option]:
        options_by_strikes = []
        for option in self._options_list:
            if option.base_asset_ticker == base_asset_ticker and option.strike in strikes:
                options_by_strikes.append(option)
        return options_by_strikes

    def get_by_tickers(self, option_tickers: [str]) -> [Option]:
        found_options = []
        for option in self._options_list:
            if option.ticker in option_tickers:
                found_options.append(option)
        return found_options

    def get_by_tickers_for_base_asset(self, base_asset_ticker: str, option_tickers: [str]) -> [Option]:
        found_options = []
        for option in self._options_list:
            if option.base_asset_ticker == base_asset_ticker and option.ticker in option_tickers:
                found_options.append(option)
        return found_options

    def get_by_tickers_and_expiration_dates_for_base_asset(self, base_asset_ticker: str, option_tickers: [str], expiration_datetimes: [datetime]):
        found_options = []
        for option in self._options_list:
            if option.base_asset_ticker == base_asset_ticker and option.ticker in option_tickers:
                is_expiration_date_in_list = False
                for expiration_datetime in expiration_datetimes:
                    if expiration_datetime.date() == option.expiration_datetime.date():
                        is_expiration_date_in_list = True

                if is_expiration_date_in_list:
                    found_options.append(option)

        return found_options
