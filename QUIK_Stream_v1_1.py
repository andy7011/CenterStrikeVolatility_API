import logging  # Выводим лог на консоль и в файл
from datetime import datetime  # Дата и время
from scipy.stats import norm
import pandas as pd
from string import Template
import time  # Подписка на события по времени
from FinLabPy.Schedule.MOEX import Futures

import implied_volatility
import option_type
from QuikPy import QuikPy  # Работа с QUIK из Python через LUA скрипты QUIK#
from option import Option

# Конфигурация для работы с файлами
temp_str = 'C:\\Users\\шадрин\\YandexDisk\\_ИИС\\Position\\$name_file'
temp_obj = Template(temp_str)

futures_firm_id = 'SPBFUT'  # Код фирмы для фьючерсов


def job():
    """Функция для выполнения по расписанию"""
    print(f"Расписание торгов фьючерсами в {datetime.now()}")


# Функция для форматирования даты и времени
def format_datetime(datetime_dict):
    """Форматирует дату и время из словаря в строку"""
    year = datetime_dict['year']
    month = datetime_dict['month']
    day = datetime_dict['day']
    hour = datetime_dict['hour']
    minute = datetime_dict['min']
    second = datetime_dict['sec']
    formatted_datetime = f"{day:02d}.{month:02d}.{year} {hour:02d}:{minute:02d}:{second:02d}"
    return formatted_datetime


# Глобальные переменные
all_rows_order_list = []  # Список для хранения всех заявок
qp_provider = None  # Глобальная ссылка на провайдер QUIK
class_code = 'SPBOPT'  # Глобальная переменная для класса опционов


class OrderHandler:
    """Класс для обработки событий по заявкам"""

    def trigger(self, data):
        _on_order_impl(data)


class TradeHandler:
    """Класс для обработки событий по сделкам"""

    def trigger(self, data):
        _on_trade_impl(data)


def _on_order_impl(data):
    """Реализация обработчика событий по заявкам"""
    global all_rows_order_list, qp_provider, class_code

    order_data = data

    # Проверяем, что это опцион
    if order_data.get('data').get('class_code') == 'SPBOPT':
        if order_data.get('data').get('flags') & 0b10 == 0b10:  # Заявка снята
            print("Заявка снята")
            all_rows_order_list = [item for item in all_rows_order_list if
                                   item['order_num'] != order_data.get('data').get('order_num')]

        else:
            print("Новая заявка")
            # Определяем тип операции
            buy = order_data.get('data').get('flags') & 0b100 != 0b100  # Заявка на покупку
            operation = "Купля" if buy else "Продажа"

            # Получаем информацию о ценной бумаге
            sec_code = order_data.get('data').get('sec_code')
            si = qp_provider.get_symbol_info('SPBOPT', sec_code)  # Спецификация тикера

            # Получаем цену базового актива
            asset_price = qp_provider.get_param_ex('SPBFUT', si['base_active_seccode'], 'LAST', trans_id=0)['data'][
                'param_value']
            asset_price = float(asset_price)

            # Получаем дату экспирации
            expdate_image = qp_provider.get_param_ex('SPBOPT', sec_code, 'EXPDATE', trans_id=0)['data']['param_image']
            expdate_str = datetime.strptime(expdate_image, "%d.%m.%Y").strftime("%Y-%m-%d")
            expdate = datetime.strptime(expdate_str, "%Y-%m-%d")

            # Определяем тип опциона
            option_type_str = qp_provider.get_param_ex('SPBOPT', sec_code, 'OPTIONTYPE', trans_id=0)['data'][
                'param_image']
            opt_type_converted = option_type.PUT if option_type_str == "Put" else option_type.CALL

            # Форматируем дату экспирации
            exp_date_number = si['exp_date']
            exp_date_str = str(exp_date_number)
            exp_date = datetime.strptime(exp_date_str, "%Y%m%d")
            formatted_exp_date = exp_date.strftime("%d.%m.%Y")

            # Вычисляем количество и цену
            order_qty = order_data.get('data').get('qty') * si['lot_size']
            order_price = qp_provider.quik_price_to_price('SPBOPT', sec_code, order_data.get('data').get('price'))

            # Создаем опцион для расчета волатильности
            option = Option(sec_code, si["base_active_seccode"], expdate, si['option_strike'], opt_type_converted)

            # Добавляем заявку в список
            all_rows_order_list.append({
                'datetime': format_datetime(order_data.get('data').get('datetime')),
                'order_num': order_data.get('data').get('order_num'),
                'option_base': si['base_active_seccode'],
                'ticker': sec_code,
                'option_type': option_type_str,
                'strike': int(si['option_strike']),
                'expdate': formatted_exp_date,
                'operation': operation,
                'volume': order_qty,
                'price': order_price,
                'value': order_qty * order_price,
                'volatility': round(implied_volatility.get_iv_for_option_price(asset_price, option, order_price), 2)
            })

            # Создаем DataFrame и сохраняем в CSV
            df_order_quik = pd.DataFrame(all_rows_order_list)
            print(df_order_quik)
            df_order_quik.to_csv(temp_obj.substitute(name_file='QUIK_Stream_Orders.csv'), sep=';', encoding='utf-8', index=False)


