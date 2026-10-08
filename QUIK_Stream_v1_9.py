import csv  # Запись портфельной информации в CSV
import logging  # Логирование в консоль и файл
from datetime import datetime  # Дата и время
from string import Template  # Шаблон пути к файлам
import threading  # Потоки
import time  # Подписка на события по времени

import pandas as pd
from FinLabPy.Schedule.MOEX import Futures  # Расписание торгов срочного рынка MOEX (FORTS)

import implied_volatility
import option_type
from QuikPy.QuikPy import QuikPy  # Работа с QUIK из Python через LUA скрипты QUIK#
from model.option import Option
from app.supported_base_asset import MAP
from accfifo import Entry, FIFO  # FIFO-учёт для расчёта средневзвешенных значений открытия

# ==================== Константы ====================
TEMP_PATH_TEMPLATE = Template('C:\\Users\\sftpuser\\Position\\$name_file')  # Шаблон пути к файлам

FUTURES_CLASS_CODE = 'SPBFUT'  # Класс фьючерсов
OPTIONS_CLASS_CODE = 'SPBOPT'  # Класс опционов
FUTURES_FIRM_ID = 'SPBFUT'  # Код фирмы для фьючерсов
TRADING_STATUS_OPEN = 1.0  # Статус торговой сессии (1 - открыта, 0 - закрыта)

SYNCHRONIZATION_INTERVAL = 10  # Секунд между синхронизациями ордеров и позиций портфеля
HISTORY_SAVE_INTERVAL = 30  # Секунд между сохранениями истории позиций
SCHEDULE_CHECK_INTERVAL = 30  # Секунд между проверками расписания торгов
MAX_SCHEDULE_SLEEP = 300  # Максимальный сон при ожидании начала торговой сессии, секунд

# Битовые флаги заявки QUIK
ORDER_FLAG_ACTIVE = 0b1  # Бит 0: заявка активна
ORDER_FLAG_CANCELLED = 0b10  # Бит 1: заявка снята
ORDER_FLAG_SELL = 0b100  # Бит 2: заявка на продажу (установлен), на покупку (снят)

# Имена файлов
PORTFOLIO_INFO_CSV = 'QUIK_MyPortfolioInfo.csv'
MYPOS_CSV = 'QUIK_MyPos.csv'
MYPOS_HISTORY_CSV = 'MyPosHistory.csv'
ORDERS_CSV = 'QUIK_Stream_Orders.csv'
TRADES_CSV = 'QUIK_Stream_Trades.csv'
TRADES_ALL_CSV = 'QUIK_Stream_Trades_ALL.csv'
LOG_FILE = 'QUIK_Stream_v1_9.log'

PORTFOLIO_COLUMNS = ['ticker', 'net_pos', 'strike', 'option_type', 'expdate', 'option_base',
                     'OpenDateTime', 'OpenPrice', 'OpenIV', 'time_last', 'bid', 'last', 'ask', 'theor',
                     'QuikVola', 'bidIV', 'lastIV', 'askIV', 'P/L theor', 'P/L last', 'P/L market',
                     'Vega', 'TrueVega']
ORDER_COLUMNS = ['datetime', 'order_num', 'option_base', 'ticker', 'option_type', 'strike', 'expdate',
                 'operation', 'volume', 'price', 'value', 'volatility']
TRADE_COLUMNS = ['datetime', 'order_num', 'option_base', 'ticker', 'option_type', 'strike', 'expdate',
                 'operation', 'volume', 'price', 'value', 'volatility']

# ==================== Логирование ====================
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(message)s',
                    handlers=[logging.StreamHandler(),
                              logging.FileHandler(LOG_FILE, encoding='utf-8')])
log = logging.getLogger('QUIK_Stream')

schedule = Futures()  # Расписание торгов срочного рынка Московской Биржи

# ==================== Глобальные переменные ====================
active_orders_dict = {}  # Словарь активных заявок. Ключ: (ticker, operation, volume)
orders_lock = threading.Lock()  # Блокировка для потокобезопасной работы со списком заявок
written_trade_nums = set()  # Номера уже записанных сделок (защита от дублей в CSV)
trades_lock = threading.Lock()  # Блокировка для потокобезопасной записи сделок
df_portfolio = pd.DataFrame()  # Глобальный датафрейм для хранения позиций портфеля
portfolio_lock = threading.Lock()  # Блокировка для доступа к df_portfolio
qp_provider = None  # Глобальная ссылка на провайдер QUIK
is_working_time = False  # Флаг рабочего времени (торговой сессии FORTS)

# Кэш спецификаций инструментов (не меняются в течение сессии)
_symbol_info_cache = {}
_exp_date_cache = {}
_option_type_cache = {}
_spec_cache_lock = threading.Lock()


def clear_spec_cache():
    """Очищает кэш спецификаций инструментов (вызывается при старте/переподключении)"""
    with _spec_cache_lock:
        _symbol_info_cache.clear()
        _exp_date_cache.clear()
        _option_type_cache.clear()


