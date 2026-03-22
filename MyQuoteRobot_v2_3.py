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
global model_from_api, base_asset_list, option_list, expiration_dates, selected_expiration_date, dff
expiration_dates = []
sell_tickers = []
dff = None  # Добавляем глобальную переменную для хранения данных
dff_filtered = None  # Добавляем глобальную переменную для хранения отфильтрованных данных по дате экспирации
dff_filtered_type = None # Добавляем глобальную переменную для хранения отфильтрованных данных по типу опциона call/put

# Глобальные переменные
global dataname_sell, dataname_buy, base_asset_ticker, quoter_side, expected_profit, lot_count, basket_size, timeout
dataname_sell = ''
dataname_buy = ''
base_asset_ticker = ''
quoter_side = ''
expected_profit = 5.0  # Значение по умолчанию
lot_count = 1
basket_size = 1
timeout = 5
global theor_profit_buy, theor_profit_sell
theor_profit_buy = 0.0
theor_profit_sell = 0.0

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

# Получаем данные по базовому активу, подписываемся на котировки
def on_base_asset_change(event, app_instance):
    global base_asset_ticker, dff
    base_asset_ticker = app_instance.combobox_base_asset.get()
    dataname_base_asset_ticker = 'SPBFUT.' + base_asset_ticker
    print(f'dataname_base_asset_ticker {dataname_base_asset_ticker}')
    print('Получаем данные по базовому активу, подписываемся на котировки')
    alor_board, symbol = ap_provider.dataname_to_alor_board_symbol(
        base_asset_ticker)  # Код режима торгов Алора и код и тикер
    exchange = ap_provider.get_exchange(alor_board, symbol)  # Код биржи
    guid = ap_provider.quotes_subscribe(exchange, symbol)  # Получаем код подписки
    guids.append(guid)
    logger.info(f'Подписка на котировки {guid} тикера {base_asset_ticker} создана')
    sleep(1)

    df = pd.DataFrame.from_dict(option_list, orient='columns')
    df = df.loc[df['_volatility'] > 0]
    dff = df[(df._base_asset_ticker == base_asset_ticker)]
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
    global dataname_sell
    selected_sell_ticker = app_instance.combobox_sell.get()
    dataname_sell = "SPBOPT." + selected_sell_ticker
    # print(selected_sell_ticker, dataname_sell)
    option_data_sell = get_opion_data_alor(dataname_sell)

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
    global dataname_buy
    selected_buy_ticker = app_instance.combobox_buy.get()
    dataname_buy = "SPBOPT." + selected_buy_ticker
    # print(selected_buy_ticker, dataname_buy)
    option_data_buy = get_opion_data_alor(dataname_buy)

def get_quoter_side(app_instance):
    global quoter_side
    quoter_side = app_instance.quoter_side.get()
    print(f"Котировщик SELL/BUY: {quoter_side}")

def selected_profit(app_instance):
    global expected_profit
    expected_profit = float(app_instance.spinbox_profit.get())
    print(f"Выбранная прибыль: {expected_profit}")

def selected_lot_count(app_instance):
    global lot_count
    lot_count = int(app_instance.spinbox_lot_count_var.get())
    print(f"Выбранное количество лотов: {lot_count}")

def selected_basket_size(app_instance):
    global basket_size
    basket_size = app_instance.spinbox_basket_size.get()
    print(f"Выбранный basket size: {basket_size}")

def selected_timeout(app_instance):
    global timeout
    timeout = app_instance.spinbox_timeout.get()
    print(f"Выбранный timeout: {timeout}")

# Получаем данные по опционам, сохраняем в словарь
options_data = {}
def get_opion_data_alor(dataname):
    alor_board, symbol = ap_provider.dataname_to_alor_board_symbol(dataname)  # Код режима торгов Алора и код и тикер
    exchange = ap_provider.get_exchange(alor_board, symbol)  # Код биржи
    si = ap_provider.get_symbol_info(exchange, symbol)  # Получаем информацию о тикере
    # print(si)
    # Создаем словарь для опциона
    options_data[dataname] = {
        'ticker': si['shortname'],
        'theorPrice': si['theorPrice'],
        'volatility': float(si['volatility']),
        'strikePrice': float(si['strikePrice']),
        'endExpiration': si['endExpiration'],
        'base_asset_ticker': si['underlyingSymbol'],
        'optionSide': si['optionSide'],
        'lot_size': si['lotsize'],
        'minstep': si['minstep'],
        'decimals': si['decimals']
    }
    # print(f'options_data {options_data}')
    guid = ap_provider.quotes_subscribe(exchange, symbol)  # Получаем код подписки
    guids.append(guid)
    logger.info(f'Подписка на котировки {guid} тикера {dataname} создана')
    return options_data

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

