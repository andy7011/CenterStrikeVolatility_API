import logging # Выводим лог на консоль и в файл
logging.basicConfig(level=logging.WARNING) # уровень логгирования
from datetime import datetime, timezone  # Дата и время
from zoneinfo import ZoneInfo
from time import sleep  # Задержка в секундах перед выполнением операций
from threading import Thread  # Запускаем поток подписки
from MyIVCalculation import get_option_data_for_calc_price, option_price, option_data_for_IV_calculation_call, option_data_for_IV_calculation_put, newton_vol_call, newton_vol_put

import time
import math
import numpy as np
from scipy.stats import norm
import signal
import sys

from AlorPy import AlorPy  # Работа с Alor OpenAPI V2
from FinamPy import FinamPy
from FinamPy.grpc.accounts.accounts_service_pb2 import GetAccountRequest, GetAccountResponse  # Счет
from FinamPy.grpc.assets.assets_service_pb2 import GetAssetRequest, GetAssetResponse  # Информация по тикеру
from FinamPy.grpc.orders.orders_service_pb2 import Order, OrderState, OrderType, CancelOrderRequest, StopCondition  # Заявки
import FinamPy.grpc.side_pb2 as side  # Направление заявки
from FinamPy.grpc.marketdata.marketdata_service_pb2 import QuoteRequest, QuoteResponse  # Последняя цена сделки
from FinLabPy.Config import brokers, default_broker  # Все брокеры и брокер по умолчанию

from QUIK_Stream_v1_7 import calculate_open_data_open_price_open_iv

from google.type.decimal_pb2 import Decimal

# GUI код
from tkinter import *
from tkinter import ttk

# Глобальные переменные для хранения настроек
dataname_sell = "SPBOPT.Si84000BO6"
dataname_buy = "SPBOPT.Si80000BC6"
expected_profit = 1.0
Lot_count = 1
Basket_size = 1
Timeout = 5
running = False

# Глобальные переменные для GUI
root = Tk()
root.title("MyQuoteRobot_v1_6.py")
root.geometry("200x410")

# Фрейм для центрирования элементов
main_frame = Frame(root)
main_frame.pack(expand=True, fill=BOTH)

# Элементы управления
label = ttk.Label(main_frame, text="Sell option")
label.pack(anchor=CENTER)

SELL = ["SPBOPT.Si84000BO6", "SPBOPT.Si85000BO6", "SPBOPT.Si86000BO6"]
combobox_sell = ttk.Combobox(main_frame, values=SELL)
combobox_sell.set(dataname_sell)
combobox_sell.pack(pady=5)

label = ttk.Label(main_frame, text="Buy option")
label.pack(anchor=CENTER)

BUY = ["SPBOPT.Si80000BC6", "SPBOPT.Si81000BC6", "SPBOPT.Si82000BC6"]
combobox_buy = ttk.Combobox(main_frame, values=BUY)
combobox_buy.set(dataname_buy)
combobox_buy.pack(pady=5)

label = ttk.Label(main_frame, text="Expected profit, %:")
label.pack(anchor=CENTER)

spinbox_profit = ttk.Spinbox(main_frame, from_=-10, to=10, increment=0.1, format="%.1f", width=8, justify=CENTER)
spinbox_profit.set(expected_profit)
spinbox_profit.pack(pady=5)

label = ttk.Label(main_frame, text="Lot count:")
label.pack(anchor=CENTER)

spinbox_lot = ttk.Spinbox(main_frame, from_=1, to=100, increment=1, width=8, justify=CENTER)
spinbox_lot.set(Lot_count)
spinbox_lot.pack(pady=5)

label = ttk.Label(main_frame, text="Basket size:")
label.pack(anchor=CENTER)

spinbox_basket = ttk.Spinbox(main_frame, from_=1, to=100, increment=1, width=8, justify=CENTER)
spinbox_basket.set(Basket_size)
spinbox_basket.pack(pady=5)

label = ttk.Label(main_frame, text="Timeout:")
label.pack(anchor=CENTER)

spinbox_timeout = ttk.Spinbox(main_frame, from_=1, to=30, increment=1, width=8, justify=CENTER)
spinbox_timeout.set(Timeout)
spinbox_timeout.pack(pady=5)

# Кнопки вертикально в центре
button_frame = Frame(main_frame)
button_frame.pack(pady=10)

def save_config():
    global dataname_sell, dataname_buy, expected_profit, Lot_count, Basket_size, Timeout, running
    dataname_sell = combobox_sell.get()
    dataname_buy = combobox_buy.get()
    expected_profit = float(spinbox_profit.get())
    Lot_count = int(spinbox_lot.get())
    Basket_size = int(spinbox_basket.get())
    Timeout = int(spinbox_timeout.get())
    running = False  # Сброс флага перед запуском
    print("Настройки сохранены")

def start_program():
    running = True
    print("Программа запущена")

def stop_program():
    running = False
    print("Программа остановлена")

btn_save = ttk.Button(button_frame, text="SAVE", command=save_config)
btn_save.pack(pady=2)

btn_start = ttk.Button(button_frame, text="START", command=start_program)
btn_start.pack(pady=2)

btn_stop = ttk.Button(button_frame, text="STOP", command=stop_program)
btn_stop.pack(pady=2)

CALL = 'C'
PUT = 'P'
r = 0 # Безрисковая ставка
# Список GUID для отписки
guids = []

# Обработчик сигнала
def signal_handler(sig, frame):
    global running
    print('Программа завершается...')
    config.running = False  # Установка флага в config
    running = False  # Также обновляем локальную переменную
    # Завершаем все потоки, если есть
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
    # Выход
    print('Закрываем канал перед выходом')
    print(f'{datetime.now().strftime("%Y-%m-%d %H:%M:%S")} Выход')
    fp_provider.close_channel()  # Закрываем канал перед выходом
    ap_provider.close_web_socket()  # Перед выходом закрываем соединение с WebSocket
    sys.exit(0)

