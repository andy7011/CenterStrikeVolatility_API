import logging  # Выводим лог на консоль и в файл
from threading import Thread  # Запускаем поток подписки
from datetime import datetime  # Дата и время
from time import sleep  # Подписка на события по времени

from FinamPy import FinamPy
from FinamPy.grpc.marketdata.marketdata_service_pb2 import SubscribeQuoteResponse  # Котировки
from FinamPy.grpc.marketdata.marketdata_service_pb2 import SubscribeOrderBookResponse  # Стакан
from FinamPy.grpc.marketdata.marketdata_service_pb2 import SubscribeLatestTradesResponse  # Сделки
from FinLabPy.Config import brokers, default_broker  # Все брокеры и брокер по умолчанию

# Словарь для хранения данных котировок
quote_data = {}
# Словарь для хранения последних ненулевых значений опционов
last_option_data = {}
# Словарь для хранения предыдущих значений
previous_values = {}

def get_portfolio_positions():
    # Получаем данные портфеля брокера Финам в список
    portfolio_positions_finam = []
    try:
        broker = brokers['Ф']  # Брокер по ключу из Config.py словаря brokers
        for position in broker.get_positions():  # Пробегаемся по всем позициям брокера
            # Проверяем, что позиция принадлежит SPBOPT и не равна 0
            if position.dataname.split('.')[0] == 'SPBOPT' and position.quantity != 0:
                dataname = position.dataname
                portfolio_positions_finam.append(dataname)
        print(portfolio_positions_finam)
        return portfolio_positions_finam
    except Exception as e:
        print(f"Ошибка получения позиций: {e}")
        return []

def _on_quote(quote: SubscribeQuoteResponse):
    global quote_data, previous_values, last_option_data

    q = quote.quote[0]  # Получаем первую котировку

    symbol_with_exchange = q.symbol
    ticker = symbol_with_exchange.split('@')[0]

    # Извлекаем данные из ответа
    ask = float(q.ask.value) if q.HasField('ask') and q.ask.value else 0.0
    bid = float(q.bid.value) if q.HasField('bid') and q.bid.value else 0.0
    last = float(q.last.value) if q.HasField('last') and q.last.value else 0.0

    # Для опционов - сохраняем только ненулевые значения
    theoretical_price = float(q.option.theoretical_price.value) if q.HasField('option') and q.option.HasField(
        'theoretical_price') and q.option.theoretical_price.value else last_option_data.get('theoretical_price', 0.0)
    implied_volatility = float(q.option.implied_volatility.value) if q.HasField('option') and q.option.HasField(
        'implied_volatility') and q.option.implied_volatility.value else last_option_data.get('implied_volatility', 0.0)

    # Обновляем словарь последних значений только если есть новое ненулевое значение
    if q.HasField('option'):
        if q.option.HasField('theoretical_price') and q.option.theoretical_price.value:
            last_option_data['theoretical_price'] = theoretical_price
        if q.option.HasField('implied_volatility') and q.option.implied_volatility.value:
            last_option_data['implied_volatility'] = implied_volatility

    # Словарь для хранения только измененных значений
    changed_data = {}

    # Проверяем изменения и добавляем только измененные значения
    if ask != previous_values.get('ask', None) and ask != 0.0:
        changed_data['ask'] = ask
        previous_values['ask'] = ask

    if bid != previous_values.get('bid', None) and bid != 0.0:
        changed_data['bid'] = bid
        previous_values['bid'] = bid

    if last != previous_values.get('last', None) and last != 0.0:
        changed_data['last'] = last
        previous_values['last'] = last

    if theoretical_price != previous_values.get('theoretical_price', None) and theoretical_price != 0.0:
        changed_data['theoretical_price'] = theoretical_price
        previous_values['theoretical_price'] = theoretical_price

    if implied_volatility != previous_values.get('implied_volatility', None) and implied_volatility != 0.0:
        changed_data['implied_volatility'] = implied_volatility
        previous_values['implied_volatility'] = implied_volatility

    # Обновляем основной словарь только измененными значениями
    if changed_data:
        quote_data['ticker'] = ticker
        quote_data.update(changed_data)  # Обновляем данные в quote_data
        changed_data = {'ticker': ticker, **changed_data}
        print(f"Измененные данные changed_data: {changed_data}")
        print(f"Обновленные данные quote_data: {quote_data}")
        return changed_data, quote_data

    # Пример данных quote_data:
    # {'ticker': 'RI115000BC6', 'ask': 2710.0, 'bid': 2500.0, 'last': 2500.0, 'theoretical_price': 2690.0, 'implied_volatility': 22.91575}

