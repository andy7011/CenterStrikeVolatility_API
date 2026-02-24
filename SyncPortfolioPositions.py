import logging  # Выводим лог на консоль и в файл
from datetime import datetime
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

# Конфигурация для работы с файлами
temp_str = 'C:\\Users\\шадрин\\YandexDisk\\_ИИС\\Position\\$name_file'
temp_obj = Template(temp_str)

def calculate_open_data_open_price_open_iv(sec_code, net_pos):
    """
    Вычисляет дату открытия позиции, цену и волатильность для заданного инструмента,
    как средневзвешенные по объёму первых сделок до достижения нужного объёма.

    :param sec_code: Код инструмента
    :param net_pos: Текущая позиция (отрицательная для короткой позиции)
    :return: tuple(OpenDateTime, OpenPrice, OpenIV)
    """

    try:
        # Чтение CSV файла
        df = pd.read_csv(temp_obj.substitute(name_file='QUIK_Stream_Trades.csv'), encoding='utf-8', delimiter=';')

        # Фильтрация по инструменту (все сделки по инструменту)
        instrument_trades_df = df[df['ticker'] == sec_code].copy()

        if instrument_trades_df.empty:
            print(f"Предупреждение: Нет данных для инструмента {sec_code}")
            return None, None, None

        # Преобразование datetime
        instrument_trades_df['datetime'] = pd.to_datetime(instrument_trades_df['datetime'], format='%d.%m.%Y %H:%M:%S')

        # Сортировка по дате
        instrument_trades_df = instrument_trades_df.sort_values('datetime', ascending=False)  # обратный порядок
        # instrument_trades_df = instrument_trades_df.sort_values('datetime')

        # Применяем изменение знака для объема при продаже (умножаем объем сделки на -1)
        instrument_trades_df.loc[instrument_trades_df['operation'] == 'Продажа', 'volume'] *= -1

        # print(instrument_trades_df)
        # print(instrument_trades_df.iloc[-1]['volume']) # последняя сделка
        volume_last = instrument_trades_df.iloc[0]['volume']  # объем последней сделки

        # Целевой объём
        required_volume = net_pos
        selected_trades = []
        # Вычитаем сделки до достижения нужного объёма
        for _, trade in instrument_trades_df.iterrows():
            volume = trade['volume']
            # Для положительного required_volume: вычитаем объем
            if required_volume > 0:
                if required_volume - volume >= 0:
                    selected_trades.append(trade)
                    required_volume -= volume
                else:
                    # Добавляем частичную сделку
                    partial_trade = trade.copy()
                    partial_trade['volume'] = required_volume
                    selected_trades.append(partial_trade)
                    required_volume = 0
                    break
            # Для отрицательного required_volume: прибавляем объем
            else:
                if required_volume - volume <= 0:
                    selected_trades.append(trade)
                    required_volume -= volume
                else:
                    # Добавляем частичную сделку
                    partial_trade = trade.copy()
                    partial_trade['volume'] = required_volume
                    selected_trades.append(partial_trade)
                    required_volume = 0
                    break

            # Прерываем цикл при достижении нуля
            if required_volume == 0:
                break

        # Создаём DataFrame из выбранных сделок
        selected_df = pd.DataFrame(selected_trades)

        # Дата первой сделки (самой старой сделки, она в конце списка)
        OpenDateTime = selected_df.iloc[-1]['datetime'].strftime('%d.%m.%Y %H:%M:%S')

        # Удаляем из списка selected_trades сделки противоположной направленности
        # для правильного расчета средневзвешенных значений цены и волатильности
        if selected_trades:  # Проверяем, что список не пуст
            # Создаем новый список без противоположных сделок
            filtered_trades = []
            # print(f"\nСписок до фильтрации {sec_code} net_pos {net_pos}: {len(selected_trades)}")

            # Проходим по всем сделкам
            for trade in selected_trades:
                volume = trade['volume']

                # Если required_volume положительный - удаляем сделки с отрицательным объемом
                if net_pos > 0:
                    if volume > 0:  # Оставляем только сделки с положительным объемом
                        filtered_trades.append(trade)
                        # print(f"Сделка LONG после фильтрации: {trade['datetime']}, {volume}, {trade['price']}, {trade['volatility']}")
                # Если required_volume отрицательный - удаляем сделки с положительным объемом
                else:
                    if volume < 0:  # Оставляем только сделки с отрицательным объемом
                        filtered_trades.append(trade)
                        # print(f"Сделка SHORT после фильтрации: {trade['datetime']}, {volume}, {trade['price']}, {trade['volatility']}")

            # print(f"Список после фильтрации {sec_code} net_pos {net_pos}: {len(filtered_trades)}")

            # Заменяем исходный список отфильтрованными сделками
            selected_trades = filtered_trades

        # Расчет средневзвешенной цены и волатильности открытия методом FIFO
        # selected_trades - это отфильтрованный на предыдущем этапе список словарей
        fifo_entries = []
        fifo_entries_volatility = []
        for trade in selected_trades:
            quantity = trade['volume']
            price = trade['price']
            volatility = trade['volatility']

            # Создаем Entry с позиционными аргументами
            fifo_entries.append(Entry(quantity=quantity, price=price))
            fifo_entries_volatility.append(Entry(quantity=quantity, price=volatility))

        fifo = FIFO(fifo_entries)
        # print(f"Позиция {sec_code}: {fifo.stock}")
        # print(f"Цены открытия позиции {sec_code}: {fifo.inventory}")
        s = fifo.inventory
        OpenPrice = calculate_weighted_average(s)
        # print(f'Средневзвешенная цена {sec_code}: {OpenPrice}')

        # print(f"Реализованный P&L {sec_code}: {sum([entry.price * entry.quantity for step in fifo.trace for entry in step])}")
        fifo = FIFO(fifo_entries_volatility)
        # print(f"Волатильность отрытых позиций {sec_code}: {fifo.inventory}")
        # print(f"Реализованный P&L IV {sec_code}: {sum([entry.price * entry.quantity for step in fifo.trace for entry in step])}")
        s = fifo.inventory
        OpenIV = calculate_weighted_average(s)
        # print(f'Средневзвешенная волатильность {sec_code}: {OpenIV}')
        #
        # print('\n')

        if not selected_trades:
            sum_volume_short = instrument_trades_df.loc[instrument_trades_df['operation'] == 'Продажа', 'volume'].sum()
            count_short = (instrument_trades_df['operation'] == 'Продажа').sum()
            sum_volume_long = instrument_trades_df.loc[instrument_trades_df['operation'] == 'Купля', 'volume'].sum()
            count_long = (instrument_trades_df['operation'] == 'Купля').sum()
            print(f"Предупреждение: Недостаточно сделок для инструмента {sec_code}")
            print(f"Позиция: {net_pos}")
            print(f"Сделок лонг: {count_long} Объем: {sum_volume_long}")
            print(f"Сделок шорт: {count_short} Объем: {sum_volume_short}")
            return None, None, None

        return OpenDateTime, OpenPrice, OpenIV

    except Exception as e:
        print(f"Ошибка при вычислении данных открытия для {sec_code}: {e}")
        return None, None, None

