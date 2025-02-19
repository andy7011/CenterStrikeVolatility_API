import threading
import dash
from dash import dcc, Input, Output, callback, dash_table
from dash import html
from matplotlib.pyplot import figure
from plotly.express import data
import datetime
import requests
import plotly.express as px
import pandas as pd
from central_strike import _calculate_central_strike
from supported_base_asset import MAP


# Create the app
# Initialize the app - incorporate css
external_stylesheets = ['https://codepen.io/chriddyp/pen/bWLwgP.css']
app = dash.Dash(external_stylesheets=external_stylesheets)
# app = dash.Dash(__name__)

def get_object_from_json_endpoint(url, method='GET', params={}):
    response = requests.request(method, url, params=params)

    response_data = None
    if response.status_code == 200:
        response_data = response.json()
    else:
        raise Exception(f"Error: {response.status_code}")
    return response_data

def my_function():
    print(datetime.datetime.now())

    # My positions data
    df_pos = pd.read_csv('C:\\Users\\ashadrin\\YandexDisk\\_ИИС\\Position\\MyPos.csv', sep=';')

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


    app.layout = html.Div([
        html.H6(children=datetime.datetime.now()),
        dcc.Dropdown(df._base_asset_ticker.unique(), value=df._base_asset_ticker.unique()[0], id='dropdown-selection'),
        dcc.Interval('table-update', interval=10000, n_intervals=0),
        dash_table.DataTable(id = 'table', data=df_pos.to_dict('records'), page_size=8),
        dcc.Graph(id='graph-content')  # Display the Plotly figure
    ])

    @callback(
        Output('table', 'data'),
        Input('table-update', 'n_intervals')
    )
    def updateTable(n):
        df_pos = pd.read_csv('C:\\Users\\ashadrin\\YandexDisk\\_ИИС\\Position\\MyPos.csv', sep=';')
        return df_pos.to_dict('records')

    def update_output(value):
        dff = df[(df._base_asset_ticker == value) & (df._type == 'C')]
        fig = px.line(dff, x='_strike', y='_volatility', color='expiration_date')
        # fig.update_xaxes(range=[dff._strike.min(), dff._strike.max()])
        return fig

def run_function():
    thread = threading.Timer(10.0, run_function)  # 60 seconds = 1 minute
    thread.start()
    my_function()


def main():
    run_function()

if __name__ == '__main__':
    main()
    app.run_server(debug=True) # Run the Dash app
