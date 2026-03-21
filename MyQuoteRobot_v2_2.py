import os.path
import tkinter as tk
from tkinter import ttk
import time
from app.supported_base_asset import MAP
import requests
import inspect
from datetime import datetime, timedelta, UTC  # Дата и время
from datetime import timedelta
import pandas as pd
import random
from pytz import utc

# Глобальные переменные для хранения данных
global model_from_api, base_asset_list, option_list, base_ticker, expiration_dates, selected_expiration_date
base_ticker = None
expiration_dates = []
sell_tickers = []

def utc_to_msk_datetime(dt, tzinfo=False):
    """Перевод времени из UTC в московское

    :param datetime dt: Время UTC
    :param bool tzinfo: Отображать временнУю зону
    :return: Московское время
    """
    dt_utc = utc.localize(dt)  # Задаем временнУю зону UTC
    # dt_msk = dt_utc.astimezone(tz_msk)  # Переводим в МСК
    dt_msk = dt_utc  # Не требуется перевод в МСК
    return dt_msk if tzinfo else dt_msk.replace(tzinfo=None)

def utc_timestamp_to_msk_datetime(seconds) -> datetime:
    """Перевод кол-ва секунд, прошедших с 01.01.1970 00:00 UTC в московское время

    :param int seconds: Кол-во секунд, прошедших с 01.01.1970 00:00 UTC
    :return: Московское время без временнОй зоны
    """
    dt_utc = datetime.fromtimestamp(seconds)  # Переводим кол-во секунд, прошедших с 01.01.1970 в UTC
    return utc_to_msk_datetime(dt_utc)  # Переводим время из UTC в московское

