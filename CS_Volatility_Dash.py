from dash import Dash, html, dcc, callback, Output, Input
import plotly.express as px
import pandas as pd

# Функция для замены нулей на NaN
def zero_to_nan(values):
    """Replace every 0 with 'nan' and return a copy."""
    return [float('nan') if x==0 else x for x in values]

# df = pd.read_csv('https://raw.githubusercontent.com/plotly/datasets/master/gapminder_unfiltered.csv')
# print(df)

# Указываем путь к файлу CSV
fn = r'C:\Users\ashadrin\YandexDisk\_ИИС\Position\_TEST_CenterStrikeVola_RTS.csv'
# Начальные параметры графиков: 840 - кол.торговых минуток за сутки
limit_day = 100
# Кол.торговых минуток за месяц 17640 = 840 мин x 21 раб. день
limit_month = 17640

# Читаем CSV/TXT файл (разделённый точкой с запятой) в DataFrame
df = pd.read_csv(fn, sep=';')
df = df.tail(limit_day)

# Заменяем нули на NaN
for i in range(1, len(df.columns)):
    df[df.columns[i]] = zero_to_nan(df[df.columns[i]])
# print(df)

# Преобразуем первую колонку в объект datetime
df['DateTime'] = pd.to_datetime(df['DateTime'], dayfirst=True)

app = Dash()

app.layout = html.Div([
    html.H4(children='Заголовок', style={'textAlign':'center'}),
    dcc.Graph(id='graph-content'),
    dcc.Checklist(
        id='checklist',
        options=df.columns[1:11],
        value=df.columns[1:6].values,
        inline=True),
])

# app.layout = html.Div([
#     html.H4(children='Заголовок', style={'textAlign':'center'}),
#     dcc.Graph(id='graph-content'),
# ])

@callback(
    Output('graph-content', 'figure'),
    Input('checklist', 'value'))

def update_graph(value):
    # dff = df[df['W 30.01.2025']==value]

    fig = px.line(df, x='DateTime', y=[df.columns[1], df.columns[2], df.columns[3],
                                       df.columns[4], df.columns[5], df.columns[6],
                                       df.columns[7], df.columns[8], df.columns[9], df.columns[10]])

    fig.update_xaxes(
        rangebreaks=[
            dict(bounds=[0, 10], pattern="hour"),  # hide hours outside of 10am-0pm
        ]
    )

    # fig.update_xaxes(
    #     rangeslider_visible=True,
    #     tickformatstops=[
    #         dict(dtickrange=[None, 1000], value="%H:%M:%S.%L ms"),
    #         dict(dtickrange=[1000, 60000], value="%H:%M:%S s"),
    #         dict(dtickrange=[60000, 3600000], value="%H:%M m"),
    #         dict(dtickrange=[3600000, 86400000], value="%H:%M h"),
    #         dict(dtickrange=[86400000, 604800000], value="%e. %b d"),
    #         dict(dtickrange=[604800000, "M1"], value="%e. %b w"),
    #         dict(dtickrange=["M1", "M12"], value="%b '%y M"),
    #         dict(dtickrange=["M12", None], value="%Y Y")
    #     ]
    # )

    return fig

if __name__ == '__main__':
    app.run(debug=True)
