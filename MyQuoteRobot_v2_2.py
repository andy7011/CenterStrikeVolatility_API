import logging # Выводим лог на консоль и в файл
# logging.basicConfig(level=logging.WARNING) # уровень логгирования
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

from FinLabPy.Config import brokers, default_broker  # Все брокеры и брокер по умолчанию
from threading import Thread  # Запускаем поток подписки
from AlorPy import AlorPy  # Работа с Alor OpenAPI V2
from FinamPy import FinamPy
from FinamPy.grpc.orders_service_pb2 import Order, OrderState, OrderType, CancelOrderRequest, StopCondition  # Заявки
import FinamPy.grpc.side_pb2 as side  # Направление заявки
from FinamPy.grpc.marketdata_service_pb2 import QuoteRequest, QuoteResponse  # Последняя цена сделки
from FinLabPy.Config import brokers, default_broker  # Все брокеры и брокер по умолчанию
from QUIK_Stream_v1_7 import calculate_open_data_open_price_open_iv

import sys
import math
import numpy as np
from datetime import datetime, timezone  # Дата и время
from time import sleep  # Задержка в секундах перед выполнением операций
from scipy.stats import norm
from google.type.decimal_pb2 import Decimal
import time

# Глобальные переменные для хранения данных
global model_from_api, base_asset_list, option_list, base_ticker, expiration_dates, selected_expiration_date, dff
base_ticker = None
expiration_dates = []
sell_tickers = []
dff = None  # Добавляем глобальную переменную для хранения отфильтрованных данных
dff_filtered = None  # Добавляем глобальную переменную для хранения отфильтрованных данных
dff_filtered_type = None

# Глобальные переменные
global theor_profit_buy, theor_profit_sell, base_asset_ticker
theor_profit_buy = 0.0
theor_profit_sell = 0.0
base_asset_ticker = 0.0
CALL = 'C'
PUT = 'P'
r = 0 # Безрисковая ставка
# Список GUID для отписки
guids = []

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

# Выполняем запрос при запуске
fetch_api_data()

# Словарь новых котировок
new_quotes = {}
def _on_new_quotes(response):
    # logger.info(f'Котировка - {response["data"]}')
    # Извлекаем данные
    description = response["data"]['description']
    ask = float(response["data"]['ask']) if response["data"]['ask'] else 0.0
    ask_vol = float(response["data"]['ask_vol']) if response["data"]['ask_vol'] else 0.0
    bid = float(response["data"]['bid']) if response["data"]['bid'] else 0.0
    bid_vol = float(response["data"]['bid_vol']) if response["data"]['bid_vol'] else 0.0
    last_price = float(response["data"]['last_price']) if response["data"]['last_price'] else 0.0

    # Сохраняем в словарь по описанию тикера
    new_quotes[description] = {
        'ask': ask,
        'ask_vol': ask_vol,
        'bid': bid,
        'bid_vol': bid_vol,
        'last_price': last_price
    }
    # print(f"Котировки для {description}: ask={ask}, ask_vol={ask_vol}, bid={bid}, bid_vol={bid_vol}, last_price={last_price}")

def _on_order(order): logger.info(f'Заявка - {order}')

# Словарь сделок
trade_dict = {}
def _on_trade(trade):
    logger.info(f'Сделка - {trade}')
    # Извлекаем данные из объекта trade
    trade_id = trade.trade_id
    order_id = trade.order_id
    timestamp = trade.timestamp
    side = trade.side
    size = trade.size.value
    price = trade.price.value

    # Сохраняем данные в словарь по ключу order_id
    trade_dict[order_id] = {
        'timestamp': timestamp,
        'trade_id': trade_id,
        'order_id': order_id,
        'side': side,
        'size': size,
        'price': price
    }

