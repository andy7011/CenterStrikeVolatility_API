# -*- coding: utf-8 -*-
"""
01MyQuoter.py — котировщик опционной пары (Opener) на FinamPy + FinLabPy + Alor.

Схема работы:
1. Первоначально выставляются ОБЕ лимитные заявки — на продажу и на покупку.
   Каждая котируется с профитом expected_profit в единицах волатильности
   относительно противоположной стороны стакана другой ноги:
       нога на продажу: target_iv = iv(ask другой ноги) + sign(свой тип) * profit
       нога на покупку: target_iv = iv(bid другой ноги) + sign(свой тип) * profit
   sign(CALL)=+1, sign(PUT)=-1. Правило единое для пар Call-Put, Put-Call,
   Put-Put и Call-Call.
2. Заявка, исполнившаяся первой, — первичная. Встречная заявка на противоположный
   инструмент котируется от ФАКТИЧЕСКИ исполненной IV первичной ноги
   (метод Ньютона от цены сделки), поэтому профит пары фиксируется
   относительно реальной сделки, а не текущего стакана.
3. Частичные исполнения поддержаны: встречная заявка выставляется на разницу
   (исполнено первичной минус исполнено встречной), size — целые лоты.
4. Пороговые параметры (profit, timeout, indent, theor) поток движка читает
   на каждой итерации — их можно менять на ходу из GUI.
"""

import logging
import traceback
import math
import os
import pandas as pd
from collections import deque
from threading import Thread, Lock
import re
from datetime import datetime
from queue import Empty, Queue
from time import sleep
from zoneinfo import ZoneInfo

import numpy as np
import tkinter as tk
from scipy.stats import norm
from tkinter import ttk
from google.type.decimal_pb2 import Decimal

from AlorPy import AlorPy
from FinamPy import FinamPy
from FinamPy.grpc.accounts_service_pb2 import GetAccountRequest, GetAccountResponse
from FinamPy.grpc.marketdata_service_pb2 import (SubscribeQuoteResponse,
                                                 SubscribeOrderBookResponse,
                                                 SubscribeLatestTradesResponse)
from FinamPy.grpc.orders_service_pb2 import (Order, OrderState, OrderType,
                                             OrderStatus, CancelOrderRequest, OrdersRequest)
import FinamPy.grpc.side_pb2 as side

from FinLabPy.Schedule.MOEX import Futures  # Расписание торгов срочного рынка
from moex_api import get_option_board, get_option_expirations
from app.supported_base_asset import MAP

# ----------------------------------------------------------------------------
# Константы и глобальное состояние
# ----------------------------------------------------------------------------
CALL = 'C'
PUT = 'P'
r = 0  # безрисковая ставка

BUY_NUM = 1   # числовое значение направления покупки в _on_order
SELL_NUM = 2  # числовое значение направления продажи в _on_order

app_instance = None
account_id = '1218884'

filename = os.path.splitext(os.path.basename(__file__))[0]
file_type = filename[4:10]  # 'Quoter'
print(file_type)

dataname_sell = ''
dataname_buy = ''
base_asset_ticker = ''

# --- пороговые параметры, изменяемые на ходу из GUI ---
expected_profit = 2.0   # профит в п.п. волатильности
lot_count = 1           # число циклов пар
basket_size = 1         # лотов в каждой заявке
timeout = 1             # пауза цикла, сек
indent = 0              # сдвиг лимитной цены в шагах цены (продажа: '-', покупка: '+')
theor_flag = False      # не котировать ближе теоретической разницы IV

# --- данные ---
expiration_dates = []
sell_tickers_call = []
sell_tickers_put = []
dataname_base_asset_ticker_old = ''
dataname_guid_sell_old = ''
dataname_guid_buy_old = ''
subscriptions_dict = {}
options_data = {}

new_quotes = {}
order_dict = {}
trade_dict = {}

_account_data = [{
    'positions': {},
    'cash': {},
    'equity': 0.0,
    'unrealized_profit': 0.0,
    'portfolio_type': ''
}]

# --- состояние движка ---
running = False
trade_counter = 0
msg_queue = Queue()

_order_seq = 0

engine = None

# Каталог data/Finam с CSV-файлами
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR_FINAM = os.path.join(BASE_DIR, "data", "Finam")
TRADES_CSV = os.path.join(DATA_DIR_FINAM, "Finam_Stream_Trades_ALL.csv")

TRADES_COLUMNS = ['datetime', 'trade_id', 'order_id', 'option_base', 'ticker',
                  'option_type', 'strike', 'expdate', 'operation', 'volume',
                  'price', 'value', 'volatility']

_trades_lock = Lock()
_trades_df_cache = pd.DataFrame(columns=TRADES_COLUMNS)  # активные сделки: CSV + свежие из потока
_stream_trades = []                                      # сделки из потока, ещё не попавшие в CSV
_no_trades_warned = set()


def next_client_order_id():
    """Уникальный client_order_id НЕ ДЛИНЕЕ 20 символов (ограничение Finam):
    имя файла (до 10) + младшие 32 бита мс (8 hex) + счётчик (2 цифры)."""
    global _order_seq
    _order_seq += 1
    ms = int(datetime.now().timestamp() * 1000)
    return f'{filename[:10]}{ms & 0xFFFFFFFF:08X}{_order_seq % 100:02d}'


# ----------------------------------------------------------------------------
# Обработчики стрим-подписок Finam
# ----------------------------------------------------------------------------
def utc_to_msk_datetime(dt, tzinfo=False):
    """Перевод времени из UTC в московское"""
    dt_utc = datetime.fromtimestamp(dt.timestamp())
    return dt_utc


def _on_account_info(account_response):
    """Обработчик информации об аккаунте из стрим-подписки"""
    data = _account_data[0]

    if not account_response:
        return
    if not hasattr(account_response, 'positions'):
        return

    if hasattr(account_response, 'account_id'):
        data['account_id'] = account_response.account_id
    if hasattr(account_response, 'status'):
        data['status'] = account_response.status

    if hasattr(account_response, 'equity') and account_response.equity:
        data['equity'] = float(account_response.equity.value) if account_response.equity.value else 0.0
    if hasattr(account_response, 'unrealized_profit') and account_response.unrealized_profit:
        data['unrealized_profit'] = float(
            account_response.unrealized_profit.value) if account_response.unrealized_profit.value else 0.0

    data['cash'] = {}
    if hasattr(account_response, 'cash'):
        for money_item in account_response.cash:
            currency = money_item.currency_code if money_item.currency_code else 'RUB'
            amount = float(money_item.units) + float(money_item.nanos) / 1_000_000_000 if money_item.units else 0.0
            data['cash'][currency] = {'balance': amount, 'blocked': 0.0, 'free': amount}

    if hasattr(account_response, 'portfolio_forts') and account_response.HasField('portfolio_forts'):
        data['portfolio_type'] = 'FORTS'
        forts = account_response.portfolio_forts
        data['margin'] = {
            'available_cash': float(forts.available_cash.value) if forts.available_cash else 0.0,
            'money_reserved': float(forts.money_reserved.value) if forts.money_reserved else 0.0,
        }
        data['cash']['RUB'] = {
            'balance': float(forts.available_cash.value) if forts.available_cash else 0.0,
            'blocked': float(forts.money_reserved.value) if forts.money_reserved else 0.0,
            'free': float(forts.available_cash.value) if forts.available_cash else 0.0,
        }
    elif hasattr(account_response, 'portfolio_mc') and account_response.HasField('portfolio_mc'):
        data['portfolio_type'] = 'MC'
        mc = account_response.portfolio_mc
        data['margin'] = {
            'available_cash': float(mc.available_cash.value) if mc.available_cash else 0.0,
            'initial_margin': float(mc.initial_margin.value) if mc.initial_margin else 0.0,
            'maintenance_margin': float(mc.maintenance_margin.value) if mc.maintenance_margin else 0.0,
        }
    elif hasattr(account_response, 'portfolio_mct') and account_response.HasField('portfolio_mct'):
        data['portfolio_type'] = 'MCT'
        mct = account_response.portfolio_mct
        data['margin'] = {
            'available_cash': float(mct.available_cash.value) if mct.available_cash else 0.0,
            'initial_margin': float(mct.initial_margin.value) if mct.initial_margin else 0.0,
            'maintenance_margin': float(mct.maintenance_margin.value) if mct.maintenance_margin else 0.0,
        }

    data['positions'] = {}
    for position in account_response.positions:
        try:
            symbol = position.symbol if hasattr(position, 'symbol') else 'UNKNOWN'
            quantity = 0.0
            if hasattr(position, 'quantity') and position.quantity and position.quantity.value:
                quantity = float(position.quantity.value)
            current_price = 0.0
            if hasattr(position, 'current_price') and position.current_price and position.current_price.value:
                current_price = float(position.current_price.value)
            average_price = 0.0
            if hasattr(position, 'average_price') and position.average_price and position.average_price.value:
                average_price = float(position.average_price.value)
            maintenance_margin = 0.0
            if hasattr(position, 'maintenance_margin') and position.maintenance_margin and position.maintenance_margin.value:
                maintenance_margin = float(position.maintenance_margin.value)
            daily_pnl = 0.0
            if hasattr(position, 'daily_pnl') and position.daily_pnl and position.daily_pnl.value:
                daily_pnl = float(position.daily_pnl.value)
            unrealized_pnl = 0.0
            if hasattr(position, 'unrealized_pnl') and position.unrealized_pnl and position.unrealized_pnl.value:
                unrealized_pnl = float(position.unrealized_pnl.value)
            data['positions'][symbol] = {
                'quantity': quantity,
                'current_price': current_price,
                'average_price': average_price,
                'maintenance_margin': maintenance_margin,
                'daily_pnl': daily_pnl,
                'unrealized_pnl': unrealized_pnl,
            }
        except Exception as e:
            logger.error(f'Ошибка при парсинге позиции: {e}')


