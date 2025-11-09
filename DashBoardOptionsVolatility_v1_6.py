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
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
from app.central_strike import _calculate_central_strike
from app.supported_base_asset import MAP
from string import Template
import time
import random
from functools import lru_cache


@lru_cache(maxsize=None)
def get_cached_data(url):
    return get_object_from_json_endpoint_with_retry(url)


temp_str = 'C:\\Users\\Андрей\\YandexDisk\\_ИИС\\Position\\$name_file'
temp_obj = Template(temp_str)


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


# # Create the app
# app = dash.Dash(__name__)

# My positions data
with open(temp_obj.substitute(name_file='MyPos.csv'), 'r') as file:
    df_table = pd.read_csv(file, sep=';')
# Close the file explicitly file.close()
file.close()
# print('\n df_table.columns:\n', df_table.columns)
# print('df_table:\n', df_table)

# My orders data
with open(temp_obj.substitute(name_file='MyOrders.csv'), 'r') as file:
    df_orders = pd.read_csv(file, sep=';')
# Close the file explicitly file.close()
file.close()


# print('\n df_orders.columns:\n', df_orders.columns)
# print('\n df_orders:\n', df_orders)

def get_object_from_json_endpoint(url, method='GET', params={}):
    response = requests.request(method, url, params=params)

    response_data = None
    if response.status_code == 200:
        response_data = response.json()
    else:
        raise Exception(f"Error: {response.status_code}")
    return response_data


def zero_to_nan(values):
    """Replace every 0 with 'nan' and return a copy."""
    return [float('nan') if x == 0 else x for x in values]


model_from_api = get_object_from_json_endpoint_with_retry('https://option-volatility-dashboard.tech/dump_model')

# Список базовых активов, вычисление и добавление в словарь центрального страйка
base_asset_list = model_from_api[0]
# print('base_asset_list:', base_asset_list)
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

# Tabs content
tab1_content = [dcc.Graph(id='MyPosTiltHistory', style={'margin-top': 10})]
tab2_content = [dcc.Graph(id='naklon_history', style={'margin-top': 10})]
tab3_content = [# График истории
                dcc.Graph(id='plot_history', style={'margin-top': 10}),
                dcc.RadioItems(options=['Call', 'Put'],
                               value='Call',
                               inline=True,
                               style=dict(display='flex', justifyContent='right'),
                               id='my-radio-buttons-final'),
            ]
tab4_content = [html.Div(id='intermediate-value', style={'display': 'none'}),
        dash_table.DataTable(id='table', data=df_table.to_dict('records'), page_size=20,
                             style_table={'max-width': '50px'},
                             style_data_conditional=[
                                 {
                                     'if': {
                                         'filter_query': '{P/L} > 1',
                                         'column_id': 'P/L'
                                     },
                                     'backgroundColor': '#3D9970',
                                     'color': 'white'
                                 }
                             ])]

