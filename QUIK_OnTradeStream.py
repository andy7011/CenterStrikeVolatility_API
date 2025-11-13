import logging  # Выводим лог на консоль и в файл
import sys  # Выход из точки входа
from datetime import datetime  # Дата и время
from threading import Thread  # Каждый скрипт будем запускать в отдельном потоке
import time  # Подписка на события по времени

from QuikPy import QuikPy  # Работа с QUIK из Python через LUA скрипты QUIK#


def script1(provider: QuikPy):  # 1-ый скрипт
    trans_id = 1  # Номера транзакций для 1-го скрипта
    # Проверяем соединение с терминалом QUIK
    is_connected = provider.is_connected()['data']  # Состояние подключения терминала к серверу QUIK
    logger.info(f'Терминал QUIK подключен к серверу: {is_connected == 1}')
    if is_connected == 0:  # Если нет подключения терминала QUIK к серверу
        provider.close_connection_and_thread()  # Перед выходом закрываем соединение для запросов и поток обработки функций обратного вызова
        sys.exit()  # Выходим, дальше не продолжаем

    # Подписка на сделки
    provider.on_trade = lambda data: logger.info(data)  # Обработчик получения сделки
    logger.info(f'Подписка на мои сделки {class_code}.{sec_code}')
    # sleep_sec = 10  # Кол-во секунд получения сделок
    # logger.info(f'Секунд моих сделок: {sleep_sec}')
    # time.sleep(sleep_sec)  # Ждем кол-во секунд получения сделок
    # # logger.info(f'Отмена подписки на сделки')
    # qp_provider.on_trade = qp_provider.default_handler  # Возвращаем обработчик по умолчанию

    # Подписка на ордера
    provider.on_order = lambda data: logger.info(data)  # Обработчик получения заявки
    logger.info(f'Подписка на мои заявки {class_code}.{sec_code}')
    # sleep_sec = 10  # Кол-во секунд получения сделок
    # logger.info(f'Секунд моих сделок: {sleep_sec}')
    # time.sleep(sleep_sec)  # Ждем кол-во секунд получения сделок
    # # logger.info(f'Отмена подписки на заявки')
    # qp_provider.on_order = qp_provider.default_handler  # Возвращаем обработчик по умолчанию

    # time.sleep(10)  # Ждем 10 секунд


def script2(provider: QuikPy):  # 2-ой скрипт
    trans_id = 2  # Номера транзакций для 2-го скрипта
    for i in range(10):  # Даем нагрузку на QuikPy
        msg = 'Hello from Python!'
        message_info = provider.message_info(msg, trans_id)  # Проверка работы QUIK. Сообщение в QUIK должно показаться как информационное
        logger.info(f'script{message_info["id"]}/{i}: Отправка сообщения в QUIK: {msg}{message_info["data"]}')


if __name__ == '__main__':  # Точка входа при запуске этого скрипта
    class_code = 'SPBFUT'  # Класс тикера
    sec_code = 'RIZ5'  # Для фьючерсов: <Код тикера><Месяц экспирации: 3-H, 6-M, 9-U, 12-Z><Последняя цифра года>
    logger = logging.getLogger('QuikPy.MultiScripts')  # Будем вести лог
    qp_provider = QuikPy()  # Подключение к локальному запущенному терминалу QUIK по портам по умолчанию

    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  # Формат сообщения
                        datefmt='%d.%m.%Y %H:%M:%S',  # Формат даты
                        level=logging.DEBUG,  # Уровень логируемых событий NOTSET/DEBUG/INFO/WARNING/ERROR/CRITICAL
                        handlers=[logging.FileHandler('MultiScripts.log', encoding='utf-8'), logging.StreamHandler()])  # Лог записываем в файл и выводим на консоль
    logging.Formatter.converter = lambda *args: datetime.now(tz=qp_provider.tz_msk).timetuple()  # В логе время указываем по МСК

    thread1 = Thread(target=script1, args=(qp_provider,), name='script1')  # Поток запуска 1-го скрипта
    logger.info(f'Запускаем 1-ый скрипт в отдельном потоке')
    thread1.start()  # Запускаем 1-ый скрипт в отдельном потоке

    thread2 = Thread(target=script2, args=(qp_provider,), name='script2')  # Поток запуска 2-го скрипта
    logger.info(f'Запускаем 2-й скрипт в отдельном потоке')
    thread2.start()  # Запускаем 2-ой скрипт в отдельном потоке
    thread1.join()  # Ожидаем завершения 1-го скрипта
    logger.info(f'Завершение 1-го скрипта')
    thread2.join()  # Ожидаем завершения 2-го скрипта
    logger.info(f'Завершение 2-го скрипта')

    # Выход
    input('Enter - выход\n')
    logger.info(f'Перед выходом закрываем соединение для запросов и поток обработки функций обратного вызова')
    qp_provider.close_connection_and_thread()  # Перед выходом закрываем соединение для запросов и поток обработки функций обратного вызова

