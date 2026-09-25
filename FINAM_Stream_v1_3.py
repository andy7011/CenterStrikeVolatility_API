import logging  # Модуль для ведения логов
from threading import Thread, Event  # Модуль для создания потоков и событий
from datetime import datetime  # Модуль для работы с датой и временем
from time import sleep  # Функция для приостановки выполнения программы
import time as _time
import signal
import traceback  # Модуль для получения полной информации об ошибке
import threading
import random
import math
import numpy as np
from scipy.stats import norm
from scipy.optimize import brentq

from moex_api import get_option_board, get_option_expirations
from FinamPy import FinamPy  # Основной класс библиотеки FinamPy
from FinamPy.grpc import orders_service_pb2 as orders_service
from FinamPy.grpc import assets_service_pb2 as assets_service
from FinamPy.grpc.assets_service_pb2 import ClockRequest, ClockResponse  # Время на сервере
from FinamPy.grpc import marketdata_service_pb2 as marketdata_service
from FinLabPy.Schedule.MOEX import Futures  # Расписание торгов
from app.supported_base_asset import MAP  # Список базовых активов
from app.central_strike import get_list_of_strikes

# Логгер на уровне модуля
logger = logging.getLogger('FinamPy.Stream')
# Константы
DAYS_IN_YEAR = 365.0
RISK_FREE_RATE = 0.0  # Безрисковая ставка (0 для фьючерсов)

# ---------------------------------------------------------------------------
# Глобальные переменные состояния
# ---------------------------------------------------------------------------
fp_provider = None  # Глобальный экземпляр FinamPy
account_id = None   # Текущий идентификатор аккаунта
_full_ticker_to_map = {}   # {полный_тикер: тикер_из_MAP}

# Множество символов базовых фьючерсов, например {'RIZ6@RTSX', 'SiZ6@RTSX', ...}
# Заполняется в subscribe_base_assets и используется для фильтрации опционов.
base_symbols = set()

# Все опционные символы, которые уже были обработаны (чтобы не подписываться повторно)
_known_symbols = set()

# Последние наборы символов из позиций и заявок (для быстрой проверки изменений)
_last_positions_symbols = set()
_last_orders_symbols = set()
_subscribed_symbols = set()  # символы, на которые реально оформлена подписка
_subscription_dirty = False       # флаг необходимости перезапуска
_last_change_time = 0.0           # время последнего изменения состава
# Флаг запроса переподключения от watchdog или упавших потоков
_reconnect_requested = False

# Список всех активных потоков подписок
_stream_threads = []

# Блокировка для защиты от одновременного переподключения
_reconnect_lock = threading.Lock()


# Глобальный список для хранения данных аккаунта
_account_data = [{
    'positions': {},
    'cash': {},
    'equity': 0.0,
    'unrealized_profit': 0.0,
    'GM': 0.0,
    'portfolio_type': ''
}]

# Объект расписания торгов
schedule = Futures()

