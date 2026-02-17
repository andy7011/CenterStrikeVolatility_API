import os.path
from math import isnan
import dash
from dash import dcc, Input, Output, callback, dash_table, State
from dash import html
import dash_bootstrap_components as dbc
import dash_daq as daq
from dash.exceptions import PreventUpdate
import datetime
from datetime import timedelta
from pytz import utc
import requests
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
from app.central_strike import _calculate_central_strike
from app.supported_base_asset import MAP
from string import Template
import time
import random
import inspect

temp_str = 'C:\\Users\\шадрин\\YandexDisk\\_ИИС\\Position\\$name_file'
temp_obj = Template(temp_str)

# Глобальные переменные для хранения данных
model_from_api = None
base_asset_list = None
option_list = None
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
    dt_utc = datetime.datetime.fromtimestamp(seconds)  # Переводим кол-во секунд, прошедших с 01.01.1970 в UTC
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
            print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Запрос к {url} успешно выполнен (строка: {line_number})")
            return response.json()

        except requests.exceptions.HTTPError as e:
            if response.status_code != 502:
                raise

            attempt += 1
            delay = min(2 ** attempt, max_delay)
            jitter = random.uniform(0, 1)
            wait_time = delay * jitter

            print(
                f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Попытка {attempt}: Получена ошибка 502. Ждём {wait_time:.1f} секунд перед повторной попыткой")
            time.sleep(wait_time)

        except requests.exceptions.Timeout:
            print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Timeout при запросе к {url}")
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
# print(df.columns)

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

# My positions data
with open(temp_obj.substitute(name_file='QUIK_MyPos.csv'), 'r') as file:
    df_table = pd.read_csv(file, encoding='UTF-8', sep=';')
# Close the file explicitly file.close()
file.close()

# My orders data
with open(temp_obj.substitute(name_file='QUIK_Stream_Orders.csv'), 'r') as file:
    df_orders = pd.read_csv(file, encoding='UTF-8', sep=';')
# Close the file explicitly file.close()
file.close()

# My trades data
with open(temp_obj.substitute(name_file='QUIK_Stream_Trades.csv'), 'r') as file:
    df_trades = pd.read_csv(file, encoding='UTF-8', sep=';')
file.close()

# My positions history data
with open(temp_obj.substitute(name_file='MyPosHistory.csv'), 'r') as file:
    df_MyPosTilt = pd.read_csv(file, encoding='UTF-8', sep=';')
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

# СВЕЧИ Данные для графика базового актива (для первой прорисовки, первый фьючерс из списка MAP)
limit_time = datetime.datetime.now() - timedelta(hours=12 * 6) # Три дня
time_frame = 'M15'
datapath = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'Data', 'Finam', '')  # Путь к файлам баров
dataname = f'SPBFUT.{first_key}'
filename = f'{datapath}{dataname}_{time_frame}.txt'  # Полное имя файла
# print(filename)
with open(file=filename, mode='r') as file:
    df_candles = pd.read_csv(file, sep='\t', header=0)
    df_candles['datetime'] = pd.to_datetime(df_candles['datetime'], format='%d.%m.%Y %H:%M')
    df_candles = df_candles.sort_values('datetime').reset_index(drop=True)
    df_candles = df_candles[(df_candles.datetime > limit_time)]
file.close()

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
current_datetime = datetime.datetime.now()
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
                'backgroundColor': 'rgb(230, 230, 230)',
                'textAlign': 'center'
            },
            style_data_conditional=[
                {
                    'if': {'filter_query': '{ticker} = "Total"'},
                    'fontWeight': 'bold',
                    'backgroundColor': 'rgb(240, 240, 240)'
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
            style_data_conditional=[
                {
                    'if': {'filter_query': '{operation} eq "Купля"'},
                    'backgroundColor': 'white',
                    'color': '#3D9970'
                },
                {
                    'if': {'filter_query': '{operation} eq "Продажа"'},
                    'backgroundColor': 'white',
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
            style_data_conditional=[
                {
                    'if': {'filter_query': '{operation} eq "Купля"'},
                    'backgroundColor': 'white',
                    'color': '#3D9970'
                },
                {
                    'if': {'filter_query': '{operation} eq "Продажа"'},
                    'backgroundColor': 'white',
                    'color': '#FF0000'
                },
            ]
        ),
        style={'margin-left': '400px'}  # Сдвиг вправо
    )
]

tab7_content = [dcc.Graph(id='MyEquityHistory', style={'margin-top': 10})]

# Создаем приложение Dash
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])

