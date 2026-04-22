import logging  # Выводим лог на консоль и в файл
# logging.basicConfig(level=logging.WARNING)  # уровень логгирования
import os.path
import tkinter as tk
from tkinter import ttk
from app.supported_base_asset import MAP
from pytz import utc
from threading import Thread  # Запускаем поток подписки
from AlorPy import AlorPy  # Работа с Alor OpenAPI V2
from FinamPy import FinamPy
from FinamPy.grpc.orders_service_pb2 import Order, OrderState, OrderType, CancelOrderRequest
from FinamPy.grpc.accounts_service_pb2 import GetAccountRequest, GetAccountResponse  # Счет
import FinamPy.grpc.side_pb2 as side  # Направление заявки
from FinLabPy.Schedule.MOEX import Futures  # Расписание торгов срочного рынка
from zoneinfo import ZoneInfo  # ВременнАя зона
from moex_api import get_option_board, get_option_expirations
from QUIK_Stream_v1_7 import calculate_open_data_open_price_open_iv
import math
import numpy as np
from datetime import datetime
from time import sleep  # Задержка в секундах перед выполнением операций
from scipy.stats import norm
from google.type.decimal_pb2 import Decimal

app_instance = None
account_id = "1218884"
# Глобальные переменные для хранения данных
# global base_asset_list, option_list, expiration_dates, selected_expiration_date, base_asset_ticker, sell_tickers_call, sell_tickers_put
base_asset_list = []
option_list = []
expiration_dates = []
sell_tickers_call = []
sell_tickers_put = []
old_target_price_sell = None
old_target_price_buy = None
order_id_sell_control = None
order_id_buy_control = None

# Глобальные переменные
# global filename, dataname_sell, dataname_buy, base_asset_ticker, quoter_side, expected_profit, lot_count, basket_size, timeout
filename = os.path.splitext(os.path.basename(__file__))[
    0]  # Получаем имя файла (не более 10 символов исключая служебные) без пути до точки .py
dataname_sell = ''
dataname_buy = ''
base_asset_ticker = ''
quoter_side = ''
expected_profit = 2.0  # Значение по умолчанию
lot_count = 1
basket_size = 1
timeout = 3
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


portfolio_positions = {}  # Глобальный словарь для хранения позиций


def get_portfolio_positions():
    global portfolio_positions  # Используем глобальную переменную

    portfolio_positions = {}  # Очищаем словарь перед заполнением

    for account_id in fp_provider.account_ids:  # Пробегаемся по всем счетам
        account = fp_provider.call_function(fp_provider.accounts_stub.GetAccount,
                                            GetAccountRequest(account_id=account_id))  # Получаем счет

        for position in account.positions:  # Пробегаемся по всем позициям
            symbol = position.symbol
            quantity = position.quantity.value
            portfolio_positions[symbol] = quantity
    print(portfolio_positions)
    return portfolio_positions


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
    message = f'Получаем данные по базовому активу {base_asset_ticker}, подписываемся на котировки'
    app_instance.add_message(message)  # Передаём текст в окно сообщений
    print(f'Получаем данные по базовому активу {base_asset_ticker}, подписываемся на котировки')
    alor_board, symbol = ap_provider.dataname_to_alor_board_symbol(
        base_asset_ticker)  # Код режима торгов Алора и код и тикер
    exchange = ap_provider.get_exchange(alor_board, symbol)  # Код биржи
    guid = ap_provider.quotes_subscribe(exchange, symbol)  # Получаем код подписки
    guids.append(guid)
    logger.info(f'Подписка на котировки {guid} тикера {base_asset_ticker} создана')
    app_instance.add_message(f'Подписка на котировки {guid} тикера {base_asset_ticker} создана')
    sleep(1)

    # Список дат экспирации по тикеру БА
    expirations = get_option_expirations(base_asset_ticker)
    expiration_dates_ = list(set(exp['expiration_date'] for exp in expirations))
    # Сортируем и форматируем даты
    expiration_dates = [date.split('-')[2] + '.' + date.split('-')[1] + '.' + date.split('-')[0]
                        for date in sorted(expiration_dates_, key=lambda x: datetime.strptime(x, '%Y-%m-%d'))]
    app_instance.add_message(f'Даты экспирации опционов базового актива {base_asset_ticker}: {expiration_dates}')

    # Обновляем значения в combobox_expire
    app_instance.combobox_expire['values'] = list(expiration_dates)
    app_instance.combobox_expire.set(expiration_dates[0])

    return expiration_dates


def on_expiration_date_change(event, app_instance):
    global base_asset_ticker, sell_tickers_call, sell_tickers_put

    selected_expiration_date = app_instance.combobox_expire.get()
    app_instance.add_message(f"Выбрана дата экспирации: {selected_expiration_date}")
    formatted_date = datetime.strptime(selected_expiration_date, "%d.%m.%Y").strftime("%Y-%m-%d")

    # Получить доску опционов базового актива - два списка 'C' и 'P'
    data = get_option_board(base_asset_ticker, formatted_date)
    app_instance.add_message(
        f'Получаем доску опционов базового актива {base_asset_ticker}, дата экспирации: {formatted_date}')
    # print(data)

    # Извлекаем SECID из списков 'C' и 'P'
    sell_tickers_call = [option['SECID'] for option in data['C']]
    sell_tickers_put = [option['SECID'] for option in data['P']]


def get_option_type_sell(app_instance):
    global sell_tickers_call, sell_tickers_put
    option_type_sell = app_instance.option_type_sell.get()  # Получаем текущее значение переменной

    # Фильтруем по типу опциона (C для Call)
    if option_type_sell == "C":
        sell_tickers_type = sell_tickers_call
    else:
        sell_tickers_type = sell_tickers_put
    # Обновляем sell_tickers
    app_instance.combobox_sell['values'] = list(sell_tickers_type)
    app_instance.combobox_sell.set(sell_tickers_type[0])
    return option_type_sell  # Возвращаем значение


def selected_sell(app_instance):
    global dataname_sell
    selected_sell_ticker = app_instance.combobox_sell.get()
    dataname_sell = "SPBOPT." + selected_sell_ticker
    option_data_sell = get_opion_data_alor(dataname_sell)
    app_instance.add_message(f'Подписка на котировки опциона {selected_sell_ticker}')


def get_option_type_buy(app_instance):
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
    app_instance.add_message(f'Подписка на котировки опциона {selected_buy_ticker}')


def get_quoter_side(app_instance):
    global quoter_side
    quoter_side = app_instance.quoter_side.get()
    app_instance.add_message(f"Котировщик: {quoter_side}")


