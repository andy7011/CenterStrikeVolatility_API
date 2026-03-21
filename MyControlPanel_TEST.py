import logging # Выводим лог на консоль и в файл
# logging.basicConfig(level=logging.WARNING) # уровень логгирования

from tkinter import ttk
from tkinter import *
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
global dataname_sell, dataname_buy, expected_profit, Lot_count, Basket_size, Timeout, running
dataname_sell = ''
dataname_buy = ''
expected_profit = 5.0
Lot_count = 1
Basket_size = 1
Timeout = 8
running = False


Lot_count_step = 0
sleep_time = 5  # Время ожидания в секундах

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  # Формат сообщения
                            datefmt='%d.%m.%Y %H:%M:%S',  # Формат даты
                            level=logging.INFO,  # Уровень логируемых событий NOTSET/DEBUG/INFO/WARNING/ERROR/CRITICAL
                            handlers=[logging.FileHandler('MyControlPanel.log', encoding='utf-8'),
                                      logging.StreamHandler()])  # Лог записываем в файл и выводим на консоль
# logging.Formatter.converter = lambda *args: datetime.now(tz=fp_provider.tz_msk).timetuple()  # В логе время указываем по МСК

# Получение позиций по инструментам портфеля проданным и купленным
def get_position_finam():
    SELL = {}
    BUY = {}
    for position in default_broker.get_positions():  # Пробегаемся по всем позициям брокера
        # print(f'  - {position.dataname} {position.quantity}')
        # Получаем dataname и quantity, сохраняем в словарь SELL dataname отрицательных позиций quantity, в словарь BUY - с положительными позициями
        if position.dataname.startswith('SPBOPT.') and position.quantity > 0:
            SELL[position.dataname] = position.quantity
        elif position.dataname.startswith('SPBOPT.') and position.quantity < 0:
            BUY[position.dataname] = position.quantity
        elif position.dataname.startswith('SPBOPT.') and position.quantity == 0:
            # Можно добавить обработку нулевых позиций, если нужно
            pass
    # print(f'SELL: {SELL}')
    # print(f'BUY: {BUY}')
    default_broker.close()  # Закрываем брокера
    return SELL, BUY

SELL, BUY = get_position_finam()  # Словари для панели управления MyControlPanel.py

