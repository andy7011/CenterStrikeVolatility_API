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
import plotly.express as px
import pandas as pd
from app.central_strike import _calculate_central_strike, get_list_of_strikes
from app.supported_base_asset import MAP
from string import Template
import time
import random
import inspect
import threading
import atexit

from FinamPy.grpc.marketdata_service_pb2 import SubscribeBarsResponse, TimeFrame  # Подписка на бары Финама
from FinLabPy.Config import brokers, default_broker  # Все брокеры и брокер по умолчанию
from FinLabPy.Core import Bar, bars_to_df  # Бар, перевод бар в pandas DataFrame
from AlorPy import AlorPy  # Работа с Alor OpenAPI V2

# temp_str = 'C:\\Users\\sftpuser\\Position\\$name_file' # виртуальная машина
# temp_str = 'C:\\Users\\ashad\\Yandex.Disk\\_ИИС\\Position\\$name_file' # домашний компьютер
temp_str = 'C:\\Users\\шадрин\\YandexDisk\\_ИИС\\Position\\$name_file' # ноутбук
temp_obj = Template(temp_str)
# Каталог data/Finam с CSV-файлами
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR_FINAM = os.path.join(BASE_DIR, "data", "Finam")

_csv_cache = {}


def read_csv_cached(name_file, sep=';', encoding=None):
    """Читает CSV с кэшированием по времени изменения файла (mtime).
    При ошибке чтения (файл перезаписывается внешним процессом) возвращает последнюю успешную версию"""
    path = temp_obj.substitute(name_file=name_file)
    mtime = os.path.getmtime(path)
    key = (name_file, sep, (encoding or '').lower())
    cached = _csv_cache.get(key)
    if cached and cached[0] == mtime:
        return cached[1].copy()
    try:
        df = pd.read_csv(path, sep=sep, encoding=encoding, low_memory=False)
        _csv_cache[key] = (mtime, df)
    except Exception as e:
        if cached:
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Ошибка чтения {name_file} ({e}), используются предыдущие данные")
            return cached[1].copy()
        raise
    return df.copy()

# Глобальные переменные для хранения данных
model_from_api = None
base_asset_list = None
option_list = None
option_df = None
central_strike = None

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
    global model_from_api, base_asset_list, option_list, option_df
    model_from_api = get_object_from_json_endpoint_with_retry('https://option-volatility-dashboard.ru/dump_model')

    # Список базовых активов
    base_asset_list = model_from_api[0]
    # print(f'base_asset_list: {base_asset_list}')

    # Список опционов
    option_list = model_from_api[1]

    # Предварительно подготовленный DataFrame опционов (строится один раз за обновление)
    option_df = pd.DataFrame.from_dict(option_list, orient='columns')
    option_df = option_df.loc[option_df['_volatility'] > 0]
    option_df['_expiration_datetime'] = pd.to_datetime(option_df['_expiration_datetime'], format='%a, %d %b %Y %H:%M:%S GMT')
    option_df['expiration_date'] = option_df['_expiration_datetime'].dt.strftime('%d.%m.%Y')

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

# Фоновый поток обновления данных с API каждые 10 секунд
def fetch_api_data_loop(interval=10):
    while True:
        time.sleep(interval)
        try:
            fetch_api_data()
        except Exception as e:
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Ошибка фоновой загрузки данных: {e}")


fetch_thread = threading.Thread(target=fetch_api_data_loop, daemon=True)
fetch_thread.start()

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
# print(df.columns)

dff = df[(df._base_asset_ticker == first_key)]  # оставим только опционы базового актива

base_asset_last_price = None
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
    df_orders = pd.read_csv(file, sep=';', low_memory=False)
    df_orders = df_orders[(df_orders.option_base == first_key)]
    df_orders_buy = df_orders[(df_orders.option_base == first_key) & (df_orders.operation == 'Купля')]
    df_orders_sell = df_orders[(df_orders.option_base == first_key) & (df_orders.operation == 'Продажа')]
    # Converting DataFrame "df_orders" to a list "tikers" containing all the rows of column 'ticker'
    tikers = df_orders['ticker'].tolist()

# My trades data
with open(temp_obj.substitute(name_file='QUIK_Stream_Trades.csv'), 'r', encoding='UTF-8') as file:
    df_trades = pd.read_csv(file, sep=';', low_memory=False)
file.close()

# My positions history data
with open(temp_obj.substitute(name_file='MyPosHistory.csv'), 'r', encoding='UTF-8') as file:
    df_MyPosTilt = pd.read_csv(file, sep=';', low_memory=False)
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


def update_bars_history():
    """Обновление истории свечей (баров) всех базовых активов из MAP.

    Используем готовую функцию broker.get_history: она сама скачивает лишь недостающие
    в истории бары и через FileStorage.set_bars сохраняет их в текстовые файлы
    data/Finam/SPBFUT.{тикер}_{time_frame}.txt. Остаётся лишь обрезать файлы
    до глубины истории: M15 - 14 дней, D1 - 140 дней.
    """
    broker = brokers['Ф']  # Брокер по ключу из Config.py словаря brokers
    time_frames = {  # Таймфрейм и глубина истории в днях
        'M15': 14,  # 15-минутные бары, глубина истории 14 дней
        'D1': 140,  # Дневные бары, глубина истории 140 дней
    }
    for ticker in iter(MAP):  # Пробегаемся по всем базовым активам из MAP
        dataname = f'SPBFUT.{ticker}'  # Название тикера
        symbol = broker.get_symbol_by_dataname(dataname)  # Тикер по названию
        if symbol is None:  # Если тикер не найден у брокера
            print(f"Тикер {dataname} не найден у брокера Финам")
            continue  # переходим к следующему активу, дальше не продолжаем
        for time_frame, depth_days in time_frames.items():  # Пробегаемся по всем таймфреймам
            dt_from = datetime.now() - timedelta(days=depth_days)  # Минимальная дата, с которой нужна история
            print(f"Запрос свечей: {dataname} {time_frame} начиная с даты {dt_from:%d.%m.%Y %H:%M}")
            try:
                # Скачивает лишь недостающие бары и сохраняет историю в файл через storage.set_bars
                broker.get_history(symbol, time_frame, dt_from=dt_from)
            except Exception as e:  # Если данные не получены (например, инструмент недоступен у брокера)
                print(f"Ошибка при получении свечей: {dataname} {time_frame}: {e}")
                continue  # переходим к следующему таймфрейму, дальше не продолжаем
            filename = f'{broker.storage.datapath}{dataname}_{time_frame}.txt'  # Полное имя файла истории
            if os.path.isfile(filename):  # Если файл истории создан
                df = pd.read_csv(filename, sep=broker.storage.delimiter, index_col='datetime',
                                 parse_dates=['datetime'], dayfirst=True)  # Читаем бары из файла
                df = df[df.index >= dt_from].sort_index()  # Оставляем только нужную глубину истории
                df.to_csv(filename, sep=broker.storage.delimiter, date_format=broker.storage.dt_format)  # Сохраняем историю в файл
                print(f"Сохранено баров: {len(df)} в {filename}")