def on_base_asset_change(event, app_instance):
    global base_ticker, dff
    base_ticker = app_instance.combobox_base_asset.get()
    df = pd.DataFrame.from_dict(option_list, orient='columns')
    df = df.loc[df['_volatility'] > 0]
    dff = df[(df._base_asset_ticker == base_ticker)]
    dff['_expiration_datetime'] = pd.to_datetime(dff['_expiration_datetime'], format='%a, %d %b %Y %H:%M:%S GMT')
    dff['expiration_date'] = dff['_expiration_datetime'].dt.strftime('%d.%m.%Y')
    expiration_dates = dff['expiration_date'].unique()

    # Обновляем значения в combobox_expire
    app_instance.combobox_expire['values'] = list(expiration_dates)
    if expiration_dates.size > 0:
        app_instance.combobox_expire.set(expiration_dates[0])

    return expiration_dates

def on_expiration_date_change(event, app_instance):
    global dff, dff_filtered, dff_filtered_type, sell_tickers

    selected_expiration_date = app_instance.combobox_expire.get()
    # print(f"Selected expiration date: {selected_expiration_date}")
    # print(f"dff is None: {dff is None}")

    if selected_expiration_date and dff is not None:
        # print(f"Filtering dff by date: {selected_expiration_date}")
        dff_filtered = dff[(dff.expiration_date == selected_expiration_date)]

def get_call_option_type_sell(app_instance):
    global dff_filtered, dff_filtered_type, sell_tickers
    call_option_type_sell = app_instance.option_type_sell.get()  # Получаем текущее значение переменной
    # Проверяем, что dff_filtered не None
    if dff_filtered is None:
        print("dff_filtered is None")
        return
    # Фильтруем по типу опциона (C для Call)
    if call_option_type_sell == "C":
        dff_filtered_type = dff_filtered[(dff_filtered._type == 'C')]
    else:
        dff_filtered_type = dff_filtered[(dff_filtered._type == 'P')]
    # Обновляем sell_tickers
    sell_tickers_type = dff_filtered_type['_ticker'].unique()
    app_instance.combobox_sell['values'] = list(sell_tickers_type)
    app_instance.combobox_sell.set(sell_tickers_type[0])

def selected_sell(app_instance):
    selected_sell_ticker = app_instance.combobox_sell.get()
    print(selected_sell_ticker)

def get_put_option_type_buy(app_instance):
    global dff_filtered, dff_filtered_type, sell_tickers
    put_option_type_buy = app_instance.option_type_buy.get()  # Получаем текущее значение переменной
    # Проверяем, что dff_filtered не None
    if dff_filtered is None:
        print("dff_filtered is None")
        return
    # Фильтруем по типу опциона (P для Put)
    if put_option_type_buy == "P":
        dff_filtered_type = dff_filtered[(dff_filtered._type == 'P')]
    else:
        dff_filtered_type = dff_filtered[(dff_filtered._type == 'C')]
    # Обновляем buy_tickers
    buy_tickers_type = dff_filtered_type['_ticker'].unique()
    app_instance.combobox_buy['values'] = list(buy_tickers_type)
    app_instance.combobox_buy.set(buy_tickers_type[0])

def selected_buy(app_instance):
    selected_buy_ticker = app_instance.combobox_buy.get()
    print(selected_buy_ticker)

