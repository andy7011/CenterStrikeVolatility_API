from dash import Dash, html, dcc, callback, Output, Input
import plotly.express as px
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta, datetime, date
import json

from infrastructure.alor_api import AlorApi
from moex_api import get_futures_series
from moex_api import get_option_expirations
from moex_api import get_option_board
from moex_api import get_option_list_by_series
from moex_api import get_option_series
from moex_api import _convert_moex_data_structure_to_list_of_dicts

from AlorPy import AlorPy  # Работа с Alor OpenAPI V2

ap_provider = AlorPy()  # Подключаемся ко всем торговым счетам
# Проверяем работу запрос/ответ
seconds_from = ap_provider.get_time()  # Время в Alor OpenAPI V2 передается в секундах, прошедших с 01.01.1970 00:00 UTC
print(f'Дата и время на сервере: {ap_provider.utc_timestamp_to_msk_datetime(seconds_from):%d.%m.%Y %H:%M:%S}')  # В AlorPy это время можно перевести в МСК для удобства восприятия)




_REFRESH_TOKEN_URL = 'https://oauth.alor.ru/refresh'
_WEBSOCKET_URL = 'wss://api.alor.ru/ws'
# ap_provider = 'wss://api.alor.ru/ws'
exchange = 'MOEX'
URL_API = f'https://api.alor.ru'
# Указываем путь к файлу CSV
fn = r'C:\Users\Андрей\YandexDisk\_ИИС\Position\_TEST_CenterStrikeVola_RTS.csv'
# Начальные параметры графиков: 840 - кол.торговых минуток за сутки
limit_day = 3900
# Кол.торговых минуток за месяц 17640 = 840 мин x 21 раб. день
limit_month = 17640
asset_code = 'RTS'
strike_step = 2500
line_colors = ["red", "orange", "green", "aqua", "blue", "light coral", "moccasin", "lime", "pale turquoise", "cornflower blue"]

_API_METHOD_QUOTES_SUBSCRIBE = "QuotesSubscribe"
_API_METHOD_INSTRUMENTS_GET_AND_SUBSCRIBE = "InstrumentsGetAndSubscribeV2"

_alorApi = AlorApi('52ede572-e81b-473e-9d89-e9af46be296d')

# Две ближайшие (текущая и следующая) фьючерсные серии по базовому активу asset_code
data = get_futures_series(asset_code)
info_fut_1 = data[len(data) - 1]
info_fut_2 = data[len(data) - 2]
fut_1 = info_fut_1['secid'] # Текущий фьючерс
fut_2 = info_fut_2['secid'] # Следующий фьючерс

print(ap_provider.dataname_to_board_symbol(fut_1))
print(ap_provider.get_symbol_info(exchange, fut_1, reload=False))


tf = 60  # 60 = 1 минута, 300 = 5 минут, 3600 = 1 час, 'D' = день, 'W' = неделя, 'M' = месяц, 'Y' = год
days = 3  # Кол-во последних календарных дней, за которые берем историю
ap_provider.on_entering()
ap_provider.on_enter()
ap_provider.on_connect()
ap_provider.on_ready()
ap_provider.on_new_bar()
# ap_provider.websocket_handler()
# # Подписка на информацию о котировках для выбранных инструментов и бирж
# guid = ap_provider.quotes_subscribe(exchange, fut_1, frequency=0, format='Simple') # Уникальный идентификатор подписки
# print(f'Подписка на сервере guid: {guid}')
# subscription = ap_provider.subscriptions[guid]  # Получаем данные подписки
# print(f'Подписка на сервере subscription: {subscription}')
seconds_from = ap_provider.msk_datetime_to_utc_timestamp(datetime.now() - timedelta(days=days))  # За последние дни. В секундах, прошедших с 01.01.1970 00:00 UTC
guid = ap_provider.bars_get_and_subscribe(exchange, fut_1, tf, seconds_from, frequency=1_000_000_000)  # Подписываемся на бары, получаем guid подписки
subscription = ap_provider.subscriptions[guid]  # Получаем данные подписки
print(f'Подписка на сервере: {guid} {subscription}')
print(f'На бирже {subscription["exchange"]} тикер {subscription["code"]} подписан на новые бары через WebSocket на временнОм интервале {subscription["tf"]}. Код подписки {guid}')
response_json = await ap_provider.ws_socket.recv()  # Ожидаем следующую строку в виде JSON
response = loads(response_json)  # Переводим JSON в словарь
opcode = subscription['opcode']  # Разбираем по типу подписки
print(f'websocket_handler: Пришли данные подписки {opcode} - {guid} - {response}')
response = ap_provider.websocket_handler
print(response)

