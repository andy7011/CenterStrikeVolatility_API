import os.path
from math import isnan
import dash
from dash import dcc, Input, Output, callback, dash_table, State
from dash import html
import dash_bootstrap_components as dbc
import dash_daq as daq
from dash.exceptions import PreventUpdate
from datetime import datetime, timedelta, UTC  # Дата и время
from datetime import timedelta
from pytz import utc
import requests
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd

from app.central_strike import _calculate_central_strike
from model.option import Option
import option_type
import implied_volatility
from app.supported_base_asset import MAP

from string import Template
import time
import random
import inspect
from accfifo import Entry, FIFO
from collections import deque
import re

from FinLabPy.Config import brokers, default_broker  # Все брокеры и брокер по умолчанию
from FinLabPy.Core import bars_to_df  # Перевод бар в pandas DataFrame
from AlorPy import AlorPy  # Работа с Alor OpenAPI V2 из Python через REST/WebSockets

temp_str = 'C:\\Users\\шадрин\\YandexDisk\\_ИИС\\Position\\$name_file'
temp_obj = Template(temp_str)

# Глобальные переменные для хранения данных
model_from_api = None
base_asset_list = None
option_list = None
central_strike = None
global df_candles

# Первый фьючерс в списке MAP
first_key = next(iter(MAP))


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

    # Вычисление и добавление в словарь центрального страйка
    for asset in base_asset_list:
        ticker = asset.get('_ticker')
        last_price = asset.get('_last_price')
        strike_step = MAP[ticker]['strike_step']
        central_strike = _calculate_central_strike(last_price, strike_step)
        asset.update({
            'central_strike': central_strike
        })

    return model_from_api


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


# Выполняем запрос при запуске
fetch_api_data()

# Список базовых активов
base_asset_ticker_list = {}
for i in range(len(base_asset_list)):
    base_asset_ticker_list.update({base_asset_list[i]['_ticker']: base_asset_list[i]['_base_asset_code']})

# Список опционов
df = pd.DataFrame.from_dict(option_list, orient='columns')
df = df.loc[df['_volatility'] > 0]
df['_expiration_datetime'] = pd.to_datetime(df['_expiration_datetime'], format='%a, %d %b %Y %H:%M:%S GMT')
df['_expiration_datetime'].dt.date
df['expiration_date'] = df['_expiration_datetime'].dt.strftime('%d.%m.%Y')
dff = df[(df._base_asset_ticker == first_key)]  # оставим только опционы базового актива

for asset in base_asset_list:
    if asset['_ticker'] == first_key:
        base_asset_last_price = asset['_last_price']  # получаем последнюю цену базового актива

dff_call = dff[(dff._type == 'C')]  # оставим только коллы

# My positions data
with open(temp_obj.substitute(name_file='QUIK_MyPos.csv'), 'r') as file:
    df_table = pd.read_csv(file, sep=';')
    df_table_buy = df_table[(df_table.option_base == first_key) & (df_table.net_pos > 0) & (df_table.OpenIV > 0)]
    df_table_sell = df_table[(df_table.option_base == first_key) & (df_table.net_pos < 0) & (df_table.OpenIV > 0)]
    MyPos_ticker_list = []
    for i in range(len(df_table)):
        MyPos_ticker_list.append(df_table['ticker'][i])
    # DataFrame для отрисовки баланса TrueVega
    df_table_base = df_table
    df_table_base = df_table_base[df_table_base.option_base == first_key]
# Close the file explicitly file.close()
file.close()

# My orders data
with open(temp_obj.substitute(name_file='QUIK_Stream_Orders.csv'), 'r', encoding='utf-8') as file:
    df_orders = pd.read_csv(file, sep=';')
    df_orders = df_orders[(df_orders.option_base == first_key)]
    df_orders_buy = df_orders[(df_orders.option_base == first_key) & (df_orders.operation == 'Купля')]
    df_orders_sell = df_orders[(df_orders.option_base == first_key) & (df_orders.operation == 'Продажа')]
    # Converting DataFrame "df_orders" to a list "tikers" containing all the rows of column 'ticker'
    tikers = df_orders['ticker'].tolist()

# My trades data
with open(temp_obj.substitute(name_file='QUIK_Stream_Trades.csv'), 'r', encoding='UTF-8') as file:
    df_trades = pd.read_csv(file, sep=';')
file.close()

# My positions history data
with open(temp_obj.substitute(name_file='MyPosHistory.csv'), 'r', encoding='UTF-8') as file:
    df_MyPosTilt = pd.read_csv(file, sep=';')
file.close()

# MyEquity
# Чтение промежуточного файла
with open(temp_obj.substitute(name_file='Equity.CSV'), 'r') as file:
    df_equity = pd.read_csv(file, sep=',')
    df_equity['Date'] = pd.to_datetime(df_equity['Date'], format='%d.%m.%Y %H:%M:%S')
    df_equity = df_equity.sort_values('Date').reset_index(drop=True)
    # Получаем все столбцы кроме 'Date'
    cols_to_convert = df_equity.columns.drop('Date')
    # Удаляем пробелы и преобразуем в числа
    df_equity[cols_to_convert] = df_equity[cols_to_convert].replace(' ', '', regex=True)
    df_equity[cols_to_convert] = df_equity[cols_to_convert].apply(pd.to_numeric, errors='coerce')
file.close()

# Получаем информацию о тикере из Алор брокера
def get_ticker_info_alor(dataname):
    option_ticker = dataname.split('.')[1]  # Тикер
    broker = brokers['АС']  # Брокер по ключу из Config.py словаря brokers
    ap_provider = AlorPy()
    symbol = broker.get_symbol_by_dataname(dataname)  # Спецификация тикера брокера. Должна совпадать у всех брокеров
    exchange = symbol.broker_info['exchange']  # Биржа
    option_info = ap_provider.get_symbol(exchange, option_ticker)  # Биржа и тикер опциона
    broker.close()  # Закрываем брокера

    # Цена опциона theor_price
    theor_price = 0.0
    if option_info['theorPrice']:
        theor_price = float(option_info['theorPrice'])
    return theor_price

# СВЕЧИ Данные для графика базового актива (для первой прорисовки, первый фьючерс из списка MAP)

# Будем запрашивать глубину истории 140 дней
dt_from = datetime.now() - timedelta(days=140)
dataname = f'SPBFUT.{first_key}'
time_frame = 'M15'


# Получаем историю баров для указанного инструмента и временного интервала
def get_candles_request(dataname, time_frame, dt_from):
    """
    Функция получения датафрейма свечей от брокера Алор.
    Args:
        dataname: имя инструмента в формате SPBFUT.RIH6
        ime_frame: таймфрейм
        dt_from: начальная дата
    """
    global df_candles
    broker = brokers['АС']  # Брокер по ключу из Config.py словаря brokers
    symbol = broker.get_symbol_by_dataname(dataname)  # Тикер по названию
    bars = broker.get_history(symbol, time_frame, dt_from=dt_from)  # Получаем историю тикера за 140 дней
    print(f"Запрос свечей: {dataname} {time_frame} начиная с даты {dt_from}")
    # print(f"Первый бар: {bars[0]}")  # Первый бар
    # print(f"Последний бар: {bars[-1]}")  # Последний бар
    df_candles = bars_to_df(bars)  # Все бары в pandas DataFrame pd_bars
    # print(df_candles)  # Все бары в pandas DataFrame pd_bars
    broker.close()  # Закрываем брокера
    return df_candles


# Вызов функции после её определения
df_candles = get_candles_request(dataname, time_frame, dt_from)

# Сборка основного файла истории
try:
    with open(temp_obj.substitute(name_file='MyEquity.CSV'), 'r') as file:
        df_myequity = pd.read_csv(file, sep=',')
        df_myequity['Date'] = pd.to_datetime(df_myequity['Date'], format='%Y-%m-%d %H:%M:%S')
        df_myequity = df_myequity.sort_values('Date').reset_index(drop=True)
except pd.errors.EmptyDataError:
    # Если файл пустой, создаем пустой DataFrame с нужными колонками
    df_myequity = pd.DataFrame(columns=df_equity.columns)

# Объединяем df_equity и df_myequity
df_combined = pd.concat([df_equity, df_myequity], ignore_index=True)
# Удаляем дубликаты
df_combined = df_combined.drop_duplicates()
# Удаляем возможные дубликаты по дате, оставляя последнюю запись
df_combined = df_combined.drop_duplicates(subset=['Date'], keep='last')
df_combined = df_combined.sort_values('Date').reset_index(drop=True)

# Сохранить df_combined в файл MyEquity.CSV с разделителем запятая
df_combined.to_csv(temp_obj.substitute(name_file='MyEquity.CSV'), sep=',', index=False)


def zero_to_nan(values):
    """Replace every 0 with 'nan' and return a copy."""
    return [float('nan') if x == 0 else x for x in values]

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

# Список базовых активов, вычисление и добавление в словарь центрального страйка
for asset in base_asset_list:
    ticker = asset.get('_ticker')
    last_price = asset.get('_last_price')
    strike_step = MAP[ticker]['strike_step']
    central_strike = _calculate_central_strike(last_price, strike_step)  # вычисление центрального страйка
    asset.update({
        'central_strike': central_strike
    })
