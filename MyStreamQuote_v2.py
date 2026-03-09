import logging  # Выводим лог на консоль и в файл
import pandas as pd
from threading import Thread  # Запускаем поток подписки
from datetime import datetime  # Дата и время
from time import sleep  # Подписка на события по времени

from FinamPy import FinamPy
from FinamPy.grpc.marketdata.marketdata_service_pb2 import SubscribeQuoteResponse  # Котировки
from FinamPy.grpc.marketdata.marketdata_service_pb2 import SubscribeOrderBookResponse  # Стакан
from FinamPy.grpc.marketdata.marketdata_service_pb2 import SubscribeLatestTradesResponse  # Сделки
from FinLabPy.Config import brokers, default_broker  # Все брокеры и брокер по умолчанию

# Словарь для хранения данных котировок по тикерам
quote_data = {}
# Словарь для хранения последних ненулевых значений опционов по тикерам
last_option_data = {}
# Словарь для хранения предыдущих значений по тикерам
previous_values = {}
# Глобальный DataFrame для хранения котировок
quote_df = pd.DataFrame()


def update_quote_dataframe(quote_data):
    """
    Обновляет DataFrame на основе словаря quote_data
    """
    global quote_df

    # Преобразуем словарь в DataFrame
    data_list = []
    for ticker, values in quote_data.items():
        if isinstance(values, dict):  # Проверяем, что это словарь
            row = values.copy()
            row['ticker'] = ticker
            data_list.append(row)
        else:
            # Если это не словарь, создаем пустую строку с тикером
            data_list.append({'ticker': ticker})

    # Создаем новый DataFrame
    new_df = pd.DataFrame(data_list)
    if not new_df.empty:
        new_df.set_index('ticker', inplace=True)
    else:
        new_df = pd.DataFrame()

    # Обновляем глобальный DataFrame
    quote_df = new_df

    return quote_df

# Получаем данные портфеля брокера Финам в список
def get_portfolio_positions():
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


def _on_quote(quote: SubscribeQuoteResponse, ticker: str):
    global quote_data, previous_values, last_option_data

    try:
        # Проверяем, есть ли котировки в ответе
        if not quote.quote:
            return  # Просто выходим, если нет данных

        q = quote.quote[0]  # Получаем первую котировку

        symbol_with_exchange = q.symbol
        ticker = symbol_with_exchange.split('@')[0]

        # Инициализируем словари для тикера, если их еще нет
        if ticker not in quote_data:
            quote_data[ticker] = {}
        if ticker not in previous_values:
            previous_values[ticker] = {}
        if ticker not in last_option_data:
            last_option_data[ticker] = {}

        # Извлекаем данные из ответа
        ask = float(q.ask.value) if q.HasField('ask') and q.ask.value else 0.0
        bid = float(q.bid.value) if q.HasField('bid') and q.bid.value else 0.0
        last = float(q.last.value) if q.HasField('last') and q.last.value else 0.0

        # Для опционов - сохраняем только ненулевые значения
        theoretical_price = float(q.option.theoretical_price.value) if q.HasField('option') and q.option.HasField(
            'theoretical_price') and q.option.theoretical_price.value else last_option_data.get(ticker, {}).get(
            'theoretical_price', 0.0)
        implied_volatility = float(q.option.implied_volatility.value) if q.HasField('option') and q.option.HasField(
            'implied_volatility') and q.option.implied_volatility.value else last_option_data.get(ticker, {}).get(
            'implied_volatility', 0.0)

        # Обновляем словарь последних значений только если есть новое ненулевое значение
        if q.HasField('option'):
            if ticker not in last_option_data:
                last_option_data[ticker] = {}
            if q.option.HasField('theoretical_price') and q.option.theoretical_price.value:
                last_option_data[ticker]['theoretical_price'] = theoretical_price
            if q.option.HasField('implied_volatility') and q.option.implied_volatility.value:
                last_option_data[ticker]['implied_volatility'] = implied_volatility

        # Словарь для хранения только измененных значений
        changed_data = {}

        # Проверяем изменения и добавляем только измененные значения
        if ask != previous_values.get(ticker, {}).get('ask', None) and ask != 0.0:
            changed_data['ask'] = ask
            if ticker not in previous_values:
                previous_values[ticker] = {}
            previous_values[ticker]['ask'] = ask

        if bid != previous_values.get(ticker, {}).get('bid', None) and bid != 0.0:
            changed_data['bid'] = bid
            if ticker not in previous_values:
                previous_values[ticker] = {}
            previous_values[ticker]['bid'] = bid

        if last != previous_values.get(ticker, {}).get('last', None) and last != 0.0:
            changed_data['last'] = last
            if ticker not in previous_values:
                previous_values[ticker] = {}
            previous_values[ticker]['last'] = last

        if theoretical_price != previous_values.get(ticker, {}).get('theoretical_price', None) and theoretical_price != 0.0:
            changed_data['theoretical_price'] = theoretical_price
            if ticker not in previous_values:
                previous_values[ticker] = {}
            previous_values[ticker]['theoretical_price'] = theoretical_price

        if implied_volatility != previous_values.get(ticker, {}).get('implied_volatility', None) and implied_volatility != 0.0:
            changed_data['implied_volatility'] = implied_volatility
            if ticker not in previous_values:
                previous_values[ticker] = {}
            previous_values[ticker]['implied_volatility'] = implied_volatility

        # Обновляем основной словарь только измененными значениями
        if changed_data:
            quote_data[ticker]['ticker'] = ticker
            quote_data[ticker].update(changed_data)  # Обновляем данные в quote_data для конкретного тикера
            update_quote_dataframe(quote_data)
            # print(f"OPT {ticker}")
            print(quote_df)
            return changed_data, quote_data

    except Exception as e:
        print(f"Ошибка в _on_quote для тикера {ticker}: {e}")
        # return None, None


