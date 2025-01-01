from urllib.parse import urlunparse
from string import Template
from infrastructure.api_utils import get_object_from_json_endpoint
from model import option_type

_SCHEME_HTTPS = 'https'
_API_HOST = 'iss.moex.com'
_OPTIONS_LIST_URL_TEMPLATE = Template('/iss/statistics/engines/futures/markets/options/series/$ticker/securities.json')
_SECURITY_DESCRIPTION_URL_TEMPLATE = Template('/iss/securities/$ticker.json')
_OPTION_EXPIRATIONS_URL = Template('/iss/statistics/engines/futures/markets/options/assets/$ticker.json')
_OPTION_SERIES_URL = '/iss/statistics/engines/futures/markets/options/series.json'
_OPTION_BOARD_URL_TEMPLATE = Template('/iss/statistics/engines/futures/markets/options/assets/$ticker/optionboard.json')


def _make_absolute_url(relative_url: str) -> str:
    params = ''
    query = ''
    fragment = ''
    return urlunparse((_SCHEME_HTTPS, _API_HOST, relative_url, params, query, fragment))


def get_security_description(ticker: str):
    url = _make_absolute_url(_SECURITY_DESCRIPTION_URL_TEMPLATE.substitute(ticker=ticker))
    response = get_object_from_json_endpoint(url)
    return _convert_moex_data_structure_to_list_of_dicts(response['description'])


def get_option_series(asset_code: str):
    url = _make_absolute_url(_OPTION_SERIES_URL)
    response = get_object_from_json_endpoint(url, params={'asset_code': asset_code})
    return _convert_moex_data_structure_to_list_of_dicts(response['series'])


def get_option_expirations(base_asset_ticker: str):
    url = _make_absolute_url(_OPTION_EXPIRATIONS_URL.substitute(ticker=base_asset_ticker))
    response = get_object_from_json_endpoint(url)
    return _convert_moex_data_structure_to_list_of_dicts(response['expirations'])


def get_option_board(ticker: str, expiration_date: str):
    url = _make_absolute_url(_OPTION_BOARD_URL_TEMPLATE.substitute(ticker=ticker))
    response = get_object_from_json_endpoint(url, params={'expiration_date': expiration_date})
    return {
        option_type.CALL: _convert_moex_data_structure_to_list_of_dicts(response['call']),
        option_type.PUT: _convert_moex_data_structure_to_list_of_dicts(response['put']),
    }


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
