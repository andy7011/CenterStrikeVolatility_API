import schedule
import time
from typing import NoReturn
from datetime import datetime
import requests
from supported_base_asset import MAP
from central_strike import _calculate_central_strike
import csv
from string import Template

temp_str = 'C:\\Users\\ashadrin\\YandexDisk\\_ИИС\\Position\\$name_file'
temp_obj = Template(temp_str)

def get_object_from_json_endpoint(url, method='GET', params={}):
    response = requests.request(method, url, params=params)

    response_data = None
    if response.status_code == 200:
        response_data = response.json()
    else:
        raise Exception(f"Error: {response.status_code}")
    return response_data

def job() -> NoReturn:
    """Функция для выполнения задачи"""
    print("Запуск задачи в", time.strftime('%Y-%m-%d %H:%M:%S'))

    model_from_api = get_object_from_json_endpoint('https://option-volatility-dashboard.ru/dump_model')

    # Список базовых активов, вычисление и добавление в словарь центрального страйка
    base_asset_list = model_from_api[0]
    # print('base_asset_list:', base_asset_list)
    data_price = []
    with open(temp_obj.substitute(name_file='BaseAssetPriceHistory.csv'), 'a') as f:
        writer = csv.writer(f, delimiter = ";", lineterminator="\r")
        for asset in base_asset_list:
            DateTime = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            ticker = asset.get('_ticker')
            base_asset_code = asset.get('_base_asset_code')
            last_price = asset.get('_last_price')
            data_price = [DateTime, ticker, base_asset_code, last_price]
            writer.writerow(data_price)

            strike_step = MAP[ticker]['strike_step']
            central_strike = _calculate_central_strike(last_price, strike_step)  # вычисление центрального страйка
            asset.update({
                'central_strike': central_strike
            })
    # Close the file explicitly f.close()
    f.close()

    # with open(temp_obj.substitute(name_file='BaseAssetPriceHistory.csv')) as f:
    #     print(f.read())
    # # Close the file explicitly f.close()
    # f.close()

    # DateTime;ticker;base_asset_code;last_price

    # print('base_asset_list:', base_asset_list) # вывод списка базовых активов
    base_asset_ticker_list = {}
    for i in range(len(base_asset_list)):
        # print(base_asset_list[i]['_ticker'])
        base_asset_ticker_list.update({base_asset_list[i]['_ticker']: base_asset_list[i]['_base_asset_code']})
    # print(base_asset_ticker_list)




def is_scheduled_time() -> bool:
    """Проверяет, соответствует ли текущее время расписанию"""
    current_hour = datetime.now().hour
    current_minute = datetime.now().minute

    # Проверяем рабочий день (понедельник = 0, воскресенье = 6)
    weekday = datetime.now().weekday()
    if weekday >= 5:  # 5 и 6 - это суббота и воскресенье
        return False

    # Проверяем время (9:00 до 23:50)
    return (9 <= current_hour < 23) or (current_hour == 23 and current_minute <= 50)


def run_scheduler() -> NoReturn:
    """Функция для запуска планировщика"""
    while True:
        if is_scheduled_time():
            schedule.run_pending()

        time.sleep(60)  # Проверяем каждую (минуту)


if __name__ == "__main__":
    # Устанавливаем задачу на выполнение каждую минуту
    schedule.every().minute.do(job)

    # Запускаем планировщик
    run_scheduler()