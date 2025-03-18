# alor_api_test.py
import asyncio
import pandas as pd
import threading
from queue import Queue
from datetime import datetime, timedelta
from pytz import timezone, utc


class AlorApiTest:
    def __init__(self):
        self._async_queue = asyncio.Queue()
        self._alorApi = AlorApi(env_utils.get_env_or_exit('ALOR_CLIENT_TOKEN'))
        self._df_candles = pd.DataFrame(columns=['time', 'open', 'high', 'low', 'close', 'volume', 'ticker'])
        self._data_queue = Queue()  # Очередь для обмена данными между потоками
        self._stop_event = threading.Event()  # Событие для остановки потоков

    def run(self):
        # Запускаем поток сбора данных
        data_thread = threading.Thread(target=self._collect_data, daemon=True)
        data_thread.start()

        # Запускаем поток обновления графика
        update_thread = threading.Thread(target=self._update_graph, daemon=True)
        update_thread.start()

        # Запускаем Dash приложение
        self._start_dash_app()

        # Ожидаем завершения работы
        try:
            while not self._stop_event.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            self._stop_event.set()

    def _collect_data(self):
        """Поток сбора данных с API"""
        while not self._stop_event.is_set():
            try:
                for ticker in MAP.keys():
                    self._alorApi.subscribe_to_bars(ticker, self._handle_quotes_event_bars)
                    time.sleep(1)  # Пауза между запросами
            except Exception as e:
                print(f"Ошибка сбора данных: {e}")
                time.sleep(5)  # Ждем перед повторной попыткой

    def _handle_quotes_event_bars(self, ticker, data):
        """Обработчик событий свечей"""
        try:
            data['ticker'] = ticker
            current_timestamp = int(datetime.now().timestamp())
            time_from = current_timestamp - (24 * 60 * 60 * 7)  # Минус неделя

            if data['time'] > time_from:
                df_candle = pd.DataFrame.from_dict([data])
                self._data_queue.put(df_candle)  # Добавляем данные в очередь
        except Exception as e:
            print(f"Ошибка обработки данных: {e}")

    def _update_graph(self):
        """Поток обновления графика"""
        while not self._stop_event.is_set():
            try:
                # Обработка данных из очереди
                while not self._data_queue.empty():
                    df_candle = self._data_queue.get()
                    self._df_candles = pd.concat([self._df_candles, df_candle], ignore_index=True)

                    # Очищаем старые данные
                    current_timestamp = int(datetime.now().timestamp())
                    time_from = current_timestamp - (24 * 60 * 60 * 7)
                    self._df_candles = self._df_candles[self._df_candles['time'] > time_from]

                time.sleep(0.1)  # Пауза между обновлениями
            except Exception as e:
                print(f"Ошибка обновления графика: {e}")
                time.sleep(1)