# Сбор данных по опциону и БА для расчета цены опциона
def get_option_data_for_calc_price(dataname):
    base_asset_ticker = options_data[dataname]['base_asset_ticker']
    S = float(new_quotes[base_asset_ticker]['last_price'])
    K = float(options_data[dataname]['strikePrice'])
    expiration_datetime = options_data[dataname]['endExpiration']
    expiration_dt = datetime.fromisoformat(expiration_datetime.replace('Z', '+00:00'))
    T_razn = (expiration_dt - datetime.today()).days
    T = float((T_razn + 1.151) / 365)
    opt_type = CALL if options_data[dataname]['optionSide'] == 'Call' else PUT
    # print(f'S: {S}, K: {K}, T: {T}, opt_type: {opt_type}')
    return S, K, T, opt_type

# Вычисление стоимости опциона по формуле Black-Scholes
def option_price(S, sigma, K, T, r: float, opt_type):
    d1 = (math.log(S / K) + (r + .5 * sigma ** 2) * T) / (sigma * T ** .5)
    d2 = d1 - sigma * T ** 0.5
    price = 0
    if opt_type == CALL:
        n1 = norm.cdf(d1)
        n2 = norm.cdf(d2)
        DF = math.exp(-r * T)
        price = S * n1 - K * DF * n2
    elif opt_type == PUT:
        n1 = norm.cdf(-d1)
        n2 = norm.cdf(-d2)
        DF = math.exp(-r * T)
        price = K * DF * n2 - S * n1
    return price

# Сбор данных опциона CALL для расчета IV
def option_data_for_IV_calculation_call(dataname, price_call):
    # S: последняя цена БА из обновляемого словаря new_quotes
    # K: strike price
    # T: time to maturity
    # C: Call value
    # r: interest rate
    # sigma: volatility of underlying asset
    base_asset_ticker = options_data[dataname]['base_asset_ticker']
    S = float(new_quotes[base_asset_ticker]['last_price'])
    K = float(options_data[dataname]['strikePrice'])
    expiration_datetime = options_data[dataname]['endExpiration']
    expiration_dt = datetime.fromisoformat(expiration_datetime.replace('Z', '+00:00'))
    T_razn = (expiration_dt - datetime.today()).days
    T = float((T_razn + 1.151) / 365)
    C = price_call
    sigma = options_data[dataname]['volatility'] / 100
    return S, K, T, C, sigma

# Сбор данных опциона PUT для расчета IV
def option_data_for_IV_calculation_put(dataname, price_put):
    # S: последняя цена БА из обновляемого словаря new_quotes
    # K: strike price
    # T: time to maturity
    # P: Put value
    # r: interest rate
    # sigma: volatility of underlying asset
    base_asset_ticker = options_data[dataname]['base_asset_ticker']
    S = float(new_quotes[base_asset_ticker]['last_price'])
    K = float(options_data[dataname]['strikePrice'])
    expiration_datetime = options_data[dataname]['endExpiration']
    expiration_dt = datetime.fromisoformat(expiration_datetime.replace('Z', '+00:00'))
    T_razn = (expiration_dt - datetime.today()).days
    T = float((T_razn + 1.151) / 365)
    P = price_put
    sigma = options_data[dataname]['volatility'] / 100
    return S, K, T, P, sigma