def selected_profit(app_instance):
    global expected_profit, dataname_sell, dataname_buy, quantity_buy, quantity_sell

    # Цикл для вычисления open_iv_buy и open_iv_sell для тикеров dataname_buy и dataname_sell
    for dataname in [dataname_buy, dataname_sell]:

        ticker = options_data[dataname]['ticker']
        # print(ticker)
        if dataname == dataname_buy:
            target_var = 'open_iv_buy'
        else:
            target_var = 'open_iv_sell'

        # Установка значения по умолчанию
        open_iv_value = 0
        quantity_value = 0

        # Поиск позиции по символу
        for symbol, quantity in portfolio_positions.items():
            # print(symbol, dataname, ticker, quantity)
            if ticker in symbol:  # Сравнение если ticker содержится в symbol

                try:
                    open_iv_value = float(
                        (calculate_open_data_open_price_open_iv(ticker, float(quantity)))[2])
                    quantity_value = float(quantity)
                    # print(open_iv_value, quantity_value)
                except (IndexError, TypeError, ValueError):
                    open_iv_value = 0
                    quantity_value = 0
                break

        # Установка переменной в глобальной области
        if target_var == 'open_iv_buy':
            open_iv_buy = open_iv_value
            quantity_buy = quantity_value
        else:
            open_iv_sell = open_iv_value
            quantity_sell = quantity_value

    expected_profit = float(app_instance.spinbox_profit.get())
    decimals = options_data[dataname_sell]['decimals']
    step_price = int(float(options_data[dataname_sell]['minstep']))  # Минимальный шаг цены

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
        diff_pos = open_iv_sell - open_iv_buy
    else:  # opt_type_sell == 'P'
        sigma = options_data[dataname_sell]['volatility'] / 100
        ask_iv_sell = newton_vol_put(S, K, T, ask_sell, r, sigma) * 100
        bid_iv_sell = newton_vol_put(S, K, T, bid_sell, r, sigma) * 100
        diff_pos = open_iv_buy - open_iv_sell
    app_instance.add_message(f'\n')
    app_instance.add_message(f"Expected profit: {expected_profit} Difference pos: {round(diff_pos, 2)}")
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

        S, K, T, opt_type_sell = get_option_data_for_calc_price(dataname_sell)  # Получаем данные опциона dataname_sell

        # PUT - слева CALL - справа
        opt_type_sell = CALL if options_data[dataname_sell]['optionSide'] == 'Call' else PUT
        if opt_type_sell == CALL:
            target_iv_sell = ask_iv_buy + expected_profit  # Целевая прибыль для котирования продажи
            limit_price_sell_ = option_price(S, target_iv_sell / 100, K, T, r,
                                             opt_type=opt_type_sell)  # Целевая цена для котирования продажи
            limit_price_sell = int(round((limit_price_sell_ // step_price) * step_price, decimals))

            app_instance.add_message(f'{"PUT BUY POS:":<14}{int(quantity_buy):<7}{"CALL SELL POS:":<14}{int(quantity_sell):<7}')
            app_instance.add_message(f'{dataname_buy:<21}{dataname_sell:<21}')
            app_instance.add_message(
                f'{"ask:":<7}{round(ask_buy, decimals):<7}{round(ask_iv_buy, 2):<7}{"ask:":<7}{round(ask_sell, decimals):<7}{round(ask_iv_sell, 2):<7}')
            app_instance.add_message(
                f'{"bid:":<7}{round(bid_buy, decimals):<7}{round(bid_iv_buy, 2):<7}{"bid:":<7}{round(bid_sell, decimals):<7}{round(bid_iv_sell, 2):<7}')
            app_instance.add_message(
                f'{"target:":<7}{round(ask_buy, decimals):<7}{round(ask_iv_buy, 2):<7}{"target:":<7}{round(limit_price_sell, decimals):<7}{round(target_iv_sell, 2):<7}')
        else:  # opt_type_sell == PUT
            target_iv_sell = ask_iv_buy - expected_profit  # Целевая прибыль для котирования продажи
            limit_price_sell_ = option_price(S, target_iv_sell / 100, K, T, r,
                                             opt_type=opt_type_sell)  # Целевая цена для котирования продажи
            limit_price_sell = int(round((limit_price_sell_ // step_price) * step_price, decimals))

            app_instance.add_message(f'{"PUT SELL POS:":<14}{int(quantity_sell):<7}{"CALL BUY POS:":<14}{int(quantity_buy):<7}')
            app_instance.add_message(f'{dataname_sell:<21}{dataname_buy:<21}')
            app_instance.add_message(
                f'{"ask:":<7}{round(ask_sell, decimals):<7}{round(ask_iv_sell, 2):<7}{"ask:":<7}{round(ask_buy, decimals):<7}{round(ask_iv_buy, 2):<7}')
            app_instance.add_message(
                f'{"bid:":<7}{round(bid_sell, decimals):<7}{round(bid_iv_sell, 2):<7}{"bid:":<7}{round(bid_buy, decimals):<7}{round(bid_iv_buy, 2):<7}')
            app_instance.add_message(
                f'{"target:":<7}{round(limit_price_sell, decimals):<7}{round(target_iv_sell, 2):<7}{"target:":<7}{round(ask_buy, decimals):<7}{round(ask_iv_buy, 2):<7}')
    else:  # quoter_side == 'BUY'

        S, K, T, opt_type_buy = get_option_data_for_calc_price(dataname_buy)  # Получаем данные опциона dataname_sell

        # PUT - слева CALL - справа
        opt_type_buy = CALL if options_data[dataname_buy]['optionSide'] == 'Call' else PUT
        if opt_type_buy == CALL:
            target_iv_buy = bid_iv_sell + expected_profit  # Целевая прибыль для котирования покупки
            limit_price_buy_ = option_price(S, target_iv_buy / 100, K, T, r,
                                            opt_type=opt_type_buy)  # Целевая цена для котирования покупки
            limit_price_buy = int(round((limit_price_buy_ // step_price) * step_price, decimals))
            app_instance.add_message(f'\n')
            app_instance.add_message(f'{"PUT SELL POS:":<14}{int(quantity_sell):<7}{"CALL BUY POS:":<14}{int(quantity_buy):<7}')
            app_instance.add_message(f'{dataname_sell:<21}{dataname_buy:<21}')
            app_instance.add_message(
                f'{"ask:":<7}{round(ask_sell, decimals):<7}{round(ask_iv_sell, 2):<7}{"ask:":<7}{round(ask_buy, decimals):<7}{round(ask_iv_buy, 2):<7}')
            app_instance.add_message(
                f'{"bid:":<7}{round(bid_sell, decimals):<7}{round(bid_iv_sell, 2):<7}{"bid:":<7}{round(bid_buy, decimals):<7}{round(bid_iv_buy, 2):<7}')
            app_instance.add_message(
                f'{"target:":<7}{round(bid_sell, decimals):<7}{round(bid_iv_sell, 2):<7}{"target:":<7}{round(limit_price_buy, decimals):<7}{round(target_iv_buy, 2):<7}')
        else:
            target_iv_buy = bid_iv_sell - expected_profit  # Целевая прибыль для котирования покупки
            limit_price_buy_ = option_price(S, target_iv_buy / 100, K, T, r,
                                            opt_type=opt_type_buy)  # Целевая цена для котирования покупки
            limit_price_buy = int(round((limit_price_buy_ // step_price) * step_price, decimals))
            app_instance.add_message(f'\n')
            app_instance.add_message(f'{"PUT BUY POS:":<14}{int(quantity_buy):<7}{"CALL SELL POS:":<14}{int(quantity_sell):<7}')
            app_instance.add_message(f'{dataname_buy:<21}{dataname_sell:<21}')
            app_instance.add_message(
                f'{"ask:":<7}{round(ask_buy, decimals):<7}{round(ask_iv_buy, 2):<7}{"ask:":<7}{round(ask_sell, decimals):<7}{round(ask_iv_sell, 2):<7}')
            app_instance.add_message(
                f'{"bid:":<7}{round(bid_buy, decimals):<7}{round(bid_iv_buy, 2):<7}{"bid:":<7}{round(bid_sell, decimals):<7}{round(bid_iv_sell, 2):<7}')
            app_instance.add_message(
                f'{"target:":<7}{round(limit_price_buy, decimals):<7}{round(target_iv_buy, 2):<7}{"target:":<7}{round(bid_sell, decimals):<7}{round(bid_iv_sell, 2):<7}')


def selected_lot_count(app_instance):
    global lot_count
    lot_count = int(app_instance.spinbox_lot_count_var.get())
    app_instance.add_message(f"Количество лотов: {lot_count}")


def selected_basket_size(app_instance):
    global basket_size
    basket_size = app_instance.spinbox_basket_size.get()
    app_instance.add_message(f"Размер лота: {basket_size}")


def selected_timeout(app_instance):
    global timeout
    timeout = int(app_instance.spinbox_timeout.get())
    app_instance.add_message(f"Выбранный timeout: {timeout}")


def selected_indent(app_instance):
    global indent
    indent = int(app_instance.spinbox_indent.get())
    app_instance.add_message(f"Сдвиг ордера в шагах цены: {indent}")


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
                client_order_id=filename + str(int(datetime.now().timestamp()))
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
                client_order_id=filename + str(int(datetime.now().timestamp()))
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
        app_instance.add_message('Биржа не работает')
        return None
    else:
        session = schedule.trade_session(market_dt)
        app_instance.add_message(f'Торговая сессия: {session.time_begin} - {session.time_end}')
        return session


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(filename)
        self.root.geometry("550x720")

        self.running = False
        self.counter = 0
        self.target_opt_type = None
        self.target_price_put = 0
        self.target_price_call = 0
        self.target_iv_put = 0
        self.target_iv_call = 0
        self.trade_count = 0  # Счётчик циклов попыток исполнения встречной заявки
        self.difference_pos = 0

        # Создаем фрейм для основных элементов
        main_frame = tk.Frame(self.root)
        main_frame.pack(side=tk.LEFT, fill=tk.Y, padx=5, pady=5)

        # Создаем фрейм для окна сообщений
        # self.message_frame = tk.Frame(self.root, width=650, bg='lightgray')
        self.message_frame = tk.Frame(self.root, width=700, height=700, bg='lightgray')
        self.message_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=1, pady=1)
        self.message_frame.pack_propagate(False)  # Не изменять размер по содержимому

        # Создаем текстовое поле для сообщений
        self.message_text = tk.Text(self.message_frame, height=20, width=70)
        self.message_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        # self.message_text = tk.Text(self.message_frame, height=20, width=70)
        # self.message_text.pack(padx=5, pady=5)

        # Label My Quote Robot
        self.label = tk.Label(main_frame, text=filename)
        self.label.pack(pady=1)

        # Label base_tickers_list
        self.base_asset_ticker_label = tk.Label(main_frame, text="Базовый актив: ")
        self.base_asset_ticker_label.pack(pady=1)

        # Выбор базового актива
        self.combobox_base_asset = ttk.Combobox(main_frame, values=list(MAP.keys()))
        # self.combobox_base_asset.set(list(MAP.keys())[0])  # Установить первый элемент по умолчанию
        self.combobox_base_asset.pack(pady=1)
        # Передаем self в обработчик
        self.combobox_base_asset.bind("<<ComboboxSelected>>", lambda event: on_base_asset_change(event, self))

        # Label Выбор опционной серии
        self.exp_date_label = tk.Label(main_frame, text="Дата экспирации: ")
        self.exp_date_label.pack(pady=1)

        # Combobox Выбор опционной серии
        self.combobox_expire = ttk.Combobox(main_frame, values=expiration_dates)
        self.combobox_expire.pack(pady=1)
        self.combobox_expire.bind("<<ComboboxSelected>>", lambda event: on_expiration_date_change(event, self))

        # Label Выбор опциона на продажу
        self.sell_option_label = tk.Label(main_frame, text="Опцион на продажу:")
        self.sell_option_label.pack(pady=1)

        # Radiobutton Выбор тип опциона "на продажу" (Call/Put)
        radio_frame = tk.Frame(main_frame)
        radio_frame.pack(pady=1)
        self.option_type_sell = tk.StringVar(value="C")
        self.call_radio_sell = tk.Radiobutton(radio_frame, text="Call", variable=self.option_type_sell, value="C",
                                              command=lambda: get_option_type_sell(self))
        self.put_radio_sell = tk.Radiobutton(radio_frame, text="Put", variable=self.option_type_sell, value="P",
                                             command=lambda: get_option_type_sell(self))
        self.call_radio_sell.pack(side=tk.LEFT, padx=10)
        self.put_radio_sell.pack(side=tk.LEFT, padx=10)

        # Combobox Выбор опциона на продажу
        self.combobox_sell = ttk.Combobox(main_frame, values=[])
        self.combobox_sell.pack(pady=1)
        self.combobox_sell.bind("<<ComboboxSelected>>", lambda event: selected_sell(self))

        # Label Выбор опциона на покупку
        self.buy_option_label = tk.Label(main_frame, text="Опцион на покупку:")
        self.buy_option_label.pack(pady=1)

        # Выбор тип опциона на покупку(Call/Put)
        radio_frame = tk.Frame(main_frame)
        radio_frame.pack(pady=1)
        self.option_type_buy = tk.StringVar(value="P")  # Установить Put по умолчанию
        self.call_radio_buy = tk.Radiobutton(radio_frame, text="Call", variable=self.option_type_buy, value="C",
                                             command=lambda: get_option_type_buy(self))
        self.put_radio_buy = tk.Radiobutton(radio_frame, text="Put", variable=self.option_type_buy, value="P",
                                            command=lambda: get_option_type_buy(self))
        self.call_radio_buy.pack(side=tk.LEFT, padx=10)
        self.put_radio_buy.pack(side=tk.LEFT, padx=10)

        # Combobox Выбор опциона на покупку
        self.combobox_buy = ttk.Combobox(main_frame, values=[])
        self.combobox_buy.pack(pady=1)
        self.combobox_buy.bind("<<ComboboxSelected>>", lambda event: selected_buy(self))

        # Label Выбор стороны котирования
        self.quoter_side_label = tk.Label(main_frame, text="Сторона котирования:")
        self.quoter_side_label.pack(pady=1)

        # Выбор SELL - котируем опцион на продажу, BUY - котируем опцион на покупку
        # Сделка по второй ноге происходит по рынку
        radio_frame = tk.Frame(main_frame)
        radio_frame.pack(pady=1, side=tk.TOP)  # Явно указываем side
        self.quoter_side = tk.StringVar(value="BUY")  # или "SELL", по умолчанию "BUY"
        self.SELL_radio = tk.Radiobutton(radio_frame, text="SELL", variable=self.quoter_side, value="SELL",
                                         command=lambda: get_quoter_side(self))
        self.BUY_radio = tk.Radiobutton(radio_frame, text="BUY", variable=self.quoter_side, value="BUY",
                                        command=lambda: get_quoter_side(self))
        self.SELL_radio.pack(side=tk.LEFT, padx=10)
        self.BUY_radio.pack(side=tk.LEFT, padx=10)

        # Label Difference pos, %:
        self.expected_profit_label = tk.Label(main_frame, text=f"Difference position, % : {self.difference_pos:.2f}")
        self.expected_profit_label.pack(pady=1)

        # Спинбокс spinbox_profit profit/difference
        self.spinbox_profit_var = tk.DoubleVar(value=-2.00)
        self.spinbox_profit = tk.Spinbox(main_frame, from_=-50, to=50, increment=0.01, format="%.2f", width=8,
                                         textvariable=self.spinbox_profit_var, command=lambda: selected_profit(self))
        self.spinbox_profit.pack(pady=1)

        # Target-цены
        self.target_label = tk.Label(main_frame, text=" PUT   CALL")
        self.target_label.pack(pady=1)

        # Создаем фрейм для целевых цен
        radio_frame = tk.Frame(main_frame)
        radio_frame.pack(pady=1)
        self.target_price_label_put = tk.Label(radio_frame, text="", fg="gray")
        self.target_price_label_call = tk.Label(radio_frame, text="", fg="gray")
        self.target_iv_label_put = tk.Label(radio_frame, text="", fg="gray")
        self.target_iv_label_call = tk.Label(radio_frame, text="", fg="gray")
        self.target_iv_label_put.pack(side=tk.LEFT, pady=1)
        self.target_price_label_put.pack(side=tk.LEFT, pady=1)
        self.target_price_label_call.pack(side=tk.LEFT, pady=1)
        self.target_iv_label_call.pack(side=tk.LEFT, pady=1)

        # Label Выбор количества лотов
        self.lot_count_label = tk.Label(main_frame, text="Количество лотов:")
        self.lot_count_label.pack(pady=1)

        # # Spinbox Переменная lot_count
        # self.spinbox_lot_count_var = tk.IntVar(value=1)
        self.spinbox_lot_count_var = tk.StringVar(value="1")  # Используем StringVar
        self.spinbox_lot_count = tk.Spinbox(main_frame, from_=1, to=100, increment=1, width=8,
                                            textvariable=self.spinbox_lot_count_var,
                                            command=lambda: selected_lot_count(self))
        self.spinbox_lot_count.pack(pady=1)

        # Label Выбор размера лота
        self.basket_size_label = tk.Label(main_frame, text="Размер лота:")
        self.basket_size_label.pack(pady=1)

        # Spinbox Переменная Basket_size
        self.spinbox_basket_size_var = tk.IntVar(value=1)
        self.spinbox_basket_size = tk.Spinbox(main_frame, from_=1, to=100, increment=1, width=8,
                                              textvariable=self.spinbox_basket_size_var,
                                              command=lambda: selected_basket_size(self))
        self.spinbox_basket_size.pack(pady=1)

        # Label Выбор таймаута
        self.timeout_label = tk.Label(main_frame, text="Таймаут (сек):")
        self.timeout_label.pack(pady=1)

        # Spinbox Выбор таймаута
        self.spinbox_timeout = tk.Spinbox(main_frame, from_=1, to=100, increment=1, width=10)
        self.spinbox_timeout.delete(0, "end")
        self.spinbox_timeout.insert(0, timeout)
        self.spinbox_timeout.pack(pady=1)
        self.spinbox_timeout.bind("<Return>", lambda event: selected_timeout(self))

        # Label indent
        self.indent_label = tk.Label(main_frame, text="Indent: ")
        self.indent_label.pack(pady=1)

        # Spinbox Переменная indent
        self.spinbox_indent_var = tk.IntVar(value=0)
        self.spinbox_indent = tk.Spinbox(main_frame, from_=-10, to=10, increment=1, width=8,
                                         textvariable=self.spinbox_indent_var, command=lambda: selected_indent(self))
        self.spinbox_indent.pack(pady=1)

        # Кнопка старт
        self.start_button = tk.Button(main_frame, text="Старт", command=self.start_loop)
        self.start_button.pack(pady=2)

        # Кнопка стоп
        self.stop_button = tk.Button(main_frame, text="Стоп", command=self.stop_loop)
        self.stop_button.pack(pady=2)

        # Button Exit
        self.exit_button = tk.Button(main_frame, text="Exit", command=self.exit)
        self.exit_button.pack(pady=2)

        # Label status
        self.status_label = tk.Label(main_frame, text="Status: Stopped")
        self.status_label.pack(pady=1)

        # Label counter
        self.counter_label = tk.Label(main_frame, text="Счётчик сделок: 0")
        self.counter_label.pack(pady=1)

    def update_target_labels(self):
        # print(self.target_opt_type)
        if self.target_opt_type == "P":
            self.target_price_label_put.config(fg="#8B0000")
            self.target_iv_label_put.config(fg="#8B0000")
            self.target_price_label_call.config(fg="#006400")
            self.target_iv_label_call.config(fg="#006400")
        else:
            self.target_price_label_put.config(fg="#006400")
            self.target_iv_label_put.config(fg="#006400")
            self.target_price_label_call.config(fg="#8B0000")
            self.target_iv_label_call.config(fg="#8B0000")

    def add_message(self, message):
        """Добавление сообщения в окно"""
        self.message_text.insert(tk.END, f"{message}\n")
        self.message_text.see(tk.END)  # Прокрутка к последнему сообщению

    def loop_function(self):
        global options_data, old_target_price_sell, old_target_price_buy, indent, order_id_sell_control, order_id_buy_control
        open_iv_sell = 0.0
        open_iv_buy = 0.0

        """Функция, которая будет выполняться в цикле"""
        if self.running:

            self.counter_label.config(text=f"Счётчик сделок: {self.counter}")
            self.status_label.config(text="Status: Running")

            ticker = options_data[dataname_sell]['ticker']
            symbol_sell = f'{ticker}@RTSX'  # Тикер Финама
            # Поиск позиции по символу
            for symbol, quantity in portfolio_positions.items():
                # print(symbol, dataname)
                if ticker in symbol:  # Сравнение если ticker содержится в symbol
                    try:
                        open_iv_sell = float(
                            (calculate_open_data_open_price_open_iv(ticker, float(quantity)))[2])
                        # print(open_iv_value)
                    except (IndexError, TypeError, ValueError):
                        open_iv_sell = 0
                    break
            # print(f'open_iv_sell: {open_iv_sell}')
            quantity_sell = options_data[dataname_sell]['lot_size']  # Размер лота
            step_price = int(float(options_data[dataname_sell]['minstep']))  # Минимальный шаг цены
            theoretical_price_sell_ = options_data[dataname_sell]['theorPrice']
            theor_iv_sell = options_data[dataname_sell]['volatility']
            decimals = options_data[dataname_sell]['decimals']
            # profit_iv_sell = theor_iv_sell + expected_profit
            # # Далее вычисляем profit_price_sell из profit_iv_sell по формуле Блэка-Шоулза
            S, K, T, opt_type_sell = get_option_data_for_calc_price(
                dataname_sell)  # Получаем данные опциона dataname_sell
            # # print(f'S: {S}, K: {K}, T: {T}, opt_type: {opt_type}')
            # profit_price_sell = option_price(S, profit_iv_sell / 100, K, T, r, opt_type=opt_type)
            # limit_price_sell = int(round((profit_price_sell // step_price) * step_price, decimals))
            # theoretical_price_sell = int(round((theoretical_price_sell_ // step_price) * step_price, decimals))
            # Получаем ask, bid из потока котировок по подписке из обновляемого словаря new_quotes
            ticker = options_data[dataname_sell]['ticker']
            ask_sell = int(round(new_quotes[ticker]['ask'], decimals))
            ask_sell_vol = int(round(new_quotes[ticker]['ask_vol'], decimals))
            bid_sell = int(round(new_quotes[ticker]['bid'], decimals))
            bid_sell_vol = int(round(new_quotes[ticker]['bid_vol'], decimals))
            # print(f'ask_sell: {ask_sell}, bid_sell: {bid_sell} ask_sell_vol: {ask_sell_vol}, bid_sell_vol: {bid_sell_vol}')
            if opt_type_sell == CALL:
                sigma = options_data[dataname_sell]['volatility'] / 100
                ask_iv_sell = newton_vol_call(S, K, T, ask_sell, r, sigma) * 100
                bid_iv_sell = newton_vol_call(S, K, T, bid_sell, r, sigma) * 100
            else:
                sigma = options_data[dataname_sell]['volatility'] / 100
                ask_iv_sell = newton_vol_put(S, K, T, ask_sell, r, sigma) * 100
                bid_iv_sell = newton_vol_put(S, K, T, bid_sell, r, sigma) * 100

            # Для тикера на покупку
            ticker = options_data[dataname_buy]['ticker']
            symbol_buy = f'{ticker}@RTSX'  # Тикер Финама
            # Поиск позиции по символу
            for symbol, quantity in portfolio_positions.items():
                # print(symbol, dataname)
                if ticker in symbol:  # Сравнение если ticker содержится в symbol
                    try:
                        open_iv_buy = float(
                            (calculate_open_data_open_price_open_iv(ticker, float(quantity)))[2])
                        # print(open_iv_value)
                    except (IndexError, TypeError, ValueError):
                        open_iv_buy = 0
                    break
            # print(f'open_iv_buy: {open_iv_buy}')
            quantity_buy = options_data[dataname_buy]['lot_size']  # Размер лота
            S, K, T, opt_type_buy = get_option_data_for_calc_price(
                dataname_buy)  # Получаем данные опциона dataname_sell
            # Получаем ask, bid из потока котировок по подписке из обновляемого словаря new_quotes
            ticker = options_data[dataname_buy]['ticker']
            ask_buy = int(round(new_quotes[ticker]['ask'], decimals))
            ask_buy_vol = int(round(new_quotes[ticker]['ask_vol'], decimals))
            bid_buy = int(round(new_quotes[ticker]['bid'], decimals))
            bid_buy_vol = int(round(new_quotes[ticker]['bid_vol'], decimals))
            # print(f'opt_type {opt_type} Котировки ask_buy: {ask_buy} ask_buy_vol: {ask_buy_vol} bid_buy: {bid_buy} bid_buy_vol: {bid_buy_vol}')
            if opt_type_buy == 'C':
                sigma = options_data[dataname_buy]['volatility'] / 100
                ask_iv_buy = newton_vol_call(S, K, T, ask_buy, r, sigma) * 100
                bid_iv_buy = newton_vol_call(S, K, T, bid_buy, r, sigma) * 100
                difference_pos = round(open_iv_buy - open_iv_sell, 2)
            else:
                sigma = options_data[dataname_buy]['volatility'] / 100
                ask_iv_buy = newton_vol_put(S, K, T, ask_buy, r, sigma) * 100
                bid_iv_buy = newton_vol_put(S, K, T, bid_buy, r, sigma) * 100
                difference_pos = round(open_iv_sell - open_iv_buy, 2)
            # print(f'Волатильность ask_iv_buy: {round(ask_iv_buy, 2)} bid_iv_buy: {round(bid_iv_buy, 2)}')
            self.difference_pos = difference_pos
            self.expected_profit_label.config(text=f"Difference pos, % : {self.difference_pos:.2f}")
            # print(f'self.difference_pos: {self.difference_pos}')

            # Вариант 1 "Котируем покупку"
            if quoter_side == 'BUY':

                # print(f'{quoter_side} Котируем покупку, продажа - по рынку!')
                # print(f'Вариант 1 "Котируем покупку"')
                # print(f'Расчёт целевой цены купли/продажи target_price (Вариант 1 "Котируем покупку")')
                # Сначала котируем покупку опциона dataname_buy по цене target_price_buy,
                # При свершении покупки сразу продаём опцион dataname_sell по цене target_price_sell
                # Для случая, когда опцион на продажу dataname_sell (купленный ранее) имеет профит больше, чем опцион на покупку dataname_buy
                target_iv_sell = bid_iv_sell  # Целевая IV для мгновенной продажи
                target_price_sell = bid_sell  # Целевая ЦЕНА для мгновенной продажи
                opt_type_sell = CALL if options_data[dataname_sell]['optionSide'] == 'Call' else PUT
                # Таргет-цены на панель управления
                if opt_type_sell == CALL:
                    self.target_opt_type = 'C'
                    self.target_price_call = target_price_sell
                    self.target_price_label_call.config(text=f"{self.target_price_call}")
                    self.target_iv_call = round(target_iv_sell, 2)
                    self.target_iv_label_call.config(text=f"{self.target_iv_call}")
                    self.update_target_labels()  # Вызов функции обновления меток
                    target_profit_buy = bid_iv_sell - expected_profit  # Целевая прибыль для котирования покупки
                else:
                    self.target_opt_type = 'P'
                    self.target_price_put = target_price_sell
                    self.target_price_label_put.config(text=f"{self.target_price_put}")
                    self.target_iv_put = round(target_iv_sell, 2)
                    self.target_iv_label_put.config(text=f"{self.target_iv_put}")
                    self.update_target_labels()  # Вызов функции обновления меток
                    target_profit_buy = bid_iv_sell + expected_profit  # Целевая прибыль для котирования покупки
                S, K, T, opt_type_buy = get_option_data_for_calc_price(
                    dataname_buy)  # Получаем данные опциона dataname_buy
                target_price_buy_ = option_price(S, target_profit_buy / 100, K, T, r,
                                                 opt_type=opt_type_buy)  # Целевая цена для котирования покупки
                target_price_buy = int(round((target_price_buy_ // step_price) * step_price, decimals))
                # Таргет-цены на панель управления
                if opt_type_buy == CALL:
                    self.target_price_call = target_price_buy
                    self.target_price_label_call.config(text=f"{self.target_price_call}")
                    self.target_iv_call = round(target_profit_buy, 2)
                    self.target_iv_label_call.config(text=f"{self.target_iv_call}")
                else:
                    self.target_price_put = target_price_buy
                    self.target_price_label_put.config(text=f"{self.target_price_put}")
                    self.target_iv_put = round(target_profit_buy, 2)
                    self.target_iv_label_put.config(text=f"{self.target_iv_put}")

                # В каждом цикле сравниваем target_price с предыдущими значениями old_target_price и выводим на экран при изменении
                if old_target_price_buy != target_price_buy or old_target_price_sell != target_price_sell:
                    current_time = datetime.now().strftime('%H:%M:%S')
                    opt_type = CALL if options_data[dataname_buy]['optionSide'] == 'Call' else PUT
                    if opt_type == CALL:
                        self.add_message(f'                    PUT      CALL')
                        self.add_message(f'{current_time} Target: BUY {target_price_sell} SELL {target_price_buy}')
                    else:
                        self.add_message(f'                    PUT      CALL')
                        self.add_message(f'{current_time} Target: BUY {target_price_buy} SELL {target_price_sell}')
                    # Сохраняем новые значения
                    old_target_price_sell = target_price_sell
                    old_target_price_buy = target_price_buy

                # Логика выставления лимитной цены на покупку опциона dataname_buy

                # Здесь введём проверку, что заявка на покупку по данному тикеру в order_dict уже существует!
                # print(f'symbol_buy: {symbol_buy}, status: {order_dict[symbol_buy]['status']}, side: {order_dict[symbol_buy]['side']}, quantity: {order_dict[symbol_buy]['quantity']} client_order_id {order_dict[symbol_buy]['client_order_id']}')
                if symbol_buy in order_dict and order_dict[symbol_buy]['status'] == 1 and order_dict[symbol_buy][
                    'side'] == 1 and float(order_dict[symbol_buy]['quantity']) == quantity_buy and order_dict[
                    symbol_buy]['client_order_id'][:10] == filename:
                    # logger.info(f'Заявка на покупку по данному тикеру {dataname_buy} уже существует: {order_dict[symbol_buy]["order_id"]}')
                    if target_price_buy < bid_buy:  # Цена на покупку вне спреда
                        # logger.info(f'Вне спреда')
                        get_cancel_order(account_id, order_dict[symbol_buy]['order_id_buy_control'])
                        logger.info(f'Заявка на покупку снята:{order_dict[symbol_buy]['order_id_buy_control']}')
                        # В начало цикла
                        self.root.after(1000, self.loop_function)
                        return
                    else:  # Цена внутри спреда
                        # Проверка на соответствие лимитной цены в заявке target-цене
                        if float(order_dict[symbol_buy]['limit_price']) != target_price_buy:
                            # Лимитная цена уже не соответствует таргет-цене, снимаем старую заявку
                            get_cancel_order(account_id, order_dict[symbol_buy]['order_id'])
                            logger.info(f'Заявка на покупку снята:{order_dict[symbol_buy]['order_id_buy_control']}')
                            # В начало цикла
                            self.root.after(1000, self.loop_function)
                            return
                        else:  # Лимитная цена соответствует таргет-цене
                            # logger.info(f'Цена на покупку опциона {dataname_buy} и таргет не изменилась')
                            # В начало цикла
                            self.root.after(1000, self.loop_function)
                            return
                else:  # Заявка на покупку по данному тикеру не существует
                    # print(f'Заявка на покупку по данному тикеру {dataname_buy} не существует')
                    # Прежде чем выставлять новую заявку нужно вставить проверку исполнилась ли старая заявка на продажу за время цикла
                    position_control = trade_dict.get(order_id_buy_control)
                    if position_control:  # Старая заявка исполнилась за время цикла
                        logger.info(f'Старая заявка на покупку исполнилась за время цикла: {order_id_buy_control}')
                        order_id_buy_control = None
                        # Далее проверяем исполнилась ли встречная заявка за время цикла
                        position_control = trade_dict.get(order_id_sell_control)
                        if position_control:  # Встречная заявка исполнилась за время цикла
                            logger.info(f'Встречная заявка исполнилась за время цикла: {order_id_sell_control}')
                            order_id_sell_control = None
                            # Здесь переходим к выставлению новой заявки на покупку, т.е. ничего не делаем
                        else:  # Встречная заявка не исполнилась за время цикла
                            # Здесь дублируем код исполнения встречной заявки
                            quantity_sell = basket_size
                            # Лимитная цена на мгновенную продажу опциона dataname_sell
                            limit_price_sell = target_price_sell
                            old_target_price_sell = target_price_sell
                            # print(f'Выставляем лимитную заявку на продажу опциона {dataname_sell} по цене {limit_price_sell} в количестве {quantity_sell}')
                            # Вызов функции выставления заявки на продажу
                            order_id_sell, status_sell = get_order_sell(
                                account_id=account_id,  # Укажите реальный номер счета
                                symbol_sell=symbol_sell,  # Укажите реальный тикер
                                quantity_sell=quantity_sell,  # Укажите количество
                                limit_price_sell=limit_price_sell  # Укажите цену
                            )
                            self.add_message(f'Заявка на продажу выставлена: {order_id_sell}, status {status_sell}')
                            logger.info(f'Заявка на продажу выставлена {order_id_sell} статус {status_sell}')
                            sleep(1)
                            position = trade_dict.get(order_id_sell)
                            if position:  # Если сделка на продажу состоялась
                                logger.info(f'Сделка на продажу {order_id_sell} состоялась')
                                self.add_message(f'timestamp - {position["timestamp"]}')
                                self.add_message(f'trade_id - {position["trade_id"]}')
                                self.add_message(f'side - {position["side"]}')
                                self.add_message(f'size - {position["size"]}')
                                self.add_message(f'price - {position["price"]}')
                                # Увеличиваем счетчик
                                self.counter += 1
                                self.add_message(f'Завершение цикла N{self.counter} из {lot_count}')
                                get_portfolio_positions()  # Обновляем портфель
                                if self.counter >= lot_count:
                                    self.add_message(
                                        f'Заданное количество лотов {self.counter} исполнено. Завершение работы котировщика!')
                                    sleep(timeout)
                                    self.running = False
                                else:
                                    # В начало цикла
                                    self.root.after(1000, self.loop_function)
                                    return
                            else:
                                self.add_message(f'Заявка на продажу не исполнена: order_id_sell - {order_id_sell}')
                                self.root.update()  # Принудительно обновляем интерфейс
                                sleep(1)
                                # В начало цикла
                                self.root.after(1000, self.loop_function)
                                return
                    else:  # Старая заявка снята или исполнена, можно выставлять новую с проверкой исполнения встречной заявки

                        # # Временная заглушка перед выставлением новой заявки!!! ДЛЯ ТЕСТОВ!!!
                        # # Планируем следующий вызов через 1000 мс
                        # self.root.after(5000, self.loop_function)
                        # return

                        if target_price_buy < bid_buy:  # Цена на покупку вне спреда
                            # logger.info(f'Вне спреда')
                            # В начало цикла
                            self.root.after(1000, self.loop_function)
                            return
                        else:  # Цена внутри спреда
                            # Проверка на соответствие лимитной цены в заявке target-цене
                            if old_target_price_buy != target_price_buy:
                                # В начало цикла
                                self.root.after(1000, self.loop_function)
                                return
                            else:  # Лимитная цена соответствует таргет-цене
                                limit_price_buy = target_price_buy + (step_price * indent)
                                old_target_price_buy = target_price_buy
                                quantity_buy = basket_size
                                logger.info(
                                    f'Выставляем лимитную заявку на покупку опциона {dataname_buy} по цене {limit_price_buy} и количеством {quantity_buy}')
                                # Вызов функции выставления заявки на покупку
                                order_id_buy, status_buy = get_order_buy(
                                    account_id=account_id,  # Укажите реальный номер счета
                                    symbol_buy=symbol_buy,  # Укажите реальный тикер
                                    quantity_buy=quantity_buy,  # Укажите количество
                                    limit_price_buy=limit_price_buy  # Укажите цену
                                )
                                logger.info(
                                    f'Заявка на покупку выставлена: order_id_buy {order_id_buy}, status {status_buy}')
                                order_id_buy_control = order_id_buy  # Запоминаем номер ордера первичной заявки для последующей проверки исполнения
                                sleep(timeout)

                                position = trade_dict.get(order_id_buy)
                                if position:  # Сделка на покупку состоялась
                                    logger.info(f'Сделка на покупку {order_id_buy} состоялась')
                                    self.add_message(f'timestamp - {position['timestamp']}')
                                    self.add_message(f'trade_id - {position['trade_id']}')
                                    self.add_message(f'side - {position['side']}')
                                    self.add_message(f'size - {position['size']}')
                                    self.add_message(f'price - {position['price']}')
                                    # Подбираем количество в зависимости от количества исполненной заявки на покупку
                                    quantity_sell = quantity_buy
                                    # Лимитная цена на мгновенную продажу опциона dataname_sell
                                    limit_price_sell = target_price_sell
                                    old_target_price_sell = target_price_sell
                                    # print(f'Выставляем лимитную заявку по цене {limit_price_sell}: {dataname_sell} колич.: {quantity_sell}')
                                    # Вызов функции выставления заявки на продажу
                                    order_id, status = get_order_sell(
                                        account_id=account_id,  # Укажите реальный номер счета
                                        symbol_sell=symbol_sell,  # Укажите реальный тикер
                                        quantity_sell=quantity_sell,  # Укажите количество
                                        limit_price_sell=limit_price_sell  # Укажите цену
                                    )
                                    self.add_message(f'Заявка на продажу выставлена: {order_id}, статус: {status} ')
                                    order_id_sell_control = order_id  # Запоминаем номер ордера встречной заявки для последующей проверки исполнения
                                    logger.info(f'Заявка на продажу выставлена {order_id} статус {status}')
                                    sleep(1)
                                    position = trade_dict.get(order_id)
                                    if position:  # Если сделка на продажу состоялась
                                        logger.info(f'Сделка на продажу {order_id} состоялась')
                                        self.add_message(f'timestamp - {position['timestamp']}')
                                        self.add_message(f'trade_id - {position['trade_id']}')
                                        self.add_message(f'side - {position['side']}')
                                        self.add_message(f'size - {position['size']}')
                                        self.add_message(f'price - {position['price']}')
                                        # Увеличиваем счетчик
                                        self.counter += 1
                                        self.add_message(f'Завершение цикла N{self.counter} из {lot_count}')
                                        get_portfolio_positions()  # Обновляем портфель
                                        if self.counter >= lot_count:
                                            self.add_message(
                                                f'Заданное количество лотов {self.counter} исполнено. Завершение работы котировщика!')
                                            sleep(timeout)
                                            self.running = False
                                        else:
                                            # Начинаем новый цикл через 1000 мс
                                            self.root.after(1000, self.loop_function)
                                            return
                                    else:
                                        self.add_message(f'Заявка на продажу не состоялась.')
                                        self.root.update()  # Принудительно обновляем интерфейс
                                        # В начало цикла
                                        self.root.after(1000, self.loop_function)
                                        return
                                else:  # Сделка на покупку не состоялась
                                    # Проверка на изменение target-цен
                                    ticker_buy = options_data[dataname_buy]['ticker']
                                    ticker_sell = options_data[dataname_sell]['ticker']
                                    if symbol_buy in order_dict and new_quotes[ticker_buy]['bid'] != float(
                                            order_dict[symbol_buy]['limit_price']) or target_price_sell != int(
                                        round(new_quotes[ticker_sell]['bid'], decimals)) and order_dict[symbol_buy][
                                        'client_order_id'][:10] == filename:
                                        get_cancel_order(account_id, order_id_buy)
                                        self.add_message(f'Заявка на покупку снята:{order_id_buy}')
                                    sleep(1)

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
                # Таргет-цены на панель управления
                if opt_type_buy == CALL:
                    self.target_price_call = target_price_buy
                    self.target_price_label_call.config(text=f"{self.target_price_call}")
                    self.target_iv_call = round(target_iv_buy, 2)
                    self.target_iv_label_call.config(text=f"{self.target_iv_call}")
                    target_profit_sell = ask_iv_buy - expected_profit  # Целевая прибыль для котирования продажи
                else:
                    self.target_price_put = target_price_buy
                    self.target_price_label_put.config(text=f"{self.target_price_put}")
                    self.target_iv_put = round(target_iv_buy, 2)
                    self.target_iv_label_put.config(text=f"{self.target_iv_put}")
                    target_profit_sell = ask_iv_buy + expected_profit  # Целевая прибыль для котирования продажи
                S, K, T, opt_type_sell = get_option_data_for_calc_price(
                    dataname_sell)  # Получаем данные опциона dataname_sell
                target_price_sell_ = option_price(S, target_profit_sell / 100, K, T, r,
                                                  opt_type=opt_type_sell)  # Целевая цена для котирования продажи
                target_price_sell = int(round((target_price_sell_ // step_price) * step_price, decimals))
                # Таргет-цены на панель управления
                if opt_type_sell == CALL:
                    self.target_opt_type = 'C'  # Устанавливаем атрибут класса
                    self.target_price_call = target_price_sell
                    self.target_price_label_call.config(text=f"{self.target_price_call}")
                    self.target_iv_call = round(target_profit_sell, 2)
                    self.target_iv_label_call.config(text=f"{self.target_iv_call}")
                    self.update_target_labels()  # Вызов функции обновления меток
                else:
                    self.target_opt_type = 'P'  # Устанавливаем атрибут класса
                    self.target_price_put = target_price_sell
                    self.target_price_label_put.config(text=f"{self.target_price_put}")
                    self.target_iv_put = round(target_profit_sell, 2)
                    self.target_iv_label_put.config(text=f"{self.target_iv_put}")
                    self.update_target_labels()  # Вызов функции обновления меток

                # В каждом цикле сравниваем target_price с предыдущими значениями old_target_price и выводим на экран при изменении
                if old_target_price_sell != target_price_sell or old_target_price_buy != target_price_buy:
                    current_time = datetime.now().strftime('%H:%M:%S')
                    opt_type = CALL if options_data[dataname_sell]['optionSide'] == 'Call' else PUT
                    if opt_type == CALL:
                        self.add_message(f'                    PUT      CALL')
                        self.add_message(f'{current_time} Target: BUY {target_price_buy} SELL {target_price_sell}')
                    else:
                        self.add_message(f'                    PUT      CALL')
                        self.add_message(f'{current_time} Target: SELL {target_price_sell} BUY {target_price_buy}')
                    # Сохраняем новые значения
                    old_target_price_sell = target_price_sell
                    old_target_price_buy = target_price_buy

                # Логика выставления лимитной цены для котирования продажи опциона dataname_sell

                # Здесь введём проверку, что первичная заявка на продажу по данному тикеру в order_dict уже существует!
                # logger.info(f'symbol_sell: {symbol_sell}, status: {order_dict[symbol_sell]['status']}, side: {order_dict[symbol_sell]['side']}, quantity: {order_dict[symbol_sell]['quantity']}')
                if symbol_sell in order_dict and order_dict[symbol_sell]['status'] == 1 and order_dict[symbol_sell][
                    'side'] == 2 and float(order_dict[symbol_sell]['quantity']) == quantity_sell and order_dict[
                    symbol_sell]['client_order_id'][:10] == filename:
                    # logger.info(f'Заявка на продажу по данному тикеру {dataname_sell} уже существует: {order_dict[symbol_sell]["order_id"]}')
                    if target_price_sell > ask_sell:  # Цена на продажу вне спреда
                        # logger.info(f'Вне спреда')
                        get_cancel_order(account_id, order_dict[symbol_sell]['order_id'])
                        logger.info(
                            f'Заявка на продажу снята limit_price:{order_dict[symbol_sell]['limit_price']} ask_sell: {ask_sell}')
                        # В начало цикла
                        self.root.after(1000, self.loop_function)
                        return
                    else:  # Цена внутри спреда
                        # Проверка на соответствие лимтной цены в заявке target-цене
                        print(f'old_target_price_sell {old_target_price_sell} target_price_sell {target_price_sell}')
                        if float(order_dict[symbol_sell]['limit_price']) != target_price_sell:
                            # Лимитная цена уже не соответствует таргет-цене, снимаем старую заявку
                            get_cancel_order(account_id, order_dict[symbol_sell]['order_id'])
                            logger.info(
                                f'Заявка на продажу снята limit_price:{order_dict[symbol_sell]['limit_price']} ask_sell: {ask_sell}')
                            # В начало цикла
                            self.root.after(1000, self.loop_function)
                            return
                        else:  # Лимитная цена соответствует таргет-цене
                            # logger.info(f'Цена на продажу опциона {dataname_sell} и таргет не изменилась')
                            # В начало цикла
                            self.root.after(1000, self.loop_function)
                            return
                else:  # Заявка на продажу по данному тикеру не существует
                    # print(f'Заявка на продажу по данному тикеру {dataname_sell} не существует')
                    # Прежде чем выставлять новую заявку нужно вставить проверку исполнилась ли старая заявка на продажу за время цикла
                    position_control = trade_dict.get(order_id_sell_control)
                    if position_control:  # Старая заявка исполнилась за время цикла
                        logger.info(f'Старая заявка на продажу исполнилась за время цикла: {order_id_sell_control}')
                        order_id_sell_control = None
                        # Далее проверяем исполнилась ли встречная заявка за время цикла
                        position_control = trade_dict.get(order_id_buy_control)
                        if position_control:  # Встречная заявка исполнилась за время цикла
                            logger.info(f'Встречная заявка исполнилась за время цикла: {order_id_buy_control}')
                            order_id_buy_control = None
                            # Здесь переходим к выставлению новой заявки на продажу, т.е. ничего не делаем
                        else:  # Встречная заявка не исполнилась за время цикла
                            # Здесь дублируем код исполнения встречной заявки
                            quantity_buy = basket_size
                            # Лимитная цена на мгновенную покупку опциона dataname_buy
                            limit_price_buy = target_price_buy
                            old_target_price_buy = target_price_buy
                            # print(f'Выставляем лимитную заявку на покупку опциона {dataname_buy} по цене {limit_price_buy} в количестве {quantity_buy}')
                            # Вызов функции выставления заявки на покупку
                            order_id_buy, status_buy = get_order_buy(
                                account_id=account_id,  # Укажите реальный номер счета
                                symbol_buy=symbol_buy,  # Укажите реальный тикер
                                quantity_buy=quantity_buy,  # Укажите количество
                                limit_price_buy=limit_price_buy  # Укажите цену
                            )
                            self.add_message(f'Заявка на покупку выставлена: {order_id_buy}, status {status_buy}')
                            logger.info(f'Заявка на покупку выставлена {order_id_buy} статус {status_buy}')
                            sleep(1)
                            position = trade_dict.get(order_id_buy)
                            if position:  # Если сделка на покупку состоялась
                                logger.info(f'Сделка на покупку {order_id_buy} состоялась')
                                self.add_message(f'timestamp - {position["timestamp"]}')
                                self.add_message(f'trade_id - {position["trade_id"]}')
                                self.add_message(f'side - {position["side"]}')
                                self.add_message(f'size - {position["size"]}')
                                self.add_message(f'price - {position["price"]}')
                                # Увеличиваем счетчик
                                self.counter += 1
                                self.add_message(f'Завершение цикла N{self.counter} из {lot_count}')
                                get_portfolio_positions()  # Обновляем портфель
                                if self.counter >= lot_count:
                                    self.add_message(
                                        f'Заданное количество лотов {self.counter} исполнено. Завершение работы котировщика!')
                                    sleep(timeout)
                                    self.running = False
                                else:
                                    # В начало цикла
                                    self.root.after(1000, self.loop_function)
                                    return
                            else:
                                self.add_message(f'Заявка на покупку не исполнена: order_id_buy - {order_id_buy}')
                                self.root.update()  # Принудительно обновляем интерфейс
                                sleep(1)
                                # В начало цикла
                                self.root.after(1000, self.loop_function)
                                return
                    else:  # Старая заявка снята или исполнена, можно выставлять новую

                        # # Временная заглушка перед выставлением новой заявки!!! ДЛЯ ТЕСТОВ!!!
                        # # Планируем следующий вызов через 1000 мс
                        # self.root.after(5000, self.loop_function)
                        # return

                        if target_price_sell > ask_sell:  # Цена на продажу вне спреда
                            # logger.info(f'Вне спреда')
                            # В начало цикла
                            self.root.after(1000, self.loop_function)
                            return
                        else:
                            # Проверка на соответствие лимитной цены target-цене
                            if old_target_price_sell != target_price_sell:
                                # В начало цикла
                                self.root.after(1000, self.loop_function)
                                return
                            else:  # Лимитная цена соответствует таргет-цене
                                limit_price_sell = target_price_sell - (step_price * indent)
                                old_target_price_sell = target_price_sell
                                quantity_sell = basket_size
                                logger.info(f'Выставляем лимитную заявку на продажу: {dataname_sell}')
                                logger.info(f'по цене: {limit_price_sell} колич: {quantity_sell}.')
                                # Вызов функции выставления заявки на продажу
                                order_id, status = get_order_sell(
                                    account_id=account_id,  # Укажите реальный номер счета
                                    symbol_sell=symbol_sell,  # Укажите реальный тикер
                                    quantity_sell=quantity_sell,  # Укажите количество
                                    limit_price_sell=limit_price_sell  # Укажите цену
                                )
                                logger.info(f'Заявка на продажу выставлена: {order_id}, статус: {status} ')
                                order_id_sell_control = order_id  # Запоминаем номер ордера первичной заявки для последующей проверки исполнения
                                sleep(timeout)

                                position = trade_dict.get(order_id)
                                if position:  # Сделка на продажу состоялась
                                    logger.info(f'Сделка на продажу {order_id} состоялась')
                                    self.add_message(f'timestamp - {position['timestamp']}')
                                    self.add_message(f'trade_id - {position['trade_id']}')
                                    self.add_message(f'side - {position['side']}')
                                    self.add_message(f'size - {position['size']}')
                                    self.add_message(f'price - {position['price']}')
                                    # Подбираем количество в зависимости от количества исполненной заявки на покупку
                                    quantity_buy = quantity_sell
                                    # Лимитная цена на мгновенную покупку опциона dataname_buy
                                    limit_price_buy = target_price_buy
                                    old_target_price_buy = target_price_buy
                                    # print(f'Выставляем лимитную заявку на покупку опциона {dataname_buy} по цене {limit_price_buy} в количестве {quantity_buy}')
                                    # Вызов функции выставления заявки на покупку
                                    order_id_buy, status_buy = get_order_buy(
                                        account_id=account_id,  # Укажите реальный номер счета
                                        symbol_buy=symbol_buy,  # Укажите реальный тикер
                                        quantity_buy=quantity_buy,  # Укажите количество
                                        limit_price_buy=limit_price_buy  # Укажите цену
                                    )
                                    self.add_message(f'Заявка на покупку выставлена: {order_id_buy}, status {status_buy}')
                                    order_id_buy_control = order_id_buy  # Запоминаем номер ордера встречной заявки для последующей проверки исполнения
                                    logger.info(f'Заявка на покупку выставлена {order_id_buy} статус {status_buy}')
                                    sleep(1)
                                    position = trade_dict.get(order_id_buy)
                                    if position:  # Если сделка на покупку состоялась
                                        logger.info(f'Сделка на покупку {order_id_buy} состоялась')
                                        self.add_message(f'timestamp - {position["timestamp"]}')
                                        self.add_message(f'trade_id - {position["trade_id"]}')
                                        self.add_message(f'side - {position["side"]}')
                                        self.add_message(f'size - {position["size"]}')
                                        self.add_message(f'price - {position["price"]}')
                                        # Увеличиваем счетчик
                                        self.counter += 1
                                        self.add_message(f'Завершение цикла N{self.counter} из {lot_count}')
                                        get_portfolio_positions()  # Обновляем портфель
                                        if self.counter >= lot_count:
                                            self.add_message(
                                                f'Заданное количество лотов {self.counter} исполнено. Завершение работы котировщика!')
                                            sleep(timeout)
                                            self.running = False
                                        else:
                                            # В начало цикла
                                            self.root.after(1000, self.loop_function)
                                            return
                                    else:
                                        self.add_message(f'Заявка на покупку не исполнена: order_id_buy - {order_id_buy}')
                                        self.root.update()  # Принудительно обновляем интерфейс
                                        # В начало цикла
                                        self.root.after(1000, self.loop_function)
                                        return
                                else:  # Сделка на продажу не состоялась
                                    # Проверка на изменение target-цен
                                    ticker_buy = options_data[dataname_buy]['ticker']
                                    ticker_sell = options_data[dataname_sell]['ticker']
                                    if symbol_sell in order_dict and new_quotes[ticker_sell]['ask'] != float(
                                            order_dict[symbol_sell]['limit_price']) or target_price_buy != \
                                            new_quotes[ticker_buy]['ask'] and order_dict[symbol_sell]['client_order_id'][
                                        :10] == filename:
                                        get_cancel_order(account_id, order_id)
                                        logger.info(f'Заявка на продажу снята:{order_id}')
                                    sleep(1)

            # Планируем следующий вызов через 100 мс
            self.root.after(100, self.loop_function)

    def start_loop(self):
        """Запуск цикла"""
        if not self.running:
            self.running = True
            self.status_label.config(text="Status: Running")

            # Используем правильный способ получения временной зоны
            from zoneinfo import ZoneInfo
            market_timezone = ZoneInfo('Europe/Moscow')
            market_dt = datetime.now(market_timezone)

            # Проверяем статус сессии с максимальным количеством попыток
            max_attempts = 10
            attempt = 0

            while attempt < max_attempts:
                session = schedule.trade_session(market_dt)
                if session is None:
                    # Если биржа не работает, ждем до следующей сессии
                    self.add_message("Ожидание начала торговой сессии...")
                    self.root.update()  # Принудительно обновляем интерфейс
                    sleep(3)  # Ждем 3 секунды перед повторной проверкой
                    # Обновляем время перед следующей проверкой
                    market_dt = datetime.now(market_timezone)
                    attempt += 1
                else:
                    # Если биржа работает, продолжаем выполнение
                    break
            else:
                # Если не удалось начать сессию после максимального количества попыток
                self.add_message("Не удалось начать торговую сессию")
                self.status_label.config(text="Status: Session not started")
                return

            # Запускаем основной цикл в отдельном потоке для предотвращения блокировки интерфейса
            self.thread = Thread(target=self.loop_function)
            self.thread.daemon = True
            self.thread.start()

    def stop_loop(self):
        """Остановка цикла и снятие активных заявок"""
        # Сначала останавливаем цикл
        self.running = False

        # Снимаем все активные заявки
        for symbol, order_data in order_dict.items():
            if order_data['status'] == 1 and order_data['client_order_id'][
                :10] == filename:  # Активная заявка для данного файла
                # Отменяем заявку через API
                try:
                    get_cancel_order(order_data['account_id'], order_data['order_id'])
                except Exception as e:
                    self.add_message(f"Ошибка отмены заявки {order_data['order_id']}: {e}")

        # Обновляем статус в интерфейсе
        self.status_label.config(text="Status: Stopped")

    def reset(self):
        """Сброс параметров"""
        self.counter = 0
        self.counter_label.config(text=f"Счётчик сделок: {self.counter}")
        # Здесь будет ваш код сброса параметров

    def exit(self):
        global guids
        """Выход из приложения"""
        self.add_message('Отмена подписок')
        # Отписываемся от всех каналов
        if guids:  # Проверяем, есть ли подписки
            for guid in guids:
                try:
                    ap_provider.unsubscribe(guid)
                    logger.info(f'Отписка от котировок {guid} выполнена')
                    self.add_message(f'Отписка от котировок {guid} выполнена')
                    print(f'Отписка от котировок {guid} выполнена')
                except Exception as e:
                    logger.error(f'Ошибка при отписке от {guid}: {e}')
        else:
            logger.info('Нет активных подписок для отписки')
        # Отмена подписок
        self.add_message(f'\n')
        self.add_message('Отмена подписок')
        fp_provider.on_order.unsubscribe(_on_order)  # Сбрасываем обработчик заявок
        fp_provider.on_trade.unsubscribe(_on_trade)  # Сбрасываем обработчик сделок
        ap_provider.on_new_quotes.unsubscribe(_on_new_quotes)  # Отменяем подписку на события
        self.add_message('Закрываем канал перед выходом')
        fp_provider.close_channel()  # Закрываем канал перед выходом
        ap_provider.close_web_socket()  # Перед выходом закрываем соединение с WebSocket
        self.add_message("Выход из программы")
        # Добавляем небольшую задержку для отображения сообщений
        self.root.update()  # Принудительно обновляем интерфейс
        sleep(3)  # Небольшая задержка для отображения сообщений

        self.root.destroy()


lot_count_step = 0

log_filename = filename + ".log"
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  # Формат сообщения
                    datefmt='%d.%m.%Y %H:%M:%S',  # Формат даты
                    level=logging.INFO,  # Уровень логируемых событий NOTSET/DEBUG/INFO/WARNING/ERROR/CRITICAL
                    handlers=[logging.FileHandler(log_filename, encoding='utf-8'),
                              logging.StreamHandler()])  # Лог записываем в файл и выводим на консоль
logging.Formatter.converter = lambda *args: datetime.now(
    tz=fp_provider.tz_msk).timetuple()  # В логе время указываем по МСК

logger = logging.getLogger(filename)  # Будем вести лог
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
sleep(5)  # Ждем 1 секунду

# Запуск приложения
if __name__ == "__main__":
    get_portfolio_positions()
    app = App()
    app.root.mainloop()