# print('base_asset_list:', base_asset_list) # вывод списка базовых активов
base_asset_ticker_list = {}
# Создание словаря с базовыми активами и их кодами
for i in range(len(base_asset_list)):
    # print(base_asset_list[i]['_ticker'])
    base_asset_ticker_list.update({base_asset_list[i]['_ticker']: base_asset_list[i]['_base_asset_code']})
# print(base_asset_ticker_list)

# Список опционов из dump_model
option_list = model_from_api[1]
current_datetime = datetime.now()
df = pd.DataFrame.from_dict(option_list, orient='columns')
df = df.loc[df['_volatility'] > 0]
df['_expiration_datetime'] = pd.to_datetime(df['_expiration_datetime'], format='%a, %d %b %Y %H:%M:%S GMT')
df['_expiration_datetime'].dt.date
df['expiration_date'] = df['_expiration_datetime'].dt.strftime('%d.%m.%Y')

# ОФОРМЛЕНИЕ ВКЛАДОК TAB
# Tabs content
tab1_content = [dcc.Graph(id='MyPosTiltHistory', style={'margin-top': 10})]
tab2_content = [dcc.Graph(id='naklon_history', style={'margin-top': 10})]
tab3_content = [  # График истории
    dcc.Graph(id='plot_history', style={'margin-top': 10}),
    dcc.RadioItems(options=['Call', 'Put'],
                   value='Call',
                   inline=True,
                   style=dict(display='flex', justifyContent='right'),
                   id='my-radio-buttons-final'),
]
tab4_content = [  # Таблица моих позиций
    html.Div(id='intermediate-value', style={'display': 'none'}),
    html.Div(
        dash_table.DataTable(
            id='table',
            data=df_table.to_dict('records'),
            page_size=20,
            style_table={'max-width': '50px'},
            style_header={
                'fontWeight': 'bold',
                'backgroundColor': 'rgb(40, 40, 40)',  # Темный фон заголовка
                'color': 'white',  # Белый текст заголовка
                'textAlign': 'center'
            },
            style_data={
                'backgroundColor': 'rgb(20, 20, 20)',  # Темный фон ячеек
                'color': 'white'  # Белый текст ячеек
            },
            style_data_conditional=[
                {
                    'if': {'filter_query': '{ticker} = "Total"'},
                    'fontWeight': 'bold',
                    'backgroundColor': 'rgb(40, 40, 40)'  # Темный фон Total
                },
                {'if': {'filter_query': '{P/L theor} > 1', 'column_id': 'P/L theor'},
                 'backgroundColor': '#3D9970', 'color': 'white'},
                {'if': {'filter_query': '{P/L last} > 1', 'column_id': 'P/L last'},
                 'backgroundColor': '#3D9970', 'color': 'white'},
                {'if': {'filter_query': '{P/L market} > 1', 'column_id': 'P/L market'},
                 'backgroundColor': '#3D9970', 'color': 'white'},
                {'if': {'column_id': 'time_last'}, 'color': '#DAA520'},
                {'if': {'column_id': 'bid'}, 'color': '#3D9970'},
                {'if': {'column_id': 'last'}, 'color': '#DAA520'},
                {'if': {'column_id': 'ask'}, 'color': '#FF0000'},
            ]
        ),
        style={'margin-left': '100px'}  # Сдвиг вправо для таблицы
    )
]

tab5_content = [  # Таблица моих сделок
    html.Div(id='intermediate-value1', style={'display': 'none'}),
    html.Div(
        dash_table.DataTable(
            id='trades',
            data=df_trades.to_dict('records'),
            page_size=14,
            style_table={'max-width': '50px'},
            style_header={
                'fontWeight': 'bold',
                'backgroundColor': 'rgb(40, 40, 40)',
                'color': 'white',
                'textAlign': 'center'
            },
            style_data={
                'backgroundColor': 'rgb(20, 20, 20)',
                'color': 'white'
            },
            style_data_conditional=[
                {
                    'if': {'filter_query': '{operation} eq "Купля"'},
                    'backgroundColor': 'rgb(30, 30, 30)',
                    'color': '#3D9970'
                },
                {
                    'if': {'filter_query': '{operation} eq "Продажа"'},
                    'backgroundColor': 'rgb(30, 30, 30)',
                    'color': '#FF0000'
                },
            ]
        ),
        style={'margin-left': '300px'}  # Сдвиг вправо
    )
]

tab6_content = [  # Таблица моих ордеров
    html.Div(id='intermediate-value2', style={'display': 'none'}),
    html.Div(
        dash_table.DataTable(
            id='orders',
            data=df_orders.to_dict('records'),
            page_size=14,
            style_table={'max-width': '50px'},
            style_header={
                'fontWeight': 'bold',
                'backgroundColor': 'rgb(40, 40, 40)',
                'color': 'white',
                'textAlign': 'center'
            },
            style_data={
                'backgroundColor': 'rgb(20, 20, 20)',
                'color': 'white'
            },
            style_data_conditional=[
                {
                    'if': {'filter_query': '{operation} eq "Купля"'},
                    'backgroundColor': 'rgb(20, 20, 20)',
                    'color': '#3D9970'
                },
                {
                    'if': {'filter_query': '{operation} eq "Продажа"'},
                    'backgroundColor': 'rgb(20, 20, 20)',
                    'color': '#FF0000'
                },
            ]
        ),
        style={'margin-left': '400px'}  # Сдвиг вправо
    )
]

tab7_content = [dcc.Graph(id='MyEquityHistory', style={'margin-top': 10})]

# Создаем приложение Dash в тёмной теме
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.DARKLY])

# Установка темной темы для всех графиков
go.Figure(layout=go.Layout(template="plotly_dark"))

app.layout = html.Div(children=[

    html.Div(children=[
        html.Div(children=[
            # График улыбки волатильности
            dcc.Graph(id='plot_smile'),
        ], style={'width': '87%', 'display': 'inline-block'}),

        html.Div(children=[
            # Текущее время обновления данных
            html.H6(id='last_update_time'),

            # Селектор выбора базового актива
            dcc.Dropdown(
                df._base_asset_ticker.unique(),
                value=first_key,
                id='dropdown-selection',
                style={
                    'backgroundColor': '#2d2d2d',
                    'color': 'white',
                    'border': '1px solid #444',
                    'borderRadius': '4px'
                },
                className='dark-dropdown'
            )
            ,

            # Спидометр TrueVega
            # https://stackoverflow.com/questions/69275527/python-dash-gauge-how-can-i-use-strings-as-values-instead-of-numbers
            daq.Gauge(id="graph-gauge",
                      units="TrueVega",
                      label='TrueVega',
                      labelPosition='bottom',
                      color={
                          "ranges": {
                              "red": [0, 2],
                              "pink": [2, 4],
                              "#ADD8E6": [4, 6],
                              "#4169E1": [6, 8],
                              "blue": [8, 10],
                          },
                      },
                      scale={
                          "custom": {
                              1: {"label": "Strong Sell"},
                              3: {"label": "Sell"},
                              5: {"label": "Neutral"},
                              7: {"label": "Buy"},
                              9: {"label": "Strong Buy"},
                          }
                      },
                      value=0,
                      max=10,
                      min=0,
                      ),
        ], style={'display': 'inline-block'}),

    ], style={'display': 'flex', 'flexDirection': 'row'}),

    html.Div(children=[

        dbc.Tabs([
            dbc.Tab(tab1_content, label='MyPos history'),
            dbc.Tab(tab2_content, label='Наклон улыбки'),
            dbc.Tab(tab3_content, label='Volatility history'),
            dbc.Tab(tab4_content, label='MyPos table'),
            dbc.Tab(tab5_content, label='MyTrades table'),
            dbc.Tab(tab6_content, label='MyOrders table'),
            dbc.Tab(tab7_content, label='MyEquity'),
        ]),

        # Интервал обновления данных
        dcc.Interval(
            id='interval-component',
            interval=1000 * 10,
            n_intervals=0),
        # Интервал обновления данных - 10 секунд
        dcc.Interval(
            id='interval-10sec',
            interval=1000 * 10,  # 10 секунд
            n_intervals=0),

        # Интервал обновления данных - 1 минута
        dcc.Interval(
            id='interval-1min',
            interval=1000 * 60,  # 1 минута
            n_intervals=0),

        # Интервал обновления данных - 5 минут
        dcc.Interval(
            id='interval-5min',
            interval=1000 * 60 * 5,  # 5 минут
            n_intervals=0),

        # Интервал обновления данных - 60 минут
        dcc.Interval(
            id='interval-60min',
            interval=1000 * 60 * 60,  # 60 минут
            n_intervals=0),

        # Слайдер
        dcc.Slider(0, 28,
                   id='my_slider',
                   step=None,
                   marks={
                       1: '0.5d',
                       2: '1d',
                       4: '2d',
                       6: '3d',
                       10: '5d',
                       14: '7d',
                       20: '10d',
                       28: '14d'
                   },
                   value=6
                   ),
        html.Div(id='slider-output-1'),
    ])
])


# --- CALLBACKS ---

# Колбэк для очистки данных после каждого обновления данных с периодичностью 10 секунд
@app.callback(Output('intermediate-value', 'children'),
              [Input('interval-component', 'n_intervals')],
              [State('intermediate-value', 'children')])
def clean_data(value, dff):
    pass


# Колбэк для обновления времени последнего обновления данных с периодичностью 10 секунд
@app.callback(Output('last_update_time', 'children'),
              [Input('interval-component', 'n_intervals')])