# Расчет средневзвешенных значений
def calculate_weighted_average(s):
    # Преобразуем deque в строку, если это необходимо
    if isinstance(s, deque):
        s = str(s)  # или другой способ преобразования deque в строку
    # Извлекаем элементы из строки
    items = re.findall(r'(-?\d+(?:\.\d+)?) @(-?\d+(?:\.\d+)?)', s)

    # Преобразуем в числа
    items = [(float(w), float(v)) for w, v in items]

    # Вычисляем средневзвешенное
    weighted_sum = sum(w * v for w, v in items)
    total_weight = sum(w for w, v in items)

    return weighted_sum / total_weight if total_weight != 0 else 0

def sync_portfolio_info():
    portfolio_info = []
    broker = brokers['Ф']  # Брокер по ключу из Config.py словаря brokers
    value = broker.get_value()  # Стоимость портфеля
    cash = broker.get_cash()  # Свободные средств
    unrealized_profit = broker.get_unrealized_profit() # Нереализованная прибыль в рублях
    money_reserved = broker.get_money_reserved()
    GM = (money_reserved / value) * 100
    # print(f'- Стоимость позиций  : {value - cash}')
    # print(f'- Нереализованная прибыль: {unrealized_profit}')
    # print(f'- Свободные средства : {cash}')
    # print(f'- Зарезервировано GM : {money_reserved}')
    # print(f'- Итого              : {value}')

    # Добавляем данные в список
    portfolio_info.append({
        'VM': unrealized_profit,
        'PL day': unrealized_profit,
        'Comiss': '?',
        'GM': (f'{GM:.0f} %')
    })
    print(f'portfolio_info: {portfolio_info}')
    return portfolio_info