def wait_for_business_time():
    """Следит за расписанием торгов FORTS: запускает основные функции на открытии сессии и останавливает на закрытии."""
    global is_working_time

    while True:
        dt_market = schedule.market_datetime_now  # Текущее время на бирже
        if schedule.trade_session(dt_market):  # Сейчас идёт торговая сессия
            if not is_working_time:
                log.info("Рабочее время наступило!")
                start_main_functions()
            time.sleep(SCHEDULE_CHECK_INTERVAL)
        else:  # Торги не идут
            if is_working_time:
                log.info("Рабочее время закончилось")
                stop_main_functions()
            wait_seconds = schedule.time_until_trade(dt_market).total_seconds()  # Время до начала следующей сессии
            log.info(f"Торги не идут. До начала следующей сессии: {wait_seconds / 3600:.1f} ч.")
            # Спим до начала сессии, но проверяем расписание не реже, чем раз в MAX_SCHEDULE_SLEEP секунд
            time.sleep(min(max(wait_seconds, 1), MAX_SCHEDULE_SLEEP))


def start_main_functions():
    """Запуск основных функций программы"""
    global qp_provider, is_working_time

    try:
        # Подключение к QUIK
        qp_provider = QuikPy()
        clear_spec_cache()  # Очищаем кэш спецификаций при новом подключении
        # Сразу выполняем синхронизацию инструментов портфеля и активных ордеров
        sync_portfolio_positions()
        sync_active_orders()

        # Запускаем единый поток синхронизации и сохранения истории позиций
        start_sync_thread()

        # Подписка на события
        qp_provider.on_order = OrderHandler()
        qp_provider.on_trade = TradeHandler()

        is_working_time = True  # Устанавливаем флаг рабочего времени
        log.info("Основные функции запущены")

    except Exception as e:
        log.error(f"Ошибка при запуске основных функций: {e}")


def stop_main_functions():
    """Остановка основных функций программы"""
    global qp_provider, is_working_time

    try:
        if qp_provider:
            qp_provider.close_connection_and_thread()
            qp_provider = None
        is_working_time = False
        log.info("Основные функции остановлены")
    except Exception as e:
        log.error(f"Ошибка при остановке основных функций: {e}")


def main_loop():
    """Основной цикл программы: контролирует соединение с QUIK во время торговой сессии"""
    log.info("Сервис запущен. Нажмите Ctrl+C для остановки.")
    try:
        while True:
            if is_working_time:
                if qp_provider is None:
                    log.warning("Соединение потеряно, переподключаемся...")
                    reconnect()
                time.sleep(1)
            else:
                time.sleep(5)
    except KeyboardInterrupt:
        log.info("Остановка сервиса...")
        stop_main_functions()
        log.info("Сервис остановлен")


def get_time_to_maturity(expiration_datetime):
    """Время до исполнения инструмента в долях года (с учётом времени экспирации в последний день)"""
    expiration_timestamp = expiration_datetime.timestamp() if isinstance(expiration_datetime, datetime) \
        else expiration_datetime

    dt_market = schedule.market_datetime_now  # Текущее московское время
    expiration_dt = schedule.timestamp_to_msk_datetime(expiration_timestamp)  # Дата экспирации в московском времени
    difference = expiration_dt - dt_market
    seconds_in_year = 365 * 24 * 60 * 60
    return (difference.total_seconds() + 67800) / seconds_in_year  # Добавляем 67800 секунд (18 ч. 50 мин.), чтобы учесть время в последний день экспирации


def format_datetime(datetime_dict):
    """Форматирует дату и время из словаря QUIK в строку"""
    return (f"{datetime_dict['day']:02d}.{datetime_dict['month']:02d}.{datetime_dict['year']} "
            f"{datetime_dict['hour']:02d}:{datetime_dict['min']:02d}:{datetime_dict['sec']:02d}")


def _get_symbol_info(sec_code):
    """Получает спецификацию опциона из кэша или QUIK"""
    with _spec_cache_lock:
        if sec_code in _symbol_info_cache:
            return _symbol_info_cache[sec_code]
    si = qp_provider.get_symbol_info(OPTIONS_CLASS_CODE, sec_code)
    with _spec_cache_lock:
        _symbol_info_cache[sec_code] = si
    return si


def _get_param_float(class_code_param, sec_code, param_name, default=0.0):
    """Получает числовой параметр инструмента из QUIK. Возвращает default при ошибке или отсутствии значения"""
    try:
        response = qp_provider.get_param_ex(class_code_param, sec_code, param_name, trans_id=0)
        param_value = response['data'].get('param_value')
        if param_value is None or param_value == '':
            return default
        return float(param_value)
    except (TypeError, ValueError, KeyError):
        return default


def _get_exp_date(sec_code):
    """Получает дату экспирации опциона (кэшируется). Возвращает (datetime, строка в формате дд.мм.гггг) или (None, '')"""
    with _spec_cache_lock:
        if sec_code in _exp_date_cache:
            return _exp_date_cache[sec_code]
    try:
        response = qp_provider.get_param_ex(OPTIONS_CLASS_CODE, sec_code, 'EXPDATE', trans_id=0)
        expdate_dt = datetime.strptime(response['data']['param_image'], "%d.%m.%Y")
        result = (expdate_dt, expdate_dt.strftime("%d.%m.%Y"))
    except (TypeError, ValueError, KeyError):
        result = (None, "")
    with _spec_cache_lock:
        _exp_date_cache[sec_code] = result
    return result


def _get_option_type(sec_code):
    """Получает тип опциона (Put/Call), кэшируется. Возвращает строку или None"""
    with _spec_cache_lock:
        if sec_code in _option_type_cache:
            return _option_type_cache[sec_code]
    try:
        response = qp_provider.get_param_ex(OPTIONS_CLASS_CODE, sec_code, 'OPTIONTYPE', trans_id=0)
        result = response['data']['param_image']
    except (TypeError, KeyError):
        result = None
    with _spec_cache_lock:
        _option_type_cache[sec_code] = result
    return result


