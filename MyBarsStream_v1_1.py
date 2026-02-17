from FinLabPy.Config import brokers, default_broker
from app.supported_base_asset import MAP
import time


def make_bar_stream(symbol, time_frame):
    print(f'Подписка на бары {time_frame} для фьючерса {symbol}')
    ticker = broker.get_symbol_by_dataname(dataname)
    broker.subscribe_history(ticker, time_frame) # Подписка на историю тикера
    return lambda bar: print(f'{symbol} {bar}')

if __name__ == '__main__':
    broker = default_broker
    time_frame = 'M15'
    # Подписываемся один раз на событие получения нового бара
    broker.on_new_bar.subscribe(lambda bar: print(bar))
    for symbol in iter(MAP):
        dataname = f'SPBFUT.{symbol}'
        symbol = broker.get_symbol_by_dataname(dataname)  # Тикер по названию
        make_bar_stream(symbol, time_frame)
        time.sleep(1)  # Пауза 1с между подписками

    input('\nEnter - выход\n')
    broker.close()