# Получаем данные по опционам, сохраняем в словарь
opions_data = {}
def get_opion_data_alor(dataname):
    alor_board, symbol = ap_provider.dataname_to_alor_board_symbol(dataname)  # Код режима торгов Алора и код и тикер
    exchange = ap_provider.get_exchange(alor_board, symbol)  # Код биржи
    si = ap_provider.get_symbol_info(exchange, symbol)  # Получаем информацию о тикере
    # print(si)
    # Создаем словарь для опциона
    opions_data[dataname] = {
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
    # print(f'opions_data {opions_data}')
    guid = ap_provider.quotes_subscribe(exchange, symbol)  # Получаем код подписки
    guids.append(guid)
    logger.info(f'Подписка на котировки {guid} тикера {dataname} создана')
    return opions_data

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
    base_asset_ticker = opions_data[dataname]['base_asset_ticker']
    S = float(new_quotes[base_asset_ticker]['last_price'])
    K = float(opions_data[dataname]['strikePrice'])
    expiration_datetime = opions_data[dataname]['endExpiration']
    expiration_dt = datetime.fromisoformat(expiration_datetime.replace('Z', '+00:00'))
    T_razn = (expiration_dt - datetime.today()).days
    T = float((T_razn + 1.151) / 365)
    opt_type = CALL if opions_data[dataname]['optionSide'] == 'Call' else PUT
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
    base_asset_ticker = opions_data[dataname]['base_asset_ticker']
    S = float(new_quotes[base_asset_ticker]['last_price'])
    K = float(opions_data[dataname]['strikePrice'])
    expiration_datetime = opions_data[dataname]['endExpiration']
    expiration_dt = datetime.fromisoformat(expiration_datetime.replace('Z', '+00:00'))
    T_razn = (expiration_dt - datetime.today()).days
    T = float((T_razn + 1.151) / 365)
    C = price_call
    sigma = opions_data[dataname]['volatility'] / 100
    return S, K, T, C, sigma

# Сбор данных опциона PUT для расчета IV
def option_data_for_IV_calculation_put(dataname, price_put):
    # S: последняя цена БА из обновляемого словаря new_quotes
    # K: strike price
    # T: time to maturity
    # P: Put value
    # r: interest rate
    # sigma: volatility of underlying asset
    base_asset_ticker = opions_data[dataname]['base_asset_ticker']
    S = float(new_quotes[base_asset_ticker]['last_price'])
    K = float(opions_data[dataname]['strikePrice'])
    expiration_datetime = opions_data[dataname]['endExpiration']
    expiration_dt = datetime.fromisoformat(expiration_datetime.replace('Z', '+00:00'))
    T_razn = (expiration_dt - datetime.today()).days
    T = float((T_razn + 1.151) / 365)
    P = price_put
    sigma = opions_data[dataname]['volatility'] / 100
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

root = Tk()
root.title("MyQuoteRobot_v1_5.py")
root.geometry("200x450")

def selected_sell(event):
    global theor_profit_buy, theor_profit_sell, base_asset_ticker
    # получаем выделенный элемент
    dataname_sell = combobox_sell.get()
    print(f'\n Определяем параметры опциона {dataname_sell}. Будем продавать купленный опцион.')
    ticker = dataname_sell.split('.')[-1]
    net_pos = SELL.get(dataname_sell, 0)
    open_data_result = calculate_open_data_open_price_open_iv(ticker, net_pos)  # Вычисление OpenDateTime, OpenPrice, OpenIV
    open_iv = open_data_result[2] if open_data_result[2] is not None else 0.0
    account_id = fp_provider.account_ids[0]  # Торговый счет, где будут выставляться заявки
    quantity_sell = net_pos  # Количество в шт
    option_data_sell = get_opion_data_alor(dataname_sell)
    # print(option_data_sell)
    print('Получаем данные по базовому активу, подписываемся на котировки')
    base_asset_ticker = option_data_sell[dataname_sell]['base_asset_ticker']
    alor_board, symbol = ap_provider.dataname_to_alor_board_symbol(base_asset_ticker)  # Код режима торгов Алора и код и тикер
    exchange = ap_provider.get_exchange(alor_board, symbol)  # Код биржи
    guid = ap_provider.quotes_subscribe(exchange, symbol)  # Получаем код подписки
    guids.append(guid)
    logger.info(f'Подписка на котировки {guid} тикера {base_asset_ticker} создана')
    sleep(1)
    step_price = int(float(option_data_sell[dataname_sell]['minstep']))  # Минимальный шаг цены
    open_iv_sell = open_iv
    profit_iv_sell = open_iv - expected_profit
    theoretical_price_sell_ = option_data_sell[dataname_sell]['theorPrice']
    S = float(new_quotes[base_asset_ticker]['last_price'])
    theor_iv_sell = option_data_sell[dataname_sell]['volatility']
    sigma = profit_iv_sell / 100  # сигма для расчета профитной цены profit_price_sell_
    K = float(option_data_sell[dataname_sell]['strikePrice'])
    expiration_datetime = option_data_sell[dataname_sell]['endExpiration']
    expiration_dt = datetime.fromisoformat(expiration_datetime.replace('Z', '+00:00'))
    T_razn = (expiration_dt - datetime.today()).days
    T = float((T_razn + 1.151) / 365)
    option_type = CALL if option_data_sell[dataname_sell]['optionSide'] == 'Call' else PUT
    decimals = option_data_sell[dataname_sell]['decimals']
    profit_price_sell_ = option_price(S, sigma, K, T, r, opt_type=option_type)
    limit_price_sell = int(round((profit_price_sell_ // step_price) * step_price, decimals))
    profit_price_sell = int(round((profit_price_sell_ // step_price) * step_price, decimals))
    theoretical_price_sell = int(round((theoretical_price_sell_ // step_price) * step_price, decimals))
    # Получаем ask, bid из потока котировок по подписке из обновляемого словаря new_quotes
    if ticker not in new_quotes:
        print(f'Нет котировок для тикера {ticker}')
        sleep(5)
    ask_sell = int(round(new_quotes[ticker]['ask'], decimals))
    ask_sell_vol = int(round(new_quotes[ticker]['ask_vol'], decimals))
    bid_sell = int(round(new_quotes[ticker]['bid'], decimals))
    bid_sell_vol = int(round(new_quotes[ticker]['bid_vol'], decimals))
    print(f'Котировки: ask_sell: {ask_sell} ask_sell_vol: {ask_sell_vol} bid_sell: {bid_sell} bid_sell_vol: {bid_sell_vol}')
    # Вычисляем волатильность ask_sell
    # print(f'{S}, {K}, {T}, {ask_sell}, {r}, {sigma} {option_type}')
    if option_type == 'C':
        sigma = option_data_sell[dataname_sell]['volatility'] / 100
        ask_iv_sell = newton_vol_call(S, K, T, ask_sell, r, sigma) * 100
        bid_iv_sell = newton_vol_call(S, K, T, bid_sell, r, sigma) * 100
    else:
        sigma = option_data_sell[dataname_sell]['volatility'] / 100
        ask_iv_sell = newton_vol_put(S, K, T, ask_sell, r, sigma) * 100
        bid_iv_sell = newton_vol_put(S, K, T, bid_sell, r, sigma) * 100
    print(f'Волатильность ask_sell: {round(ask_iv_sell, 2)} bid_iv_sell: {round(bid_iv_sell, 2)}')
    # saldo_sell = option_data_sell[dataname_sell]['volatility'] - open_iv # IV-theor - open_iv
    saldo_sell = ask_iv_sell - open_iv  # IV-ask - open_iv
    print(f'Saldo sell: {round(saldo_sell, 2)}')
    limit_price_sell = profit_price_sell

    print(f'\n')
    theor_profit_sell = theor_iv_sell - open_iv_sell
    market_profit_sell = bid_iv_sell - open_iv_sell
    print(f'Theor profit {dataname_sell}: {round(theor_profit_sell, 2)}')
    print(f'Market profit {dataname_sell}: {round(market_profit_sell, 2)}')

    return theor_profit_sell




def selected_buy(event):
    global theor_profit_buy, theor_profit_sell, base_asset_ticker
    # получаем выделенный элемент
    dataname_buy = combobox_buy.get()
    print(f'\n Определяем параметры опциона BUY {dataname_buy}. Будем откупать проданный опцион.')
    ticker = dataname_buy.split('.')[-1]
    net_pos = BUY.get(dataname_buy, 0)
    open_data_result = calculate_open_data_open_price_open_iv(ticker, net_pos)  # Вычисление OpenDateTime, OpenPrice, OpenIV
    open_iv = open_data_result[2] if open_data_result[2] is not None else 0.0
    option_data_buy = get_opion_data_alor(dataname_buy)
    account_id = fp_provider.account_ids[0]  # Торговый счет, где будут выставляться заявки
    quantity_buy = net_pos  # Количество в шт
    step_price = int(float(option_data_buy[dataname_buy]['minstep']))  # Минимальный шаг цены
    open_iv_buy = open_iv
    profit_iv_buy = open_iv - expected_profit
    theoretical_price_buy_ = option_data_buy[dataname_buy]['theorPrice']
    S = float(new_quotes[base_asset_ticker]['last_price'])
    theor_iv_buy = option_data_buy[dataname_buy]['volatility']
    sigma = profit_iv_buy / 100 # сигма для расчета профитной цены profit_price_buy_
    K = float(option_data_buy[dataname_buy]['strikePrice'])
    expiration_datetime = option_data_buy[dataname_buy]['endExpiration']
    expiration_dt = datetime.fromisoformat(expiration_datetime.replace('Z', '+00:00'))
    T_razn = (expiration_dt - datetime.today()).days
    T = float((T_razn + 1.151) / 365)
    option_type = CALL if option_data_buy[dataname_buy]['optionSide'] == 'Call' else PUT
    decimals = option_data_buy[dataname_buy]['decimals']
    profit_price_buy_ = option_price(S, sigma, K, T, r, opt_type=option_type)
    limit_price = int(round((profit_price_buy_ // step_price) * step_price, decimals))
    profit_price_buy = int(round((profit_price_buy_ // step_price) * step_price, decimals))
    theoretical_price_buy = int(round((theoretical_price_buy_ // step_price) * step_price, decimals))
    # Получаем ask, bid из потока котировок по подписке из обновляемого словаря new_quotes
    if ticker not in new_quotes:
        print(f'Нет котировок для тикера {ticker}')
        sleep(5)
    ask_buy = int(round(new_quotes[ticker]['ask'], decimals))
    ask_buy_vol = int(round(new_quotes[ticker]['ask_vol'], decimals))
    bid_buy = int(round(new_quotes[ticker]['bid'], decimals))
    bid_buy_vol = int(round(new_quotes[ticker]['bid_vol'], decimals))
    print(f'Котировки ask_buy: {ask_buy} ask_buy_vol: {ask_buy_vol} bid_buy: {bid_buy} bid_buy_vol: {bid_buy_vol}')
    # Вычисляем волатильность ask_buy
    # print(f'{S}, {K}, {T}, {ask_buy}, {r}, {sigma} {option_type}')
    if option_type == 'C':
        sigma = option_data_buy[dataname_buy]['volatility'] / 100
        ask_iv_buy = newton_vol_call(S, K, T, ask_buy, r, sigma) * 100
        bid_iv_buy = newton_vol_call(S, K, T, bid_buy, r, sigma) * 100
    else:
        sigma = option_data_buy[dataname_buy]['volatility'] / 100
        ask_iv_buy = newton_vol_put(S, K, T, ask_buy, r, sigma) * 100
        bid_iv_buy = newton_vol_put(S, K, T, bid_buy, r, sigma) * 100
    print(f'Волатильность ask_iv_buy: {round(ask_iv_buy, 2)} bid_iv_buy: {round(bid_iv_buy, 2)}')
    # saldo_buy = open_iv_buy - option_data_buy[dataname_buy]['volatility'] # open_iv - IV-theor
    saldo_buy = open_iv_buy - bid_iv_buy  # open_iv - IV-bid
    print(f'Saldo buy: {round(saldo_buy, 2)}')

    print(f'\n')
    theor_profit_buy = open_iv_buy - theor_iv_buy
    market_profit_buy = open_iv_buy - ask_iv_buy
    print(f'Theor profit {dataname_buy}: {round(theor_profit_buy, 2)}')
    print(f'Market profit {dataname_buy}: {round(market_profit_buy, 2)}')

    return theor_profit_buy


def selected_profit():
    # получаем выделенный выбранный процент
    expected_profit = spinbox_profit.get()
    print(expected_profit)
    # label["text"] = f"вы выбрали: {expected_profit}"

def selected_lot():
    # получаем выделенный выбранный лот
    Lot_count = spinbox_lot.get()
    print(Lot_count)
    # label["text"] = f"вы выбрали: {Lot_count}"

def selected_basket():
    # получаем выделенный выбранный баскет
    Basket_size = spinbox_basket.get()
    print(Basket_size)
    # label["text"] = f"вы выбрали: {Basket_size}"

def selected_timeout():
    # получаем выделенный выбранный таймаут
    Timeout = spinbox_timeout.get()
    print(Timeout)
    # label["text"] = f"вы выбрали: {Timeout}"

# Фрейм для центрирования элементов
main_frame = Frame(root)
main_frame.pack(expand=True, fill=BOTH)

# Элементы управления
label = ttk.Label(main_frame, text="Sell option")
label.pack(anchor=CENTER)

# Переменная dataname_sell
# Получение списка тикеров dataname из словаря SELL
sell_tickers = list(SELL.keys())
combobox_sell = ttk.Combobox(main_frame, values=sell_tickers)
combobox_sell.set(sell_tickers[0])  # Установить первый элемент по умолчанию
combobox_sell.pack(pady=5)
combobox_sell.bind("<<ComboboxSelected>>", selected_sell)

label = ttk.Label(main_frame, text="Buy option")
label.pack(anchor=CENTER)

# Переменная dataname_buy
# Получение списка тикеров dataname из словаря BUY
buy_tickers = list(BUY.keys())
combobox_buy = ttk.Combobox(main_frame, values=buy_tickers)
combobox_buy.set(buy_tickers[0])  # Установить первый элемент по умолчанию
combobox_buy.pack(pady=5)
combobox_buy.bind("<<ComboboxSelected>>", selected_buy)

label = ttk.Label(main_frame, text="Expected profit, %:")
label.pack(anchor=CENTER)

# Переменная expected_profit
spinbox_profit = ttk.Spinbox(main_frame, from_=-10, to=10, increment=0.1, format="%.1f", width=8, justify=CENTER, textvariable=2.0, command=selected_profit)
spinbox_profit.set(2.0)  # Установить значение по умолчанию
spinbox_profit.pack(pady=5)

label = ttk.Label(main_frame, text="Lot count:")
label.pack(anchor=CENTER)

# Переменная Lot_count
spinbox_lot = ttk.Spinbox(main_frame, from_=1, to=100, increment=1, width=8, justify=CENTER, command=selected_lot)
spinbox_lot.set(1)
spinbox_lot.pack(pady=5)

label = ttk.Label(main_frame, text="Basket size:")
label.pack(anchor=CENTER)

# Spinbox Переменная Basket_size
spinbox_basket = ttk.Spinbox(main_frame, from_=1, to=100, increment=1, width=8, justify=CENTER, command=selected_basket)
spinbox_basket.set(1)
spinbox_basket.pack(pady=5)

label = ttk.Label(main_frame, text="Timeout:")
label.pack(anchor=CENTER)

# Spinbox Переменная Timeout
spinbox_timeout = ttk.Spinbox(main_frame, from_=1, to=30, increment=1, width=8, justify=CENTER, command=selected_timeout)
spinbox_timeout.set(8)
spinbox_timeout.pack(pady=5)

# Кнопки вертикально в центре
button_frame = Frame(main_frame)
button_frame.pack(pady=10)


def save_config():
    # global dataname_sell, dataname_buy, expected_profit, Lot_count, Basket_size, Timeout, running
    dataname_sell = combobox_sell.get()
    dataname_buy = combobox_buy.get()
    expected_profit = float(spinbox_profit.get())
    Lot_count = int(spinbox_lot.get())
    Basket_size = int(spinbox_basket.get())
    Timeout = int(spinbox_timeout.get())
    running = False  # Сброс флага перед запуском
    print("Настройки сохранены")
    # Исходные данные
    print(f'Исходные данные:')
    print(f'Опцион на продажу dataname_sell: {dataname_sell}')
    print(f'Опцион на покупку dataname_buy: {dataname_buy}')
    print(f'Ожидаемый profit в % expected_profit: {expected_profit}')
    print(f'Количество лотов Lot_count: {Lot_count}')
    print(f'Размер Basket_size: {Basket_size}')
    print(f'Срок действия ордера в секундах Timeout: {Timeout}')

    print(f'\n')
    # if selected_sell(theor_profit_sell) > selected_buy(theor_profit_buy):
    if theor_profit_sell > theor_profit_buy:
        print(f'Вариант 1 "Котируем покупку"')
    else:
        print(f'Вариант 2 "Котируем продажу"')

    return dataname_sell, dataname_buy, expected_profit, Lot_count, Basket_size, Timeout, running

def start_program():
    print(f"Программа запущена")
    return

def stop_program():
    print("Программа остановлена")
    return

btn_save = ttk.Button(button_frame, text="SAVE", command=save_config)
btn_save.pack(pady=2)

btn_start = ttk.Button(button_frame, text="START", command=start_program)
btn_start.pack(pady=2)

btn_stop = ttk.Button(button_frame, text="STOP", command=stop_program)
btn_stop.pack(pady=2)

def exit_program():
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

btn_exit = ttk.Button(button_frame, text="EXIT", command=exit_program)
btn_exit.pack(pady=2)

root.mainloop()
