import threading
import requests
import datetime
import pandas as pd

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
    base_asset_list = model_from_api[0]
    option_list = model_from_api[1]
    current_datetime = datetime.datetime.now()
    for option in option_list:
        option['datetime'] = current_datetime
    # print(option_list[5])
    df = pd.DataFrame.from_dict(option_list, orient='columns')
    df.set_index('datetime', inplace=True)
    # print(df.columns)
    print(df)

    # print(len(option_list))

def run_function():
    thread = threading.Timer(60.0, run_function) # 60 seconds = 1 minute
    # thread = threading.Timer(60.0, run_function) # 60 seconds = 1 minute
    thread.start()
    my_function()

def main():
    run_function()

if __name__ == '__main__':
    main()
