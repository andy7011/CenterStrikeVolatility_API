import logging # Выводим лог на консоль и в файл
logging.basicConfig(level=logging.WARNING) # уровень логгирования
from datetime import datetime, timezone  # Дата и время
from zoneinfo import ZoneInfo
from time import sleep  # Задержка в секундах перед выполнением операций
from threading import Thread  # Запускаем поток подписки
import threading

import math
import numpy as np
from scipy.stats import norm
import signal
import sys

from FinamPy import FinamPy
from FinamPy.grpc.accounts.accounts_service_pb2 import GetAccountRequest, GetAccountResponse  # Счет
from FinamPy.grpc.assets.assets_service_pb2 import GetAssetRequest, GetAssetResponse  # Информация по тикеру
from FinamPy.grpc.orders.orders_service_pb2 import Order, OrderState, OrderType, CancelOrderRequest, StopCondition  # Заявки
import FinamPy.grpc.side_pb2 as side  # Направление заявки
from FinamPy.grpc.marketdata.marketdata_service_pb2 import QuoteRequest, QuoteResponse  # Последняя цена сделки
from FinLabPy.Config import brokers, default_broker  # Все брокеры и брокер по умолчанию

from QUIK_Stream_v1_7 import calculate_open_data_open_price_open_iv

from AlorPy import AlorPy  # Работа с Alor OpenAPI V2

from google.type.decimal_pb2 import Decimal

# Глобальная переменная для управления циклом
running = True
CALL = 'C'
PUT = 'P'
r = 0 # Безрисковая ставка
guids = []

# Обработчик сигнала
def signal_handler(sig, frame):
    global running
    print('Программа завершается...')
    running = False
    # Завершаем все потоки, если есть
    # Отписываемся от всех котировок
    for guid in guids:
        try:
            logger.info(f'Подписка на котировки {ap_provider.unsubscribe(guid)} отменена')
        except Exception as e:
            logger.error(f'Ошибка отписки: {e}')
    # Отмена подписок
    print(f'\n')
    print('Отмена подписок')
    fp_provider.on_order.unsubscribe(_on_order)  # Сбрасываем обработчик заявок
    fp_provider.on_trade.unsubscribe(_on_trade)  # Сбрасываем обработчик сделок
    ap_provider.on_new_quotes.unsubscribe(_on_new_quotes)  # Отменяем подписку на события
    # Выход
    print('Закрываем канал перед выходом')
    print(f'{datetime.now().strftime("%Y-%m-%d %H:%M:%S")} Выход')
    fp_provider.close_channel()  # Закрываем канал перед выходом
    ap_provider.close_web_socket()  # Перед выходом закрываем соединение с WebSocket
    sys.exit(0)

# Регистрируем обработчик сигнала для корректного завершения
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

new_quotes = {}
def _on_new_quotes(response):
    # logger.info(f'Котировка - {response["data"]}')
    # Извлекаем данные
    description = response["data"]['description']
    ask = float(response["data"]['ask']) if response["data"]['ask'] else 0.0
    bid = float(response["data"]['bid']) if response["data"]['bid'] else 0.0
    last_price = float(response["data"]['last_price']) if response["data"]['last_price'] else 0.0

    # Сохраняем в словарь по описанию тикера
    new_quotes[description] = {
        'ask': ask,
        'bid': bid,
        'last_price': last_price
    }

    # print(f"Котировки для {description}: ask={ask}, bid={bid}, last_price={last_price}")

def _on_order(order): logger.info(f'Заявка - {order}')


trade_dict = {}
def _on_trade(trade):
    logger.info(f'Сделка - {trade}')
    # Извлекаем данные из объекта trade
    trade_id = trade.trade_id
    order_id = trade.order_id
    timestamp = trade.timestamp
    side = trade.side
    size = trade.size.value
    price = trade.price.value

    # Сохраняем данные в словарь по ключу trade_id
    trade_dict[trade_id] = {
        'timestamp': timestamp,
        'trade_id': trade_id,
        'order_id': order_id,
        'side': side,
        'size': size,
        'price': price
    }



