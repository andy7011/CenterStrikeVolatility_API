import logging  # Выводим лог на консоль и в файл

logging.basicConfig(level=logging.WARNING)  # уровень логгирования
import os.path
import tkinter as tk
from tkinter import ttk
from app.supported_base_asset import MAP
from pytz import utc
from threading import Thread  # Запускаем поток подписки
from AlorPy import AlorPy  # Работа с Alor OpenAPI V2
from FinamPy import FinamPy
from FinamPy.grpc.orders_service_pb2 import Order, OrderState, OrderType, CancelOrderRequest
import FinamPy.grpc.side_pb2 as side  # Направление заявки
from FinLabPy.Schedule.MOEX import Futures  # Расписание торгов срочного рынка
from zoneinfo import ZoneInfo  # ВременнАя зона
from moex_api import get_option_board, get_option_expirations
import math
import numpy as np
from datetime import datetime
from time import sleep  # Задержка в секундах перед выполнением операций
from scipy.stats import norm
from google.type.decimal_pb2 import Decimal

# Глобальные переменные для хранения данных
# global base_asset_list, option_list, expiration_dates, selected_expiration_date, base_asset_ticker, sell_tickers_call, sell_tickers_put
base_asset_list = []
option_list = []
expiration_dates = []
sell_tickers_call = []
sell_tickers_put = []
old_target_price_sell = None
old_target_price_buy = None

# Глобальные переменные
# global filename, dataname_sell, dataname_buy, base_asset_ticker, quoter_side, expected_profit, lot_count, basket_size, timeout
filename = os.path.splitext(os.path.basename(__file__))[0]  # Получаем имя файла без пути до точки .py
dataname_sell = ''
dataname_buy = ''
base_asset_ticker = ''
quoter_side = ''
expected_profit = 2.0  # Значение по умолчанию
lot_count = 1
basket_size = 1
timeout = 5
indent = 0

CALL = 'C'
PUT = 'P'
r = 0  # Безрисковая ставка
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


# Словарь новых котироок
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


# Словарь заявок
order_dict = {}


def _on_order(order):
    logger.info(f'Заявка - {order}')
    # Извлекаем данные из объекта order
    order_id = order.order_id
    exec_id = order.exec_id
    status = order.status
    symbol = order.order.symbol
    account_id = order.order.account_id
    quantity = order.order.quantity.value
    side = order.order.side
    order_type = order.order.type
    time_in_force = order.order.time_in_force
    limit_price = order.order.limit_price.value if order.order.limit_price else None
    client_order_id = order.order.client_order_id
    transact_at = order.transact_at
    initial_quantity = order.initial_quantity.value
    executed_quantity = order.executed_quantity.value
    remaining_quantity = order.remaining_quantity.value

    # Сохраняем данные в словарь по ключу symbol
    order_dict[symbol] = {
        'order_id': order_id,
        'exec_id': exec_id,
        'status': status,
        'account_id': account_id,
        'quantity': quantity,
        'side': side,
        'type': order_type,
        'time_in_force': time_in_force,
        'limit_price': limit_price,
        'client_order_id': client_order_id,
        'transact_at': transact_at,
        'initial_quantity': initial_quantity,
        'executed_quantity': executed_quantity,
        'remaining_quantity': remaining_quantity
    }
    # print(f"Заявка для {symbol}: {order_dict[symbol]}")
    # print(f"Весь словарь: {order_dict}")


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
    global base_asset_ticker
    base_asset_ticker = app_instance.combobox_base_asset.get()
    dataname_base_asset_ticker = 'SPBFUT.' + base_asset_ticker
    # print(f'dataname_base_asset_ticker {dataname_base_asset_ticker}')
    print('Получаем данные по базовому активу, подписываемся на котировки')
    alor_board, symbol = ap_provider.dataname_to_alor_board_symbol(
        base_asset_ticker)  # Код режима торгов Алора и код и тикер
    exchange = ap_provider.get_exchange(alor_board, symbol)  # Код биржи
    guid = ap_provider.quotes_subscribe(exchange, symbol)  # Получаем код подписки
    guids.append(guid)
    logger.info(f'Подписка на котировки {guid} тикера {base_asset_ticker} создана')
    sleep(1)

    # Список дат экспирации по тикеру БА
    expirations = get_option_expirations(base_asset_ticker)
    expiration_dates_ = list(set(exp['expiration_date'] for exp in expirations))
    # Сортируем и форматируем даты
    expiration_dates = [date.split('-')[2] + '.' + date.split('-')[1] + '.' + date.split('-')[0]
                        for date in sorted(expiration_dates_, key=lambda x: datetime.strptime(x, '%Y-%m-%d'))]
    # print(f'expiration dates: {expiration_dates}')

    # Обновляем значения в combobox_expire
    app_instance.combobox_expire['values'] = list(expiration_dates)
    app_instance.combobox_expire.set(expiration_dates[0])

    return expiration_dates


def on_expiration_date_change(event, app_instance):
    global base_asset_ticker, sell_tickers_call, sell_tickers_put

    selected_expiration_date = app_instance.combobox_expire.get()
    # print(f"Selected expiration date: {selected_expiration_date}")
    formatted_date = datetime.strptime(selected_expiration_date, "%d.%m.%Y").strftime("%Y-%m-%d")

    # Получить доску опционов базового актива - два списка 'C' и 'P'
    data = get_option_board(base_asset_ticker, formatted_date)
    print(f'Получить доску опционов базового актива {base_asset_ticker}, дата окончания действия: {formatted_date}')
    print(data)

    # Извлекаем SECID из списков 'C' и 'P'
    sell_tickers_call = [option['SECID'] for option in data['C']]
    sell_tickers_put = [option['SECID'] for option in data['P']]


