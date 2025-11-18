import logging  # Выводим лог на консоль и в файл
from datetime import datetime  # Дата и время
from scipy.stats import norm
import pandas as pd
from string import Template
import threading
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

# Глобальная переменная для хранения активных ордеров
active_orders_set = set()

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


def sync_active_orders():
    global active_orders_set, all_rows_order_list, qp_provider

    try:
        # Получаем все ордера с биржи
        orders_response = qp_provider.get_all_orders()
        if orders_response and orders_response.get('data'):
            current_active_orders = set()
            # Создаем словарь order_num -> order_data для активных ордеров
            current_orders_dict = {}

            for order in orders_response['data']:
                if order.get('class_code') == 'SPBOPT':
                    # Проверяем, что ордер активен (бит 0 установлен) и не снят (бит 1 не установлен)
                    if (order.get('flags') & 0b1 == 0b1) and (order.get('flags') & 0b10 != 0b10):
                        order_num = str(order.get('order_num'))
                        current_active_orders.add(order_num)
                        current_orders_dict[order_num] = order

            # Находим ордера, которые были удалены с биржи или стали неактивными
            orders_to_remove = active_orders_set - current_active_orders

            # Удаляем неактивные ордера из нашего списка
            if orders_to_remove:
                original_count = len(all_rows_order_list)
                all_rows_order_list = [item for item in all_rows_order_list
                                       if str(item['order_num']) not in orders_to_remove]
                removed_count = original_count - len(all_rows_order_list)
                if removed_count > 0:
                    print(f"Удалено {removed_count} неактивных ордеров: {orders_to_remove}")

            # Добавляем новые активные ордера, которых нет в нашем списке
            existing_order_nums = {str(item['order_num']) for item in all_rows_order_list}
            new_orders_to_add = current_active_orders - existing_order_nums

            for order_num in new_orders_to_add:
                order_data = current_orders_dict[order_num]
                # Добавляем ордер в список (передаем сам order_data, не order_data.get('data'))
                _add_order_to_list_from_data(order_data)
                print(f"Добавлен активный ордер при синхронизации: {order_num}")

            # Обновляем список активных ордеров
            active_orders_set = current_active_orders

            # Сохраняем в файл
            _save_orders_to_csv()

    except Exception as e:
        print(f"Ошибка при синхронизации ордеров: {e}")