def _on_order_book(order_book: SubscribeOrderBookResponse):
    logger.info(f'Стакан - {order_book.order_book[0] if len(order_book.order_book) > 0 else "Нет стакана"}')


def _on_latest_trades(latest_trade: SubscribeLatestTradesResponse):
    logger.info(f'Сделка - {latest_trade.trades[0] if len(latest_trade.trades) > 0 else "Нет сделки"}')


# # Здесь можно временно отключить логгер
# logger = logging.getLogger('FinamPy.Stream')
# logger.disabled = True  # Отключит конкретный логгер


if __name__ == '__main__':  # Точка входа при запуске этого скрипта
    logger = logging.getLogger('FinamPy.Stream')  # Будем вести лог
    fp_provider = FinamPy()  # Подключаемся ко всем торговым счетам

    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  # Формат сообщения
                        datefmt='%d.%m.%Y %H:%M:%S',  # Формат даты
                        level=logging.INFO,  # Уровень логируемых событий NOTSET/DEBUG/INFO/WARNING/ERROR/CRITICAL
                        handlers=[logging.FileHandler('Stream.log', encoding='utf-8'),
                                  logging.StreamHandler()])  # Лог записываем в файл и выводим на консоль
    logging.Formatter.converter = lambda *args: datetime.now(
        tz=fp_provider.tz_msk).timetuple()  # В логе время указываем по МСК

    dataname = 'SPBOPT.RI115000BC6'  # Тикер

    finam_board, ticker = fp_provider.dataname_to_finam_board_ticker(dataname)  # Код режима торгов Финама и тикер
    mic = fp_provider.get_mic(finam_board, ticker)  # Биржа тикера

    # Подписываемся на стакан и сделки один раз
    # fp_provider.on_order_book.subscribe(_on_order_book)  # Подписываемся на стакан
    # Thread(target=fp_provider.subscribe_order_book_thread, name='OrderBookThread', args=(f'{ticker}@{mic}',)).start()  # Создаем и запускаем поток подписки на стакан

    # fp_provider.on_latest_trades.subscribe(_on_latest_trades)  # Подписываемся на сделки
    # Thread(target=fp_provider.subscribe_latest_trades_thread, name='LatestTradesThread', args=(f'{ticker}@{mic}',)).start()  # Создаем и запускаем поток подписки на сделки

    # Бесконечный цикл с подпиской на котировки каждые 60 секунд
    while True:
        try:
            # Котировки
            sleep_secs = 60  # Кол-во секунд получения котировок
            logger.info(f'Секунд котировок: {sleep_secs}')

            # Обновление позиций/тикеров портфеля
            positions = get_portfolio_positions()
            if not positions:
                logger.warning("Не удалось получить позиции")
                sleep(sleep_secs / 10)
                continue

            # Создаем уникальную функцию для подписки
            def on_quote_handler(quote):
                _on_quote(quote)

            fp_provider.on_quote.subscribe(on_quote_handler)  # Подписываемся на котировки
            Thread(target=fp_provider.subscribe_quote_thread, name='QuoteThread',
                   args=((f'{ticker}@{mic}',),)).start()  # Создаем и запускаем поток подписки на котировки
            sleep(sleep_secs)  # Ждем кол-во секунд получения котировок
            fp_provider.on_quote.unsubscribe(on_quote_handler)  # Отменяем подписку на котировки


        except KeyboardInterrupt:
            # Прерывание цикла по Ctrl+C
            fp_provider.close_channel()  # Закрываем канал перед выходом
            break
        except Exception as e:
            logger.error(f"Ошибка в основном цикле: {e}")
            sleep(5)  # Ждем перед повторной попыткой