def update_time(n):
    fetch_api_data()
    # My portfoloio info data
    with open(temp_obj.substitute(name_file='QUIK_MyPortfolioInfo.csv'), 'r') as file:
        info = file.read()
    return [
        'Last update: {}'.format(datetime.now().strftime('%d.%m.%Y %H:%M:%S')),
        html.Br(),
        html.Pre(info)
    ]


# Обновление графика улыбки волатильности
@app.callback(Output('plot_smile', 'figure', allow_duplicate=True),
              [Input('dropdown-selection', 'value'),
               Input('interval-component', 'n_intervals')],
              prevent_initial_call=True)
def update_output_smile(value, n):
    try:

        # Список базовых активов
        base_asset_ticker_list = {}
        for i in range(len(base_asset_list)):
            base_asset_ticker_list.update({base_asset_list[i]['_ticker']: base_asset_list[i]['_base_asset_code']})

        # Список опционов
        df = pd.DataFrame.from_dict(option_list, orient='columns')
        df = df.loc[df['_volatility'] > 0]
        df['_expiration_datetime'] = pd.to_datetime(df['_expiration_datetime'], format='%a, %d %b %Y %H:%M:%S GMT')
        df['_expiration_datetime'].dt.date
        df['expiration_date'] = df['_expiration_datetime'].dt.strftime('%d.%m.%Y')
        dff = df[(df._base_asset_ticker == value)]  # оставим только опционы базового актива

        for asset in base_asset_list:
            if asset['_ticker'] == value:
                base_asset_last_price = asset['_last_price']  # получаем последнюю цену базового актива

        dff_call = dff[(dff._type == 'C')]  # оставим только коллы

        # My positions data
        with open(temp_obj.substitute(name_file='QUIK_MyPos.csv'), 'r') as file:
            df_table = pd.read_csv(file, sep=';')
            df_table_buy = df_table[(df_table.option_base == value) & (df_table.net_pos > 0) & (df_table.OpenIV > 0)]
            df_table_sell = df_table[(df_table.option_base == value) & (df_table.net_pos < 0) & (df_table.OpenIV > 0)]
            MyPos_ticker_list = []
            for i in range(len(df_table)):
                MyPos_ticker_list.append(df_table['ticker'][i])
            # DataFrame для отрисовки баланса TrueVega
            df_table_base = df_table[df_table.option_base == value].copy()  # Добавлен .copy()
        # Close the file explicitly file.close()
        file.close()

        # My orders data
        with open(temp_obj.substitute(name_file='QUIK_Stream_Orders.csv'), 'r', encoding='utf-8') as file:
            df_orders = pd.read_csv(file, sep=';')
            df_orders = df_orders[(df_orders.option_base == value)]
            df_orders_buy = df_orders[(df_orders.option_base == value) & (df_orders.operation == 'Купля')]
            df_orders_sell = df_orders[(df_orders.option_base == value) & (df_orders.operation == 'Продажа')]
            # Converting DataFrame "df_orders" to a list "tikers" containing all the rows of column 'ticker'
            tikers = df_orders['ticker'].tolist()

        # Create figure with secondary y-axis
        fig = make_subplots(specs=[[{"secondary_y": True}]])

        # Рисуем график улыбки
        for exp_day in dff_call['expiration_date'].unique():
            dff_smile = dff_call[dff_call.expiration_date == exp_day]
            fig.add_trace(go.Scatter(x=dff_smile['_strike'], y=dff_smile['_volatility'], mode='lines+text',
                                     name=exp_day), secondary_y=False, )
        # Задаем шаг тиков и форматирование
        strike_step = MAP[value]['strike_step']
        fig.update_xaxes(dtick=strike_step * 2, tickformat=",d")

        # Мои позиции BUY
        fig.add_trace(go.Scatter(x=df_table_buy['strike'], y=df_table_buy['OpenIV'],
                                 mode='markers+text', text=df_table_buy['OpenIV'], textposition='middle left',
                                 marker=dict(size=11, symbol="star-triangle-up-open", color='lightgreen'),
                                 name='My Pos Buy',
                                 customdata=df_table_buy[['option_type', 'net_pos', 'expdate', 'ticker']],
                                 hovertemplate="<b>%{customdata}</b>"
                                 ))

        # Мои позиции SELL
        fig.add_trace(go.Scatter(x=df_table_sell['strike'], y=df_table_sell['OpenIV'],
                                 mode='markers+text', text=df_table_sell['OpenIV'], textposition='middle left',
                                 marker=dict(size=11, symbol="star-triangle-down-open", color='magenta'),
                                 name='My Pos Sell',
                                 customdata=df_table_sell[['option_type', 'net_pos', 'expdate', 'ticker']],
                                 hovertemplate="<b>%{customdata}</b><br>"
                                 ))

        # Мои ордерра BUY
        fig.add_trace(go.Scatter(x=df_orders_buy['strike'], y=df_orders_buy['volatility'],
                                 mode='markers+text', text=df_orders_buy['volatility'], textposition='middle left',
                                 marker=dict(size=8, symbol="cross-thin", line=dict(width=1, color="lightgreen")),
                                 name='My Orders BUY',
                                 customdata=df_orders_buy[['operation', 'option_type', 'expdate', 'price', 'ticker']],
                                 hovertemplate="<b>%{customdata}</b><br>"
                                 ))

        # Мои ордерра SELL
        fig.add_trace(go.Scatter(x=df_orders_sell['strike'], y=df_orders_sell['volatility'],
                                 mode='markers+text', text=df_orders_sell['volatility'], textposition='middle left',
                                 marker=dict(size=8, symbol="cross-thin", line=dict(width=1, color="magenta")),
                                 name='My Orders SELL',
                                 customdata=df_orders_sell[['operation', 'option_type', 'expdate', 'price', 'ticker']],
                                 hovertemplate="<b>%{customdata}</b><br>"
                                 ))

        # Last Bid Ask for MyPos and MyOrders
        favorites_list = MyPos_ticker_list + tikers  # слияние списков
        favorites_ticker_list = set(favorites_list)
        # dff_MyPosOrders = df[(df._base_asset_ticker == value) & (df._ticker.isin(favorites_ticker_list))]
        dff_MyPosOrders = df[(df._base_asset_ticker == value) & (df._ticker.isin(favorites_ticker_list))].copy()
        # Применяем округление только к числовым столбцам
        numeric_columns = dff_MyPosOrders.select_dtypes(include=['number']).columns
        dff_MyPosOrders[numeric_columns] = dff_MyPosOrders[numeric_columns].round(2)
        dff_MyPosOrders.loc[dff_MyPosOrders['_type'] == 'C', '_type'] = 'Call'
        dff_MyPosOrders.loc[dff_MyPosOrders['_type'] == 'P', '_type'] = 'Put'
        # Создаем пустую колонку для хранения преобразованного времени
        # dff_MyPosOrders['converted_time'] = ''
        dff_MyPosOrders.loc[:, 'converted_time'] = ''
        # Преобразование времени из UTC_seconds в MSK_time
        for i in dff_MyPosOrders['_last_price_timestamp']:
            if not isnan(i):  # Проверяем, что значение не NaN
                UTC_seconds = i
                MSK_time = utc_timestamp_to_msk_datetime(UTC_seconds)
                MSK_time_str = MSK_time.strftime('%H:%M:%S')

                # Обновляем соответствующую строку в DataFrame
                mask = dff_MyPosOrders['_last_price_timestamp'] == i
                dff_MyPosOrders.loc[mask, 'converted_time'] = MSK_time_str  # Используем новую колонку или существующую
        # print(dff_MyPosOrders['converted_time'])

        # ASK
        fig.add_trace(go.Scatter(x=dff_MyPosOrders['_strike'], y=dff_MyPosOrders['_ask_iv'],  # visible='legendonly',
                                 mode='markers', text=dff_MyPosOrders['_ask_iv'], textposition='top left',
                                 marker=dict(size=8, symbol="triangle-down", color='red'),
                                 name='Ask',
                                 customdata=dff_MyPosOrders[
                                     ['_type', '_ask', '_ask_iv', 'expiration_date', '_ticker']],
                                 hovertemplate="<b>%{customdata}</b><br>"
                                 ))

        # BID
        fig.add_trace(go.Scatter(x=dff_MyPosOrders['_strike'], y=dff_MyPosOrders['_bid_iv'],  # visible='legendonly',
                                 mode='markers', text=dff_MyPosOrders['_bid_iv'], textposition='top left',
                                 marker=dict(size=8, symbol="triangle-up", color='green'),
                                 name='Bid',
                                 customdata=dff_MyPosOrders[
                                     ['_type', '_bid', '_bid_iv', 'expiration_date', '_ticker']],
                                 hovertemplate="<b>%{customdata}</b><br>"
                                 ))

        # LAST
        fig.add_trace(go.Scatter(x=dff_MyPosOrders['_strike'], y=dff_MyPosOrders['_last_price_iv'],
                                 mode='markers', text=dff_MyPosOrders['_last_price_iv'], textposition='top left',
                                 marker=dict(size=8, color='goldenrod'),
                                 name='Last',
                                 customdata=dff_MyPosOrders[
                                     ['_type', '_last_price', '_last_price_iv', 'expiration_date', '_ticker',
                                      'converted_time']],
                                 hovertemplate="<b>%{customdata}</b><br>"
                                 ))

        # TrueVega позиции
        fig.add_trace(go.Bar(x=df_table_base['strike'], y=df_table_base['TrueVega'], text=df_table_base['TrueVega'],
                             textposition='auto', name='TrueVega', opacity=0.1), secondary_y=True)

        # Цена базового актива (вертикальная линия)
        fig.add_vline(x=base_asset_last_price, line_dash='dash', line_color='firebrick')

        fig.update_layout(height=450,
                          title_text=f"Volatility smile, series <b>{value}<b>", uirevision="Don't change"
                          )

        # Легенда справа по центру
        fig.update_layout(
            legend=dict(
                yanchor="middle",
                y=0.5,
                xanchor="left",
                x=0.96,
                orientation="v"
            )
        )
        fig.update_layout(
            margin=dict(l=1, r=1, t=30, b=0),
        )

        # Обновление сетки - добавьте эти строки перед return fig
        fig.update_xaxes(
            gridwidth=1,  # Толщина горизонтальной сетки
            gridcolor='rgba(128, 128, 128, 0.3)',  # Цвет сетки
            zeroline=False,  # Убрать нулевую линию
            showgrid=True,  # Показать сетку
            tickfont=dict(size=10)  # Размер шрифта меток
        )

        fig.update_yaxes(
            gridwidth=1,  # Толщина горизонтальной сетки
            gridcolor='rgba(128, 128, 128, 0.3)',  # Цвет сетки
            zeroline=False,  # Убрать нулевую линию
            showgrid=True,  # Показать сетку
            tickfont=dict(size=10)  # Размер шрифта меток
        )

        # Для вторичной оси
        fig.update_yaxes(
            secondary_y=True,
            gridwidth=1,  # Толщина горизонтальной сетки
            gridcolor='rgba(128, 128, 128, 0.3)',  # Цвет сетки
            zeroline=False,  # Убрать нулевую линию
            showgrid=True,  # Показать сетку
            tickfont=dict(size=10)  # Размер шрифта меток
        )

        # убрать сетку правой оси
        fig['layout']['yaxis2']['showgrid'] = False

        fig.update_layout(
            plot_bgcolor='rgb(10, 10, 10)',
            paper_bgcolor='rgb(30, 30, 30)',
            font_color='white',
            xaxis=dict(
                gridcolor='rgb(60, 60, 60)',
                gridwidth=1,
                zerolinecolor='rgb(60, 60, 60)'
            ),
            yaxis=dict(
                gridcolor='rgb(60, 60, 60)',
                gridwidth=1,
                zerolinecolor='rgb(60, 60, 60)'
            )
        )

        return fig

    except Exception as e:
        print(f"Ошибка при обновлении графика улыбки волатильности: {str(e)}")
        raise PreventUpdate