app.layout = html.Div(children=[

    html.Div(children=[
        html.Div(children=[
            # График улыбки волатильности
            dcc.Graph(id='plot_smile'),
        ], style={'width': '87%', 'display': 'inline-block'}),

        html.Div(children=[
            # Текущее время обновления данных
            html.H6(id='last_update_time'),

            # html.Div(id='dd-output-container')]),
            html.Div([
                # Селектор выбора базового актива
                dcc.Dropdown(df._base_asset_ticker.unique(), value=df._base_asset_ticker.unique()[0],
                             id='dropdown-selection')
            ]),

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
            interval=1000 * 60,   # 1 минута
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
    # # Список опционов
    # df = pd.DataFrame.from_dict(option_list, orient='columns')
    # df = df.loc[df['_volatility'] > 0]
    # df['_expiration_datetime'] = pd.to_datetime(df['_expiration_datetime'], format='%a, %d %b %Y %H:%M:%S GMT')
    # df['_expiration_datetime'].dt.date
    # df['expiration_date'] = df['_expiration_datetime'].dt.strftime('%d.%m.%Y')
    # dff = df[(df._base_asset_ticker == value) & (df._type == 'C')]
    # print(f'dff: {dff}')
    # return dff.tail(450).to_json(date_format='iso', orient='split')


# Колбэк для обновления времени последнего обновления данных с периодичностью 10 секунд
@app.callback(Output('last_update_time', 'children'),
              [Input('interval-component', 'n_intervals')])
def update_time(n):
    fetch_api_data()
    # My portfoloio info data
    with open(temp_obj.substitute(name_file='QUIK_MyPortfolioInfo.csv'), 'r') as file:
        info = file.read()
    return [
        'Last update: {}'.format(datetime.datetime.now().strftime('%d.%m.%Y %H:%M:%S')),
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
        # print(df.columns)

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
            df_table_base = df_table
            df_table_base = df_table_base[df_table_base.option_base == value]
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
        # fig = px.line(dff_call, x='_strike', y='_volatility', color='expiration_date', width=1000, height=600)
        # fig = px.line(dff_call, x='_strike', y='_volatility', color='expiration_date')
        for exp_day in dff_call['expiration_date'].unique():
            dff_smile = dff_call[dff_call.expiration_date == exp_day]
            fig.add_trace(go.Scatter(x=dff_smile['_strike'], y=dff_smile['_volatility'], mode='lines+text',
                                     name=exp_day), secondary_y=False, )

        # Мои позиции BUY
        fig.add_trace(go.Scatter(x=df_table_buy['strike'], y=df_table_buy['OpenIV'],
                                 mode='markers+text', text=df_table_buy['OpenIV'], textposition='middle left',
                                 marker=dict(size=11, symbol="star-triangle-up-open", color='darkgreen'),
                                 name='My Pos Buy',
                                 customdata=df_table_buy[['option_type', 'net_pos', 'expdate', 'ticker']],
                                 hovertemplate="<b>%{customdata}</b>"
                                 ))

        fig.update_traces(
            marker=dict(
                size=8,
                symbol="star-triangle-up-open",
                line=dict(
                    width=2,
                    #             color="DarkSlateGrey" Line colors don't apply to open markers
                )
            ),
            selector=dict(mode="markers")
        )

        # Мои позиции SELL
        fig.add_trace(go.Scatter(x=df_table_sell['strike'], y=df_table_sell['OpenIV'],
                                 mode='markers+text', text=df_table_sell['OpenIV'], textposition='middle left',
                                 marker=dict(size=11, symbol="star-triangle-down-open", color='darkmagenta'),
                                 name='My Pos Sell',
                                 customdata=df_table_sell[['option_type', 'net_pos', 'expdate', 'ticker']],
                                 hovertemplate="<b>%{customdata}</b><br>"
                                 ))

        # Мои ордерра BUY
        fig.add_trace(go.Scatter(x=df_orders_buy['strike'], y=df_orders_buy['volatility'],
                                 mode='markers+text', text=df_orders_buy['volatility'], textposition='middle left',
                                 marker=dict(size=8, symbol="cross-thin", line=dict(width=1, color="darkgreen")),
                                 name='My Orders BUY',
                                 customdata=df_orders_buy[['operation', 'option_type', 'expdate', 'price', 'ticker']],
                                 hovertemplate="<b>%{customdata}</b><br>"
                                 ))

        # Мои ордерра SELL
        fig.add_trace(go.Scatter(x=df_orders_sell['strike'], y=df_orders_sell['volatility'],
                                 mode='markers+text', text=df_orders_sell['volatility'], textposition='middle left',
                                 marker=dict(size=8, symbol="cross-thin", line=dict(width=1, color="darkmagenta")),
                                 name='My Orders SELL',
                                 customdata=df_orders_sell[['operation', 'option_type', 'expdate', 'price', 'ticker']],
                                 hovertemplate="<b>%{customdata}</b><br>"
                                 ))

        # Last Bid Ask for MyPos and MyOrders
        favorites_list = MyPos_ticker_list + tikers  # слияние списков
        favorites_ticker_list = set(favorites_list)
        dff_MyPosOrders = df[(df._base_asset_ticker == value) & (df._ticker.isin(favorites_ticker_list))]
        dff_MyPosOrders = dff_MyPosOrders.apply(lambda x: round(x, 2))
        dff_MyPosOrders.loc[dff_MyPosOrders['_type'] == 'C', '_type'] = 'Call'
        dff_MyPosOrders.loc[dff_MyPosOrders['_type'] == 'P', '_type'] = 'Put'
        for i in dff_MyPosOrders['_last_price_timestamp']:
            if isnan(i) != True:
                UTC_seconds = i
                MSK_time = utc_timestamp_to_msk_datetime(UTC_seconds)
                MSK_time = MSK_time.strftime('%H:%M:%S')
                dff_MyPosOrders[str(int(i))] = dff_MyPosOrders.replace(int(i), MSK_time, inplace=True)
        # print(dff_MyPosOrders['_last_price_timestamp'])

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
                                      '_last_price_timestamp']],
                                 hovertemplate="<b>%{customdata}</b><br>"
                                 ))

        # TrueVega позиции
        fig.add_trace(go.Bar(x=df_table_base['strike'], y=df_table_base['TrueVega'], text=df_table_base['TrueVega'],
                             textposition='auto', name='TrueVega', opacity=0.2), secondary_y=True)

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
        # убрать сетку правой оси
        fig['layout']['yaxis2']['showgrid'] = False
        return fig

    except Exception as e:
        print(f"Ошибка при обновлении графика: {str(e)}")
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
    limit_time = datetime.datetime.now() - timedelta(hours=12 * slider_value)

    # СВЕЧИ Данные для графика базового актива
    # Пробегаем по списку базовых активов, находим последнюю цену базового актива
    # base_asset_list = model_from_api[0]
    for asset in base_asset_list:
        if asset.get('_ticker') == dropdown_value:
            last_price_fut = asset.get('_last_price')
            # print(last_price_fut)
    # Candles (свечи/бары) для базового актива
    time_frame = 'M15'
    datapath = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'Data', 'Finam', '')  # Путь к файлам баров
    dataname = f'SPBFUT.{dropdown_value}'
    filename = f'{datapath}{dataname}_{time_frame}.txt'  # Полное имя файла
    with open(file=filename, mode='r') as file:
        df_candles = pd.read_csv(file, sep='\t', header=0)
        df_candles['datetime'] = pd.to_datetime(df_candles['datetime'], format='%d.%m.%Y %H:%M')
        df_candles = df_candles.sort_values('datetime').reset_index(drop=True)
        df_candles = df_candles[(df_candles.datetime > limit_time)]
        # df_candles.loc[df_candles.index[-1], 'close'] = last_price_fut # Устанавливаем последнюю цену базового актива в бар
    file.close()

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
                                 line=dict(color='gray', width=1, dash='dot'),
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

    return fig


# Обновление данных графика истории моей позиции
@app.callback(Output('MyPosTiltHistory', 'figure', allow_duplicate=True),
              [Input('dropdown-selection', 'value'),
               Input('my_slider', 'value'),
               Input('interval-component', 'n_intervals'),
               ],
              prevent_initial_call=True)
def update_output_MyPosHistory(dropdown_value, slider_value, n):
    limit_time = datetime.datetime.now() - timedelta(hours=12 * slider_value)

    # СВЕЧИ Данные для графика базового актива
    # Пробегаем по списку базовых активов, находим последнюю цену базового актива
    base_asset_list = model_from_api[0]
    for asset in base_asset_list:
        if asset.get('_ticker') == dropdown_value:
            last_price_fut = asset.get('_last_price')
    # Candles (свечи/бары) для базового актива
    time_frame = 'M15'
    datapath = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'Data', 'Finam', '')  # Путь к файлам баров
    dataname = f'SPBFUT.{dropdown_value}'
    filename = f'{datapath}{dataname}_{time_frame}.txt'  # Полное имя файла
    with open(file=filename, mode='r') as file:
        df_candles = pd.read_csv(file, sep='\t', header=0)
        df_candles['datetime'] = pd.to_datetime(df_candles['datetime'], format='%d.%m.%Y %H:%M')
        df_candles = df_candles.sort_values('datetime').reset_index(drop=True)
        df_candles = df_candles[(df_candles.datetime > limit_time)]
        # df_candles.loc[df_candles.index[-1], 'close'] = last_price_fut # Устанавливаем последнюю цену базового актива в бар
    file.close()

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

    # # График истории цены базового актива
    # fig.add_trace(go.Scatter(x=df_BaseAssetPrice['DateTime'], y=df_BaseAssetPrice['last_price'], mode='lines+text',
    #                          name=dropdown_value, line=dict(color='gray', width=2, dash='dashdot')),
    #               secondary_y=False, )

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

    return fig


# Наклон улыбки (обновление данных графика истории наклона улыбки)
@app.callback(Output('naklon_history', 'figure', allow_duplicate=True),
              [Input('dropdown-selection', 'value'),
               Input('my_slider', 'value'),
               Input('interval-component', 'n_intervals'),
               ],
              prevent_initial_call=True)
def update_output_history_naklon(dropdown_value, slider_value, n):
    # limit = 450 * slider_value
    limit_time = datetime.datetime.now() - timedelta(hours=12 * slider_value)

    # СВЕЧИ Данные для графика базового актива
    # Пробегаем по списку базовых активов, находим последнюю цену базового актива
    base_asset_list = model_from_api[0]
    for asset in base_asset_list:
        if asset.get('_ticker') == dropdown_value:
            last_price_fut = asset.get('_last_price')
    # Candles (свечи/бары) для базового актива
    time_frame = 'M15'
    datapath = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'Data', 'Finam', '')  # Путь к файлам баров
    dataname = f'SPBFUT.{dropdown_value}'
    filename = f'{datapath}{dataname}_{time_frame}.txt'  # Полное имя файла
    with open(file=filename, mode='r') as file:
        df_candles = pd.read_csv(file, sep='\t', header=0)
        df_candles['datetime'] = pd.to_datetime(df_candles['datetime'], format='%d.%m.%Y %H:%M')
        df_candles = df_candles.sort_values('datetime').reset_index(drop=True)
        df_candles = df_candles[(df_candles.datetime > limit_time)]
        # df_candles.loc[df_candles.index[-1], 'close'] = last_price_fut # Устанавливаем последнюю цену базового актива в бар
    file.close()

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
                                 line=dict(color='gray', width=1, dash='dot'),
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

    # # График истории цены базового актива
    # fig.add_trace(go.Scatter(x=df_BaseAssetPrice['DateTime'], y=df_BaseAssetPrice['last_price'], mode='lines+text',
    #                          name=dropdown_value, line=dict(color='gray', width=3, dash='dashdot')),
    #               secondary_y=False, )

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

    return fig