def _is_trading_session():
    """Проверяет статус торговой сессии QUIK по первому фьючерсу в списке MAP (True - сессия открыта)"""
    try:
        first_key = next(iter(MAP))
        qp_provider.param_request(FUTURES_CLASS_CODE, first_key, 'TRADINGSTATUS', trans_id=0)  # Заказываем получение параметров Quik
        tradingstatus = qp_provider.get_param_ex(FUTURES_CLASS_CODE, first_key, 'TRADINGSTATUS', trans_id=0)['data'][
            'param_value']
        return float(tradingstatus) == TRADING_STATUS_OPEN
    except (TypeError, ValueError, KeyError):
        log.error("Не удалось получить статус торговой сессии")
        return False


class OrderHandler:
    """Класс для обработки событий по заявкам"""

    def trigger(self, data):
        _on_order_impl(data)


class TradeHandler:
    """Класс для обработки событий по сделкам"""

    def trigger(self, data):
        _on_trade_impl(data)


def sync_active_orders():
    """Синхронизация словаря активных ордеров с биржей"""
    global active_orders_dict

    try:
        orders_response = qp_provider.get_all_orders()
        if not (orders_response and orders_response.get('data')):
            log.warning("sync_active_orders: QUIK не вернул список заявок, синхронизация пропущена")
            return

        current_orders_dict = {}  # Все заявки на опционы из снапшота
        current_active_orders = set()  # Активные заявки из снапшота

        for order in orders_response['data']:
            if order.get('class_code') == OPTIONS_CLASS_CODE:
                order_num = str(order.get('order_num'))
                current_orders_dict[order_num] = order
                flags = order.get('flags', 0)
                # Ордер активен (бит 0 установлен) и не снят (бит 1 не установлен)
                if (flags & ORDER_FLAG_ACTIVE == ORDER_FLAG_ACTIVE) \
                        and (flags & ORDER_FLAG_CANCELLED != ORDER_FLAG_CANCELLED):
                    current_active_orders.add(order_num)

        # Заявки, неактивные по данным снапшота (снятые/исполненные) - достоверный признак для удаления.
        # Отсутствие заявки в снапшоте признаком неактивности не считается:
        # снапшот может быть неполным, а заявка - только что добавленной обработчиком событий
        inactive_in_snapshot = set(current_orders_dict) - current_active_orders

        with orders_lock:
            # Удаляем заявки, которые снапшот показывает неактивными
            stale_keys = [key for key, row in active_orders_dict.items()
                          if row['order_num'] in inactive_in_snapshot]
            for key in stale_keys:
                del active_orders_dict[key]
            if stale_keys:
                log.info(f"Удалено {len(stale_keys)} неактивных ордеров")

            # Добавляем активные ордера снапшота, которых нет в нашем словаре.
            # Если заявка с тем же ключом (ticker, operation, volume) уже есть и она новее,
            # добавление отбросит её автоматически внутри _add_order_to_list_from_data
            existing_order_nums = {row['order_num'] for row in active_orders_dict.values()}
            new_orders_to_add = [current_orders_dict[order_num] for order_num in current_active_orders
                                 if order_num not in existing_order_nums]

        for order_data in new_orders_to_add:
            if _add_order_to_list_from_data(order_data):
                log.info(f"Добавлен активный ордер при синхронизации: {order_data.get('order_num')}")

        # Сохраняем в файл
        _save_orders_to_csv()

    except Exception as e:
        log.error(f"Ошибка при синхронизации ордеров: {e}")