# Расчет IV Метод Ньютона для опциона CALL
def newton_vol_call(S, K, T, C, r, sigma):
    # S: spot price
    # K: strike price
    # T: time to maturity
    # C: Call value
    # r: interest rate
    # sigma: volatility of underlying asset

    tolerance = 0.000001
    max_iterations = 100
    x0 = sigma
    xnew = x0
    xold = x0 - 1
    iteration = 0

    while abs(xnew - xold) > tolerance and iteration < max_iterations:
        xold = xnew
        d1 = (np.log(S / K) + (r - 0.5 * xnew ** 2) * T) / (xnew * np.sqrt(T))
        d2 = d1 - xnew * np.sqrt(T)
        fx = S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2) - C
        vega = S * np.sqrt(T) * np.exp(-0.5 * d1 ** 2) / np.sqrt(2 * np.pi)
        if abs(vega) < 1e-10:  # Избегаем деления на ноль
            break
        xnew = xnew - fx / vega
        iteration += 1
    return abs(xnew)

# Расчет IV Метод Ньютона для опциона PUT
def newton_vol_put(S, K, T, P, r, sigma):
    # S: spot price
    # K: strike price
    # T: time to maturity
    # P: Put value
    # r: interest rate
    # sigma: volatility of underlying asset

    tolerance = 0.000001
    max_iterations = 100
    x0 = sigma
    xnew = x0
    xold = x0 - 1
    iteration = 0
    while abs(xnew - xold) > tolerance and iteration < max_iterations:
        xold = xnew
        d1 = (np.log(S / K) + (r - 0.5 * xnew ** 2) * T) / (xnew * np.sqrt(T))
        d2 = d1 - xnew * np.sqrt(T)
        fx = K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1) - P
        vega = S * np.sqrt(T) * np.exp(-0.5 * d1 ** 2) / np.sqrt(2 * np.pi)
        if abs(vega) < 1e-10:  # Избегаем деления на ноль
            break
        xnew = xnew - fx / vega
        iteration += 1
    return abs(xnew)