# Обновление истории свечей всех базовых активов из MAP в файлы data/Finam
update_bars_history()

# Подписка на бары (свечи) всех используемых базовых активов из MAP и ведение единого словаря
# bars: <тикер> -> список баров в порядке поступления по времени. В конце списка всегда лежит
# текущий НЕЗАВЕРШЁННЫЙ бар, который обновляется на каждое изменение (тикание) свечи; когда бар
# закрывается, он остаётся в списке как завершённый, а в конец добавляется новый незавершённый бар.
#
# Механизм (как в FinLabPy/Brokers/Examples/unfinished_bar.py): обёртка FinLabPy (брокер Финам)
# через событие on_new_bar отдаёт только ЗАКРЫТЫЕ бары, а незавершённый бар непрерывно обновляет
# в broker.last_bars. Чтобы ловить каждое обновление незавершённого бара, подписываемся на событие
# ПРОВАЙДЕРА broker.provider.on_new_bar и читаем из broker.last_bars уже готовый объект Bar.

bar_subscription_broker = brokers['Ф']  # Брокер Финам для подписки на бары
bar_subscription_time_frame = 'M15'  # Таймфрейм подписки на бары
bars = {}  # Словарь баров: <тикер> -> [завершённые бары по порядку, незавершённый бар (всегда последний)]


def upsert_bar(ticker, bar: Bar):
    """Добавление/обновление бара в списке словаря bars.

    Гарантирует уникальность по времени (дубликатов нет) и порядок по времени,
    при этом последним в списке всегда остаётся текущий (незавершённый) бар.
    """
    bar_bars = bars.setdefault(ticker, [])  # Список баров тикера
    if bar_bars and bar_bars[-1].datetime == bar.datetime:  # Частый случай: это последний (незавершённый) бар
        bar_bars[-1] = bar  # то просто обновляем его
        return
    for i in range(len(bar_bars) - 1, -1, -1):  # Ищем бар с таким же временем среди остальных
        if bar_bars[i].datetime == bar.datetime:  # Если такой бар уже есть
            bar_bars[i] = bar  # то обновляем его на том же месте, не создавая дубликат
            return
    bar_bars.append(bar)  # Нового бара ещё нет - добавляем в конец
    bar_bars.sort(key=lambda b: b.datetime)  # Восстанавливаем порядок по времени


def on_completed_bar(bar: Bar):
    """Обработчик закрытия бара по подписке обёртки FinLabPy (срабатывает только при закрытии бара)"""
    ticker = bar.dataname.removeprefix('SPBFUT.')  # Тикер по названию
    upsert_bar(ticker, bar)  # Записываем завершённый бар в словарь
    # print(f'Завершён бар: {bar}')


def on_unfinished_bar(response: SubscribeBarsResponse, finam_tf: TimeFrame.ValueType):
    """Обработчик обновления незавершённого бара по подписке провайдера (срабатывает на каждое обновление свечи)"""
    ticker = response.symbol.split('@')[0]  # Тикер из тикера Финама ('RIZ6@RTSX')
    key = (f'SPBFUT.{ticker}', bar_subscription_time_frame)  # Ключ в справочнике последних бар брокера
    unfinished = bar_subscription_broker.last_bars.get(key)  # Незавершённый бар (обёртка уже перевела его в Bar)
    if unfinished is None:  # Если бара ещё нет
        return  # то выходим, дальше не продолжаем
    upsert_bar(ticker, unfinished)  # Обновляем незавершённый бар (всегда последний в списке)


