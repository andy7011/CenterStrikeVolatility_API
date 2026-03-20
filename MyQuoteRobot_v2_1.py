import logging  # Выводим лог на консоль и в файл
# logging.basicConfig(level=logging.WARNING) # уровень логгирования
import tkinter as tk
from tkinter import ttk
import time
from threading import Thread  # Запускаем поток подписки
from AlorPy import AlorPy  # Работа с Alor OpenAPI V2
from FinamPy import FinamPy
from FinLabPy.Config import brokers, default_broker  # Все брокеры и брокер по умолчанию
from QUIK_Stream_v1_7 import calculate_open_data_open_price_open_iv
import math
import numpy as np
from datetime import datetime, timezone  # Дата и время
from time import sleep  # Задержка в секундах перед выполнением операций
from scipy.stats import norm
from google.type.decimal_pb2 import Decimal

# Глобальные переменные
global theor_profit_buy, theor_profit_sell, base_asset_ticker
theor_profit_buy = 0.0
theor_profit_sell = 0.0
base_asset_ticker = 0.0
CALL = 'C'
PUT = 'P'
r = 0  # Безрисковая ставка
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


def _on_order(order):
    logger.info(f'Заявка - {order}')


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

# Импортируем необходимые модули
from FinLabPy.Config import brokers, default_broker
from AlorPy import AlorPy
from FinamPy import FinamPy
import FinamPy.grpc.side_pb2 as side
from FinamPy.grpc.marketdata_service_pb2 import QuoteRequest, QuoteResponse
from FinamPy.grpc.orders_service_pb2 import Order, OrderState, OrderType, CancelOrderRequest, StopCondition

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  # Формат сообщения
                    datefmt='%d.%m.%Y %H:%M:%S',  # Формат даты
                    level=logging.INFO,  # Уровень логируемых событий NOTSET/DEBUG/INFO/WARNING/ERROR/CRITICAL
                    handlers=[logging.FileHandler('MyControlPanel.log', encoding='utf-8'),
                              logging.StreamHandler()])  # Лог записываем в файл и выводим на консоль


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


# Сбор данных по опциону и БА для расчета цены опциона
def get_option_data_for_calc_price(dataname):
    base_asset_ticker = opions_data[dataname]['base_asset_ticker']
    S = float(new_quotes[base_asset_ticker]['last_price'])
    K = float(opions_data[dataname]['strikePrice'])
    expiration_datetime = opions_data[dataname]['endExpiration']
    expiration_dt = datetime.fromisoformat(expiration_datetime.replace('Z', '+00:00'))
    T_razн = (expiration_dt - datetime.today()).days
    T = float((T_razн + 1.151) / 365)
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
    T_razн = (expiration_dt - datetime.today()).days
    T = float((T_razн + 1.151) / 365)
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
    T_razн = (expiration_dt - datetime.today()).days
    T = float((T_razн + 1.151) / 365)
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
        # Функция Black-Scholes для CALL
        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * T ** 0.5)
        d2 = d1 - sigma * T ** 0.5
        n1 = norm.cdf(d1)
        n2 = norm.cdf(d2)
        DF = math.exp(-r * T)
        price = S * n1 - K * DF * n2

        # Частная производная от цены по волатильности (vega)
        vega = S * norm.pdf(d1) * T ** 0.5

        # Метод Ньютона
        xold = xnew
        xnew = xold - (price - C) / vega

        iteration += 1

    return xnew if iteration < max_iterations else x0


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
        # Функция Black-Scholes для PUT
        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * T ** 0.5)
        d2 = d1 - sigma * T ** 0.5
        n1 = norm.cdf(-d1)
        n2 = norm.cdf(-d2)
        DF = math.exp(-r * T)
        price = K * DF * n2 - S * n1

        # Частная производная от цены по волатильности (vega)
        vega = S * norm.pdf(d1) * T ** 0.5

        # Метод Ньютона
        xold = xnew
        xnew = xold - (price - P) / vega

        iteration += 1

    return xnew if iteration < max_iterations else x0


