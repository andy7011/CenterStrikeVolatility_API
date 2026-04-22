import time
from time import sleep  # Задержка в секундах перед выполнением операций
import signal
import sys
from datetime import datetime
from threading import Thread, Event  # Запускаем поток подписки
from FinLabPy.Schedule.MOEX import Futures
from FinamPy import FinamPy
from FinamPy.grpc.orders_service_pb2 import Order, OrderState, OrderType, CancelOrderRequest
from FinamPy.grpc.accounts_service_pb2 import GetAccountRequest, GetAccountResponse  # Счет
import FinamPy.grpc.side_pb2 as side  # Направление заявки
from AlorPy import AlorPy  # Работа с Alor OpenAPI V2
import pandas as pd

# Инициализация расписания срочного рынка
futures_schedule = Futures()

# Глобальные переменные
account_id = "1218884"
df_portfolio = pd.DataFrame()  # Глобальный датафрейм для хранения позиций портфеля
all_rows_order_list = []  # Список для хранения всех заявок

# Событие для остановки потоков
stop_event = Event()

def is_market_open():
    """Проверяет, открыт ли срочный рынок"""
    # Используем текущее время без указания часового пояса
    current_time = datetime.now()
    return futures_schedule.trade_session(current_time) is not None


def signal_handler(sig, frame):
    """Обработчик сигнала прерывания"""
    print('\nПрограмма завершена пользователем.')
    sys.exit(0)


def wait_for_market_open():
    """Ждет открытия рынка"""
    while not is_market_open():
        # Используем текущее время без указания часового пояса
        current_time = datetime.now()
        time_until_open = futures_schedule.time_until_trade(current_time)
        # Получаем время открытия следующей сессии
        next_session_start = current_time + time_until_open
        print(
            f"Рынок закрыт. Ожидание открытия через {str(time_until_open).split('.')[0]}. Следующая сессия {next_session_start.strftime('%d.%m.%Y %H:%M:%S')}")
        time.sleep(60)  # Проверяем каждую минуту


def sync_portfolio_positions():
    """Синхронизация позиций в портфеле"""
    global df_portfolio, portfolio_positions

    try:
        portfolio_positions = {}  # Очищаем словарь перед заполнением
        for account_id in fp_provider.account_ids:  # Пробегаемся по всем счетам
            account = fp_provider.call_function(fp_provider.accounts_stub.GetAccount,
                                                GetAccountRequest(account_id=account_id))  # Получаем счет

            for position in account.positions:  # Пробегаемся по всем позициям
                symbol = position.symbol
                quantity = position.quantity.value
                portfolio_positions[symbol] = quantity
        print(portfolio_positions)

        # for position in portfolio_positions:
        #     portfolio_info.append(position)
        #
        # df_portfolio = pd.DataFrame(portfolio_info)
    except Exception as e:
        print(f"Ошибка при синхронизации позиций: {e}")

# Словарь новых котироок
new_quotes = {}


def _on_new_quotes(response):
    # Извлекаем данные из ответа response["data"]
    description = response["data"]['description']
    ask = float(response["data"]['ask']) if response["data"]['ask'] else 0.0
    ask_vol = float(response["data"]['ask_vol']) if response["data"]['ask_vol'] else 0.0
    bid = float(response["data"]['bid']) if response["data"]['bid'] else 0.0
    bid_vol = float(response["data"]['bid_vol']) if response["data"]['bid_vol'] else 0.0
    last_price = float(response["data"]['last_price']) if response["data"]['last_price'] else 0.0

    # Сохраняем в словарь по описанию тикера
    new_quotes[description] = {
        'ask': ask,
        'ask_vol': ask_vol,
        'bid': bid,
        'bid_vol': bid_vol,
        'last_price': last_price
    }
    # print(f"Котировки для {description}: ask={ask}, ask_vol={ask_vol}, bid={bid}, bid_vol={bid_vol}, last_price={last_price}")


# Словарь заявок
order_dict = {}


def _on_order(order):
    # Извлекаем данные из объекта order
    order_id = order.order_id
    exec_id = order.exec_id
    status = order.status
    symbol = order.order.symbol
    account_id = order.order.account_id
    quantity = order.order.quantity.value
    side = order.order.side
    order_type = order.order.type
    time_in_force = order.order.time_in_force
    limit_price = order.order.limit_price.value if order.order.limit_price else None
    client_order_id = order.order.client_order_id
    transact_at = order.transact_at
    initial_quantity = order.initial_quantity.value
    executed_quantity = order.executed_quantity.value
    remaining_quantity = order.remaining_quantity.value

    # Сохраняем данные в словарь по ключу symbol
    order_dict[symbol] = {
        'order_id': order_id,
        'exec_id': exec_id,
        'status': status,
        'account_id': account_id,
        'quantity': quantity,
        'side': side,
        'type': order_type,
        'time_in_force': time_in_force,
        'limit_price': limit_price,
        'client_order_id': client_order_id,
        'transact_at': transact_at,
        'initial_quantity': initial_quantity,
        'executed_quantity': executed_quantity,
        'remaining_quantity': remaining_quantity
    }
    # print(f"Заявка для {symbol}: {order_dict[symbol]}")
    # print(f"Весь словарь: {order_dict}")


# Словарь сделок
trade_dict = {}


def _on_trade(trade):
    # Извлекаем данные из объекта trade
    trade_id = trade.trade_id
    order_id = trade.order_id
    timestamp = trade.timestamp
    side = trade.side
    size = trade.size.value
    price = trade.price.value

    # Сохраняем данные в словарь по ключу order_id
    trade_dict[order_id] = {
        'timestamp': timestamp,
        'trade_id': trade_id,
        'order_id': order_id,
        'side': side,
        'size': size,
        'price': price
    }


def main_loop():
    """Основной цикл программы"""
    # Регистрируем обработчик сигнала
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    while not stop_event.is_set():
        # Ждем открытия рынка
        wait_for_market_open()

        if stop_event.is_set():
            break

        print("Рынок открыт. Запуск основного кода...")

        # Здесь будет запуск основного кода
        # Ваш код будет выполняться здесь
        sync_portfolio_positions()

        # Ждем закрытия рынка
        while is_market_open() and not stop_event.is_set():
            time.sleep(60)  # Проверяем каждую минуту

        print("Рынок закрыт. Ожидание следующего открытия...")

    print("Программа завершена.")


# Подключение к провайдерам
fp_provider = FinamPy()  # Подключаемся ко всем торговым счетам
ap_provider = AlorPy()  # Подключаемся ко всем торговым счетам

# Подписываемся на события
ap_provider.on_new_quotes.subscribe(_on_new_quotes)
# Подписываемся на свои заявки и сделки
fp_provider.on_order.subscribe(_on_order)  # Подписываемся на заявки
fp_provider.on_trade.subscribe(_on_trade)  # Подписываемся на сделки

# Запуск потоков подписки
order_thread = Thread(target=fp_provider.subscribe_orders_thread, name='SubscriptionOrdersThread')
trade_thread = Thread(target=fp_provider.subscribe_trades_thread, name='SubscriptionTradesThread')

order_thread.daemon = True
trade_thread.daemon = True

order_thread.start()
trade_thread.start()

sleep(3)  # Ждем 3 секунды, чтобы подключиться к серверам

if __name__ == "__main__":
    main_loop()
