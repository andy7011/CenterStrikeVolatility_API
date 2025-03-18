# from alor_api_test import AlorApiTest
from infrastructure import env_utils
from infrastructure.alor_api import AlorApi
from supported_base_asset import MAP
import time
from math import isnan
import dash
from dash import dcc, Input, Output, callback, dash_table, State
from dash import html
import dash_daq as daq
import datetime
from datetime import timedelta
from pytz import timezone, utc  # Работаем с временнОй зоной и UTC
import requests
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
from central_strike import _calculate_central_strike
from supported_base_asset import MAP
from string import Template
import numpy as np
import schedule
import time
import csv
from typing import NoReturn
import threading

temp_str = 'C:\\Users\\ashadrin\\YandexDisk\\_ИИС\\Position\\$name_file'
temp_obj = Template(temp_str)

def utc_to_msk_datetime(dt, tzinfo=False):
    """Перевод времени из UTC в московское

    :param datetime dt: Время UTC
    :param bool tzinfo: Отображать временнУю зону
    :return: Московское время
    """
    dt_utc = utc.localize(dt)  # Задаем временнУю зону UTC
    # dt_msk = dt_utc.astimezone(tz_msk)  # Переводим в МСК
    dt_msk = dt_utc # Не требуется перевод в МСК
    return dt_msk if tzinfo else dt_msk.replace(tzinfo=None)

def utc_timestamp_to_msk_datetime(seconds) -> datetime:
    """Перевод кол-ва секунд, прошедших с 01.01.1970 00:00 UTC в московское время

    :param int seconds: Кол-во секунд, прошедших с 01.01.1970 00:00 UTC
    :return: Московское время без временнОй зоны
    """
    dt_utc = datetime.datetime.fromtimestamp(seconds)  # Переводим кол-во секунд, прошедших с 01.01.1970 в UTC
    return utc_to_msk_datetime(dt_utc)  # Переводим время из UTC в московское

class DashApp:
    # def run(self):
    #     print('RUN AlorApiTest')
    #     app.run_server(debug=True)
    #     print('Subscribe API')
    #     # self.run_server()

    def __init__(self):
        self._alor_api_test = None
        # self._alor_api_test = AlorApiTest

    def set_option_app(self, AlorApi):
        self._alor_api_test = AlorApi

    def start_app_in_thread(self):
        # Start Dash app in a separate thread
        dash_thread = threading.Thread(target=self._run_dash_app)
        dash_thread.daemon = True
        dash_thread.start()

    def _run_dash_app(self):
        port = int(env_utils.get_env_or_exit('BACKEND_PORT'))
        app.run(host='127.0.0.10', port='8050')

    def base_asset_history(self):
        return self._alor_api_test._df_candles()

    def run_server(self):
        app.run_server(debug=True)

    def _test_subscribe_to_candle(self):
        print('\n _test_subscribe_to_candle')
        for ticker in MAP.keys():
            self._alorApi.subscribe_to_bars(ticker, self._handle_quotes_event_bars)
            time.sleep(1)

    def _handle_quotes_event_bars(self, ticker, data):
        data['ticker'] = ticker
        # print(data)
        current_DateTime = datetime.datetime.now()
        currentTimestamp = int(datetime.datetime.timestamp(current_DateTime))  # текущее время в секундах UTC
        time_from = currentTimestamp - (24 * 60 * 7 * 60)  # минус одна неделя в секундах UTC
        if data['time'] > time_from:
            # MSK_time = utc_timestamp_to_msk_datetime(data['time'])
            # time_from_MSK = utc_timestamp_to_msk_datetime(time_from)
            # data['time'] = MSK_time.strftime('%Y-%m-%d %H:%M:%S')
            # time_from_MSK = time_from_MSK.strftime('%Y-%m-%d %H:%M:%S')

            df_candle = pd.DataFrame.from_dict([data])
            # print('df_candle', df_candle)
            self._df_candles = self._df_candles._append(df_candle, ignore_index=True)
            self._df_candles = self._df_candles.drop(self._df_candles[self._df_candles['time'] < time_from].index)  # Удаляем строки с временем старше одной недели (time_from)
        print(len(self._df_candles))

# Create the app
app = dash.Dash(__name__)

# My positions data
# Open the file using the "with" statement
with open(temp_obj.substitute(name_file='MyPos.csv'), 'r') as file:
    df_table = pd.read_csv(file, sep=';')
# Close the file explicitly file.close()
file.close()
# print('\n df_table.columns:\n', df_table.columns)
# print('df_table:\n', df_table)

# My orders data
# Open the file using the "with" statement
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
    return [float('nan') if x==0 else x for x in values]

