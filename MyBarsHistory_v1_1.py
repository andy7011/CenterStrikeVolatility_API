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
    for symbol in iter(MAP):  # Пробегаемся по всем фьючерсам в списке app.supported_base_asset.MAP
        # Файлы для интервалов D1 и M5
        for timeframe in ['D1', 'M5']:
            dataname = f'SPBFUT.{symbol}'
            datapath = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'Data', 'Finam', '')
            filename = f'{datapath}{dataname}_{timeframe}.txt'  # Полное имя файла
            # print(f'filename {filename}')
            if os.path.exists(filename):
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
                    # print(f'df_bars_cut {df_bars_cut}')
                    # Записываем отфильтрованный DataFrame в текстовый файл
                    # df_bars_cut.to_csv(filename, sep='\t', encoding='utf-8', index=True)
                else:
                    print(f"Столбец 'datetime' не найден в файле {filename}")

def main():
    # Создаем новый экземпляр брокера для каждого запуска
    # Используем прямой доступ к провайдеру для избежания проблем с соединением
    from FinLabPy.Brokers.Finam import Finam
    from FinLabPy.Config import FinamPy

    # Создаем новый провайдер для каждого запуска
    fp_provider = FinamPy()  # Новый экземпляр провайдера
    broker = Finam(code='Ф', name='Финам', provider=fp_provider, storage='file')  # Новый экземпляр брокера

    try:
        # Интервал D1
        for symbol in iter(MAP):  # Пробегаемся по всем фьючерсам в списке app.supported_base_asset.MAP
            time_frame = 'D1'  # Временной интервал
            print(symbol)
            dataname = f'SPBFUT.{symbol}'
            symbol = broker.get_symbol_by_dataname(dataname)  # Тикер по названию
            bars = broker.get_history(symbol, time_frame,
                                      dt_from=date_140_days_ago)  # Получаем историю тикера за 140 дней
            print(bars[0])  # Первый бар
            print(bars[-1])  # Последний бар
            # print(bars_to_df(bars))  # Все бары в pandas DataFrame
            time.sleep(1)  # Пауза в 1 секунду

        # Интервал M5
        for symbol in iter(MAP):  # Пробегаемся по всем фьючерсам в списке app.supported_base_asset.MAP
            time_frame = 'M5'  # Временной интервал
            print(symbol)
            dataname = f'SPBFUT.{symbol}'
            symbol = broker.get_symbol_by_dataname(dataname)  # Тикер по названию
            bars = broker.get_history(symbol, time_frame,
                                      dt_from=date_140_days_ago)  # Получаем историю тикера за 140 дней
            print(bars[0])  # Первый бар
            print(bars[-1])  # Последний бар
            # print(bars_to_df(bars))  # Все бары в pandas DataFrame
            time.sleep(1)  # Пауза в 1 секунду

        # Удаляем старые данные после получения новых
        print("Удаляем старые данные...")
        clean_old_data_files()

    finally:
        # Закрываем брокера только один раз при завершении работы
        broker.close()  # Закрываем брокера


if __name__ == '__main__':  # Точка входа при запуске этого скрипта
    while True:
        print(f"Запуск в {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        try:
            main()
            print("Ожидание следующего запуска...")
        except Exception as e:
            print(f"Ошибка при выполнении: {e}")
        time.sleep(60)  # Ждем 60 секунд (1 минуту)
