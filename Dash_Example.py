import dash
from dash import dcc, Input, Output, callback, dash_table, State
from dash import html
import datetime
from datetime import timedelta
import requests
import plotly.express as px
from plotly.subplots import make_subplots
import plotly.graph_objects as go
import pandas as pd

from central_strike import _calculate_central_strike
from supported_base_asset import MAP
import numpy as np



# Create the app
# Initialize the app - incorporate css
# external_stylesheets = ['https://codepen.io/chriddyp/pen/bWLwgP.css']
# app = dash.Dash(external_stylesheets=external_stylesheets)
app = dash.Dash(__name__)

# # Initialize the app
# app = dash.Dash(__name__)
# app.config.suppress_callback_exceptions = True

# My positions data
df_table = pd.read_csv('C:\\Users\\Андрей\\YandexDisk\\_ИИС\\Position\\MyPos.csv', sep=';')
print(df_table.columns)
print(df_table)


# Volatility history data RTS
# Open the file using the "with" statement
with open('C:\\Users\\Андрей\\YandexDisk\\_ИИС\\Position\\_TEST_CenterStrikeVola_RTS.csv', 'r') as file:
    df_RTS_volatility = pd.read_csv(file, sep=';')
    df_RTS_volatility = df_RTS_volatility.tail(900)
    df_RTS_volatility.set_index('DateTime', inplace=True)
# Close the file explicitly file.close()
file.close()
# print(df_RTS_volatility)


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
            dcc.Graph(id='plot_smile')]),

        html.Div(children=[
            dcc.Graph(id='plot_history')]),

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

#Callback to update the line-graph volatility smile
@app.callback(Output('plot_smile', 'figure', allow_duplicate=True),
              [Input('dropdown-selection', 'value'),
               Input('interval-component', 'n_intervals')],
              prevent_initial_call=True)
def update_output_smile(value, n):
    model_from_api = get_object_from_json_endpoint('https://option-volatility-dashboard.ru/dump_model')

    # Список опционов
    option_list = model_from_api[1]
    df = pd.DataFrame.from_dict(option_list, orient='columns')
    df = df.loc[df['_volatility'] > 0]
    df['_expiration_datetime'] = pd.to_datetime(df['_expiration_datetime'])
    df['_expiration_datetime'].dt.date
    df['expiration_date'] = df['_expiration_datetime'].dt.strftime('%d.%m.%Y')

    dff = df[(df._base_asset_ticker == value) & (df._type == 'C')]

    for asset in base_asset_list:
        if asset['_ticker'] == value:
            base_asset_last_price = asset['_last_price']
    # print('base_asset_last_price:', base_asset_last_price)

    # fig = go.Figure()
    fig = px.line(dff, x='_strike', y='_volatility', color='expiration_date')

    # My positions data
    df_table = pd.read_csv('C:\\Users\\Андрей\\YandexDisk\\_ИИС\\Position\\MyPos.csv', sep=';')
    df_table = df_table[(df_table.optionbase == value)]

    fig.add_trace(go.Scatter(x=df_table['strike'], y=df_table['OpenIV'],
                             mode='markers+text', text=df_table['OpenIV'], textposition='top left',
                             # marker=dict(size=10, color='darkmagenta'),
                             name='MyPos',
                             ))

    # fig.update_traces(
    #     marker=dict(
    #         size=8,
    #         symbol="diamond-open",
    #         line=dict(
    #             width=2,
    #             #             color="DarkSlateGrey" Line colors don't apply to open markers
    #         )
    #     ),
    #     selector=dict(mode="markers"),
    # )


    # Цена базового актива
    fig.add_trace(go.Scatter(x=[base_asset_last_price, base_asset_last_price], y=[dff._volatility.min(), dff._volatility.max()],
                             mode='lines', line=go.scatter.Line(color='gray'),
                             showlegend=False
                             ))
    # strike = dff._strike.unique()
    # last_price_iv = dff._last_price_iv
    # fig.add_trace(go.Scatter(y='_last_price_iv'), row=2, col=1)
    # fig.update_xaxes(range=[dff._strike.min(), dff._strike.max()])
    # fig.update_layout(title_text="Volatility smile of the option series", uirevision="Don't change")
    fig.update_layout(
        title_text="Volatility smile of the option series", uirevision="Don't change"
    )
    return fig

