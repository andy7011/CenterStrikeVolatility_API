import dash
from dash import html
from dash import dcc
from dash import Input, Output, State
import pandas as pd
from datetime import datetime
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import json
from central_strike import _calculate_central_strike
from supported_base_asset import MAP

def get_object_from_json_endpoint(url, method='GET', params={}):
    response = requests.request(method, url, params=params)

    response_data = None
    if response.status_code == 200:
        response_data = response.json()
    else:
        raise Exception(f"Error: {response.status_code}")
    return response_data

# My positions data
df_table = pd.read_csv('C:\\Users\\ashadrin\\YandexDisk\\_ИИС\\Position\\MyPos.csv', sep=';')

# Options data
model_from_api = get_object_from_json_endpoint('https://option-volatility-dashboard.ru/dump_model')

# Список базовых активов, вычисление и добавление в словарь центрального страйка
base_asset_list = model_from_api[0]
for asset in base_asset_list:
    ticker = asset.get('_ticker')
    last_price = asset.get('_last_price')
    strike_step = MAP[ticker]['strike_step']
    central_strike = _calculate_central_strike(last_price, strike_step) # вычисление центрального страйка
    asset.update({
        'central_strike': central_strike
    })
# print('base_asset_list:', base_asset_list) # вывод списка базовых активов

# Список опционов
option_list = model_from_api[1]
current_datetime = datetime.datetime.now()
for option in option_list:
    option['datetime'] = current_datetime
df = pd.DataFrame.from_dict(option_list, orient='columns')
# df = df.loc[df['_volatility'] != float("NaN")]
df = df.loc[df['_volatility'] > 0]
df['_expiration_datetime'] = pd.to_datetime(df['_expiration_datetime'])
df['_expiration_datetime'].dt.date
df['expiration_date'] = df['_expiration_datetime'].dt.strftime('%d.%m.%Y')
df.set_index('datetime', inplace=True)
df.index = df.index.strftime('%d.%m.%Y %H:%M:%S') # Reformat the date index using strftime()

# Create the dash app, and define its layout
app = dash.Dash()
server = app.server
app.layout = html.Div(children=[
    html.H1(
        children='DashBoard Volatility',
        style={
            'textAlign': 'center'
        }
    ),

    html.H3(
        id='last_update_time',
        style={
            'textAlign': 'center'
        }
    ),

    html.H1(
        children="   ",
        style={
            'textAlign': 'center'
        }
    ),
    html.Div(children=[
        html.Div(children=[
            html.H3(id='rate_text', children='Latest Rate', style={'textAlign': 'center'}),
            html.H1(id='rate', style={'textAlign': 'center', 'bottomMargin': 50})],
            style={"border": "2px black solid"}),
        html.Div(children=[
            dcc.Graph(id='plot')],
            style={"border": "2px black solid"})],
        style={'width': '100%', 'height': '90%', 'float': 'left', 'display': 'inline-block',
               "border": "2px black solid"}),
    dcc.Interval(
        id='interval-component',
        interval=5000,  # 5000 milliseconds = 5 seconds
        n_intervals=0),
    html.Div(id='intermediate-value', children=df_line.to_json(date_format='iso', orient='split'),
             style={'display': 'none'})
])