class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("My Quote Robot")
        self.root.geometry("200x700")

        self.running = False
        self.counter = 0

        # Label My Quote Robot
        self.label = tk.Label(self.root, text="My Quote Robot v2.2")
        self.label.pack(pady=1)

        # Label base_tickers_list
        self.base_asset_ticker_label = tk.Label(self.root, text="Базовый актив: ")
        self.base_asset_ticker_label.pack(pady=1)

        # Выбор базового актива
        self.combobox_base_asset = ttk.Combobox(self.root, values=list(MAP.keys()))
        self.combobox_base_asset.set(list(MAP.keys())[0])  # Установить первый элемент по умолчанию
        self.combobox_base_asset.pack(pady=1)
        # Передаем self в обработчик
        self.combobox_base_asset.bind("<<ComboboxSelected>>", lambda event: on_base_asset_change(event, self))

        # Label Выбор опционной серии
        self.exp_date_label = tk.Label(self.root, text="Дата экспирации: ")
        self.exp_date_label.pack(pady=1)

        # Combobox Выбор опционной серии
        self.combobox_expire = ttk.Combobox(self.root, values=expiration_dates)
        self.combobox_expire.pack(pady=1)
        self.combobox_expire.bind("<<ComboboxSelected>>", lambda event: on_expiration_date_change(event, self))

        # Инициализация с первым значением
        on_base_asset_change(None, self)

        # Label Выбор опциона на продажу
        self.sell_option_label = tk.Label(self.root, text="Опцион на продажу:")
        self.sell_option_label.pack(pady=1)

        # Radiobutton Выбор тип опциона "на продажу" (Call/Put)
        radio_frame = tk.Frame(self.root)
        radio_frame.pack(pady=1)
        self.option_type_sell = tk.StringVar(value="C")
        self.call_radio_sell = tk.Radiobutton(radio_frame, text="Call", variable=self.option_type_sell, value="C",
                                              command=lambda: get_call_option_type_sell(self))
        self.put_radio_sell = tk.Radiobutton(radio_frame, text="Put", variable=self.option_type_sell, value="P",
                                             command=lambda: get_call_option_type_sell(self))
        self.call_radio_sell.pack(side=tk.LEFT, padx=10)
        self.put_radio_sell.pack(side=tk.LEFT, padx=10)

        # Combobox Выбор опциона на продажу
        self.combobox_sell = ttk.Combobox(self.root, values=[])
        self.combobox_sell.pack(pady=1)
        self.combobox_sell.bind("<<ComboboxSelected>>", lambda event: selected_sell(self))

        # Label Выбор опциона на покупку
        self.buy_option_label = tk.Label(self.root, text="Опцион на покупку:")
        self.buy_option_label.pack(pady=1)

        # Выбор тип опциона на покупку(Call/Put)
        radio_frame = tk.Frame(self.root)
        radio_frame.pack(pady=1)
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
        self.combobox_buy.pack(pady=1)
        self.combobox_buy.bind('<<ComboboxSelected>>', lambda event: selected_buy(self))

        # Label Котировщик (SELL - котируем опцион на продажу, BUY - котируем опцион на покупку)

        self.quoter_label = tk.Label(self.root, text="Котировщик:")
        self.quoter_label.pack(pady=1)

        # Выбор SELL - котируем опцион на продажу, BUY - котируем опцион на покупку
        # Сделка по второй ноге происходит по рынку
        radio_frame = tk.Frame(self.root)
        radio_frame.pack(pady=1)
        # self.SELL_radio = tk.StringVar(value="SELL")  # Установить SELL по умолчанию
        self.quoter_side = tk.StringVar(value="BUY")  # или "SELL", по умолчанию "BUY"
        self.SELL_radio = tk.Radiobutton(radio_frame, text="SELL", variable=self.quoter_side, value="SELL",
                                             command=lambda: get_quoter_side(self))
        self.BUY_radio = tk.Radiobutton(radio_frame, text="BUY", variable=self.quoter_side, value="BUY",
                                            command=lambda: get_quoter_side(self))
        self.SELL_radio.pack(side=tk.LEFT, padx=10)
        self.BUY_radio.pack(side=tk.LEFT, padx=10)

        # Метка Expected profit, %:
        self.expected_profit_label = tk.Label(self.root, text="Expected profit, % : ")
        self.expected_profit_label.pack(pady=1)

        # Спинбокс spinbox_profit Expected profit
        self.spinbox_profit_var = tk.DoubleVar(value=5.0)
        self.spinbox_profit = tk.Spinbox(self.root, from_=-10, to=10, increment=0.1, format="%.1f", width=8, textvariable=self.spinbox_profit_var, command=lambda: selected_profit(self))
        self.spinbox_profit.pack(pady=1)

        # Label Lot count
        self.lot_count_label = tk.Label(self.root, text="Lot count: ")
        self.lot_count_label.pack(pady=1)

        # # Spinbox Переменная Lot_count
        # self.spinbox_lot_count_var = tk.IntVar(value=1)
        self.spinbox_lot_count_var = tk.StringVar(value="1")  # Используем StringVar
        self.spinbox_lot_count = tk.Spinbox(self.root, from_=1, to=100, increment=1, width=8, textvariable=self.spinbox_lot_count_var, command=lambda: selected_lot_count(self))
        self.spinbox_lot_count.pack(pady=1)

        # Label Basket size
        self.basket_size_label = tk.Label(self.root, text="Basket size: ")
        self.basket_size_label.pack(pady=1)

        # Spinbox Переменная Basket_size
        self.spinbox_basket_size_var = tk.IntVar(value=1)
        self.spinbox_basket_size = tk.Spinbox(self.root, from_=1, to=100, increment=1, width=8, textvariable=self.spinbox_basket_size_var, command=lambda: selected_basket_size(self))
        self.spinbox_basket_size.pack(pady=1)

        # Label Timeout
        self.timeout_label = tk.Label(self.root, text="Timeout: ")
        self.timeout_label.pack(pady=1)

        # Spinbox Переменная Timeout
        self.spinbox_timeout_var = tk.IntVar(value=5)
        self.spinbox_timeout = tk.Spinbox(self.root, from_=1, to=30, increment=1, width=8, textvariable=self.spinbox_timeout_var, command=lambda: selected_timeout(self))
        self.spinbox_timeout.pack(pady=1)

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
        global options_data
        """Функция, которая будет выполняться в цикле"""
        if self.running:
            self.counter += 1
            self.counter_label.config(text=f"Счётчик циклов: {self.counter}")
            self.status_label.config(text="Status: Running")

            # print(f'dataname_sell: {dataname_sell}')
            account_id = fp_provider.account_ids[0]  # Торговый счет, где будут выставляться заявки
            quantity_sell = options_data[dataname_sell]['lot_size']  # Количество в шт
            step_price = int(float(options_data[dataname_sell]['minstep']))  # Минимальный шаг цены
            theoretical_price_sell_ = options_data[dataname_sell]['theorPrice']
            theor_iv_sell = options_data[dataname_sell]['volatility']
            decimals = options_data[dataname_sell]['decimals']
            profit_iv_sell = theor_iv_sell + expected_profit
            # Далее вычисляем profit_price_sell из profit_iv_sell по формуле Блэка-Шоулза
            S, K, T, opt_type = get_option_data_for_calc_price(dataname_sell)  # Получаем данные опциона dataname_sell
            # print(f'S: {S}, K: {K}, T: {T}, opt_type: {opt_type}')
            profit_price_sell = option_price(S, profit_iv_sell / 100, K, T, r, opt_type=opt_type)
            limit_price_sell = int(round((profit_price_sell // step_price) * step_price, decimals))
            theoretical_price_sell = int(round((theoretical_price_sell_ // step_price) * step_price, decimals))
            # Получаем ask, bid из потока котировок по подписке из обновляемого словаря new_quotes
            ticker = options_data[dataname_sell]['ticker']
            ask_sell = int(round(new_quotes[ticker]['ask'], decimals))
            ask_sell_vol = int(round(new_quotes[ticker]['ask_vol'], decimals))
            bid_sell = int(round(new_quotes[ticker]['bid'], decimals))
            bid_sell_vol = int(round(new_quotes[ticker]['bid_vol'], decimals))
            last_iv_sell = int(round(new_quotes[ticker]['last_price'], decimals))
            # print(f'ask_sell: {ask_sell}, bid_sell: {bid_sell} ask_sell_vol: {ask_sell_vol}, bid_sell_vol: {bid_sell_vol}')
            if opt_type == 'C':
                sigma = options_data[dataname_sell]['volatility'] / 100
                ask_iv_sell = newton_vol_call(S, K, T, ask_sell, r, sigma) * 100
                bid_iv_sell = newton_vol_call(S, K, T, bid_sell, r, sigma) * 100
                last_iv_sell = newton_vol_call(S, K, T, last_iv_sell, r, sigma) * 100
            else:
                sigma = options_data[dataname_sell]['volatility'] / 100
                ask_iv_sell = newton_vol_put(S, K, T, ask_sell, r, sigma) * 100
                bid_iv_sell = newton_vol_put(S, K, T, bid_sell, r, sigma) * 100
                last_iv_sell = newton_vol_put(S, K, T, last_iv_sell, r, sigma) * 100



            # print(f'dataname_buy: {dataname_buy}')
            account_id = fp_provider.account_ids[0]  # Торговый счет, где будут выставляться заявки
            quantity_buy = options_data[dataname_buy]['lot_size']  # Количество в шт
            theoretical_price_buy_ = options_data[dataname_buy]['theorPrice']
            theor_iv_buy = options_data[dataname_buy]['volatility']
            profit_iv_buy = theor_iv_buy - expected_profit
            # Далее вычисляем profit_price_buy из profit_iv_buy по формуле Блэка-Шоулза
            S, K, T, opt_type = get_option_data_for_calc_price(dataname_buy)  # Получаем данные опциона dataname_sell
            # print(f'S: {S}, K: {K}, T: {T}, opt_type: {opt_type}')
            profit_price_buy = option_price(S, profit_iv_buy / 100, K, T, r, opt_type=opt_type)
            limit_price_buy = int(round((profit_price_buy // step_price) * step_price, decimals))
            theoretical_price_buy = int(round((theoretical_price_buy_ // step_price) * step_price, decimals))
            # Получаем ask, bid из потока котировок по подписке из обновляемого словаря new_quotes
            ask_buy = int(round(new_quotes[ticker]['ask'], decimals))
            ask_buy_vol = int(round(new_quotes[ticker]['ask_vol'], decimals))
            bid_buy = int(round(new_quotes[ticker]['bid'], decimals))
            bid_buy_vol = int(round(new_quotes[ticker]['bid_vol'], decimals))
            last_price_buy = int(round(new_quotes[ticker]['last_price'], decimals))
            # print(f'Котировки ask_buy: {ask_buy} ask_buy_vol: {ask_buy_vol} bid_buy: {bid_buy} bid_buy_vol: {bid_buy_vol}')
            if opt_type == 'C':
                sigma = options_data[dataname_buy]['volatility'] / 100
                ask_iv_buy = newton_vol_call(S, K, T, ask_buy, r, sigma) * 100
                bid_iv_buy = newton_vol_call(S, K, T, bid_buy, r, sigma) * 100
                last_iv_buy = newton_vol_call(S, K, T, last_price_buy, r, sigma) * 100
            else:
                sigma = options_data[dataname_buy]['volatility'] / 100
                ask_iv_buy = newton_vol_put(S, K, T, ask_buy, r, sigma) * 100
                bid_iv_buy = newton_vol_put(S, K, T, bid_buy, r, sigma) * 100
                last_iv_buy = newton_vol_put(S, K, T, last_price_buy, r, sigma) * 100
            # print(f'Волатильность ask_iv_buy: {round(ask_iv_buy, 2)} bid_iv_buy: {round(bid_iv_buy, 2)}')


            print('\n')
            print(f'Разбежка/наклон: Theor: {round(theor_iv_sell - theor_iv_buy, 2)} '
                  f'                Last: {round(last_iv_sell - last_iv_buy, 2)} '
                  f'                Market: {round(bid_iv_sell - ask_iv_buy, 2)}')

            if quoter_side == 'BUY':
                print(f'{quoter_side} Котируем покупку, продажа - по рынку!')
                print(f'Вариант 1 "Котируем покупку"')
                print(f'Расчёт целевой цены купли/продажи target_price (Вариант 1 "Котируем покупку")')
                # Сначала котируем покупку опциона dataname_buy по цене target_price_buy,
                # При свершении покупки сразу продаём опцион dataname_sell по цене target_price_sell
                # Для случая, когда опцион на продажу dataname_sell (купленный ранее) имеет профит больше, чем опцион на покупку dataname_buy
                target_iv_sell = bid_iv_sell  # Целевая IV для мгновенной продажи
                print(f'1. Целевая IV для мгновенной продажи: {round(target_iv_sell, 2)}')
                target_price_sell = bid_sell  # Целевая ЦЕНА для мгновенной продажи
                print(f'2. Целевая ЦЕНА для мгновенной продажи: {round(target_price_sell, 2)}')
                # target_profit_sell = bid_iv_sell - open_iv_sell  # Целевая прибыль для мгновенной продажи
                # print(f'3. Целевая прибыль для мгновенной продажи: {round(target_profit_sell, 2)}')
                target_profit_buy = bid_iv_sell - expected_profit # Целевая прибыль для котирования покупки
                print(f'4. Целевая прибыль для котирования покупки: {round(target_profit_buy, 2)}')
                target_iv_buy = target_profit_buy  # IV для котирования покупки
                print(f'5. Целевая IV для котирования покупки: {round(target_iv_buy, 2)}')
                S, K, T, opt_type = get_option_data_for_calc_price(dataname_buy)  # Получаем данные опциона dataname_buy
                target_price_buy_ = option_price(S, target_iv_buy / 100, K, T, r, opt_type=opt_type)  # Целевая цена для котирования покупки
                target_price_buy = int(round((target_price_buy_ // step_price) * step_price, decimals))
                print(f'Целевая цена для котирования покупки {dataname_buy}: {target_price_buy}')  # Сначала котируем покупку
                print(f'Целевая цена для мгновенной продажи {dataname_sell}: {target_price_sell}')  # Если покупка свершилась мгновенно продаем

                # Логика выставления лимитной цены на покупку опциона dataname_buy
                if target_price_buy <= bid_buy:
                    limit_price_buy = target_price_buy
                    print(f'Цена на покупку опциона {dataname_buy} в стакане {bid_buy} выше целевой цены {target_price_buy}, заявка не выставляется!')
                    sleep(timeout)
                else:
                    # При нулевой расчетной цене ставим минимальный шаг цены step_price, иначе - target_price_buy
                    limit_price_buy = bid_buy + step_price if target_price_buy != 0 else step_price

                # Лимитная цена на мгновенную продажу опциона dataname_sell
                limit_price_sell = step_price if target_price_sell == 0 else target_price_sell  # При нулевой расчетной цене ставим мин шаг цены

                # Подбираем количество в зависимости от имеющегося количества в противоположной котировке (есть риск частичного исполнения заявки) и Basket_size
                quantity_buy = min(bid_sell_vol, lot_count - lot_count_step, basket_size)

                print(
                    f'Выставляем лимитную заявку на покупку опциона {dataname_buy} по цене {limit_price_buy} и количеством {quantity_buy}')
                # Вызов функции выставления заявки на покупку
                order_id_buy, status_buy = get_order_buy(
                    account_id=account_id,  # Укажите реальный номер счета
                    symbol_buy=symbol_buy,  # Укажите реальный тикер
                    quantity_buy=quantity_buy,  # Укажите количество
                    limit_price_buy=limit_price_buy  # Укажите цену
                )
                print(f'Заявка на покупку выставлена: order_id_buy {order_id_buy}, status {status_buy}')
                sleep(Timeout)
                position = trade_dict.get(order_id_buy)
                if position:  # Если заявка на покупку исполнена
                    print(f'timestamp - {position['timestamp']}')
                    print(f'trade_id - {position['trade_id']}')
                    print(f'side - {position['side']}')
                    print(f'size - {position['size']}')
                    print(f'price - {position['price']}')

                    # Вызов функции выставления заявки на продажу
                    # Подбираем количество в зависимости от количества исполненной заявки на покупку
                    quantity_sell = quantity_buy
                    print(
                        f'Выставляем лимитную заявку по цене {limit_price_sell}: {dataname_sell} колич.: {quantity_sell} Ждём sleep_time.')
                    order_id, status = get_order_sell(
                        account_id=account_id,  # Укажите реальный номер счета
                        symbol_sell=symbol_sell,  # Укажите реальный тикер
                        quantity_sell=quantity_sell,  # Укажите количество
                        limit_price_sell=limit_price_sell  # Укажите цену
                    )
                    print(f'Заявка на продажу выставлена: {order_id}, статус: {status} ')
                    sleep(Timeout)
                    position = trade_dict.get(order_id)
                    if position:  # Если сделка на продажу состоялась
                        print(f'timestamp - {position['timestamp']}')
                        print(f'trade_id - {position['trade_id']}')
                        print(f'side - {position['side']}')
                        print(f'size - {position['size']}')
                        print(f'price - {position['price']}')

                        Lot_count_step = Lot_count_step + int(float(position['size']))
                        print(f'Завершение цикла N {Lot_count_step}')
                        if Lot_count_step == Lot_count:
                            running = False
                            print(f'Заданное количество лотов {Lot_count} исполнено. Завершение работы котировщика!')
                    else:
                        print(f'Заявка на продажу не исполнена: order_id - {order_id}')
                        # # Снятие заявки на продажу
                        # get_cancel_order(account_id, order_id)
                        # continue
                else:
                    print(f'Заявка на покупку не исполнена: order_id - {order_id_buy}')
                    # Снятие заявки на продажу
                    get_cancel_order(account_id, order_id_buy)
                    continue


            # Вариант 2 "Котируем продажу"
            else:
                print(f'{quoter_side} Котируем продажу, покупка - по рынку!')
                print(f'Вариант 2 "Котируем продажу"')
                print(f'Расчёт целевой цены продажи/купли target_price (Вариант 2 "Котируем продажу")')
                # Сначала котируем продажу опциона dataname_sell по цене target_price_sell
                # При свершении продажи сразу покупаем опцион dataname_buy по цене target_price_buy
                # Для случая, когда опцион на покупку dataname_buy (т.е. проданый ранее) имеет профит больше, чем опцион на продажу dataname_sell (купленный ранее)
                target_iv_buy = ask_iv_buy  # Целевая IV для мгновенной покупки
                print(f'1. Целевая IV для мгновенной покупки: {round(target_iv_buy, 2)}')
                target_price_buy = ask_buy  # Целевая цена для мгновенной покупки
                print(f'2. Целевая ЦЕНА для мгновенной покупки: {round(target_price_buy, 2)}')
                target_profit_sell = open_iv_buy - ask_iv_buy  # Целевая прибыль для мгновенной покупки
                print(f'3. Целевая прибыль для мгновенной покупки: {round(target_profit_sell, 2)}')
                target_profit_buy = bid_iv_sell - open_iv_sell  # Целевая прибыль для котирования продажи
                print(f'4. Целевая прибыль для котирования продажи: {round(target_profit_buy, 2)}')
                target_iv_sell = open_iv_sell + (
                            expected_profit - target_profit_buy)  # Целевая IV для котирования продажи
                print(f'5. Целевая IV для котирования продажи: {round(target_iv_sell, 2)}')
                S, K, T, opt_type = get_option_data_for_calc_price(
                    dataname_sell)  # Получаем данные опциона dataname_sell
                target_price_sell_ = option_price(S, target_iv_sell / 100, K, T, r,
                                                  opt_type=opt_type)  # Целевая цена для котирования продажи
                target_price_sell = int(round((target_price_sell_ // step_price) * step_price, decimals))
                print(f'Целевая цена для котирования продажи {dataname_sell}: {target_price_sell}')
                print(f'Целевая цена для мгновенной покупки {dataname_buy}: {target_price_buy}')

                # Логика выставления лимитной цены для котирования продажи опциона dataname_sell
                if target_price_sell >= ask_sell:
                    limit_price_sell = target_price_sell
                elif target_price_sell == 0:
                    limit_price_sell = step_price
                else:
                    limit_price_sell = ask_sell - step_price

                # Лимитная цена на мгновенную покупку опциона dataname_buy
                limit_price_buy = step_price if target_price_buy == 0 else target_price_buy

                # Подбираем количество в зависимости от количества в противоположной котировке
                quantity_sell = min(ask_buy_vol, Lot_count - Lot_count_step, Basket_size)

                print(
                    f'Выставляем лимитную заявку на продажу по цене {limit_price_sell}: {dataname_sell} количество {quantity_sell}. Ждём sleep_time.')
                # Вызов функции выставления заявки на продажу
                order_id, status = get_order_sell(
                    account_id=account_id,  # Укажите реальный номер счета
                    symbol_sell=symbol_sell,  # Укажите реальный тикер
                    quantity_sell=quantity_sell,  # Укажите количество
                    limit_price_sell=limit_price_sell  # Укажите цену
                )
                print(f'Заявка на продажу выставлена: {order_id}, статус: {status} ')
                sleep(timeout)
                position = trade_dict.get(order_id)
                if position:  # Сделка на продажу состоялась
                    print(f'timestamp - {position['timestamp']}')
                    print(f'trade_id - {position['trade_id']}')
                    print(f'side - {position['side']}')
                    print(f'size - {position['size']}')
                    print(f'price - {position['price']}')
                    # Подбираем количество в зависимости от количества исполненной заявки на покупку
                    quantity_buy = quantity_sell
                    print(
                        f'Выставляем лимитную заявку на покупку опциона {dataname_buy} по цене {limit_price_buy} в количестве {quantity_buy}')
                    # Вызов функции выставления заявки на покупку
                    order_id_buy, status_buy = get_order_buy(
                        account_id=account_id,  # Укажите реальный номер счета
                        symbol_buy=symbol_buy,  # Укажите реальный тикер
                        quantity_buy=quantity_buy,  # Укажите количество
                        limit_price_buy=limit_price_buy  # Укажите цену
                    )
                    print(f'Заявка на покупку выставлена: order_id_buy {order_id_buy}, status {status_buy}')
                    sleep(Timeout)
                    position = trade_dict.get(order_id_buy)
                    if position:
                        print(f'timestamp - {position['timestamp']}')
                        print(f'trade_id - {position['trade_id']}')
                        print(f'side - {position['side']}')
                        print(f'size - {position['size']}')
                        print(f'price - {position['price']}')

                        Lot_count_step = Lot_count_step + int(float(position['size']))
                        print(f'Завершение цикла N {Lot_count_step}')
                        if Lot_count_step == Lot_count:
                            running = False
                            print(f'Заданное количество лотов {Lot_count} исполнено. Завершение работы котировщика!')
                    else:
                        print(f'Заявка на покупку не исполнена: order_id_buy - {order_id_buy}')
                        # # Снятие заявки на покупку
                        # get_cancel_order(account_id, order_id_buy)
                        # continue
                else:
                    print(f'Заявка на продажу не исполнена: order_id - {order_id}')
                    # Снятие заявки на продажу
                    get_cancel_order(account_id, order_id)
                    continue







            # Планируем следующий вызов через 1000 мс
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