class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("My Quote Robot")
        self.root.geometry("200x700")

        self.running = False
        self.counter = 0

        # Label My Quote Robot
        self.label = tk.Label(self.root, text="My Quote Robot v2.2")
        self.label.pack(pady=2)

        # Label base_tickers_list
        self.expected_profit_label = tk.Label(self.root, text="Выбранный базовый актив: ")
        self.expected_profit_label.pack(pady=2)

        # Выбор базового актива
        self.combobox_base_asset = ttk.Combobox(self.root, values=list(MAP.keys()))
        self.combobox_base_asset.set(list(MAP.keys())[0])  # Установить первый элемент по умолчанию
        self.combobox_base_asset.pack(pady=2)
        # Передаем self в обработчик
        self.combobox_base_asset.bind("<<ComboboxSelected>>", lambda event: on_base_asset_change(event, self))

        # Label Выбор опционной серии
        self.exp_date_label = tk.Label(self.root, text="Дата экспирации: ")
        self.exp_date_label.pack(pady=2)

        # Combobox Выбор опционной серии
        self.combobox_expire = ttk.Combobox(self.root, values=expiration_dates)
        self.combobox_expire.pack(pady=2)
        self.combobox_expire.bind("<<ComboboxSelected>>", lambda event: on_expiration_date_change(event, self))

        # Инициализация с первым значением
        on_base_asset_change(None, self)

        # Label Выбор опциона на продажу)
        self.sell_option_label = tk.Label(self.root, text="Выбор опциона на продажу")
        self.sell_option_label.pack(pady=2)

        # Radiobutton Выбор тип опциона "на продажу" (Call/Put)
        radio_frame = tk.Frame(self.root)
        radio_frame.pack(pady=2)
        self.option_type_sell = tk.StringVar(value="C")
        self.call_radio_sell = tk.Radiobutton(radio_frame, text="Call", variable=self.option_type_sell, value="C",
                                              command=lambda: get_call_option_type_sell(self))
        self.put_radio_sell = tk.Radiobutton(radio_frame, text="Put", variable=self.option_type_sell, value="P",
                                             command=lambda: get_call_option_type_sell(self))
        self.call_radio_sell.pack(side=tk.LEFT, padx=10)
        self.put_radio_sell.pack(side=tk.LEFT, padx=10)

        # Combobox Выбор опциона на продажу
        self.combobox_sell = ttk.Combobox(self.root, values=[])
        self.combobox_sell.pack(pady=2)
        self.combobox_sell.bind("<<ComboboxSelected>>", lambda event: selected_sell(self))

        # Выбор тип опциона на покупку(Call/Put)
        radio_frame = tk.Frame(self.root)
        radio_frame.pack(pady=2)
        self.option_type_buy = tk.StringVar(value="P")  # Установить Put по умолчанию
        self.call_radio_buy = tk.Radiobutton(radio_frame, text="Call", variable=self.option_type_buy, value="C",
                                              command=lambda: get_put_option_type_buy(self))
        self.put_radio_buy = tk.Radiobutton(radio_frame, text="Put", variable=self.option_type_buy, value="P",
                                             command=lambda: get_put_option_type_buy(self))
        self.call_radio_buy.pack(side=tk.LEFT, padx=10)
        self.put_radio_buy.pack(side=tk.LEFT, padx=10)

        # Выбор опциона на покупку
        self.combobox_buy = ttk.Combobox(self.root, values=[])
        # self.combobox_buy.set('')  # Установить первый
        self.combobox_buy.pack(pady=2)
        self.combobox_sell.bind("<<ComboboxSelected>>", selected_buy)

        # Метка Expected profit, %:
        self.expected_profit_label = tk.Label(self.root, text="Expected profit, % : ")
        self.expected_profit_label.pack(pady=10)

        # Спинбокс spinbox_profit Expected profit
        # self.spinbox_profit = tk.Spinbox(self.root, from_=-10, to=10, increment=0.1, format="%.1f", width=8, textvariable=2.0, command=selected_profit)
        self.spinbox_profit_var = tk.DoubleVar(value=5.0)
        self.spinbox_profit = tk.Spinbox(self.root, from_=-10, to=10, increment=0.1, format="%.1f", width=8, textvariable=self.spinbox_profit_var)
        self.spinbox_profit.pack(pady=2)

        # Label Lot count
        self.lot_count_label = tk.Label(self.root, text="Lot count: ")
        self.lot_count_label.pack(pady=2)

        # # Spinbox Переменная Lot_count
        self.lot_count_var = tk.IntVar(value=1)
        self.lot_count = tk.Spinbox(self.root, from_=1, to=100, increment=1, width=8, textvariable=self.lot_count_var)
        self.lot_count.pack(pady=2)

        # Label Basket size
        self.basket_size_label = tk.Label(self.root, text="Basket size: ")
        self.basket_size_label.pack(pady=2)

        # Spinbox Переменная Basket_size
        self.basket_size_var = tk.IntVar(value=1)
        self.basket_size = tk.Spinbox(self.root, from_=1, to=100, increment=1, width=8, textvariable=self.basket_size_var)
        self.basket_size.pack(pady=2)

        # Label Timeout
        self.timeout_label = tk.Label(self.root, text="Timeout: ")
        self.timeout_label.pack(pady=2)

        # Spinbox Переменная Timeout
        self.timeout_var = tk.IntVar(value=5)
        self.timeout = tk.Spinbox(self.root, from_=1, to=30, increment=1, width=8, textvariable=self.timeout_var)
        self.timeout.pack(pady=2)

        # Создаем кнопки
        self.start_button = tk.Button(self.root, text="Start", command=self.start_loop)
        self.start_button.pack(pady=2)

        self.stop_button = tk.Button(self.root, text="Stop", command=self.stop_loop)
        self.stop_button.pack(pady=2)

        # Button Exit
        self.exit_button = tk.Button(self.root, text="Exit", command=self.exit)
        self.exit_button.pack(pady=2)

        self.status_label = tk.Label(self.root, text="Status: Stopped")
        self.status_label.pack(pady=2)

        self.counter_label = tk.Label(self.root, text="Счётчик циклов: 0")
        self.counter_label.pack(pady=2)

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
        # Отписываемся от всех котировок
        for guid in guids:
            try:
                logger.info(f'Подписка на котировки {ap_provider.unsubscribe(guid)} отменена')
            except Exception as e:
                logger.error(f'Ошибка отписки: {e}')
        # Отмена подписок
        print(f'\n')
        print('Отмена подписок')
        fp_provider.on_order.unsubscribe(_on_order)  # Сбрасываем обработчик заявок
        fp_provider.on_trade.unsubscribe(_on_trade)  # Сбрасываем обработчик сделок
        ap_provider.on_new_quotes.unsubscribe(_on_new_quotes)  # Отменяем подписку на события
        print('Закрываем канал перед выходом')
        fp_provider.close_channel()  # Закрываем канал перед выходом
        ap_provider.close_web_socket()  # Перед выходом закрываем соединение с WebSocket
        print("Выход из программы")
        self.root.destroy()