# обновление данных графика истории волатильности на центральном страйке
@app.callback(Output('plot_history', 'figure', allow_duplicate=True),
              [Input('dropdown-selection', 'value'),
               Input('my_slider', 'value'),
               Input('my-radio-buttons-final', 'value'),
               Input('interval-component', 'n_intervals'),
               ],
              prevent_initial_call=True)
def update_output_history(dropdown_value, slider_value, radiobutton_value, n):
    global df_candles  # Добавляем объявление глобальной переменной
    limit_time = datetime.now() - timedelta(hours=12 * slider_value)
    # Удаление столбца с индексом
    if 'level_0' in df_candles.columns:
        df_candles = df_candles.drop(columns=['level_0'])
    # Сброс индекса с сохранением datetime как столбца
    df_candles = df_candles.reset_index()
    df_candles = df_candles[(df_candles.datetime > limit_time)]

    # ДАННЫЕ ИЗ DAMP/csv
    # OptionsVolaHistoryDamp.csv history data options volatility
    with open(temp_obj.substitute(name_file='OptionsVolaHistoryDamp.csv'), 'r') as file:
        df_vol_history = pd.read_csv(file, sep=';')
        df_vol_history = df_vol_history[(df_vol_history.base_asset_ticker == dropdown_value)]
        # df_vol_history = df_vol_history.tail(limit * len(df_vol_history['expiration_datetime'].unique()) * 2) # глубина истории по количеству серий

        df_vol_history['DateTime'] = pd.to_datetime(df_vol_history['DateTime'], format='%Y-%m-%d %H:%M:%S')
        df_vol_history.index = pd.DatetimeIndex(df_vol_history['DateTime'])
        df_vol_history = df_vol_history[(df_vol_history.type == radiobutton_value)]
        df_vol_history = df_vol_history[(df_vol_history.DateTime > limit_time)]
        # print(df_vol_history)
    # Close the file
    file.close()

    # Create figure with secondary y-axis
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # График истории волатильности ПО ДАННЫМ ИЗ DAMP (из CSV OptionsVolaHistoryDamp.csv)
    for d_exp in sorted(df_vol_history['expiration_datetime'].unique()):
        dff = df_vol_history[df_vol_history.expiration_datetime == d_exp]
        fig.add_trace(go.Scatter(x=dff['DateTime'], y=dff['Real_vol'], visible='legendonly',
                                 legendgroup="group",  # this can be any string, not just "group"
                                 legendgrouptitle_text="RealVol",
                                 mode='lines+text',
                                 name=d_exp), secondary_y=True, )
    fig.update_layout(legend_title_text=radiobutton_value)

    # График истории БИРЖЕВОЙ волатильности (из CSV OptionsVolaHistoryDamp.csv)
    for d_exp in sorted(df_vol_history['expiration_datetime'].unique()):
        dff = df_vol_history[df_vol_history.expiration_datetime == d_exp]
        fig.add_trace(go.Scatter(x=dff['DateTime'], y=dff['Quik_vol'], visible='legendonly',
                                 legendgroup="group2",
                                 legendgrouptitle_text="QuikVol",
                                 mode='lines+text',
                                 line=dict(width=2, dash='dashdot'),
                                 name=d_exp), secondary_y=True, )
    fig.update_layout(legend=dict(groupclick="toggleitem"))

    # График Candles
    fig.add_trace(go.Candlestick(x=df_candles['datetime'],
                                 open=df_candles['open'],
                                 high=df_candles['high'],
                                 low=df_candles['low'],
                                 close=df_candles['close'],
                                 name=f"{dropdown_value} {time_frame}",
                                 increasing_line=dict(width=1),
                                 decreasing_line=dict(width=1)),
                  secondary_y=False)

    # Убираем неторговое время
    fig.update_xaxes(
        rangebreaks=[
            dict(bounds=["sat", "mon"]),  # hide weekends, eg. hide sat to before mon
            dict(bounds=[24, 9], pattern="hour"),  # hide hours outside of 9am-24pm
        ]
    )

    fig.update_layout(xaxis_title=None)
    # Легенда справа по центру
    fig.update_layout(
        legend=dict(
            yanchor="middle",
            y=0.5,
            xanchor="left",
            x=0.96,
            orientation="v"
        )
    )

    fig.update_layout(
        title_text=f'Central strike volatility history, put or call option series <b>{dropdown_value}<b>',
        uirevision="Don't change"
    )
    fig.update_layout(
        margin=dict(l=5, r=5, t=30, b=0),
    )

    # Обновление сетки - добавьте эти строки перед return fig
    fig.update_xaxes(
        gridwidth=1,  # Толщина горизонтальной сетки
        gridcolor='rgba(128, 128, 128, 0.3)',  # Цвет сетки
        zeroline=False,  # Убрать нулевую линию
        showgrid=True,  # Показать сетку
        tickfont=dict(size=10)  # Размер шрифта меток
    )

    fig.update_yaxes(
        gridwidth=1,  # Толщина горизонтальной сетки
        gridcolor='rgba(128, 128, 128, 0.3)',  # Цвет сетки
        zeroline=False,  # Убрать нулевую линию
        showgrid=True,  # Показать сетку
        tickfont=dict(size=10)  # Размер шрифта меток
    )

    # Для вторичной оси
    fig.update_yaxes(
        secondary_y=True,
        gridwidth=1,  # Толщина горизонтальной сетки
        gridcolor='rgba(128, 128, 128, 0.3)',  # Цвет сетки
        zeroline=False,  # Убрать нулевую линию
        showgrid=True,  # Показать сетку
        tickfont=dict(size=10)  # Размер шрифта меток
    )

    # Убрать сетку левой оси
    fig['layout']['yaxis']['showgrid'] = False

    fig.update_layout(
        plot_bgcolor='rgb(10, 10, 10)',  # Фон графика
        paper_bgcolor='rgb(30, 30, 30)',  # Фон области рисования
        font_color='white',  # Цвет текста
        xaxis=dict(  # Цвет вертикальных линий сетки
            gridcolor='rgb(60, 60, 60)',
            gridwidth=1,
            zerolinecolor='rgb(60, 60, 60)'
        ),
        yaxis=dict(  # Цвет горизонтальных линий сетки
            gridcolor='rgb(50, 50, 50)',
            gridwidth=0.5,
            zerolinecolor='rgb(50, 50, 50)'
        )
    )

    return fig


# Обновление данных графика истории моей позиции
@app.callback(Output('MyPosTiltHistory', 'figure', allow_duplicate=True),
              [Input('dropdown-selection', 'value'),
               Input('my_slider', 'value'),
               Input('interval-component', 'n_intervals'),
               ],
              prevent_initial_call=True)
