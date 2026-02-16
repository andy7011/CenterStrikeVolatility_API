from FinLabPy.Config import brokers, default_broker
from app.supported_base_asset import MAP
import time

if __name__ == '__main__':
    broker = default_broker
    time_frame = 'M1'

    def make_bar_handler(symbol):
        return lambda bar: print(f'{symbol} {bar}')


    for symbol in iter(MAP):
        dataname = f'SPBFUT.{symbol}'
        print(f'Подписка на бары {time_frame} для фьючерса {symbol}')
        ticker = broker.get_symbol_by_dataname(dataname)
        if ticker is None:
            print(f"Не удалось получить тикер для {dataname}")
            continue
        broker.subscribe_history(ticker, time_frame)
        broker.on_new_bar.subscribe(lambda bar, sym=symbol: print(f'{sym} {bar}'))
        time.sleep(1)  # Пауза 1с между подписками

    input('\nEnter - выход\n')
    broker.close()