model_from_api = get_object_from_json_endpoint('https://option-volatility-dashboard.ru/dump_model')

# Список базовых активов, вычисление и добавление в словарь центрального страйка
base_asset_list = model_from_api[0]
# print('base_asset_list:', base_asset_list)
for asset in base_asset_list:
    ticker = asset.get('_ticker')
    last_price = asset.get('_last_price')
    strike_step = MAP[ticker]['strike_step']
    central_strike = _calculate_central_strike(last_price, strike_step) # вычисление центрального страйка
    asset.update({
        'central_strike': central_strike
    })
# print('base_asset_list:', base_asset_list) # вывод списка базовых активов
base_asset_ticker_list = {}
for i in range(len(base_asset_list)):
    # print(base_asset_list[i]['_ticker'])
    base_asset_ticker_list.update({base_asset_list[i]['_ticker']:base_asset_list[i]['_base_asset_code']})
# print(base_asset_ticker_list)

# Список опционов из dump_model
option_list = model_from_api[1]
current_datetime = datetime.datetime.now()
df = pd.DataFrame.from_dict(option_list, orient='columns')
df = df.loc[df['_volatility'] > 0]
df['_expiration_datetime'] = pd.to_datetime(df['_expiration_datetime'])
df['_expiration_datetime'].dt.date
df['expiration_date'] = df['_expiration_datetime'].dt.strftime('%d.%m.%Y')