#Callback to update the line-graph history data
@app.callback(Output('plot_history', 'figure', allow_duplicate=True),
               Input('interval-component', 'n_intervals'),
              prevent_initial_call=True)
def update_output_histiry(value):

    # Volatility history data RTS
    # Open the file using the "with" statement
    with open('C:\\Users\\Андрей\\YandexDisk\\_ИИС\\Position\\_TEST_CenterStrikeVola_RTS.csv', 'r') as file:
        df_RTS_volatility = pd.read_csv(file, sep=';')
        df_RTS_volatility = df_RTS_volatility.tail(900)
    # Close the file explicitly file.close()
    file.close()

    # Преобразуем DateTime в формат datetime
    df_RTS_volatility['DateTime'] = pd.to_datetime(df_RTS_volatility['DateTime'], format='%d.%m.%Y %H:%M:%S', dayfirst=True)

    # Удаляем столбцы содержащие только нулевые значения
    df_RTS_volatility = df_RTS_volatility.loc[:, (df_RTS_volatility != 0).any(axis=0)]

    # Преобразуйте 0 в NaN с помощью pandas DataFrame.replace()
    df_RTS_volatility.replace(0, np.nan, inplace=True)

    # # Устанавливаем индекс по столбцу DateTime
    df_RTS_volatility.index = pd.DatetimeIndex(df_RTS_volatility['DateTime'])
    del df_RTS_volatility['DateTime']
    # print(df_RTS_volatility.index)
    # print('type columns df_RTS_volatility:', df_RTS_volatility.dtypes)

    # column_name_series = []
    # for col in df_RTS_volatility.columns:
    #     column_name_series.append(col)
    # # print('column_name_series:', column_name_series)

    fig = px.line(df_RTS_volatility, x=df_RTS_volatility.index, y=df_RTS_volatility.columns)
    # Добавляем к оси Х 60 минут
    fig.update_xaxes(range=[df_RTS_volatility.index.min(), df_RTS_volatility.index.max() + timedelta(minutes=60)])


    # fig = go.Figure(data=[go.Scatter(x=df_RTS_volatility.index, y=df_RTS_volatility[i])])

    # Убираем неторговое время
    fig.update_xaxes(
        rangebreaks=[
            # dict(bounds=["sat", "mon"]),  # hide weekends, eg. hide sat to before mon
            # dict(bounds=[24, 9], pattern="hour"),  # hide hours outside of 9am-24pm
        ]
    )

    fig.update_layout(
        title_text="Volatility history of the option series", uirevision="Don't change"
    )

    # fig.add_trace(
    #     go.Scatter(x=df_RTS_volatility.index, y=df_RTS_volatility['W 27.02.2025'],
    #                mode='lines',
    #                ))

    return fig

#Callback to update the table
@app.callback(
    Output('table', 'data', allow_duplicate=True),
    [Input('interval-component', 'n_intervals'),
    Input('dropdown-selection', 'value')],
    prevent_initial_call=True
)
def updateTable(n, value):
    df_pos = pd.read_csv('C:\\Users\\Андрей\\YandexDisk\\_ИИС\\Position\\MyPos.csv', sep=';')
    # Фильтрация строк по базовому активу
    df_pos = df_pos[df_pos['optionbase'] == value]

    # # Замена RealIV на _last_price_iv опционов моих позиций
    # for i, df in df_pos.iterrows():
    #     df_pos['RealIV'] = df['_last_price_iv']

    return df_pos.to_dict('records')

if __name__ == '__main__':

    app.run_server(debug=True) # Run the Dash app