def _add_order_to_list_from_data(order_data):
    """Добавление ордера в список на основе данных ордера"""
    global all_rows_order_list, qp_provider

    try:
        order_num = str(order_data.get('order_num'))

        # Проверяем, нет ли уже такой заявки в списке
        existing_order = next((item for item in all_rows_order_list if str(item['order_num']) == order_num), None)
        if existing_order:
            print(f"Заявка с order_num {order_num} уже существует, пропускаем")
            return

        # Определяем тип операции
        buy = order_data.get('flags') & 0b100 != 0b100  # Заявка на покупку
        operation = "Купля" if buy else "Продажа"

        # Получаем информацию о ценной бумаге
        sec_code = order_data.get('sec_code')
        si = qp_provider.get_symbol_info('SPBOPT', sec_code)  # Спецификация тикера

        # Получаем цену базового актива
        asset_price_data = qp_provider.get_param_ex('SPBFUT', si['base_active_seccode'], 'LAST', trans_id=0)
        if not asset_price_data or not asset_price_data.get('data'):
            print(f"Не удалось получить цену базового актива для {si['base_active_seccode']}")
            return

        asset_price = float(asset_price_data['data']['param_value'])

        # Получаем дату экспирации
        expdate_data = qp_provider.get_param_ex('SPBOPT', sec_code, 'EXPDATE', trans_id=0)
        if not expdate_data or not expdate_data.get('data'):
            print(f"Не удалось получить дату экспирации для {sec_code}")
            return

        expdate_image = expdate_data['data']['param_image']
        expdate_str = datetime.strptime(expdate_image, "%d.%m.%Y").strftime("%Y-%m-%d")
        expdate = datetime.strptime(expdate_str, "%Y-%m-%d")

        # Определяем тип опциона
        option_type_data = qp_provider.get_param_ex('SPBOPT', sec_code, 'OPTIONTYPE', trans_id=0)
        if not option_type_data or not option_type_data.get('data'):
            print(f"Не удалось получить тип опциона для {sec_code}")
            return

        option_type_str = option_type_data['data']['param_image']
        opt_type_converted = option_type.PUT if option_type_str == "Put" else option_type.CALL

        # Форматируем дату экспирации
        exp_date_number = si['exp_date']
        exp_date_str = str(exp_date_number)
        exp_date = datetime.strptime(exp_date_str, "%Y%m%d")
        formatted_exp_date = exp_date.strftime("%d.%m.%Y")

        # Вычисляем количество и цену
        order_qty = order_data.get('qty') * si['lot_size']
        order_price = qp_provider.quik_price_to_price('SPBOPT', sec_code, order_data.get('price'))

        # Создаем опцион для расчета волатильности
        option = Option(sec_code, si["base_active_seccode"], expdate, si['option_strike'], opt_type_converted)

        # Добавляем заявку в список
        all_rows_order_list.append({
            'datetime': format_datetime(order_data.get('datetime')),
            'order_num': order_num,
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

    except Exception as e:
        print(f"Ошибка при добавлении ордера {order_data.get('order_num')}: {e}")

def _save_orders_to_csv():
    """Сохранение ордеров в CSV"""
    if all_rows_order_list:
        df_order_quik = pd.DataFrame(all_rows_order_list)
        df_order_quik.to_csv(temp_obj.substitute(name_file='QUIK_Stream_Orders.csv'),
                           sep=';', encoding='utf-8', index=False)
    else:
        empty_df = pd.DataFrame(columns=['datetime', 'order_num', 'option_base', 'ticker',
                                        'option_type', 'strike', 'expdate', 'operation',
                                        'volume', 'price', 'value', 'volatility'])
        empty_df.to_csv(temp_obj.substitute(name_file='QUIK_Stream_Orders.csv'),
                       sep=';', encoding='utf-8', index=False)

def _add_order_to_list(order_data):
    """Добавление ордера в список (логика как в _on_order_impl)"""
    _add_order_to_list_from_data(order_data.get('data'))


def sync_orders_worker():
    """Фоновый поток для периодической синхронизации ордеров"""
    while True:
        try:
            time.sleep(30)  # Проверяем каждые 30 секунд
            sync_active_orders()
        except Exception as e:
            print(f"Ошибка в потоке синхронизации: {e}")
            time.sleep(5)  # При ошибке ждем 5 секунд перед повтором


# Запуск потока синхронизации при старте
def start_sync_thread():
    sync_thread = threading.Thread(target=sync_orders_worker, daemon=True)
    sync_thread.start()
    print("Поток синхронизации ордеров запущен")


# Обновленная функция _on_order_impl
def _on_order_impl(data):
    """Реализация обработчика событий по заявкам"""
    global all_rows_order_list, qp_provider, class_code, active_orders_set

    order_data = data

    # Проверяем, что это опцион
    if order_data.get('data').get('class_code') == 'SPBOPT':
        order_num = str(order_data.get('data').get('order_num'))

        # Проверяем, что ордер активен (бит 0 установлен) и не снят (бит 1 не установлен)
        if (order_data.get('data').get('flags') & 0b1 != 0b1) or (order_data.get('data').get('flags') & 0b10 == 0b10):
            print(f"{format_datetime(order_data.get('data').get('datetime'))} Заявка снята: {order_num}")
            # Удаляем из списка активных ордеров
            active_orders_set.discard(order_num)
            # Удаляем из нашего списка
            original_count = len(all_rows_order_list)
            all_rows_order_list = [item for item in all_rows_order_list if str(item['order_num']) != order_num]
            # removed_count = original_count - len(all_rows_order_list)
            # if removed_count > 0:
                # print(f"Удалено {removed_count} записей с order_num: {order_num}")
        else:
            print(f"{format_datetime(order_data.get('data').get('datetime'))} Новая заявка: {order_num}")
            # Добавляем в список активных ордеров
            active_orders_set.add(order_num)

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

            # Проверяем, нет ли уже такой заявки в списке
            existing_order = next((item for item in all_rows_order_list if str(item['order_num']) == order_num), None)
            if existing_order:
                print(f"Заявка с order_num {order_num} уже существует, пропускаем")
                return

            # Добавляем заявку в список
            all_rows_order_list.append({
                'datetime': format_datetime(order_data.get('data').get('datetime')),
                'order_num': order_num,
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

        # Создаем DataFrame и сохраняем в CSV только если есть изменения
        if all_rows_order_list:
            df_order_quik = pd.DataFrame(all_rows_order_list)
            df_order_quik.to_csv(temp_obj.substitute(name_file='QUIK_Stream_Orders.csv'), sep=';', encoding='utf-8',
                                 index=False)
        else:
            # Если список пуст, создаем пустой файл с заголовками
            empty_df = pd.DataFrame(columns=['datetime', 'order_num', 'option_base', 'ticker', 'option_type',
                                             'strike', 'expdate', 'operation', 'volume', 'price', 'value',
                                             'volatility'])
            empty_df.to_csv(temp_obj.substitute(name_file='QUIK_Stream_Orders.csv'), sep=';', encoding='utf-8',
                            index=False)



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

    # Сразу выполняем синхронизацию активных ордеров
    sync_active_orders()

    # Запускаем поток синхронизации
    start_sync_thread()

    # Создаем обработчики событий
    order_handler = OrderHandler()
    trade_handler = TradeHandler()

    # Подписка на события через объекты с методом trigger
    qp_provider.on_order = order_handler
    qp_provider.on_trade = trade_handler

    # Основной цикл
    try:
        print("Сервис запущен. Нажмите Ctrl+C для остановки.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Остановка сервиса...")
        qp_provider.close_connection_and_thread()
        print("Сервис остановлен")