# Функция для остановки выполнения
def stop_operation():
    global running
    running = False
    status_label.config(text="Статус: Остановлен", foreground="red")
    output_text.insert(tk.END, "Операция остановлена\n")
    output_text.see(tk.END)


# Функция для запуска выполнения
def start_operation():
    global running, expected_profit, Lot_count, Basket_size, Timeout

    # Получаем значения из Spinbox
    expected_profit = float(expected_profit_spinbox.get())
    Lot_count = int(lot_count_spinbox.get())
    Basket_size = int(basket_size_spinbox.get())
    Timeout = int(timeout_spinbox.get())

    running = True
    status_label.config(text="Статус: Работает", foreground="green")
    output_text.insert(tk.END, "Операция запущена\n")
    output_text.see(tk.END)

    # Запускаем основной цикл
    loop_function()


# Функция для завершения работы программы
def exit_program():
    global running
    running = False

    # Отписываемся от всех каналов
    if guids:  # Проверяем, есть ли подписки
        for guid in guids:
            try:
                ap_provider.quotes_unsubscribe(guid)
                logger.info(f'Отписка от котировок {guid} выполнена')
            except Exception as e:
                logger.error(f'Ошибка при отписке от {guid}: {e}')
    else:
        logger.info('Нет активных подписок для отписки')

    # Закрываем брокеров
    try:
        default_broker.close()
        logger.info('Брокер закрыт')
    except Exception as e:
        logger.error(f'Ошибка при закрытии брокера: {e}')

    # Закрываем подключения
    try:
        # Закрываем только те подключения, которые есть
        if 'fp_provider' in locals() or 'fp_provider' in globals():
            fp_provider.close()
        if 'ap_provider' in locals() or 'ap_provider' in globals():
            ap_provider.close()
        logger.info('Подключения закрыты')
    except Exception as e:
        logger.error(f'Ошибка при закрытии подключений: {e}')

    # Закрываем окно
    root.destroy()




# Основная функция цикла
def loop_function():
    """Функция, которая будет выполняться в цикле"""
    global running
    if running:
        # Ваш основной код здесь
        # Пример операций:
        output_text.insert(tk.END, "Цикл выполняется...\n")
        output_text.see(tk.END)

        # Планируем следующий вызов через 1 секунду
        root.after(1000, loop_function)


# Функция для обновления списка инструментов
def update_instruments():
    # Получаем список инструментов из брокера
    try:
        sell_tickers = list(SELL.keys())
        instruments = []
        for position in default_broker.get_position_finam():
            if position.dataname.startswith('SPBOPT.'):
                instruments.append(position.dataname_sell)

        # Обновляем список в combobox
        combobox_sell['values'] = instruments
        combobox_buy['values'] = instruments

        if instruments:
            combobox_sell.set(instruments[0])
            combobox_buy.set(instruments[0])
    except Exception as e:
        logger.error(f"Ошибка при обновлении инструментов: {e}")


# Создаем главное окно
root = tk.Tk()
root.title("Панель управления роботом")
root.geometry("800x700")

# Настройка колонок
root.columnconfigure(0, weight=0, minsize=100)  # Метки
root.columnconfigure(1, weight=0, minsize=6)   # Комбобоксы и поля ввода - фиксированная ширина
root.columnconfigure(2, weight=0, minsize=80)    # Кнопки
root.columnconfigure(3, weight=0, minsize=80)   # Кнопки

# Настройка строк
root.rowconfigure(0, weight=1)     # Для строки 0 (фрейм)

# Создаем основной фрейм
main_frame = ttk.Frame(root, padding="10")
main_frame.grid(row=0, column=0, columnspan=4, sticky=(tk.W, tk.E, tk.N, tk.S))

# Статус
status_label = ttk.Label(main_frame, text="Статус: Готов", foreground="green")
status_label.grid(row=0, column=0, columnspan=4, sticky=tk.W)