def sync_portfolio_positions():
    """Синхронизация позиций в портфеле и сохранение их в CSV"""
    global df_portfolio

    try:
        portfolio_info = []
        portfolio_positions = []
        class_codes = qp_provider.get_classes_list()['data']  # Режимы торгов через запятую
        class_codes_list = class_codes[:-1].split(',')  # Удаляем последнюю запятую, разбиваем по запятой
        trade_accounts = qp_provider.get_trade_accounts()['data']  # Все торговые счета
        money_limits = qp_provider.get_money_limits()['data']  # Все денежные лимиты (остатки на счетах)

        for trade_account in trade_accounts:  # Пробегаемся по всем счетам (Коды клиента/Фирма/Счет)
            firm_id = trade_account['firmid']  # Фирма
            trade_account_id = trade_account['trdaccid']  # Счет
            if firm_id == FUTURES_FIRM_ID:  # Для фирмы фьючерсов
                futures_limit = qp_provider.get_futures_limit(firm_id, trade_account_id, 0, qp_provider.currency)[
                    'data']  # Фьючерсные лимиты по денежным средствам (limit_type=0)
                varmargin = futures_limit['varmargin']  # Вариационная маржа
                accruedint = futures_limit['accruedint']  # Накопленный доход
                ts_comission = futures_limit['ts_comission']  # ТС комиссия
                pl_day = varmargin + accruedint  # Дневной P/L
                cbplused = futures_limit['cbplused']  # Текущие чистые позиции
                cbplplanned = futures_limit['cbplplanned']  # Плановые чистые позиции
                money = cbplused + cbplplanned - ts_comission  # Деньги
                GM = (cbplused / money) * 100

                portfolio_info.append({
                    'VM': round(varmargin, 2),
                    'PL day': round(pl_day, 2),
                    'Comiss': round(ts_comission, 2),
                    'GM': (f'{GM:.0f} %')
                })
                with open(TEMP_PATH_TEMPLATE.substitute(name_file=PORTFOLIO_INFO_CSV), "w", newline="",
                          encoding="utf-8") as file:
                    writer = csv.writer(file, delimiter=':')
                    for item in portfolio_info:
                        for key, value in item.items():
                            writer.writerow([key, value])

        # Проверка статуса торговой сессии (1 - открыта, 0 - закрыта)
        if not _is_trading_session():
            log.info('sync_portfolio_positions: Эта сессия сейчас не идёт!')
            return

        # Читаем все сделки один раз за проход синхронизации
        trades_df = _read_trades_csv()

        # Получаем активные позиции по опционам
        futures_holdings_response = qp_provider.get_futures_holdings()
        if futures_holdings_response and futures_holdings_response.get('data'):
            active_futures_holdings = [futuresHolding for futuresHolding in futures_holdings_response['data']
                                       if futuresHolding['totalnet'] != 0]  # Активные позиции

            for active_futures_holding in active_futures_holdings:
                sec_code = active_futures_holding["sec_code"]
                class_code_result = qp_provider.get_security_class(class_codes, sec_code)

                if class_code_result and class_code_result.get('data'):
                    option_class_code = class_code_result['data']
                    if option_class_code == OPTIONS_CLASS_CODE:  # Берем только опционы
                        si = _get_symbol_info(sec_code)  # Спецификация тикера (кэшируется)

                        # Тип опциона
                        option_type_str = _get_option_type(sec_code)
                        if option_type_str is None:
                            continue
                        opt_type_converted = option_type.PUT if option_type_str == "Put" else option_type.CALL

                        # Время последней сделки Last
                        try:
                            last_time = qp_provider.get_param_ex(option_class_code, sec_code, 'TIME', trans_id=0)[
                                'data'].get('param_image') or ""
                        except (TypeError, KeyError):
                            last_time = ""

                        # Цены опциона: последней сделки, BID, OFFER, THEORPRICE
                        opt_price = _get_param_float(option_class_code, sec_code, 'LAST')
                        bid_price = _get_param_float(option_class_code, sec_code, 'BID')
                        offer_price = _get_param_float(option_class_code, sec_code, 'OFFER')
                        theor_price = _get_param_float(option_class_code, sec_code, 'THEORPRICE')

                        # Цена последней сделки базового актива (S) и страйк опциона (K)
                        asset_price = _get_param_float(FUTURES_CLASS_CODE, si['base_active_seccode'], 'LAST')
                        strike_price = _get_param_float(option_class_code, sec_code, 'STRIKE')

                        # Волатильность опциона и дата исполнения
                        VOLATILITY = _get_param_float(option_class_code, sec_code, 'VOLATILITY')
                        EXPDATE, formatted_exp_date = _get_exp_date(sec_code)

                        # Время до исполнения инструмента в долях года
                        time_to_maturity = get_time_to_maturity(EXPDATE)

                        # Вычисление Vega
                        sigma = VOLATILITY / 100
                        vega = implied_volatility._vega(asset_price, sigma, strike_price, time_to_maturity,
                                                        implied_volatility._RISK_FREE_INTEREST_RATE,
                                                        opt_type_converted)
                        Vega = vega / 100

                        # Число дней до экспирации
                        DAYS_TO_MAT_DATE = _get_param_float(option_class_code, sec_code, 'DAYS_TO_MAT_DATE')

                        # Вычисление TrueVega
                        TrueVega = 0 if DAYS_TO_MAT_DATE == 0 else Vega / (DAYS_TO_MAT_DATE ** 0.5)

                        # Создание опциона
                        option = Option(si["sec_code"], si["base_active_seccode"], EXPDATE, strike_price,
                                        opt_type_converted)

                        # Волатильность опциона IMPLIED_VOLATILITY (IV) - через расчет по цене опциона
                        opt_volatility_last = 0.0
                        if opt_price > 0:
                            iv_result = implied_volatility.get_iv_for_option_price(asset_price, option, opt_price)
                            if iv_result is not None:
                                opt_volatility_last = iv_result

                        opt_volatility_bid = implied_volatility.get_iv_for_option_price(asset_price, option, bid_price)
                        opt_volatility_offer = implied_volatility.get_iv_for_option_price(asset_price, option,
                                                                                          offer_price)

                        net_pos = active_futures_holding['totalnet']
                        open_data_result = calculate_open_data_open_price_open_iv(sec_code, net_pos,
                                                                                  trades_df=trades_df)
                        # Проверяем, что функция вернула корректные данные
                        if open_data_result is not None and len(open_data_result) > 2:
                            open_datetime = open_data_result[0]
                            open_price = open_data_result[1] if open_data_result[1] is not None else 0.0
                            open_iv = open_data_result[2] if open_data_result[2] is not None else 0.0
                        else:
                            open_datetime = ""
                            open_price = 0.0
                            open_iv = 0.0

                        portfolio_positions.append({
                            'ticker': sec_code,
                            'net_pos': net_pos,
                            'strike': strike_price,
                            'option_type': option_type_str,
                            'expdate': formatted_exp_date,
                            'option_base': si['base_active_seccode'],
                            'OpenDateTime': open_datetime,
                            'OpenPrice': round(open_price, 2) if open_price is not None else open_price,
                            'OpenIV': round(open_iv, 2) if open_iv is not None else open_iv,
                            'time_last': last_time,
                            'bid': bid_price,
                            'last': opt_price,
                            'ask': offer_price,
                            'theor': theor_price,
                            'QuikVola': VOLATILITY,
                            'bidIV': round(opt_volatility_bid, 2) if opt_volatility_bid is not None else 0,
                            'lastIV': round(opt_volatility_last, 2) if opt_volatility_last is not None else 0,
                            'askIV': round(opt_volatility_offer, 2) if opt_volatility_offer is not None else 0,
                            'P/L theor': round(VOLATILITY - open_iv, 2) if net_pos > 0 else round(open_iv - VOLATILITY, 2),
                            'P/L last': 0 if opt_volatility_last == 0 else (
                                round(opt_volatility_last - open_iv, 2) if net_pos > 0 else round(
                                    open_iv - opt_volatility_last, 2)),
                            'P/L market': round(opt_volatility_bid - open_iv, 2) if (
                                    net_pos > 0 and opt_volatility_bid is not None) else round(
                                open_iv - opt_volatility_offer, 2) if opt_volatility_offer is not None else None,
                            'Vega': round(Vega * net_pos, 2),
                            'TrueVega': round(TrueVega * net_pos, 2)
                        })

        # Сохраняем в CSV файл
        with portfolio_lock:
            if portfolio_positions:
                df_portfolio = pd.DataFrame(portfolio_positions)
            else:
                # Пустой датафрейм с заголовками
                df_portfolio = pd.DataFrame(columns=PORTFOLIO_COLUMNS)
        df_portfolio.to_csv(TEMP_PATH_TEMPLATE.substitute(name_file=MYPOS_CSV),
                            sep=';', encoding='utf-8', index=False)

        # Очищаем файл со сделками - удаляем старые сделки с тикерами, которых уже нет в портфеле
        tickers = [item['ticker'] for item in portfolio_positions]
        trades_df = trades_df[trades_df['ticker'].isin(tickers)]
        trades_df.to_csv(TEMP_PATH_TEMPLATE.substitute(name_file=TRADES_CSV), encoding='utf-8', index=False, sep=';')

    except Exception as e:
        log.error(f"Ошибка при синхронизации позиций портфеля: {e}")


