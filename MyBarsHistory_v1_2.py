from datetime import datetime, timedelta, UTC  # Дата и время
import time  # Подписка на события по времени
import os  # Для работы с файлами
import os.path
import pandas as pd

from FinLabPy.Config import brokers, default_broker  # Все брокеры и брокер по умолчанию
from FinLabPy.Core import bars_to_df  # Перевод бар в pandas DataFrame
from app.supported_base_asset import MAP

# Запрашиваем глубину истории 140 дней
date_140_days_ago = datetime.now() - timedelta(days=140)


def clean_old_data_files():
    """Удаляет из файлов исторических данных строки со значением datetime менее date_140_days_ago"""
    print(f"Удаляем старые данные начиная с {date_140_days_ago}")
    for symbol in iter(MAP):  # Пробегаемся по всем фьючерсам в списке app.supported_base_asset.MAP
        # Файлы для интервалов D1 и M15
        for timeframe in ['D1', 'M15']:
            dataname = f'SPBFUT.{symbol}'
            datapath = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'Data', 'Alor', '')
            filename = f'{datapath}{dataname}_{timeframe}.txt'  # Полное имя файла
            if os.path.exists(filename):
                try:
                    df_bars_cut = pd.read_csv(filename, sep='\t', encoding='utf-8', header=0)
                    # Убедимся, что столбец datetime существует
                    if 'datetime' in df_bars_cut.columns:
                        # Конвертируем столбец datetime в правильный формат
                        df_bars_cut['datetime'] = pd.to_datetime(df_bars_cut['datetime'], format='%d.%m.%Y %H:%M')
                        # Устанавливаем datetime как индекс
                        df_bars_cut = df_bars_cut.set_index('datetime')
                        # Фильтруем по дате
                        df_bars_cut = df_bars_cut[df_bars_cut.index >= date_140_days_ago]
                        # Сбрасываем индекс, чтобы datetime стал обычным столбцом
                        df_bars_cut = df_bars_cut.reset_index()
                        df_bars_cut['datetime'] = df_bars_cut['datetime'].dt.strftime('%d.%m.%Y %H:%M')
                        # Записываем отфильтрованный DataFrame обратно в тот же текстовый файл
                        df_bars_cut.to_csv(filename, sep='\t', encoding='utf-8', index=False)
                    else:
                        print(f"Столбец 'datetime' не найден в файле {filename}")
                except Exception as e:
                    print(f"Ошибка при обработке файла {filename}: {e}")


def main():
    # Создаем новый экземпляр брокера для каждого запуска
    # Используем прямой доступ к провайдеру для избежания проблем с соединением
    # from FinLabPy.Brokers.Finam import Finam
    # from FinLabPy.Config import FinamPy
    from FinLabPy.Brokers.Alor import Alor
    from FinLabPy.Config import AlorPy

    # Создаем новый провайдер для каждого запуска
    # fp_provider = FinamPy()  # Новый экземпляр провайдера
    # broker = Finam(code='Ф', name='Финам', provider=fp_provider, storage='file')  # Новый экземпляр брокера
    ap_provider = AlorPy()  # Провайдер Алор.
    broker = Alor(code='AC', name='Алор - Срочный рынок', provider=ap_provider, storage='file')



    try:
        # Интервал D1 - обновляется каждые 10 минут
        print("Начинаем загрузку D1 данных...")
        for symbol in iter(MAP):  # Пробегаемся по всем фьючерсам в списке app.supported_base_asset.MAP
            time_frame = 'D1'  # Временной интервал
            print(f"Загружаем {time_frame} данные для {symbol}")
            dataname = f'SPBFUT.{symbol}'

            # Проверяем, существует ли символ в брокере
            try:
                symbol_obj = broker.get_symbol_by_dataname(dataname)
                if symbol_obj is None:
                    print(f"Символ {dataname} не найден в брокере")
                    continue

                bars = broker.get_history(symbol_obj, time_frame,
                                          dt_from=date_140_days_ago)  # Получаем историю тикера за 140 дней
                print(f"Первый бар: {bars[0]}")  # Первый бар
                print(f"Последний бар: {bars[-1]}")  # Последний бар
                # print(bars_to_df(bars))  # Все бары в pandas DataFrame
                time.sleep(1)  # Пауза в 1 секунду
            except Exception as e:
                print(f"Ошибка при загрузке данных для {symbol}: {e}")
                continue

        # Интервал M15 - обновляется каждую минуту
        print("Начинаем загрузку M15 данных...")
        for symbol in iter(MAP):  # Пробегаемся по всем фьючерсам в списке app.supported_base_asset.MAP
            time_frame = 'M15'  # Временной интервал
            print(f"Загружаем {time_frame} данные для {symbol}")
            dataname = f'SPBFUT.{symbol}'

            # Проверяем, существует ли символ в брокере
            try:
                symbol_obj = broker.get_symbol_by_dataname(dataname)
                if symbol_obj is None:
                    print(f"Символ {dataname} не найден в брокере")
                    continue

                bars = broker.get_history(symbol_obj, time_frame,
                                          dt_from=date_140_days_ago)  # Получаем историю тикера за 140 дней
                print(f"Первый бар: {bars[0]}")  # Первый бар
                print(f"Последний бар: {bars[-1]}")  # Последний бар
                # print(bars_to_df(bars))  # Все бары в pandas DataFrame
                time.sleep(1)  # Пауза в 1 секунду
            except Exception as e:
                print(f"Ошибка при загрузке данных для {symbol}: {e}")
                continue

        # Удаляем старые данные после получения новых
        clean_old_data_files()

    finally:
        # Закрываем брокера только один раз при завершении работы
        broker.close()  # Закрываем брокера


