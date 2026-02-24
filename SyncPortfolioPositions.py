import logging  # Выводим лог на консоль и в файл
from datetime import datetime, timedelta, UTC  # Дата и время
import pytz
from pytz import timezone
from scipy.stats import norm
import pandas as pd
import csv
from string import Template
import threading
import time  # Подписка на события по времени
from accfifo import Entry, FIFO
from collections import deque
import re

from QuikPy.QuikPy import QuikPy  # Работа с QUIK из Python через LUA скрипты QUIK#
from Token import ap_provider

from model.option import Option
import option_type
import implied_volatility
from app.supported_base_asset import MAP

from threading import Thread, Event  # Поток и событие выхода из потока

from FinLabPy.Core import Broker, Bar, Position, Trade, Order, Symbol  # Брокер, бар, позиция, сделка, заявка, тикер
from FinLabPy.Config import brokers, default_broker  # Все брокеры и брокер по умолчанию
from AlorPy import AlorPy  # Работа с Alor OpenAPI V2 из Python через REST/WebSockets
from FinLabPy.Core import Broker, bars_to_df  # Перевод бар в pandas DataFrame
from FinLabPy.Schedule.MarketSchedule import Schedule  # Расписание работы биржи
from FinLabPy.Schedule.MOEX import Futures  # Расписание торгов срочного рынка

def sync_portfolio_info():
    portfolio_info = []
    broker = brokers['Ф']  # Брокер по ключу из Config.py словаря brokers
    value = broker.get_value()  # Стоимость портфеля
    cash = broker.get_cash()  # Свободные средств
    unrealized_profit = broker.get_unrealized_profit() # Нереализованная прибыль в рублях
    money_reserved = broker.get_money_reserved()
    GM = (money_reserved / value) * 100
    print(f'- Стоимость позиций  : {value - cash}')
    print(f'- Нереализованная прибыль: {unrealized_profit}')
    print(f'- Свободные средства : {cash}')
    print(f'- Зарезервировано GM : {money_reserved}')
    print(f'- Итого              : {value}')

    # Добавляем данные в список
    portfolio_info.append({
        'VM': unrealized_profit,
        'PL day': unrealized_profit,
        'Comiss': '?',
        'GM': (f'{GM:.0f} %')
    })
    print(f'portfolio_info: {portfolio_info}')
    return portfolio_info

def sync_portfolio_positions():
    portfolio_positions = []
    broker = brokers['Ф']  # Брокер по ключу из Config.py словаря brokers
    for position in broker.get_positions():  # Пробегаемся по всем позициям брокера
        if position.dataname.split('.')[0] == 'SPBOPT':  # Берём только SPBOPT (опционы)
            ticker = position.dataname.split('.')[1]
            dataname = position.dataname
            # print(ticker)
            # print(f'{dataname} {position.quantity}')
            # symbol = self.provider.get_symbol_by_dataname(dataname)
            # print(symbol)
            # Добавляем позиции в портфель
            portfolio_positions.append(position)
    print(f'portfolio_positions {portfolio_positions}')


    broker = brokers['АС']  # Брокер по ключу из Config.py словаря brokers
    ap_provider = AlorPy()
    for position in portfolio_positions:
        ticker = position.dataname.split('.')[1]
        dataname = position.dataname
        symbol = broker.get_symbol_by_dataname(dataname)  # Спецификация тикера брокера. Должна совпадать у всех брокеров
        # print(f'[{'SPBOPT'}] {symbol} Информация брокера: {symbol.broker_info}')
        exchange = symbol.broker_info['exchange']  # Биржа
        quotes = ap_provider.get_quotes(f'{exchange}:{ticker}') # Последнюю котировку получаем через запрос
        print(f' quotes {quotes}')
        option_info = ap_provider.get_symbol(exchange, ticker)  # Биржа и тикер опциона
        print(f' option_info {option_info}')

        # Тип опциона opt_type_converted
        option_type_response = option_info['optionSide']
        opt_type_converted = option_type.PUT if option_type_response == "Put" else option_type.CALL
        # print(f"Опцион: {ticker}, тип: {opt_type_converted}")

        # Время последней сделки last_time
        last_time = ""
        if quotes and len(quotes) > 0 and 'last_price_timestamp' in quotes[0]:
            last_time = quotes[0]['last_price_timestamp']
        # print(f"Время последней сделки: {last_time}")

        # Цена последней сделки по опциону (LAST) opt_price
        opt_price = 0
        if quotes and len(quotes) > 0 and 'last_price' in quotes[0]:
            param_value = quotes[0]['last_price']
            if param_value is not None and param_value != '':
                try:
                    opt_price = float(param_value)
                except ValueError:
                    opt_price = 0.0
        # print(f"Цена последней сделки по опциону: {opt_price}")

        # Цена опциона BID
        bid_price = 0.0
        if quotes and len(quotes) > 0 and 'bid' in quotes[0]:
            bid_price = float(quotes[0]['bid'])
        print(f"Цена опциона BID: {bid_price}")

        # Цена опциона OFFER (или ASK)
        offer_price = 0.0
        if quotes and len(quotes) > 0 and 'ask' in quotes[0]:
            offer_price = float(quotes[0]['ask'])
        print(f"Цена опциона OFFER: {offer_price}")

        # Цена опциона theor_price
        theor_price = 0.0
        if quotes and len(quotes) > 0 and option_info['theorPrice']:
            theor_price = float(option_info['theorPrice'])
        print(f"Цена опциона THEORPRICE: {theor_price}")

        # Цена последней сделки базового актива (S)
        exchange = option_info['exchange']
        underlyingSymbol = option_info['underlyingSymbol']
        quotes = ap_provider.get_quotes(f'{exchange}:{underlyingSymbol}')  # Получаем первую котировку
        asset_price = quotes[0]['last_price'] if quotes and len(quotes) > 0 else None  # Последняя цена сделки
        print(f"Цена последней сделки базового актива: {asset_price}")

        # Страйк опциона (K)
        strike_price = float(option_info['strikePrice'])
        print(f"Страйк опциона: {strike_price}")





        # Не забываем закрыть соединение
        ap_provider.close_web_socket()

if __name__ == '__main__':  # Точка входа при запуске этого скрипта
    sync_portfolio_info()
    sync_portfolio_positions()