# Выбор базового актива
ttk.Label(main_frame, text="Базовый актив:").grid(row=1, column=0, sticky=tk.W, pady=5)
combobox_base = ttk.Combobox(main_frame, width=15)
combobox_base.grid(row=1, column=1, sticky=tk.W, pady=5)
combobox_base.bind("<<ComboboxSelected>>", selected_base)

# Выбор опционной серии
ttk.Label(main_frame, text="Дата экспирации серии:").grid(row=2, column=0, sticky=tk.W, pady=5)
combobox_expire = ttk.Combobox(main_frame, width=15)
combobox_expire.grid(row=2, column=1, sticky=tk.W, pady=5)
combobox_expire.bind("<<ComboboxSelected>>", selected_expire)

# Выбор инструмента для продажи
ttk.Label(main_frame, text="Инструмент для продажи:").grid(row=3, column=0, sticky=tk.W, pady=5)
combobox_sell = ttk.Combobox(main_frame, width=15)
combobox_sell.grid(row=3, column=1, sticky=tk.W, pady=5)

# Выбор инструмента для покупки
ttk.Label(main_frame, text="Инструмент для покупки:").grid(row=4, column=0, sticky=tk.W, pady=5)
combobox_buy = ttk.Combobox(main_frame, width=15)
combobox_buy.grid(row=4, column=1, sticky=tk.W, pady=5)

# Поля ввода параметров
# Ожидаемая прибыль (%)
ttk.Label(main_frame, text="Ожидаемая прибыль (%):").grid(row=5, column=0, sticky=tk.W, pady=5)
expected_profit_spinbox = ttk.Spinbox(main_frame, from_=-10, to=10, width=5, increment=0.1, format="%.1f")
expected_profit_spinbox.set(str(expected_profit))
expected_profit_spinbox.grid(row=5, column=1, sticky=tk.W, pady=5)

# Количество лотов
ttk.Label(main_frame, text="Количество лотов:").grid(row=6, column=0, sticky=tk.W, pady=5)
lot_count_spinbox = ttk.Spinbox(main_frame, from_=1, to=1000, width=5)
lot_count_spinbox.set(str(Lot_count))
lot_count_spinbox.grid(row=6, column=1, sticky=tk.W, pady=5)

# Размер корзины
ttk.Label(main_frame, text="Лот -n/+n:").grid(row=7, column=0, sticky=tk.W, pady=5)
basket_size_spinbox = ttk.Spinbox(main_frame, from_=1, to=100, width=5)
basket_size_spinbox.set(str(Basket_size))
basket_size_spinbox.grid(row=7, column=1, sticky=tk.W, pady=5)

# Таймаут (сек)
ttk.Label(main_frame, text="Таймаут (сек):").grid(row=8, column=0, sticky=tk.W, pady=5)
timeout_spinbox = ttk.Spinbox(main_frame, from_=1, to=300, width=5)
timeout_spinbox.set(str(Timeout))
timeout_spinbox.grid(row=8, column=1, sticky=tk.W, pady=5)

# Текстовый вывод
output_text = tk.Text(main_frame, height=15, width=80)
output_text.grid(row=9, column=0, columnspan=4, pady=10)

# Кнопки управления
start_button = ttk.Button(main_frame, text="START", command=start_operation)
start_button.grid(row=10, column=0, pady=10, padx=5)

stop_button = ttk.Button(main_frame, text="STOP", command=stop_operation)
stop_button.grid(row=10, column=1, pady=10, padx=5)

exit_button = ttk.Button(main_frame, text="EXIT", command=exit_program)
exit_button.grid(row=10, column=2, pady=10, padx=5)

# Кнопка обновления инструментов
refresh_button = ttk.Button(main_frame, text="Обновить инструменты", command=update_instruments)
refresh_button.grid(row=10, column=3, pady=10, padx=5)

# Заполняем список инструментов при запуске
root.after(100, update_instruments)

# Запускаем основной цикл
root.mainloop()


