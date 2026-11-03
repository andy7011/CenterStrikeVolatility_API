import os.path
import pandas as pd
import threading
from accfifo import Entry, FIFO
from collections import deque
import re

# Каталог data/Finam с CSV-файлами
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR_FINAM = os.path.join(BASE_DIR, "data", "Finam")
# Блокировка для синхронизации доступа к словарям сделок
_trades_lock = threading.Lock()
# Архивная копия сделок (полная история, никогда не очищается)
trades_all = {}
# Хранилище сделок: {trade_id: { ... }}
trades = {}

def load_trades_from_csv(path):
    """Одноразовая загрузка архивной истории сделок из CSV в словарь trades_all."""
    if not path or not os.path.exists(path):
        return 0
    try:
        df = pd.read_csv(path, sep=';', encoding='utf-8')
        print(df)
    except (FileNotFoundError, pd.errors.EmptyDataError, ValueError):
        return 0
    n_total = 0
    n_active = 0
    with _trades_lock:
        for _, row in df.iterrows():
            d = row.to_dict()
            tid = str(d.get('trade_id', ''))
            if not tid:
                continue
            if tid not in trades_all:
                trades_all[tid] = d
                n_total += 1
            # Активные сделки тоже нужны сразу: FIFO (OpenPrice/OpenIV) до
            # первой новой сделки из потока не должен быть пустым
            if tid not in trades:
                trades[tid] = d
                n_active += 1
    # logger.info(
    #     f"Загружено архивных сделок из {path}: всего {n_total} "
    #     f"(в активную историю trades добавлено {n_active})"
    # )
    return n_total