def _read_trades_csv():
    """Читает CSV файл со сделками. Возвращает пустой датафрейм при отсутствии файла или ошибке"""
    try:
        return pd.read_csv(TEMP_PATH_TEMPLATE.substitute(name_file=TRADES_CSV), encoding='utf-8', delimiter=';')
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return pd.DataFrame(columns=TRADE_COLUMNS)


def save_mypos_history():
    """Сохраняет текущие позиции портфеля в файл истории MyPosHistory.csv (один проход)"""
    # Проверка статуса торговой сессии
    if not _is_trading_session():
        log.info('save_mypos_history: Эта сессия сейчас не идёт!')
        return

    # Проверяем, что df_portfolio существует и не пуст
    with portfolio_lock:
        if df_portfolio.empty:
            return
        df = df_portfolio.copy()

    # Конвертируем числовые столбцы
    numeric_columns = ['net_pos', 'TrueVega', 'QuikVola', 'lastIV', 'bidIV', 'askIV', 'OpenIV']
    for column in numeric_columns:
        df[column] = pd.to_numeric(df[column], errors='coerce')
    # Удаляем строки с NaN в ключевых столбцах
    df = df.dropna(subset=['net_pos', 'TrueVega'])
    rows_to_write = []

    # Группируем по option_base и обрабатываем каждую группу отдельно
    for option_base, group_data in df.groupby('option_base'):
        # Разделяем на long и short позиции внутри группы
        for pos_name, positions, market_column in (
                ('long', group_data[group_data['net_pos'] > 0], 'bidIV'),
                ('short', group_data[group_data['net_pos'] < 0], 'askIV')):
            if positions.empty or positions['TrueVega'].abs().sum() == 0:
                continue

            # Используем TrueVega как веса
            weights = positions['TrueVega'].abs()
            total_weight = weights.sum()

            # Заменяем нулевые значения 'lastIV' на 'QuikVola' (theor)
            lastIV_corrected = positions['lastIV'].replace(0, pd.NA).fillna(positions['QuikVola']).infer_objects()

            rows_to_write.append({
                'DateTime': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'option_base': option_base,
                'pos': pos_name,
                'theor': round((positions['QuikVola'] * weights).sum() / total_weight, 2),
                'last': round((lastIV_corrected * weights).sum() / total_weight, 2),
                'market': round((positions[market_column] * weights).sum() / total_weight, 2),
                'mypos': round((positions['OpenIV'] * weights).sum() / total_weight, 2)
            })

    # Записываем данные в CSV файл
    if rows_to_write:
        filename = TEMP_PATH_TEMPLATE.substitute(name_file=MYPOS_HISTORY_CSV)
        df_history = pd.DataFrame(rows_to_write)
        # Проверяем, существует ли файл
        try:
            with open(filename, 'r'):
                file_exists = True
        except FileNotFoundError:
            file_exists = False
        # Записываем в файл (добавляем или создаем новый)
        with open(filename, 'a', newline='', encoding='utf-8') as f:
            df_history.to_csv(f, index=False, sep=';', header=file_exists)


