import threading
import requests
import datetime
import pandas as pd
from central_strike import _calculate_central_strike
from supported_base_asset import MAP

def get_object_from_json_endpoint(url, method='GET', params={}):
    response = requests.request(method, url, params=params)

    response_data = None
    if response.status_code == 200:
        response_data = response.json()
    else:
        raise Exception(f"Error: {response.status_code}")
    return response_data

def my_function():
    model_from_api = get_object_from_json_endpoint('https://option-volatility-dashboard.ru/dump_model')

    # Список базовых активов, вычисление центрального страйка
    base_asset_list = model_from_api[0]
    for asset in base_asset_list:
        ticker = asset.get('_ticker')
        last_price = asset.get('_last_price')
        strike_step = MAP[ticker]['strike_step']
        central_strike = _calculate_central_strike(last_price, strike_step) # вычисление центрального страйка
        asset.update({
            'central_strike': central_strike
        })
    print('base_asset_list:', base_asset_list) # вывод списка базовых активов

    # Список опционов
    option_list = model_from_api[1]
    current_datetime = datetime.datetime.now()
    for option in option_list:
        option['datetime'] = current_datetime
    df = pd.DataFrame.from_dict(option_list, orient='columns')
    df.set_index('datetime', inplace=True)
    df.index = df.index.strftime('%d.%m.%Y %H:%M:%S') # Reformat the date index using strftime()
    print(df.columns)
    print(df)



def run_function():
    # thread = threading.Timer(60.0, run_function) # 60 seconds = 1 minute
    thread = threading.Timer(60.0, run_function)  # 60 seconds = 1 minute
    thread.start()
    my_function()


def main():
    run_function()

if __name__ == '__main__':
    main()