def _on_trade_impl(data):
    """Реализация обработчика событий по сделкам"""
    global qp_provider, class_code

    trade_data = data
    row_trade_list = []  # Список для новой сделки

    # Проверяем, что это опцион
    if trade_data.get('data').get('class_code') == 'SPBOPT':
        print("Новая сделка")

        # Определяем тип операции
        buy = trade_data.get('data').get('flags') & 0b100 != 0b100  # Заявка на покупку
        operation = "Купля" if buy else "Продажа"

        # Получаем информацию о ценной бумаге
        sec_code = trade_data.get('data').get('sec_code')
        si = qp_provider.get_symbol_info('SPBOPT', sec_code)

        # Получаем цену базового актива
        asset_price = qp_provider.get_param_ex('SPBFUT', si['base_active_seccode'], 'LAST', trans_id=0)['data'][
            'param_value']
        asset_price = float(asset_price)

        # Получаем дату экспирации
        expdate_image = qp_provider.get_param_ex('SPBOPT', sec_code, 'EXPDATE', trans_id=0)['data']['param_image']
        expdate_str = datetime.strptime(expdate_image, "%d.%m.%Y").strftime("%Y-%m-%d")
        expdate = datetime.strptime(expdate_str, "%Y-%m-%d")

        # Определяем тип опциона
        option_type_str = qp_provider.get_param_ex('SPBOPT', sec_code, 'OPTIONTYPE', trans_id=0)['data']['param_image']
        opt_type_converted = option_type.PUT if option_type_str == "Put" else option_type.CALL

        # Форматируем дату экспирации
        exp_date_number = si['exp_date']
        exp_date_str = str(exp_date_number)
        exp_date = datetime.strptime(exp_date_str, "%Y%m%d")
        formatted_exp_date = exp_date.strftime("%d.%m.%Y")

        # Вычисляем количество и цену
        trade_qty = trade_data.get('data').get('qty') * si['lot_size']
        trade_price = qp_provider.quik_price_to_price('SPBOPT', sec_code, trade_data.get('data').get('price'))

        # Создаем опцион для расчета волатильности
        option = Option(sec_code, si["base_active_seccode"], expdate, si['option_strike'], opt_type_converted)

        # Добавляем сделку в список
        row_trade_list.append({
            'datetime': format_datetime(trade_data.get('data').get('datetime')),
            'order_num': trade_data.get('data').get('trade_num'),
            'option_base': si['base_active_seccode'],
            'ticker': sec_code,
            'option_type': option_type_str,
            'strike': int(si['option_strike']),
            'expdate': formatted_exp_date,
            'operation': operation,
            'volume': trade_qty,
            'price': trade_price,
            'value': trade_qty * trade_price,
            'volatility': round(implied_volatility.get_iv_for_option_price(asset_price, option, trade_price), 2)
        })

        # Создаем DataFrame и добавляем в CSV файл
        df_trade_quik = pd.DataFrame(row_trade_list)
        print(df_trade_quik)
        df_trade_quik.to_csv(temp_obj.substitute(name_file='QUIK_Stream_Trades.csv'), mode='a', sep=';', index=False,
                             header=False)


if __name__ == '__main__':  # Точка входа при запуске этого скрипта
    # Настройка логирования
    logger = logging.getLogger('QuikPy.Accounts')
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%d.%m.%Y %H:%M:%S',
        level=logging.DEBUG,
        handlers=[
            logging.FileHandler('QUIK_Stream.log', encoding='utf-8'),
            logging.StreamHandler()
        ]
    )

    # Подключение к QUIK
    qp_provider = QuikPy()

    # Создаем обработчики событий
    order_handler = OrderHandler()
    trade_handler = TradeHandler()

    # Подписка на события через объекты с методом trigger
    qp_provider.on_order = order_handler
    qp_provider.on_trade = trade_handler

    # Основной цикл с обработкой Ctrl+C
    try:
        print("Сервис запущен. Нажмите Ctrl+C для остановки.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Остановка сервиса...")
        qp_provider.close_connection_and_thread()
        print("Сервис остановлен.")
