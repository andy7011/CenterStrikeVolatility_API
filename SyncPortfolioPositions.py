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



global qp_provider, df_portfolio
# Создаем экземпляр AlorPy
ap_provider = AlorPy()

broker = brokers['Ф']  # Брокер по ключу из Config.py словаря brokers
portfolio_info = []
portfolio_positions = []
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
print(portfolio_positions)

broker = brokers['АС']  # Брокер по ключу из Config.py словаря brokers
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

    # # Получаем котировки для конкретного тикера
    # quotes = ap_provider.get_quotes('MOEX:RI97500BO6')[0]  # Получаем первую котировку
    # print(quotes)
    # # last_price = quotes['last_price'] if quotes else None  # Последняя цена сделки
    # # print(last_price)

# Не забываем закрыть соединение
ap_provider.close_web_socket()