def calculate_open_data_open_price_open_iv(sec_code, net_pos, trades_df=None):
    """
    Вычисляет дату открытия позиции, цену и волатильность для заданного инструмента,
    как средневзвешенные по объёму первых сделок до достижения нужного объёма.

    :param str sec_code: Код инструмента
    :param int net_pos: Текущая позиция (отрицательная для короткой позиции)
    :param pd.DataFrame trades_df: Датафрейм всех сделок. Если None, читается из CSV файла
    :return: tuple(OpenDateTime, OpenPrice, OpenIV)
    """
    try:
        # Чтение сделок из переданного датафрейма или CSV файла
        if trades_df is None:
            trades_df = _read_trades_csv()

        # Фильтрация по инструменту (все сделки по инструменту)
        instrument_trades_df = trades_df[trades_df['ticker'] == sec_code].copy()

        if instrument_trades_df.empty:
            log.warning(f"Предупреждение: Нет данных для инструмента {sec_code}")
            return None, None, None

        # Преобразование datetime и сортировка в обратном порядке (от последних сделок к первым)
        instrument_trades_df['datetime'] = pd.to_datetime(instrument_trades_df['datetime'],
                                                          format='%d.%m.%Y %H:%M:%S')
        instrument_trades_df = instrument_trades_df.sort_values('datetime', ascending=False)

        # Применяем изменение знака для объема при продаже (умножаем объем сделки на -1)
        instrument_trades_df.loc[instrument_trades_df['operation'] == 'Продажа', 'volume'] *= -1

        # Целевой объём
        required_volume = net_pos
        sign = 1 if required_volume > 0 else -1  # Знак позиции: для положительной вычитаем объемы, для отрицательной прибавляем
        selected_trades = []
        # Отбираем сделки до достижения нужного объёма
        for _, trade in instrument_trades_df.iterrows():
            volume = trade['volume']
            if sign * (required_volume - volume) >= 0:
                # Добавляем сделку целиком
                selected_trades.append(trade)
                required_volume -= volume
            else:
                # Добавляем частичную сделку
                partial_trade = trade.copy()
                partial_trade['volume'] = required_volume
                selected_trades.append(partial_trade)
                required_volume = 0
                break

        if not selected_trades:
            sum_volume_short = instrument_trades_df.loc[instrument_trades_df['operation'] == 'Продажа', 'volume'].sum()
            count_short = (instrument_trades_df['operation'] == 'Продажа').sum()
            sum_volume_long = instrument_trades_df.loc[instrument_trades_df['operation'] == 'Купля', 'volume'].sum()
            count_long = (instrument_trades_df['operation'] == 'Купля').sum()
            log.warning(f"Предупреждение: Недостаточно сделок для инструмента {sec_code}")
            log.warning(f"Позиция: {net_pos}")
            log.warning(f"Сделок лонг: {count_long} Объем: {sum_volume_long}")
            log.warning(f"Сделок шорт: {count_short} Объем: {sum_volume_short}")
            return None, None, None

        # Дата первой сделки (самой старой сделки, она в конце списка)
        selected_df = pd.DataFrame(selected_trades)
        OpenDateTime = selected_df.iloc[-1]['datetime'].strftime('%d.%m.%Y %H:%M:%S')

        # Удаляем из списка сделки противоположной направленности
        # для правильного расчета средневзвешенных значений цены и волатильности
        selected_trades = [trade for trade in selected_trades
                           if (trade['volume'] > 0) == (net_pos > 0)]

        # Расчет средневзвешенной цены и волатильности открытия методом FIFO
        fifo_entries = [Entry(quantity=trade['volume'], price=trade['price']) for trade in selected_trades]
        fifo_entries_volatility = [Entry(quantity=trade['volume'], price=trade['volatility'])
                                   for trade in selected_trades]

        OpenPrice = calculate_weighted_average(FIFO(fifo_entries).inventory)
        OpenIV = calculate_weighted_average(FIFO(fifo_entries_volatility).inventory)

        return OpenDateTime, OpenPrice, OpenIV

    except Exception as e:
        log.error(f"Ошибка при вычислении данных открытия для {sec_code}: {e}")
        return None, None, None


def calculate_weighted_average(inventory):
    """Средневзвешенное значение по инвентарю FIFO (deque из Entry с атрибутами quantity и price)"""
    weighted_sum = sum(entry.quantity * entry.price for entry in inventory)
    total_weight = sum(entry.quantity for entry in inventory)
    return weighted_sum / total_weight if total_weight != 0 else 0