def get_call_option_type_sell(app_instance):
    global sell_tickers_call, sell_tickers_put
    call_option_type_sell = app_instance.option_type_sell.get()  # Получаем текущее значение переменной

    # Фильтруем по типу опциона (C для Call)
    if call_option_type_sell == "C":
        sell_tickers_type = sell_tickers_call
    else:
        sell_tickers_type = sell_tickers_put
    # Обновляем sell_tickers
    app_instance.combobox_sell['values'] = list(sell_tickers_type)
    app_instance.combobox_sell.set(sell_tickers_type[0])


def selected_sell(app_instance):
    global dataname_sell
    selected_sell_ticker = app_instance.combobox_sell.get()
    dataname_sell = "SPBOPT." + selected_sell_ticker
    option_data_sell = get_opion_data_alor(dataname_sell)


def get_put_option_type_buy(app_instance):
    global sell_tickers_call, sell_tickers_put
    put_option_type_buy = app_instance.option_type_buy.get()  # Получаем текущее значение переменной
    # Фильтруем по типу опциона (P для Put)
    if put_option_type_buy == "P":
        buy_tickers_type = sell_tickers_put
    else:
        buy_tickers_type = sell_tickers_call
    # Обновляем buy_tickers
    app_instance.combobox_buy['values'] = list(buy_tickers_type)
    app_instance.combobox_buy.set(buy_tickers_type[0])


def selected_buy(app_instance):
    global dataname_buy
    selected_buy_ticker = app_instance.combobox_buy.get()
    dataname_buy = "SPBOPT." + selected_buy_ticker
    option_data_buy = get_opion_data_alor(dataname_buy)


def get_quoter_side(app_instance):
    global quoter_side
    quoter_side = app_instance.quoter_side.get()
    print(f"Котировщик SELL/BUY: {quoter_side}")


