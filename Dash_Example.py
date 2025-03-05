import dash
from dash import dcc, Input, Output, callback, dash_table, State
from dash import html
import dash_daq as daq
import datetime
from datetime import timedelta
import requests
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
from central_strike import _calculate_central_strike
from supported_base_asset import MAP
from string import Template
import numpy as np

temp_str = 'C:\\Users\\ashadrin\\YandexDisk\\_ИИС\\Position\\$name_file'
temp_obj = Template(temp_str)

# Create the app
# Initialize the app - incorporate css
# external_stylesheets = ['https://codepen.io/chriddyp/pen/bWLwgP.css']
# app = dash.Dash(external_stylesheets=external_stylesheets)
app = dash.Dash(__name__)

# # Initialize the app
# app = dash.Dash(__name__)
# app.config.suppress_callback_exceptions = True

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


# # Volatility history data
# # Open the file using the "with" statement
# with open(temp_obj.substitute(name_file='_TEST_CenterStrikeVola_RTS.csv'), 'r') as file:
#     df_volatility = pd.read_csv(file, sep=';')
#     df_volatility = df_volatility.tail(300)
#     df_volatility.set_index('DateTime', inplace=True)
# # Close the file explicitly file.close()
# file.close()
# # print(df_volatility)


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
base_asset_ticker_list = {}
for i in range(len(base_asset_list)):
    # print(base_asset_list[i]['_ticker'])
    base_asset_ticker_list.update({base_asset_list[i]['_ticker']:base_asset_list[i]['_base_asset_code']})
# print(base_asset_ticker_list)

# Список опционов
option_list = model_from_api[1]
current_datetime = datetime.datetime.now()
df = pd.DataFrame.from_dict(option_list, orient='columns')
df = df.loc[df['_volatility'] > 0]
df['_expiration_datetime'] = pd.to_datetime(df['_expiration_datetime'])
df['_expiration_datetime'].dt.date
df['expiration_date'] = df['_expiration_datetime'].dt.strftime('%d.%m.%Y')
# print(df.columns)