def _add_order_to_list_from_data(order_data):
    """Добавление ордера в словарь активных заявок.

    Ключ заявки: (ticker, operation, volume). По каждому ключу хранится только одна заявка -
    при конфликте остаётся заявка с большим временем (при равном времени - с большим номером).
    Это исключает накопление снятых дублей по одному инструменту.
    Возвращает True, если заявка добавлена или заменена"""
    global active_orders_dict

    try:
        order_num = str(order_data.get('order_num'))
        try:
            order_num_int = int(order_num)
        except ValueError:
            order_num_int = 0

        # Проверяем актуальность флагов заявки: она могла быть снята после снапшота,
        # либо события QUIK пришли вне очереди (снятие раньше постановки)
        flags = order_data.get('flags', 0)
        is_active = (flags & ORDER_FLAG_ACTIVE == ORDER_FLAG_ACTIVE) \
            and (flags & ORDER_FLAG_CANCELLED != ORDER_FLAG_CANCELLED)
        if not is_active:
            log.warning(f"Заявка {order_num} не активна, пропускаем добавление")
            return False

        # Определяем тип операции и ключ заявки
        buy = flags & ORDER_FLAG_SELL != ORDER_FLAG_SELL  # Заявка на покупку
        operation = "Купля" if buy else "Продажа"
        sec_code = order_data.get('sec_code')
        si = _get_symbol_info(sec_code)  # Спецификация тикера (кэшируется)
        order_qty = order_data.get('qty') * si['lot_size']
        key = (sec_code, operation, order_qty)

        dt = order_data.get('datetime')
        dt_key = (dt['year'], dt['month'], dt['day'], dt['hour'], dt['min'], dt['sec'])

        with orders_lock:
            # Быстрая проверка: если по этому ключу уже есть более новая (или та же) заявка -
            # выходим, не выполняя запросы к QUIK и расчеты
            existing = active_orders_dict.get(key)
            if existing is not None \
                    and (existing['_dt_key'], int(existing['order_num'])) >= (dt_key, order_num_int):
                return False

        # Получаем цену базового актива
        asset_price = _get_param_float(FUTURES_CLASS_CODE, si['base_active_seccode'], 'LAST')
        if asset_price == 0.0:
            log.warning(f"Не удалось получить цену базового актива для {si['base_active_seccode']}")
            return False

        # Получаем дату экспирации и тип опциона (кэшируются)
        expdate, formatted_exp_date = _get_exp_date(sec_code)
        if expdate is None:
            log.warning(f"Не удалось получить дату экспирации для {sec_code}")
            return False
        option_type_str = _get_option_type(sec_code)
        if option_type_str is None:
            log.warning(f"Не удалось получить тип опциона для {sec_code}")
            return False
        opt_type_converted = option_type.PUT if option_type_str == "Put" else option_type.CALL

        # Вычисляем цену
        order_price = qp_provider.quik_price_to_price(OPTIONS_CLASS_CODE, sec_code, order_data.get('price'))

        # Создаем опцион для расчета волатильности
        option = Option(sec_code, si["base_active_seccode"], expdate, si['option_strike'], opt_type_converted)

        iv = implied_volatility.get_iv_for_option_price(asset_price, option, order_price)

        row = {
            'datetime': format_datetime(dt),
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
            'volatility': round(iv, 2) if iv is not None else 0.0,
            '_dt_key': dt_key  # Служебное поле для сортировки и сравнения (в CSV не попадает)
        }

        with orders_lock:
            # Повторная проверка: за время получения данных могла появиться более новая заявка
            existing = active_orders_dict.get(key)
            if existing is not None \
                    and (existing['_dt_key'], int(existing['order_num'])) >= (dt_key, order_num_int):
                return False
            active_orders_dict[key] = row
            return True

    except Exception as e:
        log.error(f"Ошибка при добавлении ордера {order_data.get('order_num')}: {e}")
        return False


def _save_orders_to_csv():
    """Сохранение активных ордеров в CSV. По каждому ключу (ticker, operation, volume)
    хранится только одна - самая новая - заявка, снятые дубли в файл не попадают"""
    with orders_lock:
        rows = sorted(active_orders_dict.values(), key=lambda row: row['_dt_key'])
    df_order_quik = pd.DataFrame(rows, columns=ORDER_COLUMNS)
    df_order_quik.to_csv(TEMP_PATH_TEMPLATE.substitute(name_file=ORDERS_CSV),
                         sep=';', encoding='utf-8', index=False)


