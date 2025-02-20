import threading
import dash
from dash import dcc, Input, Output, callback, dash_table, State
from dash import html
import datetime
import requests
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
from central_strike import _calculate_central_strike
from supported_base_asset import MAP


# Create the app
# Initialize the app - incorporate css
external_stylesheets = ['https://codepen.io/chriddyp/pen/bWLwgP.css']
app = dash.Dash(external_stylesheets=external_stylesheets)
# app = dash.Dash(__name__)

# My positions data
df_table = pd.read_csv('C:\\Users\\Андрей\\YandexDisk\\_ИИС\\Position\\MyPos.csv', sep=';')

def get_object_from_json_endpoint(url, method='GET', params={}):
    response = requests.request(method, url, params=params)

    response_data = None
    if response.status_code == 200:
        response_data = response.json()
    else:
        raise Exception(f"Error: {response.status_code}")
    return response_data

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
df = pd.DataFrame.from_dict(option_list, orient='columns')
df = df.loc[df['_volatility'] > 0]
df['_expiration_datetime'] = pd.to_datetime(df['_expiration_datetime'])
df['_expiration_datetime'].dt.date
df['expiration_date'] = df['_expiration_datetime'].dt.strftime('%d.%m.%Y')
print(df.columns)

app.layout = html.Div(children=[

    html.H6(id='last_update_time', style={'textAlign': 'left'}),

    html.Div(children=[
        dcc.Dropdown(df._base_asset_ticker.unique(), value=df._base_asset_ticker.unique()[0], id='dropdown-selection'),
        html.Div(id='dd-output-container')]),

        html.Div(children=[
            dcc.Graph(id='plot')]),

    dcc.Interval(
        id='interval-component',
        interval=1000 * 10,
        n_intervals=0),

    html.Div(id='intermediate-value', style={'display': 'none'}),
        dash_table.DataTable(id='table', data=df_table.to_dict('records'), page_size=8)

])



# Callback to update the invisible intermediate-value element
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
    return dff.tail(100).to_json(date_format='iso', orient='split')

# Callback to update the dropdown
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

#Callback to update the line-graph
@app.callback(Output('plot', 'figure', allow_duplicate=True),
              [Input('dropdown-selection', 'value'),
               Input('interval-component', 'n_intervals')],
              prevent_initial_call=True)
def update_output(value, n):
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

    # fig = go.Figure()
    fig = px.line(dff, x='_strike', y='_volatility', color='expiration_date')
    # strike = dff._strike.unique()
    # last_price_iv = dff._last_price_iv
    # fig.add_trace(go.Scatter(x=strike, y=last_price_iv, color='expiration_date'))
    # fig.update_xaxes(range=[dff._strike.min(), dff._strike.max()])
    # fig.update_layout(title_text="Volatility smile of the option series", uirevision="Don't change")
    fig.update_layout(
        title_text="Volatility smile of the option series", uirevision="Don't change"
    )
    return fig

#Callback to update the table
@app.callback(
    Output('table', 'data'),
    Input('interval-component', 'n_intervals')
)
def updateTable(n):
    df_pos = pd.read_csv('C:\\Users\\Андрей\\YandexDisk\\_ИИС\\Position\\MyPos.csv', sep=';')
    return df_pos.to_dict('records')

if __name__ == '__main__':

    app.run_server(debug=True) # Run the Dash app
