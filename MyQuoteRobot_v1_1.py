from datetime import datetime  # Дата и время
from time import sleep  # Задержка в секундах перед выполнением операций
import logging  # Выводим лог на консоль и в файл
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


# Словарь для хранения данных по заявкам
orders_dict = {}
def _on_order(order):
    # logger.info(f'Заявка - {order}')
    # Преобразуем side в текстовую строку
    side_text = "Продажа" if order.order.side == 2 else "Купля"

    # Преобразуем статус в текстовую строку
    status_text = "Активна" if order.status == 1 else "Снята" if order.status == 5 else f"Статус {order.status}"

    # Не сохраняем снятые заявки (status == 5)
    if order.status != 5:
        # Сохраняем данные в словарь по ключу symbol (заменяет предыдущие данные)
        symbol = order.order.symbol
        orders_dict[symbol] = {
            'order_id': order.order_id,
            'side': side_text,
            'status': status_text,
            'quantity': order.order.quantity.value,
            'limit_price': order.order.limit_price.value
        }

    # print(f'Заявка - {order.order.symbol} {order.order_id} {side_text} {status_text} {order.order.quantity.value} {order.order.limit_price.value}')
    # print(orders_dict)


trade_dict = {}
def _on_trade(trade):
    # logger.info(f'Сделка - {trade}')
    # Сохраняем данные в словарь по ключу symbol (заменяет предыдущие данные)
    symbol = trade.symbol
    trade_dict[symbol] = {
        'timestamp': trade.timestamp.seconds,
        'trade_id': trade.trade_id,
        'order_id': trade.order_id,
        'side': trade.side,
        'size': trade.size.value,
        'price': trade.price.value
    }
    # print(f'trade_dict - {trade_dict}')
    # print(f'Сделка - {trade.symbol} {trade.side} {trade.size.value} {trade.price.value}')