Lot_count_step = 0
sleep_time = 5  # Время ожидания в секундах

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  # Формат сообщения
                            datefmt='%d.%m.%Y %H:%M:%S',  # Формат даты
                            level=logging.INFO,  # Уровень логируемых событий NOTSET/DEBUG/INFO/WARNING/ERROR/CRITICAL
                            handlers=[logging.FileHandler('MyControlPanel.log', encoding='utf-8'),
                                      logging.StreamHandler()])  # Лог записываем в файл и выводим на консоль
# logging.Formatter.converter = lambda *args: datetime.now(tz=fp_provider.tz_msk).timetuple()  # В логе время указываем по МСК

logger = logging.getLogger('MyControlPanel')  # Будем вести лог
fp_provider = FinamPy()  # Подключаемся ко всем торговым счетам
ap_provider = AlorPy()  # Подключаемся ко всем торговым счетам
# Подписываемся на события
ap_provider.on_new_quotes.subscribe(_on_new_quotes)
# Подписываемся на свои заявки и сделки
fp_provider.on_order.subscribe(_on_order)  # Подписываемся на заявки
fp_provider.on_trade.subscribe(_on_trade)  # Подписываемся на сделки
Thread(target=fp_provider.subscribe_orders_thread,
       name='SubscriptionOrdersThread').start()  # Создаем и запускаем поток обработки своих заявок
Thread(target=fp_provider.subscribe_trades_thread,
       name='SubscriptionTradesThread').start()  # Создаем и запускаем поток обработки своих сделок
sleep(1)  # Ждем 1 секунду

# Запуск приложения
if __name__ == "__main__":
    app = App()
    app.root.mainloop()