app.layout = html.Div(children=[

    # Текущее время обновления данных
    html.H6(id='last_update_time', style={'textAlign': 'left'}),

    html.Div(children=[
        # Селектор выбора базового актива
        dcc.Dropdown(df._base_asset_ticker.unique(), value=df._base_asset_ticker.unique()[0], id='dropdown-selection',  style={'width':'40%'}),
        html.Div(id='dd-output-container')]),

        html.Div(children=[
            # График улыбки волатильности
            dcc.Graph(id='plot_smile', style={'display': 'inline-block'}),
            # Спидометр TrueVega
            # https://stackoverflow.com/questions/69275527/python-dash-gauge-how-can-i-use-strings-as-values-instead-of-numbers
            daq.Gauge(id="graph-gauge", style={'display': 'inline-block'},
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
        ]),


    html.Div(children=[
        # График истории
        dcc.Graph(id='plot_history'),
        # Слайдер
        dcc.Slider(0, 28,
            id='my_slider',
            step=None,
            marks={
                1: '0.5d',
                2: '1d',
                6: '3d',
                14: '7d',
                28: '14d'
            },
            value=1
        ),
        html.Div(id='slider-output-1')
    ]),

    # Интервал обновления данных
    dcc.Interval(
        id='interval-component',
        interval=1000 * 6,
        n_intervals=0),

    # Таблица моих позиций
    html.Div(id='intermediate-value', style={'display': 'none'}),
        dash_table.DataTable(id='table', data=df_table.to_dict('records'), page_size=8, style_table={'max-width': '50px'},
        style_data_conditional = [
        {
            'if': {
                'filter_query': '{P/L} > 1',
                'column_id': 'P/L'
            },
            'backgroundColor': '#3D9970',
            'color': 'white'
        }]
    ),

])

# Callback to update the table
@app.callback(Output('intermediate-value', 'children'),
              [Input('interval-component', 'n_intervals')],
              [State('intermediate-value', 'children')])
def clean_data(value, dff):
    model_from_api = get_object_from_json_endpoint('https://option-volatility-dashboard.ru/dump_model')

    # Список опционов
    option_list = model_from_api[1]
    df = pd.DataFrame.from_dict(option_list, orient='columns')
    df = df.loc[df['_volatility'] > 0]
    df['_expiration_datetime'] = pd.to_datetime(df['_expiration_datetime'])
    df['_expiration_datetime'].dt.date
    df['expiration_date'] = df['_expiration_datetime'].dt.strftime('%d.%m.%Y')
    dff = df[(df._base_asset_ticker == value) & (df._type == 'C')]
    # print(dff)
    return dff.tail(420).to_json(date_format='iso', orient='split')

# Callback to update the dropdown (селектор базового актива)
@app.callback(
    Output('dd-output-container', 'children'),
    Input('dropdown-selection', 'value')
)
def update_output(value):
    return f'You have selected {value}'

# Callback to update the last-update-time element
@app.callback(Output('last_update_time', 'children'),
              [Input('interval-component', 'n_intervals')])
def update_time(n):
    return 'Last update time: {}'.format(datetime.datetime.now())

#Callback to update the line-graph volatility smile (обновление улыбки волатильности)
@app.callback(Output('plot_smile', 'figure', allow_duplicate=True),
              [Input('dropdown-selection', 'value'),
               Input('interval-component', 'n_intervals')],
              prevent_initial_call=True)
def update_output_smile(value, n):
    model_from_api = get_object_from_json_endpoint('https://option-volatility-dashboard.ru/dump_model')

    # Список базовых активов, вычисление и добавление в словарь центрального страйка
    base_asset_list = model_from_api[0]
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

    # Список опционов
    option_list = model_from_api[1]
    df = pd.DataFrame.from_dict(option_list, orient='columns')
    df = df.loc[df['_volatility'] > 0]
    df['_expiration_datetime'] = pd.to_datetime(df['_expiration_datetime'])
    df['_expiration_datetime'].dt.date
    df['expiration_date'] = df['_expiration_datetime'].dt.strftime('%d.%m.%Y')
    # print(df.columns)

    dff = df[(df._base_asset_ticker == value)] # оставим только опционы базового актива

    for asset in base_asset_list:
        if asset['_ticker'] == value:
            base_asset_last_price = asset['_last_price'] # получаем последнюю цену базового актива
    # print('base_asset_last_price:', base_asset_last_price)

    dff_call = dff[(dff._type == 'C')]  # оставим только коллы

    # My positions data
    # Open the file using the "with" statement
    with open(temp_obj.substitute(name_file='MyPos.csv'), 'r') as file:
        df_table = pd.read_csv(file, sep=';')
        df_table_buy = df_table[(df_table.optionbase == value) & (df_table.net_pos > 0)]
        df_table_sell = df_table[(df_table.optionbase == value) & (df_table.net_pos < 0)]
        MyPos_ticker_list = []
        for i in range(len(df_table)):
            MyPos_ticker_list.append(df_table['ticker'][i])
    # print('MyPos_ticker_list:', MyPos_ticker_list)
    # Close the file explicitly file.close()
    file.close()

    # My orders data
    # Open the file using the "with" statement
    with open(temp_obj.substitute(name_file='MyOrders.csv'), 'r') as file:
        df_orders = pd.read_csv(file, sep=';')
        df_orders = df_orders[(df_orders.optionbase == value)]
        MyOrders_ticker_list = []
        for i in range(len(df_orders)):
            MyOrders_ticker_list.append(df_orders['tiker'][i])
        # print('MyOrders_ticker_list:', MyOrders_ticker_list)
    # Close the file explicitly file.close()
    file.close()
    # print('\n df_orders.columns:\n', df_orders.columns)
    # print('\n df_orders:\n', df_orders)

    color_palette = len(set(dff['expiration_date']))

    # fig = go.Figure()
    # fig.add_trace(go.Line(x=dff_call['_strike'], y=dff['_volatility'], mode='lines+markers', name='Volatility'))
    fig = px.line(dff_call, x='_strike', y='_volatility', color='expiration_date', width=1000, height=600)

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

    # Мои ордерра
    fig.add_trace(go.Scatter(x=df_orders['strike'], y=df_orders['volatility'],
                             mode='markers+text', text=df_orders['volatility'], textposition='middle left',
                             marker=dict(size=8, symbol="cross-thin", line=dict(width=1, color="DarkSlateGrey")),
                             name='My Orders',
                             customdata=df_orders[['operation', 'optiontype', 'expdate', 'price', 'tiker']],
                             hovertemplate="<b>%{customdata}</b><br>"
                             ))

    # Last Bid Ask for MyPos
    favorites_ticker_list = MyPos_ticker_list + MyOrders_ticker_list # слияние списков
    favorites_ticker_list = list(set(favorites_ticker_list)) # удаление дубликатов
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

    # BID
    fig.add_trace(go.Scatter(x=dff_MyPosOrders['_strike'], y=dff_MyPosOrders['_bid_iv'],
                             mode='markers', text=dff_MyPosOrders['_bid_iv'], textposition='top left',
                             marker=dict(size=8, symbol="triangle-up", color='green'),
                             name='Bid',
                             customdata=dff_MyPosOrders[
                                 ['_type', '_bid', '_bid_iv', 'expiration_date', '_ticker']],
                             hovertemplate="<b>%{customdata}</b><br>"
                             ))
    # ASK
    fig.add_trace(go.Scatter(x=dff_MyPosOrders['_strike'], y=dff_MyPosOrders['_ask_iv'],
                             mode='markers', text=dff_MyPosOrders['_ask_iv'], textposition='top left',
                             marker=dict(size=8, symbol="triangle-down", color='red'),
                             name='Ask',
                             customdata=dff_MyPosOrders[
                                 ['_type', '_ask', '_ask_iv', 'expiration_date', '_ticker']],
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

    # Цена базового актива (вертикальная линия)
    fig.add_vline(x=base_asset_last_price, line_dash='dash', line_color='firebrick')

    fig.update_layout(
        title_text="Volatility smile of the option series", uirevision="Don't change"
    )
    fig.update_layout(
        margin=dict(l=0, r=0, t=30, b=0),
    )
    return fig

#Callback to update the line-graph history data (обновление данных графика истории)
@app.callback(Output('plot_history', 'figure', allow_duplicate=True),
               [Input('dropdown-selection', 'value'),
                Input('my_slider', 'value'),
                Input('interval-component', 'n_intervals')],
              prevent_initial_call=True)
def update_output_history(dropdown_value, slider_value, n):
    print('RUN History')


    # print(AlorApiTest._df_candles)
    test = self._df_candles
    print(test)

    limit = 440 * slider_value
    drop_base_ticker = dropdown_value

    for base_asset_ticker in base_asset_ticker_list:
        if drop_base_ticker == base_asset_ticker:
            substitution_text = base_asset_ticker_list.get(base_asset_ticker)
            # Volatility history data
            with open(temp_obj.substitute(name_file=f'_TEST_CenterStrikeVola_{substitution_text}.csv'), 'r') as file:
                df_volatility = pd.read_csv(file, sep=';')
                df_volatility = df_volatility.tail(limit)
            # Close the file
            file.close()

    # Преобразуем DateTime в формат datetime
    df_volatility['DateTime'] = pd.to_datetime(df_volatility['DateTime'], format='%d.%m.%Y %H:%M:%S', dayfirst=True)
    # Удаляем столбцы содержащие только нулевые значения
    df_volatility = df_volatility.loc[:, (df_volatility != 0).any(axis=0)]
    # Преобразуйте 0 в NaN с помощью pandas DataFrame.replace()
    df_volatility.replace(0, np.nan, inplace=True)
    # # Устанавливаем индекс по столбцу DateTime
    df_volatility.index = pd.DatetimeIndex(df_volatility['DateTime'])
    del df_volatility['DateTime']

    # BaseAssetPrice history data
    with open(temp_obj.substitute(name_file='BaseAssetPriceHistory.csv'), 'r') as file:
        df_BaseAssetPrice = pd.read_csv(file, sep=';')
        df_BaseAssetPrice = df_BaseAssetPrice[(df_BaseAssetPrice.ticker == dropdown_value)]
        df_BaseAssetPrice = df_BaseAssetPrice.tail(limit)
    # Close the file
    file.close()


    fig = go.Figure()
    # Create figure with secondary y-axis
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # График истории волатильности
    # Перебираем все столбцы
    for i in df_volatility.columns:
        # fig.add_trace(go.Line(x=df_volatility.index, y=df_volatility[i], name=i))
        fig.add_trace(go.Scatter(x=df_volatility.index, y=df_volatility[i], mode='lines+text',
                                 name=i), secondary_y=True)

    # График истории цены базового актива
    fig.add_trace(go.Scatter(x=df_BaseAssetPrice['DateTime'], y=df_BaseAssetPrice['last_price'], mode='lines+text',
                             name=dropdown_value, line=dict(color='gray', width=1, dash='dashdot')),
                  secondary_y=False)

    # Убираем неторговое время
    fig.update_xaxes(
        rangebreaks=[
            dict(bounds=["sat", "mon"]),  # hide weekends, eg. hide sat to before mon
            dict(bounds=[24, 9], pattern="hour"),  # hide hours outside of 9am-24pm
        ]
    )

    # Добавляем к оси Х 10 минут
    fig.update_xaxes(range=[df_volatility.index.min(), df_volatility.index.max() + timedelta(minutes=10)])

    # # Добавляем аннотацию
    # fig.add_annotation(x=df_volatility.index[-1], y=df_volatility.columns[-1],
    #                    text="Text annotation with arrow",
    #                    showarrow=True,
    #                    arrowhead=1)

    fig.update_layout(xaxis_title=None)

    fig.update_layout(
        title_text=f'The history of the volatility of the central strike of the option series {dropdown_value}', uirevision="Don't change"
    )
    fig.update_layout(
        margin=dict(l=0, r=0, t=30, b=0),
    )

    return fig

#Callback to update the table
@app.callback(
    Output('table', 'data', allow_duplicate=True),
    [Input('interval-component', 'n_intervals'),
    Input('dropdown-selection', 'value')],
    prevent_initial_call=True
)
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

_dash_app = DashApp()

def get_dash_app():
    # return app.run_server(debug=True)  # Run the Dash app
    return _dash_app



# if __name__ == '__main__':
#
#     app.run_server(debug=True) # Run the Dash app