## EQUITY HISTORY##
@app.callback(Output('MyEquityHistory', 'figure'),
              [Input('dropdown-selection', 'value'),
               Input('my_slider', 'value'),
               Input('interval-component', 'n_intervals')],
              prevent_initial_call=True)
def update_equity_history(dropdown_value, slider_value, n):
    global df_combined
    limit_time = datetime.datetime.now() - timedelta(hours=10 * 12 * slider_value)
    # Создаем копию для избежания предупреждения
    df_limited = df_combined[(df_combined.Date > limit_time)].copy()
    # Преобразуем формат даты
    df_limited['Date'] = pd.to_datetime(df_limited['Date'], format='%d.%m.%Y')

    # СВЕЧИ Данные для графика базового актива
    # Поиск последней цены базового актива
    # model_from_api = get_object_from_json_endpoint_with_retry('https://option-volatility-dashboard.tech/dump_model', timeout=5)
    # Пробегаем по списку базовых активов, находим последнюю цену базового актива
    base_asset_list = model_from_api[0]
    for asset in base_asset_list:
        if asset.get('_ticker') == dropdown_value:
            last_price_fut = asset.get('_last_price')
    # Candles (свечи/бары) для базового актива
    time_frame = 'D1'
    datapath = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'Data', 'Finam', '')  # Путь к файлам баров
    dataname = f'SPBFUT.{dropdown_value}'
    filename = f'{datapath}{dataname}_{time_frame}.txt'  # Полное имя файла
    with open(file=filename, mode='r') as file:
        df_candles = pd.read_csv(file, sep='\t', header=0)
        df_candles['datetime'] = pd.to_datetime(df_candles['datetime'], format='%d.%m.%Y %H:%M')
        df_candles = df_candles.sort_values('datetime').reset_index(drop=True)
        df_candles = df_candles[(df_candles.datetime > limit_time)]
        df_candles.loc[df_candles.index[-1], 'close'] = last_price_fut
    file.close()

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

    return fig