# Получаем данные портфеля брокера Финам в список
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
    guids = []

    # Исходные данные
    dataname_buy = 'SPBOPT.RI97500BO6'  # Option BUY
    dataname_sell = 'SPBOPT.RI130000BC6'  # Option SELL
    expected_profit = 2 # Ожидаемый profit в %
    sleep_time = 5  # Время ожидания в секундах

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
                'minstep': si['minstep']
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
    sleep(1)  # Ждем 10 секунд

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
            print(f'Open IV: {open_iv}')
            open_iv_buy = open_iv
            profit_iv_buy = open_iv - expected_profit
            print(f'Profit IV buy: {profit_iv_buy}')
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
            # Далее вычисляем profit_price_buy из profit_iv_buy по формуле Блэка-Шоулза
            profit_price_buy = option_price(S, sigma, K, T, r, opt_type=option_type)
            limit_price = (profit_price_buy // step_price) * step_price
            profit_price_buy = (profit_price_buy // step_price) * step_price
            print(f'Profit_price_buy {profit_price_buy}')
            # Получаем ask, bid из потока котировок по подписке из обновляемого словаря new_quotes
            if ticker not in new_quotes:
                print(f'Нет котировок для тикера {ticker}')
                sleep(5)
                continue
            ask_buy = new_quotes[ticker]['ask']
            bid_buy = new_quotes[ticker]['bid']
            print(f'Котировки ask {ask_buy} bid {bid_buy}')
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
            print(f'Волатильность ask_iv_buy: {ask_iv_buy} bid_iv_buy: {bid_iv_buy}')
            saldo_buy = open_iv - opions_data[dataname]['volatility'] # open_iv - IV-theor
            print(f'Saldo buy: {saldo_buy}')


            print(f'\n Параметры опциона SELL {dataname_sell}. Продаём купленный опцион.')
            # Параметры опциона на продажу SELL (продаем купленный опцион)
            dataname = dataname_sell
            finam_board, ticker = fp_provider.dataname_to_finam_board_ticker(dataname)  # Код режима торгов Финама и тикер
            mic = fp_provider.get_mic(finam_board, ticker)  # Биржа тикера
            symbol = f'{ticker}@{mic}'  # Тикер Финама
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
            # print(f'Количество в шт quantity: {quantity}')
            step_price = int(float(opions_data[dataname]['minstep']))  # Минимальный шаг цены
            # print(f'Минимальный шаг цены step_price: {step_price}')
            print(f'Количество купленных {ticker} в шт: {net_pos}')
            print(f'Open IV: {open_iv}')
            open_iv_sell = open_iv
            profit_iv_sell = open_iv + expected_profit
            print(f'Profit IV sell: {profit_iv_sell}')
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
            # Далее вычисляем profit_price_sell из profit_iv_sell по формуле Блэка-Шоулза
            profit_price_sell = option_price(S, sigma, K, T, r, opt_type=option_type)
            limit_price = (profit_price_sell // step_price) * step_price
            profit_price_sell = (profit_price_sell // step_price) * step_price
            print(f'Profit_price_sell {profit_price_sell}')
            # Получаем ask, bid из потока котировок по подписке из обновляемого словаря new_quotes
            if ticker not in new_quotes:
                print(f'Нет котировок для тикера {ticker}')
                sleep(5)
                continue
            ask_sell = new_quotes[ticker]['ask']
            bid_sell = new_quotes[ticker]['bid']
            print(f'Котироки ask: {ask_sell} bid: {bid_sell}')
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
            print(f'Волатильность ask_sell: {ask_iv_sell} bid_iv_sell: {bid_iv_sell}')
            saldo_sell = opions_data[dataname]['volatility'] - open_iv # IV-theor - open_iv
            print(f'Saldo sell: {saldo_sell}')

            Real_profit_sell = (ask_iv_sell - open_iv_sell) + (open_iv_buy - ask_iv_buy)
            Real_profit_buy = (open_iv_buy - bid_iv_buy) + (bid_iv_sell - open_iv_sell)


            print(f'\n')
            print(f'Выставление заявок:')
            if saldo_sell >= saldo_buy: # Если прибыльная нога - SELL
                print(f'\n')
                print(f'Лучшая нога - на продажу! Real profit sell: {Real_profit_sell}')
                if Real_profit_sell >= expected_profit: # Если реальный профит больше или равен ожидаемому профиту
                    print(f'Если реальный профит {Real_profit_sell} больше или равен ожидаемому профиту {expected_profit}')
                    limit_price_sell = ask_sell - step_price # Ставим лимитную цену на шаг ниже лучшей продажи
                    print(f'Выставляем лимитную заявку по цене на шаг ниже лучшей продажи: {limit_price_sell} опциона {dataname_sell}. Ждём sleep_time.')
                    # Здесь должна быть логика для выставления лимитной заявки на продажу опциона dataname_sell
                    sleep(sleep_time)
                    print(f'Если сделка на продажу опциона {dataname_sell} совершилась, переходим к покупке опциона {dataname_buy}')
                    # Здесь должна быть логика подтверждения сделки на продажу опциона dataname_sell
                    limit_price_buy = ask_buy  # Фиксируем цену покупки
                    print(f'Выставляем лимитную заявку на покупку по цене {limit_price_buy} опциона {dataname_buy}')
                    # Здесь должна быть логика для выставления лимитной заявки на покупку опциона dataname_buy

                    print(f'Если сделка на продажу опциона {dataname_sell} за время sleep_time не совершилась, удаляем существующую лимитную заявку, завершаем цикл, идём в начало цикла.')
                    # Здесь должна быть логика для удаления существующей лимитной заявки на продажу опциона dataname_sell и выхода в начало цикла.
                    # if условие:
                    #     continue # переход в начало цикла

                else:
                    print(f'Реальный профит {Real_profit_sell} меньше ожидаемого профита {expected_profit}. Ждём sleep_time, завершаем цикл, идём в начало цикла.')
                    sleep(sleep_time)
                    continue
            else: # Если прибыльная нога - BUY
                print(f'\n')
                print(f'Лучшая нога - на покупку! Real profit buy: {Real_profit_buy}')
                if Real_profit_buy >= expected_profit:  # Если реальный профит больше или равен ожидаемому профиту
                    print(f'Если реальный профит {Real_profit_buy} больше или равен ожидаемому профиту {expected_profit}')
                    limit_price_buy = bid_buy + step_price  # Ставим лимитную цену на шаг выше лучшей покупки
                    print(f'Выставляем лимитную заявку по цене на шаг выше лучшей покупки: {limit_price_buy} опциона {dataname_buy}. Ждём sleep_time.')
                    # Здесь должна быть логика для выставления лимитной заявки на покупку опциона dataname_buy
                    sleep(sleep_time)
                    print(f'Если сделка на покупку опциона {dataname_buy} совершилась, переходим к продаже опциона {dataname_sell}')
                    # Здесь должна быть логика подтверждения сделки на покупку опциона dataname_buy
                    limit_price_sell = ask_sell  # Фиксируем цену продажи
                    print(f'Выставляем лимитную заявку на продажу по цене {limit_price_sell} опциона {dataname_sell}.')
                    # Здесь должна быть логика для выставления лимитной заявки на продажу опциона dataname_sell

                    print(f'Если сделка на покупку опциона {dataname_buy} за время sleep_time не совершилась, удаляем существующую лимитную заявку, завершаем цикл, идём в начало цикла.')
                    # Здесь должна быть логика для удаления существующей лимитной заявки на покупку опциона dataname_buy и выхода в начало цикла.
                    # if условие:
                    #     continue # переход в начало цикла

                else:
                    print(f'Реальный профит {Real_profit_buy} меньше ожидаемого профита {expected_profit}. Ждём sleep_time, завершаем цикл, идём в начало цикла.')
                    sleep(sleep_time)
                    continue

            sleep(sleep_time)
        pass
    except Exception as e:
        print(f'Ошибка в цикле: {e}')
        sleep(1)
    except KeyboardInterrupt:
        print("Программа прервана пользователем")
        sys.exit(0)
    finally:
        print("Завершение программы")

    # # Новая лимитная заявка на покупку
    # limit_price = round(last_price * 0.9, si.decimals)  # Лимитная цена на 10% ниже последней цены сделки
    # logger.info(f'Заявка на покупку минимального лота {quantity} шт. {dataname} по лимитной цене {limit_price}')
    # order_state: OrderState = fp_provider.call_function(
    #     fp_provider.orders_stub.PlaceOrder,
    #     Order(account_id=account_id, symbol=symbol, quantity=quantity, side=side.SIDE_BUY, type=OrderType.ORDER_TYPE_LIMIT,
    #           limit_price=Decimal(value=str(limit_price)), client_order_id=str(int(datetime.now().timestamp())))
    # )  # Выставление заявки
    # logger.debug(order_state)
    # order_id = order_state.order_id  # Номер заявки
    # logger.info(f'Номер заявки: {order_id}')
    # logger.info(f'Статус заявки: {order_state.status}')
    #
    # sleep(5)  # Ждем 5 секунд

    # # Удаление существующей лимитной заявки
    # logger.info(f'Удаление заявки: {order_id}')
    # order_state: OrderState = fp_provider.call_function(fp_provider.orders_stub.CancelOrder, CancelOrderRequest(account_id=account_id, order_id=order_id))  # Удаление заявки
    # logger.debug(order_state)
    # logger.info(f'Статус заявки: {order_state.status}')

    # sleep(10)  # Ждем 10 секунд

    # Новая рыночная заявка на покупку (открытие позиции)
    # logger.info(f'Заявка {symbol} на покупку минимального лота {quantity} шт. по рыночной цене')
    # order_state: OrderState = fp_provider.call_function(
    #     fp_provider.orders_stub.PlaceOrder,
    #     Order(account_id=account_id, symbol=symbol, quantity=quantity, side=side.SIDE_BUY, type=OrderType.ORDER_TYPE_MARKET,
    #           client_order_id=str(int(datetime.now().timestamp())))
    # )  # Выставление заявки
    # logger.debug(order_state)
    # logger.info(f'Номер заявки: {order_state.order_id}')
    # logger.info(f'Номер исполнения заявки: {order_state.exec_id}')
    # logger.info(f'Статус заявки: {order_state.status}')
    #
    # sleep(10)  # Ждем 10 секунд

    # Новая рыночная заявка на продажу (закрытие позиции)
    # logger.info(f'Заявка {symbol} на продажу минимального лота {quantity} шт. по рыночной цене')
    # order_state: OrderState = fp_provider.call_function(
    #     fp_provider.orders_stub.PlaceOrder,
    #     Order(account_id=account_id, symbol=symbol, quantity=quantity, side=side.SIDE_SELL, type=OrderType.ORDER_TYPE_MARKET,
    #           client_order_id=str(int(datetime.now().timestamp())))
    # )  # Выставление заявки
    # logger.debug(order_state)
    # logger.info(f'Номер заявки: {order_state.order_id}')
    # logger.info(f'Номер исполнения заявки: {order_state.exec_id}')
    # logger.info(f'Статус заявки: {order_state.status}')
    #
    # sleep(10)  # Ждем 10 секунд


    # # Новая стоп заявка на покупку
    # stop_price = round(last_price * 1.01, si.decimals)  # Стоп цена на 1% выше последней цены сделки
    # logger.info(f'Заявка на покупку минимального лота {quantity} шт. {dataname} по стоп цене {stop_price}')
    # order_state: OrderState = fp_provider.call_function(
    #     fp_provider.orders_stub.PlaceOrder,
    #     Order(account_id=account_id, symbol=symbol, quantity=quantity, side=side.SIDE_BUY, type=OrderType.ORDER_TYPE_STOP,
    #           stop_price=Decimal(value=str(stop_price)), stop_condition=StopCondition.STOP_CONDITION_LAST_UP, client_order_id=str(int(datetime.now().timestamp())))
    # )  # Выставление заявки
    # logger.debug(order_state)
    # order_id = order_state.order_id  # Номер заявки
    # logger.info(f'Номер заявки: {order_id}')
    # logger.info(f'Статус заявки: {order_state.status}')

    # sleep(10)  # Ждем 10 секунд

    # # Удаление существующей стоп заявки
    # logger.info(f'Удаление стоп заявки: {order_id}')
    # order_state: OrderState = fp_provider.call_function(fp_provider.orders_stub.CancelOrder, CancelOrderRequest(account_id=account_id, order_id=order_id))  # Удаление заявки
    # logger.debug(order_state)
    # logger.info(f'Статус заявки: {order_state.status}')
    #
    # sleep(10)  # Ждем 10 секунд

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