# Регистрируем обработчик сигнала для корректного завершения
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

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

# Выставление лимитной заявки на продажу инструмента symbol_sell в количестве quantity_sell
# по цене limit_price_sell. Возвращаем номер заявки order_id
def get_order_sell(account_id, symbol_sell, quantity_sell, limit_price_sell):
    try:
        order_state = fp_provider.call_function(
            fp_provider.orders_stub.PlaceOrder,
            Order(
                account_id=account_id,
                symbol=symbol_sell,
                quantity=Decimal(value=str(quantity_sell)),
                side=side.SIDE_SELL,
                type=OrderType.ORDER_TYPE_LIMIT,
                limit_price=Decimal(value=str(limit_price_sell)),
                client_order_id=str(int(datetime.now().timestamp()))
            )
        )
        if order_state is None:
            logger.error("Не удалось разместить ордер: order_state is None")
            return None, "ERROR"
        logger.debug(order_state)
        order_id = order_state.order_id
        logger.info(f'Номер заявки: {order_id}')
        logger.info(f'Статус заявки: {order_state.status}')
        status = order_state.status
        return order_id, status
    except Exception as e:
        logger.error(f"Ошибка размещения ордера: {e}")
        return None, "ERROR"


# Выставление лимитной заявки на покупку инструмента symbol_buy в количестве quantity_buy
# по цене limit_price_buy. Возвращаем номер заявки order_id
def get_order_buy(account_id, symbol_buy, quantity_buy, limit_price_buy):
    try:
        order_state = fp_provider.call_function(
            fp_provider.orders_stub.PlaceOrder,
            Order(
                account_id=account_id,
                symbol=symbol_buy,
                quantity=Decimal(value=str(quantity_buy)),
                side=side.SIDE_BUY,
                type=OrderType.ORDER_TYPE_LIMIT,
                limit_price=Decimal(value=str(limit_price_buy)),
                client_order_id=str(int(datetime.now().timestamp()))
            )
        )
        if order_state is None:
            logger.error("Не удалось разместить ордер: order_state is None")
            return None, "ERROR"
        logger.debug(order_state)
        order_id_buy = order_state.order_id  # Номер заявки
        status_buy = order_state.status
        logger.info(f'Номер заявки: {order_id_buy}')
        logger.info(f'Статус заявки: {status_buy}')
        return order_id_buy, status_buy
    except Exception as e:
        logger.error(f"Ошибка размещения ордера: {e}")
        return None, "ERROR"


# Удаление существующей лимитной заявки
def get_cancel_order(account_id, order_id):
    # print(f'Отмена заявки {order_id}')
    logger.info(f'Удаление заявки: {order_id}')
    order_state: OrderState = fp_provider.call_function(fp_provider.orders_stub.CancelOrder,
                                                        CancelOrderRequest(account_id=account_id,
                                                                           order_id=order_id))  # Удаление заявки
    logger.debug(order_state)
    logger.info(f'Статус заявки: {order_state.status}')
    return order_state.status

# Получаем данные портфеля брокера Финам в словарь portfolio_positions_finam
def get_portfolio_positions():
    portfolio_positions_finam = {}
    try:
        broker = brokers['Ф']  # Брокер по ключу из Config.py словаря brokers
        if broker is None:
            print("Ошибка: брокер не инициализирован")
            return []

        positions = broker.get_positions()  # Пробегаемся по всем позициям брокера
        if positions is None:
            print(f"Ошибка: не удалось получить позиции")
            return []

        for position in positions:  # Пробегаемся по всем позициям брокера
            # Проверяем, что позиция не равна 0
            if position.quantity != 0 or position.quantity != None:
                portfolio_positions_finam[position.dataname] = {
                    'dataname': position.dataname,
                    'net_pos': int(float(position.quantity)),
                    'price_pos': float(position.current_price)
                }
            else:
                print(f"Ошибка: не удалось получить позицию {position.dataname}")
                # Остановка программы
                sys.exit(1)

        return portfolio_positions_finam
    except Exception as e:
        print(f"Ошибка получения позиций: {e}")
        return []

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

# Вычисление волатильности по формуле Ньютона-Рафсона
def newton_vol_call(S, K, T, r, price):
    sigma = 0.2
    epsilon = 1e-6
    max_iterations = 100
    for i in range(max_iterations):
        price_calculated = option_price(S, sigma, K, T, r, CALL)
        diff = price_calculated - price
        if abs(diff) < epsilon:
            return sigma
        d1 = (math.log(S / K) + (r + .5 * sigma ** 2) * T) / (sigma * T ** .5)
        vega = S * norm.pdf(d1) * T ** .5
        sigma = sigma - diff / vega
    return sigma

def newton_vol_put(S, K, T, r, price):
    sigma = 0.2
    epsilon = 1e-6
    max_iterations = 100
    for i in range(max_iterations):
        price_calculated = option_price(S, sigma, K, T, r, PUT)
        diff = price_calculated - price
        if abs(diff) < epsilon:
            return sigma
        d1 = (math.log(S / K) + (r + .5 * sigma ** 2) * T) / (sigma * T ** .5)
        vega = S * norm.pdf(d1) * T ** .5
        sigma = sigma - diff / vega
    return sigma

# Основной цикл программы
def main():
    global running
    if running:
        print("Запуск def main")
    else:
        print("Не работает")
    # Инициализация остальных переменных
    # ... остальная логика программы ...
    root.mainloop()

if __name__ == "__main__":
    main()