def selected_profit(app_instance):
    global expected_profit, dataname_sell, dataname_buy
    expected_profit = float(app_instance.spinbox_profit.get())
    decimals = options_data[dataname_sell]['decimals']
    step_price = int(float(options_data[dataname_sell]['minstep']))  # Минимальный шаг цены
    print(f"Expected profit: {expected_profit}")
    # Получаем ask, bid из потока котировок по подписке из обновляемого словаря new_quotes
    sell_ticker = dataname_sell.split('.')[-1]
    ask_sell = new_quotes[sell_ticker]['ask']
    bid_sell = new_quotes[sell_ticker]['bid']
    # print(f'ask_sell: {ask_sell}, bid_sell: {bid_sell}, last_sell: {last_sell}')
    S, K, T, opt_type_sell = get_option_data_for_calc_price(dataname_sell)  # Получаем данные опциона dataname_sell
    if opt_type_sell == 'C':
        sigma = options_data[dataname_sell]['volatility'] / 100
        ask_iv_sell = newton_vol_call(S, K, T, ask_sell, r, sigma) * 100
        bid_iv_sell = newton_vol_call(S, K, T, bid_sell, r, sigma) * 100
    else:  # opt_type_sell == 'P'
        sigma = options_data[dataname_sell]['volatility'] / 100
        ask_iv_sell = newton_vol_put(S, K, T, ask_sell, r, sigma) * 100
        bid_iv_sell = newton_vol_put(S, K, T, bid_sell, r, sigma) * 100
    theor_iv_sell = options_data[dataname_sell]['volatility']
    # print(f'ask_iv_sell: {round(ask_iv_sell, 2)}, bid_iv_sell: {round(bid_iv_sell, 2)}, last_iv_sell: {round(last_iv_sell, 2)}')

    # Получаем ask, bid из потока котировок по подписке из обновляемого словаря new_quotes
    buy_ticker = dataname_buy.split('.')[-1]
    ask_buy = new_quotes[buy_ticker]['ask']
    bid_buy = new_quotes[buy_ticker]['bid']
    # print(f'ask_buy: {ask_buy}, bid_buy: {bid_buy}, last_buy: {last_buy}')
    S, K, T, opt_type_buy = get_option_data_for_calc_price(dataname_buy)  # Получаем данные опциона dataname_sell
    if opt_type_buy == 'C':
        sigma = options_data[dataname_buy]['volatility'] / 100
        ask_iv_buy = newton_vol_call(S, K, T, ask_buy, r, sigma) * 100
        bid_iv_buy = newton_vol_call(S, K, T, bid_buy, r, sigma) * 100
    else:
        sigma = options_data[dataname_buy]['volatility'] / 100
        ask_iv_buy = newton_vol_put(S, K, T, ask_buy, r, sigma) * 100
        bid_iv_buy = newton_vol_put(S, K, T, bid_buy, r, sigma) * 100
    theor_iv_buy = options_data[dataname_buy]['volatility']
    # print(f'ask_iv_buy: {round(ask_iv_buy, 2)}, bid_iv_buy: {round(bid_iv_buy, 2)}, last_iv_buy: {round(last_iv_buy, 2)}')

    if quoter_side == 'SELL':
        target_iv_sell = ask_iv_buy + expected_profit  # Целевая прибыль для котирования продажи
        S, K, T, opt_type = get_option_data_for_calc_price(dataname_sell)  # Получаем данные опциона dataname_sell
        limit_price_sell_ = option_price(S, target_iv_sell / 100, K, T, r,
                                         opt_type=opt_type)  # Целевая цена для котирования продажи
        limit_price_sell = int(round((limit_price_sell_ // step_price) * step_price, decimals))
        # PUT - слева CALL - справа
        opt_type = CALL if options_data[dataname_sell]['optionSide'] == 'Call' else PUT
        if opt_type == CALL:
            print(f'\n')
            print(f'{"PUT BUY:":<30}{"CALL SELL:":<30}')
            print(f'{dataname_buy:<30}{dataname_sell:<30}')
            print(
                f'{"ask:":<10}{round(ask_buy, decimals):<10}{round(ask_iv_buy, 2):<10}{"ask:":<10}{round(ask_sell, decimals):<10}{round(ask_iv_sell, 2):<10}')
            print(
                f'{"bid:":<10}{round(bid_buy, decimals):<10}{round(bid_iv_buy, 2):<10}{"bid:":<10}{round(bid_sell, decimals):<10}{round(bid_iv_sell, 2):<10}')
            print(
                f'{"target:":<10}{round(ask_buy, decimals):<10}{round(ask_iv_buy, 2):<10}{"target:":<10}{round(limit_price_sell, decimals):<10}{round(target_iv_sell, 2):<10}')
        else:  # opt_type == PUT
            print(f'\n')
            print(f'{"PUT SELL:":<30}{"CALL BUY:":<30}')
            print(f'{dataname_sell:<30}{dataname_buy:<30}')
            print(
                f'{"ask:":<10}{round(ask_sell, decimals):<10}{round(ask_iv_sell, 2):<10}{"ask:":<10}{round(ask_buy, decimals):<10}{round(ask_iv_buy, 2):<10}')
            print(
                f'{"bid:":<10}{round(bid_sell, decimals):<10}{round(bid_iv_sell, 2):<10}{"bid:":<10}{round(bid_buy, decimals):<10}{round(bid_iv_buy, 2):<10}')
            print(
                f'{"target:":<10}{round(limit_price_sell, decimals):<10}{round(target_iv_sell, 2):<10}{"target:":<10}{round(ask_buy, decimals):<10}{round(ask_iv_buy, 2):<10}')
    else:  # quoter_side == 'BUY'
        target_iv_buy = bid_iv_sell - expected_profit  # Целевая прибыль для котирования покупки
        S, K, T, opt_type = get_option_data_for_calc_price(dataname_buy)  # Получаем данные опциона dataname_sell
        limit_price_buy_ = option_price(S, target_iv_buy / 100, K, T, r,
                                        opt_type=opt_type)  # Целевая цена для котирования покупки
        limit_price_buy = int(round((limit_price_buy_ // step_price) * step_price, decimals))
        # PUT - слева CALL - справа
        opt_type = CALL if options_data[dataname_buy]['optionSide'] == 'Call' else PUT
        if opt_type == CALL:
            print(f'\n')
            print(f'{"PUT SELL:":<30}{"CALL BUY:":<30}')
            print(f'{dataname_sell:<30}{dataname_buy:<30}')
            print(
                f'{"ask:":<10}{round(ask_sell, decimals):<10}{round(ask_iv_sell, 2):<10}{"ask:":<10}{round(ask_buy, decimals):<10}{round(ask_iv_buy, 2):<10}')
            print(
                f'{"bid:":<10}{round(bid_sell, decimals):<10}{round(bid_iv_sell, 2):<10}{"bid:":<10}{round(bid_buy, decimals):<10}{round(bid_iv_buy, 2):<10}')
            print(
                f'{"target:":<10}{round(bid_sell, decimals):<10}{round(bid_iv_sell, 2):<10}{"target:":<10}{round(limit_price_buy, decimals):<10}{round(target_iv_buy, 2):<10}')
        else:
            print(f'\n')
            print(f'{"PUT BUY:":<30}{"CALL SELL:":<30}')
            print(f'{dataname_buy:<30}{dataname_sell:<30}')
            print(
                f'{"ask:":<10}{round(ask_buy, decimals):<10}{round(ask_iv_buy, 2):<10}{"ask:":<10}{round(ask_sell, decimals):<10}{round(ask_iv_sell, 2):<10}')
            print(
                f'{"bid:":<10}{round(bid_buy, decimals):<10}{round(bid_iv_buy, 2):<10}{"bid:":<10}{round(bid_sell, decimals):<10}{round(bid_iv_sell, 2):<10}')
            print(
                f'{"target:":<10}{round(limit_price_buy, decimals):<10}{round(target_iv_buy, 2):<10}{"target:":<10}{round(bid_sell, decimals):<10}{round(bid_iv_sell, 2):<10}')


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
    timeout = int(app_instance.spinbox_timeout.get())
    print(f"Выбранный timeout: {timeout}")


def selected_indent(app_instance):
    global indent
    indent = int(app_instance.spinbox_indent.get())
    print(f"Выбранный indent: {indent}")


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


# Выставление лимитной заявки на продажу инструмента symbol_sell (типа 'RI127500BD6@RTSX') в количестве quantity_sell
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


# Проверка торговой сессии
def schedule_market(market_dt: datetime):
    """Проверяет, идет ли сейчас торговая сессия"""
    if schedule.trade_session(market_dt) is None:  # Если биржа не работает
        print('Биржа не работает')
        return None
    else:
        session = schedule.trade_session(market_dt)
        print(f'Торговая сессия: {session.time_begin} - {session.time_end}')
        return session


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(filename)
        self.root.geometry("200x720")

        self.running = False
        self.counter = 0
        self.target_price_put = 0
        self.target_price_call = 0

        # Label My Quote Robot
        self.label = tk.Label(self.root, text=filename)
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
        self.spinbox_profit_var = tk.DoubleVar(value=2.00)
        self.spinbox_profit = tk.Spinbox(self.root, from_=-10, to=10, increment=0.01, format="%.2f", width=8,
                                         textvariable=self.spinbox_profit_var, command=lambda: selected_profit(self))
        self.spinbox_profit.pack(pady=1)

        # Target-цены
        self.target_label = tk.Label(self.root, text="PUT   CALL")
        self.target_label.pack(pady=1)

        # Создаем фрейм для целевых цен
        radio_frame = tk.Frame(self.root)
        radio_frame.pack(pady=1)
        self.target_price_label_put = tk.Label(radio_frame, text="", fg="gray")
        self.target_price_label_call = tk.Label(radio_frame, text="", fg="gray")
        # self.target_price_label_put = tk.Label(radio_frame, text="", fg="#8B0000")  # Тёмно-красный
        # self.target_price_label_call = tk.Label(radio_frame, text="", fg="#006400")  # Тёмно-зелёный
        if self.option_type_sell.get() == "P":
            self.target_price_label_put = tk.Label(radio_frame, text="", fg="#8B0000")  # Тёмно-красный
        else:
            self.target_price_label_call = tk.Label(radio_frame, text="", fg="#8B0000")  # Тёмно-красный
        if self.option_type_buy.get() == "P":
            self.target_price_label_put = tk.Label(radio_frame, text="", fg="#006400")  # Тёмно-зелёный
        else:
            self.target_price_label_call = tk.Label(radio_frame, text="", fg="#006400")  # Тёмно-зелёный
        self.target_price_label_put.pack(side=tk.LEFT, pady=1)
        self.target_price_label_call.pack(side=tk.LEFT, pady=1)

        # Label Lot count
        self.lot_count_label = tk.Label(self.root, text="Lot count: ")
        self.lot_count_label.pack(pady=1)

        # # Spinbox Переменная lot_count
        # self.spinbox_lot_count_var = tk.IntVar(value=1)
        self.spinbox_lot_count_var = tk.StringVar(value="1")  # Используем StringVar
        self.spinbox_lot_count = tk.Spinbox(self.root, from_=1, to=100, increment=1, width=8,
                                            textvariable=self.spinbox_lot_count_var,
                                            command=lambda: selected_lot_count(self))
        self.spinbox_lot_count.pack(pady=1)

        # Label Basket size
        self.basket_size_label = tk.Label(self.root, text="Basket size: ")
        self.basket_size_label.pack(pady=1)

        # Spinbox Переменная Basket_size
        self.spinbox_basket_size_var = tk.IntVar(value=1)
        self.spinbox_basket_size = tk.Spinbox(self.root, from_=1, to=100, increment=1, width=8,
                                              textvariable=self.spinbox_basket_size_var,
                                              command=lambda: selected_basket_size(self))
        self.spinbox_basket_size.pack(pady=1)

        # Label timeout
        self.timeout_label = tk.Label(self.root, text="timeout: ")
        self.timeout_label.pack(pady=1)

        # Spinbox Переменная timeout
        self.spinbox_timeout_var = tk.IntVar(value=5)
        self.spinbox_timeout = tk.Spinbox(self.root, from_=1, to=30, increment=1, width=8,
                                          textvariable=self.spinbox_timeout_var, command=lambda: selected_timeout(self))
        self.spinbox_timeout.pack(pady=1)

        # Label indent
        self.indent_label = tk.Label(self.root, text="Indent: ")
        self.indent_label.pack(pady=2)

        # Spinbox Переменная indent
        self.spinbox_indent_var = tk.IntVar(value=0)
        self.spinbox_indent = tk.Spinbox(self.root, from_=-10, to=10, increment=1, width=8,
                                         textvariable=self.spinbox_indent_var, command=lambda: selected_indent(self))
        self.spinbox_indent.pack(pady=1)

        # Создаем кнопки
        self.start_button = tk.Button(self.root, text="Start", command=self.start_loop)
        self.start_button.pack(pady=2)

        self.stop_button = tk.Button(self.root, text="Stop", command=self.stop_loop)
        self.stop_button.pack(pady=2)

        # Button Exit
        self.exit_button = tk.Button(self.root, text="Exit", command=self.exit)
        self.exit_button.pack(pady=2)

        # Label status
        self.status_label = tk.Label(self.root, text="Status: Stopped")
        self.status_label.pack(pady=1)

        # Label counter
        self.counter_label = tk.Label(self.root, text="Счётчик сделок: 0")
        self.counter_label.pack(pady=1)

    def loop_function(self):
        global options_data, old_target_price_sell, old_target_price_buy, indent

        """Функция, которая будет выполняться в цикле"""
        if self.running:

            self.counter_label.config(text=f"Счётчик сделок: {self.counter}")
            self.status_label.config(text="Status: Running")

            lot_count_step = 0
            finam_board, ticker = fp_provider.dataname_to_finam_board_ticker(
                dataname_sell)  # Код режима торгов Финама и тикер
            mic = fp_provider.get_mic(finam_board, ticker)  # Биржа тикера
            symbol = f'{ticker}@{mic}'  # Тикер Финама
            symbol_sell = symbol
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
            # print(f'ask_sell: {ask_sell}, bid_sell: {bid_sell} ask_sell_vol: {ask_sell_vol}, bid_sell_vol: {bid_sell_vol}')
            if opt_type == 'C':
                sigma = options_data[dataname_sell]['volatility'] / 100
                ask_iv_sell = newton_vol_call(S, K, T, ask_sell, r, sigma) * 100
                bid_iv_sell = newton_vol_call(S, K, T, bid_sell, r, sigma) * 100
            else:
                sigma = options_data[dataname_sell]['volatility'] / 100
                ask_iv_sell = newton_vol_put(S, K, T, ask_sell, r, sigma) * 100
                bid_iv_sell = newton_vol_put(S, K, T, bid_sell, r, sigma) * 100

            finam_board, ticker = fp_provider.dataname_to_finam_board_ticker(
                dataname_buy)  # Код режима торгов Финама и тикер
            mic = fp_provider.get_mic(finam_board, ticker)  # Биржа тикера
            symbol = f'{ticker}@{mic}'  # Тикер Финама
            symbol_buy = symbol
            account_id = fp_provider.account_ids[0]  # Торговый счет, где будут выставляться заявки
            quantity_buy = options_data[dataname_buy]['lot_size']  # Количество в шт
            S, K, T, opt_type = get_option_data_for_calc_price(dataname_buy)  # Получаем данные опциона dataname_sell
            # Получаем ask, bid из потока котировок по подписке из обновляемого словаря new_quotes
            ticker = options_data[dataname_buy]['ticker']
            ask_buy = int(round(new_quotes[ticker]['ask'], decimals))
            ask_buy_vol = int(round(new_quotes[ticker]['ask_vol'], decimals))
            bid_buy = int(round(new_quotes[ticker]['bid'], decimals))
            bid_buy_vol = int(round(new_quotes[ticker]['bid_vol'], decimals))
            # print(f'opt_type {opt_type} Котировки ask_buy: {ask_buy} ask_buy_vol: {ask_buy_vol} bid_buy: {bid_buy} bid_buy_vol: {bid_buy_vol}')
            if opt_type == 'C':
                sigma = options_data[dataname_buy]['volatility'] / 100
                ask_iv_buy = newton_vol_call(S, K, T, ask_buy, r, sigma) * 100
                bid_iv_buy = newton_vol_call(S, K, T, bid_buy, r, sigma) * 100
            else:
                sigma = options_data[dataname_buy]['volatility'] / 100
                ask_iv_buy = newton_vol_put(S, K, T, ask_buy, r, sigma) * 100
                bid_iv_buy = newton_vol_put(S, K, T, bid_buy, r, sigma) * 100
            # print(f'Волатильность ask_iv_buy: {round(ask_iv_buy, 2)} bid_iv_buy: {round(bid_iv_buy, 2)}')

            # Вариант 1 "Котируем покупку"
            if quoter_side == 'BUY':

                # print(f'{quoter_side} Котируем покупку, продажа - по рынку!')
                # print(f'Вариант 1 "Котируем покупку"')
                # print(f'Расчёт целевой цены купли/продажи target_price (Вариант 1 "Котируем покупку")')
                # Сначала котируем покупку опциона dataname_buy по цене target_price_buy,
                # При свершении покупки сразу продаём опцион dataname_sell по цене target_price_sell
                # Для случая, когда опцион на продажу dataname_sell (купленный ранее) имеет профит больше, чем опцион на покупку dataname_buy
                target_iv_sell = bid_iv_sell  # Целевая IV для мгновенной продажи
                # print(f'1. Целевая IV для мгновенной продажи: {round(target_iv_sell, 2)}')
                target_price_sell = bid_sell  # Целевая ЦЕНА для мгновенной продажи
                opt_type_sell = CALL if options_data[dataname_sell]['optionSide'] == 'Call' else PUT
                if opt_type_sell == CALL:
                    self.target_price_call = target_price_sell
                    self.target_price_label_call.config(text=f"{self.target_price_call}")
                else:
                    self.target_price_put = target_price_sell
                    self.target_price_label_put.config(text=f"{self.target_price_put}")
                # print(f'2. Целевая ЦЕНА для мгновенной продажи: {round(target_price_sell, 2)}')
                # target_profit_sell = bid_iv_sell - open_iv_sell  # Целевая прибыль для мгновенной продажи
                # print(f'3. Целевая прибыль для мгновенной продажи: {round(target_profit_sell, 2)}')
                target_profit_buy = bid_iv_sell - expected_profit  # Целевая прибыль для котирования покупки
                # print(f'4. Целевая прибыль для котирования покупки: {round(target_profit_buy, 2)}')
                target_iv_buy = target_profit_buy  # IV для котирования покупки
                # print(f'5. Целевая IV для котирования покупки: {round(target_iv_buy, 2)}')
                S, K, T, opt_type = get_option_data_for_calc_price(dataname_buy)  # Получаем данные опциона dataname_buy
                target_price_buy_ = option_price(S, target_iv_buy / 100, K, T, r,
                                                 opt_type=opt_type)  # Целевая цена для котирования покупки
                target_price_buy = int(round((target_price_buy_ // step_price) * step_price, decimals))
                if opt_type == 'C':
                    self.target_price_call = target_price_buy
                    self.target_price_label_call.config(text=f"{self.target_price_call}")
                else:
                    self.target_price_put = target_price_buy
                    self.target_price_label_put.config(text=f"{self.target_price_put}")

                # Логика выставления лимитной цены на покупку опциона dataname_buy

                # Здесь введём проверку, что заявка на покупку по данному тикеру в order_dict уже существует!
                # print(f'symbol_buy: {symbol_buy}, status: {order_dict[symbol_buy]['status']}, side: {order_dict[symbol_buy]['side']}, quantity: {order_dict[symbol_buy]['quantity']} client_order_id {order_dict[symbol_buy]['client_order_id']}')
                if symbol_buy in order_dict and order_dict[symbol_buy]['status'] == 1 and order_dict[symbol_buy][
                    'side'] == 1 and float(order_dict[symbol_buy]['quantity']) == quantity_buy:
                    # print(f'Заявка на покупку по данному тикеру {dataname_buy} уже существует: {order_dict[symbol_buy]["order_id"]}')

                    # Проверка на соответствие лимитной цены в заявке target-цене
                    if bid_buy > float(
                            order_dict[symbol_buy]['limit_price']) or old_target_price_buy != target_price_buy:
                        # Снимаем старую заявку
                        get_cancel_order(account_id, order_dict[symbol_buy]['order_id'])
                        # print(f'Заявка на покупку снята:{order_dict[symbol_buy]['order_id']}')
                        self.root.after(1000, self.loop_function)
                        return
                    else:
                        # print(f'Цена на покупку опциона {dataname_buy} и таргет не изменилась')
                        self.root.after(1000, self.loop_function)
                        return
                else:
                    # print(f'Заявка на покупку по данному тикеру {dataname_buy} не существует')
                    if target_price_buy < bid_buy:  # Цена на покупку вне спреда
                        # print(f'Вне спреда')

                        # В каждом цикле сравниваем target_price с предыдущими значениями old_target_price и выводим на экран при изменении
                        if old_target_price_buy != target_price_buy or old_target_price_sell != target_price_sell:
                            current_time = datetime.now().strftime('%H:%M:%S')
                            opt_type = CALL if options_data[dataname_buy]['optionSide'] == 'Call' else PUT
                            if opt_type == CALL:
                                print(f'                    PUT      CALL')
                                print(f'{current_time} Target: BUY {target_price_buy} SELL {target_price_sell}')
                            else:
                                print(f'                    PUT      CALL')
                                print(f'{current_time} Target: BUY {target_price_buy} SELL {target_price_sell}')
                            # Сохраняем новые значения
                            old_target_price_sell = target_price_sell
                            old_target_price_buy = target_price_buy

                        # print('Заявка не выставляется!')
                        self.root.after(1000, self.loop_function)
                        return
                    else:
                        limit_price_buy = target_price_buy + (step_price * indent)
                        # Подбираем количество в зависимости от имеющегося количества в противоположной котировке (есть риск частичного исполнения заявки) и Basket_size
                        quantity_buy = basket_size
                        # print(f'Выставляем лимитную заявку на покупку опциона {dataname_buy} по цене {limit_price_buy} и количеством {quantity_buy}')
                        # Вызов функции выставления заявки на покупку
                        order_id_buy, status_buy = get_order_buy(
                            account_id=account_id,  # Укажите реальный номер счета
                            symbol_buy=symbol_buy,  # Укажите реальный тикер
                            quantity_buy=quantity_buy,  # Укажите количество
                            limit_price_buy=limit_price_buy  # Укажите цену
                        )
                        # print(f'Заявка на покупку выставлена: order_id_buy {order_id_buy}, status {status_buy}')
                        sleep(1)

                        position = trade_dict.get(order_id_buy)
                        if position:  # Сделка на покупку состоялась
                            print(f'timestamp - {position['timestamp']}')
                            print(f'trade_id - {position['trade_id']}')
                            print(f'side - {position['side']}')
                            print(f'size - {position['size']}')
                            print(f'price - {position['price']}')
                            # Подбираем количество в зависимости от количества исполненной заявки на покупку
                            quantity_sell = quantity_buy
                            # Лимитная цена на мгновенную продажу опциона dataname_sell
                            limit_price_sell = target_price_sell
                            # print(f'Выставляем лимитную заявку по цене {limit_price_sell}: {dataname_sell} колич.: {quantity_sell}')
                            # Вызов функции выставления заявки на продажу
                            order_id, status = get_order_sell(
                                account_id=account_id,  # Укажите реальный номер счета
                                symbol_sell=symbol_sell,  # Укажите реальный тикер
                                quantity_sell=quantity_sell,  # Укажите количество
                                limit_price_sell=limit_price_sell  # Укажите цену
                            )
                            # print(f'Заявка на продажу выставлена: {order_id}, статус: {status} ')
                            sleep(1)
                            position = trade_dict.get(order_id)
                            if position:  # Если сделка на продажу состоялась
                                print(f'timestamp - {position['timestamp']}')
                                print(f'trade_id - {position['trade_id']}')
                                print(f'side - {position['side']}')
                                print(f'size - {position['size']}')
                                print(f'price - {position['price']}')
                                self.counter += int(float(position['size']))
                                print(f'Завершение цикла N {lot_count_step}')
                                if self.counter >= lot_count:
                                    print(
                                        f'Заданное количество лотов {self.counter} исполнено. Завершение работы котировщика!')
                                    sleep(timeout)
                                    self.running = False
                            else:
                                print(f'Заявка на продажу не состоялась.')
                        else:  # Сделка на покупку не состоялась
                            # Проверка на изменение target-цен
                            ticker_buy = options_data[dataname_buy]['ticker']
                            ticker_sell = options_data[dataname_sell]['ticker']
                            if symbol_buy in order_dict and new_quotes[ticker_buy]['bid'] != float(
                                    order_dict[symbol_buy]['limit_price']) or target_price_sell != int(
                                round(new_quotes[ticker_sell]['bid'], decimals)):
                                get_cancel_order(account_id, order_id_buy)
                                print(f'Заявка на покупку снята:{order_id_buy}')
                            sleep(1)
                # В каждом цикле сравниваем target_price с предыдущими значениями old_target_price и выводим на экран при изменении
                if old_target_price_buy != target_price_buy or old_target_price_sell != target_price_sell:
                    current_time = datetime.now().strftime('%H:%M:%S')
                    opt_type = CALL if options_data[dataname_buy]['optionSide'] == 'Call' else PUT
                    if opt_type == CALL:
                        print(f'                    PUT      CALL')
                        print(f'{current_time} Target: BUY {target_price_buy} SELL {target_price_sell}')
                    else:
                        print(f'                    PUT      CALL')
                        print(f'{current_time} Target: BUY {target_price_buy} SELL {target_price_sell}')
                    # Сохраняем новые значения
                    old_target_price_sell = target_price_sell
                    old_target_price_buy = target_price_buy


            # Вариант 2 "Котируем продажу"
            else:  # 'SELL'
                # print(f'{quoter_side} Котируем продажу, покупка - по рынку!')
                # print(f'Вариант 2 "Котируем продажу"')
                # print(f'Расчёт целевой цены продажи/купли target_price (Вариант 2 "Котируем продажу")')
                # Сначала котируем продажу опциона dataname_sell по цене target_price_sell
                # При свершении продажи сразу покупаем опцион dataname_buy по цене target_price_buy
                # Для случая, когда опцион на покупку dataname_buy (т.е. проданый ранее) имеет профит больше, чем опцион на продажу dataname_sell (купленный ранее)
                target_iv_buy = ask_iv_buy  # Целевая IV для мгновенной покупки
                target_price_buy = ask_buy  # Целевая цена для мгновенной покупки
                opt_type_buy = CALL if options_data[dataname_buy]['optionSide'] == 'Call' else PUT
                if opt_type_buy == CALL:
                    self.target_price_call = target_price_buy
                    self.target_price_label_call.config(text=f"{self.target_price_call}")
                else:
                    self.target_price_put = target_price_buy
                    self.target_price_label_put.config(text=f"{self.target_price_put}")
                # target_profit_sell = open_iv_buy - ask_iv_buy  # Целевая прибыль для мгновенной покупки
                # print(f'3. Целевая прибыль для мгновенной покупки: {round(target_profit_sell, 2)}')
                target_profit_sell = ask_iv_buy + expected_profit  # Целевая прибыль для котирования продажи
                # print(f'4. Целевая прибыль для котирования продажи: {round(target_profit_buy, 2)}')
                target_iv_sell = target_profit_sell  # Целевая IV для котирования продажи
                # print(f'5. Целевая IV для котирования продажи: {round(target_iv_sell, 2)}')
                S, K, T, opt_type = get_option_data_for_calc_price(
                    dataname_sell)  # Получаем данные опциона dataname_sell
                target_price_sell_ = option_price(S, target_iv_sell / 100, K, T, r,
                                                  opt_type=opt_type)  # Целевая цена для котирования продажи
                target_price_sell = int(round((target_price_sell_ // step_price) * step_price, decimals))
                if opt_type == 'C':
                    self.target_price_call = target_price_sell
                    self.target_price_label_call.config(text=f"{self.target_price_call}")
                else:
                    self.target_price_put = target_price_sell
                    self.target_price_label_put.config(text=f"{self.target_price_put}")

                # Логика выставления лимитной цены для котирования продажи опциона dataname_sell

                # Здесь введём проверку, что заявка на продажу по данному тикеру в order_dict уже существует!
                # print(f'order_dict {order_dict}')
                # print(f'symbol_sell: {symbol_sell}, status: {order_dict[symbol_sell]['status']}, side: {order_dict[symbol_sell]['side']}, quantity: {order_dict[symbol_sell]['quantity']}')
                if symbol_sell in order_dict and order_dict[symbol_sell]['status'] == 1 and order_dict[symbol_sell][
                    'side'] == 2 and float(order_dict[symbol_sell]['quantity']) == quantity_sell:
                    # print(f'Заявка на продажу по данному тикеру {dataname_sell} уже существует: {order_dict[symbol_sell]["order_id"]}')

                    # Проверка на соответствие лимтной цены в заявке target-цене
                    if ask_sell < float(
                            order_dict[symbol_sell]['limit_price']) or old_target_price_sell != target_price_sell:
                        # Снимаем старую заявку
                        get_cancel_order(account_id, order_dict[symbol_sell]['order_id'])
                        # print(f'Заявка на продажу снята limit_price:{order_dict[symbol_sell]['limit_price']} ask_sell: {ask_sell}')
                        self.root.after(1000, self.loop_function)
                        return
                    else:
                        # print(f'Цена на продажу опциона {dataname_sell} и таргет не изменилась')
                        self.root.after(1000, self.loop_function)
                        return
                else:
                    # print(f'Заявка на продажу по данному тикеру {dataname_sell} не существует')
                    if target_price_sell > ask_sell:  # Цена на продажу вне спреда
                        # print(f'Вне спреда')

                        # В каждом цикле сравниваем target_price с предыдущими значениями old_target_price и выводим на экран при изменении
                        if old_target_price_sell != target_price_sell or old_target_price_buy != target_price_buy:
                            current_time = datetime.now().strftime('%H:%M:%S')
                            opt_type = CALL if options_data[dataname_sell]['optionSide'] == 'Call' else PUT
                            if opt_type == CALL:
                                print(f'                    PUT      CALL')
                                print(f'{current_time} Target: BUY {target_price_buy} SELL {target_price_sell}')
                            else:
                                print(f'                    PUT      CALL')
                                print(f'{current_time} Target: SELL {target_price_sell} BUY {target_price_buy}')
                            # Сохраняем новые значения
                            old_target_price_sell = target_price_sell
                            old_target_price_buy = target_price_buy

                        self.root.after(1000, self.loop_function)
                        return
                    else:
                        limit_price_sell = target_price_sell - (step_price * indent)
                        # Подбираем количество в зависимости от количества в противоположной котировке
                        quantity_sell = basket_size
                        # print(f'Выставляем лимитную заявку на продажу: {dataname_sell} ')
                        # print(f'                              по цене: {limit_price_sell} колич: {quantity_sell}.')
                        # Вызов функции выставления заявки на продажу
                        order_id, status = get_order_sell(
                            account_id=account_id,  # Укажите реальный номер счета
                            symbol_sell=symbol_sell,  # Укажите реальный тикер
                            quantity_sell=quantity_sell,  # Укажите количество
                            limit_price_sell=limit_price_sell  # Укажите цену
                        )
                        # print(f'Заявка на продажу выставлена: {order_id}, статус: {status} ')
                        sleep(1)

                        position = trade_dict.get(order_id)
                        if position:  # Сделка на продажу состоялась
                            print(f'timestamp - {position['timestamp']}')
                            print(f'trade_id - {position['trade_id']}')
                            print(f'side - {position['side']}')
                            print(f'size - {position['size']}')
                            print(f'price - {position['price']}')

                            # Подбираем количество в зависимости от количества исполненной заявки на покупку
                            quantity_buy = quantity_sell
                            # Лимитная цена на мгновенную покупку опциона dataname_buy
                            limit_price_buy = target_price_buy
                            # print(f'Выставляем лимитную заявку на покупку опциона {dataname_buy} по цене {limit_price_buy} в количестве {quantity_buy}')
                            # Вызов функции выставления заявки на покупку
                            order_id_buy, status_buy = get_order_buy(
                                account_id=account_id,  # Укажите реальный номер счета
                                symbol_buy=symbol_buy,  # Укажите реальный тикер
                                quantity_buy=quantity_buy,  # Укажите количество
                                limit_price_buy=limit_price_buy  # Укажите цену
                            )
                            print(f'Заявка на покупку выставлена: {order_id_buy}, status {status_buy}')
                            sleep(1)

                            position = trade_dict.get(order_id_buy)
                            if position:  # Если сделка на покупку состоялась
                                print(f'timestamp - {position['timestamp']}')
                                print(f'trade_id - {position['trade_id']}')
                                print(f'side - {position['side']}')
                                print(f'size - {position['size']}')
                                print(f'price - {position['price']}')

                                self.counter += int(float(position['size']))
                                print(f'Завершение цикла N {lot_count_step}')
                                if self.counter >= lot_count:
                                    print(
                                        f'Заданное количество лотов {self.counter} исполнено. Завершение работы котировщика!')
                                    sleep(timeout)
                                    self.running = False
                            else:
                                print(f'Заявка на покупку не исполнена: order_id_buy - {order_id_buy}')
                                # # Снятие заявки на покупку
                                # get_cancel_order(account_id, order_id_buy)
                        else:  # Сделка на продажу не состоялась
                            # Проверка на изменение target-цен
                            ticker_buy = options_data[dataname_buy]['ticker']
                            ticker_sell = options_data[dataname_sell]['ticker']
                            if symbol_sell in order_dict and new_quotes[ticker_sell]['ask'] != float(
                                    order_dict[symbol_sell]['limit_price']) or target_price_buy != \
                                    new_quotes[ticker_buy]['ask']:
                                get_cancel_order(account_id, order_id)
                                print(f'Заявка на продажу снята:{order_id}')
                            sleep(1)
                # В каждом цикле сравниваем target_price с предыдущими значениями old_target_price и выводим на экран при изменении
                if old_target_price_sell != target_price_sell or old_target_price_buy != target_price_buy:
                    current_time = datetime.now().strftime('%H:%M:%S')
                    opt_type = CALL if options_data[dataname_sell]['optionSide'] == 'Call' else PUT
                    if opt_type == CALL:
                        print(f'                    PUT      CALL')
                        print(f'{current_time} Target: BUY {target_price_buy} SELL {target_price_sell}')
                    else:
                        print(f'                    PUT      CALL')
                        print(f'{current_time} Target: SELL {target_price_sell} BUY {target_price_buy}')
                    # Сохраняем новые значения
                    old_target_price_sell = target_price_sell
                    old_target_price_buy = target_price_buy

            # Планируем следующий вызов через 100 мс
            self.root.after(1000, self.loop_function)

    def start_loop(self):
        """Запуск цикла"""
        if not self.running:
            self.running = True
            # Используем правильный способ получения временной зоны
            from zoneinfo import ZoneInfo
            market_timezone = ZoneInfo('Europe/Moscow')
            market_dt = datetime.now(market_timezone)

            while True:
                session = schedule.trade_session(market_dt)
                if session is None:
                    # Если биржа не работает, ждем до следующей сессии
                    print("Ожидание начала торговой сессии...")
                    sleep(1)  # Ждем 1 секунду перед повторной проверкой
                    # Обновляем время перед следующей проверкой
                    market_dt = datetime.now(market_timezone)
                    continue
                else:
                    # Если биржа работает, продолжаем выполнение
                    break
            self.loop_function()  # Запускаем цикл

    def stop_loop(self):
        """Остановка цикла и снятие активных заявок"""
        # Сначала останавливаем цикл
        self.running = False

        # Снимаем все активные заявки
        for symbol, order_data in order_dict.items():
            if order_data['status'] == 1:  # Активная заявка
                # Отменяем заявку через API
                get_cancel_order(order_data['account_id'], order_data['order_id'])

        # Обновляем статус в интерфейсе
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


lot_count_step = 0

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  # Формат сообщения
                    datefmt='%d.%m.%Y %H:%M:%S',  # Формат даты
                    level=logging.INFO,  # Уровень логируемых событий NOTSET/DEBUG/INFO/WARNING/ERROR/CRITICAL
                    handlers=[logging.FileHandler('MyControlPanel.log', encoding='utf-8'),
                              logging.StreamHandler()])  # Лог записываем в файл и выводим на консоль
# logging.Formatter.converter = lambda *args: datetime.now(tz=fp_provider.tz_msk).timetuple()  # В логе время указываем по МСК

logger = logging.getLogger('MyControlPanel')  # Будем вести лог
schedule = Futures()
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