def sync_orders_worker():
    """Единый рабочий поток: синхронизация активных ордеров и позиций портфеля (каждые SYNCHRONIZATION_INTERVAL секунд)
    и сохранение истории позиций (каждые HISTORY_SAVE_INTERVAL секунд)"""
    history_every = max(HISTORY_SAVE_INTERVAL // SYNCHRONIZATION_INTERVAL, 1)  # Каждую N-ю итерацию сохраняем историю
    iteration = 0
    while True:
        try:
            time.sleep(SYNCHRONIZATION_INTERVAL)
            iteration += 1
            sync_active_orders()
            sync_portfolio_positions()
            if iteration % history_every == 0:
                save_mypos_history()
        except Exception as e:
            log.error(f"Ошибка в потоке синхронизации: {e}")
            if "WinError 10053" in str(e) or "Connection" in str(e):
                log.warning("Попытка переподключения...")
                reconnect()
            time.sleep(5)


def start_sync_thread():
    """Запускает единый поток синхронизации ордеров, позиций портфеля и истории позиций"""
    sync_thread = threading.Thread(target=sync_orders_worker, daemon=True)
    sync_thread.start()
    log.info("Поток синхронизации ордеров, позиций портфеля и истории позиций запущен")


def _on_order_impl(data):
    """Реализация обработчика событий по заявкам"""
    order_data = data.get('data')

    # Проверяем, что это опцион
    if order_data.get('class_code') != OPTIONS_CLASS_CODE:
        return

    order_num = str(order_data.get('order_num'))
    # Ордер активен (бит 0 установлен) и не снят (бит 1 не установлен)
    is_active = (order_data.get('flags') & ORDER_FLAG_ACTIVE == ORDER_FLAG_ACTIVE) \
        and (order_data.get('flags') & ORDER_FLAG_CANCELLED != ORDER_FLAG_CANCELLED)

    if not is_active:
        with orders_lock:
            # Удаляем снятую заявку из словаря активных заявок
            stale_keys = [key for key, row in active_orders_dict.items()
                          if row['order_num'] == order_num]
            for key in stale_keys:
                del active_orders_dict[key]
    else:
        # Добавление заявки: дубли по ключу (ticker, operation, volume)
        # вытесняются заявкой с большим временем
        _add_order_to_list_from_data(order_data)

    # Сохраняем в CSV при любом изменении
    _save_orders_to_csv()


def _load_written_trade_nums():
    """Загружает номера уже записанных сделок из CSV файлов (защита от дублей после перезапуска)"""
    loaded = set()
    for filename in (TRADES_CSV, TRADES_ALL_CSV):
        try:
            df = pd.read_csv(TEMP_PATH_TEMPLATE.substitute(name_file=filename),
                             encoding='utf-8', usecols=['order_num'], delimiter=';')
            loaded.update(str(num) for num in df['order_num'])
        except (FileNotFoundError, pd.errors.EmptyDataError, ValueError):
            continue
    with trades_lock:
        written_trade_nums.update(loaded)
    log.info(f"Загружено {len(loaded)} номеров ранее записанных сделок")


def _on_trade_impl(data):
    """Реализация обработчика событий по сделкам"""
    trade_data = data.get('data')

    # Проверяем, что это опцион
    if trade_data.get('class_code') != OPTIONS_CLASS_CODE:
        return

    trade_num = str(trade_data.get('trade_num'))
    with trades_lock:
        # Защита от повторной записи той же сделки
        if trade_num in written_trade_nums:
            log.warning(f"Сделка {trade_num} уже записана, пропускаем")
            return
        written_trade_nums.add(trade_num)

    try:
        # Определяем тип операции
        buy = trade_data.get('flags') & ORDER_FLAG_SELL != ORDER_FLAG_SELL  # Заявка на покупку
        operation = "Купля" if buy else "Продажа"

        # Получаем информацию о ценной бумаге (кэшируется)
        sec_code = trade_data.get('sec_code')
        si = _get_symbol_info(sec_code)

        # Получаем цену базового актива, дату экспирации и тип опциона (кэшируются)
        asset_price = _get_param_float(FUTURES_CLASS_CODE, si['base_active_seccode'], 'LAST')
        expdate, formatted_exp_date = _get_exp_date(sec_code)
        option_type_str = _get_option_type(sec_code)
        opt_type_converted = option_type.PUT if option_type_str == "Put" else option_type.CALL

        # Вычисляем количество и цену
        trade_qty = trade_data.get('qty') * si['lot_size']
        trade_price = qp_provider.quik_price_to_price(OPTIONS_CLASS_CODE, sec_code, trade_data.get('price'))

        # Создаем опцион для расчета волатильности
        option = Option(sec_code, si["base_active_seccode"], expdate, si['option_strike'], opt_type_converted)

        iv = implied_volatility.get_iv_for_option_price(asset_price, option, trade_price)
        volatility = round(iv, 2) if iv is not None else 0.0

        # Добавляем сделку в список
        df_trade_quik = pd.DataFrame([{
            'datetime': format_datetime(trade_data.get('datetime')),
            'order_num': trade_num,
            'option_base': si['base_active_seccode'],
            'ticker': sec_code,
            'option_type': option_type_str,
            'strike': int(si['option_strike']),
            'expdate': formatted_exp_date,
            'operation': operation,
            'volume': trade_qty,
            'price': trade_price,
            'value': trade_qty * trade_price,
            'volatility': volatility
        }], columns=TRADE_COLUMNS)

        log.info(f"Новая сделка:\n{df_trade_quik.to_string(index=False)}")

        # Добавляем сделку в CSV файл
        df_trade_quik.to_csv(TEMP_PATH_TEMPLATE.substitute(name_file=TRADES_CSV), mode='a', sep=';', index=False,
                             header=False)
        # Добавляем сделку в резервный CSV файл
        df_trade_quik.to_csv(TEMP_PATH_TEMPLATE.substitute(name_file=TRADES_ALL_CSV), mode='a', sep=';',
                             index=False, header=False)
    except Exception as e:
        # При ошибке записи освобождаем номер сделки для повторной попытки
        with trades_lock:
            written_trade_nums.discard(trade_num)
        log.error(f"Ошибка при обработке сделки {trade_num}: {e}")


def reconnect():
    """Переподключение к QUIK и повторная подписка на события"""
    global qp_provider
    try:
        if qp_provider:
            qp_provider.close_connection_and_thread()
    except Exception:
        pass
    qp_provider = QuikPy()
    clear_spec_cache()  # Очищаем кэш спецификаций при переподключении
    # Повторная синхронизация
    sync_portfolio_positions()
    sync_active_orders()
    # Подписка на события
    qp_provider.on_order = OrderHandler()
    qp_provider.on_trade = TradeHandler()
    log.info("Переподключение выполнено")


if __name__ == '__main__':  # Точка входа при запуске этого скрипта

    # Загружаем номера ранее записанных сделок для защиты от дублей
    _load_written_trade_nums()

    # Запускаем поток отслеживания расписания торгов FORTS
    time_thread = threading.Thread(target=wait_for_business_time, daemon=True)
    time_thread.start()

    # Запускаем основной цикл
    main_loop()
