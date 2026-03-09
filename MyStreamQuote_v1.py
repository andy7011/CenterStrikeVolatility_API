import logging  # Выводим лог на консоль и в файл
from datetime import datetime  # Дата и время
from time import sleep  # Подписка на события по времени

from AlorPy import AlorPy  # Работа с Alor OpenAPI V2

def _on_new_quotes(response):
    logger.info(f'Котировка - {response["data"]}')

if __name__ == '__main__':  # Точка входа при запуске этого скрипта
    logger = logging.getLogger('AlorPy.Stream')  # Будем вести лог
    ap_provider = AlorPy()  # Подключаемся ко всем торговым счетам

    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  # Формат сообщения
                        datefmt='%d.%m.%Y %H:%M:%S',  # Формат даты
                        level=logging.DEBUG,  # Уровень логируемых событий NOTSET/DEBUG/INFO/WARNING/ERROR/CRITICAL
                        handlers=[logging.FileHandler('Stream.log', encoding='utf-8'),
                                  logging.StreamHandler()])  # Лог записываем в файл и выводим на консоль
    logging.Formatter.converter = lambda *args: datetime.now(
        tz=ap_provider.tz_msk).timetuple()  # В логе время указываем по МСК
    logging.getLogger('urllib3').setLevel(logging.CRITICAL + 1)  # Не пропускать в лог
    logging.getLogger('websockets').setLevel(logging.CRITICAL + 1)  # события в этих библиотеках

    portfolio_positions_finam = ['SPBOPT.RI92500BO6', 'SPBOPT.RI130000BC6', 'SPBOPT.Si79000BC6A', 'SPBOPT.RI127500BF6',
                                 'SPBOPT.RI97500BO6',
                                 'SPBOPT.RI127500BC6', 'SPBOPT.RI107500BR6', 'SPBOPT.RI102500BO6', 'SPBOPT.RI95000BO6']

    sleep_secs = 60 # Кол-во секунд получения котировок
    logger.info(f'Секунд котировок: {sleep_secs}')

    # Подписываемся на события
    ap_provider.on_new_quotes.subscribe(_on_new_quotes)

    # Список GUID для отписки
    guids = []

    # Подписываемся на котировки для каждого тикера
    for dataname in portfolio_positions_finam:
        try:
            alor_board, symbol = ap_provider.dataname_to_alor_board_symbol(
                dataname)  # Код режима торгов Алора и код и тикер
            exchange = ap_provider.get_exchange(alor_board, symbol)  # Код биржи

            guid = ap_provider.quotes_subscribe(exchange, symbol)  # Получаем код подписки
            guids.append(guid)
            logger.info(f'Подписка на котировки {guid} тикера {dataname} создана')
        except Exception as e:
            logger.error(f'Ошибка подписки на {dataname}: {e}')

    # Ждем кол-во секунд получения котировок
    sleep(sleep_secs)

    # Отписываемся от всех котировок
    for guid in guids:
        try:
            logger.info(f'Подписка на котировки {ap_provider.unsubscribe(guid)} отменена')
        except Exception as e:
            logger.error(f'Ошибка отписки: {e}')

    # Отменяем подписку на события
    ap_provider.on_new_quotes.unsubscribe(_on_new_quotes)

    # Выход
    ap_provider.close_web_socket()  # Перед выходом закрываем соединение с WebSocket