# Хранилище активных заявок: {order_id: { ... }}
active_orders = {}


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------
def black_76_price(F, K, T, sigma, option_type='call'):
    """Цена европейского опциона на фьючерс по модели Блэка-76."""
    if sigma <= 0 or T <= 0:
        return 0.0
    d1 = (math.log(F / K) + 0.5 * sigma ** 2 * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if option_type == 'call':
        price = math.exp(-RISK_FREE_RATE * T) * (F * norm.cdf(d1) - K * norm.cdf(d2))
    else:
        price = math.exp(-RISK_FREE_RATE * T) * (K * norm.cdf(-d2) - F * norm.cdf(-d1))
    return price

def black_76_vega(F, K, T, sigma):
    """Вега (производная цены по волатильности)."""
    if sigma <= 0 or T <= 0:
        return 0.0
    d1 = (math.log(F / K) + 0.5 * sigma ** 2 * T) / (sigma * math.sqrt(T))
    return F * math.exp(-RISK_FREE_RATE * T) * norm.pdf(d1) * math.sqrt(T)

def initial_volatility_guess(F, K, T, price, option_type='call'):
    """
    Быстрое начальное приближение IV для метода Ньютона.
    Использует формулу Бренера–Субраманьяна для ATM и корректировку для OTM.
    """
    if T <= 0 or price <= 0:
        return 0.2  # дефолт
    # Внутренняя стоимость
    intrinsic = max(0, F - K) if option_type == 'call' else max(0, K - F)
    if price <= intrinsic:
        return 0.001  # минимум
    # Для ATM опционов: sigma ≈ sqrt(2π/T) * (price / F) (приближение)
    if abs(F - K) / F < 0.05:  # около денег
        return math.sqrt(2 * math.pi) * price / (F * math.sqrt(T))
    else:
        # Для OTM используем бисекцию на 5 итерациях или возвращаем дефолт 0.2
        # Простой вариант: стартовая 0.2
        return 0.2

def implied_volatility_newton(market_price, F, K, T, option_type='call',
                              initial_guess=None, tolerance=1e-8, max_iter=100):
    """
    Вычисление IV методом Ньютона с аналитической вегой.
    Возвращает sigma (десятичная дробь) или None при неудаче.
    """
    if T <= 0 or market_price <= 0:
        return None
    intrinsic = max(0, F - K) if option_type == 'call' else max(0, K - F)
    if market_price < intrinsic:
        return None

    sigma = initial_guess if initial_guess is not None else initial_volatility_guess(F, K, T, market_price, option_type)
    sigma = max(sigma, 1e-5)  # защита от нуля

    for _ in range(max_iter):
        price = black_76_price(F, K, T, sigma, option_type)
        diff = price - market_price
        if abs(diff) < tolerance:
            return sigma
        vega = black_76_vega(F, K, T, sigma)
        if abs(vega) < 1e-12:
            break  # вега слишком мала, дальнейшие шаги бесполезны
        step = diff / vega
        sigma_new = sigma - step
        if sigma_new <= 0 or not math.isfinite(sigma_new):
            break
        sigma = sigma_new

    # Если не сошлось — пробуем Brent как fallback
    try:
        sigma = brentq(lambda s: black_76_price(F, K, T, s, option_type) - market_price,
                       1e-5, 10.0)
        return sigma
    except ValueError:
        return None

def calculate_greeks(F, K, T, sigma, option_type='call'):
    """
    Расчёт всех греков по модели Блэка-76 при r=0.
    Возвращает словарь с delta, gamma, theta, vega, rho.
    """
    if sigma <= 0 or T <= 0:
        return {'delta': None, 'gamma': None, 'theta': None, 'vega': None, 'rho': None}
    sqrt_T = math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * sigma ** 2 * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    pdf_d1 = norm.pdf(d1)

    if option_type == 'call':
        delta = norm.cdf(d1)
        theta = -(F * pdf_d1 * sigma) / (2 * sqrt_T)  # без r*F*... (r=0)
        rho = 0.0  # при r=0 rho всегда 0
    else:
        delta = -norm.cdf(-d1)
        theta = -(F * pdf_d1 * sigma) / (2 * sqrt_T)  # для put тоже (без r)
        rho = 0.0

    gamma = pdf_d1 / (F * sigma * sqrt_T)
    vega = F * pdf_d1 * sqrt_T

    return {
        'delta': delta,
        'gamma': gamma,
        'theta': theta,
        'vega': vega,
        'rho': rho,
    }


def to_float(decimal_field):
    """Универсальное преобразование Decimal-поля protobuf в float."""
    if decimal_field and hasattr(decimal_field, 'value') and decimal_field.value:
        try:
            return float(decimal_field.value)
        except (ValueError, TypeError):
            return 0.0
    return 0.0


def fmt_date(d):
    """Форматирует дату protobuf в строку YYYY-MM-DD."""
    if d is None:
        return None
    return f"{d.year:04d}-{d.month:02d}-{d.day:02d}"


def is_order_status_active(status: str) -> bool:
    """Определяет, является ли статус заявки активным (не терминальным)."""
    short_status = status.replace('ORDER_STATUS_', '')
    active_statuses = {
        'NEW',
        'PARTIALLY_FILLED',
        'PENDING_NEW',
        'PENDING_CANCEL',
        'REPLACED',
        'SUSPENDED',
        'FORWARDING',
        'WAIT',
        'WATCHING',
        'LINK_WAIT',
        'SL_GUARD_TIME',
        'SL_FORWARDING',
        'TP_GUARD_TIME',
        'TP_FORWARDING',
        'TP_CORRECTION',
        'TP_CORR_GUARD_TIME',
    }
    return short_status in active_statuses


def get_market_now():
    """Возвращает текущее время в часовой зоне биржи (Москва) как naive datetime."""
    return datetime.now(schedule.market_timezone).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Обработчик событий по собственным заявкам
# ---------------------------------------------------------------------------
def _on_order(order_state):
    """
    Обработчик событий по собственным заявкам.
    Поддерживает:
      - ответ с полем orders (список заявок),
      - одиночный объект OrderState.
    """
    try:
        # Если это ответ с полем orders — берём список, иначе считаем одиночной заявкой
        if hasattr(order_state, 'orders') and order_state.orders:
            order_states = order_state.orders
        else:
            order_states = [order_state]

        for order_state_item in order_states:
            order_id = order_state_item.order_id if hasattr(order_state_item, 'order_id') else None
            if not order_id:
                continue

            # --- Статус заявки ---
            status_raw = order_state_item.status if hasattr(order_state_item, 'status') else None
            if isinstance(status_raw, int):
                try:
                    status = orders_service.OrderStatus.Name(status_raw)
                except ValueError:
                    status = f"UNKNOWN_{status_raw}"
            else:
                status = str(status_raw) if status_raw else ''

            # --- Определяем активность ---
            is_active = is_order_status_active(status)

            if is_active:
                order = order_state_item.order if hasattr(order_state_item, 'order') else None
                if not order:
                    continue

                symbol = order.symbol if hasattr(order, 'symbol') else ''

                quantity = to_float(order.quantity) if hasattr(order, 'quantity') else 0.0
                price = to_float(order.limit_price) if hasattr(order, 'limit_price') else 0.0
                executed_quantity = to_float(order_state_item.executed_quantity) if hasattr(order_state_item,
                                                                                              'executed_quantity') else 0.0
                remaining_quantity = to_float(order_state_item.remaining_quantity) if hasattr(order_state_item,
                                                                                                'remaining_quantity') else 0.0

                # --- Сторона (side) — универсально, т.к. enum Side может отсутствовать ---
                side = ''
                if hasattr(order, 'side'):
                    side_raw = order.side
                    if isinstance(side_raw, int):
                        # Ищем подходящий enum в модуле orders_service
                        enum_class = None
                        for enum_name in ('Side', 'OrderSide', 'SideType', 'OrderOperation'):
                            if hasattr(orders_service, enum_name):
                                enum_class = getattr(orders_service, enum_name)
                                break

                        if enum_class is not None:
                            try:
                                side = enum_class.Name(side_raw)
                            except ValueError:
                                side = str(side_raw)
                        else:
                            # Если enum не найден — просто сохраняем число
                            side = str(side_raw)
                    else:
                        side = str(side_raw)

                # --- Сохраняем заявку ---
                active_orders[order_id] = {
                    'symbol': symbol,
                    'quantity': quantity,
                    'price': price,
                    'side': side,
                    'status': status,
                    'executed_quantity': executed_quantity,
                    'remaining_quantity': remaining_quantity,
                    'client_order_id': order.client_order_id if hasattr(order, 'client_order_id') else '',
                    'updated': datetime.now().strftime('%H:%M:%S')
                }
                logger.debug(f"Активная заявка #{order_id}: {active_orders[order_id]}")
            else:
                # Терминальный статус — удаляем заявку
                if order_id in active_orders:
                    removed = active_orders.pop(order_id)
                    logger.debug(f"Заявка #{order_id} удалена (статус: {status}). Была: {removed}")

        # Проверяем, не появились ли новые опционы в заявках
        update_option_subscriptions_from_portfolio()

    except Exception as e:
        logger.error(f"Ошибка в _on_order: {e}\n{traceback.format_exc()}")


# ---------------------------------------------------------------------------
# Подписка на события по заявкам
# ---------------------------------------------------------------------------
def subscribe_orders(fp_provider, account_id):
    """Подписка на события по собственным заявкам"""
    fp_provider.on_order.subscribe(_on_order)
    thread = Thread(
        target=fp_provider.subscribe_orders_thread,
        name='OrdersThread',
        args=(account_id,),
        daemon=True
    )
    thread.start()
    track_thread(thread)  # ← добавить
    logger.info(f"Подписка на собственные заявки аккаунта {account_id} запущена")
    return thread


# ---------------------------------------------------------------------------
# Хранилища котировок
# ---------------------------------------------------------------------------
base_asset_quotes = {}  # Котировки базовых активов: {ticker: {...}}
option_quotes = {}      # Котировки опционов: {symbol: {...}}
subscribed_option_symbols = set()  # Символы опционов, на которые уже подписаны
options_chains = {}               # {symbol: { ... }} — все опционы по базовым активам
_options_chains_loaded = False    # Флаг однократной загрузки

def fetch_last_quote_for_symbol(symbol):
    """
    Получает последнюю котировку по опциону через API LastQuote
    и сохраняет в option_quotes.
    """
    try:
        request = marketdata_service.QuoteRequest(symbol=symbol)
        response = fp_provider.call_function(fp_provider.marketdata_stub.LastQuote, request)

        if response is None:
            logger.warning(f"Не удалось получить последнюю котировку для {symbol}")
            return

        # response.quote — одиночная котировка (объект Quote)
        process_single_quote(response.quote)

    except Exception as e:
        logger.error(f"Ошибка при получении последней котировки для {symbol}: {e}")


def _set_if_present(target, source, field):
    """Обновляет поле только если оно реально присутствует в сообщении."""
    try:
        if source.HasField(field):
            # Decimal содержит строковое поле .value
            target[field] = float(getattr(source, field).value)
    except (ValueError, TypeError, AttributeError):
        target[field] = None

def _set_timestamp(target, source):
    """Заполняет timestamp из protobuf Timestamp (секунды + наносекунды) в МСК."""
    try:
        if source.HasField('timestamp'):
            ts = source.timestamp
            dt_msk = fp_provider.timestamp_to_msk_datetime(ts.seconds)
            target['timestamp'] = dt_msk.strftime('%Y-%m-%d %H:%M:%S')
    except (AttributeError, ValueError, TypeError):
        target['timestamp'] = None

def update_iv_and_greeks(symbol):
    """Вычисляет IV для ask/bid/last/theor и греки для опциона."""
    # Получаем параметры из хранилищ
    chain = options_chains.get(symbol)
    if not chain:
        return

    base_ticker = chain.get('base_ticker')
    if not base_ticker:
        return
    quote = base_asset_quotes.get(base_ticker)  # 'RIZ6' — совпадает с ключами хранилища
    if not quote:
        return
    if not quote.get('last'):
        bid = quote.get('bid')
        ask = quote.get('ask')
        F = (bid + ask) / 2 if bid and ask else None
    else:
        F = quote['last']
    if not F or F <= 0:
        return

    K = chain['strike']
    # Дата экспирации
    exp_date_str = chain['expiration_last_day']
    if not exp_date_str or exp_date_str == '0000-00-00':
        return
    exp_date = datetime.strptime(exp_date_str, '%Y-%m-%d').date()
    today = datetime.now().date()
    T = (exp_date - today).days / DAYS_IN_YEAR
    if T <= 0:
        return

    option_type = 'call' if chain['type'] == 'TYPE_CALL' else 'put'

    record = option_quotes.get(symbol)
    if not record:
        return

    # Расчёт IV для каждой цены
    for price_field, iv_field in [('ask', 'ask_iv'), ('bid', 'bid_iv'),
                                  ('last', 'last_iv'), ('theoretical_price', 'theor_iv')]:
        price = record.get(price_field)
        if price is None:
            record[iv_field] = None
            continue
        iv = implied_volatility_newton(price, F, K, T, option_type)
        record[iv_field] = iv * 100 if iv is not None else None  # в процентах

    # Для греков используем среднюю IV или IV от теоретической цены
    # Возьмём IV от последней сделки, если есть, иначе от ask/bid
    sigma_for_greeks = record.get('last_iv')
    if sigma_for_greeks is None:
        sigma_for_greeks = record.get('theor_iv') or record.get('ask_iv') or record.get('bid_iv')
    if sigma_for_greeks is None:
        sigma_for_greeks = record.get('implied_volatility')  # от биржи (если есть)
    if sigma_for_greeks is None:
        return
    sigma = sigma_for_greeks / 100.0  # переводим в десятичную

    greeks = calculate_greeks(F, K, T, sigma, option_type)
    record.update(greeks)  # добавит delta, gamma, theta, vega, rho

def process_single_quote(q):
    """Обрабатывает одну котировку (из подписки или запроса последней цены)."""
    full_symbol = q.symbol
    ticker = full_symbol.split('@')[0] if '@' in full_symbol else full_symbol

    # --- Базовые активы (фьючерсы) ---
    if full_symbol in base_symbols or ticker in MAP:
        map_ticker = _full_ticker_to_map.get(ticker, ticker)  # 'RIZ6' → 'RI'
        if map_ticker not in base_asset_quotes:
            base_asset_quotes[map_ticker] = {
                'timestamp': None,
                'ask': None, 'bid': None, 'last': None,
                'ask_size': None, 'bid_size': None, 'last_size': None,
                'time': None
            }
        record = base_asset_quotes[map_ticker]
        _set_timestamp(record, q)
        for field in ('ask', 'bid', 'last', 'ask_size', 'bid_size', 'last_size'):
            _set_if_present(record, q, field)
        record['time'] = datetime.now().strftime('%H:%M:%S')

    # --- Опционы ---
    elif full_symbol in subscribed_option_symbols:
        if full_symbol not in option_quotes:
            option_quotes[full_symbol] = {
                'timestamp': None,
                'ask': None, 'ask_iv': None, 'ask_size': None, 'bid': None, 'bid_iv': None, 'bid_size': None,
                'last': None, 'last_iv': None, 'last_size': None,
                'open_interest': None, 'implied_volatility': None,
                'theoretical_price': None,
                'theor_iv': None,
                'delta': None, 'gamma': None, 'theta': None, 'vega': None, 'rho': None,
                'time': None
            }
        record = option_quotes[full_symbol]
        for field in ('ask', 'bid', 'last', 'ask_size', 'bid_size', 'last_size'):
            _set_if_present(record, q, field)
        _set_timestamp(record, q)
        _set_if_present(record, q, 'open_interest')

        if q.HasField('option'):
            opt = q.option
            for field in ('open_interest', 'implied_volatility', 'theoretical_price',
                          'delta', 'gamma', 'theta', 'vega', 'rho'):
                _set_if_present(record, opt, field)

        record['time'] = datetime.now().strftime('%H:%M:%S')

        # --- Расчёт IV и греков ---
        update_iv_and_greeks(full_symbol)


# ---------------------------------------------------------------------------
# Обработчик котировок (базовые активы + опционы)
# ---------------------------------------------------------------------------
def _on_quote(quote):
    """Обработчик котировок базовых активов и опционов."""
    if not quote.quote:
        logger.warning("Получена пустая котировка")
        return

    for q in quote.quote:
        process_single_quote(q)



# ---------------------------------------------------------------------------
# Подписка на котировки базовых активов
# ---------------------------------------------------------------------------
def subscribe_base_assets(fp_provider):
    global base_symbols, _full_ticker_to_map
    base_symbols.clear()
    _full_ticker_to_map.clear()

    for ticker in MAP.keys():
        dataname = f'SPBFUT.{ticker}'
        try:
            finam_board, ticker_code = fp_provider.dataname_to_finam_board_ticker(dataname)
            mic = fp_provider.get_mic(finam_board, ticker_code)
            symbol = f'{ticker_code}@{mic}'
            base_symbols.add(symbol)
            _full_ticker_to_map[ticker_code] = ticker   # ← добавить
        except Exception as e:
            logger.error(f"Не удалось определить биржу для {ticker}: {e}")

    logger.info(f"Базовые активы собраны: {list(base_symbols)}")



# ---------------------------------------------------------------------------
# Проверка появления новых опционов в портфеле/заявках
# ---------------------------------------------------------------------------
# Глобальная переменная для debounce
_last_restart_time = 0.0

# Хранилище активных потоков подписки
_quotes_threads = []

def update_option_subscriptions_from_portfolio():
    """
    Обновляет subscribed_option_symbols новыми опционами из портфеля/заявок.
    Исключает фьючерсы (инструменты из MAP и base_symbols).
    Устанавливает флаг _subscription_dirty для отложенного перезапуска подписки.
    """
    global subscribed_option_symbols, _last_positions_symbols, _last_orders_symbols
    global _subscription_dirty, _last_change_time

    # Текущие символы из позиций портфеля с ненулевым количеством
    raw_positions = _account_data[0].get('positions', {})
    positions = {sym: pos for sym, pos in raw_positions.items() if float(pos['quantity']) != 0}
    current_positions = set(positions.keys())

    # Текущие символы из активных заявок
    current_orders = set()
    for order in active_orders.values():
        symbol = order.get('symbol', '')
        if symbol:
            current_orders.add(symbol)

    # Если ничего не изменилось — выходим (быстрая проверка)
    if current_positions == _last_positions_symbols and current_orders == _last_orders_symbols:
        return

    # Обновляем сохранённые множества
    _last_positions_symbols = current_positions
    _last_orders_symbols = current_orders

    # Все символы из портфеля и заявок
    all_symbols = current_positions | current_orders

    # Оставляем только опционы:
    # 1) исключаем символы, которые есть в base_symbols (полные символы фьючерсов)
    # 2) исключаем тикеры, которые есть в MAP (тикеры фьючерсов, например RIZ6, SiZ6)
    option_symbols = set()
    for s in all_symbols:
        if s in base_symbols:
            continue
        ticker = s.split('@')[0]  # берём часть до @
        if ticker in MAP:
            continue
        option_symbols.add(s)

    # Новые опционы, которых ещё нет в подписке
    new_symbols = option_symbols - subscribed_option_symbols
    if not new_symbols:
        return



    # Добавляем новые символы в отслеживание
    subscribed_option_symbols.update(new_symbols)
    logger.info(f"Добавлены новые опционы в отслеживание: {new_symbols}")
    # Предзаполняем котировки новым опционам (особенно важно для малоликвидных)
    for symbol in new_symbols:
        fetch_last_quote_for_symbol(symbol)

    # Помечаем, что подписку нужно перезапустить (отложенно)
    _subscription_dirty = True
    _last_change_time = _time.time()



_quotes_thread = None

def restart_quotes_subscription():
    """Перезапускает подписку на котировки с актуальным списком символов."""
    global _quotes_threads

    # Отписываемся от старого обработчика, чтобы старые события не дублировались
    if fp_provider is not None:
        fp_provider.on_quote.unsubscribe(_on_quote)

    # Запускаем новый поток подписки (он сам подпишется заново)
    new_threads = start_quotes_subscription(fp_provider) or []
    _quotes_threads = new_threads

# ---------------------------------------------------------------------------
# Загрузка цепочек опционов
# ---------------------------------------------------------------------------
def load_options_chains(fp_provider):
    global _options_chains_loaded
    if _options_chains_loaded:
        return options_chains
    _options_chains_loaded = True

    for ticker, params in MAP.items():
        strike_step = params['strike_step']
        strikes_count = params['max_strikes_count']

        try:
            # Получаем список дат экспирации (уникальные, в формате 'YYYY-MM-DD')
            expirations = get_option_expirations(ticker)
            expiration_dates = sorted(set(exp['expiration_date'] for exp in expirations))
            print(f'Даты экспирации опционов базового актива {ticker}: {expiration_dates}')

            # Получаем цену базового актива
            quote = base_asset_quotes.get(ticker)
            if not quote or quote.get('last') is None:
                logger.warning(f"Нет цены для {ticker}, пропускаем загрузку цепочки")
                continue
            base_price = quote['last']

            # Формируем нужные страйки
            required_strikes = set(get_list_of_strikes(base_price, strike_step, strikes_count))

            # Определяем символ для API
            dataname = f'SPBFUT.{ticker}'
            finam_board, ticker_code = fp_provider.dataname_to_finam_board_ticker(dataname)
            mic = fp_provider.get_mic(finam_board, ticker_code)
            underlying_symbol = f'{ticker_code}@{mic}'

            # Перебираем все даты экспирации
            for exp_date_str in expiration_dates:
                expiration_date_obj = datetime.strptime(exp_date_str, "%Y-%m-%d").date()
                year = expiration_date_obj.year
                month = expiration_date_obj.month
                day = expiration_date_obj.day
                # --- Запрашиваем полную цепочку опционов ---
                request = assets_service.OptionsChainRequest(
                    underlying_symbol=underlying_symbol,
                    expiration_date={"year": year, "month": month, "day": day}
                )
                response = fp_provider.call_function(fp_provider.assets_stub.OptionsChain, request)

                if response is None:
                    logger.error(f"Не удалось получить цепочку опционов для {underlying_symbol} на {exp_date_str}")
                    continue

                filtered_count = 0
                for opt in response.options:
                    strike = to_float(opt.strike)
                    if strike not in required_strikes:
                        continue

                    try:
                        opt_type = assets_service.Option.Type.Name(opt.type)
                    except ValueError:
                        opt_type = str(opt.type)

                    options_chains[opt.symbol] = {
                        'symbol': opt.symbol,
                        'type': opt_type,
                        'contract_size': to_float(opt.contract_size),
                        'trade_first_day': fmt_date(opt.trade_first_day),
                        'trade_last_day': fmt_date(opt.trade_last_day),
                        'strike': strike,
                        'multiplier': to_float(opt.multiplier),
                        'expiration_first_day': fmt_date(opt.expiration_first_day),
                        'expiration_last_day': fmt_date(opt.expiration_last_day),
                        'base_ticker': ticker,
                    }
                    filtered_count += 1

                logger.info(f"Цепочка опционов для {underlying_symbol} на {exp_date_str}: "
                            f"загружено {filtered_count} из {len(response.options)} опционов "
                            f"(страйков: {len(required_strikes)})")

        except Exception as e:
            logger.error(f"Ошибка при получении цепочки опционов для {ticker}: {e}")

    logger.info(f"Всего опционов загружено: {len(options_chains)}")
    # === ВРЕМЕННЫЙ ВЫВОД ДЛЯ ПРОВЕРКИ ===
    # print(f"\n=== options_chains ({len(options_chains)} символов) ===")
    # for symbol, data in options_chains.items():
        # print(f"{symbol}: {data}")
    # print("=====================================\n")
    return options_chains

def start_quotes_subscription(fp_provider):
    """Подписка на базовые активы + все опционы из subscribed_option_symbols."""
    global subscribed_option_symbols, _subscribed_symbols

    all_symbols = set(base_symbols) | subscribed_option_symbols

    if not all_symbols:
        logger.warning("Нет символов для подписки на котировки")
        return []

    fp_provider.on_quote.subscribe(_on_quote)

    thread = Thread(
        target=fp_provider.subscribe_quote_thread,
        name='QuotesThread',
        args=(list(all_symbols),),
        daemon=True
    )
    thread.start()
    track_thread(thread)  # ← ЭТА СТРОКА БЫЛА ПРОПУЩЕНА

    _subscribed_symbols = set(all_symbols)
    logger.info(f"Запущен поток подписки на {len(all_symbols)} символов: {thread.name}")
    return [thread]


# ---------------------------------------------------------------------------
# Обработчик информации об аккаунте
# ---------------------------------------------------------------------------
def _on_account_info(account_response):
    """Обработчик информации об аккаунте из стрим-подписки"""
    try:
        data = _account_data[0]

        if not account_response:
            logger.warning('Получен пустой ответ по аккаунту из стрим-подписки')
            return

        if not hasattr(account_response, 'positions'):
            logger.warning('В ответе нет атрибута positions')
            return

        # --- Сохраняем базовую информацию ---
        if hasattr(account_response, 'account_id'):
            data['account_id'] = account_response.account_id
        if hasattr(account_response, 'status'):
            data['status'] = account_response.status

        # --- Equity и unrealized_profit ---
        if hasattr(account_response, 'equity') and account_response.equity:
            data['equity'] = to_float(account_response.equity)
        if hasattr(account_response, 'unrealized_profit') and account_response.unrealized_profit:
            data['unrealized_profit'] = to_float(account_response.unrealized_profit)

        # --- Денежные средства ---
        data['cash'] = {}
        if hasattr(account_response, 'cash'):
            for money_item in account_response.cash:
                currency = money_item.currency_code if money_item.currency_code else 'RUB'
                amount = float(money_item.units) + float(money_item.nanos) / 1_000_000_000 if money_item.units else 0.0
                data['cash'][currency] = {
                    'balance': amount,
                    'blocked': 0.0,
                    'free': amount,
                }

        # --- Определяем тип портфеля ---
        # Проверяем наличие поля через DESCRIPTOR, чтобы избежать ошибок HasField
        if 'portfolio_forts' in account_response.DESCRIPTOR.fields_by_name and account_response.HasField('portfolio_forts'):
            data['portfolio_type'] = 'FORTS'
            forts = account_response.portfolio_forts
            data['margin'] = {
                'available_cash': to_float(forts.available_cash),
                'money_reserved': to_float(forts.money_reserved),
            }
            data['cash']['RUB'] = {
                'balance': to_float(forts.available_cash),
                'blocked': to_float(forts.money_reserved),
                'free': to_float(forts.available_cash),
                'GM': (to_float(forts.money_reserved) / data['equity']) * 100 if data['equity'] else 0.0,
            }
        elif 'portfolio_mc' in account_response.DESCRIPTOR.fields_by_name and account_response.HasField('portfolio_mc'):
            data['portfolio_type'] = 'MC'
            mc = account_response.portfolio_mc
            data['margin'] = {
                'available_cash': to_float(mc.available_cash),
                'initial_margin': to_float(mc.initial_margin),
                'maintenance_margin': to_float(mc.maintenance_margin),
            }
        elif 'portfolio_mct' in account_response.DESCRIPTOR.fields_by_name and account_response.HasField('portfolio_mct'):
            data['portfolio_type'] = 'MCT'
            mct = account_response.portfolio_mct
            data['margin'] = {
                'available_cash': to_float(mct.available_cash),
                'initial_margin': to_float(mct.initial_margin),
                'maintenance_margin': to_float(mct.maintenance_margin),
            }

        # --- Парсим позиции ---
        data['positions'] = {}

        for position in account_response.positions:
            try:
                symbol = position.symbol if hasattr(position, 'symbol') else 'UNKNOWN'
                if symbol == 'UNKNOWN':
                    continue  # пропускаем позиции без символа

                quantity = to_float(position.quantity) if hasattr(position, 'quantity') else 0.0
                current_price = to_float(position.current_price) if hasattr(position, 'current_price') else 0.0
                average_price = to_float(position.average_price) if hasattr(position, 'average_price') else 0.0
                maintenance_margin = to_float(position.maintenance_margin) if hasattr(position, 'maintenance_margin') else 0.0
                daily_pnl = to_float(position.daily_pnl) if hasattr(position, 'daily_pnl') else 0.0
                unrealized_pnl = to_float(position.unrealized_pnl) if hasattr(position, 'unrealized_pnl') else 0.0

                data['positions'][symbol] = {
                    'quantity': quantity,
                    'current_price': current_price,
                    'average_price': average_price,
                    'maintenance_margin': maintenance_margin,
                    'daily_pnl': daily_pnl,
                    'unrealized_pnl': unrealized_pnl,
                }
            except Exception as e:
                logger.error(f"Ошибка при парсинге позиции: {e}")

        # Проверяем, не появились ли новые опционы в портфеле
        update_option_subscriptions_from_portfolio()

    except Exception as e:
        logger.error(f"Необработанная ошибка в _on_account_info: {e}\n{traceback.format_exc()}")


# ---------------------------------------------------------------------------
# Подписка на поток информации об аккаунте
# ---------------------------------------------------------------------------
def start_account_stream(fp_provider, account_id):
    """Запускает поток подписки на информацию об аккаунте"""
    fp_provider.on_account_info.subscribe(_on_account_info)
    stream_thread = Thread(
        target=fp_provider.subscribe_account_thread,
        name='AccountThread',
        args=(account_id,),
        daemon=True
    )
    stream_thread.start()
    track_thread(stream_thread)  # ← добавить
    logger.info(f"Подписка на аккаунт {account_id} запущена")
    return stream_thread


# ---------------------------------------------------------------------------
# Ожидание торговой сессии
# ---------------------------------------------------------------------------
def wait_for_trading_session(stop_event):
    """Ожидает начала торговой сессии."""
    while not stop_event.is_set():
        now = get_market_now()
        seconds_to_trade = schedule.time_until_trade(now).total_seconds()

        if seconds_to_trade <= 0:
            logger.info("Торговая сессия активна. Начинаем работу.")
            return

        wait_seconds = min(seconds_to_trade, 60)
        logger.info(f"До начала торгов {seconds_to_trade:.0f} сек. Ждём {wait_seconds:.0f} сек...")
        stop_event.wait(wait_seconds)


def wait_for_base_asset_prices(stop_event, timeout=30):
    """Ожидает появления котировок по всем базовым активам."""
    deadline = datetime.now().timestamp() + timeout
    while not stop_event.is_set():
        missing = [t for t in MAP if t not in base_asset_quotes]
        if not missing:
            return True
        if datetime.now().timestamp() > deadline:
            logger.warning(f"Не удалось получить котировки по всем базовым активам за {timeout} сек. Отсутствуют: {missing}")
            return False
        sleep(0.5)
    return False



# ---------------------------------------------------------------------------
# Отладочный вывод котировок (периодический)
# ---------------------------------------------------------------------------
def print_quotes_periodically(stop_event):
    """Раз в 5 секунд выводит содержимое base_asset_quotes и option_quotes."""
    while not stop_event.is_set():
        stop_event.wait(10)

        # --- Вывод котировок базовых активов ---
        if base_asset_quotes:
            print(f"\n=== base_asset_quotes ({len(base_asset_quotes)} тикеров) ===")
            for ticker, quote in base_asset_quotes.items():
                print(f"{ticker}: {quote}")
        else:
            print("\n=== base_asset_quotes пуст ===")

        # --- Вывод котировок опционов ---
        if option_quotes:
            print(f"\n=== option_quotes ({len(option_quotes)} символов) ===")
            for symbol, quote in option_quotes.items():
                print(f"{symbol}: {quote}")
        else:
            print("\n=== option_quotes пуст ===")


# ---------------------------------------------------------------------------
# Управление соединением и переподключением
# ---------------------------------------------------------------------------
def close_provider():
    global fp_provider
    if fp_provider is not None:
        try:
            # Отписываемся от всех событий (как в вашем примере)
            fp_provider.on_quote.unsubscribe(_on_quote)
            fp_provider.on_order.unsubscribe(_on_order)
            fp_provider.on_account_info.unsubscribe(_on_account_info)

            # Закрываем канал
            fp_provider.close_channel()
        except Exception:
            pass
        finally:
            fp_provider = None


def reset_state():
    """Сбрасывает все глобальные состояния перед переподключением."""
    global base_symbols, _known_symbols, _last_positions_symbols, _last_orders_symbols
    global _subscribed_symbols, _options_chains_loaded, subscribed_option_symbols
    global _stream_threads, option_quotes, options_chains, active_orders, _subscription_dirty
    global _full_ticker_to_map

    base_symbols.clear()
    _full_ticker_to_map.clear()
    _known_symbols.clear()
    _last_positions_symbols.clear()
    _last_orders_symbols.clear()
    _subscribed_symbols.clear()
    subscribed_option_symbols.clear()
    _stream_threads.clear()
    option_quotes.clear()
    options_chains.clear()
    active_orders.clear()
    _options_chains_loaded = False
    _subscription_dirty = False


def track_thread(thread):
    """Добавляет поток в список отслеживаемых и чистит завершённые."""
    _stream_threads.append(thread)
    # Удаляем мёртвые потоки, чтобы список не разрастался
    for t in _stream_threads[:]:
        if not t.is_alive():
            _stream_threads.remove(t)


def get_backoff_delay(attempt):
    """Экспоненциальная задержка с джиттером: 5с, 10с, 20с, 40с, ... до 300с."""
    base = min(5 * (2 ** attempt), 300)
    jitter = random.uniform(0, 0.3 * base)
    return base + jitter


def initialize_connection(stop_event):
    """
    Полная инициализация подключения: создание провайдера,
    подписка на все потоки и загрузка данных.
    """
    global fp_provider, account_id, _options_chains_loaded

    # 1. Закрываем старый канал
    close_provider()

    # 2. Создаём новый экземпляр FinamPy
    fp_provider = FinamPy()
    if not fp_provider.account_ids:
        fp_provider.account_ids = list(fp_provider.token_details().account_ids)
    if not fp_provider.account_ids:
        raise RuntimeError("Не найдено ни одного торгового счёта")
    account_id = fp_provider.account_ids[0]
    logger.info(f"Инициализация: работа с аккаунтом {account_id}")

    # 3. Сбрасываем все глобальные состояния
    reset_state()

    # 4. Последовательность подписок (как в исходном main)
    subscribe_base_assets(fp_provider)          # заполняет base_symbols
    start_quotes_subscription(fp_provider)      # базовые активы
    wait_for_base_asset_prices(stop_event, timeout=30)
    load_options_chains(fp_provider)            # загружает цепочки опционов
    # start_quotes_subscription(fp_provider)      # перезапуск с опционами
    subscribe_orders(fp_provider, account_id)   # заявки
    start_account_stream(fp_provider, account_id)  # аккаунт

    logger.info("Все подписки активны.")


def perform_reconnect(stop_event):
    """Выполняет переподключение с защитой от повторного входа."""
    if not _reconnect_lock.acquire(blocking=False):
        logger.info("Переподключение уже выполняется, пропускаем.")
        return

    try:
        logger.warning("Начинаем процедуру переподключения...")
        initialize_connection(stop_event)
        logger.info("Переподключение выполнено успешно.")
    except Exception as e:
        logger.error(f"Ошибка при переподключении: {e}\n{traceback.format_exc()}")
    finally:
        _reconnect_lock.release()


def watchdog(stop_event):
    """
    Периодически проверяет доступность API через запрос серверного времени.
    Если запрос не проходит — инициирует переподключение.
    """
    global _reconnect_requested

    while not stop_event.is_set():
        if fp_provider is not None:
            try:
                # Проверка живости канала: получаем время на сервере
                clock: ClockResponse = fp_provider.call_function(
                    fp_provider.assets_stub.Clock,
                    ClockRequest()
                )

                if clock is None:
                    raise ConnectionError("ClockRequest вернул None — соединение потеряно")

                # Дополнительно можно проверить, что время адекватное
                dt_server = datetime.fromtimestamp(
                    clock.timestamp.seconds + clock.timestamp.nanos / 1e9,
                    fp_provider.tz_msk
                )
                logger.debug(f"Watchdog: серверное время {dt_server:%d.%m.%Y %H:%M:%S} — соединение живо")

                if _reconnect_requested:
                    logger.info("Соединение восстановлено (watchdog).")
                _reconnect_requested = False

            except Exception as e:
                logger.error(f"Watchdog: соединение потеряно: {e}")
                _reconnect_requested = True

        stop_event.wait(10)  # проверка каждые 10 секунд



# ---------------------------------------------------------------------------
# Основная функция
# ---------------------------------------------------------------------------
def main():
    logger.info("Запуск программы мониторинга аккаунта по расписанию биржи")
    global fp_provider, account_id, _reconnect_requested, _subscription_dirty, _last_change_time

    stop_event = Event()

    def signal_handler(signum, frame):
        logger.info("Получен сигнал остановки. Завершаем работу...")
        stop_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    Thread(target=print_quotes_periodically, args=(stop_event,), daemon=True).start()
    Thread(target=watchdog, args=(stop_event,), daemon=True).start()

    try:
        while not stop_event.is_set():
            wait_for_trading_session(stop_event)
            if stop_event.is_set():
                break

            # --- Подключение (первичное или после обрыва) ---
            attempt = 0
            while not stop_event.is_set():
                try:
                    initialize_connection(stop_event)
                    logger.info(f"Соединение установлено. Аккаунт: {account_id}")
                    attempt = 0
                    break
                except Exception as e:
                    logger.error(f"Не удалось инициализировать соединение: {e}")
                    delay = get_backoff_delay(attempt)
                    attempt += 1
                    logger.info(f"Повторная попытка через {delay:.1f} сек...")
                    stop_event.wait(delay)

            if stop_event.is_set():
                break

            # --- Основной цикл работы ---
            while not stop_event.is_set():
                now = get_market_now()
                if not schedule.trade_session(now):
                    logger.info("Торговая сессия закончилась.")
                    break

                # Обрыв соединения → выходим во внешний цикл для переподключения
                if _reconnect_requested or not all(t.is_alive() for t in _stream_threads):
                    logger.warning("Обнаружен обрыв соединения. Переподключаемся...")
                    _reconnect_requested = False
                    break

                # Изменение состава опционов → перезапуск подписки
                if _subscription_dirty and _time.time() - _last_change_time >= 1.0:
                    _subscription_dirty = False
                    logger.info("Перезапуск подписки после накопления изменений")
                    restart_quotes_subscription()

                stop_event.wait(1)

    except Exception as e:
        logger.error(f"Критическая ошибка в main: {e}\n{traceback.format_exc()}")
    finally:
        stop_event.set()
        close_provider()
        logger.info("Программа остановлена")


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%d.%m.%Y %H:%M:%S',
        level=logging.INFO,
        handlers=[
            logging.FileHandler('FINAM_Stream.log', encoding='utf-8'),
            logging.StreamHandler()
        ],
        force=True
    )

    main()