# Выставление лимитной заявки на продажу инструмента symbol_sell в количестве quantity_sell
# по цене limit_price_sell. Возвращаем номер заявки order_id
def get_order_sell(account_id, symbol_sell, quantity_sell, limit_price_sell):
    order_state = fp_provider.call_function(
        fp_provider.orders_stub.PlaceOrder,
        Order(
            account_id=account_id,
            symbol=symbol_sell,
            quantity=Decimal(value=str(quantity_sell)),
            side=side.SIDE_SELL,
            type=OrderType.ORDER_TYPE_LIMIT,
            limit_price=Decimal(value=str(limit_price_sell)),
            client_order_id=str(int(datetime.now().timestamp()))
        )
    )
    logger.debug(order_state)
    order_id = order_state.order_id  # Номер заявки
    logger.info(f'Номер заявки: {order_id}')
    logger.info(f'Статус заявки: {order_state.status}')
    status = order_state.status
    return order_id, status

# Выставление лимитной заявки на покупку инструмента symbol_buy в количестве quantity_buy
# по цене limit_price_buy. Возвращаем номер заявки order_id_buy
def get_order_buy(account_id, symbol_buy, quantity_buy, limit_price_buy):
    order_state = fp_provider.call_function(
        fp_provider.orders_stub.PlaceOrder,
        Order(
            account_id=account_id,
            symbol=symbol_buy,
            quantity=Decimal(value=str(quantity_buy)),
            side=side.SIDE_BUY,
            type=OrderType.ORDER_TYPE_LIMIT,
            limit_price=Decimal(value=str(limit_price_buy)),
            client_order_id=str(int(datetime.now().timestamp()))
        )
    )
    logger.debug(order_state)
    order_id_buy = order_state.order_id  # Номер заявки
    status_buy = order_state.status
    logger.info(f'Номер заявки: {order_id_buy}')
    logger.info(f'Статус заявки: {order_state.status}')
    return order_id_buy, status_buy

# Удаление существующей лимитной заявки
def get_cancel_order(account_id, order_id):
    logger.info(f'Удаление заявки: {order_id}')
    order_state: OrderState = fp_provider.call_function(fp_provider.orders_stub.CancelOrder,
                                                        CancelOrderRequest(account_id=account_id,
                                                                           order_id=order_id))  # Удаление заявки
    logger.debug(order_state)
    logger.info(f'Статус заявки: {order_state.status}')
    return order_state.status

# Получаем данные портфеля брокера Финам в словарь portfolio_positions_finam
def get_portfolio_positions():
    portfolio_positions_finam = {}
    try:
        broker = brokers['Ф']  # Брокер по ключу из Config.py словаря brokers
        if broker is None:
            print("Ошибка: брокер не инициализирован")
            return []
        positions = broker.get_positions()  # Пробегаемся по всем позициям брокера
        if positions is None:
            print(f"Ошибка: не удалось получить позиции")
            return []
        for position in positions:  # Пробегаемся по всем позициям брокера
            # Проверяем, что позиция не равна 0
            if position.quantity != 0 or position.quantity != None:
                portfolio_positions_finam[position.dataname] = {
                    'dataname': position.dataname,
                    'net_pos': int(float(position.quantity)),
                    'price_pos': float(position.current_price)
                }
            else:
                print(f"Ошибка: не удалось получить позицию {position.dataname}")
                # Остановка программы
                sys.exit(1)

        return portfolio_positions_finam
    except Exception as e:
        print(f"Ошибка получения позиций: {e}")
        return []

# Вычисление стоимости опциона по формуле Black-Scholes
def option_price(S, sigma, K, T, r: float, opt_type):
    d1 = (math.log(S / K) + (r + .5 * sigma ** 2) * T) / (sigma * T ** .5)
    d2 = d1 - sigma * T ** 0.5
    price = 0
    if opt_type == CALL:
        n1 = norm.cdf(d1)
        n2 = norm.cdf(d2)
        DF = math.exp(-r * T)
        price = S * n1 - K * DF * n2
    elif opt_type == PUT:
        n1 = norm.cdf(-d1)
        n2 = norm.cdf(-d2)
        DF = math.exp(-r * T)
        price = K * DF * n2 - S * n1
    return price


