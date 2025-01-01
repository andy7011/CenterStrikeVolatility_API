from urllib.parse import urlunparse
from string import Template
from infrastructure.api_utils import get_object_from_json_endpoint
import option_type

_SCHEME_HTTPS = 'https'
_API_HOST = 'iss.moex.com'
_OPTIONS_LIST_URL_TEMPLATE = Template('/iss/statistics/engines/futures/markets/options/series/$ticker/securities.json')
_SECURITY_DESCRIPTION_URL_TEMPLATE = Template('/iss/securities/$ticker.json')
_OPTION_EXPIRATIONS_URL = Template('/iss/statistics/engines/futures/markets/options/assets/$ticker.json')
_OPTION_SERIES_URL = '/iss/statistics/engines/futures/markets/options/series.json'
_OPTION_BOARD_URL_TEMPLATE = Template('/iss/statistics/engines/futures/markets/options/assets/$ticker/optionboard.json')
_FUTURES_SERIES_URL = Template('/iss/statistics/engines/futures/markets/forts/series.json')

def _make_absolute_url(relative_url: str) -> str:
    params = ''
    query = ''
    fragment = ''
    return urlunparse((_SCHEME_HTTPS, _API_HOST, relative_url, params, query, fragment))

# Страйки могут быть нецелочисленными. Для консистентности списка страйков в
# модели и в API следует вычислять их с округлением до явно указанного количества знаков после запятой
_PRECISION_DIGITS_COUNT = 5

# Центральный страйк - наиболее близкий к цене базового актива с учётом заданного шага цены страйков
def _calculate_central_strike(base_asset_price, strike_step):
    return _round_strike(round(base_asset_price / strike_step) * strike_step)

def _round_strike(value):
    return round(value, ndigits=_PRECISION_DIGITS_COUNT)

# Получить спецификацию инструмента
def get_security_description(ticker: str):
    url = _make_absolute_url(_SECURITY_DESCRIPTION_URL_TEMPLATE.substitute(ticker=ticker))
    response = get_object_from_json_endpoint(url)
    return _convert_moex_data_structure_to_list_of_dicts(response['description'])

# Фьючерсные серии по базовому активу (напр. RTS)
def get_futures_series(asset_code: str):
    url = _make_absolute_url(_FUTURES_SERIES_URL.substitute(ticker=asset_code))
    response = get_object_from_json_endpoint(url, params={'asset_code': asset_code})
    return _convert_moex_data_structure_to_list_of_dicts(response['series'])

# Опционные серии по базовому активу (напр. RTS)
def get_option_series(asset_code: str):
    url = _make_absolute_url(_OPTION_SERIES_URL)
    response = get_object_from_json_endpoint(url, params={'asset_code': asset_code})
    return _convert_moex_data_structure_to_list_of_dicts(response['series'])

# Опционные серии (дата экспирации)
def get_option_expirations(base_asset_ticker: str):
    url = _make_absolute_url(_OPTION_EXPIRATIONS_URL.substitute(ticker=base_asset_ticker))
    response = get_object_from_json_endpoint(url)
    return _convert_moex_data_structure_to_list_of_dicts(response['expirations'])

# Доска опционов
def get_option_board(ticker: str, expiration_date: str):
    url = _make_absolute_url(_OPTION_BOARD_URL_TEMPLATE.substitute(ticker=ticker))
    response = get_object_from_json_endpoint(url, params={'expiration_date': expiration_date})
    return {
        option_type.CALL: _convert_moex_data_structure_to_list_of_dicts(response['call']),
        option_type.PUT: _convert_moex_data_structure_to_list_of_dicts(response['put']),
    }

# Получить список опционов серии
def get_option_list_by_series(option_series_ticker: str):
    url = _make_absolute_url(_OPTIONS_LIST_URL_TEMPLATE.substitute(ticker=option_series_ticker))
    response = get_object_from_json_endpoint(url)
    return _convert_moex_data_structure_to_list_of_dicts(response['securities'])


def _convert_moex_data_structure_to_list_of_dicts(moex_data_structure):
    list_of_dicts = []
    if 'columns' not in moex_data_structure or 'data' not in moex_data_structure:
        return list_of_dicts

    columns = moex_data_structure['columns']
    data = moex_data_structure['data']
    for row in data:
        row_dict = {}
        for i in range(len(columns)):
            key = columns[i]
            value = row[i]
            row_dict[key] = value
        list_of_dicts.append(row_dict)
    return list_of_dicts

if __name__ == '__main__':
    # Указываем символ для которого нужно получить данные
    ticker = 'RIH5'
    # Получить спецификацию инструмента
    data = get_security_description(ticker)
    print("\n Получить спецификацию инструмента", ticker)
    print(data)

    # Фьючерсные серии по базовому активу (напр. RTS)
    asset_code = 'RTS'
    data = get_futures_series(asset_code)
    print("\n Фьючерсные серии по базовому активу (напр. RTS):", asset_code)
    print(data)

    # Опционные серии по базовому активу (напр. RTS)
    asset_code = 'RTS'
    data = get_option_series(asset_code)
    print("\n Опционные серии по базовому активу (напр. RTS):", asset_code)
    print(data)

    # Получить даты окончания действия опционов
    data = get_option_expirations(ticker)
    print("\n Получить даты окончания действия опционов базового актива:", ticker)
    print(data)

    # Получить доску опционов
    data = get_option_board(ticker, '2025-03-20')
    print("\n Получить доску опционов базового актива", ticker, "дата окончания действия: 2025-03-20")
    print(data)

    # Получить список опционов
    option_series_ticker = 'RTS-3.25M261224XA'
    data = get_option_list_by_series(option_series_ticker)
    print("\n Получить список опционов серии", option_series_ticker)
    print(data)