def run_with_intervals():
    """Запуск с разными интервалами обновления"""
    last_d1_update = datetime.min
    last_m15_update = datetime.min

    while True:
        current_time = datetime.now()
        print(f"Запуск в {current_time.strftime('%Y-%m-%d %H:%M:%S')}")

        try:
            # Проверяем, нужно ли обновлять D1 данные (каждые 10 минут)
            if current_time - last_d1_update >= timedelta(minutes=10):
                print("Выполняем обновление D1 данных...")
                main()
                last_d1_update = current_time
                last_m15_update = current_time  # Сбрасываем время M15, чтобы обновить сразу после D1
                print("Обновление D1 данных завершено")
            else:
                # Обновляем M15 данные каждую минуту
                if current_time - last_m15_update >= timedelta(minutes=1):
                    print("Выполняем обновление M15 данных...")
                    # Только обновляем M15 данные

                    from FinLabPy.Brokers.Alor import Alor  # Брокер Алор
                    from AlorPy import AlorPy  # Провайдер Алор
                    ap_provider = AlorPy()  # Провайдер Алор.
                    broker = Alor(code='AC', name='Алор - Срочный рынок', provider=ap_provider, storage='file')

                    # from FinLabPy.Brokers.Finam import Finam
                    # from FinLabPy.Config import FinamPy
                    # fp_provider = FinamPy()
                    # broker = Finam(code='Ф', name='Финам', provider=fp_provider, storage='file')

                    try:
                        for symbol in iter(MAP):
                            time_frame = 'M15'
                            print(f"Загружаем {time_frame} данные для {symbol}")
                            dataname = f'SPBFUT.{symbol}'

                            # Проверяем, существует ли символ в брокере
                            try:
                                symbol_obj = broker.get_symbol_by_dataname(dataname)
                                if symbol_obj is None:
                                    print(f"Символ {dataname} не найден в брокере")
                                    continue

                                bars = broker.get_history(symbol_obj, time_frame, dt_from=date_140_days_ago)
                                print(f"Первый бар: {bars[0]}")
                                print(f"Последний бар: {bars[-1]}")
                                time.sleep(1)
                            except Exception as e:
                                print(f"Ошибка при загрузке данных для {symbol}: {e}")
                                continue

                        clean_old_data_files()
                        last_m15_update = current_time
                        print("Обновление M15 данных завершено")
                    finally:
                        broker.close()

                print("Ожидание следующего запуска...")

        except Exception as e:
            print(f"Ошибка при выполнении: {e}")

        time.sleep(60)  # Ждем 60 секунд (1 минуту)


if __name__ == '__main__':  # Точка входа при запуске этого скрипта
    run_with_intervals()