def _on_order_book(order_book: SubscribeOrderBookResponse):
    logger.info(f'Стакан - {order_book.order_book[0] if len(order_book.order_book) > 0 else "Нет стакана"}')


def _on_latest_trades(latest_trade: SubscribeLatestTradesResponse):
    logger.info(f'Сделка - {latest_trade.trades[0] if len(latest_trade.trades) > 0 else "Нет сделки"}')


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
                sleep(5)
                continue

            # Подписываемся на котировки для каждого тикера
            threads = []
            handlers = []

            # Создаем уникальные обработчики для каждого тикера
            for dataname in positions:
                try:
                    finam_board, ticker = fp_provider.dataname_to_finam_board_ticker(dataname)
                    print(finam_board, ticker)
                    mic = fp_provider.get_mic(finam_board, ticker)

                    # Создаем уникальную функцию для подписки
                    def create_quote_handler(ticker):
                        def on_quote_handler(quote):
                            _on_quote(quote, ticker)  # Передаем тикер в обработчик

                        return on_quote_handler

                    handler = create_quote_handler(ticker)
                    handlers.append(handler)

                    fp_provider.on_quote.subscribe(handler)
                    thread = Thread(target=fp_provider.subscribe_quote_thread, name=f'QuoteThread_{ticker}',
                                    args=((f'{ticker}@{mic}',),))
                    threads.append(thread)
                    thread.start()
                    sleep(1)
                except Exception as e:
                    logger.error(f"Ошибка при подготовке подписки для {dataname}: {e}")

            # Ждем завершения всех потоков
            for thread in threads:
                thread.join(timeout=10)

            sleep(sleep_secs)
            # Не отписываемся от подписки здесь - потоки завершатся автоматически
            # fp_provider.on_quote.unsubscribe(handler)  # Отменяем подписку на котировки

        except KeyboardInterrupt:
            # Прерывание цикла по Ctrl+C
            fp_provider.close_channel()  # Закрываем канал перед выходом
            break
        except Exception as e:
            logger.error(f"Ошибка в основном цикле: {e}")
            sleep(5)  # Ждем перед повторной попыткой