# ap_provider.close_web_socket()  # Перед выходом закрываем соединение с WebSocket


# quotes = ap_provider.get_quotes(f'{exchange}:{fut_1}')[0]  # Последнюю котировку получаем через запрос
# last_price = quotes['last_price'] if quotes else None  # Последняя цена сделки
# print(f'- Последняя цена сделки: {last_price}')
# last_price_timestamp = quotes['last_price_timestamp'] if quotes else None  # Последняя цена сделки
# print(f'- Время Последней сделки: {last_price_timestamp}')


# Получить список дат окончания действия опционов базовых активов fut_1 fut_2
option_expirations_fut_1 = get_option_expirations(fut_1)
dict_option_expirations_fut_1 = []
for i in option_expirations_fut_1:
    expiration_date = i['expiration_date']
    dict_option_expirations_fut_1.append(expiration_date)
# print('\n Даты окончания действия опционов базового актива', fut_1, '\n', dict_option_expirations_fut_1)
option_expirations_fut_2 = get_option_expirations(fut_2)
dict_option_expirations_fut_2 = []
for i in option_expirations_fut_2:
    expiration_date = i['expiration_date']
    dict_option_expirations_fut_2.append(expiration_date)
# print('\n Даты окончания действия опционов базового актива', fut_2, '\n', dict_option_expirations_fut_2)
option_expirations = get_option_expirations(fut_1) + get_option_expirations(fut_2)
# print('\n Даты экспирации выбранных серий option_expirations:','\n',option_expirations)

options_series_names = []
for i in option_expirations:
    options_series_name = i['expiration_date']
    options_series_date = datetime.strptime(options_series_name, '%Y-%m-%d')
    options_series_type = i['series_type']
    options_series_name = " ".join(options_series_type) + ' ' + options_series_date.strftime('%d.%m.%Y')
    options_series_names.append(options_series_name)
print("\n Имена колонок для записи в csv файл options_series_names:",'\n',options_series_names)

# # Опционные серии по базовому активу fut_1 (текущая серия)
# fut_series = [fut_1]
# data = get_option_series(asset_code)
# option_series_by_name_series_1 = []
# for item in data:
#     if item['underlying_asset'] in fut_series:
#         option_series_by_name_series_1.append(item['name'])
# # print("\n Опционные серии по базовому активу", fut_series, '\n', option_series_by_name_series_1)
#
# # Опционные серии по базовому активу fut_2 (следующая серия)
# fut_series = [fut_2]
# data = get_option_series(asset_code)
# option_series_by_name_series_2 = []
# for item in data:
#     if item['underlying_asset'] in fut_series:
#         option_series_by_name_series_2.append(item['name'])
# # print("\n Опционные серии по базовому активу", fut_series, '\n', option_series_by_name_series_2)

# Функция для замены нулей на NaN
def zero_to_nan(values):
    """Replace every 0 with 'nan' and return a copy."""
    return [float('nan') if x==0 else x for x in values]

# Читаем CSV/TXT файл (разделённый точкой с запятой) в DataFrame
df = pd.read_csv(fn, sep=';')
df = df.tail(limit_month)

# Формируем цвета действующих опционных серий из списка line_colors
line_colors_series = []
for i in range(1, len(df.columns)):
    if df.columns[i] in options_series_names:
        line_colors_series.append(line_colors[i-1])
