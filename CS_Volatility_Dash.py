from dash import Dash, html, dcc, callback, Output, Input
import plotly.express as px
import pandas as pd

# Функция для замены нулей на NaN
def zero_to_nan(values):
    """Replace every 0 with 'nan' and return a copy."""
    return [float('nan') if x==0 else x for x in values]

# Указываем путь к файлу CSV
fn = r'C:\Users\Андрей\YandexDisk\_ИИС\Position\_TEST_CenterStrikeVola_RTS.csv'
# Начальные параметры графиков: 840 - кол.торговых минуток за сутки
limit_day = 2000
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

fig = px.line(df, x='DateTime', y=[df.columns[1], df.columns[2], df.columns[3],
                                   df.columns[4], df.columns[5], df.columns[6],
                                   df.columns[7], df.columns[8], df.columns[9],
                                   df.columns[10]], render_mode='svg')
fig.update_xaxes(
        rangebreaks=[
            dict(bounds=[0, 10], pattern="hour"),  # hide hours outside of 10am-0pm
        ]
    )
title = html.H1("Central Strike Volatility")
graph_to_display = dcc.Graph(id="graph-content", figure=fig)

fig.update_layout(
    xaxis=dict(
        rangeselector=dict(
            buttons=list([
                dict(count=1,
                    step="day",
                    stepmode="backward"),
            ])
        ),
        rangeslider=dict(
            visible=True
        ),
    )
)

app.layout = html.Div([
    title,
    graph_to_display,
])

def update_graph(value):
    fig = px.line(df, x='DateTime', y=[df.columns[1], df.columns[2], df.columns[3],
                                       df.columns[4], df.columns[5], df.columns[6],
                                       df.columns[7], df.columns[8], df.columns[9],
                                       df.columns[10]])

    fig.update_xaxes(
        rangebreaks=[
            dict(bounds=["sat", "mon"])] # Исключить выходные
    )

    fig.update_xaxes(
        rangebreaks=[
            dict(bounds=[0, 10], pattern="hour"),  # Исключить неторговые часы
        ]
    )

    return fig

if __name__ == '__main__':
    app.run(debug=True)