def update_output_MyPosHistory(dropdown_value, slider_value, n):
    global df_candles  # Добавляем объявление глобальной переменной

    limit_time = datetime.now() - timedelta(hours=12 * slider_value)

    # СВЕЧИ Данные для графика базового актива
    dataname = f'SPBFUT.{dropdown_value}'
    time_frame = 'M15'
    # Будем запрашивать глубину истории 140 дней
    dt_from = datetime.now() - timedelta(days=140)

    df_candles = get_candles_request(dataname, time_frame, dt_from)
    # Удаление столбца с индексом
    if 'level_0' in df_candles.columns:
        df_candles = df_candles.drop(columns=['level_0'])
    # Сброс индекса с сохранением datetime как столбца
    df_candles = df_candles.reset_index()
    df_candles = df_candles[(df_candles.datetime > limit_time)]

    # ДАННЫЕ ИЗ csv
    # MyPosHistory.csv history data options volatility
    with open(temp_obj.substitute(name_file='MyPosHistory.csv'), 'r') as file:
        df_MyPosHistory = pd.read_csv(file, sep=';')
        df_MyPosHistory = df_MyPosHistory[(df_MyPosHistory.option_base == dropdown_value)]

        df_MyPosHistory['DateTime'] = pd.to_datetime(df_MyPosHistory['DateTime'],
                                                     format='%Y-%m-%d %H:%M:%S')
        df_MyPosHistory.index = pd.DatetimeIndex(df_MyPosHistory['DateTime'])
        # df_MyPosHistory = df_MyPosHistory[(df_vol_history.type == radiobutton_value)]
        df_MyPosHistory = df_MyPosHistory[(df_MyPosHistory.DateTime > limit_time)]
        # print(df_MyPosHistory)
    # Close the file
    file.close()

    # Данные о сделках
    # My trades data
    with open(temp_obj.substitute(name_file='QUIK_Stream_Trades.csv'), 'r', encoding='UTF-8') as file:
        df_trades = pd.read_csv(file, sep=';')
        df_trades = df_trades[(df_trades.option_base == dropdown_value)]
        df_trades['datetime'] = pd.to_datetime(df_trades['datetime'],
                                               format='%d.%m.%Y %H:%M:%S')
        df_trades.index = pd.DatetimeIndex(df_trades['datetime'])
        df_trades = df_trades[(df_trades.datetime > limit_time)]
        # print(df_table)
        # Создаем столбец 'pos' в df_trades на основе значений из df_table
        df_table['pos'] = df_table['net_pos'].apply(lambda x: 'long' if x > 0 else 'short')
        df_trades = df_trades.merge(df_table[['ticker', 'pos']], on='ticker', how='left')
        # Удаляем строки, где 'pos' равен NaN
        df_trades = df_trades.dropna(subset=['pos'])
    file.close()

    # Create figure with secondary y-axis
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # График истории моей позиции (из MyPosHistory.cs)
    for pos in sorted(df_MyPosHistory['pos'].unique(), reverse=True):
        dff = df_MyPosHistory[df_MyPosHistory.pos == pos]
        fig.add_trace(go.Scatter(x=dff['DateTime'], y=dff['mypos'], visible='legendonly',
                                 legendgroup=pos,  # this can be any string, not just "group"
                                 legendgrouptitle_text=pos,
                                 mode='lines+text',
                                 line=dict(dash='dot'),
                                 name='MyPos'), secondary_y=True, )

    # График истории моей позиции ПО теоретической цене из MyPosHistory
    for pos in sorted(df_MyPosHistory['pos'].unique()):
        dff = df_MyPosHistory[df_MyPosHistory.pos == pos]
        fig.add_trace(go.Scatter(x=dff['DateTime'], y=dff['last'],
                                 legendgroup=pos,  # this can be any string, not just "group"
                                 legendgrouptitle_text=pos,
                                 mode='lines+text',
                                 name='Last'), secondary_y=True, )

    # График истории моей позиции по цене LAST (из MyPosHistory.csv)
    for pos in sorted(df_MyPosHistory['pos'].unique(), reverse=True):
        dff = df_MyPosHistory[df_MyPosHistory.pos == pos]
        fig.add_trace(go.Scatter(x=dff['DateTime'], y=dff['theor'],
                                 legendgroup=pos,
                                 legendgrouptitle_text=pos,
                                 mode='lines+text',
                                 line=dict(color='gray', width=1, dash='dot'),
                                 name='Theor'), secondary_y=True, )

    # График истории моей позиции ПО рынку из MyPosHistory
    for pos in sorted(df_MyPosHistory['pos'].unique(), reverse=True):
        dff = df_MyPosHistory[df_MyPosHistory.pos == pos]
        fig.add_trace(go.Scatter(x=dff['DateTime'], y=dff['market'], visible='legendonly',
                                 legendgroup=pos,  # this can be any string, not just "group"
                                 legendgrouptitle_text=pos,
                                 mode='lines+text',
                                 name='Market'), secondary_y=True, )

    # Мои сделки (trades) на графике
    for opt in sorted(df_trades['ticker'].unique()):
        df_ticker = df_trades[df_trades.ticker == opt]

        # Создаем отдельные серии для покупок и продаж
        df_buy = df_ticker[df_ticker['operation'] == 'Купля']
        df_sell = df_ticker[df_ticker['operation'] == 'Продажа']
        if not df_buy.empty:
            pos = df_buy['pos'].iloc[0]
            fig.add_trace(go.Scatter(x=df_buy['datetime'], y=df_buy['volatility'], visible='legendonly',
                                     legendgroup=pos,
                                     legendgrouptitle_text=pos,
                                     mode='markers', text=df_buy['volatility'], textposition='top left',
                                     marker=dict(size=8, symbol="triangle-up", color='green'),
                                     name=f'{opt} (купля)',
                                     customdata=df_buy[
                                         ['volatility', 'option_type', 'price', 'volume', 'expdate']],
                                     hovertemplate="<b>%{customdata}</b><br>"
                                     ), secondary_y=True, )

        if not df_sell.empty:
            pos = df_sell['pos'].iloc[0]
            fig.add_trace(go.Scatter(x=df_sell['datetime'], y=df_sell['volatility'], visible='legendonly',
                                     legendgroup=pos,
                                     legendgrouptitle_text=pos,
                                     mode='markers', text=df_sell['volatility'], textposition='top left',
                                     marker=dict(size=8, symbol="triangle-down", color='red'),
                                     name=f'{opt} (продажа)',
                                     customdata=df_sell[
                                         ['volatility', 'option_type', 'price', 'volume', 'expdate']],
                                     hovertemplate="<b>%{customdata}</b><br>"
                                     ), secondary_y=True, )

    fig.update_layout(legend=dict(groupclick="toggleitem"))

    # График Candles
    fig.add_trace(go.Candlestick(x=df_candles['datetime'],
                                 open=df_candles['open'],
                                 high=df_candles['high'],
                                 low=df_candles['low'],
                                 close=df_candles['close'],
                                 name=f"{dropdown_value} {time_frame}",
                                 increasing_line=dict(width=1),
                                 decreasing_line=dict(width=1)),
                  secondary_y=False)

    # Убираем неторговое время
    fig.update_xaxes(
        rangebreaks=[
            dict(bounds=["sat", "mon"]),  # hide weekends, eg. hide sat to before mon
            dict(bounds=[24, 9], pattern="hour"),  # hide hours outside of 9am-24pm
        ]
    )

    fig.update_layout(xaxis_title=None)
    # Легенда справа по центру
    fig.update_layout(
        legend=dict(
            yanchor="middle",
            y=0.5,
            xanchor="left",
            x=0.96,
            orientation="v"
        )
    )

    # fig.update_layout(
    #     title_text=f'История моей позиции, option series <b>{dropdown_value}<b>', uirevision="Don't change"
    # )
    fig.update_layout(uirevision="Don't change")
    fig.update_layout(
        margin=dict(l=3, r=3, t=0, b=0),
    )

    # Обновление сетки - добавьте эти строки перед return fig
    fig.update_xaxes(
        gridwidth=1,  # Толщина горизонтальной сетки
        gridcolor='rgba(128, 128, 128, 0.3)',  # Цвет сетки
        zeroline=False,  # Убрать нулевую линию
        showgrid=True,  # Показать сетку
        tickfont=dict(size=10)  # Размер шрифта меток
    )

    fig.update_yaxes(
        gridwidth=1,  # Толщина горизонтальной сетки
        gridcolor='rgba(128, 128, 128, 0.3)',  # Цвет сетки
        zeroline=False,  # Убрать нулевую линию
        showgrid=True,  # Показать сетку
        tickfont=dict(size=10)  # Размер шрифта меток
    )

    # Для вторичной оси
    fig.update_yaxes(
        secondary_y=True,
        gridwidth=1,  # Толщина горизонтальной сетки
        gridcolor='rgba(128, 128, 128, 0.3)',  # Цвет сетки
        zeroline=False,  # Убрать нулевую линию
        showgrid=True,  # Показать сетку
        tickfont=dict(size=10)  # Размер шрифта меток
    )

    # Убрать сетку левой оси
    fig['layout']['yaxis']['showgrid'] = False

    fig.update_layout(
        plot_bgcolor='rgb(10, 10, 10)',
        paper_bgcolor='rgb(30, 30, 30)',
        font_color='white',
        xaxis=dict(
            gridcolor='rgb(60, 60, 60)',
            gridwidth=1,
            zerolinecolor='rgb(60, 60, 60)'
        ),
        yaxis=dict(
            gridcolor='rgb(60, 60, 60)',
            gridwidth=1,
            zerolinecolor='rgb(60, 60, 60)'
        )
    )

    return fig