def get_object_from_json_endpoint_with_retry(url, method='GET', params={}, max_delay=180, timeout=10):
    """
    Модифицированная версия функции с механизмом повторных запросов при ошибке 502.
    Args:
        url (str): URL для запроса
        method (str): Метод HTTP запроса (по умолчанию 'GET')
        params (dict): Параметры запроса
        max_delay (int): Максимальная задержка между попытками в секундах
        timeout (int): Таймаут запроса в секундах

    Returns:
        dict: Данные из JSON ответа
    """
    attempt = 0
    while True:
        try:
            response = requests.request(method, url, params=params, timeout=timeout)
            response.raise_for_status()  # Вызываем исключение для всех ошибочных статусов
            # Получаем информацию о вызывающей функции
            frame = inspect.currentframe().f_back
            filename = os.path.basename(frame.f_code.co_filename)
            line_number = frame.f_lineno
            # print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Запрос к {url} успешно выполнен (строка: {line_number})")
            return response.json()

        except requests.exceptions.HTTPError as e:
            if response.status_code != 502:
                raise

            attempt += 1
            delay = min(2 ** attempt, max_delay)
            jitter = random.uniform(0, 1)
            wait_time = delay * jitter

            print(
                f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Попытка {attempt}: Получена ошибка 502. Ждём {wait_time:.1f} секунд перед повторной попыткой")
            time.sleep(wait_time)

        except requests.exceptions.Timeout:
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Timeout при запросе к {url}")
            raise

# Функция для получения данных с API при первом запуске приложения, далее каждые 10 секунд по запуску функции обратного вызова update_time(n)
def fetch_api_data():
    """Функция для получения данных с API"""
    global model_from_api, base_asset_list, option_list
    model_from_api = get_object_from_json_endpoint_with_retry('https://option-volatility-dashboard.tech/dump_model')

    # Список базовых активов
    base_asset_list = model_from_api[0]
    # print(f'base_asset_list: {base_asset_list}')

    # Список опционов
    option_list = model_from_api[1]
    # print(option_list)
    return model_from_api, option_list

def on_base_asset_change(event, app_instance):
    global base_ticker, expiration_dates
    # base_ticker = self.combobox_base_asset.get()
    # expiration()  # Обновляем список дат истечения
    base_ticker = app_instance.combobox_base_asset.get()
    expiration(app_instance)  # Обновляем список дат истечения

# Выполняем запрос при запуске
fetch_api_data()

# expiration_dates = []
def expiration(app_instance):
    global expiration_dates, selected_expiration_date
    # print(base_ticker)
    # Список опционов
    df = pd.DataFrame.from_dict(option_list, orient='columns')
    df = df.loc[df['_volatility'] > 0]
    # base_ticker = self.combobox_base_asset.get()
    dff = df[(df._base_asset_ticker == base_ticker)]  # оставим только опционы базового актива
    dff['_expiration_datetime'] = pd.to_datetime(df['_expiration_datetime'], format='%a, %d %b %Y %H:%M:%S GMT')
    dff['_expiration_datetime'].dt.date
    dff['expiration_date'] = dff['_expiration_datetime'].dt.strftime('%d.%m.%Y')
    print(dff)
    # Получаем уникальные даты истечения для выбранного базового актива
    expiration_dates = dff[dff._base_asset_ticker == base_ticker]['expiration_date'].unique()

    print(expiration_dates)
    # Обновляем значения в combobox_expire
    # self.combobox_expire['values'] = list(expiration_dates)
    # self.combobox_expire.set(expiration_dates[0])
    app_instance.combobox_expire['values'] = list(expiration_dates)
    selected_expiration_date = app_instance.combobox_expire.get()
    return list(expiration_dates)

def get_option_type_sell(app_instance):
    global selected_expiration_date, option_type_sell, dff
    print(option_type_sell)

    dff = dff[(dff.expiration_date == selected_expiration_date)]  # оставим только опционы выбранной даты экспирации
    option_type_sell = app_instance.call_radio_sell.get()

    dff = dff[(dff._type == option_type_sell)]  # оставим только опционы выбранного типа
    # Список sell_tickers
    sell_tickers = dff['_ticker'].unique()
    print(sell_tickers)






class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("My Quote Robot")
        self.root.geometry("200x900")

        self.running = False
        self.counter = 0

        # Label My Quote Robot
        self.label = tk.Label(self.root, text="My Quote Robot v2.2")
        self.label.pack(pady=5)

        # Label base_tickers_list
        self.expected_profit_label = tk.Label(self.root, text="Выбранный базовый актив: ")
        self.expected_profit_label.pack(pady=10)

        # Выбор базового актива
        self.combobox_base_asset = ttk.Combobox(self.root, values=list(MAP.keys()))
        self.combobox_base_asset.set(list(MAP.keys())[0])  # Установить первый элемент по умолчанию
        self.combobox_base_asset.pack(pady=5)
        # Передаем self в обработчик
        self.combobox_base_asset.bind("<<ComboboxSelected>>", lambda event: on_base_asset_change(event, self))

        # Label Выбор опционной серии
        self.exp_date_label = tk.Label(self.root, text="Дата экспирации: ")
        self.exp_date_label.pack(pady=5)

        # Combobox Выбор опционной серии
        self.combobox_expire = ttk.Combobox(self.root, values=expiration_dates)
        # self.combobox_expire.set(expiration_dates[0]) # Установить первый
        # self.combobox_expire.set('')  # Установить первый
        self.combobox_expire.pack(pady=5)
        # self.combobox_expire.bind("<<ComboboxSelected>>", expiration)

        # Label Выбор опциона на продажу)
        self.sell_option_label = tk.Label(self.root, text="Выбор опциона на продажу")
        self.sell_option_label.pack(pady=5)

        # Radiobutton Выбор тип опциона на продажу (Call/Put)
        radio_frame = tk.Frame(self.root)
        radio_frame.pack(pady=5)
        self.option_type_sell = tk.StringVar(value="Call")
        self.call_radio_sell = tk.Radiobutton(radio_frame, text="Call", variable=self.option_type_sell, value="Call")
        self.put_radio_sell = tk.Radiobutton(radio_frame, text="Put", variable=self.option_type_sell, value="Put")
        self.call_radio_sell.pack(side=tk.LEFT, padx=10)
        self.put_radio_sell.pack(side=tk.LEFT, padx=10)
        self.call_radio_sell.bind("<<RadiobuttonSelected>>", get_option_type_sell)

        # Combobox Выбор опциона на продажу
        # sell_tickers = ["AAPL", "GOOG", "MSFT"]
        self.combobox_sell = ttk.Combobox(self.root, values=sell_tickers)
        # self.combobox_sell.set('')  # Установить первый
        self.combobox_sell.pack(pady=5)
        # self.combobox_sell.bind("<<ComboboxSelected>>", selected_sell)

        # Выбор тип опциона на покупку(Call/Put)
        radio_frame = tk.Frame(self.root)
        radio_frame.pack(pady=5)
        self.option_type_buy = tk.StringVar(value="Put")  # Установить Put по умолчанию
        self.call_radio_buy = tk.Radiobutton(radio_frame, text="Call", variable=self.option_type_buy, value="Call")
        self.put_radio_buy = tk.Radiobutton(radio_frame, text="Put", variable=self.option_type_buy, value="Put")
        self.call_radio_buy.pack(side=tk.LEFT, padx=10)
        self.put_radio_buy.pack(side=tk.LEFT, padx=10)

        # Выбор опциона на покупку
        buy_tickers = ["AAPL", "GOOG", "MSFT"]
        self.combobox_buy = ttk.Combobox(self.root, values=buy_tickers)
        self.combobox_buy.set('')  # Установить первый
        self.combobox_buy.pack(pady=5)
        # self.combobox_sell.bind("<<ComboboxSelected>>", selected_buy)

        # Метка Expected profit, %:
        self.expected_profit_label = tk.Label(self.root, text="Expected profit, % : ")
        self.expected_profit_label.pack(pady=10)

        # Спинбокс spinbox_profit Expected profit
        # self.spinbox_profit = tk.Spinbox(self.root, from_=-10, to=10, increment=0.1, format="%.1f", width=8, textvariable=2.0, command=selected_profit)
        self.spinbox_profit_var = tk.DoubleVar(value=5.0)
        self.spinbox_profit = tk.Spinbox(self.root, from_=-10, to=10, increment=0.1, format="%.1f", width=8, textvariable=self.spinbox_profit_var)
        self.spinbox_profit.pack(pady=5)

        # Label Lot count
        self.lot_count_label = tk.Label(self.root, text="Lot count: ")
        self.lot_count_label.pack(pady=5)

        # # Spinbox Переменная Lot_count
        self.lot_count_var = tk.IntVar(value=1)
        self.lot_count = tk.Spinbox(self.root, from_=1, to=100, increment=1, width=8, textvariable=self.lot_count_var)
        self.lot_count.pack(pady=5)

        # Label Basket size
        self.basket_size_label = tk.Label(self.root, text="Basket size: ")
        self.basket_size_label.pack(pady=5)

        # Spinbox Переменная Basket_size
        self.basket_size_var = tk.IntVar(value=1)
        self.basket_size = tk.Spinbox(self.root, from_=1, to=100, increment=1, width=8, textvariable=self.basket_size_var)
        self.basket_size.pack(pady=5)

        # Label Timeout
        self.timeout_label = tk.Label(self.root, text="Timeout: ")
        self.timeout_label.pack(pady=5)

        # Spinbox Переменная Timeout
        self.timeout_var = tk.IntVar(value=1)
        self.timeout = tk.Spinbox(self.root, from_=1, to=30, increment=1, width=8, textvariable=self.timeout_var)
        self.timeout.pack(pady=5)

        # Создаем кнопки
        self.start_button = tk.Button(self.root, text="Start", command=self.start_loop)
        self.start_button.pack(pady=10)

        self.stop_button = tk.Button(self.root, text="Stop", command=self.stop_loop)
        self.stop_button.pack(pady=10)

        # Button Exit
        self.exit_button = tk.Button(self.root, text="Exit", command=self.exit)
        self.exit_button.pack(pady=10)

        self.status_label = tk.Label(self.root, text="Status: Stopped")
        self.status_label.pack(pady=10)

        self.counter_label = tk.Label(self.root, text="Счётчик циклов: 0")
        self.counter_label.pack(pady=10)

    def loop_function(self):
        """Функция, которая будет выполняться в цикле"""
        if self.running:
            self.counter += 1
            self.counter_label.config(text=f"Счётчик циклов: {self.counter}")
            self.status_label.config(text="Status: Running")

            # Планируем следующий вызов через 100 мс
            self.root.after(1000, self.loop_function)

    def start_loop(self):
        """Запуск цикла"""
        if not self.running:
            self.running = True
            self.loop_function()  # Запускаем цикл

    def stop_loop(self):
        """Остановка цикла"""
        self.running = False
        self.status_label.config(text="Status: Stopped")

    def exit(self):
        """Выход из приложения"""
        self.root.destroy()


# Запуск приложения
if __name__ == "__main__":
    app = App()
    app.root.mainloop()