print(line_colors_series)

# Заменяем нули на NaN
for i in range(1, len(df.columns)):
    df[df.columns[i]] = zero_to_nan(df[df.columns[i]])

# Преобразуем первую колонку в объект datetime
df['DateTime'] = pd.to_datetime(df['DateTime'], dayfirst=True)

df.index = pd.DatetimeIndex(df['DateTime'])


def get_marks(f):
    dates = {}
    for z in f.index:
        dates[f.index.get_loc(z)] = {}
        dates[f.index.get_loc(z)] = str(z.day) + "." + str(z.month) + "." + str(z.year)
        return dates








app = Dash()

fig = go.Figure()

title = html.H1("RTS. Central Strike Options Volatility.")
graph_to_display = dcc.Graph(id="graph-content", figure=fig, style={'width': '100%', 'height': '70vh'})

app.layout = html.Div([
    title,
    graph_to_display,
    dcc.Interval(
        id='interval-component',
        interval=10*1000,  # Update data every 10 second
        n_intervals=0),
    dcc.RangeSlider(
        updatemode='mouseup',
        min=0, #the first date
        max=len(df.index) - 1, #the last date
        step=1,
        value=[(len(df.index) - 1) - 900,len(df.index) - 1], #default: the first
        marks = get_marks(df),
        id='rangeslider'
    )
])

# Define the callback to update the graph with new data
@app.callback(
    Output('graph-content', 'figure'),
    # [Input('interval-component', 'n_intervals'),
    Input('rangeslider', 'value'))


def update_graph(value):
    # print('RUN update_graph')
    # Читаем CSV/TXT файл (разделённый точкой с запятой) в DataFrame
    df = pd.read_csv(fn, sep=';')
    df = df.tail(limit_month)

    # Заменяем нули на NaN
    for i in range(1, len(df.columns)):
        df[df.columns[i]] = zero_to_nan(df[df.columns[i]])

    # Преобразуем первую колонку в объект datetime
    df['DateTime'] = pd.to_datetime(df['DateTime'], dayfirst=True)
    df.index = pd.DatetimeIndex(df['DateTime'])
    print(value)
    print(df.index[-1])

    # Создаем фигуру и текстовые метки
    fig = go.Figure()
    for i in range(1, len(df.columns)):
        if df.columns[i] in options_series_names:
            fig.add_trace(
                go.Scatter(
                    x=df.index,
                    y=df[df.columns[i]],
                    name=df.columns[i],
                    line=dict(color=line_colors[i-1]),
                ))
        # endpoints markers
        if df.columns[i] in options_series_names:
            fig.add_trace(
                go.Scatter(
                    x=[df['DateTime'].iloc[-1]],
                    y=[df[df.columns[i]].iloc[-1]],
                    mode="markers",
                    marker=dict(color=line_colors[i-1], size=10),
                    text = df[df.columns[i]].iloc[-1],
                    showlegend=False,
                ))
        # labeling the right_side of the plot
        if df.columns[i] in options_series_names:
            fig.add_trace(
                go.Scatter(
                    x=[df['DateTime'].iloc[-1]],
                    y=[df[df.columns[i]].iloc[-1]],
                    mode="text",
                    text=[df[df.columns[i]].iloc[-1]],
                    textposition="middle right",
                    # fillcolor=dict(line_colors[i-1]),
                    textfont=dict(size=16),
                    showlegend=False,
                ))

    fig.update_xaxes(
        range=df.index[value],
        rangebreaks=[
            {'pattern': 'day of week', 'bounds': [6, 1]},
            {'pattern': 'hour', 'bounds': [24, 9]}
        ]
    )

    # fig.update_layout(margin=dict(l=0, r=0, t=0, b=0))
    fig.update_yaxes(automargin=True)

    # @app.callback(
    #     Output('graph-content', 'figure'),
    #     Input('slider', 'value')
    # )


    return fig

if __name__ == '__main__':
    app.run(debug=True)