# Наклон улыбки (обновление данных графика истории наклона улыбки)
@app.callback(Output('naklon_history', 'figure', allow_duplicate=True),
              [Input('dropdown-selection', 'value'),
               Input('my_slider', 'value'),
               Input('interval-component', 'n_intervals'),
               ],
              prevent_initial_call=True)
def update_output_history_naklon(dropdown_value, slider_value, n):
    global df_candles  # Добавляем объявление глобальной переменной
    limit_time = datetime.now() - timedelta(hours=12 * slider_value)
    # Удаление столбца с индексом
    if 'level_0' in df_candles.columns:
        df_candles = df_candles.drop(columns=['level_0'])
    # Сброс индекса с сохранением datetime как столбца
    df_candles = df_candles.reset_index()
    df_candles = df_candles[(df_candles.datetime > limit_time)]

    # ДАННЫЕ ИЗ DAMP/csv
    # OptionsSmileNaklonHistory.csv history data options volatility
    with open(temp_obj.substitute(name_file='OptionsSmileNaklonHistory.csv'), 'r') as file:
        df_vol_history_naklon = pd.read_csv(file, sep=';')
        df_vol_history_naklon = df_vol_history_naklon[(df_vol_history_naklon.base_asset_ticker == dropdown_value)]
        # df_vol_history_naklon = df_vol_history_naklon.tail(limit * len(df_vol_history_naklon['expiration_datetime'].unique()) * 2) # глубина истории по количеству серий

        df_vol_history_naklon['DateTime'] = pd.to_datetime(df_vol_history_naklon['DateTime'],
                                                           format='%Y-%m-%d %H:%M:%S')
        df_vol_history_naklon.index = pd.DatetimeIndex(df_vol_history_naklon['DateTime'])
        # df_vol_history_naklon = df_vol_history_naklon[(df_vol_history.type == radiobutton_value)]
        df_vol_history_naklon = df_vol_history_naklon[(df_vol_history_naklon.DateTime > limit_time)]
        # print(df_vol_history_naklon)
    # Close the file
    file.close()

    # Create figure with secondary y-axis
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # График истории наклона улыбки ПО ДАННЫМ ИЗ DAMP (из CSV OptionsSmileNaklonHistory.csv)
    for d_exp in sorted(df_vol_history_naklon['expiration_datetime'].unique()):
        dff = df_vol_history_naklon[df_vol_history_naklon.expiration_datetime == d_exp]
        fig.add_trace(go.Scatter(x=dff['DateTime'], y=dff['Real'], visible='legendonly',
                                 legendgroup="group",  # this can be any string, not just "group"
                                 legendgrouptitle_text="Real",
                                 mode='lines+text',
                                 name=d_exp), secondary_y=True, )
    # fig.update_layout(legend_title_text=radiobutton_value)

    # График истории наклона БИРЖЕВОЙ улыбки (из CSV OptionsSmileNaklonHistory.csv)
    for d_exp in sorted(df_vol_history_naklon['expiration_datetime'].unique()):
        dff = df_vol_history_naklon[df_vol_history_naklon.expiration_datetime == d_exp]
        fig.add_trace(go.Scatter(x=dff['DateTime'], y=dff['Quik'], visible='legendonly',
                                 legendgroup="group2",
                                 legendgrouptitle_text="Quik",
                                 mode='lines+text',
                                 line=dict(width=1, dash='dashdot'),
                                 name=d_exp), secondary_y=True, )
    fig.update_layout(legend=dict(groupclick="toggleitem"))

    # График Candles
    fig.add_trace(go.Candlestick(x=df_candles['datetime'],
                                 open=df_candles['open'],
                                 high=df_candles['high'],
                                 low=df_candles['low'],
                                 close=df_candles['close'],
                                 name=f"{dropdown_value} {time_frame}",
                                 increasing_line=dict(width=1),
                                 decreasing_line=dict(width=1)),
                  secondary_y=False)

    # Убираем неторговое время
    fig.update_xaxes(
        rangebreaks=[
            dict(bounds=["sat", "mon"]),  # hide weekends, eg. hide sat to before mon
            dict(bounds=[24, 9], pattern="hour"),  # hide hours outside of 9am-24pm
        ]
    )

    fig.update_layout(xaxis_title=None)
    # Легенда справа по центру
    fig.update_layout(
        legend=dict(
            yanchor="middle",
            y=0.5,
            xanchor="left",
            x=0.96,
            orientation="v"
        )
    )

    # fig.update_layout(
    #     title_text=f'"Наклон улыбки" of the option series <b>{dropdown_value}<b>', uirevision="Don't change"
    # )
    fig.update_layout(uirevision="Don't change")
    fig.update_layout(
        margin=dict(l=3, r=3, t=0, b=0),
    )

    fig.update_layout(
        plot_bgcolor='rgb(10, 10, 10)',
        paper_bgcolor='rgb(30, 30, 30)',
        font_color='white',
        xaxis=dict(
            gridcolor='rgb(50, 50, 50)',
            gridwidth=0.5,
            zerolinecolor='rgb(50, 50, 50)'
        ),
        yaxis=dict(
            gridcolor='rgb(60, 60, 60)',
            gridwidth=1,
            zerolinecolor='rgb(60, 60, 60)'
        )
    )

    # Обновление сетки - добавьте эти строки перед return fig
    fig.update_xaxes(
        gridwidth=1,  # Толщина горизонтальной сетки
        gridcolor='rgba(128, 128, 128, 0.3)',  # Цвет сетки
        zeroline=False,  # Убрать нулевую линию
        showgrid=True,  # Показать сетку
        tickfont=dict(size=10)  # Размер шрифта меток
    )

    fig.update_yaxes(
        gridwidth=1,  # Толщина горизонтальной сетки
        gridcolor='rgba(128, 128, 128, 0.3)',  # Цвет сетки
        zeroline=False,  # Убрать нулевую линию
        showgrid=True,  # Показать сетку
        tickfont=dict(size=10)  # Размер шрифта меток
    )

    # Для вторичной оси
    fig.update_yaxes(
        secondary_y=True,
        gridwidth=1,  # Толщина горизонтальной сетки
        gridcolor='rgba(128, 128, 128, 0.3)',  # Цвет сетки
        zeroline=False,  # Убрать нулевую линию
        showgrid=True,  # Показать сетку
        tickfont=dict(size=10)  # Размер шрифта меток
    )

    # Убрать сетку левой оси
    fig['layout']['yaxis']['showgrid'] = False

    return fig


## EQUITY HISTORY##
@app.callback(Output('MyEquityHistory', 'figure'),
              [Input('dropdown-selection', 'value'),
               Input('my_slider', 'value'),
               Input('interval-component', 'n_intervals * 2')],
              prevent_initial_call=True)