def get_candles_df(ticker, limit_time):
    """Построение DataFrame свечей M15 по истории из файла + живым барам подписки (фильтр по базовому активу и времени)"""
    all_bars = []
    symbol = bar_subscription_broker.get_symbol_by_dataname(f'SPBFUT.{ticker}')  # Спецификация тикера
    if symbol is not None:  # Если тикер найден
        file_bars = bar_subscription_broker.storage.get_bars(symbol, bar_subscription_time_frame)  # История из файла data/Finam
        if file_bars:  # Если в файле есть бары
            all_bars.extend(file_bars)  # то добавляем их
    all_bars.extend(bars.get(ticker, []))  # Живые бары подписки (последний - незавершённый бар)
    if not all_bars:  # Если баров нет совсем
        return pd.DataFrame(columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
    df_candles = pd.DataFrame([bar.to_dict() for bar in all_bars])  # Бары в DataFrame
    df_candles = df_candles.drop_duplicates(subset=['datetime'], keep='last').sort_values('datetime')  # Убираем дубликаты по времени, сортируем
    df_candles['datetime'] = pd.to_datetime(df_candles['datetime'])  # Дата и время бара
    return df_candles[(df_candles.datetime > limit_time)]  # Фильтр по времени


# Подписка на бары всех базовых активов из MAP
bar_subscription_broker.on_new_bar.subscribe(on_completed_bar)  # Обработчик завершённых бар
bar_subscription_broker.provider.on_new_bar.subscribe(on_unfinished_bar)  # Обработчик незавершённых бар
for ticker in iter(MAP):  # Пробегаемся по всем базовым активам из MAP
    dataname = f'SPBFUT.{ticker}'  # Название тикера
    symbol = bar_subscription_broker.get_symbol_by_dataname(dataname)  # Тикер по названию
    if symbol is None:  # Если тикер не найден у брокера
        print(f'Тикер {dataname} не найден у брокера Финам, пропускаем подписку')
        continue  # переходим к следующему активу, дальше не продолжаем
    bar_subscription_broker.subscribe_history(symbol, bar_subscription_time_frame)  # Подписка на бары


# Корректное закрытие брокера перед завершением работы программы
def shutdown_bars_subscription():
    """Отписка от баров и корректное закрытие брокера перед завершением работы программы"""
    try:  # Пытаемся
        bar_subscription_broker.provider.on_new_bar.unsubscribe(on_unfinished_bar)  # отписаться от незавершённых бар
        bar_subscription_broker.on_new_bar.unsubscribe(on_completed_bar)  # отписаться от завершённых бар
        bar_subscription_broker.unsubscribe_all_history()  # отменить все подписки на историю
    except Exception as e:  # При ошибке отписки
        print(f'Ошибка при отписке от баров: {e}')
    try:  # Пытаемся
        bar_subscription_broker.close()  # корректно закрыть брокера (закрывает канал, потоки подписки завершаются)
        print('Брокер корректно закрыт')
    except Exception as e:  # При ошибке закрытия
        print(f'Ошибка при закрытии брокера: {e}')


atexit.register(shutdown_bars_subscription)  # Закрытие брокера при завершении работы программы


# Сборка основного файла истории MyEquity
try:
    with open(temp_obj.substitute(name_file='MyEquity.CSV'), 'r') as file:
        df_myequity = pd.read_csv(file, sep=',', low_memory=False)
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
tab3_content = [  # IV ATM history
    dcc.Graph(id='plot_history', style={'margin-top': 10}),
    dcc.RadioItems(options=['Call', 'Put'],
                   value='Call',
                   inline=True,
                   style=dict(display='flex', justifyContent='right'),
                   id='my-radio-buttons-final'),
]
tab4_content = [  # MyPosTable
    html.Div([
        html.Div([
            html.Div(id='intermediate-value', style={'display': 'none'}),
            html.Div(
                dash_table.DataTable(
                    id='table',
                    data=df_table.to_dict('records'),
                    page_size=20,
                    style_table={'max-width': '50px'},
                    style_header={
                        'fontWeight': 'bold',
                        'backgroundColor': 'rgb(50, 50, 50)',
                        'color': 'white',
                        'textAlign': 'center'
                    },
                    style_data={
                        'backgroundColor': 'rgb(30, 30, 30)',
                        'color': 'white'
                    },
                    style_data_conditional=[
                        {
                            'if': {'filter_query': '{ticker} = "Total"'},
                            'fontWeight': 'bold',
                            'backgroundColor': 'rgb(60, 60, 60)'
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
                style={'margin': '20px'}
            )
        ], style={'width': '85%', 'display': 'inline-block', 'verticalAlign': 'top'})
    ])
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
                'backgroundColor': 'rgb(50, 50, 50)',
                'color': 'white',
                'textAlign': 'center'
            },
            style_data={
                'backgroundColor': 'rgb(30, 30, 30)',
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
                'backgroundColor': 'rgb(50, 50, 50)',
                'color': 'white',
                'textAlign': 'center'
            },
            style_data={
                'backgroundColor': 'rgb(30, 30, 30)',
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
        # style={'margin-left': '400px'}  # Сдвиг вправо
    )
]

tab7_content = [dcc.Graph(id='MyEquityHistory', style={'margin-top': 10})]

# Создаем приложение Dash в тёмной теме
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.DARKLY])

# Установка темной темы для всех графиков
go.Figure(layout=go.Layout(template="plotly_dark"))

app.layout = html.Div(children=[

    html.Div(children=[  # График улыбки волатильности
        html.Div(children=[
            # График улыбки волатильности
            dcc.Graph(id='plot_smile'),
        ], style={'width': '87%', 'display': 'inline-block'}),

        html.Div(children=[  # Текущее время обновления данных
            # Текущее время обновления данных
            html.H6(id='last_update_time'),

            html.Div(  # Контейнер для двух селекторов в одну линию
                children=[
                    dcc.Dropdown(  # Селектор выбора базового актива
                        df._base_asset_ticker.unique(),
                        value=first_key,
                        id='dropdown-selection',
                        style={
                            'backgroundColor': '#2d2d2d',
                            'color': 'white',
                            'border': '1px solid #444',
                            'borderRadius': '4px',
                            'flex': '0 0 55%',  # 50% ширины контейнера
                        },
                        className='dark-dropdown'
                    ),
                    dcc.Dropdown(  # Селектор выбора количества страйков
                        options=[{'label': str(i), 'value': i} for i in range(3, 16)],
                        value=11,
                        id='num_srikes_selection',
                        style={
                            'backgroundColor': '#2d2d2d',
                            'color': 'white',
                            'border': '1px solid #444',
                            'borderRadius': '4px',
                            'flex': '1 1 auto',  # занимает оставшиеся 30%
                            'marginLeft': '8px',  # небольшой отступ между селекторами
                        },
                        className='dark-dropdown'
                    ),
                ],
                style={
                    'display': 'flex',
                    'flexDirection': 'row',
                    'alignItems': 'center',
                    'width': '100%',
                }
            ),

            daq.Gauge(
                # Спидометр TrueVega # https://stackoverflow.com/questions/69275527/python-dash-gauge-how-can-i-use-strings-as-values-instead-of-numbers
                id="graph-gauge",
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

        dbc.Tabs(id='main-tabs', active_tab='tab-1', children=[
            dbc.Tab(tab1_content, label='MyPos history', tab_id='tab-1'),
            dbc.Tab(tab2_content, label='Наклон улыбки', tab_id='tab-2'),
            dbc.Tab(tab3_content, label='IV ATM history', tab_id='tab-3'),
            dbc.Tab(tab4_content, label='MyPos table', tab_id='tab-4'),
            dbc.Tab(tab5_content, label='MyTrades table', tab_id='tab-5'),
            dbc.Tab(tab6_content, label='MyOrders table', tab_id='tab-6'),
            dbc.Tab(tab7_content, label='MyEquity', tab_id='tab-7'),
        ]),

        # Интервал обновления данных - 5 секунд
        dcc.Interval(
            id='interval-component',
            interval=1000 * 5,
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
                   value=6,
                   className='dark-slider'
                   ),
        html.Div(id='slider-output-1'),
    ])
])

# --- CALLBACKS ---

# Колбэк для обновления времени последнего обновления данных с периодичностью 10 секунд
@app.callback(Output('last_update_time', 'children'),
              [Input('interval-component', 'n_intervals')])
def update_time(n):
    # Данные обновляются в фоновом потоке fetch_api_data_loop
    # My portfoloio info data
    with open(temp_obj.substitute(name_file='QUIK_MyPortfolioInfo.csv'), 'r') as file:
        info = file.read()
    return [
        'Last update: {}'.format(datetime.now().strftime('%d.%m.%Y %H:%M:%S')),
        html.Br(),
        html.Pre(info)
    ]


# Обновление графика улыбки волатильности
@app.callback(
    Output('plot_smile', 'figure', allow_duplicate=True),
    [
        Input('dropdown-selection', 'value'),
        Input('num_srikes_selection', 'value'),  # <-- добавили Input
        Input('interval-component', 'n_intervals')
    ],
    prevent_initial_call=True
)
def update_output_smile(value, num_strikes, n):  # <-- новый параметр num_strikes
    try:
        # Список опционов (предрасчитанный DataFrame из fetch_api_data)
        df = option_df

        dff = df[(df._base_asset_ticker == value)]

        base_asset_last_price = None
        strike_step = None
        strikes_count = num_strikes
        for asset in base_asset_list:
            if asset['_ticker'] == value:
                base_asset_last_price = asset['_last_price']
                strike_step = MAP[value]['strike_step']
                # Используем значение из Dropdown вместо фиксированного max_strikes_count
                strikes_count = num_strikes

        if base_asset_last_price is None or strike_step is None:
            print(f"update_output_smile: тикер {value} не найден в base_asset_list/MAP")
            raise PreventUpdate

        strikes = get_list_of_strikes(base_asset_last_price, strike_step, strikes_count)
        # print(strikes)

        # Фильтруем данные по выбранному количеству страйков в селекторе по умолчанию
        dff = dff[dff['_strike'].isin(strikes)]

        dff_call = dff[(dff._type == 'C')]  # оставим только коллы

        # Получаем уникальные даты истечения
        exp_dates = dff_call['expiration_date'].unique()

        # Создаем словарь сопоставления дат и цветов
        colors = px.colors.qualitative.Plotly[:len(exp_dates)]
        expdate_colors = dict(zip(exp_dates, colors))

        def get_exp_color(exp_day):
            # Даты истечения позиций/ордеров могут отсутствовать среди серий коллов
            return expdate_colors.get(exp_day, 'gray')

        # My positions data
        df_table = read_csv_cached('QUIK_MyPos.csv', sep=';')
        df_table_buy = df_table[(df_table.option_base == value) & (df_table.net_pos > 0) & (df_table.OpenIV > 0)]
        df_table_sell = df_table[(df_table.option_base == value) & (df_table.net_pos < 0) & (df_table.OpenIV > 0)]
        MyPos_ticker_list = df_table['ticker'].tolist()
        # DataFrame для отрисовки баланса TrueVega
        df_table_base = df_table
        df_table_base = df_table_base[df_table_base.option_base == value]

        # My orders data
        df_orders = read_csv_cached('QUIK_Stream_Orders.csv', sep=';', encoding='utf-8')
        df_orders = df_orders[(df_orders.option_base == value)]
        df_orders_buy = df_orders[(df_orders.option_base == value) & (df_orders.operation == 'Купля')]
        df_orders_sell = df_orders[(df_orders.option_base == value) & (df_orders.operation == 'Продажа')]
        # Converting DataFrame "df_orders" to a list "tikers" containing all the rows of column 'ticker'
        tikers = df_orders['ticker'].tolist()

        # Create figure with secondary y-axis
        fig = make_subplots(specs=[[{"secondary_y": True}]])

        # Рисуем график улыбки с уникальными цветами
        for exp_day in exp_dates:
            dff_smile = dff_call[dff_call.expiration_date == exp_day]
            fig.add_trace(go.Scatter(
                x=dff_smile['_strike'],
                y=dff_smile['_volatility'],
                mode='lines+text',
                name=exp_day,
                line=dict(color=get_exp_color(exp_day))
            ), secondary_y=False)

        # Мои позиции BUY
        for exp_day in df_table_buy['expdate'].unique():
            df_buy = df_table_buy[df_table_buy.expdate == exp_day]
            fig.add_trace(go.Scatter(
                x=df_buy['strike'],
                y=df_buy['OpenIV'],
                mode='markers+text',
                text=df_buy['OpenIV'],
                textposition='middle left',
                marker=dict(
                    size=11,
                    symbol="star-triangle-up-open",
                    color=get_exp_color(exp_day)
                ),
                name=f'My Pos Buy {exp_day}',
                customdata=df_buy[['option_type', 'net_pos', 'expdate', 'ticker']],
                hovertemplate="<b>%{customdata}</b>"
            ))

        # Мои позиции SELL
        for exp_day in df_table_sell['expdate'].unique():
            df_sell = df_table_sell[df_table_sell.expdate == exp_day]
            fig.add_trace(go.Scatter(
                x=df_sell['strike'],
                y=df_sell['OpenIV'],
                mode='markers+text',
                text=df_sell['OpenIV'],
                textposition='middle left',
                marker=dict(
                    size=11,
                    symbol="star-triangle-down-open",
                    color=get_exp_color(exp_day)
                ),
                name=f'My Pos Sell {exp_day}',
                customdata=df_sell[['option_type', 'net_pos', 'expdate', 'ticker']],
                hovertemplate="<b>%{customdata}</b><br>"
            ))

        # Мои ордерра BUY
        for exp_day in df_orders_buy['expdate'].unique():
            df_order_buy = df_orders_buy[df_orders_buy.expdate == exp_day]
            fig.add_trace(go.Scatter(
                x=df_order_buy['strike'],
                y=df_order_buy['volatility'],
                mode='markers+text',
                text=df_order_buy['volatility'],
                textposition='middle left',
                marker=dict(
                    size=8,
                    symbol="cross-thin",
                    line=dict(width=1, color=get_exp_color(exp_day))
                ),
                name=f'My Orders BUY {exp_day}',
                customdata=df_order_buy[['operation', 'option_type', 'expdate', 'price', 'ticker']],
                hovertemplate="<b>%{customdata}</b><br>"
            ))

        # Мои ордерра SELL
        for exp_day in df_orders_sell['expdate'].unique():
            df_order_sell = df_orders_sell[df_orders_sell.expdate == exp_day]
            fig.add_trace(go.Scatter(
                x=df_order_sell['strike'],
                y=df_order_sell['volatility'],
                mode='markers+text',
                text=df_order_sell['volatility'],
                textposition='middle left',
                marker=dict(
                    size=8,
                    symbol="cross-thin",
                    line=dict(width=1, color=get_exp_color(exp_day))
                ),
                name=f'My Orders SELL {exp_day}',
                customdata=df_order_sell[['operation', 'option_type', 'expdate', 'price', 'ticker']],
                hovertemplate="<b>%{customdata}</b><br>"
            ))

        # Last Bid Ask for MyPos and MyOrders
        favorites_list = MyPos_ticker_list + tikers  # слияние списков
        favorites_ticker_list = set(favorites_list)
        dff_MyPosOrders = df[(df._base_asset_ticker == value) & (df._ticker.isin(favorites_ticker_list))].copy()
        # dff_MyPosOrders = dff_MyPosOrders.apply(lambda x: round(x, 2))
        # Применяем округление только к числовым столбцам
        numeric_columns = dff_MyPosOrders.select_dtypes(include=['number']).columns
        dff_MyPosOrders[numeric_columns] = dff_MyPosOrders[numeric_columns].round(2)
        dff_MyPosOrders.loc[dff_MyPosOrders['_type'] == 'C', '_type'] = 'Call'
        dff_MyPosOrders.loc[dff_MyPosOrders['_type'] == 'P', '_type'] = 'Put'
        # Создаем пустую колонку для хранения преобразованного времени
        dff_MyPosOrders['converted_time'] = ''
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
        fig.add_trace(
            go.Scatter(x=dff_MyPosOrders['_strike'], y=dff_MyPosOrders['_last_price_iv'], visible='legendonly',
                       mode='markers', text=dff_MyPosOrders['_last_price_iv'], textposition='top left',
                       marker=dict(size=8, color='goldenrod'),
                       name='Last',
                       customdata=dff_MyPosOrders[
                           ['_type', '_last_price', '_last_price_iv', 'expiration_date', '_ticker',
                            'converted_time']],
                       hovertemplate="<b>%{customdata}</b><br>"
                       ))

        # # TrueVega позиции
        # fig.add_trace(go.Bar(x=df_table_base['strike'], y=df_table_base['TrueVega'], text=df_table_base['TrueVega'],
        # textposition='auto', name='TrueVega', opacity=0.1), secondary_y=True)

        # TrueVega позиции
        for exp_day in exp_dates:
            df_filtered = df_table_base[df_table_base.expdate == exp_day]
            fig.add_trace(
                go.Bar(
                    x=df_filtered['strike'],
                    y=df_filtered['TrueVega'],
                    text=df_filtered['TrueVega'],
                    textposition='auto',
                    name=f'TrueVega {exp_day}',
                    marker_color=get_exp_color(exp_day),
                    opacity=0.1
                ),
                secondary_y=True
            )

        # После установки barmode='stack' переупорядочиваем легенду
        fig.update_layout(
            barmode='stack',
            legend_traceorder='normal'  # 'normal' - в порядке добавления, 'reversed' - обратный порядок
        )

        # Цена базового актива (вертикальная линия)
        fig.add_vline(x=base_asset_last_price, line_dash='dash', line_color='firebrick')

        fig.update_layout(height=450,
                          title_text=f"Volatility smile, series <b>{value}<b>"
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
            plot_bgcolor='rgb(30, 30, 30)',
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

        fig.update_layout(uirevision=f'smile-{value}-{num_strikes}')

        return fig

    except Exception as e:
        print(f"Ошибка при обновлении графика улыбки волатильности: {str(e)}")
        raise PreventUpdate

# Обновление данных графика истории моей позиции
@app.callback(Output('MyPosTiltHistory', 'figure', allow_duplicate=True),
              [Input('dropdown-selection', 'value'),
               Input('my_slider', 'value'),
               Input('interval-component', 'n_intervals'),
               Input('main-tabs', 'active_tab'),
               ],
              prevent_initial_call=True)
def update_output_MyPosHistory(dropdown_value, slider_value, n, active_tab):
    if active_tab != 'tab-1':
        raise PreventUpdate
    limit_time = datetime.now() - timedelta(hours=12 * slider_value)
    time_frame = 'M15'
    df_candles = get_candles_df(dropdown_value, limit_time)  # Свечи M15 из словаря баров bars
    # print(df_candles)
    # print(limit_time)
    # ДАННЫЕ ИЗ csv
    # MyPosHistory.csv history data options volatility
    df_MyPosHistory = read_csv_cached('MyPosHistory.csv', sep=';')
    df_MyPosHistory = df_MyPosHistory[(df_MyPosHistory.option_base == dropdown_value)]

    df_MyPosHistory['DateTime'] = pd.to_datetime(df_MyPosHistory['DateTime'],
                                                 format='%Y-%m-%d %H:%M:%S')
    df_MyPosHistory.index = pd.DatetimeIndex(df_MyPosHistory['DateTime'])
    # df_MyPosHistory = df_MyPosHistory[(df_vol_history.type == radiobutton_value)]
    df_MyPosHistory = df_MyPosHistory[(df_MyPosHistory.DateTime > limit_time)]
    # Сортировка по времени (индексу) для корректного порядка точек на линиях
    df_MyPosHistory = df_MyPosHistory.sort_index()

    # Фильтрация аномальных значений market (пустой стакан на границах сессии):
    # market отбрасывается, если превышает theor более чем на 200% или неположительный
    df_MyPosHistory['market'] = pd.to_numeric(df_MyPosHistory['market'], errors='coerce')
    df_MyPosHistory['theor'] = pd.to_numeric(df_MyPosHistory['theor'], errors='coerce')
    market_mask = (df_MyPosHistory['market'] > df_MyPosHistory['theor'] * 3) | (df_MyPosHistory['market'] <= 0)
    df_MyPosHistory.loc[market_mask, 'market'] = None
    # print(df_MyPosHistory)

    # Данные о сделках
    # My trades data
    df_trades = read_csv_cached('QUIK_Stream_Trades.csv', sep=';', encoding='UTF-8')
    df_trades = df_trades[(df_trades.option_base == dropdown_value)]
    df_trades['datetime'] = pd.to_datetime(df_trades['datetime'],
                                           format='%d.%m.%Y %H:%M:%S')
    df_trades.index = pd.DatetimeIndex(df_trades['datetime'])
    df_trades = df_trades[(df_trades.datetime > limit_time)]
    # Сортировка по времени (индексу) для корректного порядка точек на линиях
    df_trades = df_trades.sort_index()
    # print(df_table)
    # Создаем столбец 'pos' в df_trades на основе значений из df_table
    df_table['pos'] = df_table['net_pos'].apply(lambda x: 'long' if x > 0 else 'short')
    df_trades = df_trades.merge(df_table[['ticker', 'pos']], on='ticker', how='left')
    # Удаляем строки, где 'pos' равен NaN
    df_trades = df_trades.dropna(subset=['pos'])

    # Create figure with secondary y-axis
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # График истории моей позиции (из MyPosHistory.cs)
    for pos in sorted(df_MyPosHistory['pos'].unique(), reverse=True):
        dff = df_MyPosHistory[df_MyPosHistory.pos == pos]
        color = 'red' if pos == "short" else 'green'
        fig.add_trace(go.Scatter(x=dff['DateTime'], y=dff['mypos'], visible='legendonly',
                                 legendgroup=pos,
                                 legendgrouptitle_text=pos,
                                 mode='lines+text',
                                 line=dict(dash='dot', color=color),
                                 name='MyPos'), secondary_y=True, )

    # График истории моей позиции ПО LAST цене из MyPosHistory
    for pos in sorted(df_MyPosHistory['pos'].unique()):
        dff = df_MyPosHistory[df_MyPosHistory.pos == pos]
        color = 'red' if pos == "short" else 'green'
        fig.add_trace(go.Scatter(x=dff['DateTime'], y=dff['last'],
                                 legendgroup=pos,
                                 legendgrouptitle_text=pos,
                                 mode='lines+text',
                                 line=dict(color=color),
                                 name='Last'), secondary_y=True, )

    # График истории моей позиции по цене Theor (из MyPosHistory.csv)
    for pos in sorted(df_MyPosHistory['pos'].unique(), reverse=True):
        dff = df_MyPosHistory[df_MyPosHistory.pos == pos]
        color = 'red' if pos == "short" else 'green'
        fig.add_trace(go.Scatter(x=dff['DateTime'], y=dff['theor'],
                                 legendgroup=pos,
                                 legendgrouptitle_text=pos,
                                 mode='lines+text',
                                 line=dict(color=color, width=1, dash='dot'),
                                 name='Theor'), secondary_y=True, )

    # График истории моей позиции ПО рынку из MyPosHistory
    for pos in sorted(df_MyPosHistory['pos'].unique(), reverse=True):
        dff = df_MyPosHistory[df_MyPosHistory.pos == pos]
        color = 'red' if pos == "short" else 'green'
        fig.add_trace(go.Scatter(x=dff['DateTime'], y=dff['market'], visible='legendonly',
                                 legendgroup=pos,
                                 legendgrouptitle_text=pos,
                                 mode='lines+text',
                                 line=dict(color=color, dash='longdashdot'),
                                 name='Market'), secondary_y=True)

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
            dict(bounds=[24, 7], pattern="hour"),  # hide hours outside of 9am-24pm
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
        plot_bgcolor='rgb(30, 30, 30)',
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

    # Сохранение зума и выбора в легенде между обновлениями;
    # сброс только при смене инструмента или глубины истории
    fig.update_layout(uirevision=f'mypos-{dropdown_value}-{slider_value}')

    return fig


# обновление данных графика истории волатильности на центральном страйке
@app.callback(Output('plot_history', 'figure', allow_duplicate=True),
              [Input('dropdown-selection', 'value'),
               Input('my_slider', 'value'),
               Input('my-radio-buttons-final', 'value'),
               Input('interval-component', 'n_intervals'),
               Input('main-tabs', 'active_tab'),
               ],
              prevent_initial_call=True)
def update_output_history(dropdown_value, slider_value, radiobutton_value, n, active_tab):
    if active_tab != 'tab-3':
        raise PreventUpdate
    limit_time = datetime.now() - timedelta(hours=12 * slider_value)
    time_frame = 'M15'
    df_candles = get_candles_df(dropdown_value, limit_time)  # Свечи M15 из словаря баров bars

    # ДАННЫЕ ИЗ DAMP/csv
    # OptionsVolaHistoryDamp.csv history data options volatility
    df_vol_history = read_csv_cached('OptionsVolaHistoryDamp.csv', sep=';')
    df_vol_history = df_vol_history[(df_vol_history.base_asset_ticker == dropdown_value)]
    # df_vol_history = df_vol_history.tail(limit * len(df_vol_history['expiration_datetime'].unique()) * 2) # глубина истории по количеству серий

    df_vol_history['DateTime'] = pd.to_datetime(df_vol_history['DateTime'], format='%Y-%m-%d %H:%M:%S')
    df_vol_history.index = pd.DatetimeIndex(df_vol_history['DateTime'])
    df_vol_history = df_vol_history[(df_vol_history.type == radiobutton_value)]
    df_vol_history = df_vol_history[(df_vol_history.DateTime > limit_time)]
    # print(df_vol_history)

    # Create figure with secondary y-axis
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # График истории волатильности ПО ДАННЫМ ИЗ DAMP (из CSV OptionsVolaHistoryDamp.csv)
    exp_dates = sorted(df_vol_history['expiration_datetime'].unique())
    colors = px.colors.qualitative.Plotly

    # Сначала определяем, какие даты истекли
    current_date = datetime.now().date()
    expired_dates = set()
    active_dates = []

    for d_exp in exp_dates:
        exp_date = pd.to_datetime(d_exp).date()
        if exp_date < current_date:
            expired_dates.add(d_exp)
        else:
            active_dates.append(d_exp)

    # Создаем словарь цветов для активных опционов
    active_colors = {}
    for i, d_exp in enumerate(active_dates):
        active_colors[d_exp] = colors[i % len(colors)]

    # График истории наклона улыбки ПО ДАННЫМ ИЗ DAMP
    for d_exp in exp_dates:
        dff = df_vol_history[df_vol_history.expiration_datetime == d_exp]

        # Определяем цвет: серый для истёкших опционов
        if d_exp in expired_dates:
            color = 'gray'
        else:
            color = active_colors[d_exp]

        fig.add_trace(go.Scatter(x=dff['DateTime'], y=dff['Real_vol'], visible='legendonly',
                                 legendgroup="group",
                                 legendgrouptitle_text="RealVol",
                                 mode='lines+text',
                                 line=dict(color=color),
                                 name=d_exp), secondary_y=True)

    # График истории БИРЖЕВОЙ волатильности (из CSV OptionsVolaHistoryDamp.csv)
    for d_exp in exp_dates:
        dff = df_vol_history[df_vol_history.expiration_datetime == d_exp]

        # Определяем цвет: серый для истёкших опционов
        if d_exp in expired_dates:
            color = 'gray'
        else:
            color = active_colors[d_exp]

        fig.add_trace(go.Scatter(x=dff['DateTime'], y=dff['Quik_vol'], visible='legendonly',
                                 legendgroup="group2",
                                 legendgrouptitle_text="QuikVol",
                                 mode='lines+text',
                                 line=dict(width=2, dash='dashdot', color=color),
                                 name=d_exp), secondary_y=True)

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
            dict(bounds=[24, 7], pattern="hour"),  # hide hours outside of 9am-24pm
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
        title_text=f'IV ATM history, put or call option series <b>{dropdown_value}<b>',
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
        plot_bgcolor='rgb(30, 30, 30)',  # Фон графика
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

    fig.update_layout(uirevision=f'mypos-{dropdown_value}-{slider_value}')

    return fig


# Наклон улыбки (обновление данных графика истории наклона улыбки)
@app.callback(Output('naklon_history', 'figure', allow_duplicate=True),
              [Input('dropdown-selection', 'value'),
               Input('my_slider', 'value'),
               Input('interval-component', 'n_intervals'),
               Input('main-tabs', 'active_tab'),
               ],
              prevent_initial_call=True)
def update_output_history_naklon(dropdown_value, slider_value, n, active_tab):
    if active_tab != 'tab-2':
        raise PreventUpdate
    limit_time = datetime.now() - timedelta(hours=12 * slider_value)
    time_frame = 'M15'
    df_candles = get_candles_df(dropdown_value, limit_time)  # Свечи M15 из словаря баров bars

    # Проверка на пустой DataFrame
    if df_candles.empty:
        return dash.no_update  # или вернуть пустой график/данные

    # ДАННЫЕ ИЗ DAMP/csv
    # OptionsSmileNaklonHistory.csv history data options volatility
    df_vol_history_naklon = read_csv_cached('OptionsSmileNaklonHistory.csv', sep=';')
    df_vol_history_naklon = df_vol_history_naklon[(df_vol_history_naklon.base_asset_ticker == dropdown_value)]
    # df_vol_history_naklon = df_vol_history_naklon.tail(limit * len(df_vol_history_naklon['expiration_datetime'].unique()) * 2) # глубина истории по количеству серий

    df_vol_history_naklon['DateTime'] = pd.to_datetime(df_vol_history_naklon['DateTime'],
                                                       format='%Y-%m-%d %H:%M:%S')
    df_vol_history_naklon.index = pd.DatetimeIndex(df_vol_history_naklon['DateTime'])
    # df_vol_history_naklon = df_vol_history_naklon[(df_vol_history.type == radiobutton_value)]
    df_vol_history_naklon = df_vol_history_naklon[(df_vol_history_naklon.DateTime > limit_time)]
    # print(df_vol_history_naklon)

    # Create figure with secondary y-axis
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # График истории наклона улыбки ПО ДАННЫМ ИЗ DAMP (из CSV OptionsSmileNaklonHistory.csv)
    # Для графиков с истекшей датой используется серый цвет
    # Для активных графиков используются стандартные цвета Plotly по порядку

    # График истории наклона улыбки ПО ДАННЫМ ИЗ DAMP и БИРЖЕВОЙ улыбки
    # Цвета серий графиков по дате экспирации должны совпадать
    # Для истёкших опционов использовать серый цвет

    # Получаем уникальные даты экспирации и сортируем их
    expiration_dates = sorted(df_vol_history_naklon['expiration_datetime'].unique())
    current_date = datetime.now().date()

    # Получаем стандартные цвета Plotly
    colors = px.colors.qualitative.Plotly
    color_index = 0

    # Создаем словарь цветов для каждой даты экспирации
    color_map = {}
    for d_exp in expiration_dates:
        exp_date = pd.to_datetime(d_exp).date()
        if exp_date < current_date:
            color_map[d_exp] = 'gray'  # Серый для истёкших
        else:
            color_map[d_exp] = colors[color_index % len(colors)]  # Цвета из палитры для активных
            color_index += 1

    # График истории наклона улыбки ПО ДАННЫМ ИЗ DAMP
    for d_exp in expiration_dates:
        dff = df_vol_history_naklon[df_vol_history_naklon.expiration_datetime == d_exp]
        color = color_map[d_exp]

        fig.add_trace(go.Scatter(
            x=dff['DateTime'],
            y=dff['Real'],
            visible='legendonly',
            legendgroup="group",
            legendgrouptitle_text="Real",
            mode='lines+text',
            name=d_exp,
            line=dict(color=color)
        ), secondary_y=True)

    # График истории наклона БИРЖЕВОЙ улыбки
    for d_exp in expiration_dates:
        dff = df_vol_history_naklon[df_vol_history_naklon.expiration_datetime == d_exp]
        color = color_map[d_exp]

        fig.add_trace(go.Scatter(
            x=dff['DateTime'],
            y=dff['Quik'],
            line=dict(width=1, dash='dashdot', color=color),
            name=d_exp,
            legendgroup="group2",
            legendgrouptitle_text="Quik",
            mode='lines+text',
            visible='legendonly'
        ), secondary_y=True)
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
            dict(bounds=[24, 7], pattern="hour"),  # hide hours outside of 9am-24pm
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
    fig.update_layout(
        margin=dict(l=3, r=3, t=0, b=0),
    )

    fig.update_layout(
        plot_bgcolor='rgb(30, 30, 30)',
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

    fig.update_layout(uirevision=f'naklon-{dropdown_value}-{slider_value}')

    return fig


## EQUITY HISTORY##
@app.callback(Output('MyEquityHistory', 'figure'),
              [Input('dropdown-selection', 'value'),
               Input('my_slider', 'value'),
               Input('interval-component', 'interval-60min'),
               Input('main-tabs', 'active_tab')],
              prevent_initial_call=True)
def update_equity_history(dropdown_value, slider_value, n, active_tab):
    if active_tab != 'tab-7':
        raise PreventUpdate
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

    broker = brokers['Ф']  # Брокер по ключу из Config.py словаря brokers
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
        plot_bgcolor='rgb(30, 30, 30)',
        paper_bgcolor='rgb(30, 30, 30)',
        font_color='white'
    )

    fig.update_layout(uirevision=f'equity-{dropdown_value}-{slider_value}')

    return fig


# Callback to update the table "MyPos Table"
@app.callback(
    Output('table', 'data', allow_duplicate=True),
    [Input('interval-component', 'n_intervals'),
     Input('dropdown-selection', 'value'),
     Input('main-tabs', 'active_tab')],
    prevent_initial_call=True)
def updateTable(n, value, active_tab):
    if active_tab != 'tab-4':
        raise PreventUpdate
    df_pos = pd.read_csv(
        os.path.join(DATA_DIR_FINAM, "Finam_MyPos.csv"),
        sep=";"
    )
    # Фильтрация строк по базовому активу option_base и тикеру ticker
    df_pos = df_pos[(df_pos['option_base'] == value) | (df_pos['ticker'] == value)]
    # Присвоение фьючерсу значения дельта
    df_pos.loc[df_pos['ticker'] == value, 'Delta'] = df_pos.loc[df_pos['ticker'] == value, 'net_pos']

    # Вычисление итогов для опционов по колонке net_pos
    total_net_pos = df_pos.loc[df_pos['ticker'] != value, 'net_pos'].sum()

    # Вычисление сумм
    total_delta = df_pos['Delta'].sum() if 'Delta' in df_pos.columns else 0
    total_gamma = round(df_pos['Gamma'].sum(), 5)
    total_theta = df_pos['Theta'].sum() if 'Theta' in df_pos.columns else 0
    total_vega = df_pos['Vega'].sum() if 'Vega' in df_pos.columns else 0
    total_true_vega = df_pos['TrueVega'].sum() if 'TrueVega' in df_pos.columns else 0
    total_u_pnl = df_pos['u_pnl'].sum() if 'u_pnl' in df_pos.columns else 0

    # Сортировать датафрейм df_pos по столбцу strike
    df_pos = df_pos.sort_values(by='strike')
    # Удаляем столбец option_base
    df_pos = df_pos.drop(columns=['option_base'], errors='ignore')
    # Добавляем столбец с порядковым номером строки, начиная с 1
    df_pos['num'] = range(1, len(df_pos) + 1)
    # Переставляем столбец 'num' в начало
    cols = ['num'] + [col for col in df_pos.columns if col != 'num']
    df_pos = df_pos[cols]

    # Создание строки итогов
    total_row = {col: '' for col in df_pos.columns}
    total_row['ticker'] = 'Total options'
    total_row['net_pos'] = total_net_pos
    total_row['Delta'] = round(total_delta, 2)
    total_row['Gamma'] = round(total_gamma, 4)
    total_row['Theta'] = round(total_theta, 2)
    total_row['Vega'] = round(total_vega, 2)
    total_row['TrueVega'] = round(total_true_vega, 2)
    total_row['u_pnl'] = round(total_u_pnl, 2)

    # Добавление строки итогов к данным
    df_pos_with_total = pd.concat([df_pos, pd.DataFrame([total_row])], ignore_index=True)

    return df_pos_with_total.to_dict('records')


# Callback to update the table "MyTrades Table"
@app.callback(
    Output('trades', 'data', allow_duplicate=True),
    [Input('interval-component', 'n_intervals'),
     Input('dropdown-selection', 'value'),
     Input('main-tabs', 'active_tab')],
    prevent_initial_call=True)
def updateTrades(n, value, active_tab):
    if active_tab != 'tab-5':
        raise PreventUpdate
    df_trades = pd.read_csv(
        os.path.join(DATA_DIR_FINAM, "Finam_Stream_Trades_ALL.csv"),
        sep=";"
    )
    # Добавляем столбец с порядковым номером строки, начиная с 1
    df_trades['num'] = range(1, len(df_trades) + 1)
    # Переставляем столбец 'num' в начало
    cols = ['num'] + [col for col in df_trades.columns if col != 'num']
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
     Input('dropdown-selection', 'value'),
     Input('main-tabs', 'active_tab')],
    prevent_initial_call=True)
def updateOrders(n, value, active_tab):
    if active_tab != 'tab-6':
        raise PreventUpdate
    df_orders = pd.read_csv(
        os.path.join(DATA_DIR_FINAM, "Finam_Stream_Orders.csv"),
        sep=";"
    )
    # df_orders = read_csv_cached('QUIK_Stream_Orders.csv', encoding='UTF-8', sep=';')
    # Добавляем столбец с порядковым номером строки, начиная с 1
    df_orders['num'] = range(1, len(df_orders) + 1)
    # Переставляем столбец 'num' в начало
    cols = ['num'] + [col for col in df_orders.columns if col != 'num']
    df_orders = df_orders[cols]
    # # Преобразование столбца order_num в строку
    # df_orders['order_num'] = df_orders['order_num'].astype(str)
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
    df_pos = pd.read_csv(
        os.path.join(DATA_DIR_FINAM, "Finam_MyPos.csv"),
        sep=";"
    )
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
    try:
        app.run(debug=False)  # Запускаем Dash приложение
    except KeyboardInterrupt:  # При остановке программы
        pass  # ничего не делаем, выходим
    finally:
        shutdown_bars_subscription()  # Отписка и корректное закрытие брокера