# Callback to update the table "MyPos Table"
@app.callback(
    Output('table', 'data', allow_duplicate=True),
    [Input('interval-component', 'n_intervals'),
     Input('dropdown-selection', 'value')],
    prevent_initial_call=True)
def updateTable(n, value):
    df_pos = pd.read_csv(temp_obj.substitute(name_file='QUIK_MyPos.csv'), sep=';')
    # Фильтрация строк по базовому активу
    df_pos = df_pos[df_pos['option_base'] == value]

    # # Замена нулевых и NaN значений 'P/L last' на значения 'P/L theor'
    # df_pos['P/L last'] = df_pos['P/L last'].replace(0, pd.NA)  # Заменяем 0 на NaN
    # df_pos['P/L last'] = df_pos['P/L last'].fillna(df_pos['P/L theor'])  # Заменяем NaN на значения из P/L theor

    # Замена нулевых значений 'P/L last' на значения 'P/L theor'
    df_pos['P/L last'] = df_pos['P/L last'].mask(df_pos['P/L last'] == 0, df_pos['P/L theor'])

    # Вычисление итогов по колонке net_pos
    total_net_pos = df_pos['net_pos'].sum()
    total_theor = df_pos['theor'].sum()
    # total_theor = (df_pos['theor'] * df_pos['net_pos']).sum()
    total_last = df_pos['last'].sum()

    # Theor
    weights_theor = df_pos['theor'] * abs(df_pos['net_pos'])
    total_weight_theor = weights_theor.sum()

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
    weighted_pl_theor = (df_pos[
                             'P/L theor'] * weights_theor).sum() / total_weight_theor if 'P/L theor' in df_pos.columns and total_weight_theor != 0 else 0
    weighted_pl_last = (df_pos[
                            'P/L last'] * weights_last).sum() / total_weight_last if 'P/L last' in df_pos.columns and total_weight_last != 0 else 0

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
    total_row['P/L theor'] = round(weighted_pl_theor, 2)
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