def _to_float(v):
    """Числовое поле proto-Decimal: значение приходит строкой, пустое -> 0.0."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _on_order(order):
    logger.info(f'Заявка - {order}')
    order_dict[order.order.symbol] = {
        'order_id': order.order_id,
        'exec_id': order.exec_id,
        'status': order.status,
        'account_id': order.order.account_id,
        'quantity': _to_float(order.order.quantity.value),
        'side': order.order.side,
        'type': order.order.type,
        'time_in_force': order.order.time_in_force,
        'limit_price': _to_float(order.order.limit_price.value),
        'client_order_id': order.order.client_order_id,
        'transact_at': order.transact_at,
        'initial_quantity': _to_float(order.initial_quantity.value),
        'executed_quantity': _to_float(order.executed_quantity.value),
        'remaining_quantity': _to_float(order.remaining_quantity.value),
    }


def _on_trade(trade):
    """Накопительная запись сделок: по каждой заявке собираем все частичные
    исполнения (size — целые лоты) и средневзвешенную цену."""
    logger.info(f'Сделка - {trade}')
    order_id = trade.order_id
    size = int(trade.size.value)
    price = float(trade.price.value)

    entry = trade_dict.get(order_id)
    if entry is None:
        entry = {'trades': [], 'filled_qty': 0, 'price_sum': 0.0, 'last_price': price,
                 'last_timestamp': trade.timestamp}
        trade_dict[order_id] = entry

    entry['trades'].append({
        'trade_id': trade.trade_id,
        'timestamp': trade.timestamp,
        'side': trade.side,
        'size': size,
        'price': price,
    })
    entry['filled_qty'] += size
    entry['price_sum'] += price * size
    entry['last_price'] = price
    entry['last_timestamp'] = trade.timestamp

    _register_trade(trade, size, price)

    if app_instance is not None:
        msg_queue.put(('msg', f'Сделка: заявка {order_id}: {trade.side} {size} лотов по {price}'))


def fill_info(order_id):
    """(накопленный объём, средневзвешенная цена) по заявке или None."""
    entry = trade_dict.get(order_id)
    if entry is None or entry['filled_qty'] <= 0:
        return None
    return entry['filled_qty'], entry['price_sum'] / entry['filled_qty']


# ----------------------------------------------------------------------------
# Подписки на котировки
# ----------------------------------------------------------------------------
def _on_new_quotes(quote: SubscribeQuoteResponse):
    """Единый обработчик котировок для всех инструментов.
    Обновление инкрементальное: пустые поля (0 / None) не затирают
    предыдущие значения — частичный тик не обнуляет last_price."""
    if len(quote.quote) > 0:
        quote_data = quote.quote[0]
        symbol = quote_data.symbol
        description = symbol.split('@')[0] if '@' in symbol else symbol

        ask = float(quote_data.ask.value) if quote_data.ask and quote_data.ask.value else 0.0
        ask_size = float(quote_data.ask_size.value) if quote_data.ask_size and quote_data.ask_size.value else 0.0
        bid = float(quote_data.bid.value) if quote_data.bid and quote_data.bid.value else 0.0
        bid_size = float(quote_data.bid_size.value) if quote_data.bid_size and quote_data.bid_size.value else 0.0
        last_price = float(quote_data.last.value) if quote_data.last and quote_data.last.value else 0.0

        implied_volatility = None
        theoretical_price = None
        if quote_data.HasField('option'):
            option_data = quote_data.option
            if option_data.implied_volatility and option_data.implied_volatility.value:
                implied_volatility = float(option_data.implied_volatility.value)
            if option_data.theoretical_price and option_data.theoretical_price.value:
                theoretical_price = float(option_data.theoretical_price.value)

        if description in new_quotes:
            entry = new_quotes[description]
            if implied_volatility is not None:
                entry['implied_volatility'] = implied_volatility
            if theoretical_price is not None:
                entry['theoretical_price'] = theoretical_price
            if ask:
                entry['ask'] = ask
                entry['ask_vol'] = ask_size
            if bid:
                entry['bid'] = bid
                entry['bid_vol'] = bid_size
            if last_price:
                entry['last_price'] = last_price
        else:
            if implied_volatility is None:
                implied_volatility = 0.0
            if theoretical_price is None:
                theoretical_price = 0.0
            if ask == 0.0 and bid == 0.0 and last_price == 0.0:
                logger.warning(f'Пропущен некорректный ответ для нового тикера {description}')
                return
            new_quotes[description] = {
                'ask': ask,
                'ask_vol': ask_size,
                'bid': bid,
                'bid_vol': bid_size,
                'last_price': last_price,
                'implied_volatility': implied_volatility,
                'theoretical_price': theoretical_price
            }


def subscribe_instrument(dataname):
    """Подписка на котировки инструмента через Финам"""
    try:
        finam_board, ticker = fp_provider.dataname_to_finam_board_ticker(dataname)
        mic = fp_provider.get_mic(finam_board, ticker)

        thread_name = f'QuoteThread_{ticker}'
        quote_thread = Thread(target=fp_provider.subscribe_quote_thread,
                              name=thread_name,
                              args=((f'{ticker}@{mic}',),))
        quote_thread.daemon = True
        quote_thread.start()

        subscriptions_dict[dataname] = {
            'ticker': ticker,
            'mic': mic,
            'thread': quote_thread,
            'thread_name': thread_name
        }
        logger.info(f'Подписка на котировки {dataname} ({ticker}@{mic}) создана')
        return True
    except Exception as e:
        logger.error(f'Ошибка подписки на {dataname}: {e}')
        return False


def unsubscribe_instrument(dataname):
    """Отписка от котировок конкретного инструмента"""
    if dataname in subscriptions_dict:
        try:
            del subscriptions_dict[dataname]
            logger.info(f'Отписка от котировок {dataname} выполнена')
            return True
        except Exception as e:
            logger.error(f'Ошибка отписки от {dataname}: {e}')
            return False
    return False


def unsubscribe_all():
    """Отписка от всех котировок (вызывается при выходе)"""
    for dataname in list(subscriptions_dict.keys()):
        unsubscribe_instrument(dataname)
    logger.info('Отписка от всех котировок завершена')
    subscriptions_dict.clear()


# ----------------------------------------------------------------------------
# Данные опционов (Alor) и расчёты
# ----------------------------------------------------------------------------
def get_option_data_alor(dataname):
    """Получаем данные по опциону из Alor, сохраняем в options_data[dataname]."""
    global options_data
    alor_board, symbol = ap_provider.dataname_to_alor_board_symbol(dataname)
    exchange = ap_provider.get_exchange(alor_board, symbol)
    si = ap_provider.get_symbol_info(exchange, symbol)
    if not isinstance(si, dict):
        logger.error(f'Alor get_symbol_info вернул не словарь: {si!r} для {exchange}/{symbol}')
        return options_data

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
    logger.info(f'Данные Alor по {dataname}: {options_data[dataname]}')
    return options_data


def _parse_expiration(end_expiration):
    """Парсинг endExpiration из Alor в datetime. Доли секунды обрезаем до 6 знаков:
    Alor присылает 7 ("2026-11-19T00:00:00.0000000"), а %f принимает максимум 6."""
    if isinstance(end_expiration, datetime):
        return end_expiration
    s = str(end_expiration).strip()
    s = re.sub(r'(\.\d{6})\d+', r'\1', s)   # .0000000 -> .000000
    for fmt in ('%Y-%m-%dT%H:%M:%S.%f%z', '%Y-%m-%dT%H:%M:%S%z',
                '%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S',
                '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(f'Не удалось распознать дату экспирации: {end_expiration}')


def get_option_data_for_calc_price(dataname):
    """(S, K, T, opt_type) для Блэка–Шоулза: S — цена базового актива из потока
    котировок, K — страйк, T — время до экспирации в долях года."""
    info = options_data[dataname]
    K = info['strikePrice']
    opt_type = CALL if info['optionSide'] == 'Call' else PUT
    exp_dt = _parse_expiration(info['endExpiration'])
    now = datetime.now(exp_dt.tzinfo) if exp_dt.tzinfo else datetime.now()
    T = max((exp_dt - now).total_seconds() / (365 * 24 * 3600), 1 / (365 * 24 * 3600))
    # Цена базового актива: подписка на БА создана в on_base_asset_change
    q = new_quotes.get(base_asset_ticker)
    S = q['last_price'] if q and q.get('last_price') else None
    if S is None:
        raise ValueError(f'Нет цены базового актива {base_asset_ticker} для {dataname}')
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


# Расчет IV Метод Ньютона для опциона CALL
def newton_vol_call(S, K, T, C, r, sigma):
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
        if abs(vega) < 1e-10:
            break
        xnew = xnew - fx / vega
        iteration += 1
    return abs(xnew)


def round_step(price, step, decimals):
    """Округление цены вниз к шагу цены (как в 03MyCloser)."""
    return int(round((price // step) * step, decimals))


def opt_type_of(dataname):
    return CALL if options_data[dataname]['optionSide'] == 'Call' else PUT


def sign_of(opt_type):
    """Знак оффсета: CALL +1, PUT -1."""
    return 1 if opt_type == CALL else -1


def _sigma_of(dataname):
    """Рабочая IV инструмента: из потока котировок, иначе из Alor."""
    ticker = options_data[dataname]['ticker']
    q = new_quotes.get(ticker)
    if q and q.get('implied_volatility'):
        return q['implied_volatility'] / 100
    return options_data[dataname]['volatility'] / 100


def leg_market(dataname):
    """(ask, bid, ask_iv, bid_iv, theor_iv) по ноге или None, если котировок нет."""
    ticker = options_data[dataname]['ticker']
    q = new_quotes.get(ticker)
    if q is None or not q.get('ask') or not q.get('bid'):
        return None
    S, K, T, opt_type = get_option_data_for_calc_price(dataname)
    sigma = _sigma_of(dataname)
    newton = newton_vol_call if opt_type == CALL else newton_vol_put
    ask, bid = q['ask'], q['bid']
    ask_iv = newton(S, K, T, ask, r, sigma) * 100
    bid_iv = newton(S, K, T, bid, r, sigma) * 100
    theor_iv = q.get('implied_volatility') or 0.0
    return ask, bid, ask_iv, bid_iv, theor_iv


def leg_iv(dataname, price):
    """IV по цене сделки ноги (метод Ньютона)."""
    S, K, T, opt_type = get_option_data_for_calc_price(dataname)
    sigma = _sigma_of(dataname)
    newton = newton_vol_call if opt_type == CALL else newton_vol_put
    return newton(S, K, T, price, r, sigma) * 100


def positions_quantity(dataname):
    """Количество лотов позиции по тикеру опциона (со знаком)."""
    ticker = dataname.split('.')[1]
    for symbol in _account_data[0]['positions']:
        if ticker == symbol.split('@')[0]:
            try:
                return int(float(_account_data[0]['positions'][symbol]['quantity']))
            except (IndexError, TypeError, ValueError):
                return 0
    return 0

class Entry:
    """Позиция в инвентаре FIFO: количество (со знаком) и значение (цена/IV)."""
    __slots__ = ('quantity', 'price')

    def __init__(self, quantity, price):
        self.quantity = quantity
        self.price = price


class FIFO:
    """Учёт позиций по FIFO: входы закрывают противоположные по знаку записи
    инвентаря, остаток хранится в self.inventory (deque из Entry)."""

    def __init__(self, entries):
        self.inventory = deque()
        for e in entries:
            q, p = e.quantity, e.price
            if q == 0 or p is None or (isinstance(p, float) and math.isnan(p)):
                continue
            if q > 0:
                while q > 0 and self.inventory and self.inventory[0].quantity < 0:
                    first = self.inventory[0]
                    if first.quantity + q <= 0:
                        q += first.quantity
                        self.inventory.popleft()
                    else:
                        first.quantity += q
                        q = 0
                if q > 0:
                    self.inventory.append(Entry(q, p))
            else:
                while q < 0 and self.inventory and self.inventory[0].quantity > 0:
                    first = self.inventory[0]
                    if first.quantity + q >= 0:
                        first.quantity += q
                        q = 0
                    else:
                        q += first.quantity
                        self.inventory.popleft()
                if q < 0:
                    self.inventory.append(Entry(q, p))


def calculate_weighted_average(inventory):
    """Средневзвешенное значение по инвентарю FIFO (deque из Entry)."""
    weighted_sum = sum(entry.quantity * entry.price for entry in inventory)
    total_weight = sum(entry.quantity for entry in inventory)
    return weighted_sum / total_weight if total_weight != 0 else 0


def calculate_open_data_open_price_open_iv(sec_code, net_pos, trades_df=None):
    """Дата открытия, средневзвешенная цена и IV позиции по FIFO сделок.
    Позиции переживают перезапуск: сначала активные сделки, затем полная история."""
    try:
        if trades_df is None:
            trades_df = get_trades_df()
        instrument_trades_df = trades_df[trades_df['ticker'] == sec_code].copy()

        if instrument_trades_df.empty:
            all_df = get_trades_all_df()
            instrument_trades_df = all_df[all_df['ticker'] == sec_code].copy()
        if instrument_trades_df.empty:
            if sec_code not in _no_trades_warned:
                _no_trades_warned.add(sec_code)
                logger.warning(f"Предупреждение: Нет данных для инструмента {sec_code}")
            return None, None, None

        instrument_trades_df['datetime'] = pd.to_datetime(
            instrument_trades_df['datetime'], format='%d.%m.%Y %H:%M:%S')
        instrument_trades_df = instrument_trades_df.sort_values('datetime', ascending=False)
        instrument_trades_df.loc[instrument_trades_df['operation'] == 'Продажа', 'volume'] *= -1

        required_volume = net_pos
        sign = 1 if required_volume > 0 else -1
        selected_trades = []
        for _, trade in instrument_trades_df.iterrows():
            volume = trade['volume']
            if sign * (required_volume - volume) >= 0:
                selected_trades.append(trade)
                required_volume -= volume
            else:
                partial_trade = trade.copy()
                partial_trade['volume'] = required_volume
                selected_trades.append(partial_trade)
                required_volume = 0
                break

        if not selected_trades:
            sum_volume_short = instrument_trades_df.loc[
                instrument_trades_df['operation'] == 'Продажа', 'volume'].sum()
            count_short = (instrument_trades_df['operation'] == 'Продажа').sum()
            sum_volume_long = instrument_trades_df.loc[
                instrument_trades_df['operation'] == 'Купля', 'volume'].sum()
            count_long = (instrument_trades_df['operation'] == 'Купля').sum()
            logger.warning(f"Предупреждение: Недостаточно сделок для инструмента {sec_code}")
            logger.warning(f"Позиция: {net_pos}")
            logger.warning(f"Сделок лонг: {count_long} Объем: {sum_volume_long}")
            logger.warning(f"Сделок шорт: {count_short} Объем: {sum_volume_short}")
            return None, None, None

        selected_df = pd.DataFrame(selected_trades)
        OpenDateTime = selected_df.iloc[-1]['datetime'].strftime('%d.%m.%Y %H:%M:%S')

        selected_trades = [t for t in selected_trades if (t['volume'] > 0) == (net_pos > 0)]

        fifo_entries = [Entry(t['volume'], t['price']) for t in selected_trades]
        fifo_entries_vol = [Entry(t['volume'], t['volatility']) for t in selected_trades]

        OpenPrice = calculate_weighted_average(FIFO(fifo_entries).inventory)
        OpenIV = calculate_weighted_average(FIFO(fifo_entries_vol).inventory)
        return OpenDateTime, OpenPrice, OpenIV

    except Exception as e:
        logger.error(f"Ошибка при вычислении данных открытия для {sec_code}: {e}")
        return None, None, None

def _normalize_trades_df(df):
    df = df.copy()
    if df.empty:
        return df
    df['datetime'] = pd.to_datetime(df['datetime'], format='%d.%m.%Y %H:%M:%S', errors='coerce')
    for column in ['strike', 'volume', 'price', 'value', 'volatility']:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors='coerce')
    return df


def refresh_trades():
    """Перечитывает CSV в кэш активных сделок и добавляет сделки из потока,
    которых в файле ещё нет (дедупликация по trade_id). При ошибке чтения
    (файл занят записью другой программы) оставляет прежний кэш."""
    global _trades_df_cache
    try:
        df = pd.read_csv(TRADES_CSV, sep=';', encoding='utf-8')
    except FileNotFoundError:
        df = pd.DataFrame(columns=TRADES_COLUMNS)
    except (PermissionError, OSError) as e:
        logger.warning(f'CSV занят, используем прежний кэш: {e}')
        return
    except Exception as e:
        logger.error(f'Ошибка чтения {TRADES_CSV}: {e}')
        return
    df = _normalize_trades_df(df)
    with _trades_lock:
        known = set(df['trade_id'].astype(str)) if 'trade_id' in df.columns else set()
        fresh = [r for r in _stream_trades if str(r['trade_id']) not in known]
        _stream_trades.clear()          # добавленные сейчас или отфильтрованные — больше не нужны
        if fresh:
            extra = _normalize_trades_df(pd.DataFrame(fresh, columns=TRADES_COLUMNS))
            if not extra.empty:
                df = pd.concat([df, extra], ignore_index=True)
        _trades_df_cache = df
    logger.debug(f'История сделок обновлена: {len(_trades_df_cache)} записей')


def get_trades_df():
    """DataFrame активных сделок: содержимое CSV + свежие сделки из потока."""
    with _trades_lock:
        return _trades_df_cache.copy()


def get_trades_all_df():
    """Полная история — тот же источник (CSV ведёт внешняя программа)."""
    return get_trades_df()


def open_iv_safe(dataname, pos):
    """IV открытой позиции по опциону или 0, если позиции нет.
    Знак pos передаётся как есть: отрицательная позиция — шорт, FIFO учитывает это."""
    if not pos:
        return 0
    ticker = dataname.split('.')[1]
    try:
        return float(calculate_open_data_open_price_open_iv(ticker, pos)[2])
    except (IndexError, TypeError, ValueError):
        return 0


def _trade_datetime(ts):
    """Время сделки в формате CSV ('д.м.ГГГГ ЧЧ:ММ:СС')."""
    if hasattr(ts, 'seconds'):
        return datetime.fromtimestamp(ts.seconds + getattr(ts, 'nanos', 0) / 1e9) \
            .strftime('%d.%m.%Y %H:%M:%S')
    if isinstance(ts, datetime):
        return ts.strftime('%d.%m.%Y %H:%M:%S')
    return datetime.now().strftime('%d.%m.%Y %H:%M:%S')


def _register_trade(trade, size, price):
    """Сделка из потока Finam -> в кэш активных сделок + перечитывание CSV."""
    try:
        symbol = next((sym for sym, o in order_dict.items()
                       if o.get('order_id') == trade.order_id), None)
        ticker = symbol.split('@')[0] if symbol else ''
        dataname = next((d for d, v in options_data.items() if v['ticker'] == ticker), None)
        info = options_data.get(dataname, {})
        vol = None
        if dataname is not None:
            try:
                vol = round(leg_iv(dataname, price), 2)
            except Exception:
                vol = None
        expdate = ''
        if info.get('endExpiration'):
            try:
                expdate = _parse_expiration(info['endExpiration']).strftime('%d.%m.%Y')
            except ValueError:
                pass
        row = {
            'datetime': _trade_datetime(trade.timestamp),
            'trade_id': str(trade.trade_id),
            'order_id': str(trade.order_id),
            'option_base': info.get('base_asset_ticker', ''),
            'ticker': ticker,
            'option_type': 'C' if info.get('optionSide', '') == 'Call'
                           else ('P' if info.get('optionSide', '') == 'Put' else ''),
            'strike': info.get('strikePrice', ''),
            'expdate': expdate,
            'operation': 'Купля' if trade.side == side.SIDE_BUY else 'Продажа',
            'volume': size,
            'price': price,
            'value': price * size,
            'volatility': vol if vol is not None else 0.0,
        }
        with _trades_lock:
            _stream_trades.append(row)
        refresh_trades()  # CSV уже мог обновиться другой программой — подхватим
    except Exception as e:
        logger.error(f'Ошибка регистрации сделки в истории: {e}')

# ----------------------------------------------------------------------------
# Блок 5. Заявки и утилиты состояния
# ----------------------------------------------------------------------------
def place_order(side_dir, symbol, quantity, limit_price):
    try:
        st = fp_provider.call_function(
            fp_provider.orders_stub.PlaceOrder,
            Order(account_id=account_id, symbol=symbol,
                  quantity=Decimal(value=str(quantity)), side=side_dir,
                  type=OrderType.ORDER_TYPE_LIMIT,
                  limit_price=Decimal(value=str(limit_price)),
                  client_order_id=next_client_order_id()))
        if st is None:
            logger.error('PlaceOrder вернул None')
            return None
        logger.info(f'Заявка {st.order_id} статус {st.status}')
        return st.order_id
    except Exception as e:
        logger.error(f'Ошибка размещения заявки: {e}')
        return None


def get_cancel_order(account_id_, order_id):
    st = fp_provider.call_function(fp_provider.orders_stub.CancelOrder,
                                   CancelOrderRequest(account_id=account_id_, order_id=order_id))
    logger.info(f'Отмена заявки {order_id}, статус {st.status}')
    return st.status


def active_order(symbol, side_dir):
    """Активная заявка: статус NEW или PARTIALLY_FILLED (или на пути к ним),
    объём не исполнен полностью."""
    o = order_dict.get(symbol)
    if o is None or o['side'] != side_dir or o['remaining_quantity'] <= 0:
        return None
    if o['status'] in (OrderStatus.ORDER_STATUS_NEW,
                       OrderStatus.ORDER_STATUS_PARTIALLY_FILLED,
                       OrderStatus.ORDER_STATUS_PENDING_NEW,
                       OrderStatus.ORDER_STATUS_WAIT):
        return o
    return None


def cancel_active(symbol, side_dir):
    o = active_order(symbol, side_dir)
    if o:
        try:
            get_cancel_order(account_id, o['order_id'])
            return o['order_id']
        except Exception as e:
            logger.error(f'Ошибка отмены заявки: {e}')
    return None


def build_legs():
    """Словарь ног {'sell': {...}, 'buy': {...}}. Доступ по ключам:
    legs['sell'], legs['buy'] — НЕ распаковывать в переменные, ключи станут строками."""
    if dataname_sell not in options_data or dataname_buy not in options_data:
        raise ValueError(f'Нет данных опционов: sell={dataname_sell!r}, buy={dataname_buy!r}')
    legs = {}
    for name, dataname in (('sell', dataname_sell), ('buy', dataname_buy)):
        info = options_data[dataname]
        legs[name] = {
            'dataname': dataname,
            'symbol': f"{info['ticker']}@RTSX",
            'side': side.SIDE_SELL if name == 'sell' else side.SIDE_BUY,
            'step': int(float(info['minstep'])),
            'decimals': int(info['decimals']),
            'opt_type': opt_type_of(dataname),
            'order_id': None,
            'order_ids': [],
            'price_old': None,
            'qty_placed': 0,
            'logged': 0,
        }
    return legs


# ----------------------------------------------------------------------------
# Блок 6. Движок: обе заявки → встречная от исполненной IV
# ----------------------------------------------------------------------------
def initial_offset(own, other, own_side):
    """Оффсет в п.п. IV для фазы обеих заявок. При отрицательном профите котируем
    агрессивнее рынка (продажа ниже, покупка выше). При флаге Theor оффсет
    ограничивается теоретической разницей IV: для положительного профита —
    не меньше неё, для отрицательного — не больше неё."""
    s = sign_of(opt_type_of(own))
    if theor_flag:
        theo = s * (new_quotes[options_data[own]['ticker']]['implied_volatility']
                    - new_quotes[options_data[other]['ticker']]['implied_volatility'])
        if expected_profit >= 0:
            return s * max(expected_profit, theo)
        return s * min(expected_profit, theo)
    return s * expected_profit


def counter_target_iv(lead_dataname, lead_fill_price, lag_dataname):
    try:
        fill_iv = leg_iv(lead_dataname, lead_fill_price)
        s = sign_of(opt_type_of(lag_dataname))
        off = s * expected_profit

        if theor_flag:
            m = leg_market(lag_dataname)
            if m is None:
                raise ValueError("Нет рыночных данных для расчета")

            max_off = abs(m[4] - fill_iv)
            if max_off == 0:
                raise ValueError("Нулевое значение теоретической разницы")

            if abs(off) > max_off:
                off = math.copysign(max_off, off)

        return fill_iv + off

    except Exception as e:
        logger.error(f"Ошибка расчета целевой IV: {e}")
        return None


class QuoterEngine:
    def __init__(self, legs):
        self.legs = legs
        self.counter = 0

    def say(self, text): msg_queue.put(('msg', str(text)))
    def set_led(self, color): msg_queue.put(('led', color))
    def set_status(self, text): msg_queue.put(('status', text))

    def session_active(self):
        try:
            return schedule.trade_session(datetime.now(ZoneInfo('Europe/Moscow'))) is not None
        except Exception:
            return True

    def wait_session(self):
        market_dt = datetime.now(ZoneInfo('Europe/Moscow'))
        attempt = 0
        while attempt < 10 and running:
            session = schedule.trade_session(market_dt)
            if session is None:
                self.say('Ожидание начала торговой сессии...')
                sleep(3)
                market_dt = datetime.now(ZoneInfo('Europe/Moscow'))
                attempt += 1
            else:
                self.say(f'Торговая сессия: {session.time_begin} - {session.time_end}')
                return True
        return False

    def cleanup(self):
        for leg in self.legs.values():
            if leg['order_id'] is not None:
                try:
                    get_cancel_order(account_id, leg['order_id'])
                    self.say(f'Заявка {leg["symbol"]} снята: {leg["order_id"]}')
                except Exception as e:
                    logger.error(f'Ошибка отмены заявки: {e}')
            leg['order_id'] = None
            leg['price_old'] = None
            leg['qty_placed'] = 0

    def leg_filled(self, leg):
        """Суммарное исполнение по всем заявкам ноги: (лоты, средневзвешенная цена)."""
        total, price_sum = 0, 0.0
        for oid in leg['order_ids']:
            fi = fill_info(oid)
            if fi:
                total += fi[0]
                price_sum += fi[0] * fi[1]
        return (total, price_sum / total) if total > 0 else None

    def log_new_trades(self):
        for leg_name, leg in self.legs.items():
            for oid in leg['order_ids']:
                entry = trade_dict.get(oid)
                if not entry:
                    continue
                while len(entry['trades']) > leg.get('logged', 0):
                    t = entry['trades'][leg['logged']]
                    leg['logged'] += 1
                    self.say(f"Сделка {leg_name.upper()} {leg['symbol']}: "
                             f"{t['side']} {t['size']} лотов по {t['price']}")

    def compute_targets(self):
        m_sell, m_buy = leg_market(dataname_sell), leg_market(dataname_buy)
        if m_sell is None or m_buy is None:
            return None
        ask_sell, bid_sell, ask_iv_sell, bid_iv_sell, theor_iv_sell = m_sell
        ask_buy, bid_buy, ask_iv_buy, bid_iv_buy, theor_iv_buy = m_buy
        # Продажа котируется от ask покупаемой ноги, покупка — от bid продаваемой
        off_sell = initial_offset(dataname_sell, dataname_buy, 'sell')
        off_buy = initial_offset(dataname_buy, dataname_sell, 'buy')
        tiv_sell = ask_iv_buy + off_sell
        tiv_buy = bid_iv_sell + off_buy
        sell_leg, buy_leg = self.legs['sell'], self.legs['buy']
        Ss, Ks, Ts, _ = get_option_data_for_calc_price(dataname_sell)
        Sb, Kb, Tb, _ = get_option_data_for_calc_price(dataname_buy)
        tp_sell = round_step(option_price(Ss, tiv_sell / 100, Ks, Ts, r, sell_leg['opt_type']),
                             sell_leg['step'], sell_leg['decimals'])
        tp_buy = round_step(option_price(Sb, tiv_buy / 100, Kb, Tb, r, buy_leg['opt_type']),
                            buy_leg['step'], buy_leg['decimals'])
        return {'sell_ask': ask_sell, 'sell_bid': bid_sell, 'buy_ask': ask_buy, 'buy_bid': bid_buy,
                'target_price_sell': tp_sell, 'target_iv_sell': tiv_sell,
                'target_price_buy': tp_buy, 'target_iv_buy': tiv_buy,
                'diff': round(theor_iv_sell - theor_iv_buy, 2)}

    def maintain_leg(self, leg_name, tg, qty):
        """Реквот ноги фазы 1. Решение принимаем по собственному учёту
        (leg['order_id'], leg['price_old']), а не по order_dict — иначе можно
        снять свежевыставленную заявку, пока событие по ней ещё в пути."""
        leg = self.legs[leg_name]
        limit_price = tg['target_price_sell'] if leg_name == 'sell' else tg['target_price_buy']
        limit_price += -leg['step'] * indent if leg_name == 'sell' else leg['step'] * indent
        market_ref = tg['sell_ask'] if leg_name == 'sell' else tg['buy_bid']

        fi = self.leg_filled(leg)                    # исполнение проверяем ДО отмены
        if fi is not None:
            return 'filled' if fi[0] >= qty else 'partial'

        if limit_price > market_ref if leg_name == 'sell' else limit_price < market_ref:
            if leg['order_id'] is not None:          # вне спреда — снимаем и ждём
                self.cancel_leg(leg_name)
            return 'skip'

        if leg['order_id'] is not None:
            if leg['price_old'] == limit_price and leg['qty_placed'] == qty:
                return 'keep'                        # цена не изменилась — не трогаем
            self.cancel_leg(leg_name)                # цена изменилась — переквот
            new_id = self._requote(leg, qty, limit_price, leg_name)
            return 'placed' if new_id is not None else 'error'

        # Приём "потерянной" заявки: своя нет, а в order_dict активная наша есть
        active = active_order(leg['symbol'], leg['side'])
        if active is not None and str(active['client_order_id']).startswith(filename):
            leg['order_id'] = active['order_id']
            leg['price_old'] = float(active['limit_price'])
            leg['qty_placed'] = int(float(active['remaining_quantity']))
            leg['order_ids'].append(leg['order_id'])
            self.say(f"Найдена активная заявка {leg_name.upper()} {leg['order_id']}")
            return 'keep'

        new_id = self._requote(leg, qty, limit_price, leg_name)
        return 'placed' if new_id is not None else 'error'

    def _requote(self, leg, qty, limit_price, leg_name):
        if not running:
            return None
        new_id = place_order(leg['side'], leg['symbol'], qty, limit_price)
        if new_id is None:
            self.set_led('red')
            self.say(f'НЕ выставлена заявка {leg_name.upper()} {leg["symbol"]}: '
                     f'{limit_price} x{qty} — причина в консоли')
            return None
        leg['order_id'] = new_id
        leg['order_ids'].append(new_id)
        leg['price_old'] = limit_price
        leg['qty_placed'] = qty
        self.set_led('lightgreen')
        self.say(f"Заявка {leg_name.upper()} {leg['symbol']}: {limit_price} x{qty}")
        return new_id

    def cancel_leg(self, leg_name):
        leg = self.legs[leg_name]
        if leg['order_id'] is not None:
            try:
                get_cancel_order(account_id, leg['order_id'])
                self.say(f'Заявка {leg_name.upper()} снята: {leg["order_id"]}')
            except Exception as e:
                logger.error(f'Ошибка отмены заявки: {e}')
        leg['order_id'] = None
        leg['price_old'] = None
        leg['qty_placed'] = 0

    def run(self):
        global running, trade_counter
        running = True
        self.set_led('yellow')
        self.set_status('Running')
        if not self.wait_session():
            self.finish()
            return
        while running and self.counter < lot_count:
            try:
                done = self.run_pair()
            except Exception as e:
                logger.error(f'Ошибка в цикле пары: {e}')
                logger.error(traceback.format_exc())
                self.say(f'Ошибка в цикле пары: {e}')
                self.cleanup()
                break
            if not running or not done:
                break
            self.counter += 1
            trade_counter = self.counter
            msg_queue.put(('counter', self.counter))
            self.say(f'Пара N{self.counter} из {lot_count} исполнена')
            sleep(timeout)
        self.finish()

    def finish(self):
        self.cleanup()
        self.set_led('lightgray')
        self.set_status('Stopped')

    def run_pair(self):
        """Фаза 1: обе заявки. Первая исполненная — первичная. Исполнения
        опрашиваются с шагом poll_step, чтобы встречная заявка ушла в стакан
        немедленно, пока встречное предложение ещё стоит в книге."""
        qty = basket_size
        poll_step = 0.1  # шаг опроса исполнений, сек
        for leg in self.legs.values():
            leg['order_id'] = None
            leg['order_ids'] = []
            leg['price_old'] = None
            leg['qty_placed'] = 0
            leg['logged'] = 0
        self.say(f'--- Цикл: sell {dataname_sell} / buy {dataname_buy}, {qty} лотов ---')
        last_key = None
        while running:
            if not self.session_active():
                self.say('Вне торговой сессии — заявки сняты, ждём')
                self.cleanup()
                sleep(timeout)
                continue
            try:
                tg = self.compute_targets()
            except Exception as e:
                logger.warning(f'compute_targets пропущен: {e}')
                tg = None
            if tg is not None:
                self.emit_panel(tg)
                key = (tg['target_price_sell'], tg['target_price_buy'])
                if key != last_key:
                    self.say(f"Target SELL {tg['target_price_sell']} ({tg['target_iv_sell']:.2f}%) | "
                             f"BUY {tg['target_price_buy']} ({tg['target_iv_buy']:.2f}%) | "
                             f"Diff.theor {tg['diff']}")
                    last_key = key
                self.maintain_leg('sell', tg, qty)
                self.maintain_leg('buy', tg, qty)
            # Быстрый опрос исполнений внутри интервала timeout: переквот — раз в
            # timeout, обнаружение сделки — каждые poll_step
            for _ in range(max(int(timeout / poll_step), 1)):
                self.log_new_trades()
                fs, fb = self.leg_filled(self.legs['sell']), self.leg_filled(self.legs['buy'])
                fsq, fbq = fs[0] if fs else 0, fb[0] if fb else 0
                if fsq >= qty and fbq >= qty:
                    return True  # обе исполнились — пара готова
                if fsq > 0 or fbq > 0:
                    self.say('Первичная нога исполнена — мгновенная встречная заявка')
                    return self.run_balance(qty)
                sleep(poll_step)
        return False

    def run_balance(self, qty):
        """Фаза 2: встречная заявка на разницу исполненных лотов. Якорь — фактическая
        IV первичной ноги. Цена клампится к встречной стороне стакана (покупка —
        не ниже ask, продажа — не выше bid), чтобы исполниться немедленно."""
        poll_step = 0.1
        while running:
            if not self.session_active():
                self.cleanup()
                sleep(timeout)
                continue
            self.log_new_trades()
            fs, fb = self.leg_filled(self.legs['sell']), self.leg_filled(self.legs['buy'])
            fsq, fbq = fs[0] if fs else 0, fb[0] if fb else 0
            if fsq >= qty and fbq >= qty:
                return True
            lead = 'sell' if fsq >= fbq else 'buy'
            lag = 'buy' if lead == 'sell' else 'sell'
            lead_q, lag_q = (fsq, fbq) if lead == 'sell' else (fbq, fsq)
            need = lead_q - lag_q
            if need <= 0:
                sleep(poll_step)
                continue
            lead_price = (fs if lead == 'sell' else fb)[1]
            lag_leg = self.legs[lag]
            try:
                target_iv = counter_target_iv(self.legs[lead]['dataname'], lead_price,
                                              lag_leg['dataname'])
                S, K, T, opt_type = get_option_data_for_calc_price(lag_leg['dataname'])
                target_price = round_step(option_price(S, target_iv / 100, K, T, r, opt_type),
                                          lag_leg['step'], lag_leg['decimals'])
            except Exception as e:
                logger.warning(f'Таргет встречной ноги пропущен: {e}')
                sleep(poll_step)
                continue
            limit_price = target_price - lag_leg['step'] * indent if lag == 'sell' \
                else target_price + lag_leg['step'] * indent
            m = leg_market(lag_leg['dataname'])
            if m is None:
                sleep(poll_step)
                continue
            # Мгновенное исполнение: цель по построению — встречная сторона стакана,
            # но рынок мог уйти за время опроса. Покупаем не ниже ask, продаём не выше bid.
            if lag == 'buy' and limit_price < m[0]:
                self.say(f"Встречная BUY: цель {limit_price} ниже ask {m[0]} — исполнение по ask")
                limit_price = m[0]
            elif lag == 'sell' and limit_price > m[1]:
                self.say(f"Встречная SELL: цель {limit_price} выше bid {m[1]} — исполнение по bid")
                limit_price = m[1]

            if lag_leg['order_id'] is not None:
                if lag_leg['price_old'] == limit_price and lag_leg['qty_placed'] == need:
                    sleep(poll_step)
                    continue  # ничего не менялось
                self.cancel_leg(lag)  # переквот встречной заявки
            else:
                active = active_order(lag_leg['symbol'], lag_leg['side'])
                if active is not None and str(active['client_order_id']).startswith(filename):
                    lag_leg['order_id'] = active['order_id']
                    lag_leg['order_ids'].append(lag_leg['order_id'])
                    lag_leg['price_old'] = float(active['limit_price'])
                    lag_leg['qty_placed'] = int(float(active['remaining_quantity']))
                    self.say(f"Найдена активная заявка {lag.upper()} {lag_leg['order_id']}")
                    continue

            if not running:
                break
            new_id = place_order(lag_leg['side'], lag_leg['symbol'], need, limit_price)
            if new_id is not None:
                lag_leg['order_id'] = new_id
                lag_leg['order_ids'].append(new_id)
                lag_leg['price_old'] = limit_price
                lag_leg['qty_placed'] = need
                self.set_led('lightgreen')
                self.say(f"Встречная заявка {lag.upper()} {lag_leg['symbol']}: "
                         f"{limit_price} x{need} (якорь IV {target_iv:.2f}%)")
            sleep(poll_step)
        return False

    def emit_panel(self, tg):
        pos_sell, pos_buy = positions_quantity(dataname_sell), positions_quantity(dataname_buy)
        open_sell, open_buy = open_iv_safe(dataname_sell, pos_sell), open_iv_safe(dataname_buy, pos_buy)
        diff_pos = open_sell - open_buy if self.legs['sell']['opt_type'] == CALL else open_buy - open_sell
        msg_queue.put(('panel', {
            'sell': f"Target SELL: {tg['target_price_sell']} ({tg['target_iv_sell']:.2f}%) pos:{pos_sell}",
            'buy': f"Target BUY: {tg['target_price_buy']} ({tg['target_iv_buy']:.2f}%) pos:{pos_buy}",
            'diff_pos': diff_pos, 'diff_theor': tg['diff']}))


# ----------------------------------------------------------------------------
# Блок 7. GUI и запуск
# ----------------------------------------------------------------------------
def on_base_asset_change(event, app):
    global base_asset_ticker, dataname_base_asset_ticker_old, expiration_dates
    base_asset_ticker = app.combobox_base_asset.get()
    dataname = 'SPBFUT.' + base_asset_ticker
    if dataname_base_asset_ticker_old and dataname_base_asset_ticker_old in subscriptions_dict:
        unsubscribe_instrument(dataname_base_asset_ticker_old)
    app.add_message(f'Подписка на базовый актив {base_asset_ticker}')
    subscribe_instrument(dataname)
    sleep(1)
    expirations = get_option_expirations(base_asset_ticker)
    expiration_dates = [d.split('-')[2] + '.' + d.split('-')[1] + '.' + d.split('-')[0]
                        for d in sorted(set(e['expiration_date'] for e in expirations),
                                        key=lambda x: datetime.strptime(x, '%Y-%m-%d'))]
    app.combobox_expire['values'] = list(expiration_dates)
    app.combobox_expire.set(expiration_dates[0])
    dataname_base_asset_ticker_old = dataname


def on_expiration_date_change(event, app):
    global sell_tickers_call, sell_tickers_put
    formatted = datetime.strptime(app.combobox_expire.get(), '%d.%m.%Y').strftime('%Y-%m-%d')
    data = get_option_board(base_asset_ticker, formatted)
    app.add_message(f'Доска опционов {base_asset_ticker}, экспирация {formatted}')
    sell_tickers_call = [o['SECID'] for o in data['C']]
    sell_tickers_put = [o['SECID'] for o in data['P']]


def get_option_type_sell(app):
    values = sell_tickers_call if app.option_type_sell.get() == 'C' else sell_tickers_put
    app.combobox_sell['values'] = list(values)
    app.combobox_sell.set(values[0])


def get_option_type_buy(app):
    values = sell_tickers_put if app.option_type_buy.get() == 'P' else sell_tickers_call
    app.combobox_buy['values'] = list(values)
    app.combobox_buy.set(values[0])


def selected_sell(app):
    global dataname_sell, dataname_guid_sell_old
    ticker = app.combobox_sell.get()
    dataname_sell = 'SPBOPT.' + ticker
    if dataname_guid_sell_old and dataname_guid_sell_old in subscriptions_dict:
        unsubscribe_instrument(dataname_guid_sell_old)
    if subscribe_instrument(dataname_sell):
        get_option_data_alor(dataname_sell)
        dataname_guid_sell_old = dataname_sell
        app.add_message(f'Нога SELL: {ticker}')
    preview_targets(app, verbose=True)


def selected_buy(app):
    global dataname_buy, dataname_guid_buy_old
    ticker = app.combobox_buy.get()
    dataname_buy = 'SPBOPT.' + ticker
    if dataname_guid_buy_old and dataname_guid_buy_old in subscriptions_dict:
        unsubscribe_instrument(dataname_guid_buy_old)
    if subscribe_instrument(dataname_buy):
        get_option_data_alor(dataname_buy)
        dataname_guid_buy_old = dataname_buy
        app.add_message(f'Нога BUY: {ticker}')
    preview_targets(app, verbose=True)

def preview_targets(app, verbose=False):
    try:
        return _preview_targets_impl(app, verbose)
    except Exception:
        app.add_message('Предрасчёт недоступен:\n' + traceback.format_exc())


def _preview_targets_impl(app, verbose=False):
    """Предварительный расчёт целевых цен и IV обеих ног без выставления заявок."""
    if not dataname_sell or not dataname_buy:
        return
    if dataname_sell not in options_data or dataname_buy not in options_data:
        return
    m_sell, m_buy = leg_market(dataname_sell), leg_market(dataname_buy)
    if m_sell is None or m_buy is None:
        return
    ask_sell, bid_sell, ask_iv_sell, bid_iv_sell, theor_iv_sell = m_sell
    ask_buy, bid_buy, ask_iv_buy, bid_iv_buy, theor_iv_buy = m_buy

    off_sell = initial_offset(dataname_sell, dataname_buy, 'sell')
    off_buy = initial_offset(dataname_buy, dataname_sell, 'buy')
    tiv_sell = ask_iv_buy + off_sell
    tiv_buy = bid_iv_sell + off_buy

    legs = build_legs()
    sell_leg, buy_leg = legs['sell'], legs['buy']      # доступ по ключам, НЕ распаковка словаря
    Ss, Ks, Ts, _ = get_option_data_for_calc_price(dataname_sell)
    Sb, Kb, Tb, _ = get_option_data_for_calc_price(dataname_buy)
    tp_sell = round_step(option_price(Ss, tiv_sell / 100, Ks, Ts, r, sell_leg['opt_type']),
                         sell_leg['step'], sell_leg['decimals'])
    tp_buy = round_step(option_price(Sb, tiv_buy / 100, Kb, Tb, r, buy_leg['opt_type']),
                        buy_leg['step'], buy_leg['decimals'])
    tp_sell -= sell_leg['step'] * indent    # как в maintain_leg — предрасчёт = реальным заявкам
    tp_buy += buy_leg['step'] * indent

    pos_sell, pos_buy = positions_quantity(dataname_sell), positions_quantity(dataname_buy)
    open_sell, open_buy = open_iv_safe(dataname_sell, pos_sell), open_iv_safe(dataname_buy, pos_buy)
    diff_pos = open_sell - open_buy if sell_leg['opt_type'] == CALL else open_buy - open_sell

    msg_queue.put(('panel', {
        'sell': f"Target SELL: {tp_sell} ({tiv_sell:.2f}%) pos:{pos_sell}",
        'buy': f"Target BUY: {tp_buy} ({tiv_buy:.2f}%) pos:{pos_buy}",
        'diff_pos': diff_pos,
        'diff_theor': round(theor_iv_sell - theor_iv_buy, 2)}))

    if verbose:
        s = sign_of(sell_leg['opt_type'])
        diff_market = round(s * (bid_iv_sell - ask_iv_buy), 2)
        app.add_message('')
        app.add_message(f'Профит (IV): {expected_profit:g} | Theor: {theor_flag} | Indent: {indent}')
        app.add_message(f'SELL {dataname_sell}: ask {ask_sell:g} ({ask_iv_sell:.2f}%) '
                        f'bid {bid_sell:g} ({bid_iv_sell:.2f}%) -> target {tp_sell} ({tiv_sell:.2f}%)')
        app.add_message(f'BUY  {dataname_buy}: ask {ask_buy:g} ({ask_iv_buy:.2f}%) '
                        f'bid {bid_buy:g} ({bid_iv_buy:.2f}%) -> target {tp_buy} ({tiv_buy:.2f}%)')
        app.add_message(f'Diff.theor {round(theor_iv_sell - theor_iv_buy, 2)} | '
                        f'Diff.market {diff_market} | Difference pos {round(diff_pos, 2)}')


def selected_profit(app):
    global expected_profit
    try:
        value = float(app.spinbox_profit.get())
        if -20.0 <= value <= 20.0:
            expected_profit = round(value, 1)
            app.spinbox_profit_var.set(f'{expected_profit:g}')
            app.add_message(f'Профит (IV): {expected_profit}')
            preview_targets(app, verbose=True)
        else:
            app.add_message('Ошибка: значение вне диапазона -20.0 … 20.0')
    except ValueError:
        app.add_message('Ошибка: введите корректное числовое значение')


def toggle_theor(app):
    global theor_flag
    theor_flag = app.theor_var.get()
    app.add_message(f'Флаг Theor: {theor_flag}')


def selected_lot_count(app):
    global lot_count
    try:
        lot_count = int(app.spinbox_lot_count_var.get())
        app.add_message(f'Число циклов: {lot_count}')
    except ValueError:
        pass


def selected_basket_size(app):
    global basket_size
    try:
        basket_size = int(app.spinbox_basket_size.get())
        app.add_message(f'Лотов в заявке: {basket_size}')
    except ValueError:
        pass


def selected_timeout(app):
    global timeout
    try:
        timeout = int(app.spinbox_timeout.get())
        app.add_message(f'Timeout: {timeout}')
    except ValueError:
        pass


def selected_indent(app):
    global indent
    indent = int(app.spinbox_indent_var.get())
    app.add_message(f'Indent (шагов цены): {indent}')


class App:
    """GUI котировщика. Все обращения из торгового потока идут через msg_queue,
    рабочий цикл движка живёт в отдельном потоке."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title(f'{filename} — опционный котировщик')
        self.root.geometry('840x600')

        # Правая панель: журнал сообщений
        frame_right = tk.Frame(self.root)
        frame_right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.message_text = tk.Text(frame_right, width=64)
        self.message_text.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        scroll = tk.Scrollbar(frame_right, command=self.message_text.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.message_text.config(yscrollcommand=scroll.set)

        # Левая панель: управление
        frame_left = tk.Frame(self.root)
        frame_left.pack(side=tk.LEFT, fill=tk.Y, padx=5, pady=5)

        # Статус, светодиод, счётчик пар
        frame_status = tk.Frame(frame_left)
        frame_status.pack(fill=tk.X)
        self.status_label = tk.Label(frame_status, text='Status: Stopped', width=18, anchor='w')
        self.status_label.pack(side=tk.LEFT)
        self.led_label = tk.Label(frame_status, text='  ', bg='lightgray', width=3, relief=tk.GROOVE)
        self.led_label.pack(side=tk.LEFT, padx=5)
        self.counter_label = tk.Label(frame_status, text='Пар исполнено: 0')
        self.counter_label.pack(side=tk.LEFT, padx=5)

        # Панель таргетов и разниц
        self.target_label_sell = tk.Label(frame_left, text='Target SELL: -', anchor='w', width=45)
        self.target_label_sell.pack(fill=tk.X)
        self.target_label_buy = tk.Label(frame_left, text='Target BUY: -', anchor='w', width=45)
        self.target_label_buy.pack(fill=tk.X)
        self.difference_pos_label = tk.Label(frame_left, text='Difference position, % : -',
                                             anchor='w', width=45)
        self.difference_pos_label.pack(fill=tk.X)
        self.difference_theor_label = tk.Label(frame_left, text='Difference theor, % : -',
                                               anchor='w', width=45)
        self.difference_theor_label.pack(fill=tk.X)

        # Базовый актив
        tk.Label(frame_left, text='Базовый актив:').pack(anchor='w')
        self.combobox_base_asset = ttk.Combobox(frame_left, values=list(MAP.keys()), width=12)
        self.combobox_base_asset.pack(fill=tk.X)
        self.combobox_base_asset.bind('<<ComboboxSelected>>',
                                      lambda event: on_base_asset_change(event, self))

        # Дата экспирации
        tk.Label(frame_left, text='Дата экспирации:').pack(anchor='w')
        self.combobox_expire = ttk.Combobox(frame_left, values=[], width=12)
        self.combobox_expire.pack(fill=tk.X)
        self.combobox_expire.bind('<<ComboboxSelected>>',
                                  lambda event: on_expiration_date_change(event, self))

        # Опцион продажи
        tk.Label(frame_left, text='Опцион продажи:').pack(anchor='w')
        frame_opt_sell = tk.Frame(frame_left)
        frame_opt_sell.pack(fill=tk.X)
        self.option_type_sell = tk.StringVar(value='C')
        tk.Radiobutton(frame_opt_sell, text='Call', variable=self.option_type_sell, value='C',
                       command=lambda: get_option_type_sell(self)).pack(side=tk.LEFT)
        tk.Radiobutton(frame_opt_sell, text='Put', variable=self.option_type_sell, value='P',
                       command=lambda: get_option_type_sell(self)).pack(side=tk.LEFT)
        self.combobox_sell = ttk.Combobox(frame_left, values=[], width=14)
        self.combobox_sell.pack(fill=tk.X)
        self.combobox_sell.bind('<<ComboboxSelected>>', lambda event: selected_sell(self))

        # Опцион покупки
        tk.Label(frame_left, text='Опцион покупки:').pack(anchor='w')
        frame_opt_buy = tk.Frame(frame_left)
        frame_opt_buy.pack(fill=tk.X)
        self.option_type_buy = tk.StringVar(value='P')
        tk.Radiobutton(frame_opt_buy, text='Call', variable=self.option_type_buy, value='C',
                       command=lambda: get_option_type_buy(self)).pack(side=tk.LEFT)
        tk.Radiobutton(frame_opt_buy, text='Put', variable=self.option_type_buy, value='P',
                       command=lambda: get_option_type_buy(self)).pack(side=tk.LEFT)
        self.combobox_buy = ttk.Combobox(frame_left, values=[], width=14)
        self.combobox_buy.pack(fill=tk.X)
        self.combobox_buy.bind('<<ComboboxSelected>>', lambda event: selected_buy(self))

        # Профит и флаг Theor
        tk.Label(frame_left, text='Профит, п.п. IV:').pack(anchor='w')
        self.spinbox_profit_var = tk.StringVar(value=str(expected_profit))
        self.spinbox_profit = tk.Spinbox(frame_left, from_=-20.0, to=20.0, increment=0.1,
                                         textvariable=self.spinbox_profit_var, width=8,
                                         command=lambda: selected_profit(self))
        self.spinbox_profit.pack(fill=tk.X)
        self.spinbox_profit.bind('<Return>', lambda e: selected_profit(self))
        self.spinbox_profit.bind('<FocusOut>', lambda e: selected_profit(self))
        self.spinbox_profit.bind('<KeyRelease>', lambda e: selected_profit(self))  # после ввода


        self.theor_var = tk.BooleanVar(value=False)
        tk.Checkbutton(frame_left, text='Theor', variable=self.theor_var,
                       command=lambda: toggle_theor(self)).pack(anchor='w')

        # Число циклов
        self.spinbox_lot_count_var = tk.StringVar(value=str(lot_count))
        frame_lot = tk.Frame(frame_left)
        frame_lot.pack(fill=tk.X)
        tk.Label(frame_lot, text='Число циклов:').pack(side=tk.LEFT)
        self.spinbox_lot_count = tk.Spinbox(frame_lot, from_=1, to=100, increment=1,
                                            textvariable=self.spinbox_lot_count_var, width=6,
                                            command=lambda: selected_lot_count(self))
        self.spinbox_lot_count.pack(side=tk.LEFT)

        # Размер заявки
        self.spinbox_basket_size_var = tk.StringVar(value=str(basket_size))
        frame_basket = tk.Frame(frame_left)
        frame_basket.pack(fill=tk.X)
        tk.Label(frame_basket, text='Лотов в заявке:').pack(side=tk.LEFT)
        self.spinbox_basket_size = tk.Spinbox(frame_basket, from_=1, to=100, increment=1,
                                              textvariable=self.spinbox_basket_size_var, width=6,
                                              command=lambda: selected_basket_size(self))
        self.spinbox_basket_size.pack(side=tk.LEFT)

        # Timeout
        self.spinbox_timeout_var = tk.StringVar(value=str(timeout))
        frame_timeout = tk.Frame(frame_left)
        frame_timeout.pack(fill=tk.X)
        tk.Label(frame_timeout, text='Timeout, сек:').pack(side=tk.LEFT)
        self.spinbox_timeout = tk.Spinbox(frame_timeout, from_=1, to=60, increment=1,
                                          textvariable=self.spinbox_timeout_var, width=6,
                                          command=lambda: selected_timeout(self))
        self.spinbox_timeout.pack(side=tk.LEFT)

        # Indent
        self.spinbox_indent_var = tk.StringVar(value=str(indent))
        frame_indent = tk.Frame(frame_left)
        frame_indent.pack(fill=tk.X)
        tk.Label(frame_indent, text='Indent, шагов:').pack(side=tk.LEFT)
        self.spinbox_indent = tk.Spinbox(frame_indent, from_=0, to=20, increment=1,
                                         textvariable=self.spinbox_indent_var, width=6,
                                         command=lambda: selected_indent(self))
        self.spinbox_indent.pack(side=tk.LEFT)

        # Кнопки
        frame_buttons = tk.Frame(frame_left)
        frame_buttons.pack(fill=tk.X, pady=10)
        tk.Button(frame_buttons, text='Старт', width=10, command=self.start_quoter).pack(side=tk.LEFT, padx=2)
        tk.Button(frame_buttons, text='Стоп', width=10, command=self.stop_quoter).pack(side=tk.LEFT, padx=2)
        tk.Button(frame_buttons, text='Выход', width=10, command=self.exit).pack(side=tk.LEFT, padx=2)

        self.quoter_thread = None
        self.root.after(100, self._poll_messages)
        self._refresh_csv()  # первое обновление после запуска GUI
        self._schedule_preview()

    def _schedule_preview(self):
        if not running and dataname_sell and dataname_buy:
            preview_targets(self, verbose=False)
        self.root.after(2000, self._schedule_preview)

    def add_message(self, text):
        msg_queue.put(('msg', str(text)))

    def _refresh_csv(self):
        refresh_trades()
        self.root.after(15_000, self._refresh_csv)  # раз в 15 секунд

    def _poll_messages(self):
        while True:
            try:
                kind, value = msg_queue.get_nowait()
            except Empty:
                break
            if kind == 'msg':
                self.message_text.insert('end', value + '\n')
                self.message_text.see('end')
            elif kind == 'led':
                self.led_label.config(bg=value)
            elif kind == 'status':
                self.status_label.config(text=f'Status: {value}')
            elif kind == 'counter':
                self.counter_label.config(text=f'Пар исполнено: {value}')
            elif kind == 'panel':
                self.target_label_sell.config(text=value['sell'])
                self.target_label_buy.config(text=value['buy'])
                self.difference_pos_label.config(
                    text=f'Difference position, % : {value["diff_pos"]:.2f}')
                self.difference_theor_label.config(
                    text=f'Difference theor, % : {value["diff_theor"]:.2f}')
        self.root.after(100, self._poll_messages)

    def start_quoter(self):
        global engine
        if running:
            return
        if not dataname_sell or not dataname_buy \
                or dataname_sell not in options_data or dataname_buy not in options_data:
            self.add_message('Выберите оба опциона пары')
            return
        selected_profit(self)
        toggle_theor(self)
        selected_timeout(self)
        selected_indent(self)
        selected_basket_size(self)
        selected_lot_count(self)
        engine = QuoterEngine(build_legs())
        self.quoter_thread = Thread(target=engine.run, name='QuoterThread', daemon=True)
        self.quoter_thread.start()
        self.add_message('Котировщик запущен')

    def stop_quoter(self):
        global running
        running = False
        self.add_message('Стоп: останавливаем цикл и снимаем активные заявки')
        if engine is not None:
            engine.cleanup()

    def exit(self):
        global running
        running = False
        if engine is not None:
            engine.cleanup()
        unsubscribe_all()
        try:
            fp_provider.on_order.unsubscribe(_on_order)
            fp_provider.on_trade.unsubscribe(_on_trade)
            fp_provider.on_quote.unsubscribe(_on_new_quotes)
        except Exception as e:
            logger.error(f'Ошибка отписки от событий: {e}')
        fp_provider.close_channel()
        ap_provider.close_web_socket()
        sleep(2)
        if self.quoter_thread:
            self.quoter_thread.join(timeout=5)
        self.root.destroy()


# ----------------------------------------------------------------------------
# Bootstrap
# ----------------------------------------------------------------------------
logger = logging.getLogger(filename)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[logging.StreamHandler(),
              logging.FileHandler(f'{filename}.log', encoding='utf-8')])

schedule = Futures()
fp_provider = FinamPy()  # Подключаемся ко всем торговым счетам
ap_provider = AlorPy()  # Подключаемся ко всем торговым счетам
# Подписываемся на события
fp_provider.on_quote.subscribe(_on_new_quotes)  # Подписываемся на котировки
fp_provider.on_order.subscribe(_on_order)      # Подписываемся на заявки
fp_provider.on_trade.subscribe(_on_trade)      # Подписываемся на сделки
Thread(target=fp_provider.subscribe_orders_thread,
       name='SubscriptionOrdersThread').start()
Thread(target=fp_provider.subscribe_trades_thread,
       name='SubscriptionTradesThread').start()
# Подписка на информацию по аккаунту
if not fp_provider.account_ids:
    fp_provider.account_ids = list(fp_provider.token_details().account_ids)
if fp_provider.account_ids:
    account_id = fp_provider.account_ids[0]
    fp_provider.on_account_info.subscribe(_on_account_info)
    Thread(target=fp_provider.subscribe_account_thread,
           name='AccountThread', args=(account_id,)).start()
refresh_trades()
sleep(5)  # Ждем 5 секунд

if __name__ == "__main__":
    app = App()
    app.root.mainloop()