# Сбор данных опциона CALL для расчета IV
def option_data_for_IV_calculation_call(dataname, price_call):
    # S: последняя цена БА из обновляемого словаря new_quotes
    # K: strike price
    # T: time to maturity
    # C: Call value
    # r: interest rate
    # sigma: volatility of underlying asset
    base_asset_ticker = opions_data[dataname]['base_asset_ticker']
    S = float(new_quotes[base_asset_ticker]['last_price'])
    K = float(opions_data[dataname]['strikePrice'])
    expiration_datetime = opions_data[dataname]['endExpiration']
    expiration_dt = datetime.fromisoformat(expiration_datetime.replace('Z', '+00:00'))
    T_razn = (expiration_dt - datetime.today()).days
    T = float((T_razn + 1.151) / 365)
    C = price_call
    sigma = opions_data[dataname]['volatility'] / 100

    return S, K, T, C, sigma

# Сбор данных опциона PUT для расчета IV
def option_data_for_IV_calculation_put(dataname, price_put):
    # S: последняя цена БА из обновляемого словаря new_quotes
    # K: strike price
    # T: time to maturity
    # P: Put value
    # r: interest rate
    # sigma: volatility of underlying asset
    base_asset_ticker = opions_data[dataname]['base_asset_ticker']
    S = float(new_quotes[base_asset_ticker]['last_price'])
    K = float(opions_data[dataname]['strikePrice'])
    expiration_datetime = opions_data[dataname]['endExpiration']
    expiration_dt = datetime.fromisoformat(expiration_datetime.replace('Z', '+00:00'))
    T_razn = (expiration_dt - datetime.today()).days
    T = float((T_razn + 1.151) / 365)
    P = price_put
    sigma = opions_data[dataname]['volatility'] / 100

    return S, K, T, P, sigma

# Расчет IV Метод Ньютона для опциона CALL
def newton_vol_call(S, K, T, C, r, sigma):
    # S: spot price
    # K: strike price
    # T: time to maturity
    # C: Call value
    # r: interest rate
    # sigma: volatility of underlying asset

    tolerance = 0.000001
    max_iterations = 100
    x0 = sigma
    xnew = x0
    xold = x0 - 1
    iteration = 0

    while abs(xnew - xold) > tolerance and iteration < max_iterations:
        xold = xnew

        d1 = (np.log(S / K) + (r - 0.5 * xnew ** 2) * T) / (xnew * np.sqrt(T))
        d2 = d1 - xnew * np.sqrt(T)

        fx = S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2) - C
        vega = S * np.sqrt(T) * np.exp(-0.5 * d1 ** 2) / np.sqrt(2 * np.pi)

        if abs(vega) < 1e-10:  # Избегаем деления на ноль
            break

        xnew = xnew - fx / vega
        iteration += 1

    return abs(xnew)


# Расчет IV Метод Ньютона для опциона PUT
def newton_vol_put(S, K, T, P, r, sigma):
    # S: spot price
    # K: strike price
    # T: time to maturity
    # P: Put value
    # r: interest rate
    # sigma: volatility of underlying asset

    tolerance = 0.000001
    max_iterations = 100
    x0 = sigma
    xnew = x0
    xold = x0 - 1
    iteration = 0

    while abs(xnew - xold) > tolerance and iteration < max_iterations:
        xold = xnew

        d1 = (np.log(S / K) + (r - 0.5 * xnew ** 2) * T) / (xnew * np.sqrt(T))
        d2 = d1 - xnew * np.sqrt(T)

        fx = K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1) - P
        vega = S * np.sqrt(T) * np.exp(-0.5 * d1 ** 2) / np.sqrt(2 * np.pi)

        if abs(vega) < 1e-10:  # Избегаем деления на ноль
            break

        xnew = xnew - fx / vega
        iteration += 1

    return abs(xnew)