app = dash.Dash(external_stylesheets=[dbc.themes.BOOTSTRAP])
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
                    dbc.Tab(tab1_content, label='MyPos'),
                    dbc.Tab(tab2_content, label='Наклон улыбки'),
                    dbc.Tab(tab3_content, label='Volatility history'),
                    dbc.Tab(tab4_content, label='MyPos table'),
                ]),


        # # График истории "Наклон моей позиции"
        # dcc.Graph(id='MyPosTiltHistory'),


        # # График истории "Наклон"
        # dcc.Graph(id='naklon_history'),

        # # Радио кнопки Call и Put
        # dcc.RadioItems(options=['Call', 'Put'],
        #                value='Call',
        #                inline=True,
        #                style=dict(display='flex', justifyContent='right'),
        #                id='my-radio-buttons-final'),

        # # График истории
        # dcc.Graph(id='plot_history'),

        # # Таблица моих позиций
        # html.Div(id='intermediate-value', style={'display': 'none'}),
        # dash_table.DataTable(id='table', data=df_table.to_dict('records'), page_size=20,
        #                      style_table={'max-width': '50px'},
        #                      style_data_conditional=[
        #                          {
        #                              'if': {
        #                                  'filter_query': '{P/L} > 1',
        #                                  'column_id': 'P/L'
        #                              },
        #                              'backgroundColor': '#3D9970',
        #                              'color': 'white'
        #                          }
        #                      ]),

        # Интервал обновления данных
        dcc.Interval(
            id='interval-component',
            interval=1000 * 10,
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


# Callback to update the table
@app.callback(Output('intermediate-value', 'children'),
              [Input('interval-component', 'n_intervals')],
              [State('intermediate-value', 'children')])
def clean_data(value, dff):
    model_from_api = get_object_from_json_endpoint_with_retry('https://option-volatility-dashboard.tech/dump_model')

    # Список опционов
    option_list = model_from_api[1]
    df = pd.DataFrame.from_dict(option_list, orient='columns')
    df = df.loc[df['_volatility'] > 0]
    df['_expiration_datetime'] = pd.to_datetime(df['_expiration_datetime'], format='%a, %d %b %Y %H:%M:%S GMT')
    df['_expiration_datetime'].dt.date
    df['expiration_date'] = df['_expiration_datetime'].dt.strftime('%d.%m.%Y')
    dff = df[(df._base_asset_ticker == value) & (df._type == 'C')]
    # print(dff)
    return dff.tail(450).to_json(date_format='iso', orient='split')


# Callback to update the last-update-time element
@app.callback(Output('last_update_time', 'children'),
              [Input('interval-component', 'n_intervals')])
def update_time(n):
    return 'Last update time: {}'.format(datetime.datetime.now())


# Callback to update the line-graph volatility smile (обновление улыбки волатильности)
@app.callback(Output('plot_smile', 'figure', allow_duplicate=True),
              [Input('dropdown-selection', 'value'),
               Input('interval-component', 'n_intervals')],
              prevent_initial_call=True)
def update_output_smile(value, n):
    try:
        model_from_api = get_object_from_json_endpoint_with_retry('https://option-volatility-dashboard.tech/dump_model',
                                                                  timeout=5)

        # Список базовых активов, вычисление и добавление в словарь центрального страйка
        base_asset_list = model_from_api[0]
        base_asset_ticker_list = {}
        for i in range(len(base_asset_list)):
            base_asset_ticker_list.update({base_asset_list[i]['_ticker']: base_asset_list[i]['_base_asset_code']})

        # Список опционов
        option_list = model_from_api[1]
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
        # Open the file using the "with" statement
        with open(temp_obj.substitute(name_file='MyPos.csv'), 'r') as file:
            df_table = pd.read_csv(file, sep=';')
            # df_table = df_table[(df_table.optionbase == value)
            df_table_buy = df_table[(df_table.optionbase == value) & (df_table.net_pos > 0)]
            df_table_sell = df_table[(df_table.optionbase == value) & (df_table.net_pos < 0)]
            MyPos_ticker_list = []
            for i in range(len(df_table)):
                MyPos_ticker_list.append(df_table['ticker'][i])
            # DataFrame для отрисовки баланса TrueVega
            df_table_base = df_table
            df_table_base = df_table_base[df_table_base.optionbase == value]
        # Close the file explicitly file.close()
        file.close()

        # My orders data
        # Open the file using the "with" statement
        with open(temp_obj.substitute(name_file='MyOrders.csv'), 'r') as file:
            df_orders = pd.read_csv(file, sep=';')
            df_orders = df_orders[(df_orders.optionbase == value)]
            df_orders_buy = df_orders[(df_orders.optionbase == value) & (df_orders.operation == 'Купля')]
            df_orders_sell = df_orders[(df_orders.optionbase == value) & (df_orders.operation == 'Продажа')]
            # Converting DataFrame "df_orders" to a list "tikers" containing all the rows of column 'tiker'
            tikers = df_orders['tiker'].tolist()
        # Close the file explicitly file.close()
        file.close()

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
                                 customdata=df_table_buy[['optiontype', 'net_pos', 'expdate', 'ticker']],
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
                                 customdata=df_table_sell[['optiontype', 'net_pos', 'expdate', 'ticker']],
                                 hovertemplate="<b>%{customdata}</b><br>"
                                 ))

        # Мои ордерра BUY
        fig.add_trace(go.Scatter(x=df_orders_buy['strike'], y=df_orders_buy['volatility'],
                                 mode='markers+text', text=df_orders_buy['volatility'], textposition='middle left',
                                 marker=dict(size=8, symbol="cross-thin", line=dict(width=1, color="darkgreen")),
                                 name='My Orders BUY',
                                 customdata=df_orders_buy[['operation', 'optiontype', 'expdate', 'price', 'tiker']],
                                 hovertemplate="<b>%{customdata}</b><br>"
                                 ))

        # Мои ордерра SELL
        fig.add_trace(go.Scatter(x=df_orders_sell['strike'], y=df_orders_sell['volatility'],
                                 mode='markers+text', text=df_orders_sell['volatility'], textposition='middle left',
                                 marker=dict(size=8, symbol="cross-thin", line=dict(width=1, color="darkmagenta")),
                                 name='My Orders SELL',
                                 customdata=df_orders_sell[['operation', 'optiontype', 'expdate', 'price', 'tiker']],
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
        fig.add_trace(go.Scatter(x=dff_MyPosOrders['_strike'], y=dff_MyPosOrders['_ask_iv'], visible='legendonly',
                                 mode='markers', text=dff_MyPosOrders['_ask_iv'], textposition='top left',
                                 marker=dict(size=8, symbol="triangle-down", color='red'),
                                 name='Ask',
                                 customdata=dff_MyPosOrders[
                                     ['_type', '_ask', '_ask_iv', 'expiration_date', '_ticker']],
                                 hovertemplate="<b>%{customdata}</b><br>"
                                 ))

        # BID
        fig.add_trace(go.Scatter(x=dff_MyPosOrders['_strike'], y=dff_MyPosOrders['_bid_iv'], visible='legendonly',
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
                             textposition='auto', name='TrueVega', opacity=0.1), secondary_y=True)

        # Цена базового актива (вертикальная линия)
        fig.add_vline(x=base_asset_last_price, line_dash='dash', line_color='firebrick')

        fig.update_layout(
            title_text=f"Volatility smile of the option series <b>{value}<b>", uirevision="Don't change"
        )
        fig.update_layout(
            margin=dict(l=0, r=0, t=30, b=0),
        )
        # убрать сетку правой оси
        fig['layout']['yaxis2']['showgrid'] = False
        return fig

    except Exception as e:
        print(f"Ошибка при обновлении графика: {str(e)}")
        raise PreventUpdate


# Callback to update the line-graph history data (обновление данных графика истории)
@app.callback(Output('plot_history', 'figure', allow_duplicate=True),
              [Input('dropdown-selection', 'value'),
               Input('my_slider', 'value'),
               Input('my-radio-buttons-final', 'value'),
               Input('interval-component', 'n_intervals'),
               ],
              prevent_initial_call=True)
def update_output_history(dropdown_value, slider_value, radiobutton_value, n):
    # limit = 450 * slider_value
    limit_time = datetime.datetime.now() - timedelta(hours=12 * slider_value)

    # BaseAssetPrice history data DAMP
    with open(temp_obj.substitute(name_file='BaseAssetPriceHistoryDamp.csv'), 'r') as file:
        df_BaseAssetPrice = pd.read_csv(file, sep=';')
        df_BaseAssetPrice = df_BaseAssetPrice[(df_BaseAssetPrice.ticker == dropdown_value)]
        # df_BaseAssetPrice = df_BaseAssetPrice.tail(limit)
        df_BaseAssetPrice['DateTime'] = pd.to_datetime(df_BaseAssetPrice['DateTime'], format='%Y-%m-%d %H:%M:%S')
        df_BaseAssetPrice.index = pd.DatetimeIndex(df_BaseAssetPrice['DateTime'])
        df_BaseAssetPrice = df_BaseAssetPrice[(df_BaseAssetPrice.DateTime > limit_time)]
    # Close the file
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
        fig.add_trace(go.Scatter(x=dff['DateTime'], y=dff['Real_vol'],
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

    # График истории цены базового актива
    fig.add_trace(go.Scatter(x=df_BaseAssetPrice['DateTime'], y=df_BaseAssetPrice['last_price'], mode='lines+text',
                             name=dropdown_value, line=dict(color='gray', width=3, dash='dashdot')),
                  secondary_y=False, )

    # Убираем неторговое время
    fig.update_xaxes(
        rangebreaks=[
            dict(bounds=["sat", "mon"]),  # hide weekends, eg. hide sat to before mon
            dict(bounds=[24, 9], pattern="hour"),  # hide hours outside of 9am-24pm
        ]
    )

    fig.update_layout(xaxis_title=None)

    fig.update_layout(
        title_text=f'The history of the volatility of the central strike of the option series <b>{dropdown_value}<b>',
        uirevision="Don't change"
    )
    fig.update_layout(
        margin=dict(l=0, r=0, t=30, b=0),
    )

    return fig

# Callback to update the line-graph history MyPosTilt data (обновление данных графика истории наклона моей позиции)
@app.callback(Output('MyPosTiltHistory', 'figure', allow_duplicate=True),
              [Input('dropdown-selection', 'value'),
               Input('my_slider', 'value'),
               Input('interval-component', 'n_intervals'),
               ],
              prevent_initial_call=True)
def update_output_MyPosTiltn(dropdown_value, slider_value, n):
    # limit = 450 * slider_value
    limit_time = datetime.datetime.now() - timedelta(hours=12 * slider_value)

    # BaseAssetPrice history data DAMP
    with open(temp_obj.substitute(name_file='BaseAssetPriceHistoryDamp.csv'), 'r') as file:
        df_BaseAssetPrice = pd.read_csv(file, sep=';')
        df_BaseAssetPrice = df_BaseAssetPrice[(df_BaseAssetPrice.ticker == dropdown_value)]
        # df_BaseAssetPrice = df_BaseAssetPrice.tail(limit)
        df_BaseAssetPrice['DateTime'] = pd.to_datetime(df_BaseAssetPrice['DateTime'], format='%Y-%m-%d %H:%M:%S')
        df_BaseAssetPrice.index = pd.DatetimeIndex(df_BaseAssetPrice['DateTime'])
        df_BaseAssetPrice = df_BaseAssetPrice[(df_BaseAssetPrice.DateTime > limit_time)]
    # Close the file
    file.close()

    # ДАННЫЕ ИЗ DAMP/csv
    # MyPosTilt.csv history data options volatility
    with open(temp_obj.substitute(name_file='MyPosTilt.csv'), 'r') as file:
        df_MyPosTilt = pd.read_csv(file, sep=';')
        df_MyPosTilt = df_MyPosTilt[(df_MyPosTilt.optionbase == dropdown_value)]
        # df_MyPosTilt = df_MyPosTilt.tail(limit * len(df_MyPosTilt['expiration_datetime'].unique()) * 2) # глубина истории по количеству серий

        df_MyPosTilt['DateTime'] = pd.to_datetime(df_MyPosTilt['DateTime'],
                                                           format='%Y-%m-%d %H:%M:%S')
        df_MyPosTilt.index = pd.DatetimeIndex(df_MyPosTilt['DateTime'])
        # df_MyPosTilt = df_MyPosTilt[(df_vol_history.type == radiobutton_value)]
        df_MyPosTilt = df_MyPosTilt[(df_MyPosTilt.DateTime > limit_time)]
        # print(df_MyPosTilt)
    # Close the file
    file.close()

    # Create figure with secondary y-axis
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # График истории наклона моей позиции (из CSV MyPosTilt.csv)
    for d_exp in sorted(df_MyPosTilt['expdate'].unique()):
        dff = df_MyPosTilt[df_MyPosTilt.expdate == d_exp]
        fig.add_trace(go.Scatter(x=dff['DateTime'], y=dff['MyPosTilt'],
                                 legendgroup="group",  # this can be any string, not just "group"
                                 legendgrouptitle_text="MyPosTilt",
                                 mode='lines+text',
                                 line=dict(dash='dot'),
                                 name=d_exp), secondary_y=True, )
    # fig.update_layout(legend_title_text=radiobutton_value)

    # График истории наклона моей позиции ПО ценам из стакана (из CSV MyPosTilt.csv)
    for d_exp in sorted(df_MyPosTilt['expdate'].unique()):
        dff = df_MyPosTilt[df_MyPosTilt.expdate == d_exp]
        fig.add_trace(go.Scatter(x=dff['DateTime'], y=dff['RealTilt'],
                                 legendgroup="group1",  # this can be any string, not just "group"
                                 legendgrouptitle_text="RealTilt",
                                 mode='lines+text',
                                 name=d_exp), secondary_y=True, )
    # fig.update_layout(legend_title_text=radiobutton_value)

    # График истории наклона моей позиции по БИРЖЕВОЙ волатильности QuikTilt (из CSV MyPosTilt.csv)
    for d_exp in sorted(df_MyPosTilt['expdate'].unique()):
        dff = df_MyPosTilt[df_MyPosTilt.expdate == d_exp]
        fig.add_trace(go.Scatter(x=dff['DateTime'], y=dff['QuikTilt'],
                                 legendgroup="group2",
                                 legendgrouptitle_text="QuikTilt",
                                 mode='lines+text',
                                 line=dict(color='gray', width=1, dash='dot'),
                                 name=d_exp), secondary_y=True, )
    fig.update_layout(legend=dict(groupclick="toggleitem"))

    # График истории цены базового актива
    fig.add_trace(go.Scatter(x=df_BaseAssetPrice['DateTime'], y=df_BaseAssetPrice['last_price'], mode='lines+text',
                             name=dropdown_value, line=dict(color='gray', width=2, dash='dashdot')),
                  secondary_y=False, )

    # Убираем неторговое время
    fig.update_xaxes(
        rangebreaks=[
            dict(bounds=["sat", "mon"]),  # hide weekends, eg. hide sat to before mon
            dict(bounds=[24, 9], pattern="hour"),  # hide hours outside of 9am-24pm
        ]
    )

    fig.update_layout(xaxis_title=None)

    fig.update_layout(
        title_text=f'Наклон моей позиции, option series <b>{dropdown_value}<b>', uirevision="Don't change"
    )
    fig.update_layout(
        margin=dict(l=0, r=0, t=30, b=0),
    )

    return fig

# Callback to update the line-graph history 'naklon' data (обновление данных графика истории наклона улыбки)
@app.callback(Output('naklon_history', 'figure', allow_duplicate=True),
              [Input('dropdown-selection', 'value'),
               Input('my_slider', 'value'),
               Input('interval-component', 'n_intervals'),
               ],
              prevent_initial_call=True)
def update_output_history_naklon(dropdown_value, slider_value, n):
    # limit = 450 * slider_value
    limit_time = datetime.datetime.now() - timedelta(hours=12 * slider_value)

    # BaseAssetPrice history data DAMP
    with open(temp_obj.substitute(name_file='BaseAssetPriceHistoryDamp.csv'), 'r') as file:
        df_BaseAssetPrice = pd.read_csv(file, sep=';')
        df_BaseAssetPrice = df_BaseAssetPrice[(df_BaseAssetPrice.ticker == dropdown_value)]
        # df_BaseAssetPrice = df_BaseAssetPrice.tail(limit)
        df_BaseAssetPrice['DateTime'] = pd.to_datetime(df_BaseAssetPrice['DateTime'], format='%Y-%m-%d %H:%M:%S')
        df_BaseAssetPrice.index = pd.DatetimeIndex(df_BaseAssetPrice['DateTime'])
        df_BaseAssetPrice = df_BaseAssetPrice[(df_BaseAssetPrice.DateTime > limit_time)]
    # Close the file
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
        fig.add_trace(go.Scatter(x=dff['DateTime'], y=dff['Real'],
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

    # График истории цены базового актива
    fig.add_trace(go.Scatter(x=df_BaseAssetPrice['DateTime'], y=df_BaseAssetPrice['last_price'], mode='lines+text',
                             visible='legendonly',
                             name=dropdown_value, line=dict(color='gray', width=3, dash='dashdot')),
                  secondary_y=False, )

    # Убираем неторговое время
    fig.update_xaxes(
        rangebreaks=[
            dict(bounds=["sat", "mon"]),  # hide weekends, eg. hide sat to before mon
            dict(bounds=[24, 9], pattern="hour"),  # hide hours outside of 9am-24pm
        ]
    )

    fig.update_layout(xaxis_title=None)

    fig.update_layout(
        title_text=f'"Наклон улыбки" of the option series <b>{dropdown_value}<b>', uirevision="Don't change"
    )
    fig.update_layout(
        margin=dict(l=0, r=0, t=30, b=0),
    )

    return fig


# Callback to update the table
@app.callback(
    Output('table', 'data', allow_duplicate=True),
    [Input('interval-component', 'n_intervals'),
     Input('dropdown-selection', 'value')],
    prevent_initial_call=True)
def updateTable(n, value):
    df_pos = pd.read_csv(temp_obj.substitute(name_file='MyPos.csv'), sep=';')
    # Фильтрация строк по базовому активу
    df_pos = df_pos[df_pos['optionbase'] == value]

    return df_pos.to_dict('records')


# Callback to update the graph-gauge
@app.callback(
    Output('graph-gauge', 'value', allow_duplicate=True),
    [Input('interval-component', 'n_intervals'),
     Input('dropdown-selection', 'value')],
    prevent_initial_call=True
)
def updateGauge(n, value):
    df_pos = pd.read_csv(temp_obj.substitute(name_file='MyPos.csv'), sep=';')
    # Фильтрация строк по базовому активу
    df_pos = df_pos[df_pos['optionbase'] == value]

    # TrueVega
    tv_sum_positive = df_pos.loc[df_pos['net_pos'] > 0, 'TrueVega'].sum()
    tv_sum_negative = df_pos.loc[df_pos['net_pos'] < 0, 'TrueVega'].sum()
    tv_sum = abs(tv_sum_positive) + abs(tv_sum_negative)
    if tv_sum == 0:
        value = 0
    else:
        value = (abs(tv_sum_positive) / (abs(tv_sum_positive) + abs(tv_sum_negative))) * 10
    return value


# # Callback to update the histogram TrueVega
# @app.callback(
#     Output('Hisogram_TrueVega', 'data', allow_duplicate=True),
#     [Input('interval-component', 'n_intervals'),
#      Input('dropdown-selection', 'value')],
#     prevent_initial_call=True
# )
# def updateGauge(n, value):
#     df_pos = pd.read_csv(temp_obj.substitute(name_file='MyPos.csv'), sep=';')
#     # Фильтрация строк по базовому активу
#     df_pos = df_pos[df_pos['optionbase'] == value]
#     return df_pos.to_dict('records')

if __name__ == '__main__':
    app.run(debug=False)  # Run the Dash app