# Получить количество позиций по соответствующему тикеру из portfolio_positions
def get_position_quantity_by_ticker(portfolio_positions, ticker):
    for position in portfolio_positions:
        if position.dataname.split('.')[1] == ticker:
            return position.quantity
    return 0  # Если позиция не найдена

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
    # print(f'portfolio_positions {portfolio_positions}')

    broker = brokers['АС']  # Брокер по ключу из Config.py словаря brokers
    ap_provider = AlorPy()
    portfolio_positions_finam = []
    for position in portfolio_positions:
        if position.quantity != 0:
            ticker = position.dataname.split('.')[1]
            dataname = position.dataname
            symbol = broker.get_symbol_by_dataname(dataname)  # Спецификация тикера брокера. Должна совпадать у всех брокеров
            # print(f'[{'SPBOPT'}] {symbol} Информация брокера: {symbol.broker_info}')
            exchange = symbol.broker_info['exchange']  # Биржа
            quotes = ap_provider.get_quotes(f'{exchange}:{ticker}') # Последнюю котировку получаем через запрос
            # print(f' quotes {quotes}')
            option_info = ap_provider.get_symbol(exchange, ticker)  # Биржа и тикер опциона
            # print(f' option_info {option_info}')

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
            # print(f"Цена опциона BID: {bid_price}")

            # Цена опциона OFFER (или ASK)
            offer_price = 0.0
            if quotes and len(quotes) > 0 and 'ask' in quotes[0]:
                offer_price = float(quotes[0]['ask'])
            # print(f"Цена опциона OFFER: {offer_price}")

            # Цена опциона theor_price
            theor_price = 0.0
            if quotes and len(quotes) > 0 and option_info['theorPrice']:
                theor_price = float(option_info['theorPrice'])
            # print(f"Цена опциона THEORPRICE: {theor_price}")

            # Цена последней сделки базового актива (S)
            exchange = option_info['exchange']
            underlyingSymbol = option_info['underlyingSymbol']
            quotes = ap_provider.get_quotes(f'{exchange}:{underlyingSymbol}')  # Получаем первую котировку
            asset_price = quotes[0]['last_price'] if quotes and len(quotes) > 0 else None  # Последняя цена сделки
            # print(f"Цена последней сделки базового актива: {asset_price}")

            # Страйк опциона (K)
            strike_price = float(option_info['strikePrice'])
            # print(f"Страйк опциона: {strike_price}")

            # Волатильность опциона (sigma)
            VOLATILITY = float(option_info['volatility'])
            # print(f"Волатильность опциона: {VOLATILITY}")

            # Дата исполнения инструмента "%Y-%m-%d" <class 'datetime.date'>
            EXPDATE_image = option_info['endExpiration']
            from datetime import date, datetime
            EXPDATE_iso = datetime.strptime(EXPDATE_image.split('.')[0], '%Y-%m-%dT%H:%M:%S').date()
            formatted_exp_date = EXPDATE_iso.strftime("%d.%m.%Y")
            from datetime import datetime
            EXPDATE = datetime.fromisoformat(EXPDATE_image.replace('Z', '+00:00')).date()
            # print(f"Дата исполнения инструмента: {EXPDATE} {type(EXPDATE)}")

            # Число дней до экспирации
            from datetime import date
            # DAYS_TO_MAT_DATE = (EXPDATE - datetime.now().date()).days
            DAYS_TO_MAT_DATE = (EXPDATE - date.today()).days
            # print(f"Число дней до исполнения инструмента: {DAYS_TO_MAT_DATE}")

            # Создание опциона
            # option = Option(ticker, underlyingSymbol, EXPDATE, strike_price, opt_type_converted)
            from datetime import datetime
            option = Option(ticker, underlyingSymbol, datetime.combine(EXPDATE, datetime.min.time()), strike_price,
                            opt_type_converted)
            # print(option)

            # Время до исполнения инструмента в долях года
            time_to_maturity = option.get_time_to_maturity()
            # print(f'time_to_maturity - Время до исполнения инструмента в долях года: {time_to_maturity}, тип: {type(time_to_maturity)}')

            # Вычисление Vega
            sigma = VOLATILITY / 100
            vega = implied_volatility._vega(asset_price, sigma, strike_price, time_to_maturity,
                                            implied_volatility._RISK_FREE_INTEREST_RATE,
                                            opt_type_converted)
            Vega = vega / 100
            # print(f"Vega: {Vega}")

            # Вычисление TrueVega
            if DAYS_TO_MAT_DATE == 0:
                TrueVega = 0
            else:
                TrueVega = Vega / (DAYS_TO_MAT_DATE ** 0.5)

            # Волатильность опциона IMPLIED_VOLATILITY (IV) - через расчет по цене опциона
            opt_volatility_last = 0.0
            if opt_price > 0:
                opt_volatility_last = implied_volatility.get_iv_for_option_price(asset_price, option, opt_price)
                if opt_volatility_last is None:
                    opt_volatility_last = 0.0
            # print(f"Волатильность опциона (IV) - через расчет по цене опциона: {opt_volatility_last}")

            opt_volatility_bid = implied_volatility.get_iv_for_option_price(asset_price, option, bid_price)
            # print(f'opt_volatility_bid - IV Bid: {opt_volatility_bid}, тип: {type(opt_volatility_bid)}')
            opt_volatility_offer = implied_volatility.get_iv_for_option_price(asset_price, option, offer_price)
            # print(f'opt_volatility_offer - IV Offer: {opt_volatility_offer}, тип: {type(opt_volatility_offer)}')

            # Получить количество позиций по соответствующему тикеру из portfolio_positions
            net_pos = get_position_quantity_by_ticker(portfolio_positions, ticker)
            # print(f'net_pos - Net position: {net_pos}, тип: {type(net_pos)}')

            # Вычисляем данные открытия позиции
            open_data_result = calculate_open_data_open_price_open_iv(ticker, net_pos)
            # Проверяем, что функция вернула корректные данные
            if open_data_result is not None and len(open_data_result) > 2:
                open_datetime = open_data_result[0]
                open_price = open_data_result[1] if open_data_result[1] is not None else 0.0
                open_iv = open_data_result[2] if open_data_result[2] is not None else 0.0
            else:
                open_datetime = ""
                open_price = 0.0
                open_iv = 0.0

            # Добавляем данные в список
            portfolio_positions_finam.append({
                'ticker': ticker,
                'net_pos': net_pos,
                'strike': strike_price,
                'option_type': option_type_response,
                'expdate': formatted_exp_date,
                'option_base': underlyingSymbol,
                'OpenDateTime': open_datetime,
                'OpenPrice': round(open_price, 2) if open_price is not None else open_price,
                'OpenIV': round(open_iv, 2) if open_iv is not None else open_iv,
                'time_last': last_time,
                'bid': bid_price,
                'last': opt_price,
                'ask': offer_price,
                'theor': theor_price,
                'QuikVola': VOLATILITY,
                'bidIV': round(opt_volatility_bid, 2) if opt_volatility_bid is not None else 0,
                'lastIV': round(opt_volatility_last, 2) if opt_volatility_last is not None else 0,
                'askIV': round(opt_volatility_offer, 2) if opt_volatility_offer is not None else 0,
                'P/L theor': round(VOLATILITY - open_iv, 2) if net_pos > 0 else round(open_iv - VOLATILITY,
                                                                                      2),
                # 'P/L last': round(opt_volatility_last - open_iv, 2) if net_pos > 0 else round(open_iv - opt_volatility_last, 2),
                'P/L last': 0 if opt_volatility_last == 0 else (
                    round(opt_volatility_last - open_iv, 2) if net_pos > 0 else round(
                        open_iv - opt_volatility_last, 2)),
                # 'P/L market': round(opt_volatility_bid - open_iv, 2) if net_pos > 0 else round(open_iv - opt_volatility_offer, 2),
                'P/L market': round(opt_volatility_bid - open_iv, 2) if (
                        net_pos > 0 and opt_volatility_bid is not None) else round(
                    open_iv - opt_volatility_offer, 2) if opt_volatility_offer is not None else None,
                'Vega': round(Vega * net_pos, 2),
                'TrueVega': round(TrueVega * net_pos, 2)
            })
    # print(f'portfolio_positions_finam: {portfolio_positions_finam}')
    # Сохраняем в CSV файл
    if portfolio_positions_finam:
        df_portfolio = pd.DataFrame(portfolio_positions_finam)
        df_portfolio.to_csv(temp_obj.substitute(name_file='MyPosFinam.csv'),
                            sep=';', encoding='utf-8', index=False)
    else:
        # Создаем пустой файл с заголовками
        empty_df = pd.DataFrame(columns=[
            'ticker', 'net_pos', 'strike', 'option_type', 'expdate', 'option_base',
            'OpenDateTime', 'OpenPrice', 'OpenIV', 'time_last', 'bid', 'last', 'ask', 'theor',
            'QuikVola', 'bidIV', 'lastIV', 'askIV', 'P/L theor', 'P/L last', 'P/L market',
            'Vega', 'TrueVega'
        ])
        empty_df.to_csv(temp_obj.substitute(name_file='MyPosFinam.csv'),
                        sep=';', encoding='utf-8', index=False)

    # Получаем список тикеров из портфеля
    tickers = [item['ticker'] for item in portfolio_positions_finam]
    # print(f'portfolio_positions_finam tickers: {tickers}')

    # Очищаем файл со сделками QUIK_Stream_Trades.csv - удаляем старые сделки с тикерами, которых уже нет в портфеле
    # Чтение CSV файла
    df = pd.read_csv(temp_obj.substitute(name_file='QUIK_Stream_Trades.csv'), encoding='utf-8', delimiter=';')
    # Удаляем строки с тикерами, которых нет в портфеле
    df = df[df['ticker'].isin(tickers)]
    # Сохраняем обновленный CSV файл
    df.to_csv(temp_obj.substitute(name_file='QUIK_Stream_Trades.csv'), encoding='utf-8', index=False, sep=';')


    # Не забываем закрыть соединение
    ap_provider.close_web_socket()

if __name__ == '__main__':  # Точка входа при запуске этого скрипта
    sync_portfolio_info()
    sync_portfolio_positions()