# Получение последней котировки по инструменту
def get_last_quotes(symbol):
    quote_response: QuoteResponse = fp_provider.call_function(fp_provider.marketdata_stub.LastQuote,
                                                              QuoteRequest(symbol=symbol))
    # print(f'quote_response {quote_response}')
    ask = float(quote_response.quote.ask.value)  # Последняя цена продажи
    bid = float(quote_response.quote.bid.value)  # Последняя цена покупки
    last_price = float(quote_response.quote.last.value)  # Последняя цена сделки
    theoretical_price = float(quote_response.quote.option.theoretical_price.value)  # Теоретическая цена
    implied_volatility = float(quote_response.quote.option.implied_volatility.value)  # Волатильность
    # print(f'Последние котировки по инструменту {symbol}: ask:{ask} bid:{bid} last_price:{last_price} theoretical_price:{theoretical_price} volatility:{implied_volatility}')
    return ask, bid, last_price, theoretical_price, implied_volatility


if __name__ == '__main__':  # Точка входа при запуске этого скрипта
    print(f'{datetime.now().strftime("%Y-%m-%d %H:%M:%S")} Старт MyQuoteRobot.py')

    logger = logging.getLogger('FinamPy.MyQuoteRobot')  # Будем вести лог
    fp_provider = FinamPy()  # Подключаемся ко всем торговым счетам
    ap_provider = AlorPy()  # Подключаемся ко всем торговым счетам
    # Подписываемся на события
    ap_provider.on_new_quotes.subscribe(_on_new_quotes)
    # Список GUID для отписки

    # Исходные данные
    dataname_buy = 'SPBOPT.RI97500BO6'  # Option BUY
    dataname_sell = 'SPBOPT.RI127500BC6'  # Option SELL
    expected_profit = 1 # Ожидаемый profit в %
    sleep_time = 5  # Время ожидания в секундах
    Lot_count = 1 # Количество лотов
    Lot_count_step = 0
    Timeout = 5 # Срок действия ордера в секундах

    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  # Формат сообщения
                        datefmt='%d.%m.%Y %H:%M:%S',  # Формат даты
                        level=logging.INFO,  # Уровень логируемых событий NOTSET/DEBUG/INFO/WARNING/ERROR/CRITICAL
                        handlers=[logging.FileHandler('MyQuoteRobot.log', encoding='utf-8'),
                                  logging.StreamHandler()])  # Лог записываем в файл и выводим на консоль
    logging.Formatter.converter = lambda *args: datetime.now(
        tz=fp_provider.tz_msk).timetuple()  # В логе время указываем по МСК

    # Получаем данные по опционам, подписываемся на котировки для каждого тикера
    opions_data = {}
    for dataname in [dataname_buy, dataname_sell]:
        try:
            alor_board, symbol = ap_provider.dataname_to_alor_board_symbol(dataname)  # Код режима торгов Алора и код и тикер
            exchange = ap_provider.get_exchange(alor_board, symbol)  # Код биржи
            si = ap_provider.get_symbol_info(exchange, symbol)  # Получаем информацию о тикере
            # print(si)
            # Создаем словарь для опционов
            opions_data[dataname] = {
                'ticker': si['shortname'],
                'theorPrice': si['theorPrice'],
                'volatility': float(si['volatility']),
                'strikePrice': float(si['strikePrice']),
                'endExpiration': si['endExpiration'],
                'base_asset_ticker': si['underlyingSymbol'],
                'optionSide': si['optionSide'],
                'lot_size': si['lotsize'],
                'minstep': si['minstep'],
                'decimals': si['decimals']
            }
            guid = ap_provider.quotes_subscribe(exchange, symbol)  # Получаем код подписки
            guids.append(guid)
            logger.info(f'Подписка на котировки {guid} тикера {dataname} создана')
        except Exception as e:
            print(f"Ошибка получения данных по тикеру {dataname}: {e}")
            continue
    # print(f'opions_data {opions_data}')

    # Из словаря opions_data получить все значения 'base_asset_ticker' занести в список base_asset_tickers, удалить дубликаты
    base_asset_tickers = list(set(option_data['base_asset_ticker'] for option_data in opions_data.values()))
    # Получаем данные по базовому активу, подписываемся на котировки для каждого тикера
    for ba_tiker in base_asset_tickers:
        alor_board, symbol = ap_provider.dataname_to_alor_board_symbol(ba_tiker)  # Код режима торгов Алора и код и тикер
        exchange = ap_provider.get_exchange(alor_board, symbol)  # Код биржи
        guid = ap_provider.quotes_subscribe(exchange, symbol)  # Получаем код подписки
        guids.append(guid)
        logger.info(f'Подписка на котировки {guid} тикера {ba_tiker} создана')

    # Свои заявки и сделки
    fp_provider.on_order.subscribe(_on_order)  # Подписываемся на заявки
    fp_provider.on_trade.subscribe(_on_trade)  # Подписываемся на сделки
    Thread(target=fp_provider.subscribe_orders_thread,
           name='SubscriptionOrdersThread').start()  # Создаем и запускаем поток обработки своих заявок
    Thread(target=fp_provider.subscribe_trades_thread,
           name='SubscriptionTradesThread').start()  # Создаем и запускаем поток обработки своих сделок
    sleep(1)  # Ждем 1 секунду

    # Начинаем бесконечный цикл с этого места
    try:
        while running:
            # Обновление позиций/тикеров портфеля
            positions = get_portfolio_positions()
            # print(positions)

            print(f'\n Параметры опциона BUY {dataname_buy}. Откупаем проданный опцион.')
            # Параметры опциона на покупку BUY (откупаем проданный опцион)
            dataname = dataname_buy
            finam_board, ticker = fp_provider.dataname_to_finam_board_ticker(dataname)  # Код режима торгов Финама и тикер
            mic = fp_provider.get_mic(finam_board, ticker)  # Биржа тикера
            symbol = f'{ticker}@{mic}'  # Тикер Финама
            symbol_buy = symbol
            net_pos = positions[dataname]['net_pos'] if dataname in positions else 0  # Количество в позиции
            if net_pos != 0:
                open_data_result = calculate_open_data_open_price_open_iv(ticker, net_pos)  # Вычисление OpenDateTime, OpenPrice, OpenIV
            else:
                print(f'Нет данных о позиции {dataname} количество {net_pos}')
                # Завершаем работу программы
                running = False
                # Вызываем сигнал для корректного завершения
                signal.raise_signal(signal.SIGTERM)
            # Проверяем, что функция вернула корректные данные
            if open_data_result is not None and len(open_data_result) > 2:
                open_datetime = open_data_result[0]
                open_price = open_data_result[1] if open_data_result[1] is not None else 0.0
                open_iv = open_data_result[2] if open_data_result[2] is not None else 0.0
            else:
                open_datetime = ""
                open_price = 0.0
                open_iv = 0.0
            account_id = fp_provider.account_ids[0]  # Торговый счет, где будут выставляться заявки
            quantity_buy = opions_data[dataname]['lot_size']  # Количество в шт
            # print(f'Количество в шт quantity: {quantity}')
            step_price = int(float(opions_data[dataname]['minstep']))  # Минимальный шаг цены
            # print(f'Минимальный шаг цены step_price: {step_price}')
            print(f'Количество проданных {ticker} в шт: {net_pos}')
            print(f'Open IV: {round(open_iv, 2)}')
            open_iv_buy = open_iv
            profit_iv_buy = open_iv - expected_profit
            print(f'Profit IV buy: {round(profit_iv_buy, 2)}')
            theoretical_price_buy = opions_data[dataname]['theorPrice']
            base_asset_ticker = opions_data[dataname]['base_asset_ticker']
            # Проверяем наличие котировок для базового актива
            if base_asset_ticker not in new_quotes:
                print(f'Нет котировок для базового актива {base_asset_ticker}')
                sleep(5)
                continue
            S = float(new_quotes[base_asset_ticker]['last_price'])
            # print(f'S: {S}')
            # sigma = opions_data[dataname]['volatility'] / 100
            sigma = profit_iv_buy / 100
            # print(f'Sigma: {sigma}')
            K = float(opions_data[dataname]['strikePrice'])
            # print(f'K: {K}')
            expiration_datetime = opions_data[dataname]['endExpiration']
            # print(f'Expiration datetime: {expiration_datetime}')
            expiration_dt = datetime.fromisoformat(expiration_datetime.replace('Z', '+00:00'))
            T_razn = (expiration_dt - datetime.today()).days
            T = float((T_razn + 1.151) / 365)
            # print(f'T: {T}')
            option_type = CALL if opions_data[dataname]['optionSide'] == 'Call' else PUT
            # print(f'Option type: {option_type}')
            decimals = opions_data[dataname_sell]['decimals']
            # Далее вычисляем profit_price_buy из profit_iv_buy по формуле Блэка-Шоулза
            profit_price_buy = option_price(S, sigma, K, T, r, opt_type=option_type)
            limit_price = int(round((profit_price_buy // step_price) * step_price, decimals))
            profit_price_buy = int(round((profit_price_buy // step_price) * step_price, decimals))
            print(f'Profit_price_buy {profit_price_buy}')
            # Получаем ask, bid из потока котировок по подписке из обновляемого словаря new_quotes
            if ticker not in new_quotes:
                print(f'Нет котировок для тикера {ticker}')
                sleep(5)
                continue
            ask_buy = int(round(new_quotes[ticker]['ask'], decimals))
            bid_buy = int(round(new_quotes[ticker]['bid'], decimals))
            print(f'Котировки ask_buy {ask_buy} bid_buy {bid_buy}')
            # Вычисляем волатильность ask_buy
            # print(f'{S}, {K}, {T}, {ask_buy}, {r}, {sigma} {option_type}')
            if option_type == 'C':
                sigma = opions_data[dataname]['volatility'] / 100
                ask_iv_buy = newton_vol_call(S, K, T, ask_buy, r, sigma) * 100
                bid_iv_buy = newton_vol_call(S, K, T, bid_buy, r, sigma) * 100
            else:
                sigma = opions_data[dataname]['volatility'] / 100
                ask_iv_buy = newton_vol_put(S, K, T, ask_buy, r, sigma) * 100
                bid_iv_buy = newton_vol_put(S, K, T, bid_buy, r, sigma) * 100
            print(f'Волатильность ask_iv_buy: {round(ask_iv_buy, 2)} bid_iv_buy: {round(bid_iv_buy, 2)}')
            saldo_buy = open_iv_buy - opions_data[dataname]['volatility'] # open_iv - IV-theor
            print(f'Saldo buy: {round(saldo_buy, 2)}')


            print(f'\n Параметры опциона SELL {dataname_sell}. Продаём купленный опцион.')
            # Параметры опциона на продажу SELL (продаем купленный опцион)
            dataname = dataname_sell
            finam_board, ticker = fp_provider.dataname_to_finam_board_ticker(dataname)  # Код режима торгов Финама и тикер
            mic = fp_provider.get_mic(finam_board, ticker)  # Биржа тикера
            symbol = f'{ticker}@{mic}'  # Тикер Финама
            symbol_sell = symbol
            net_pos = positions[dataname]['net_pos'] if dataname in positions else 0  # Количество в позиции
            if net_pos != 0:
                open_data_result = calculate_open_data_open_price_open_iv(ticker, net_pos)  # Вычисление OpenDateTime, OpenPrice, OpenIV
            else:
                print(f'Нет данных о позиции {dataname} количество {net_pos}')
                # Завершаем работу программы
                running = False
                # Вызываем сигнал для корректного завершения
                signal.raise_signal(signal.SIGTERM)
            # Проверяем, что функция вернула корректные данные
            if open_data_result is not None and len(open_data_result) > 2:
                open_datetime = open_data_result[0]
                open_price = open_data_result[1] if open_data_result[1] is not None else 0.0
                open_iv = open_data_result[2] if open_data_result[2] is not None else 0.0
            else:
                open_datetime = ""
                open_price = 0.0
                open_iv = 0.0
            account_id = fp_provider.account_ids[0]  # Торговый счет, где будут выставляться заявки
            quantity_sell = opions_data[dataname]['lot_size']  # Количество в шт
            # print(f'Количество в шт quantity: {quantity_sell}')
            step_price = int(float(opions_data[dataname]['minstep']))  # Минимальный шаг цены
            # print(f'Минимальный шаг цены step_price: {step_price}')
            print(f'Количество купленных {ticker} в шт: {net_pos}')
            print(f'Open IV: {round(open_iv, 2)}')
            open_iv_sell = open_iv
            profit_iv_sell = open_iv + expected_profit
            print(f'Profit IV sell: {round(profit_iv_sell, 2)}')
            theoretical_price_sell = opions_data[dataname]['theorPrice']
            base_asset_ticker = opions_data[dataname]['base_asset_ticker']
            # Проверяем наличие котировок для базового актива
            if base_asset_ticker not in new_quotes:
                print(f'Нет котировок для базового актива {base_asset_ticker}')
                sleep(5)
                continue
            S = float(new_quotes[base_asset_ticker]['last_price'])
            # print(f'S: {S}')
            # sigma = opions_data[dataname]['volatility'] / 100 # Для проверки теорцены
            sigma = profit_iv_sell / 100
            # print(f'Sigma: {sigma}')
            K = float(opions_data[dataname]['strikePrice'])
            # print(f'K: {K}')
            expiration_datetime = opions_data[dataname]['endExpiration']
            # print(f'Expiration datetime: {expiration_datetime}')
            expiration_dt = datetime.fromisoformat(expiration_datetime.replace('Z', '+00:00'))
            T_razn = (expiration_dt - datetime.today()).days
            T = float((T_razn + 1.151) / 365)
            # print(f'T: {T}')
            option_type = CALL if opions_data[dataname]['optionSide'] == 'Call' else PUT
            # print(f'Option type: {option_type}')
            decimals = opions_data[dataname_sell]['decimals']
            # Далее вычисляем profit_price_sell из profit_iv_sell по формуле Блэка-Шоулза
            profit_price_sell = option_price(S, sigma, K, T, r, opt_type=option_type)
            profit_price_sell = int(round(profit_price_sell, decimals))
            limit_price_sell = int(round((profit_price_sell // step_price) * step_price, decimals))
            profit_price_sell = int(round((profit_price_sell // step_price) * step_price, decimals))
            print(f'Profit_price_sell {profit_price_sell}')
            # Получаем ask, bid из потока котировок по подписке из обновляемого словаря new_quotes
            if ticker not in new_quotes:
                print(f'Нет котировок для тикера {ticker}')
                sleep(5)
                continue
            ask_sell = int(round(new_quotes[ticker]['ask'], decimals))
            bid_sell = int(round(new_quotes[ticker]['bid'], decimals))
            print(f'Котироки ask_sell: {ask_sell} bid_sell: {bid_sell}')
            # Вычисляем волатильность ask_sell
            # print(f'{S}, {K}, {T}, {ask_sell}, {r}, {sigma} {option_type}')
            if option_type == 'C':
                sigma = opions_data[dataname]['volatility'] / 100
                ask_iv_sell = newton_vol_call(S, K, T, ask_sell, r, sigma) * 100
                bid_iv_sell = newton_vol_call(S, K, T, bid_sell, r, sigma) * 100
            else:
                sigma = opions_data[dataname]['volatility'] / 100
                ask_iv_sell = newton_vol_put(S, K, T, ask_sell, r, sigma) * 100
                bid_iv_sell = newton_vol_put(S, K, T, bid_sell, r, sigma) * 100
            print(f'Волатильность ask_sell: {round(ask_iv_sell, 2)} bid_iv_sell: {round(bid_iv_sell, 2)}')
            saldo_sell = opions_data[dataname]['volatility'] - open_iv # IV-theor - open_iv
            print(f'Saldo sell: {round(saldo_sell, 2)}')

            Real_profit_sell = round((ask_iv_sell - open_iv_sell) + (open_iv_buy - ask_iv_buy), 2)
            Real_profit_buy = round((open_iv_buy - bid_iv_buy) + (bid_iv_sell - open_iv_sell), 2)


            print(f'\n')
            print(f'Выставление заявок:')

            if saldo_sell >= saldo_buy: # Если прибыльная нога - SELL
                print(f'\n')
                print(f'Лучшая нога - на продажу! Real profit sell: {Real_profit_sell}')
                if Real_profit_sell >= expected_profit:  # Если реальный профит больше или равен ожидаемому профиту
                    print(f'Если реальный профит {Real_profit_sell} больше или равен ожидаемому профиту {expected_profit}')
                    # Новая лимитная заявка на продажу
                    # limit_price_sell = ask_sell - step_price  # Ставим лимитную цену на шаг ниже лучшей продажи
                    # limit_price_sell = ask_sell - step_price # Test
                    limit_price_sell = bid_sell  # По рынку
                    print(f'Выставляем лимитную заявку по цене {limit_price_sell} - на шаг ниже лучшей продажи опциона: {dataname_sell}. Ждём sleep_time.')
                    # Вызов функции выставления заявки на продажу
                    order_id, status = get_order_sell(
                        account_id=account_id,  # Укажите реальный номер счета
                        symbol_sell=symbol_sell,  # Укажите реальный тикер
                        quantity_sell=quantity_sell,  # Укажите количество
                        limit_price_sell=limit_price_sell  # Укажите цену
                    )
                    print(f'Заявка на продажу выставлена: {order_id}, статус: {status} ')
                    sleep(Timeout)
                    # Перебор позиций словаря trade_dict
                    for trade_id, trade_data in trade_dict.items():
                        if trade_data and trade_data['order_id'] == order_id:
                            print(f"ID сделки: {trade_id}")
                            print(f"Время: {trade_data['timestamp']}")
                            print(f"Цена: {trade_data['price']}")
                            print(f"Объем: {trade_data['size']}")

                            limit_price_buy = ask_buy  # Test
                            print(f'Выставляем лимитную заявку на покупку опциона {dataname_buy} по цене {limit_price_buy}')
                            # Вызов функции выставления заявки на покупку
                            order_id_buy, status_buy = get_order_buy(
                                account_id=account_id,  # Укажите реальный номер счета
                                symbol_buy=symbol_buy,  # Укажите реальный тикер
                                quantity_buy=quantity_buy,  # Укажите количество
                                limit_price_buy=limit_price_buy  # Укажите цену
                            )
                            print(f'Заявка на покупку выставлена: order_id_buy {order_id_buy}, status {status_buy}')
                            print(trade_dict)
                            sleep(Timeout)
                            for trade_id, trade_data in trade_dict.items():
                                if trade_data and trade_data['order_id'] == order_id_buy:
                                    print(f"ID сделки: {trade_id}")
                                    print(f"Время: {trade_data['timestamp']}")
                                    print(f"Цена: {trade_data['price']}")
                                    print(f"Объем: {trade_data['size']}")
                                    print(f'Заявка на покупку исполнена: {trade_data['order_id']}')
                                    # running = False
                                # else:
                                #     print(f'Заявка на покупку не исполнена: {trade_data['order_id']}')
                                #     continue
                        # else:
                        #     print(f'Заявка на продажу не исполнена')
                        #     continue
                    else:
                        # Снятие заявки на продажу
                        get_cancel_order(account_id, order_id)
                        continue

        running = False
        # pass
    except Exception as e:
        print(f'Ошибка в цикле: {e}')
        sleep(1)
    except KeyboardInterrupt:
        print("Программа прервана пользователем")
        sys.exit(0)
    finally:
        print("Завершение программы")

    # Отписываемся от всех котировок
    for guid in guids:
        try:
            logger.info(f'Подписка на котировки {ap_provider.unsubscribe(guid)} отменена')
        except Exception as e:
            logger.error(f'Ошибка отписки: {e}')

    # Отмена подписок
    print(f'\n')
    print('Отмена подписок')
    fp_provider.on_order.unsubscribe(_on_order)  # Сбрасываем обработчик заявок
    fp_provider.on_trade.unsubscribe(_on_trade)  # Сбрасываем обработчик сделок
    ap_provider.on_new_quotes.unsubscribe(_on_new_quotes) # Отменяем подписку на события

    # Выход
    # print(f'new_quotes {new_quotes}')
    print('Закрываем канал перед выходом')
    print(f'{datetime.now().strftime("%Y-%m-%d %H:%M:%S")} Выход')
    fp_provider.close_channel()  # Закрываем канал перед выходом
    ap_provider.close_web_socket()  # Перед выходом закрываем соединение с WebSocket