def calculate_open_data_open_price_open_iv(sec_code, net_pos):
    # print(f"Вычисление данных для инструмента {sec_code} с позицией {net_pos}")
    """
    Вычисляет дату открытия позиции, цену и волатильность для заданного инструмента,
    как средневзвешенные по объёму первых сделок до достижения нужного объёма.

    :param sec_code: Код инструмента
    :param net_pos: Текущая позиция (отрицательная для короткой позиции)
    :return: tuple(OpenDateTime, OpenPrice, OpenIV)
    """

    try:
        # Чтение CSV файла
        df = pd.read_csv(os.path.join(DATA_DIR_FINAM, "Finam_Stream_Trades_ALL.csv"), encoding='utf-8', delimiter=';')

        # # Одноразовая загрузка архивной истории сделок из архива CSV в память
        # load_trades_from_csv(os.path.join(DATA_DIR_FINAM, "Finam_Stream_Trades_ALL.csv"))

        # Фильтрация по инструменту (все сделки по инструменту)
        instrument_trades_df = df[df['ticker'] == sec_code].copy()
        # print(instrument_trades_df)

        if instrument_trades_df.empty:
            print(f"Предупреждение: Нет данных для инструмента {sec_code}")
            return None, None, None

        # Преобразование datetime
        instrument_trades_df['datetime'] = pd.to_datetime(instrument_trades_df['datetime'], format='%d.%m.%Y %H:%M:%S')

        # Сортировка по дате
        instrument_trades_df = instrument_trades_df.sort_values('datetime', ascending=False)  # обратный порядок
        # instrument_trades_df = instrument_trades_df.sort_values('datetime')

        # Применяем изменение знака для объема при продаже (умножаем объем сделки на -1)
        instrument_trades_df.loc[instrument_trades_df['operation'] == 'Продажа', 'volume'] *= -1

        # print(instrument_trades_df)
        # print(instrument_trades_df.iloc[-1]['volume']) # последняя сделка
        volume_last = instrument_trades_df.iloc[0]['volume']  # объем последней сделки

        # Целевой объём
        required_volume = net_pos
        selected_trades = []
        # Вычитаем сделки до достижения нужного объёма
        for _, trade in instrument_trades_df.iterrows():
            volume = trade['volume']
            # Для положительного required_volume: вычитаем объем
            if required_volume > 0:
                if required_volume - volume >= 0:
                    selected_trades.append(trade)
                    required_volume -= volume
                else:
                    # Добавляем частичную сделку
                    partial_trade = trade.copy()
                    partial_trade['volume'] = required_volume
                    selected_trades.append(partial_trade)
                    required_volume = 0
                    break
            # Для отрицательного required_volume: прибавляем объем
            else:
                if required_volume - volume <= 0:
                    selected_trades.append(trade)
                    required_volume -= volume
                else:
                    # Добавляем частичную сделку
                    partial_trade = trade.copy()
                    partial_trade['volume'] = required_volume
                    selected_trades.append(partial_trade)
                    required_volume = 0
                    break

            # Прерываем цикл при достижении нуля
            if required_volume == 0:
                break

        # Создаём DataFrame из выбранных сделок
        selected_df = pd.DataFrame(selected_trades)

        # Дата первой сделки (самой старой сделки, она в конце списка)
        OpenDateTime = selected_df.iloc[-1]['datetime'].strftime('%d.%m.%Y %H:%M:%S')

        # Удаляем из списка selected_trades сделки противоположной направленности
        # для правильного расчета средневзвешенных значений цены и волатильности
        if selected_trades:  # Проверяем, что список не пуст
            # Создаем новый список без противоположных сделок
            filtered_trades = []
            # print(f"\nСписок до фильтрации {sec_code} net_pos {net_pos}: {len(selected_trades)}")

            # Проходим по всем сделкам
            for trade in selected_trades:
                volume = trade['volume']

                # Если required_volume положительный - удаляем сделки с отрицательным объемом
                if net_pos > 0:
                    if volume > 0:  # Оставляем только сделки с положительным объемом
                        filtered_trades.append(trade)
                        # print(f"Сделка LONG после фильтрации: {trade['datetime']}, {volume}, {trade['price']}, {trade['volatility']}")
                # Если required_volume отрицательный - удаляем сделки с положительным объемом
                else:
                    if volume < 0:  # Оставляем только сделки с отрицательным объемом
                        filtered_trades.append(trade)
                        # print(f"Сделка SHORT после фильтрации: {trade['datetime']}, {volume}, {trade['price']}, {trade['volatility']}")

            # print(f"Список после фильтрации {sec_code} net_pos {net_pos}: {len(filtered_trades)}")

            # Заменяем исходный список отфильтрованными сделками
            selected_trades = filtered_trades
            # print(f"Список после фильтрации {sec_code} net_pos {net_pos}: {len(selected_trades)}")

        # Расчет средневзвешенной цены и волатильности открытия методом FIFO
        # selected_trades - это отфильтрованный на предыдущем этапе список словарей
        fifo_entries = []
        fifo_entries_volatility = []
        for trade in selected_trades:
            quantity = trade['volume']
            price = trade['price']
            volatility = trade['volatility']

            # Создаем Entry с позиционными аргументами
            fifo_entries.append(Entry(quantity=quantity, price=price))
            fifo_entries_volatility.append(Entry(quantity=quantity, price=volatility))

        fifo = FIFO(fifo_entries)
        # print(f"Позиция {sec_code}: {fifo.stock}")
        # print(f"Цены открытия позиции {sec_code}: {fifo.inventory}")
        s = fifo.inventory
        OpenPrice = calculate_weighted_average(s)
        # print(f'Средневзвешенная цена {sec_code}: {OpenPrice}')

        # print(f"Реализованный P&L {sec_code}: {sum([entry.price * entry.quantity for step in fifo.trace for entry in step])}")
        fifo = FIFO(fifo_entries_volatility)
        # print(f"Волатильность отрытых позиций {sec_code}: {fifo.inventory}")
        # print(f"Реализованный P&L IV {sec_code}: {sum([entry.price * entry.quantity for step in fifo.trace for entry in step])}")
        s = fifo.inventory
        OpenIV = calculate_weighted_average(s)
        # print(f'Средневзвешенная волатильность {sec_code}: {OpenIV}')
        #
        # print('\n')

        if not selected_trades:
            sum_volume_short = instrument_trades_df.loc[instrument_trades_df['operation'] == 'Продажа', 'volume'].sum()
            count_short = (instrument_trades_df['operation'] == 'Продажа').sum()
            sum_volume_long = instrument_trades_df.loc[instrument_trades_df['operation'] == 'Купля', 'volume'].sum()
            count_long = (instrument_trades_df['operation'] == 'Купля').sum()
            print(f"Предупреждение: Недостаточно сделок для инструмента {sec_code}")
            print(f"Позиция: {net_pos}")
            print(f"Сделок лонг: {count_long} Объем: {sum_volume_long}")
            print(f"Сделок шорт: {count_short} Объем: {sum_volume_short}")
            return None, None, None

        return OpenDateTime, OpenPrice, OpenIV

    except Exception as e:
        print(f"Ошибка при вычислении данных открытия для {sec_code}: {e}")
        return None, None, None


def calculate_weighted_average(s):
    # Преобразуем deque в строку, если это необходимо
    if isinstance(s, deque):
        s = str(s)  # или другой способ преобразования deque в строку
    # Извлекаем элементы из строки
    items = re.findall(r'(-?\d+(?:\.\d+)?) @(-?\d+(?:\.\d+)?)', s)

    # Преобразуем в числа
    items = [(float(w), float(v)) for w, v in items]

    # Вычисляем средневзвешенное
    weighted_sum = sum(w * v for w, v in items)
    total_weight = sum(w for w, v in items)

    return weighted_sum / total_weight if total_weight != 0 else 0

# open_iv_value = calculate_open_data_open_price_open_iv('RI100000BK6B', 22)[2]
# print(open_iv_value)