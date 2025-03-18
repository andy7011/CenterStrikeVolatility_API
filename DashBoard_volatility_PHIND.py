# DashBoard_volatility.py
def update_output_history(dropdown_value, slider_value, n):
    """Обновление графика истории"""
    limit = 440 * slider_value
    df_candles = alor_api_test._df_candles.copy()

    if not df_candles.empty:
        # Фильтруем данные по тикеру и времени
        df_candles = df_candles[df_candles['ticker'] == dropdown_value]
        df_candles = df_candles.tail(limit)

        # Создаем свечной график
        fig = go.Figure(data=[go.Candlestick(
            x=df_candles['time'],
            open=df_candles['open'],
            high=df_candles['high'],
            low=df_candles['low'],
            close=df_candles['close'],
            name='Candle'
        )])

        # Настраиваем внешний вид графика
        fig.update_layout(
            title=f'Свечной график {dropdown_value}',
            xaxis_title='Время',
            yaxis_title='Цена',
            template='plotly_dark'
        )

        # Убираем неторговое время
        fig.update_xaxes(
            rangebreaks=[
                dict(bounds=["sat", "mon"]),  # hide weekends
                dict(bounds=[24, 9], pattern="hour"),  # hide hours outside of 9am-24pm
            ]
        )

        return fig
    return go.Figure()