def update_equity_history(dropdown_value, slider_value, n):
    global df_combined
    limit_time = datetime.now() - timedelta(hours=10 * 12 * slider_value)
    # Создаем копию для избежания предупреждения
    df_limited = df_combined[(df_combined.Date > limit_time)].copy()
    # Преобразуем формат даты
    df_limited['Date'] = pd.to_datetime(df_limited['Date'], format='%d.%m.%Y')

    # СВЕЧИ Данные для графика базового актива

    # Будем запрашивать глубину истории 140 дней
    dt_from = datetime.now() - timedelta(days=140)
    time_frame = 'D1'
    dataname = f'SPBFUT.{dropdown_value}'

    broker = brokers['АС']  # Брокер по ключу из Config.py словаря brokers
    symbol = broker.get_symbol_by_dataname(dataname)  # Тикер по названию
    bars = broker.get_history(symbol, time_frame, dt_from=dt_from)  # Получаем историю тикера за 140 дней
    print(f"Запрос свечей: {dataname} {time_frame} начиная с даты {dt_from}")
    # print(f"Первый бар: {bars[0]}")  # Первый бар
    # print(f"Последний бар: {bars[-1]}")  # Последний бар
    df_candles = bars_to_df(bars)  # Все бары в pandas DataFrame pd_bars
    # print(df_candles)  # Все бары в pandas DataFrame pd_bars
    df_candles.reset_index(inplace=True)
    df_candles['datetime'] = pd.to_datetime(df_candles['datetime'], format='%d.%m.%Y %H:%M')
    df_candles = df_candles[(df_candles.datetime > limit_time)]
    # print(f"Данные свечей df_candles: {df_candles}")  # Все бары в pandas DataFrame pd_bars

    # Вычисление доходности
    if len(df_limited) > 1:
        initial_money = df_limited['Money'].iloc[0]
        final_money = df_limited['Money'].iloc[-1]
        profit = ((final_money - initial_money) / initial_money) * 100
        profit_year = profit * 365 / (slider_value * 5)
    else:
        profit = 0
        profit_year = 0

    # Create figure with secondary y-axis
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # График Money
    fig.add_trace(go.Scatter(x=df_limited['Date'], y=df_limited['Money'], mode='lines+text',
                             name='Money',
                             line=dict(color='red', width=3, dash='dashdot')),
                  secondary_y=True)

    # График GM
    fig.add_trace(go.Scatter(x=df_limited['Date'], y=df_limited['GM'], mode='lines+text',
                             name='GM', visible='legendonly',
                             line=dict(color='gray', width=1, dash='dashdot')),
                  secondary_y=True)

    # График Fee
    fig.add_trace(go.Scatter(x=df_limited['Date'], y=df_limited['Fee'], mode='lines+text',
                             name="Comiss",
                             visible='legendonly',
                             line=dict(color='gray', width=1, dash='dashdot')),
                  secondary_y=True)

    # График Candles
    fig.add_trace(go.Candlestick(x=df_candles['datetime'],
                                 open=df_candles['open'],
                                 high=df_candles['high'],
                                 low=df_candles['low'],
                                 close=df_candles['close'],
                                 name=f"{dropdown_value} {time_frame}",
                                 increasing_line=dict(width=1),
                                 decreasing_line=dict(width=1)),
                  secondary_y=False)

    fig.update_layout(
        annotations=[
            dict(
                x=0.94,
                y=0.11,
                xref="paper",
                yref="paper",
                text=f'Доходность за период {slider_value * 5} дн. в процентах: {profit:.2f}%',
                showarrow=False,
                xanchor='right',
                yanchor='top'
            ),
            dict(
                x=0.94,
                y=0.11,
                xref="paper",
                yref="paper",
                text=f'Доходность за период в процентах годовых: {profit_year:.2f}%',
                showarrow=False,
                xanchor='right',
                yanchor='top',
                yshift=-20
            )
        ]
    )
    # # Убираем неторговое время
    # fig.update_xaxes(
    #     rangebreaks=[
    #         dict(bounds=["sat", "mon"]),  # hide weekends, eg. hide sat to before mon
    #     ]
    # )
    # Убираем выходные дни
    fig.update_xaxes(
        rangebreaks=[
            dict(bounds=["sat", "mon"]),  # hide weekends, eg. hide sat to before mon
        ]
    )

    fig.update_layout(xaxis_title=None)
    # Легенда справа по центру
    fig.update_layout(
        legend=dict(
            yanchor="middle",
            y=0.5,
            xanchor="left",
            x=0.96,
            orientation="v"
        )
    )

    fig.update_layout(uirevision="Don't change")
    fig.update_layout(
        margin=dict(l=3, r=3, t=0, b=0),
    )

    # Убрать сетку левой оси
    fig['layout']['yaxis']['showgrid'] = False

    # В конце функции update_output_history перед return fig
    fig.update_layout(
        xaxis=dict(
            gridwidth=1,
            gridcolor='rgba(128, 128, 128, 0.3)'
        ),
        yaxis=dict(
            gridwidth=1,
            gridcolor='rgba(128, 128, 128, 0.3)'
        ),
        yaxis2=dict(  # Для вторичной оси
            gridwidth=1,
            gridcolor='rgba(128, 128, 128, 0.3)'
        )
    )

    fig.update_layout(
        plot_bgcolor='rgb(10, 10, 10)',
        paper_bgcolor='rgb(30, 30, 30)',
        font_color='white'
    )

    return fig


# Callback to update the table "MyPos Table"
@app.callback(
    Output('table', 'data', allow_duplicate=True),
    [Input('interval-component', 'n_intervals'),
     Input('dropdown-selection', 'value')],
    prevent_initial_call=True)