app.layout = html.Div(children=[

    html.H6(id='last_update_time', style={'textAlign': 'left'}),

    html.Div(children=[
        dcc.Dropdown(df._base_asset_ticker.unique(), value=df._base_asset_ticker.unique()[0], id='dropdown-selection',  style={'width':'40%'}),
        html.Div(id='dd-output-container')]),

        html.Div(children=[
            dcc.Graph(id='plot_smile')]),


        html.Div(children=[
            dcc.Graph(id='plot_history')]),

    dcc.Interval(
        id='interval-component',
        interval=1000 * 10,
        n_intervals=0),

    # Таблица
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
    # Спидометр
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
        value=8,
        max=10,
        min=0,
    )
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
    return dff.tail(420).to_json(date_format='iso', orient='split')

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

    dff = df[(df._base_asset_ticker == value)] # оставим только опционы базового актива

    for asset in base_asset_list:
        if asset['_ticker'] == value:
            base_asset_last_price = asset['_last_price']
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
    # Close the file explicitly file.close()
    file.close()
    # print('\n df_orders.columns:\n', df_orders.columns)
    print('\n df_orders:\n', df_orders)


    color_palette = len(set(dff['expiration_date']))

    # fig = go.Figure()
    # fig.add_trace(go.Line(x=dff_call['_strike'], y=dff['_volatility'], mode='lines+markers', name='Volatility'))
    fig = px.line(dff_call, x='_strike', y='_volatility', color='expiration_date', width=1000, height=600)

    # Мои позиции BUY
    # fig = px.scatter(dff, x='_strike', y='my_pos_buy', color='expiration_date')
    # fig.add_trace(go.Scatter(x=dff['_strike'], y=dff['my_pos_buy'],
    #                          mode='markers+text', text=dff['my_pos_buy'], textposition='middle left',
    #                          marker=dict(size=10, symbol="star-triangle-up-open", color=[i for i in range(color_palette)]),
    #                          name='My Pos Buy'
    #                          ))
    fig.add_trace(go.Scatter(x=df_table_buy['strike'], y=df_table_buy['OpenIV'],
                                mode='markers+text', text=df_table_buy['OpenIV'], textposition='middle left',
                                marker=dict(size=11, symbol="star-triangle-up-open", color='darkgreen'),
                                name='My Pos Buy'
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

    # fig.update_traces(hoverinfo="all", hovertemplate=dff['expiration_date'])

    # Мои позиции SELL
    fig.add_trace(go.Scatter(x=df_table_sell['strike'], y=df_table_sell['OpenIV'],
                             mode='markers+text', text=df_table_sell['OpenIV'], textposition='middle left',
                             marker=dict(size=11, symbol="star-triangle-down-open", color='darkmagenta'),
                             name='My Pos Sell',
                             ))

    # Мои ордерра
    fig.add_trace(go.Scatter(x=df_orders['strike'], y=df_orders['volatility'],
                             mode='markers+text', text=df_orders['volatility'], textposition='middle left',
                             marker=dict(size=8, symbol="cross-thin", line=dict(width=1, color="DarkSlateGrey")),
                             name='My Orders',
                             ))


    # LastPrice
    dff_LastPrice_Call = df[(df._base_asset_ticker == value) & (df._ticker.isin(MyPos_ticker_list))]
    fig.add_trace(go.Scatter(x=dff_LastPrice_Call['_strike'], y=dff_LastPrice_Call['_last_price_iv'],
                             mode='markers', text=dff_LastPrice_Call['_last_price_iv'], textposition='top left',
                             marker=dict(size=8, color='goldenrod'),
                             name='Last',
                             ))



    # Цена базового актива (вертикальная линия)
    fig.add_vline(x=base_asset_last_price, line_dash='dash', line_color='firebrick')
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
               [Input('dropdown-selection', 'value'),
                Input('interval-component', 'n_intervals')],
              prevent_initial_call=True)
def update_output_history(value, n):
    for base_asset_ticker in base_asset_ticker_list:
        if value == base_asset_ticker:
            substitution_text = base_asset_ticker_list.get(base_asset_ticker)
            # Volatility history data
            with open(temp_obj.substitute(name_file=f'_TEST_CenterStrikeVola_{substitution_text}.csv'), 'r') as file:
                df_volatility = pd.read_csv(file, sep=';')
                df_volatility = df_volatility.tail(300)
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


    # column_name_series = []
    # for col in df_volatility.columns:
    #     column_name_series.append(col)
    # print('column_name_series:', column_name_series)

    # График истории волатильности
    fig = px.line(df_volatility, x=df_volatility.index, y=df_volatility.columns)
    # Добавляем к оси Х 30 минут
    fig.update_xaxes(range=[df_volatility.index.min(), df_volatility.index.max() + timedelta(minutes=30)])
    # # Добавляем аннотацию
    # fig.add_annotation(x=df_volatility.index[-1], y=df_volatility.columns[-1],
    #                    text="Text annotation with arrow",
    #                    showarrow=True,
    #                    arrowhead=1)

    fig.update_layout(xaxis_title=None)

    # fig = go.Figure(data=[go.Scatter(x=df_volatility.index, y=df_volatility[i])])

    # # Убираем неторговое время
    # fig.update_xaxes(
    #     rangebreaks=[
    #         dict(bounds=["sat", "mon"]),  # hide weekends, eg. hide sat to before mon
    #         dict(bounds=[24, 9], pattern="hour"),  # hide hours outside of 9am-24pm
    #     ]
    # )

    fig.update_layout(
        title_text=f'Volatility history of the option series {value}', uirevision="Don't change"
    )

    # fig.add_trace(
    #     go.Scatter(x=df_volatility.index, y=df_latility[0],
    #                mode='lines'
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


if __name__ == '__main__':

    app.run_server(debug=True) # Run the Dash app