def updateTable(n, value):
    # Инициализируем df_pos заранее
    df_pos = pd.DataFrame()
    # Находим цену базового актива
    asset_price = None
    for asset in base_asset_list:
        if asset['_ticker'] == value:
            asset_price = asset['_last_price']
            break
    # print(f'asset_price - Цена базового актива {value}: {asset_price}')

    # Список опционов из Damp
    df_pos_finam = pd.DataFrame.from_dict(option_list, orient='columns')
    df_pos_finam = df_pos_finam.loc[df_pos_finam['_volatility'] > 0]
    # Получаем данные портфеля брокера Финам
    portfolio_positions_finam = []
    broker = brokers['Ф']  # Брокер по ключу из Config.py словаря brokers
    for position in broker.get_positions():  # Пробегаемся по всем позициям брокера
        # Проверяем, что позиция принадлежит SPBOPT и не равна 0
        if position.dataname.split('.')[0] == 'SPBOPT' and position.quantity != 0:
            ticker = position.dataname.split('.')[1] # Тикер позиции
            # print(f'ticker - Тикер позиции: {ticker}')
            # Найти значение '_base_asset_ticker' для заданного '_ticker'
            # Создаем копию DataFrame
            filtered_df = df_pos_finam[df_pos_finam['_ticker'] == ticker].copy()
            # print(f'filtered_df - Фильтрованный DataFrame: {filtered_df}')
            filtered_df.loc[:, '_expiration_datetime'] = pd.to_datetime(filtered_df['_expiration_datetime'],
                                                                        format='%a, %d %b %Y %H:%M:%S GMT')
            # filtered_df.loc[:, 'expiration_date'] = filtered_df['_expiration_datetime'].dt.strftime('%d.%m.%Y')
            # Преобразуем дату с обработкой ошибок
            filtered_df['_expiration_datetime'] = pd.to_datetime(filtered_df['_expiration_datetime'],
                                                                 format='%a, %d %b %Y %H:%M:%S GMT',
                                                                 errors='coerce')

            # Проверяем, что дата корректна, прежде чем использовать .dt accessor
            mask = filtered_df['_expiration_datetime'].notna()
            filtered_df.loc[mask, 'expiration_date'] = filtered_df.loc[mask, '_expiration_datetime'].dt.strftime(
                '%d.%m.%Y')
            filtered_df.loc[~mask, 'expiration_date'] = None  # Для некорректных дат
            # print(filtered_df['expiration_date'])
            # base_asset_ticker = filtered_df['_base_asset_ticker'].iloc[0]
            # print(f'base_asset_ticker - Базовый актив {value}: {base_asset_ticker}')

            # Берём только SPBOPT (опционы) соответствующего базового актива value
            if not filtered_df.empty and filtered_df['_base_asset_ticker'].iloc[0] == value:
                base_asset_ticker = value
                offer_price = filtered_df['_ask'].iloc[0]
                opt_volatility_offer = filtered_df['_ask_iv'].iloc[0]
                bid_price = filtered_df['_bid'].iloc[0]
                opt_volatility_bid = filtered_df['_bid_iv'].iloc[0]
                expiration_datetime = filtered_df['_expiration_datetime'].iloc[0]
                opt_price = filtered_df['_last_price'].iloc[0]
                opt_volatility_last = filtered_df['_last_price_iv'].iloc[0]
                last_price_timestamp = filtered_df['_last_price_timestamp'].iloc[0]
                real_vol = filtered_df['_real_vol'].iloc[0]
                strike_price = filtered_df['_strike'].iloc[0]
                option_type = filtered_df['_type'].iloc[0]
                VOLATILITY = filtered_df['_volatility'].iloc[0]

                # Получить количество позиций по соответствующему тикеру из portfolio_positions
                net_pos = position.quantity
                # print(f'Net position: {ticker}, количество: {net_pos}')

                # Время последней сделки last_time
                last_datetime = utc_timestamp_to_msk_datetime(last_price_timestamp)
                last_time = last_datetime.strftime("%H:%M:%S")
                # print(f"Время последней сделки: {last_time}")

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

                # Число дней до экспирации
                DAYS_TO_MAT_DATE = (expiration_datetime - datetime.today()).days
                # print(f"Число дней до исполнения инструмента: {DAYS_TO_MAT_DATE}")

                option = Option(ticker, base_asset_ticker, datetime.combine(expiration_datetime, datetime.min.time()), strike_price,
                                option_type)

                # Время до исполнения инструмента в долях года
                time_to_maturity = option.get_time_to_maturity()
                # print(f'time_to_maturity - Время до исполнения инструмента в долях года: {time_to_maturity}')

                # Вычисление Vega
                sigma = VOLATILITY / 100
                vega = implied_volatility._vega(asset_price, sigma, strike_price, time_to_maturity,
                                                implied_volatility._RISK_FREE_INTEREST_RATE,
                                                option_type)
                Vega = vega / 100
                # print(f"Vega: {Vega}")

                # Вычисление TrueVega
                if DAYS_TO_MAT_DATE == 0:
                    TrueVega = 0
                else:
                    TrueVega = Vega / (DAYS_TO_MAT_DATE ** 0.5)

                # theor_price = get_ticker_info_alor(position.dataname)

                # Формируем словарь для DataFrame
                position_data = {
                    'ticker': ticker,
                    'net_pos': net_pos,
                    'strike': strike_price,
                    'option_type': 'Call' if option_type == 'C' else 'Put',
                    'expdate': expiration_datetime.strftime('%d.%m.%Y'),
                    'option_base': base_asset_ticker,
                    'OpenDateTime': open_datetime,
                    'OpenPrice': round(open_price, 2) if open_price is not None else open_price,
                    'OpenIV': round(open_iv, 2) if open_iv is not None else open_iv,
                    'time_last': last_time,
                    'bid': bid_price,
                    'last': opt_price,
                    'ask': offer_price,
                    # 'theor': 0, # theor_price,
                    'QuikVola': VOLATILITY,
                    'bidIV': round(opt_volatility_bid, 2) if opt_volatility_bid is not None else 0,
                    'lastIV': round(opt_volatility_last, 2) if opt_volatility_last is not None else 0,
                    'askIV': round(opt_volatility_offer, 2) if opt_volatility_offer is not None else 0,
                    'P/L theor': round(VOLATILITY - open_iv, 2) if net_pos > 0 else round(open_iv - VOLATILITY, 2),
                    # 'P/L last': 0 if opt_volatility_last == 0 else (round(opt_volatility_last - open_iv, 2) if net_pos > 0 else round(open_iv - opt_volatility_last, 2)),
                    'P/L last': 0 if opt_volatility_last is None or opt_volatility_last == 0 or open_iv is None else (
                        round(opt_volatility_last - open_iv, 2) if net_pos > 0 else round(open_iv - opt_volatility_last, 2)),
                    'P/L market': round(opt_volatility_bid - open_iv, 2) if (net_pos > 0 and opt_volatility_bid is not None) else round(open_iv - opt_volatility_offer, 2) if opt_volatility_offer is not None else None,
                    'Vega': round(Vega * net_pos, 2),
                    'TrueVega': round(TrueVega * net_pos, 2)
                }
                # Добавляем позиции в портфель
                portfolio_positions_finam.append(position_data)
    # print(f'portfolio_positions_finam {portfolio_positions_finam}')

    # Сохраняем в CSV файл
    if portfolio_positions_finam:
        df_pos = pd.DataFrame(portfolio_positions_finam)
        df_pos.to_csv(temp_obj.substitute(name_file='MyPosFinam.csv'),
                            sep=';', encoding='utf-8', index=False)
    else:
        # Создаем пустой файл с заголовками
        empty_df = pd.DataFrame(columns=[
            'ticker', 'net_pos', 'strike', 'option_type', 'expdate', 'option_base',
            'OpenDateTime', 'OpenPrice', 'OpenIV', 'time_last', 'bid', 'last', 'ask',
            'QuikVola', 'bidIV', 'lastIV', 'askIV', 'P/L theor', 'P/L last', 'P/L market',
            'Vega', 'TrueVega'
        ])
        empty_df.to_csv(temp_obj.substitute(name_file='MyPosFinam.csv'),
                        sep=';', encoding='utf-8', index=False)






    # df_pos = pd.read_csv(temp_obj.substitute(name_file='MyPosFinam.csv'), sep=';')
    # Фильтрация строк по базовому активу
    # df_pos = df_pos[df_pos['option_base'] == value]
    if value is not None:
        df_pos = df_table_base[df_table_base.option_base == value]

    # Замена нулевых значений 'P/L last' на значения 'P/L theor'
    df_pos['P/L last'] = df_pos['P/L last'].mask(df_pos['P/L last'] == 0, df_pos['P/L theor'])

    # Вычисление итогов по колонке net_pos
    total_net_pos = df_pos['net_pos'].sum()
    # total_theor = df_pos['theor'].sum()
    # total_theor = (df_pos['theor'] * df_pos['net_pos']).sum()
    total_last = df_pos['last'].sum()

    # # Расчет весов theor
    # weights_theor = df_pos['theor'] * abs(df_pos['net_pos'])
    # total_weight_theor = weights_theor.sum()

    # Last
    weights_last = df_pos['last'] * abs(df_pos['net_pos'])
    total_weight_last = weights_last.sum()

    # Market
    # Раздельное вычисление total_weight_bid и total_weight_ask для weighted_pl_market
    # Для положительных значений net_pos (длинные позиции)
    mask_long = df_pos['net_pos'] > 0
    weights_bid = df_pos.loc[mask_long, 'bid'] * df_pos.loc[mask_long, 'net_pos']
    total_weight_bid = weights_bid.sum()

    # Для отрицательных значений net_pos (короткие позиции)
    mask_short = df_pos['net_pos'] < 0
    weights_ask = df_pos.loc[mask_short, 'ask'] * abs(df_pos.loc[mask_short, 'net_pos'])
    total_weight_ask = weights_ask.sum()

    # Расчет weighted_pl_market с использованием тех же масок
    weighted_pl_market_pos = (df_pos.loc[mask_long, 'P/L market'] * df_pos.loc[mask_long, 'bid'] * df_pos.loc[
        mask_long, 'net_pos']).sum()
    weighted_pl_market_neg = (df_pos.loc[mask_short, 'P/L market'] * df_pos.loc[mask_short, 'ask'] * abs(
        df_pos.loc[mask_short, 'net_pos'])).sum()

    # Общий взвешенный P/L market
    total_weight = total_weight_bid + total_weight_ask
    weighted_pl_market = (weighted_pl_market_pos + weighted_pl_market_neg) / total_weight if total_weight != 0 else 0

    # Проверка на существование колонок перед вычислением
    # weighted_pl_theor = (df_pos['P/L theor'] * weights_theor).sum() / total_weight_theor if 'P/L theor' in df_pos.columns and total_weight_theor != 0 else 0
    weighted_pl_last = (df_pos['P/L last'] * weights_last).sum() / total_weight_last if 'P/L last' in df_pos.columns and total_weight_last != 0 else 0

    # Вычисление сумм по Vega и TrueVega
    total_vega = df_pos['Vega'].sum() if 'Vega' in df_pos.columns else 0
    total_true_vega = df_pos['TrueVega'].sum() if 'TrueVega' in df_pos.columns else 0

    # Сортировать датафрейм df_pos по столбцу strike
    df_pos = df_pos.sort_values(by='strike')
    # Добавляем столбец с порядковым номером строки, начиная с 1
    df_pos['num'] = range(1, len(df_pos) + 1)
    # Переставляем столбец 'num' в начало
    cols = ['num'] + [col for col in df_pos.columns if col != 'num']
    df_pos = df_pos[cols]

    # Создание строки итогов
    total_row = {col: '' for col in df_pos.columns}
    total_row['ticker'] = 'Total'
    total_row['net_pos'] = total_net_pos
    # total_row['P/L theor'] = round(weighted_pl_theor, 2)
    total_row['P/L last'] = round(weighted_pl_last, 2)
    total_row['P/L market'] = round(weighted_pl_market, 2)
    total_row['Vega'] = round(total_vega, 2)
    total_row['TrueVega'] = round(total_true_vega, 2)

    # Добавление строки итогов к данным
    df_pos_with_total = pd.concat([df_pos, pd.DataFrame([total_row])], ignore_index=True)

    return df_pos_with_total.to_dict('records')


# Callback to update the table "MyTrades Table"
@app.callback(
    Output('trades', 'data', allow_duplicate=True),
    [Input('interval-component', 'n_intervals'),
     Input('dropdown-selection', 'value')],
    prevent_initial_call=True)
def updateTrades(n, value):
    df_trades = pd.read_csv(temp_obj.substitute(name_file='QUIK_Stream_Trades.csv'), encoding='UTF-8', sep=';')
    # Добавляем столбец с порядковым номером строки, начиная с 1
    df_trades['num'] = range(1, len(df_trades) + 1)
    # Переставляем столбец 'num' в начало
    cols = ['num'] + [col for col in df_orders.columns if col != 'num']
    df_trades = df_trades[cols]
    # Преобразование столбца order_num в строку
    df_trades['order_num'] = df_trades['order_num'].astype(str)
    # Фильтрация строк по базовому активу
    df_trades = df_trades[df_trades['option_base'] == value]

    return df_trades.to_dict('records')


# Callback to update the table "MyOrders Table"
@app.callback(
    Output('orders', 'data', allow_duplicate=True),
    [Input('interval-component', 'n_intervals'),
     Input('dropdown-selection', 'value')],
    prevent_initial_call=True)
def updateOrders(n, value):
    df_orders = pd.read_csv(temp_obj.substitute(name_file='QUIK_Stream_Orders.csv'), encoding='UTF-8', sep=';')
    # Добавляем столбец с порядковым номером строки, начиная с 1
    df_orders['num'] = range(1, len(df_orders) + 1)
    # Переставляем столбец 'num' в начало
    cols = ['num'] + [col for col in df_orders.columns if col != 'num']
    df_orders = df_orders[cols]
    # Преобразование столбца order_num в строку
    df_orders['order_num'] = df_orders['order_num'].astype(str)
    # Фильтрация строк по базовому активу
    df_orders = df_orders[df_orders['option_base'] == value]

    return df_orders.to_dict('records')


# Callback to update the graph-gauge Спидометр TrueVega
@app.callback(
    Output('graph-gauge', 'value', allow_duplicate=True),
    [Input('interval-component', 'n_intervals'),
     Input('dropdown-selection', 'value')],
    prevent_initial_call=True
)
def updateGauge(n, value):
    df_pos = pd.read_csv(temp_obj.substitute(name_file='QUIK_MyPos.csv'), sep=';')
    # Фильтрация строк по базовому активу
    df_pos = df_pos[df_pos['option_base'] == value]

    # TrueVega
    tv_sum_positive = df_pos.loc[df_pos['net_pos'] > 0, 'TrueVega'].sum()
    tv_sum_negative = df_pos.loc[df_pos['net_pos'] < 0, 'TrueVega'].sum()
    tv_sum = abs(tv_sum_positive) + abs(tv_sum_negative)
    if tv_sum == 0:
        value = 0
    else:
        value = (abs(tv_sum_positive) / (abs(tv_sum_positive) + abs(tv_sum_negative))) * 10
    return value


if __name__ == '__main__':
    app.run(debug=False)  # Run the Dash app