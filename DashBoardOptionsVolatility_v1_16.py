import os.path
from math import isnan
import dash
from dash import dcc, Input, Output, callback, dash_table, State
from dash import html
import dash_bootstrap_components as dbc
import dash_daq as daq
from dash.exceptions import PreventUpdate
from datetime import datetime, timedelta, UTC  # Дата и время
from datetime import timedelta
from pytz import utc
import requests
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.express as px
import pandas as pd
from app.central_strike import _calculate_central_strike, get_list_of_strikes
from app.supported_base_asset import MAP
from string import Template
import time
import random
import inspect
import threading
import atexit

from FinamPy.grpc.marketdata_service_pb2 import SubscribeBarsResponse, TimeFrame  # Подписка на бары Финама
from FinLabPy.Config import brokers, default_broker  # Все брокеры и брокер по умолчанию
from FinLabPy.Core import Bar, bars_to_df  # Бар, перевод бар в pandas DataFrame

# temp_str = 'C:\\Users\\sftpuser\\Position\\$name_file' # виртуальная машина
# temp_str = 'C:\\Users\\ashad\\Yandex.Disk\\_ИИС\\Position\\$name_file' # домашний компьютер
temp_str = 'C:\\Users\\шадрин\\YandexDisk\\_ИИС\\Position\\$name_file' # ноутбук
temp_obj = Template(temp_str)
# Каталог data/Finam с CSV-файлами
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR_FINAM = os.path.join(BASE_DIR, "data", "Finam")

# ============================ ФИНАМ-СТРИМ (встроенный блок) ============================
import logging  # Модуль для ведения логов
from threading import Thread, Event  # Модуль для создания потоков и событий
from datetime import datetime  # Модуль для работы с датой и временем
from time import sleep  # Функция для приостановки выполнения программы
import time as _time
import signal
import traceback  # Модуль для получения полной информации об ошибке
import math
import os
import queue  # Очередь для фоновых задач I/O (очистка CSV, LastQuote)
from scipy.stats import norm
from scipy.optimize import brentq
from accfifo import Entry, FIFO

# Импортируем только те функции MOEX API, которые реально используются в этом модуле
from moex_api import get_option_expirations
from FinamPy import FinamPy  # Основной класс библиотеки FinamPy
from FinamPy.grpc import orders_service_pb2 as orders_service
from FinamPy.grpc import assets_service_pb2 as assets_service
from FinamPy.grpc import accounts_service_pb2 as accounts_service  # Счета (GetAccount)
from FinamPy.grpc.assets_service_pb2 import (
    ClockRequest,
    ClockResponse,
)  # Время на сервере
from FinamPy.grpc import marketdata_service_pb2 as marketdata_service
from FinLabPy.Schedule.MOEX import Futures  # Расписание торгов
from app.supported_base_asset import MAP  # Список базовых активов
from app.central_strike import get_list_of_strikes

# Логгер на уровне модуля
logger = logging.getLogger("FinamPy.Stream")
# Константы
DAYS_IN_YEAR = 365.0
RISK_FREE_RATE = 0.0  # Безрисковая ставка (0 для фьючерсов)
# ---------------------------------------------------------------------------
# Глобальные переменные состояния
# ---------------------------------------------------------------------------
fp_provider = None  # Глобальный экземпляр FinamPy
account_id = None  # Текущий идентификатор аккаунта
_full_ticker_to_map = {}  # {полный_тикер: тикер_из_MAP}
# Время последнего появления символа в портфеле/заявках: {symbol: timestamp}
_symbol_last_seen = {}

# Множество символов базовых фьючерсов, например {'RIZ6@RTSX', 'SiZ6@RTSX', ...}
# Заполняется в subscribe_base_assets и используется для фильтрации опционов.
base_symbols = set()


# Последние наборы символов из позиций и заявок (для быстрой проверки изменений)
_last_positions_symbols = set()
_last_orders_symbols = set()
# Момент времени, когда символ перестал появляться в событиях: {symbol: timestamp}.
# Используется для отложенной очистки CSV (позиция считается закрытой,
# если она отсутствует в потоке дольше _POSITION_CLEANUP_DELAY).
_symbol_closed_at = {}
# Задержка (сек) перед удалением сделок закрытых позиций
# которые исчезли из событий аккаунта (защита от «рассинхрона» потока).
_POSITION_CLEANUP_DELAY = 30.0
# Хранилище устаревших опционов для логирования
_previous_obsolete = set()
_subscription_dirty = (
    False  # флаг необходимости немедленного перезапуска (для новых опционов)
)
_cleanup_dirty = False  # флаг необходимости отложенной очистки (для старых опционов)
_last_cleanup_check = 0.0  # время последней попытки очистки
# Время последней постановки задачи проверки портфеля/очистки CSV в очередь.
# Нужно для дедупликации: при старте подписки на сделки приходит исторический
# снапшот внутри пакетов, каждый пакет → отдельный _on_trade → в очередь
# ставится отдельная задача. Чтобы не выполнять 4+ одинаковых очисток подряд,
# ограничиваем частоту постановки задач.
_LAST_TRADES_CLEANUP_INTERVAL = 5.0  # сек
_last_trades_cleanup_enqueued = 0.0

# Флаг запроса переподключения от watchdog или упавших потоков
_reconnect_requested = False

# Список всех активных потоков подписок
_stream_threads = []

# Блокировка для защиты от одновременного переподключения
_reconnect_lock = threading.Lock()
# Блокировка для синхронизации доступа к словарям сделок
_trades_lock = threading.Lock()

# Очередь фоновых задач ввода-вывода.
# Сюда ставятся «тяжёлые» операции (очистка CSV, сетевые запросы LastQuote),
# чтобы не блокировать gRPC-потоки событий (_on_order, _on_account_info).
_io_task_queue = queue.Queue()


# Глобальный список для хранения данных аккаунта
_account_data = [
    {
        "positions": {},
        "cash": {},
        "equity": 0.0,
        "unrealized_profit": 0.0,
        "GM": 0.0,
        "portfolio_type": "",
    }
]

# Объект расписания торгов
schedule = Futures()

# Хранилище активных заявок: {order_id: { ... }}
active_orders = {}

CSV_ORDERS_COLUMNS = [
    "transact_at",
    "order_num",
    "opt_base",
    "ticker",
    "opt_type",
    "strike",
    "expdate",
    "operation",
    "volume",
    "price",
    "value",
    "type",
    "status",
    "exec",
    "remain",
    "updated",
    "order_iv",
]

# Хранилище сделок: {trade_id: { ... }}
trades = {}

# Архивная копия сделок (полная история, никогда не очищается)
trades_all = {}

# Колонки DataFrame позиций (состав полей записи позиции в _on_account_info)
POSITION_COLUMNS = [
    'ticker', 'net_pos', 'strike', 'opt_type', 'expdate', 'option_base',
    'OpenDateTime', 'OpenPrice', 'OpenIV', 'time_last', 'bid', 'last', 'ask',
    'theor', 'QuikVola', 'bidIV', 'lastIV', 'askIV',
    'Delta', 'Gamma', 'Theta', 'Vega', 'TrueVega', 'u_pnl',
]


class QuoteSubscription:
    """Управляемая подписка на котировки с возможностью остановки."""

    def __init__(self, fp_provider, symbols, name="QuotesThread"):
        self.fp_provider = fp_provider
        self.symbols = symbols
        self.name = name
        self.stream = None
        self.stop_event = threading.Event()
        self.thread = None

    def _run(self):
        """Основной цикл подписки."""
        while not self.stop_event.is_set():
            try:
                self.stream = self.fp_provider.marketdata_stub.SubscribeQuote(
                    request=marketdata_service.SubscribeQuoteRequest(
                        symbols=self.symbols
                    ),
                    metadata=(self.fp_provider.metadata,),
                )
                # Читаем события, пока не запрошена остановка
                while not self.stop_event.is_set():
                    event = next(self.stream)
                    self.fp_provider.on_quote.trigger(event)
            except ValueError as e:
                # Канал закрыт. Логируем только если остановка не была запрошена
                # намеренно, чтобы была видна причина завершения потока.
                if not self.stop_event.is_set():
                    logger.warning(f"Канал подписки закрыт ({self.name}): {e}")
                break
            except Exception as e:
                if self.stop_event.is_set():
                    break
                logger.error(f"Ошибка подписки на котировки ({self.name}): {e}")
                sleep(5)  # повторная попытка через 5 секунд

    def start(self):
        """Запускает поток подписки."""
        self.thread = Thread(target=self._run, name=self.name, daemon=True)
        self.thread.start()

    def stop(self):
        """Останавливает поток и отменяет gRPC-стрим."""
        self.stop_event.set()
        if self.stream is not None:
            try:
                self.stream.cancel()
            except Exception:
                pass
        if self.thread is not None:
            self.thread.join(timeout=10)


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------
def black_76_price(F, K, T, sigma, option_type="call"):
    """Цена европейского опциона на фьючерс по модели Блэка-76."""
    if sigma <= 0 or T <= 0:
        return 0.0
    d1 = (math.log(F / K) + 0.5 * sigma**2 * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if option_type == "call":
        price = math.exp(-RISK_FREE_RATE * T) * (F * norm.cdf(d1) - K * norm.cdf(d2))
    else:
        price = math.exp(-RISK_FREE_RATE * T) * (K * norm.cdf(-d2) - F * norm.cdf(-d1))
    return price


def black_76_vega(F, K, T, sigma):
    """Вега (производная цены по волатильности)."""
    if sigma <= 0 or T <= 0:
        return 0.0
    d1 = (math.log(F / K) + 0.5 * sigma**2 * T) / (sigma * math.sqrt(T))
    return F * math.exp(-RISK_FREE_RATE * T) * norm.pdf(d1) * math.sqrt(T)


def initial_volatility_guess(F, K, T, price, option_type="call"):
    """
    Быстрое начальное приближение IV для метода Ньютона.
    Использует формулу Бренера–Субраманьяна для ATM и корректировку для OTM.
    """
    if T <= 0 or price <= 0:
        return 0.2  # дефолт
    # Внутренняя стоимость
    intrinsic = max(0, F - K) if option_type == "call" else max(0, K - F)
    if price <= intrinsic:
        return 0.001  # минимум
    # Для ATM опционов: sigma ≈ sqrt(2π/T) * (price / F) (приближение)
    if abs(F - K) / F < 0.05:  # около денег
        return math.sqrt(2 * math.pi) * price / (F * math.sqrt(T))
    else:
        # Для OTM используем бисекцию на 5 итерациях или возвращаем дефолт 0.2
        # Простой вариант: стартовая 0.2
        return 0.2


def implied_volatility_newton(
    market_price,
    F,
    K,
    T,
    option_type="call",
    initial_guess=None,
    tolerance=1e-8,
    max_iter=100,
):
    """
    Вычисление IV методом Ньютона с аналитической вегой.
    Возвращает sigma (десятичная дробь) или None при неудаче.
    """
    if T <= 0 or market_price <= 0:
        return None
    intrinsic = max(0, F - K) if option_type == "call" else max(0, K - F)
    if market_price < intrinsic:
        return None

    sigma = (
        initial_guess
        if initial_guess is not None
        else initial_volatility_guess(F, K, T, market_price, option_type)
    )
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
        sigma = brentq(
            lambda s: black_76_price(F, K, T, s, option_type) - market_price, 1e-5, 10.0
        )
        return sigma
    except ValueError:
        return None


def calculate_greeks(F, K, T, sigma, option_type="call", trading_days_per_year=365):
    if sigma <= 0 or T <= 0:
        return {"delta": None, "gamma": None, "theta": None, "vega": None, "rho": None}

    sqrt_T = math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * sigma**2 * T) / (sigma * sqrt_T)
    pdf_d1 = norm.pdf(d1)

    # Годовой theta
    theta_annual = -(F * pdf_d1 * sigma) / (2 * sqrt_T)

    if option_type == "call":
        delta = norm.cdf(d1)
    else:
        delta = -norm.cdf(-d1)

    gamma = pdf_d1 / (F * sigma * sqrt_T)
    vega = F * pdf_d1 * sqrt_T

    # Дневной theta (делим годовой на число торговых дней)
    theta = theta_annual / trading_days_per_year

    return {
        "delta": delta,
        "gamma": gamma,
        "theta": theta,
        "vega": vega / 100,
        "rho": 0.0,
    }


def calculate_order_iv(symbol, price):
    """
    Рассчитывает подразумеваемую волатильность (IV) для опциона по цене заявки.
    Возвращает IV в процентах или None, если расчёт невозможен.
    """
    if not symbol or price is None or price <= 0:
        return None

    # Проверяем, что символ является опционом (есть в options_chains)
    chain = options_chains.get(symbol)
    if not chain:
        return None

    base_ticker = chain.get("base_ticker")
    if not base_ticker:
        return None

    # Получаем цену базового актива
    base_quote = base_asset_quotes.get(base_ticker)
    if not base_quote:
        return None

    # Берём последнюю цену, иначе среднее bid/ask
    F = base_quote.get("last")
    if F is None:
        bid = base_quote.get("bid")
        ask = base_quote.get("ask")
        if bid and ask:
            F = (bid + ask) / 2
        else:
            return None
    if not F or F <= 0:
        return None

    # Параметры опциона
    K = chain["strike"]
    exp_date_str = chain.get("expiration_last_day")
    if not exp_date_str or exp_date_str == "0000-00-00":
        return None

    try:
        exp_date = datetime.strptime(exp_date_str, "%Y-%m-%d").date()
    except ValueError:
        return None

    today = datetime.now().date()
    T = (exp_date - today).days / DAYS_IN_YEAR
    if T <= 0:
        return None

    option_type = "call" if chain["type"] == "TYPE_CALL" else "put"

    # Расчёт IV
    iv = implied_volatility_newton(price, F, K, T, option_type)
    if iv is None:
        return None
    return iv * 100  # в процентах


def to_float(decimal_field):
    """Универсальное преобразование Decimal-поля protobuf в float."""
    if decimal_field and hasattr(decimal_field, "value") and decimal_field.value:
        try:
            return float(decimal_field.value)
        except (ValueError, TypeError):
            return 0.0
    return 0.0

def _safe_float(value):
    """Безопасно приводит произвольное значение к float. None/''/нечисло → 0.0."""
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def fmt_date(d):
    """Форматирует дату protobuf в строку YYYY-MM-DD."""
    if d is None:
        return None
    return f"{d.year:04d}-{d.month:02d}-{d.day:02d}"


def fmt_ru_date(date_str):
    """Переводит дату YYYY-MM-DD в российский формат DD.MM.YYYY."""
    if not date_str:
        return ""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")
    except (ValueError, TypeError):
        return date_str


def is_order_status_active(status: str) -> bool:
    """Определяет, является ли статус заявки активным (не терминальным)."""
    short_status = status.replace("ORDER_STATUS_", "")
    active_statuses = {
        "NEW",
        "PARTIALLY_FILLED",
        "PENDING_NEW",
        "PENDING_CANCEL",
        "REPLACED",
        "SUSPENDED",
        "FORWARDING",
        "WAIT",
        "WATCHING",
        "LINK_WAIT",
        "SL_GUARD_TIME",
        "SL_FORWARDING",
        "TP_GUARD_TIME",
        "TP_FORWARDING",
        "TP_CORRECTION",
        "TP_CORR_GUARD_TIME",
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
        # Различаем два случая по НАЛИЧИЮ поля orders, а не по его значению.
        if hasattr(order_state, "orders"):
            order_states = order_state.orders or []
        else:
            order_states = [order_state]

        for order_state_item in order_states:
            order_id = (
                order_state_item.order_id
                if hasattr(order_state_item, "order_id")
                else None
            )
            if not order_id:
                continue

            # --- Статус заявки ---
            status_raw = (
                order_state_item.status if hasattr(order_state_item, "status") else None
            )
            if isinstance(status_raw, int):
                try:
                    status = orders_service.OrderStatus.Name(status_raw)
                except ValueError:
                    status = f"UNKNOWN_{status_raw}"
            else:
                status = str(status_raw) if status_raw else ""

            # --- Определяем активность ---
            is_active = is_order_status_active(status)

            if is_active:
                order = (
                    order_state_item.order
                    if hasattr(order_state_item, "order")
                    else None
                )
                if not order:
                    continue

                symbol = order.symbol if hasattr(order, "symbol") else ""

                quantity = (
                    to_float(order.quantity) if hasattr(order, "quantity") else 0.0
                )
                price = (
                    to_float(order.limit_price)
                    if hasattr(order, "limit_price")
                    else 0.0
                )
                executed_quantity = (
                    to_float(order_state_item.executed_quantity)
                    if hasattr(order_state_item, "executed_quantity")
                    else 0.0
                )
                remaining_quantity = (
                    to_float(order_state_item.remaining_quantity)
                    if hasattr(order_state_item, "remaining_quantity")
                    else 0.0
                )

                # --- Сторона (side) ---
                side = ""
                if hasattr(order, "side"):
                    side_raw = order.side
                    if isinstance(side_raw, int):
                        enum_class = getattr(orders_service, "Side", None)
                        if enum_class is not None:
                            try:
                                side = enum_class.Name(side_raw)
                            except ValueError:
                                side = str(side_raw)
                        else:
                            side = str(side_raw)
                    else:
                        side = str(side_raw)

                # --- Тип заявки (type) ---
                order_type = ""
                if hasattr(order, "type"):
                    type_raw = order.type
                    if isinstance(type_raw, int):
                        enum_class = getattr(orders_service, "OrderType", None)
                        if enum_class is not None:
                            try:
                                order_type = enum_class.Name(type_raw)
                            except ValueError:
                                order_type = str(type_raw)
                        else:
                            order_type = str(type_raw)
                    else:
                        order_type = str(type_raw)

                # --- Метка времени transact_at ---
                transact_at_str = None
                if order_state_item.HasField("transact_at"):
                    ts = order_state_item.transact_at
                    try:
                        dt_msk = fp_provider.timestamp_to_msk_datetime(ts.seconds)
                        transact_at_str = dt_msk.strftime("%d.%m.%Y %H:%M:%S")
                    except (AttributeError, ValueError, TypeError):
                        transact_at_str = None

                # --- Информация об опционе ---
                chain = options_chains.get(symbol)
                option_base = chain.get("base_ticker") if chain else ""
                opt_type_raw = chain.get("type") if chain else ""
                opt_type = "Put" if "PUT" in opt_type_raw.upper() else (
                    "Call" if "CALL" in opt_type_raw.upper() else opt_type_raw
                )
                opt_strike = chain.get("strike") if chain else ""
                opt_expdate = fmt_ru_date(chain.get("expiration_last_day")) if chain else ""

                # Сторона сделки: SIDE_BUY/1 -> Купля, SIDE_SELL/2 -> Продажа
                side_upper = side.upper()
                if "BUY" in side_upper or side == "1":
                    operation = "Купля"
                elif "SELL" in side_upper or side == "2":
                    operation = "Продажа"
                else:
                    operation = side

                ticker = symbol.split("@")[0] if symbol else ""

                # --- Сохраняем заявку ---
                active_orders[order_id] = {
                    "transact_at": transact_at_str,
                    "order_num": order_id,
                    "opt_base": option_base,
                    "symbol": symbol,
                    "ticker": ticker,
                    "opt_type": opt_type,
                    "strike": opt_strike,
                    "expdate": opt_expdate,
                    "operation": operation,
                    "volume": quantity,
                    "price": price,
                    "value": quantity * price,
                    "type": order_type,
                    "status": status,
                    "exec": executed_quantity,
                    "remain": remaining_quantity,
                    "updated": datetime.now().strftime("%H:%M:%S"),
                }
                # Добавляем расчёт IV (если это опцион)
                order_iv = calculate_order_iv(symbol, price)
                if order_iv is not None:
                    active_orders[order_id]["order_iv"] = round(float(order_iv), 2)
                else:
                    active_orders[order_id]["order_iv"] = None
                    logger.warning("order_iv is None для order_id=%s", order_id)

                logger.debug(f"Активная заявка #{order_id}: {active_orders[order_id]}")
            else:
                # Терминальный статус — удаляем заявку
                if order_id in active_orders:
                    removed = active_orders.pop(order_id)
                    logger.debug(
                        f"Заявка #{order_id} удалена (статус: {status}). Была: {removed}"
                    )

        # Проверяем, не появились ли новые опционы в заявках
        update_option_subscriptions_from_portfolio()

    except Exception as e:
        logger.error(f"Ошибка в _on_order: {e}\n{traceback.format_exc()}")

# ---------------------------------------------------------------------------
# Обработчик событий по собственным сделкам
# ---------------------------------------------------------------------------
def _on_trade(trade_response):
    try:
        if not trade_response:
            logger.warning("Получен пустой ответ по сделкам")
            return

        # Различаем контейнерный ответ (поле trades) и одиночную сделку по
        # НАЛИЧИЮ поля, а не по его значению: пустой список — это «сделок нет».
        if hasattr(trade_response, "trades"):
            trade_list = trade_response.trades or []
        else:
            trade_list = [trade_response]  # одиночная сделка

        for trade in trade_list:
            trade_id = trade.trade_id if hasattr(trade, "trade_id") else None
            if not trade_id:
                logger.warning("Сделка без trade_id, пропускаем")
                continue

            # --- Сторона сделки (side) ---
            side = ""
            if hasattr(trade, "side"):
                side_raw = trade.side
                if isinstance(side_raw, int):
                    enum_class = getattr(orders_service, "Side", None)
                    if enum_class is not None:
                        try:
                            side = enum_class.Name(side_raw)
                        except ValueError:
                            side = str(side_raw)
                    else:
                        side = str(side_raw)
                else:
                    side = str(side_raw)

            # --- Метка времени ---
            timestamp_str = None
            if hasattr(trade, "timestamp") and trade.timestamp:
                try:
                    ts = trade.timestamp
                    dt_msk = fp_provider.timestamp_to_msk_datetime(ts.seconds)
                    timestamp_str = dt_msk.strftime("%d.%m.%Y %H:%M:%S")
                except (AttributeError, ValueError, TypeError):
                    timestamp_str = None

            # --- Цена сделки (для расчёта IV) ---
            price = to_float(trade.price) if hasattr(trade, "price") else 0.0
            # --- Расчёт IV для опциона ---
            trade_iv = calculate_order_iv(trade.symbol, price)

            symbol = trade.symbol if hasattr(trade, "symbol") else ""
            chain = options_chains.get(symbol)

            # Тикер без суффикса биржи (например RIZ6@RTSX -> RIZ6)
            ticker = symbol.split("@")[0] if symbol else ""

            # Базовый актив для опциона
            option_base = chain.get("base_ticker") if chain else ""
            opt_type_raw = chain.get("type") if chain else ""
            opt_type = "Put" if "PUT" in opt_type_raw.upper() else (
                "Call" if "CALL" in opt_type_raw.upper() else opt_type_raw
            )
            opt_strike = chain.get("strike") if chain else ""
            opt_expdate = fmt_ru_date(chain.get("expiration_last_day")) if chain else ""

            # Сторона сделки: SIDE_BUY/1 -> Купля, SIDE_SELL/2 -> Продажа
            side_upper = side.upper()
            if "BUY" in side_upper or side == "1":
                operation = "Купля"
            elif "SELL" in side_upper or side == "2":
                operation = "Продажа"
            else:
                operation = side

            # Поля для CSV
            # datetime;trade_id;order_id;option_base;ticker;option_type;strike;expdate;operation;volume;price;value;volatility
            # --- Сохраняем сделку ---
            trades[trade_id] = {
                "datetime": timestamp_str,
                "trade_id": trade_id,
                "order_id": trade.order_id if hasattr(trade, "order_id") else "",
                "option_base": option_base,
                "ticker": ticker,
                "option_type": opt_type,
                "strike": opt_strike,
                "expdate": opt_expdate,
                "operation": operation,
                "volume": to_float(trade.size) if hasattr(trade, "size") else 0.0,
                "price": price,
                "value": price * (to_float(trade.size) if hasattr(trade, "size") else 0.0),
                "volatility": trade_iv,
            }

            # Архивная копия сделки в полную историю (не очищается)
            with _trades_lock:
                trades_all[trade_id] = dict(trades[trade_id])

            logger.debug(f"Сделка {trade_id}: {trades[trade_id]}")

        # После обработки пакета сделок запускаем проверку состава портфеля
        # (GetAccount + очистка CSV от инструментов, которых больше нет в портфеле).
        # Сделка потенциально закрывает инструмент — после неё в словаре trades
        # могут остаться записи, которые нужно удалить. Выполняется в фоновом потоке
        # io_worker, чтобы не блокировать gRPC-поток событий.
        #
        # Дедупликация: на старте/переподключении подписки на сделки приходит
        # исторический снапшот пакетами — каждый пакет порождает отдельный _on_trade,
        # и без ограничения частоты в очередь набиралось бы много одинаковых задач
        # очистки. Ставим задачу не чаще одного раза за _LAST_TRADES_CLEANUP_INTERVAL.
        global _last_trades_cleanup_enqueued
        now_enqueue = _time.time()
        if (fp_provider is not None and now_enqueue - _last_trades_cleanup_enqueued >= _LAST_TRADES_CLEANUP_INTERVAL):
            logger.info(f'_on_trade запуск функции verify_positions_and_cleanup_trades')
            _last_trades_cleanup_enqueued = now_enqueue
            _io_task_queue.put(lambda: verify_positions_and_cleanup_trades(set()))

    except Exception as e:
        logger.error(f"Ошибка в _on_trade: {e}\n{traceback.format_exc()}")

# ---------------------------------------------------------------------------
# Подписка на события по заявкам
# ---------------------------------------------------------------------------
def subscribe_orders(fp_provider, account_id):
    """Подписка на события по собственным заявкам"""
    fp_provider.on_order.subscribe(_on_order)
    thread = Thread(
        target=fp_provider.subscribe_orders_thread,
        name="OrdersThread",
        args=(account_id,),
        daemon=True,
    )
    thread.start()
    track_thread(thread)
    logger.info(f"Подписка на собственные заявки аккаунта {account_id} запущена")
    return thread


def subscribe_trades(fp_provider, account_id):
    """Подписка на события по собственным сделкам"""
    fp_provider.on_trade.subscribe(_on_trade)
    thread = Thread(
        target=fp_provider.subscribe_trades_thread,
        name="TradesThread",
        args=(account_id,),
        daemon=True,
    )
    thread.start()
    track_thread(thread)
    logger.info(f"Подписка на собственные сделки аккаунта {account_id} запущена")
    return thread


# ---------------------------------------------------------------------------
# Хранилища котировок
# ---------------------------------------------------------------------------
base_asset_quotes = {}  # Котировки базовых активов: {ticker: {...}}
option_quotes = {}  # Котировки опционов: {symbol: {...}}
subscribed_option_symbols = set()  # Символы опционов, на которые уже подписаны
options_chains = {}  # {symbol: { ... }} — все опционы по базовым активам
_options_chains_loaded = False  # Флаг однократной загрузки


def fetch_last_quote_for_symbol(symbol):
    """
    Получает последнюю котировку по опциону через API LastQuote
    и сохраняет в option_quotes.
    Вызывается из фонового потока io_worker (через очередь _io_task_queue),
    чтобы не блокировать gRPC-поток событий.
    """
    try:
        request = marketdata_service.QuoteRequest(symbol=symbol)
        response = fp_provider.call_function(
            fp_provider.marketdata_stub.LastQuote, request
        )

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
        if source.HasField("timestamp"):
            ts = source.timestamp
            dt_msk = fp_provider.timestamp_to_msk_datetime(ts.seconds)
            target["timestamp"] = dt_msk.strftime("%Y-%m-%d %H:%M:%S")
    except (AttributeError, ValueError, TypeError):
        target["timestamp"] = None


def update_iv_and_greeks(symbol):
    """Вычисляет IV для ask/bid/last/theor и греки для опциона."""
    # Получаем параметры из хранилищ
    chain = options_chains.get(symbol)
    if not chain:
        return

    base_ticker = chain.get("base_ticker")
    if not base_ticker:
        return
    quote = base_asset_quotes.get(base_ticker)  # 'RIZ6' — совпадает с ключами хранилища
    if not quote:
        return
    if quote.get("last") is None:
        bid = quote.get("bid")
        ask = quote.get("ask")
        F = (bid + ask) / 2 if bid and ask else None
    else:
        F = quote["last"]
    if not F or F <= 0:
        return

    K = chain["strike"]
    # Дата экспирации
    exp_date_str = chain["expiration_last_day"]
    if not exp_date_str or exp_date_str == "0000-00-00":
        return
    exp_date = datetime.strptime(exp_date_str, "%Y-%m-%d").date()
    today = datetime.now().date()
    T = (exp_date - today).days / DAYS_IN_YEAR
    if T <= 0:
        return

    option_type = "call" if chain["type"] == "TYPE_CALL" else "put"

    record = option_quotes.get(symbol)
    if not record:
        return

    # Расчёт IV для каждой цены
    for price_field, iv_field in [
        ("ask", "ask_iv"),
        ("bid", "bid_iv"),
        ("last", "last_iv"),
        ("theoretical_price", "theor_iv"),
    ]:
        price = record.get(price_field)
        if price is None:
            record[iv_field] = None
            continue
        iv = implied_volatility_newton(price, F, K, T, option_type)
        record[iv_field] = iv * 100 if iv is not None else None  # в процентах

    # Для греков используем IV биржи
    sigma_for_greeks = record.get("implied_volatility")
    # if sigma_for_greeks is None:
    #     sigma_for_greeks = (
    #         record.get("theor_iv") or record.get("ask_iv") or record.get("bid_iv")
    #     )
    # if sigma_for_greeks is None:
    #     sigma_for_greeks = record.get("last_iv")  # last_iv (если есть)
    # if sigma_for_greeks is None:
    #     return
    sigma = sigma_for_greeks / 100.0  # переводим в десятичную
    greeks = calculate_greeks(F, K, T, sigma, option_type)
    record.update(greeks)  # добавит delta, gamma, theta, vega, rho


def process_single_quote(q):
    """Обрабатывает одну котировку (из подписки или запроса последней цены)."""
    full_symbol = q.symbol
    ticker = full_symbol.split("@")[0] if "@" in full_symbol else full_symbol

    # --- Базовые активы (фьючерсы) ---
    if full_symbol in base_symbols or ticker in MAP:
        map_ticker = _full_ticker_to_map.get(ticker, ticker)  # 'RIZ6' → 'RI'
        if map_ticker not in base_asset_quotes:
            base_asset_quotes[map_ticker] = {
                "timestamp": None,
                "ask": None,
                "bid": None,
                "last": None,
                "ask_size": None,
                "bid_size": None,
                "last_size": None,
                "time": None,
            }
        record = base_asset_quotes[map_ticker]
        _set_timestamp(record, q)
        for field in ("ask", "bid", "last", "ask_size", "bid_size", "last_size"):
            _set_if_present(record, q, field)
        record["time"] = datetime.now().strftime("%H:%M:%S")

    # --- Опционы ---
    elif full_symbol in subscribed_option_symbols:
        if full_symbol not in option_quotes:
            option_quotes[full_symbol] = {
                "timestamp": None,
                "ask": None,
                "ask_iv": None,
                "ask_size": None,
                "bid": None,
                "bid_iv": None,
                "bid_size": None,
                "last": None,
                "last_iv": None,
                "last_size": None,
                "open_interest": None,
                "implied_volatility": None,
                "theoretical_price": None,
                "theor_iv": None,
                "delta": None,
                "gamma": None,
                "theta": None,
                "vega": None,
                "rho": None,
                "time": None,
            }
        record = option_quotes[full_symbol]
        for field in ("ask", "bid", "last", "ask_size", "bid_size", "last_size"):
            _set_if_present(record, q, field)
        _set_timestamp(record, q)
        _set_if_present(record, q, "open_interest")

        if q.HasField("option"):
            opt = q.option
            for field in (
                "open_interest",
                "implied_volatility",
                "theoretical_price",
                "delta",
                "gamma",
                "theta",
                "vega",
                "rho",
            ):
                _set_if_present(record, opt, field)

        record["time"] = datetime.now().strftime("%H:%M:%S")

        # --- Расчёт IV и греков ---
        update_iv_and_greeks(full_symbol)


# ---------------------------------------------------------------------------
# Обработчик котировок (базовые активы + опционы)
# ---------------------------------------------------------------------------
def _on_quote(quote):
    """Обработчик котировок базовых активов и опционов."""
    # Обрабатываем оба формата, которые может присылать сервер:
    #   - SubscribeQuoteResponse / QuoteResponse: контейнер с полем quote (список)
    #   - одиночная котировка Quote
    try:
        if hasattr(quote, "quote"):
            # Поле error есть в подписочном ответе (SubscribeQuoteResponse).
            # Объект protobuf всегда «истинен», поэтому проверяем реальные признаки ошибки.
            if hasattr(quote, "error") and (
                quote.error.code != 0 or quote.error.description
            ):
                err = quote.error
                logger.warning(
                    f"Ошибка в потоке котировок: код={err.code}, {err.description}"
                )
                return
            quotes = quote.quote or []
            for q in quotes:
                process_single_quote(q)
        else:
            # Одиночная котировка
            process_single_quote(quote)
    except Exception as e:
        logger.error(f"Ошибка в _on_quote: {e}\n{traceback.format_exc()}")


# ---------------------------------------------------------------------------
# Подписка на котировки базовых активов
# ---------------------------------------------------------------------------
def subscribe_base_assets(fp_provider):
    global base_symbols, _full_ticker_to_map
    base_symbols.clear()
    _full_ticker_to_map.clear()

    for ticker in MAP.keys():
        dataname = f"SPBFUT.{ticker}"
        try:
            finam_board, ticker_code = fp_provider.dataname_to_finam_board_ticker(
                dataname
            )
            mic = fp_provider.get_mic(finam_board, ticker_code)
            symbol = f"{ticker_code}@{mic}"
            base_symbols.add(symbol)
            _full_ticker_to_map[ticker_code] = ticker
        except Exception as e:
            logger.error(f"Не удалось определить биржу для {ticker}: {e}")

    logger.info(f"Базовые активы собраны: {list(base_symbols)}")


# ---------------------------------------------------------------------------
# Проверка появления новых опционов в портфеле/заявках
# ---------------------------------------------------------------------------

# Хранилище активных потоков подписки
_quote_subscriptions = []  # список активных QuoteSubscription


def io_worker(stop_event):
    """
    Фоновый поток для выполнения «тяжёлых» операций ввода-вывода:
    чтение/запись CSV-файлов и сетевые запросы LastQuote.
    Ранее эти операции выполнялись прямо в gRPC-потоках событий
    (_on_order, _on_account_info), что могло блокировать обработку
    котировок и заявок. Теперь задачи ставятся в очередь _io_task_queue
    и выполняются в этом отдельном потоке.
    """
    logger.info("Фоновый поток обработки задач I/O запущен")
    while not stop_event.is_set():
        try:
            # Ожидаем задачу с таймаутом, чтобы вовремя реагировать на stop_event
            task = _io_task_queue.get(timeout=0.5)
        except queue.Empty:
            continue
        try:
            task()
        except Exception as e:
            logger.error(f"Ошибка в фоновой задаче I/O: {e}\n{traceback.format_exc()}")


# функция очистки сделок закрытых инструментов
def cleanup_trades(actual_positions):
    """
    Удаляет из словаря trades записи, инструмент которых отсутствует
    в актуальном составе портфеля. Проверка строго по тикеру - части символа
    до знака '@' (например 'RI82500BW6'). Полная история trades_all не очищается.

    :param set actual_positions: символы позиций с ненулевым количеством из GetAccount,
                                 напр. {'RIZ6@RTSX', 'RI90000BK6@RTSX'}
    """
    logger.info("Запуск функции cleanup_trades очистки сделок закрытых инструментов")
    # Тикеры (часть до '@'), которые есть в актуальном портфеле
    live_tickers = {p.split("@")[0] for p in actual_positions if p}
    with _trades_lock:
        stale_ids = [
            tid for tid, row in trades.items()
            if row.get("ticker") not in live_tickers
        ]
        for tid in stale_ids:
            del trades[tid]
    if stale_ids:
        logger.info(f"Очистка сделок: удалено записей: {len(stale_ids)}")


def single_transaction_clearing():
    """Однократная очистка сделок закрытых инструментов из словаря trades при запуске кода"""
    logger.info(
        f"Запуск функции single_transaction_clearing. Загрузка состава портфеля отдельным запросом GetAccount и"
        f" очистка сделок инструментов, которых уже нет в портфеле")
    try:
        if fp_provider is None:
            logger.warning(
                "Проверка портфеля: провайдер не инициализирован, очистка отменена"
            )
            return
        account: accounts_service.GetAccountResponse = fp_provider.call_function(
            fp_provider.accounts_stub.GetAccount,
            accounts_service.GetAccountRequest(account_id=account_id),
        )
        if account is None:
            logger.warning(
                "Проверка портфеля: GetAccount не вернул ответ, очистка отменена"
            )
            return

        # Актуальный состав портфеля с ненулевым количеством из свежего снапшота
        actual_positions = {
            position.symbol
            for position in account.positions
            if to_float(position.quantity) != 0
        }
        logger.info(f'Актуальный состав портфеля: {actual_positions}')
        cleanup_trades(actual_positions)

    except Exception as e:
        logger.error(
            f"Ошибка проверки портфеля через GetAccount: {e}\n{traceback.format_exc()}"
        )


def verify_positions_and_cleanup_trades(removed_symbols=frozenset()):
    """Проверка состава портфеля отдельным запросом GetAccount (унитарный,
    а не потоковый) перед удалением сделок из Finam_Stream_Trades.csv.

    Очистка CSV выполняется ТОЛЬКО когда есть подтверждённо закрытые позиции:
    символы, исчезнувшие из состава (removed_symbols или, если они не переданы,
    разница между _last_positions_symbols и свежим снапшотом GetAccount) и
    отсутствующие в актуальном портфеле. После подтверждения удаляются все
    записи из CSV, чей тикер отсутствует в актуальном портфеле.

    :param set removed_symbols: Символы, исчезнувшие из портфеля по данным
                                стрим-подписки (объединение позиций и заявок).
                                Может быть пустым — тогда разница вычисляется
                                по _last_positions_symbols.
    """
    global _last_positions_symbols
    logger.info(f"Запуск функции verify_positions_and_cleanup_trades Проверка состава портфеля отдельным запросом GetAccount")
    try:
        if fp_provider is None:
            logger.warning(
                "Проверка портфеля: провайдер не инициализирован, очистка отменена"
            )
            return
        account: accounts_service.GetAccountResponse = fp_provider.call_function(
            fp_provider.accounts_stub.GetAccount,
            accounts_service.GetAccountRequest(account_id=account_id),
        )
        if account is None:
            logger.warning(
                "Проверка портфеля: GetAccount не вернул ответ, очистка отменена"
            )
            return

        # Актуальный состав портфеля с ненулевым количеством из свежего снапшота
        actual_positions = {
            position.symbol
            for position in account.positions
            if to_float(position.quantity) != 0
        }

        # Если триггер не передан — вычисляем исчезнувшие сами: символы, которые
        # были в прошлом известном составе (_last_positions_symbols), но которых
        # нет в свежем снапшоте GetAccount.
        if not removed_symbols:
            removed_symbols = _last_positions_symbols - actual_positions

        # Символы, которые стрим считал закрытыми, но которые есть в свежем снапшоте
        restored = removed_symbols & actual_positions
        if restored:
            # logger.warning(
            #     f"Проверка портфеля: символы {restored} присутствуют в снапшоте GetAccount "
            #     f"— ложное срабатывание стрима, очистка CSV по ним не выполняется"
            # )
            # Восстанавливаем символы в составе портфеля, чтобы не терять их отслеживание
            _last_positions_symbols |= restored

        confirmed_removed = removed_symbols - actual_positions
        if not confirmed_removed:
            # logger.info(f"Проверка портфеля: подтверждённых закрытых позиций нет, очистка CSV не требуется")
            return

        logger.info(
            f"Проверка портфеля: подтверждено закрытие позиций: {confirmed_removed}. "
            f"Удаляем сделки из CSV"
        )
        cleanup_trades(actual_positions)

    except Exception as e:
        logger.error(
            f"Ошибка проверки портфеля через GetAccount: {e}\n{traceback.format_exc()}"
        )


def update_option_subscriptions_from_portfolio():
    global subscribed_option_symbols, _last_positions_symbols, _last_orders_symbols
    global _subscription_dirty, _cleanup_dirty, _symbol_last_seen
    global _previous_obsolete

    # Во внеторговое время подписки не трогаем: снапшот портфеля, пришедший
    # вне сессии, может отличаться от состояния на конец дня и порождать
    # ложное обнаружение «устаревших» опционов
    if not schedule.trade_session(get_market_now()):
        return

    # Текущие символы из позиций портфеля с ненулевым количеством
    raw_positions = _account_data[0].get("positions", {})
    positions = {
        sym: pos for sym, pos in raw_positions.items() if float(pos["net_pos"]) != 0
    }
    current_positions = set(positions.keys())

    # Текущие символы из активных заявок
    current_orders = set()
    for order in active_orders.values():
        symbol = order.get("symbol", "")
        if symbol:
            current_orders.add(symbol)

    # Если ничего не изменилось — выходим (быстрая проверка)
    if (
        current_positions == _last_positions_symbols
        and current_orders == _last_orders_symbols
    ):
        return

    # Символы, которые были в портфеле/заявках раньше, но исчезли сейчас.
    # Важно учитывать и заявки, а не только позиции: опцион мог быть куплен
    # и продан через заявку, и позиция уже ненулевой, а символ исчез из заявок.
    # Тогда CSV по нему всё равно нужно чистить.
    prev_all_symbols = _last_positions_symbols | _last_orders_symbols
    all_symbols_now = current_positions | current_orders
    removed_symbols = prev_all_symbols - all_symbols_now

    # Если позиции/заявки изменились и сейчас торговая сессия — проверяем состав
    # портфеля отдельным запросом GetAccount и только после подтверждения
    # удаляем из CSV сделки по действительно закрытым инструментам.
    # Потоковый снапшот подписки может быть промежуточным/неполным, поэтому
    # доверяем ему только как триггеру, а не как источнику истины.
    # Проверка выполняется в фоновом потоке io_worker, чтобы не блокировать
    # gRPC-поток событий сетевым запросом.
    if removed_symbols and schedule.trade_session(get_market_now()):
        logger.info(f"Закрыты позиции (по данным стрима): {removed_symbols}")
        _io_task_queue.put(
            lambda removed=set(removed_symbols): verify_positions_and_cleanup_trades(removed)
        )

    # Обновляем сохранённые множества
    _last_positions_symbols = current_positions
    _last_orders_symbols = current_orders

    # Все символы из портфеля и заявок
    all_symbols = current_positions | current_orders

    # Оставляем только опционы
    option_symbols = set()
    for s in all_symbols:
        if s in base_symbols:
            continue
        ticker = s.split("@")[0]
        if ticker in MAP:
            continue
        option_symbols.add(s)

    # Обновляем время последнего появления для всех актуальных опционов
    now = _time.time()
    for sym in option_symbols:
        _symbol_last_seen[sym] = now

    # --- Новые опционы — добавляем и перезапускаем подписку НЕМЕДЛЕННО ---
    new_symbols = option_symbols - subscribed_option_symbols
    if new_symbols:
        subscribed_option_symbols.update(new_symbols)
        logger.info(f"Добавлены новые опционы в отслеживание: {new_symbols}")

        # Предзаполняем котировки. Сетевые запросы LastQuote выполняются
        # в фоновом потоке io_worker, чтобы не задерживать обработку событий.
        for symbol in new_symbols:
            _io_task_queue.put(lambda s=symbol: fetch_last_quote_for_symbol(s))

        # Помечаем, что нужно перезапустить подписку (сделаем это в main сразу)
        _subscription_dirty = True

    # --- Устаревшие опционы (не появлялись >30 сек) — помечаем для очистки ---
    # Опционы, которых нет в текущем составе и которые не появлялись более 30 секунд
    obsolete_symbols = {
        sym
        for sym in subscribed_option_symbols
        if sym not in option_symbols and now - _symbol_last_seen.get(sym, 0) > 30
    }
    if obsolete_symbols:
        _cleanup_dirty = True
        # Логируем только новые устаревшие
        new_obsolete = obsolete_symbols - _previous_obsolete
        if new_obsolete:
            logger.info(
                f"Обнаружены устаревшие опционы (очистка через 30 сек): {new_obsolete}"
            )
        _previous_obsolete = obsolete_symbols


_restart_lock = threading.Lock()


def restart_quotes_subscription():
    global _quote_subscriptions, _stream_threads

    if not _restart_lock.acquire(blocking=False):
        logger.info("Перезапуск подписки уже выполняется, пропускаем.")
        return

    try:
        # Останавливаем все старые подписки
        for sub in _quote_subscriptions:
            sub.stop()
        _quote_subscriptions = []
        logger.info("Все старые подписки остановлены")

        # Убираем мёртвые потоки из списка (потоки подписки уже дожданы
        # внутри sub.stop(), повторный join не требуется)
        _stream_threads[:] = [t for t in _stream_threads if t.is_alive()]

        # Даём серверу время освободить символы
        sleep(1)

        # Отписываемся от обработчика
        if fp_provider is not None:
            fp_provider.on_quote.unsubscribe(_on_quote)

        # Запускаем новые подписки
        start_quotes_subscription(fp_provider)
    finally:
        _restart_lock.release()


def cleanup_obsolete_subscriptions():
    """Удаляет опционы, отсутствующие в портфеле/заявках более 30 секунд, и перезапускает подписку."""
    global \
        subscribed_option_symbols, \
        _cleanup_dirty, \
        _symbol_last_seen, \
        _previous_obsolete

    # Пересчитываем актуальные символы
    raw_positions = _account_data[0].get("positions", {})
    positions = {
        sym: pos for sym, pos in raw_positions.items() if float(pos["net_pos"]) != 0
    }
    current_positions = set(positions.keys())

    current_orders = set()
    for order in active_orders.values():
        symbol = order.get("symbol", "")
        if symbol:
            current_orders.add(symbol)

    all_symbols = current_positions | current_orders
    option_symbols = set()
    for s in all_symbols:
        if s in base_symbols:
            continue
        ticker = s.split("@")[0]
        if ticker in MAP:
            continue
        option_symbols.add(s)

    # Обновляем время последнего появления для актуальных
    now = _time.time()
    for sym in option_symbols:
        _symbol_last_seen[sym] = now

    # Находим действительно устаревшие
    obsolete = {
        sym
        for sym in subscribed_option_symbols
        if sym not in option_symbols and now - _symbol_last_seen.get(sym, 0) > 30
    }

    if obsolete:
        # Удаляем из отслеживания, котировок и last_seen
        for sym in obsolete:
            subscribed_option_symbols.discard(sym)
            option_quotes.pop(sym, None)
            _symbol_last_seen.pop(sym, None)
        logger.info(f"Очистка: удалены устаревшие опционы: {obsolete}")

        # Перезапускаем подписку без устаревших
        restart_quotes_subscription()
    else:
        logger.debug("Очистка: устаревших опционов нет")

    _previous_obsolete.clear()

    _cleanup_dirty = False


# ---------------------------------------------------------------------------
# Загрузка цепочек опционов
# ---------------------------------------------------------------------------
def load_options_chains(fp_provider):
    global _options_chains_loaded
    if _options_chains_loaded:
        return options_chains
    _options_chains_loaded = True

    for ticker, params in MAP.items():
        strike_step = params["strike_step"]
        strikes_count = params["max_strikes_count"]

        try:
            # Получаем список дат экспирации (уникальные, в формате 'YYYY-MM-DD')
            expirations = get_option_expirations(ticker)
            expiration_dates = sorted(
                set(exp["expiration_date"] for exp in expirations)
            )
            print(
                f"Даты экспирации опционов базового актива {ticker}: {expiration_dates}"
            )

            # Получаем цену базового актива
            quote = base_asset_quotes.get(ticker)
            if not quote or quote.get("last") is None:
                logger.warning(f"Нет цены для {ticker}, пропускаем загрузку цепочки")
                continue
            base_price = quote["last"]

            # Формируем нужные страйки
            required_strikes = set(
                get_list_of_strikes(base_price, strike_step, strikes_count)
            )

            # Определяем символ для API
            dataname = f"SPBFUT.{ticker}"
            finam_board, ticker_code = fp_provider.dataname_to_finam_board_ticker(
                dataname
            )
            mic = fp_provider.get_mic(finam_board, ticker_code)
            underlying_symbol = f"{ticker_code}@{mic}"

            # Перебираем все даты экспирации
            for exp_date_str in expiration_dates:
                expiration_date_obj = datetime.strptime(exp_date_str, "%Y-%m-%d").date()
                year = expiration_date_obj.year
                month = expiration_date_obj.month
                day = expiration_date_obj.day
                # --- Запрашиваем полную цепочку опционов ---
                request = assets_service.OptionsChainRequest(
                    underlying_symbol=underlying_symbol,
                    expiration_date={"year": year, "month": month, "day": day},
                )
                response = fp_provider.call_function(
                    fp_provider.assets_stub.OptionsChain, request
                )

                if response is None:
                    logger.error(
                        f"Не удалось получить цепочку опционов для {underlying_symbol} на {exp_date_str}"
                    )
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
                        "symbol": opt.symbol,
                        "type": opt_type,
                        "contract_size": to_float(opt.contract_size),
                        "trade_first_day": fmt_date(opt.trade_first_day),
                        "trade_last_day": fmt_date(opt.trade_last_day),
                        "strike": strike,
                        "multiplier": to_float(opt.multiplier),
                        "expiration_first_day": fmt_date(opt.expiration_first_day),
                        "expiration_last_day": fmt_date(opt.expiration_last_day),
                        "base_ticker": ticker,
                    }
                    filtered_count += 1

                logger.info(
                    f"Цепочка опционов для {underlying_symbol} на {exp_date_str}: "
                    f"загружено {filtered_count} из {len(response.options)} опционов "
                    f"(страйков: {len(required_strikes)})"
                )

        except Exception as e:
            logger.error(f"Ошибка при получении цепочки опционов для {ticker}: {e}")

    logger.info(f"Всего опционов загружено: {len(options_chains)}")
    return options_chains


def start_quotes_subscription(fp_provider):
    """Подписка на базовые активы + все опционы из subscribed_option_symbols."""
    global subscribed_option_symbols, _quote_subscriptions

    all_symbols = list(set(base_symbols) | subscribed_option_symbols)
    if not all_symbols:
        logger.warning("Нет символов для подписки на котировки")
        return []

    # Защита от дублирования обработчика
    fp_provider.on_quote.unsubscribe(_on_quote)
    fp_provider.on_quote.subscribe(_on_quote)

    subscriptions = []
    chunk_size = 10  # уменьшите до 10, чтобы точно не превысить лимит

    for i in range(0, len(all_symbols), chunk_size):
        chunk = all_symbols[i : i + chunk_size]
        sub = QuoteSubscription(
            fp_provider, chunk, name=f"QuotesThread-{i // chunk_size}"
        )
        sub.start()
        track_thread(sub.thread)
        subscriptions.append(sub)

    _quote_subscriptions = subscriptions
    logger.info(
        f"Запущено {len(subscriptions)} потоков подписки на {len(all_symbols)} символов"
    )
    return subscriptions

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
            trades_df = get_trades_df()

        # Фильтрация по инструменту (все сделки по инструменту)
        instrument_trades_df = trades_df[trades_df['ticker'] == sec_code].copy()

        if instrument_trades_df.empty:
            logger.warning(f"Предупреждение: Нет данных для инструмента {sec_code}")
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
            logger.warning(f"Предупреждение: Недостаточно сделок для инструмента {sec_code}")
            logger.warning(f"Позиция: {net_pos}")
            logger.warning(f"Сделок лонг: {count_long} Объем: {sum_volume_long}")
            logger.warning(f"Сделок шорт: {count_short} Объем: {sum_volume_short}")
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
        logger.error(f"Ошибка при вычислении данных открытия для {sec_code}: {e}")
        return None, None, None


def calculate_weighted_average(inventory):
    """Средневзвешенное значение по инвентарю FIFO (deque из Entry с атрибутами quantity и price)"""
    weighted_sum = sum(entry.quantity * entry.price for entry in inventory)
    total_weight = sum(entry.quantity for entry in inventory)
    return weighted_sum / total_weight if total_weight != 0 else 0

def get_trades_df():
    """DataFrame активных сделок из словаря trades (вместо чтения CSV)."""
    with _trades_lock:
        rows = [dict(r) for r in trades.values()]
    trades_df = pd.DataFrame(rows, columns=[
        'datetime', 'trade_id', 'order_id', 'option_base', 'ticker',
        'option_type', 'strike', 'expdate', 'operation', 'volume',
        'price', 'value', 'volatility'
    ])
    if trades_df.empty:
        return trades_df
    trades_df['datetime'] = pd.to_datetime(
        trades_df['datetime'], format='%d.%m.%Y %H:%M:%S', errors='coerce'
    )
    for column in ['strike', 'volume', 'price', 'value', 'volatility']:
        if column in trades_df.columns:
            trades_df[column] = pd.to_numeric(trades_df[column], errors='coerce')
    return trades_df


def get_trades_all_df():
    """DataFrame полной истории сделок из словаря trades_all."""
    with _trades_lock:
        rows = [dict(r) for r in trades_all.values()]
    return pd.DataFrame(rows, columns=[
        'datetime', 'trade_id', 'order_id', 'option_base', 'ticker',
        'option_type', 'strike', 'expdate', 'operation', 'volume',
        'price', 'value', 'volatility'
    ])


def get_positions_df():
    """DataFrame позиций из _account_data.

    Числовые колонки приводятся к числам (аналог того, что раньше делал
    pd.read_csv при чтении Finam_MyPos.csv): пустые и нечисловые значения
    превращаются в NaN, колонки получают числовой тип. Без этого колонка
    'strike' у фьючерса содержит '' (пустую строку), а у опционов — float,
    что приводило к TypeError в sort_values(by='strike') и к некорректным
    сравнениям вида net_pos > 0 / OpenIV > 0.
    """
    positions = dict(_account_data[0]["positions"])
    if not positions:
        return pd.DataFrame(columns=POSITION_COLUMNS)
    df_pos = pd.DataFrame.from_dict(positions, orient="index").reset_index(drop=True)

    # Приведение числовых колонок к числам (пустые/нечисловые значения -> NaN)
    numeric_cols = [
        'net_pos', 'strike', 'OpenPrice', 'OpenIV',
        'bid', 'last', 'ask', 'theor', 'QuikVola',
        'bidIV', 'lastIV', 'askIV',
        'Delta', 'Gamma', 'Theta', 'Vega', 'TrueVega', 'u_pnl',
    ]
    for col in numeric_cols:
        if col in df_pos.columns:
            df_pos[col] = pd.to_numeric(df_pos[col], errors='coerce')

    return df_pos


def get_orders_df():
    """DataFrame активных заявок из словаря active_orders."""
    try:
        rows = list(active_orders.values())
    except RuntimeError:
        rows = []
    df = pd.DataFrame([dict(r) for r in rows])
    if df.empty:
        return pd.DataFrame(columns=CSV_ORDERS_COLUMNS)
    return df


def load_trades_from_csv(path):
    """Одноразовая загрузка архивной истории сделок из CSV в словарь trades_all."""
    if not path or not os.path.exists(path):
        return 0
    try:
        df = pd.read_csv(path, sep=';', encoding='utf-8')
    except (FileNotFoundError, pd.errors.EmptyDataError, ValueError):
        return 0
    n = 0
    with _trades_lock:
        for _, row in df.iterrows():
            d = row.to_dict()
            tid = str(d.get('trade_id', ''))
            if tid and tid not in trades_all:
                trades_all[tid] = d
                n += 1
    logger.info(f"Загружено архивных сделок из {path}: {n}")
    return n


# ---------------------------------------------------------------------------
# Обработчик информации об аккаунте
# ---------------------------------------------------------------------------
def _on_account_info(account_response):
    """Обработчик информации об аккаунте из стрим-подписки"""
    try:
        data = _account_data[0]

        if not account_response:
            logger.warning("Получен пустой ответ по аккаунту из стрим-подписки")
            return

        if not hasattr(account_response, "positions"):
            logger.warning("В ответе нет атрибута positions")
            return

        # --- Сохраняем базовую информацию ---
        if hasattr(account_response, "account_id"):
            data["account_id"] = account_response.account_id  # Идентификатор аккаунта
        if hasattr(account_response, "status"):
            data["status"] = account_response.status  # Статус аккаунта

        # --- Equity и unrealized_profit ---
        if hasattr(account_response, "equity") and account_response.equity:
            data["equity"] = to_float(
                account_response.equity
            )  # Доступные средства плюс стоимость открытых позиций
        if (
            hasattr(account_response, "unrealized_profit")
            and account_response.unrealized_profit
        ):
            data["unrealized_profit"] = to_float(
                account_response.unrealized_profit
            )  # Нереализованная прибыль

        # --- Денежные средства ---
        data["cash"] = {}
        if hasattr(account_response, "cash"):
            for money_item in account_response.cash:
                currency = (
                    money_item.currency_code if money_item.currency_code else "RUB"
                )
                # В Google Money (protobuf) nanos всегда неотрицателен и лежит в [0, 1e9),
                # а знак числа задаётся units. Поэтому сумму считаем как units + nanos/1e9.
                # Важно: не выбрасывать наносоставляющую, даже если units == 0.
                amount = (
                    float(money_item.units) + float(money_item.nanos) / 1_000_000_000
                )
                data["cash"][currency] = {
                    "balance": amount,
                    "blocked": 0.0,
                    "free": amount,
                }

        # --- Определяем тип портфеля ---
        # Проверяем наличие поля через DESCRIPTOR, чтобы избежать ошибок HasField
        if (
            "portfolio_forts" in account_response.DESCRIPTOR.fields_by_name
            and account_response.HasField("portfolio_forts")
        ):
            data["portfolio_type"] = (
                "FORTS"  # Тип портфеля для торговли на срочном рынке Московской Биржи.
            )
            forts = account_response.portfolio_forts
            data["margin"] = {
                "available_cash": to_float(
                    forts.available_cash
                ),  # Сумма собственных денежных средств на счете, доступная для торговли. Включает маржинальные средства.
                "money_reserved": to_float(
                    forts.money_reserved
                ),  # Минимальная маржа (необходимая сумма обеспечения под открытые позиции)
            }
            data["cash"]["RUB"] = {
                "balance": to_float(forts.available_cash),
                "blocked": to_float(forts.money_reserved),
                "free": to_float(forts.available_cash),
                "GM": (to_float(forts.money_reserved) / data["equity"]) * 100
                if data["equity"]
                else 0.0,
            }
        elif (
            "portfolio_mc" in account_response.DESCRIPTOR.fields_by_name
            and account_response.HasField("portfolio_mc")
        ):
            data["portfolio_type"] = "MC"
            mc = account_response.portfolio_mc
            data["margin"] = {
                "available_cash": to_float(mc.available_cash),
                "initial_margin": to_float(mc.initial_margin),
                "maintenance_margin": to_float(mc.maintenance_margin),
            }
        elif (
            "portfolio_mct" in account_response.DESCRIPTOR.fields_by_name
            and account_response.HasField("portfolio_mct")
        ):
            data["portfolio_type"] = "MCT"
            mct = account_response.portfolio_mct
            data["margin"] = {
                "available_cash": to_float(mct.available_cash),
                "initial_margin": to_float(mct.initial_margin),
                "maintenance_margin": to_float(mct.maintenance_margin),
            }

        # --- Парсим позиции ---
        # Накопительное обновление: не очищаем data["positions"] на каждом событии,
        # а обновляем записи по символам, пришедшим в текущем событии.
        # Позиции, отсутствующие в событии, остаются без изменений.
        # Даже при quantity == 0 запись сохраняется в data["positions"].

        for position in account_response.positions:
            try:
                symbol = position.symbol if hasattr(position, "symbol") else "UNKNOWN"
                if symbol == "UNKNOWN":
                    continue  # пропускаем позиции без символа
                chain = options_chains.get(symbol)

                quantity = (
                    to_float(position.quantity)
                    if hasattr(position, "quantity")
                    else 0.0
                )
                current_price = (
                    to_float(position.current_price)
                    if hasattr(position, "current_price")
                    else 0.0
                )
                average_price = (
                    to_float(position.average_price)
                    if hasattr(position, "average_price")
                    else 0.0
                )
                maintenance_margin = (
                    to_float(position.maintenance_margin)
                    if hasattr(position, "maintenance_margin")
                    else 0.0
                )
                daily_pnl = (
                    to_float(position.daily_pnl)
                    if hasattr(position, "daily_pnl")
                    else 0.0
                )
                unrealized_pnl = (
                    to_float(position.unrealized_pnl)
                    if hasattr(position, "unrealized_pnl")
                    else 0.0
                )

                # Тикер без суффикса биржи (например RIZ6@RTSX -> RIZ6)
                ticker = symbol.split("@")[0] if symbol else ""

                strike_price = chain.get("strike") if chain else ""
                opt_type_raw = chain.get("type") if chain else ""
                opt_type = "Put" if "PUT" in opt_type_raw.upper() else (
                    "Call" if "CALL" in opt_type_raw.upper() else opt_type_raw
                )
                opt_expdate = fmt_ru_date(chain.get("expiration_last_day")) if chain else ""
                option_base = chain.get("base_ticker") if chain else ""

                # Если позиция не нулевая производим расчёт
                if quantity != 0:
                    # Вычисление даты, цены и волатильности открытия позиции
                    open_data_result = calculate_open_data_open_price_open_iv(ticker, quantity)
                    # Проверяем, что функция вернула корректные данные
                    if open_data_result is not None and len(open_data_result) > 2:
                        open_datetime = open_data_result[0]
                        open_price = open_data_result[1] if open_data_result[1] is not None else 0.0
                        open_iv = open_data_result[2] if open_data_result[2] is not None else 0.0
                    else:
                        open_datetime = ""
                        open_price = 0.0
                        open_iv = 0.0
                else:
                    open_datetime = ""
                    open_price = 0.0
                    open_iv = 0.0

                # Безопасное обращение к котировкам: позиция могла быть по символу,
                # которого ещё нет в option_quotes (фьючерс или ещё неподписанный опцион)
                q = option_quotes.get(symbol, {}) if option_quotes else {}
                ts = q.get("timestamp")
                if ts:
                    dt = datetime.fromisoformat(ts)  # or datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                    last_time = dt.time()
                else:
                    last_time = None
                bid_price = q.get("bid")
                last = q.get("last")
                ask = q.get("ask")
                theoretical_price = q.get("theoretical_price")
                volatility = q.get("implied_volatility")
                bid_iv = q.get("bid_iv")
                last_iv = q.get("last_iv")
                ask_iv = q.get("ask_iv")
                delta = _safe_float(q.get("delta"))
                gamma = _safe_float(q.get("gamma"))
                theta = _safe_float(q.get("theta"))
                vega = _safe_float(q.get("vega"))
                volatility_f = _safe_float(volatility)
                bid_iv_f = _safe_float(bid_iv)
                last_iv_f = _safe_float(last_iv)
                ask_iv_f = _safe_float(ask_iv)
                # Вычисление TrueVega
                # opt_expdate в формате DD.MM.YYYY (см. fmt_ru_date)
                try:
                    exp_date = datetime.strptime(opt_expdate, "%d.%m.%Y").date()
                except (ValueError, TypeError):
                    exp_date = None
                DAYS_TO_MAT_DATE = (exp_date - datetime.now().date()).days if exp_date else 0
                TrueVega = 0 if DAYS_TO_MAT_DATE <= 0 else vega / (DAYS_TO_MAT_DATE ** 0.5)

                data["positions"][symbol] = {
                    'ticker': ticker,
                    'net_pos': quantity,
                    'strike': strike_price,
                    'opt_type': opt_type,
                    'expdate': opt_expdate,
                    'option_base': option_base,
                    'OpenDateTime': open_datetime,
                    'OpenPrice': round(open_price, 2) if open_price is not None else open_price,
                    'OpenIV': round(open_iv, 2) if open_iv is not None else open_iv,
                    'time_last': last_time,
                    'bid': bid_price,
                    'last': last,
                    'ask': ask,
                    'theor': theoretical_price,
                    'QuikVola': round(volatility_f, 2),
                    'bidIV': round(bid_iv_f, 2),
                    'lastIV': round(last_iv_f, 2),
                    'askIV': round(ask_iv_f, 2),
                    'Delta': round(delta * quantity, 2),
                    'Gamma': round(gamma * quantity, 4),
                    'Theta': round(theta * quantity, 2),
                    'Vega': round(vega * quantity, 2),
                    'TrueVega': round(TrueVega * quantity, 2),
                    "u_pnl": round(unrealized_pnl, 2),  # unrealized_pnl
                }

            except Exception as e:
                logger.error(f"Ошибка при парсинге позиции: {e}")

        # Проверяем, не появились ли новые опционы в портфеле
        update_option_subscriptions_from_portfolio()

    except Exception as e:
        logger.error(
            f"Необработанная ошибка в _on_account_info: {e}\n{traceback.format_exc()}"
        )


# ---------------------------------------------------------------------------
# Подписка на поток информации об аккаунте
# ---------------------------------------------------------------------------
def start_account_stream(fp_provider, account_id):
    """Запускает поток подписки на информацию об аккаунте"""
    fp_provider.on_account_info.subscribe(_on_account_info)
    stream_thread = Thread(
        target=fp_provider.subscribe_account_thread,
        name="AccountThread",
        args=(account_id,),
        daemon=True,
    )
    stream_thread.start()
    track_thread(stream_thread)
    logger.info(f"Подписка на аккаунт {account_id} запущена")
    return stream_thread


# ---------------------------------------------------------------------------
# Ожидание торговой сессии
# ---------------------------------------------------------------------------
def wait_for_trading_session(stop_event):
    """
    Ожидает начала торговой сессии.

    Во время ожидания дополнительно следит за состоянием соединения:
    если оно оборвалось (флаг _reconnect_requested или все потоки подписки
    на котировки мертвы) — немедленно переподключается, чтобы к началу торгов
    программа уже была готова к работе.
    """
    global _reconnect_requested

    while not stop_event.is_set():
        now = get_market_now()
        seconds_to_trade = schedule.time_until_trade(now).total_seconds()

        if seconds_to_trade <= 0:
            logger.info("Торговая сессия активна. Начинаем работу.")
            return

        # Если соединение оборвалось во время ожидания торгов — переподключаемся сразу
        if _reconnect_requested or (
            fp_provider is not None and not _connection_is_alive()
        ):
            _reconnect_requested = False
            logger.info(
                "Обнаружен обрыв соединения во время ожидания торгов. Переподключаемся..."
            )
            try:
                initialize_connection(stop_event)
                logger.info("Соединение восстановлено во время ожидания торгов.")
            except Exception as e:
                logger.error(
                    f"Не удалось переподключиться во время ожидания торгов: "
                    f"{e}\n{traceback.format_exc()}"
                )

        wait_seconds = min(seconds_to_trade, 60)
        logger.info(
            f"До начала торгов {seconds_to_trade:.0f} сек. Ждём {wait_seconds:.0f} сек..."
        )
        stop_event.wait(wait_seconds)


def wait_for_base_asset_prices(stop_event, timeout=30):
    """Ожидает появления котировок по всем базовым активам."""
    deadline = datetime.now().timestamp() + timeout
    while not stop_event.is_set():
        missing = [t for t in MAP if t not in base_asset_quotes]
        if not missing:
            return True
        if datetime.now().timestamp() > deadline:
            logger.warning(
                f"Не удалось получить котировки по всем базовым активам за {timeout} сек. Отсутствуют: {missing}"
            )
            return False
        sleep(0.5)
    return False


# ---------------------------------------------------------------------------
# Отладочный вывод котировок (периодический)
# ---------------------------------------------------------------------------
def close_provider():
    global fp_provider
    if fp_provider is not None:
        try:
            # Останавливаем все подписки на котировки
            for sub in _quote_subscriptions:
                sub.stop()
            _quote_subscriptions.clear()

            # Отписываемся от всех событий
            fp_provider.on_quote.unsubscribe(_on_quote)
            fp_provider.on_order.unsubscribe(_on_order)
            fp_provider.on_trade.unsubscribe(_on_trade)
            fp_provider.on_account_info.unsubscribe(_on_account_info)

            # Закрываем канал
            fp_provider.close_channel()
        except Exception:
            pass
        finally:
            fp_provider = None


def reset_state():
    """
    Сбрасывает все глобальные состояния перед повторным подключением.
    Удалены неиспользуемые переменные (_known_symbols, _subscribed_symbols,
    _last_change_time); добавлен сброс _previous_obsolete и очистка очереди задач.
    """
    global base_symbols, _last_positions_symbols, _last_orders_symbols
    global _options_chains_loaded, subscribed_option_symbols
    global \
        _stream_threads, \
        option_quotes, \
        options_chains, \
        active_orders, \
        _subscription_dirty
    global _full_ticker_to_map, _quote_subscriptions, _cleanup_dirty, _symbol_last_seen
    global _previous_obsolete, _io_task_queue
    global _last_trades_cleanup_enqueued

    _quote_subscriptions.clear()
    _symbol_last_seen.clear()
    base_symbols.clear()
    _full_ticker_to_map.clear()
    _last_positions_symbols.clear()
    _last_orders_symbols.clear()
    subscribed_option_symbols.clear()
    _stream_threads.clear()
    option_quotes.clear()
    options_chains.clear()
    active_orders.clear()
    _previous_obsolete.clear()
    _options_chains_loaded = False
    _subscription_dirty = False
    _cleanup_dirty = False
    _last_cleanup_check = 0.0
    _last_trades_cleanup_enqueued = 0.0

    # Выбрасываем накопившиеся фоновые задачи, чтобы после переподключения
    # не выполнялась устаревшая очистка/подписка по старым данным
    while not _io_task_queue.empty():
        try:
            _io_task_queue.get_nowait()
        except queue.Empty:
            break


def track_thread(thread):
    """Добавляет поток в список отслеживаемых и чистит завершённые."""
    _stream_threads.append(thread)
    # Удаляем мёртвые потоки, чтобы список не разрастался
    for t in _stream_threads[:]:
        if not t.is_alive():
            _stream_threads.remove(t)


def _connection_is_alive():
    """
    Проверяет, жив ли хотя бы один поток подписки на котировки.

    Используется как индикатор здоровья gRPC-соединения: если все потоки
    подписки на котировки мертвы, значит, канал с сервером потерян
    (в отличие от проверки is_alive всех потоков, этот метод не даёт ложных
    срабатываний на управляющие потоки вроде io_worker).
    """
    quote_threads = [t for t in _stream_threads if t.name.startswith("QuotesThread")]
    return bool(quote_threads) and all(t.is_alive() for t in quote_threads)


def get_backoff_delay(attempt):
    """Экспоненциальная задержка с джиттером: 5с, 10с, 20с, 40с, ... до 300с."""
    base = min(5 * (2**attempt), 300)
    jitter = random.uniform(0, 0.3 * base)
    return base + jitter


def initialize_connection(stop_event):
    """
    Полная инициализация подключения: создание провайдера,
    подписка на все потоки и загрузка данных.
    """
    global fp_provider, account_id, _options_chains_loaded

    # 1. Закрываем старый канал (внутри уже остановит и очистит подписки)
    close_provider()

    # 2. Создаём новый экземпляр FinamPy
    fp_provider = FinamPy()
    if not fp_provider.account_ids:
        fp_provider.account_ids = list(fp_provider.token_details().account_ids)
    if not fp_provider.account_ids:
        raise RuntimeError("Не найдено ни одного торгового счёта")
    account_id = fp_provider.account_ids[0]
    logger.info(f"Инициализация: работа с аккаунтом {account_id}")
    single_transaction_clearing()  # Очистка сделок закрытых инструментов

    # 3. Сбрасываем все глобальные состояния
    reset_state()

    # 4. Последовательность подписок
    subscribe_base_assets(fp_provider)  # заполняет base_symbols
    start_quotes_subscription(fp_provider)  # базовые активы
    wait_for_base_asset_prices(stop_event, timeout=30)
    load_options_chains(fp_provider)  # загружает цепочки опционов
    # start_quotes_subscription(fp_provider)      # перезапуск с опционами
    subscribe_orders(fp_provider, account_id)  # заявки
    subscribe_trades(fp_provider, account_id)  # сделки
    start_account_stream(fp_provider, account_id)  # аккаунт

    logger.info("Все подписки активны.")


def watchdog(stop_event):
    """
    Периодически проверяет доступность API через запрос серверного времени.
    Если запрос не проходит — инициирует переподключение (выставляет флаг).
    """
    global _reconnect_requested

    while not stop_event.is_set():
        if fp_provider is not None:
            try:
                # Проверка живости канала: получаем время на сервере
                clock: ClockResponse = fp_provider.call_function(
                    fp_provider.assets_stub.Clock, ClockRequest()
                )

                if clock is None:
                    raise ConnectionError(
                        "ClockRequest вернул None — соединение потеряно"
                    )

                # Дополнительно можно проверить, что время адекватное
                dt_server = datetime.fromtimestamp(
                    clock.timestamp.seconds + clock.timestamp.nanos / 1e9,
                    fp_provider.tz_msk,
                )
                logger.debug(
                    f"Watchdog: серверное время {dt_server:%d.%m.%Y %H:%M:%S} — соединение живо"
                )

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
def stream_main():
    logger.info("Запуск программы мониторинга аккаунта по расписанию биржи")
    global fp_provider, account_id, _reconnect_requested, _subscription_dirty
    global _last_cleanup_check

    stop_event = Event()

    def signal_handler(signum, frame):
        logger.info("Получен сигнал остановки. Завершаем работу...")
        stop_event.set()

    # Регистрация обработчиков сигналов возможна только в главном потоке
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    Thread(target=watchdog, args=(stop_event,), daemon=True).start()

    # Фоновый поток для задач ввода-вывода (очистка CSV, LastQuote),
    # чтобы не блокировать gRPC-потоки событий
    io_thread = Thread(
        target=io_worker, args=(stop_event,), daemon=True, name="IOWorkerThread"
    )
    io_thread.start()
    track_thread(io_thread)

    try:
        while not stop_event.is_set():
            wait_for_trading_session(stop_event)
            if stop_event.is_set():
                break

            # --- Подключение (первичное или после обрыва) ---
            attempt = 0
            while not stop_event.is_set():
                try:
                    # Если соединение уже живое (например, восстановлено во время
                    # ожидания торгов в wait_for_trading_session) — не инициализируем
                    # его повторно, чтобы избежать двойного переподключения.
                    if fp_provider is not None and _connection_is_alive():
                        logger.info("Соединение уже активно. Используем существующее.")
                        break
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
                if _reconnect_requested or not _connection_is_alive():
                    logger.warning("Обнаружен обрыв соединения. Переподключаемся...")
                    _reconnect_requested = False
                    break

                # Немедленный перезапуск при появлении новых опционов
                if _subscription_dirty:
                    _subscription_dirty = False
                    logger.info("Перезапуск подписки после добавления новых опционов")
                    restart_quotes_subscription()

                # Отложенная очистка устаревших опционов (проверяем не чаще раза в 5 секунд)
                if _cleanup_dirty and _time.time() - _last_cleanup_check >= 5.0:
                    _last_cleanup_check = _time.time()
                    logger.info("Периодическая очистка устаревших опционов")
                    cleanup_obsolete_subscriptions()

                stop_event.wait(1)

    except Exception as e:
        logger.error(f"Критическая ошибка в main: {e}\n{traceback.format_exc()}")
    finally:
        stop_event.set()
        close_provider()
        logger.info("Программа остановлена")


# ---------------------------------------------------------------------------
# Запуск stream_main() выполняется из дашборда в фоновом потоке
# ---------------------------------------------------------------------------

# Настройка логгера стрима (файл + консоль); дубли не добавляем
if not logger.handlers:
    _log_fmt = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s", "%d.%m.%Y %H:%M:%S")
    logger.setLevel(logging.INFO)
    _log_fh = logging.FileHandler("FINAM_Stream.log", encoding="utf-8")
    _log_fh.setFormatter(_log_fmt)
    logger.addHandler(_log_fh)
    _log_ch = logging.StreamHandler()
    _log_ch.setFormatter(_log_fmt)
    logger.addHandler(_log_ch)

# Одноразовая загрузка архивной истории сделок из старого CSV в память
load_trades_from_csv(os.path.join(DATA_DIR_FINAM, "Finam_Stream_Trades_ALL.csv"))


_csv_cache = {}


def read_csv_cached(name_file, sep=';', encoding=None):
    """Читает CSV с кэшированием по времени изменения файла (mtime).
    При ошибке чтения (файл перезаписывается внешним процессом) возвращает последнюю успешную версию"""
    path = temp_obj.substitute(name_file=name_file)
    mtime = os.path.getmtime(path)
    key = (name_file, sep, (encoding or '').lower())
    cached = _csv_cache.get(key)
    if cached and cached[0] == mtime:
        return cached[1].copy()
    try:
        df = pd.read_csv(path, sep=sep, encoding=encoding, low_memory=False)
        _csv_cache[key] = (mtime, df)
    except Exception as e:
        if cached:
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Ошибка чтения {name_file} ({e}), используются предыдущие данные")
            return cached[1].copy()
        raise
    return df.copy()

# Глобальные переменные для хранения данных
model_from_api = None
base_asset_list = None
option_list = None
option_df = None
central_strike = None

# Первый фьючерс в списке MAP
first_key = next(iter(MAP))


def utc_to_msk_datetime(dt, tzinfo=False):
    """Перевод времени из UTC в московское

    :param datetime dt: Время UTC
    :param bool tzinfo: Отображать временнУю зону
    :return: Московское время
    """
    dt_utc = utc.localize(dt)  # Задаем временнУю зону UTC
    # dt_msk = dt_utc.astimezone(tz_msk)  # Переводим в МСК
    dt_msk = dt_utc  # Не требуется перевод в МСК
    return dt_msk if tzinfo else dt_msk.replace(tzinfo=None)


def utc_timestamp_to_msk_datetime(seconds) -> datetime:
    """Перевод кол-ва секунд, прошедших с 01.01.1970 00:00 UTC в московское время

    :param int seconds: Кол-во секунд, прошедших с 01.01.1970 00:00 UTC
    :return: Московское время без временнОй зоны
    """
    dt_utc = datetime.fromtimestamp(seconds)  # Переводим кол-во секунд, прошедших с 01.01.1970 в UTC
    return utc_to_msk_datetime(dt_utc)  # Переводим время из UTC в московское


# Функция для получения данных с API при первом запуске приложения, далее каждые 10 секунд по запуску функции обратного вызова update_time(n)
def fetch_api_data():
    """Функция для получения данных с API"""
    global model_from_api, base_asset_list, option_list, option_df
    model_from_api = get_object_from_json_endpoint_with_retry('https://option-volatility-dashboard.ru/dump_model')

    # Список базовых активов
    base_asset_list = model_from_api[0]
    # print(f'base_asset_list: {base_asset_list}')

    # Список опционов
    option_list = model_from_api[1]

    # Предварительно подготовленный DataFrame опционов (строится один раз за обновление)
    option_df = pd.DataFrame.from_dict(option_list, orient='columns')
    option_df = option_df.loc[option_df['_volatility'] > 0]
    option_df['_expiration_datetime'] = pd.to_datetime(option_df['_expiration_datetime'], format='%a, %d %b %Y %H:%M:%S GMT')
    option_df['expiration_date'] = option_df['_expiration_datetime'].dt.strftime('%d.%m.%Y')

    # Вычисление и добавление в словарь центрального страйка
    for asset in base_asset_list:
        ticker = asset.get('_ticker')
        last_price = asset.get('_last_price')
        strike_step = MAP[ticker]['strike_step']
        central_strike = _calculate_central_strike(last_price, strike_step)
        asset.update({
            'central_strike': central_strike
        })

    return model_from_api


def get_object_from_json_endpoint_with_retry(url, method='GET', params={}, max_delay=180, timeout=10):
    """
    Модифицированная версия функции с механизмом повторных запросов при ошибке 502.
    Args:
        url (str): URL для запроса
        method (str): Метод HTTP запроса (по умолчанию 'GET')
        params (dict): Параметры запроса
        max_delay (int): Максимальная задержка между попытками в секундах
        timeout (int): Таймаут запроса в секундах

    Returns:
        dict: Данные из JSON ответа
    """
    attempt = 0
    while True:
        try:
            response = requests.request(method, url, params=params, timeout=timeout)
            response.raise_for_status()  # Вызываем исключение для всех ошибочных статусов
            # Получаем информацию о вызывающей функции
            frame = inspect.currentframe().f_back
            filename = os.path.basename(frame.f_code.co_filename)
            line_number = frame.f_lineno
            # print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Запрос к {url} успешно выполнен (строка: {line_number})")
            return response.json()

        except requests.exceptions.HTTPError as e:
            if response.status_code != 502:
                raise

            attempt += 1
            delay = min(2 ** attempt, max_delay)
            jitter = random.uniform(0, 1)
            wait_time = delay * jitter

            print(
                f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Попытка {attempt}: Получена ошибка 502. Ждём {wait_time:.1f} секунд перед повторной попыткой")
            time.sleep(wait_time)

        except requests.exceptions.Timeout:
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Timeout при запросе к {url}")
            raise


# Выполняем запрос при запуске
fetch_api_data()

# Фоновый поток обновления данных с API каждые 10 секунд
def fetch_api_data_loop(interval=10):
    while True:
        time.sleep(interval)
        try:
            fetch_api_data()
        except Exception as e:
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Ошибка фоновой загрузки данных: {e}")


fetch_thread = threading.Thread(target=fetch_api_data_loop, daemon=True)
fetch_thread.start()

# Список базовых активов
base_asset_ticker_list = {}
for i in range(len(base_asset_list)):
    base_asset_ticker_list.update({base_asset_list[i]['_ticker']: base_asset_list[i]['_base_asset_code']})

# Список опционов
df = pd.DataFrame.from_dict(option_list, orient='columns')
df = df.loc[df['_volatility'] > 0]
df['_expiration_datetime'] = pd.to_datetime(df['_expiration_datetime'], format='%a, %d %b %Y %H:%M:%S GMT')
df['_expiration_datetime'].dt.date
df['expiration_date'] = df['_expiration_datetime'].dt.strftime('%d.%m.%Y')
# print(df.columns)

dff = df[(df._base_asset_ticker == first_key)]  # оставим только опционы базового актива

base_asset_last_price = None
for asset in base_asset_list:
    if asset['_ticker'] == first_key:
        base_asset_last_price = asset['_last_price']  # получаем последнюю цену базового актива

dff_call = dff[(dff._type == 'C')]  # оставим только коллы

# My positions data
df_table = get_positions_df()
df_table_buy = df_table[(df_table.option_base == first_key) & (df_table.net_pos > 0) & (df_table.OpenIV > 0)]
df_table_sell = df_table[(df_table.option_base == first_key) & (df_table.net_pos < 0) & (df_table.OpenIV > 0)]
MyPos_ticker_list = []
for i in range(len(df_table)):
    MyPos_ticker_list.append(df_table['ticker'][i])
# DataFrame для отрисовки баланса TrueVega
df_table_base = df_table
df_table_base = df_table_base[df_table_base.option_base == first_key]

# My orders data
df_orders = get_orders_df()
df_orders = df_orders[(df_orders.opt_base == first_key)]
df_orders_buy = df_orders[(df_orders.opt_base == first_key) & (df_orders.operation == 'Купля')]
df_orders_sell = df_orders[(df_orders.opt_base == first_key) & (df_orders.operation == 'Продажа')]
# Converting DataFrame "df_orders" to a list "tikers" containing all the rows of column 'ticker'
tikers = df_orders['ticker'].tolist()

# My trades data
df_trades = get_trades_all_df()

# My positions history data
with open(temp_obj.substitute(name_file='MyPosHistory.csv'), 'r', encoding='UTF-8') as file:
    df_MyPosTilt = pd.read_csv(file, sep=';', low_memory=False)
file.close()

# MyEquity
# Чтение промежуточного файла
with open(temp_obj.substitute(name_file='Equity.CSV'), 'r') as file:
    df_equity = pd.read_csv(file, sep=',')
    df_equity['Date'] = pd.to_datetime(df_equity['Date'], format='%d.%m.%Y %H:%M:%S')
    df_equity = df_equity.sort_values('Date').reset_index(drop=True)
    # Получаем все столбцы кроме 'Date'
    cols_to_convert = df_equity.columns.drop('Date')
    # Удаляем пробелы и преобразуем в числа
    df_equity[cols_to_convert] = df_equity[cols_to_convert].replace(' ', '', regex=True)
    df_equity[cols_to_convert] = df_equity[cols_to_convert].apply(pd.to_numeric, errors='coerce')
file.close()


def update_bars_history():
    """Обновление истории свечей (баров) всех базовых активов из MAP.

    Используем готовую функцию broker.get_history: она сама скачивает лишь недостающие
    в истории бары и через FileStorage.set_bars сохраняет их в текстовые файлы
    data/Finam/SPBFUT.{тикер}_{time_frame}.txt. Остаётся лишь обрезать файлы
    до глубины истории: M15 - 14 дней, D1 - 140 дней.
    """
    broker = brokers['Ф']  # Брокер по ключу из Config.py словаря brokers
    time_frames = {  # Таймфрейм и глубина истории в днях
        'M15': 14,  # 15-минутные бары, глубина истории 14 дней
        'D1': 140,  # Дневные бары, глубина истории 140 дней
    }
    for ticker in iter(MAP):  # Пробегаемся по всем базовым активам из MAP
        dataname = f'SPBFUT.{ticker}'  # Название тикера
        symbol = broker.get_symbol_by_dataname(dataname)  # Тикер по названию
        if symbol is None:  # Если тикер не найден у брокера
            print(f"Тикер {dataname} не найден у брокера Финам")
            continue  # переходим к следующему активу, дальше не продолжаем
        for time_frame, depth_days in time_frames.items():  # Пробегаемся по всем таймфреймам
            dt_from = datetime.now() - timedelta(days=depth_days)  # Минимальная дата, с которой нужна история
            print(f"Запрос свечей: {dataname} {time_frame} начиная с даты {dt_from:%d.%m.%Y %H:%M}")
            try:
                # Скачивает лишь недостающие бары и сохраняет историю в файл через storage.set_bars
                broker.get_history(symbol, time_frame, dt_from=dt_from)
            except Exception as e:  # Если данные не получены (например, инструмент недоступен у брокера)
                print(f"Ошибка при получении свечей: {dataname} {time_frame}: {e}")
                continue  # переходим к следующему таймфрейму, дальше не продолжаем
            filename = f'{broker.storage.datapath}{dataname}_{time_frame}.txt'  # Полное имя файла истории
            if os.path.isfile(filename):  # Если файл истории создан
                df = pd.read_csv(filename, sep=broker.storage.delimiter, index_col='datetime',
                                 parse_dates=['datetime'], dayfirst=True)  # Читаем бары из файла
                df = df[df.index >= dt_from].sort_index()  # Оставляем только нужную глубину истории
                df.to_csv(filename, sep=broker.storage.delimiter, date_format=broker.storage.dt_format)  # Сохраняем историю в файл
                print(f"Сохранено баров: {len(df)} в {filename}")

# Обновление истории свечей всех базовых активов из MAP в файлы data/Finam
update_bars_history()

# Подписка на бары (свечи) всех используемых базовых активов из MAP и ведение единого словаря
# bars: <тикер> -> список баров в порядке поступления по времени. В конце списка всегда лежит
# текущий НЕЗАВЕРШЁННЫЙ бар, который обновляется на каждое изменение (тикание) свечи; когда бар
# закрывается, он остаётся в списке как завершённый, а в конец добавляется новый незавершённый бар.
#
# Механизм (как в FinLabPy/Brokers/Examples/unfinished_bar.py): обёртка FinLabPy (брокер Финам)
# через событие on_new_bar отдаёт только ЗАКРЫТЫЕ бары, а незавершённый бар непрерывно обновляет
# в broker.last_bars. Чтобы ловить каждое обновление незавершённого бара, подписываемся на событие
# ПРОВАЙДЕРА broker.provider.on_new_bar и читаем из broker.last_bars уже готовый объект Bar.

bar_subscription_broker = brokers['Ф']  # Брокер Финам для подписки на бары
bar_subscription_time_frame = 'M15'  # Таймфрейм подписки на бары
bars = {}  # Словарь баров: <тикер> -> [завершённые бары по порядку, незавершённый бар (всегда последний)]


def upsert_bar(ticker, bar: Bar):
    """Добавление/обновление бара в списке словаря bars.

    Гарантирует уникальность по времени (дубликатов нет) и порядок по времени,
    при этом последним в списке всегда остаётся текущий (незавершённый) бар.
    """
    bar_bars = bars.setdefault(ticker, [])  # Список баров тикера
    if bar_bars and bar_bars[-1].datetime == bar.datetime:  # Частый случай: это последний (незавершённый) бар
        bar_bars[-1] = bar  # то просто обновляем его
        return
    for i in range(len(bar_bars) - 1, -1, -1):  # Ищем бар с таким же временем среди остальных
        if bar_bars[i].datetime == bar.datetime:  # Если такой бар уже есть
            bar_bars[i] = bar  # то обновляем его на том же месте, не создавая дубликат
            return
    bar_bars.append(bar)  # Нового бара ещё нет - добавляем в конец
    bar_bars.sort(key=lambda b: b.datetime)  # Восстанавливаем порядок по времени


def on_completed_bar(bar: Bar):
    """Обработчик закрытия бара по подписке обёртки FinLabPy (срабатывает только при закрытии бара)"""
    ticker = bar.dataname.removeprefix('SPBFUT.')  # Тикер по названию
    upsert_bar(ticker, bar)  # Записываем завершённый бар в словарь
    # print(f'Завершён бар: {bar}')


def on_unfinished_bar(response: SubscribeBarsResponse, finam_tf: TimeFrame.ValueType):
    """Обработчик обновления незавершённого бара по подписке провайдера (срабатывает на каждое обновление свечи)"""
    ticker = response.symbol.split('@')[0]  # Тикер из тикера Финама ('RIZ6@RTSX')
    key = (f'SPBFUT.{ticker}', bar_subscription_time_frame)  # Ключ в справочнике последних бар брокера
    unfinished = bar_subscription_broker.last_bars.get(key)  # Незавершённый бар (обёртка уже перевела его в Bar)
    if unfinished is None:  # Если бара ещё нет
        return  # то выходим, дальше не продолжаем
    upsert_bar(ticker, unfinished)  # Обновляем незавершённый бар (всегда последний в списке)


def get_candles_df(ticker, limit_time):
    """Построение DataFrame свечей M15 по истории из файла + живым барам подписки (фильтр по базовому активу и времени)"""
    all_bars = []
    symbol = bar_subscription_broker.get_symbol_by_dataname(f'SPBFUT.{ticker}')  # Спецификация тикера
    if symbol is not None:  # Если тикер найден
        file_bars = bar_subscription_broker.storage.get_bars(symbol, bar_subscription_time_frame)  # История из файла data/Finam
        if file_bars:  # Если в файле есть бары
            all_bars.extend(file_bars)  # то добавляем их
    all_bars.extend(bars.get(ticker, []))  # Живые бары подписки (последний - незавершённый бар)
    if not all_bars:  # Если баров нет совсем
        return pd.DataFrame(columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
    df_candles = pd.DataFrame([bar.to_dict() for bar in all_bars])  # Бары в DataFrame
    df_candles = df_candles.drop_duplicates(subset=['datetime'], keep='last').sort_values('datetime')  # Убираем дубликаты по времени, сортируем
    df_candles['datetime'] = pd.to_datetime(df_candles['datetime'])  # Дата и время бара
    return df_candles[(df_candles.datetime > limit_time)]  # Фильтр по времени


# Подписка на бары всех базовых активов из MAP
bar_subscription_broker.on_new_bar.subscribe(on_completed_bar)  # Обработчик завершённых бар
bar_subscription_broker.provider.on_new_bar.subscribe(on_unfinished_bar)  # Обработчик незавершённых бар
for ticker in iter(MAP):  # Пробегаемся по всем базовым активам из MAP
    dataname = f'SPBFUT.{ticker}'  # Название тикера
    symbol = bar_subscription_broker.get_symbol_by_dataname(dataname)  # Тикер по названию
    if symbol is None:  # Если тикер не найден у брокера
        print(f'Тикер {dataname} не найден у брокера Финам, пропускаем подписку')
        continue  # переходим к следующему активу, дальше не продолжаем
    bar_subscription_broker.subscribe_history(symbol, bar_subscription_time_frame)  # Подписка на бары


# Корректное закрытие брокера перед завершением работы программы
def shutdown_bars_subscription():
    """Отписка от баров и корректное закрытие брокера перед завершением работы программы"""
    try:  # Пытаемся
        bar_subscription_broker.provider.on_new_bar.unsubscribe(on_unfinished_bar)  # отписаться от незавершённых бар
        bar_subscription_broker.on_new_bar.unsubscribe(on_completed_bar)  # отписаться от завершённых бар
        bar_subscription_broker.unsubscribe_all_history()  # отменить все подписки на историю
    except Exception as e:  # При ошибке отписки
        print(f'Ошибка при отписке от баров: {e}')
    try:  # Пытаемся
        bar_subscription_broker.close()  # корректно закрыть брокера (закрывает канал, потоки подписки завершаются)
        print('Брокер корректно закрыт')
    except Exception as e:  # При ошибке закрытия
        print(f'Ошибка при закрытии брокера: {e}')


atexit.register(shutdown_bars_subscription)  # Закрытие брокера при завершении работы программы


# Сборка основного файла истории MyEquity
try:
    with open(temp_obj.substitute(name_file='MyEquity.CSV'), 'r') as file:
        df_myequity = pd.read_csv(file, sep=',', low_memory=False)
        df_myequity['Date'] = pd.to_datetime(df_myequity['Date'], format='%Y-%m-%d %H:%M:%S')
        df_myequity = df_myequity.sort_values('Date').reset_index(drop=True)
except pd.errors.EmptyDataError:
    # Если файл пустой, создаем пустой DataFrame с нужными колонками
    df_myequity = pd.DataFrame(columns=df_equity.columns)

# Объединяем df_equity и df_myequity
df_combined = pd.concat([df_equity, df_myequity], ignore_index=True)
# Удаляем дубликаты
df_combined = df_combined.drop_duplicates()
# Удаляем возможные дубликаты по дате, оставляя последнюю запись
df_combined = df_combined.drop_duplicates(subset=['Date'], keep='last')
df_combined = df_combined.sort_values('Date').reset_index(drop=True)

# Сохранить df_combined в файл MyEquity.CSV с разделителем запятая
df_combined.to_csv(temp_obj.substitute(name_file='MyEquity.CSV'), sep=',', index=False)


def zero_to_nan(values):
    """Replace every 0 with 'nan' and return a copy."""
    return [float('nan') if x == 0 else x for x in values]


# Список базовых активов, вычисление и добавление в словарь центрального страйка
for asset in base_asset_list:
    ticker = asset.get('_ticker')
    last_price = asset.get('_last_price')
    strike_step = MAP[ticker]['strike_step']
    central_strike = _calculate_central_strike(last_price, strike_step)  # вычисление центрального страйка
    asset.update({
        'central_strike': central_strike
    })
# print('base_asset_list:', base_asset_list) # вывод списка базовых активов
base_asset_ticker_list = {}
# Создание словаря с базовыми активами и их кодами
for i in range(len(base_asset_list)):
    # print(base_asset_list[i]['_ticker'])
    base_asset_ticker_list.update({base_asset_list[i]['_ticker']: base_asset_list[i]['_base_asset_code']})
# print(base_asset_ticker_list)

# Список опционов из dump_model
option_list = model_from_api[1]
current_datetime = datetime.now()
df = pd.DataFrame.from_dict(option_list, orient='columns')
df = df.loc[df['_volatility'] > 0]
df['_expiration_datetime'] = pd.to_datetime(df['_expiration_datetime'], format='%a, %d %b %Y %H:%M:%S GMT')
df['_expiration_datetime'].dt.date
df['expiration_date'] = df['_expiration_datetime'].dt.strftime('%d.%m.%Y')

# ОФОРМЛЕНИЕ ВКЛАДОК TAB
# Tabs content
tab1_content = [dcc.Graph(id='MyPosTiltHistory', style={'margin-top': 10})]
tab2_content = [dcc.Graph(id='naklon_history', style={'margin-top': 10})]
tab3_content = [  # IV ATM history
    dcc.Graph(id='plot_history', style={'margin-top': 10}),
    dcc.RadioItems(options=['Call', 'Put'],
                   value='Call',
                   inline=True,
                   style=dict(display='flex', justifyContent='right'),
                   id='my-radio-buttons-final'),
]
tab4_content = [  # MyPosTable
    html.Div([
        html.Div([
            html.Div(id='intermediate-value', style={'display': 'none'}),
            html.Div(
                dash_table.DataTable(
                    id='table',
                    data=df_table.to_dict('records'),
                    page_size=20,
                    style_table={'max-width': '50px'},
                    style_header={
                        'fontWeight': 'bold',
                        'backgroundColor': 'rgb(50, 50, 50)',
                        'color': 'white',
                        'textAlign': 'center'
                    },
                    style_data={
                        'backgroundColor': 'rgb(30, 30, 30)',
                        'color': 'white'
                    },
                    style_data_conditional=[
                        {
                            'if': {'filter_query': '{ticker} = "Total"'},
                            'fontWeight': 'bold',
                            'backgroundColor': 'rgb(60, 60, 60)'
                        },
                        {'if': {'column_id': 'time_last'}, 'color': '#DAA520'},
                        {'if': {'column_id': 'bid'}, 'color': '#3D9970'},
                        {'if': {'column_id': 'last'}, 'color': '#DAA520'},
                        {'if': {'column_id': 'ask'}, 'color': '#FF0000'},
                        # правило для net_pos == 0
                        {
                            'if': {'filter_query': 'net_pos eq 0'},
                            'color': '#CCCCCC',  # светло‑серый
                            'fontStyle': 'italic'  # курсив
                        },
                    ]
                ),
                style={'margin': '20px'}
            )
        ], style={'width': '85%', 'display': 'inline-block', 'verticalAlign': 'top'})
    ])
]

tab5_content = [  # Таблица моих сделок
    html.Div(id='intermediate-value1', style={'display': 'none'}),
    html.Div(
        dash_table.DataTable(
            id='trades',
            data=df_trades.to_dict('records'),
            page_size=14,
            style_table={'max-width': '50px'},
            style_header={
                'fontWeight': 'bold',
                'backgroundColor': 'rgb(50, 50, 50)',
                'color': 'white',
                'textAlign': 'center'
            },
            style_data={
                'backgroundColor': 'rgb(30, 30, 30)',
                'color': 'white'
            },
            style_data_conditional=[
                {
                    'if': {'filter_query': '{operation} eq "Купля"'},
                    'backgroundColor': 'rgb(30, 30, 30)',
                    'color': '#3D9970'
                },
                {
                    'if': {'filter_query': '{operation} eq "Продажа"'},
                    'backgroundColor': 'rgb(30, 30, 30)',
                    'color': '#FF0000'
                },
            ]
        ),
        style={'margin-left': '300px'}  # Сдвиг вправо
    )
]

tab6_content = [  # Таблица моих ордеров
    html.Div(id='intermediate-value2', style={'display': 'none'}),
    html.Div(
        dash_table.DataTable(
            id='orders',
            data=df_orders.to_dict('records'),
            page_size=14,
            style_table={'max-width': '50px'},
            style_header={
                'fontWeight': 'bold',
                'backgroundColor': 'rgb(50, 50, 50)',
                'color': 'white',
                'textAlign': 'center'
            },
            style_data={
                'backgroundColor': 'rgb(30, 30, 30)',
                'color': 'white'
            },
            style_data_conditional=[
                {
                    'if': {'filter_query': '{operation} eq "Купля"'},
                    'backgroundColor': 'rgb(30, 30, 30)',
                    'color': '#3D9970'
                },
                {
                    'if': {'filter_query': '{operation} eq "Продажа"'},
                    'backgroundColor': 'rgb(30, 30, 30)',
                    'color': '#FF0000'
                },
            ]
        ),
        # style={'margin-left': '400px'}  # Сдвиг вправо
    )
]

tab7_content = [dcc.Graph(id='MyEquityHistory', style={'margin-top': 10})]

# Создаем приложение Dash в тёмной теме
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.DARKLY])

# Установка темной темы для всех графиков
go.Figure(layout=go.Layout(template="plotly_dark"))

app.layout = html.Div(children=[

    html.Div(children=[  # График улыбки волатильности
        html.Div(children=[
            # График улыбки волатильности
            dcc.Graph(id='plot_smile'),
        ], style={'width': '87%', 'display': 'inline-block'}),

        html.Div(children=[  # Текущее время обновления данных
            # Текущее время обновления данных
            html.H6(id='last_update_time'),

            html.Div(  # Контейнер для двух селекторов в одну линию
                children=[
                    dcc.Dropdown(  # Селектор выбора базового актива
                        df._base_asset_ticker.unique(),
                        value=first_key,
                        id='dropdown-selection',
                        style={
                            'backgroundColor': '#2d2d2d',
                            'color': 'white',
                            'border': '1px solid #444',
                            'borderRadius': '4px',
                            'flex': '0 0 55%',  # 50% ширины контейнера
                        },
                        className='dark-dropdown'
                    ),
                    dcc.Dropdown(  # Селектор выбора количества страйков
                        options=[{'label': str(i), 'value': i} for i in range(3, 16)],
                        value=11,
                        id='num_srikes_selection',
                        style={
                            'backgroundColor': '#2d2d2d',
                            'color': 'white',
                            'border': '1px solid #444',
                            'borderRadius': '4px',
                            'flex': '1 1 auto',  # занимает оставшиеся 30%
                            'marginLeft': '8px',  # небольшой отступ между селекторами
                        },
                        className='dark-dropdown'
                    ),
                ],
                style={
                    'display': 'flex',
                    'flexDirection': 'row',
                    'alignItems': 'center',
                    'width': '100%',
                }
            ),

            daq.Gauge(
                # Спидометр TrueVega # https://stackoverflow.com/questions/69275527/python-dash-gauge-how-can-i-use-strings-as-values-instead-of-numbers
                id="graph-gauge",
                units="TrueVega",
                label='TrueVega',
                labelPosition='bottom',
                color={
                    "ranges": {
                        "red": [0, 2],
                        "pink": [2, 4],
                        "#ADD8E6": [4, 6],
                        "#4169E1": [6, 8],
                        "blue": [8, 10],
                    },
                },
                scale={
                    "custom": {
                        1: {"label": "Strong Sell"},
                        3: {"label": "Sell"},
                        5: {"label": "Neutral"},
                        7: {"label": "Buy"},
                        9: {"label": "Strong Buy"},
                    }
                },
                value=0,
                max=10,
                min=0,
            ),
        ], style={'display': 'inline-block'}),

    ], style={'display': 'flex', 'flexDirection': 'row'}),

    html.Div(children=[

        dbc.Tabs(id='main-tabs', active_tab='tab-1', children=[
            dbc.Tab(tab1_content, label='MyPos history', tab_id='tab-1'),
            dbc.Tab(tab2_content, label='Наклон улыбки', tab_id='tab-2'),
            dbc.Tab(tab3_content, label='IV ATM history', tab_id='tab-3'),
            dbc.Tab(tab4_content, label='MyPos table', tab_id='tab-4'),
            dbc.Tab(tab5_content, label='MyTrades table', tab_id='tab-5'),
            dbc.Tab(tab6_content, label='MyOrders table', tab_id='tab-6'),
            dbc.Tab(tab7_content, label='MyEquity', tab_id='tab-7'),
        ]),

        # Интервал обновления данных - 5 секунд
        dcc.Interval(
            id='interval-component',
            interval=5000,
            n_intervals=0),
        # Интервал обновления данных - 10 секунд
        dcc.Interval(
            id='interval-10sec',
            interval=10000,  # 10 секунд
            n_intervals=0),

        # Интервал обновления данных - 1 минута
        dcc.Interval(
            id='interval-1min',
            interval=60000,  # 1 минута
            n_intervals=0),

        # Интервал обновления данных - 5 минут
        dcc.Interval(
            id='interval-5min',
            interval=300000,  # 5 минут
            n_intervals=0),

        # Интервал обновления данных - 60 минут
        dcc.Interval(
            id='interval-60min',
            interval=3600000,  # 60 минут
            n_intervals=0),

        # Слайдер
        dcc.Slider(0, 28,
                   id='my_slider',
                   step=None,
                   marks={
                       1: '0.5d',
                       2: '1d',
                       4: '2d',
                       6: '3d',
                       10: '5d',
                       14: '7d',
                       20: '10d',
                       28: '14d'
                   },
                   value=6,
                   className='dark-slider'
                   ),
        html.Div(id='slider-output-1'),
    ])
])

# --- CALLBACKS ---

# Колбэк для обновления времени последнего обновления данных с периодичностью 10 секунд
@app.callback(Output('last_update_time', 'children'),
              [Input('interval-component', 'n_intervals')])
def update_time(n):
    # Данные обновляются в фоновом потоке fetch_api_data_loop
    # My portfoloio info data
    with open(temp_obj.substitute(name_file='QUIK_MyPortfolioInfo.csv'), 'r') as file:
        info = file.read()
    return [
        'Last update: {}'.format(datetime.now().strftime('%d.%m.%Y %H:%M:%S')),
        html.Br(),
        html.Pre(info)
    ]


# Обновление графика улыбки волатильности
@app.callback(
    Output('plot_smile', 'figure', allow_duplicate=True),
    [
        Input('dropdown-selection', 'value'),
        Input('num_srikes_selection', 'value'),  # <-- добавили Input
        Input('interval-component', 'n_intervals')
    ],
    prevent_initial_call=True
)
def update_output_smile(value, num_strikes, n):  # <-- новый параметр num_strikes
    try:
        # Список опционов (предрасчитанный DataFrame из fetch_api_data)
        df = option_df

        dff = df[(df._base_asset_ticker == value)]

        base_asset_last_price = None
        strike_step = None
        strikes_count = num_strikes
        for asset in base_asset_list:
            if asset['_ticker'] == value:
                base_asset_last_price = asset['_last_price']
                strike_step = MAP[value]['strike_step']
                # Используем значение из Dropdown вместо фиксированного max_strikes_count
                strikes_count = num_strikes

        if base_asset_last_price is None or strike_step is None:
            print(f"update_output_smile: тикер {value} не найден в base_asset_list/MAP")
            raise PreventUpdate

        strikes = get_list_of_strikes(base_asset_last_price, strike_step, strikes_count)
        # print(strikes)

        # Фильтруем данные по выбранному количеству страйков в селекторе по умолчанию
        dff = dff[dff['_strike'].isin(strikes)]

        dff_call = dff[(dff._type == 'C')]  # оставим только коллы

        # Получаем уникальные даты истечения
        exp_dates = dff_call['expiration_date'].unique()

        # Создаем словарь сопоставления дат и цветов
        colors = px.colors.qualitative.Plotly[:len(exp_dates)]
        expdate_colors = dict(zip(exp_dates, colors))

        def get_exp_color(exp_day):
            # Даты истечения позиций/ордеров могут отсутствовать среди серий коллов
            return expdate_colors.get(exp_day, 'gray')

        # My positions data
        df_table = get_positions_df()
        df_table_buy = df_table[(df_table.option_base == value) & (df_table.net_pos > 0) & (df_table.OpenIV > 0)]
        df_table_sell = df_table[(df_table.option_base == value) & (df_table.net_pos < 0) & (df_table.OpenIV > 0)]
        MyPos_ticker_list = df_table['ticker'].tolist()
        # DataFrame для отрисовки баланса TrueVega
        df_table_base = df_table
        df_table_base = df_table_base[df_table_base.option_base == value]

        # My orders data
        df_orders = get_orders_df()
        df_orders = df_orders[(df_orders.opt_base == value)]
        df_orders_buy = df_orders[(df_orders.opt_base == value) & (df_orders.operation == 'Купля')]
        df_orders_sell = df_orders[(df_orders.opt_base == value) & (df_orders.operation == 'Продажа')]
        # Converting DataFrame "df_orders" to a list "tikers" containing all the rows of column 'ticker'
        tikers = df_orders['ticker'].tolist()

        # Create figure with secondary y-axis
        fig = make_subplots(specs=[[{"secondary_y": True}]])

        # Рисуем график улыбки с уникальными цветами
        for exp_day in exp_dates:
            dff_smile = dff_call[dff_call.expiration_date == exp_day]
            fig.add_trace(go.Scatter(
                x=dff_smile['_strike'],
                y=dff_smile['_volatility'],
                mode='lines+text',
                name=exp_day,
                line=dict(color=get_exp_color(exp_day))
            ), secondary_y=False)

        # Мои позиции BUY
        for exp_day in df_table_buy['expdate'].unique():
            df_buy = df_table_buy[df_table_buy.expdate == exp_day]
            fig.add_trace(go.Scatter(
                x=df_buy['strike'],
                y=df_buy['OpenIV'],
                mode='markers+text',
                text=df_buy['OpenIV'],
                textposition='middle left',
                marker=dict(
                    size=11,
                    symbol="star-triangle-up-open",
                    color=get_exp_color(exp_day)
                ),
                name=f'My Pos Buy {exp_day}',
                customdata=df_buy[['opt_type', 'net_pos', 'expdate', 'ticker']],
                hovertemplate="<b>%{customdata}</b>"
            ))

        # Мои позиции SELL
        for exp_day in df_table_sell['expdate'].unique():
            df_sell = df_table_sell[df_table_sell.expdate == exp_day]
            fig.add_trace(go.Scatter(
                x=df_sell['strike'],
                y=df_sell['OpenIV'],
                mode='markers+text',
                text=df_sell['OpenIV'],
                textposition='middle left',
                marker=dict(
                    size=11,
                    symbol="star-triangle-down-open",
                    color=get_exp_color(exp_day)
                ),
                name=f'My Pos Sell {exp_day}',
                customdata=df_sell[['opt_type', 'net_pos', 'expdate', 'ticker']],
                hovertemplate="<b>%{customdata}</b><br>"
            ))

        # Мои ордерра BUY
        for exp_day in df_orders_buy['expdate'].unique():
            df_order_buy = df_orders_buy[df_orders_buy.expdate == exp_day]
            fig.add_trace(go.Scatter(
                x=df_order_buy['strike'],
                y=df_order_buy['order_iv'],
                mode='markers+text',
                text=df_order_buy['order_iv'],
                textposition='middle left',
                marker=dict(
                    size=8,
                    symbol="cross-thin",
                    line=dict(width=1, color=get_exp_color(exp_day))
                ),
                name=f'My Orders BUY {exp_day}',
                customdata=df_order_buy[['operation', 'opt_type', 'expdate', 'price', 'ticker']],
                hovertemplate="<b>%{customdata}</b><br>"
            ))

        # Мои ордерра SELL
        for exp_day in df_orders_sell['expdate'].unique():
            df_order_sell = df_orders_sell[df_orders_sell.expdate == exp_day]
            fig.add_trace(go.Scatter(
                x=df_order_sell['strike'],
                y=df_order_sell['order_iv'],
                mode='markers+text',
                text=df_order_sell['order_iv'],
                textposition='middle left',
                marker=dict(
                    size=8,
                    symbol="cross-thin",
                    line=dict(width=1, color=get_exp_color(exp_day))
                ),
                name=f'My Orders SELL {exp_day}',
                customdata=df_order_sell[['operation', 'opt_type', 'expdate', 'price', 'ticker']],
                hovertemplate="<b>%{customdata}</b><br>"
            ))

        # Last Bid Ask for MyPos and MyOrders
        favorites_list = MyPos_ticker_list + tikers  # слияние списков
        favorites_ticker_list = set(favorites_list)
        dff_MyPosOrders = df[(df._base_asset_ticker == value) & (df._ticker.isin(favorites_ticker_list))].copy()
        # dff_MyPosOrders = dff_MyPosOrders.apply(lambda x: round(x, 2))
        # Применяем округление только к числовым столбцам
        numeric_columns = dff_MyPosOrders.select_dtypes(include=['number']).columns
        dff_MyPosOrders[numeric_columns] = dff_MyPosOrders[numeric_columns].round(2)
        dff_MyPosOrders.loc[dff_MyPosOrders['_type'] == 'C', '_type'] = 'Call'
        dff_MyPosOrders.loc[dff_MyPosOrders['_type'] == 'P', '_type'] = 'Put'
        # Создаем пустую колонку для хранения преобразованного времени
        dff_MyPosOrders['converted_time'] = ''
        # Преобразование времени из UTC_seconds в MSK_time
        for i in dff_MyPosOrders['_last_price_timestamp']:
            if not isnan(i):  # Проверяем, что значение не NaN
                UTC_seconds = i
                MSK_time = utc_timestamp_to_msk_datetime(UTC_seconds)
                MSK_time_str = MSK_time.strftime('%H:%M:%S')

                # Обновляем соответствующую строку в DataFrame
                mask = dff_MyPosOrders['_last_price_timestamp'] == i
                dff_MyPosOrders.loc[mask, 'converted_time'] = MSK_time_str  # Используем новую колонку или существующую
        # print(dff_MyPosOrders['converted_time'])

        # ASK
        fig.add_trace(go.Scatter(x=dff_MyPosOrders['_strike'], y=dff_MyPosOrders['_ask_iv'],  # visible='legendonly',
                                 mode='markers', text=dff_MyPosOrders['_ask_iv'], textposition='top left',
                                 marker=dict(size=8, symbol="triangle-down", color='red'),
                                 name='Ask',
                                 customdata=dff_MyPosOrders[
                                     ['_type', '_ask', '_ask_iv', 'expiration_date', '_ticker']],
                                 hovertemplate="<b>%{customdata}</b><br>"
                                 ))

        # BID
        fig.add_trace(go.Scatter(x=dff_MyPosOrders['_strike'], y=dff_MyPosOrders['_bid_iv'],  # visible='legendonly',
                                 mode='markers', text=dff_MyPosOrders['_bid_iv'], textposition='top left',
                                 marker=dict(size=8, symbol="triangle-up", color='green'),
                                 name='Bid',
                                 customdata=dff_MyPosOrders[
                                     ['_type', '_bid', '_bid_iv', 'expiration_date', '_ticker']],
                                 hovertemplate="<b>%{customdata}</b><br>"
                                 ))

        # LAST
        fig.add_trace(
            go.Scatter(x=dff_MyPosOrders['_strike'], y=dff_MyPosOrders['_last_price_iv'], visible='legendonly',
                       mode='markers', text=dff_MyPosOrders['_last_price_iv'], textposition='top left',
                       marker=dict(size=8, color='goldenrod'),
                       name='Last',
                       customdata=dff_MyPosOrders[
                           ['_type', '_last_price', '_last_price_iv', 'expiration_date', '_ticker',
                            'converted_time']],
                       hovertemplate="<b>%{customdata}</b><br>"
                       ))

        # # TrueVega позиции
        # fig.add_trace(go.Bar(x=df_table_base['strike'], y=df_table_base['TrueVega'], text=df_table_base['TrueVega'],
        # textposition='auto', name='TrueVega', opacity=0.1), secondary_y=True)

        # TrueVega позиции
        for exp_day in exp_dates:
            df_filtered = df_table_base[df_table_base.expdate == exp_day]
            fig.add_trace(
                go.Bar(
                    x=df_filtered['strike'],
                    y=df_filtered['TrueVega'],
                    text=df_filtered['TrueVega'],
                    textposition='auto',
                    name=f'TrueVega {exp_day}',
                    marker_color=get_exp_color(exp_day),
                    opacity=0.1
                ),
                secondary_y=True
            )

        # После установки barmode='stack' переупорядочиваем легенду
        fig.update_layout(
            barmode='stack',
            legend_traceorder='normal'  # 'normal' - в порядке добавления, 'reversed' - обратный порядок
        )

        # Цена базового актива (вертикальная линия)
        fig.add_vline(x=base_asset_last_price, line_dash='dash', line_color='firebrick')

        fig.update_layout(height=450,
                          title_text=f"Volatility smile, series <b>{value}<b>"
                          )

        # Легенда справа по центру
        fig.update_layout(
            legend=dict(
                yanchor="middle",
                y=0.5,
                xanchor="left",
                x=0.96,
                orientation="v"
            )
        )
        fig.update_layout(
            margin=dict(l=1, r=1, t=30, b=0),
        )

        # Обновление сетки - добавьте эти строки перед return fig
        fig.update_xaxes(
            gridwidth=1,  # Толщина горизонтальной сетки
            gridcolor='rgba(128, 128, 128, 0.3)',  # Цвет сетки
            zeroline=False,  # Убрать нулевую линию
            showgrid=True,  # Показать сетку
            tickfont=dict(size=10)  # Размер шрифта меток
        )

        fig.update_yaxes(
            gridwidth=1,  # Толщина горизонтальной сетки
            gridcolor='rgba(128, 128, 128, 0.3)',  # Цвет сетки
            zeroline=False,  # Убрать нулевую линию
            showgrid=True,  # Показать сетку
            tickfont=dict(size=10)  # Размер шрифта меток
        )

        # Для вторичной оси
        fig.update_yaxes(
            secondary_y=True,
            gridwidth=1,  # Толщина горизонтальной сетки
            gridcolor='rgba(128, 128, 128, 0.3)',  # Цвет сетки
            zeroline=False,  # Убрать нулевую линию
            showgrid=True,  # Показать сетку
            tickfont=dict(size=10)  # Размер шрифта меток
        )

        # убрать сетку правой оси
        fig['layout']['yaxis2']['showgrid'] = False

        fig.update_layout(
            plot_bgcolor='rgb(30, 30, 30)',
            paper_bgcolor='rgb(30, 30, 30)',
            font_color='white',
            xaxis=dict(
                gridcolor='rgb(60, 60, 60)',
                gridwidth=1,
                zerolinecolor='rgb(60, 60, 60)'
            ),
            yaxis=dict(
                gridcolor='rgb(60, 60, 60)',
                gridwidth=1,
                zerolinecolor='rgb(60, 60, 60)'
            )
        )

        fig.update_layout(uirevision=f'smile-{value}-{num_strikes}')

        return fig

    except Exception as e:
        print(f"Ошибка при обновлении графика улыбки волатильности: {str(e)}")
        raise PreventUpdate

# Обновление данных графика истории моей позиции
@app.callback(Output('MyPosTiltHistory', 'figure', allow_duplicate=True),
              [Input('dropdown-selection', 'value'),
               Input('my_slider', 'value'),
               Input('interval-component', 'n_intervals'),
               Input('main-tabs', 'active_tab'),
               ],
              prevent_initial_call=True)
def update_output_MyPosHistory(dropdown_value, slider_value, n, active_tab):
    if active_tab != 'tab-1':
        raise PreventUpdate
    limit_time = datetime.now() - timedelta(hours=12 * slider_value)
    time_frame = 'M15'
    df_candles = get_candles_df(dropdown_value, limit_time)  # Свечи M15 из словаря баров bars
    # print(df_candles)
    # print(limit_time)
    # ДАННЫЕ ИЗ csv
    # MyPosHistory.csv history data options volatility
    df_MyPosHistory = read_csv_cached('MyPosHistory.csv', sep=';')
    df_MyPosHistory = df_MyPosHistory[(df_MyPosHistory.option_base == dropdown_value)]

    df_MyPosHistory['DateTime'] = pd.to_datetime(df_MyPosHistory['DateTime'],
                                                 format='%Y-%m-%d %H:%M:%S')
    df_MyPosHistory.index = pd.DatetimeIndex(df_MyPosHistory['DateTime'])
    # df_MyPosHistory = df_MyPosHistory[(df_vol_history.type == radiobutton_value)]
    df_MyPosHistory = df_MyPosHistory[(df_MyPosHistory.DateTime > limit_time)]
    # Сортировка по времени (индексу) для корректного порядка точек на линиях
    df_MyPosHistory = df_MyPosHistory.sort_index()

    # Фильтрация аномальных значений market (пустой стакан на границах сессии):
    # market отбрасывается, если превышает theor более чем на 200% или неположительный
    df_MyPosHistory['market'] = pd.to_numeric(df_MyPosHistory['market'], errors='coerce')
    df_MyPosHistory['theor'] = pd.to_numeric(df_MyPosHistory['theor'], errors='coerce')
    market_mask = (df_MyPosHistory['market'] > df_MyPosHistory['theor'] * 3) | (df_MyPosHistory['market'] <= 0)
    df_MyPosHistory.loc[market_mask, 'market'] = None
    # print(df_MyPosHistory)

    # Данные о сделках
    # My trades data
    df_trades = read_csv_cached('QUIK_Stream_Trades.csv', sep=';', encoding='UTF-8')
    df_trades = df_trades[(df_trades.option_base == dropdown_value)]
    df_trades['datetime'] = pd.to_datetime(df_trades['datetime'],
                                           format='%d.%m.%Y %H:%M:%S')
    df_trades.index = pd.DatetimeIndex(df_trades['datetime'])
    df_trades = df_trades[(df_trades.datetime > limit_time)]
    # Сортировка по времени (индексу) для корректного порядка точек на линиях
    df_trades = df_trades.sort_index()
    # print(df_table)
    # Создаем столбец 'pos' в df_trades на основе значений из df_table
    df_table['pos'] = df_table['net_pos'].apply(lambda x: 'long' if x > 0 else 'short')
    df_trades = df_trades.merge(df_table[['ticker', 'pos']], on='ticker', how='left')
    # Удаляем строки, где 'pos' равен NaN
    df_trades = df_trades.dropna(subset=['pos'])

    # Create figure with secondary y-axis
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # График истории моей позиции (из MyPosHistory.cs)
    for pos in sorted(df_MyPosHistory['pos'].unique(), reverse=True):
        dff = df_MyPosHistory[df_MyPosHistory.pos == pos]
        color = 'red' if pos == "short" else 'green'
        fig.add_trace(go.Scatter(x=dff['DateTime'], y=dff['mypos'], visible='legendonly',
                                 legendgroup=pos,
                                 legendgrouptitle_text=pos,
                                 mode='lines+text',
                                 line=dict(dash='dot', color=color),
                                 name='MyPos'), secondary_y=True, )

    # График истории моей позиции ПО LAST цене из MyPosHistory
    for pos in sorted(df_MyPosHistory['pos'].unique()):
        dff = df_MyPosHistory[df_MyPosHistory.pos == pos]
        color = 'red' if pos == "short" else 'green'
        fig.add_trace(go.Scatter(x=dff['DateTime'], y=dff['last'],
                                 legendgroup=pos,
                                 legendgrouptitle_text=pos,
                                 mode='lines+text',
                                 line=dict(color=color),
                                 name='Last'), secondary_y=True, )

    # График истории моей позиции по цене Theor (из MyPosHistory.csv)
    for pos in sorted(df_MyPosHistory['pos'].unique(), reverse=True):
        dff = df_MyPosHistory[df_MyPosHistory.pos == pos]
        color = 'red' if pos == "short" else 'green'
        fig.add_trace(go.Scatter(x=dff['DateTime'], y=dff['theor'],
                                 legendgroup=pos,
                                 legendgrouptitle_text=pos,
                                 mode='lines+text',
                                 line=dict(color=color, width=1, dash='dot'),
                                 name='Theor'), secondary_y=True, )

    # График истории моей позиции ПО рынку из MyPosHistory
    for pos in sorted(df_MyPosHistory['pos'].unique(), reverse=True):
        dff = df_MyPosHistory[df_MyPosHistory.pos == pos]
        color = 'red' if pos == "short" else 'green'
        fig.add_trace(go.Scatter(x=dff['DateTime'], y=dff['market'], visible='legendonly',
                                 legendgroup=pos,
                                 legendgrouptitle_text=pos,
                                 mode='lines+text',
                                 line=dict(color=color, dash='longdashdot'),
                                 name='Market'), secondary_y=True)

    # Мои сделки (trades) на графике
    for opt in sorted(df_trades['ticker'].unique()):
        df_ticker = df_trades[df_trades.ticker == opt]

        # Создаем отдельные серии для покупок и продаж
        df_buy = df_ticker[df_ticker['operation'] == 'Купля']
        df_sell = df_ticker[df_ticker['operation'] == 'Продажа']
        if not df_buy.empty:
            pos = df_buy['pos'].iloc[0]
            fig.add_trace(go.Scatter(x=df_buy['datetime'], y=df_buy['volatility'], visible='legendonly',
                                     legendgroup=pos,
                                     legendgrouptitle_text=pos,
                                     mode='markers', text=df_buy['volatility'], textposition='top left',
                                     marker=dict(size=8, symbol="triangle-up", color='green'),
                                     name=f'{opt} (купля)',
                                     customdata=df_buy[
                                         ['volatility', 'option_type', 'price', 'volume', 'expdate']],
                                     hovertemplate="<b>%{customdata}</b><br>"
                                     ), secondary_y=True, )

        if not df_sell.empty:
            pos = df_sell['pos'].iloc[0]
            fig.add_trace(go.Scatter(x=df_sell['datetime'], y=df_sell['volatility'], visible='legendonly',
                                     legendgroup=pos,
                                     legendgrouptitle_text=pos,
                                     mode='markers', text=df_sell['volatility'], textposition='top left',
                                     marker=dict(size=8, symbol="triangle-down", color='red'),
                                     name=f'{opt} (продажа)',
                                     customdata=df_sell[
                                         ['volatility', 'option_type', 'price', 'volume', 'expdate']],
                                     hovertemplate="<b>%{customdata}</b><br>"
                                     ), secondary_y=True, )

    fig.update_layout(legend=dict(groupclick="toggleitem"))

    # График Candles
    fig.add_trace(go.Candlestick(x=df_candles['datetime'],
                                 open=df_candles['open'],
                                 high=df_candles['high'],
                                 low=df_candles['low'],
                                 close=df_candles['close'],
                                 name=f"{dropdown_value} {time_frame}",
                                 increasing_line=dict(width=1),
                                 decreasing_line=dict(width=1)),
                  secondary_y=False)

    # Убираем неторговое время
    fig.update_xaxes(
        rangebreaks=[
            dict(bounds=["sat", "mon"]),  # hide weekends, eg. hide sat to before mon
            dict(bounds=[24, 7], pattern="hour"),  # hide hours outside of 9am-24pm
        ]
    )

    fig.update_layout(xaxis_title=None)
    # Легенда справа по центру
    fig.update_layout(
        legend=dict(
            yanchor="middle",
            y=0.5,
            xanchor="left",
            x=0.96,
            orientation="v"
        )
    )

    # fig.update_layout(
    #     title_text=f'История моей позиции, option series <b>{dropdown_value}<b>', uirevision="Don't change"
    # )
    fig.update_layout(
        margin=dict(l=3, r=3, t=0, b=0),
    )

    # Обновление сетки - добавьте эти строки перед return fig
    fig.update_xaxes(
        gridwidth=1,  # Толщина горизонтальной сетки
        gridcolor='rgba(128, 128, 128, 0.3)',  # Цвет сетки
        zeroline=False,  # Убрать нулевую линию
        showgrid=True,  # Показать сетку
        tickfont=dict(size=10)  # Размер шрифта меток
    )

    fig.update_yaxes(
        gridwidth=1,  # Толщина горизонтальной сетки
        gridcolor='rgba(128, 128, 128, 0.3)',  # Цвет сетки
        zeroline=False,  # Убрать нулевую линию
        showgrid=True,  # Показать сетку
        tickfont=dict(size=10)  # Размер шрифта меток
    )

    # Для вторичной оси
    fig.update_yaxes(
        secondary_y=True,
        gridwidth=1,  # Толщина горизонтальной сетки
        gridcolor='rgba(128, 128, 128, 0.3)',  # Цвет сетки
        zeroline=False,  # Убрать нулевую линию
        showgrid=True,  # Показать сетку
        tickfont=dict(size=10)  # Размер шрифта меток
    )

    # Убрать сетку левой оси
    fig['layout']['yaxis']['showgrid'] = False

    fig.update_layout(
        plot_bgcolor='rgb(30, 30, 30)',
        paper_bgcolor='rgb(30, 30, 30)',
        font_color='white',
        xaxis=dict(
            gridcolor='rgb(60, 60, 60)',
            gridwidth=1,
            zerolinecolor='rgb(60, 60, 60)'
        ),
        yaxis=dict(
            gridcolor='rgb(60, 60, 60)',
            gridwidth=1,
            zerolinecolor='rgb(60, 60, 60)'
        )
    )

    # Сохранение зума и выбора в легенде между обновлениями;
    # сброс только при смене инструмента или глубины истории
    fig.update_layout(uirevision=f'mypos-{dropdown_value}-{slider_value}')

    return fig


# обновление данных графика истории волатильности на центральном страйке
@app.callback(Output('plot_history', 'figure', allow_duplicate=True),
              [Input('dropdown-selection', 'value'),
               Input('my_slider', 'value'),
               Input('my-radio-buttons-final', 'value'),
               Input('interval-component', 'n_intervals'),
               Input('main-tabs', 'active_tab'),
               ],
              prevent_initial_call=True)
def update_output_history(dropdown_value, slider_value, radiobutton_value, n, active_tab):
    if active_tab != 'tab-3':
        raise PreventUpdate
    limit_time = datetime.now() - timedelta(hours=12 * slider_value)
    time_frame = 'M15'
    df_candles = get_candles_df(dropdown_value, limit_time)  # Свечи M15 из словаря баров bars

    # ДАННЫЕ ИЗ DAMP/csv
    # OptionsVolaHistoryDamp.csv history data options volatility
    df_vol_history = read_csv_cached('OptionsVolaHistoryDamp.csv', sep=';')
    df_vol_history = df_vol_history[(df_vol_history.base_asset_ticker == dropdown_value)]
    # df_vol_history = df_vol_history.tail(limit * len(df_vol_history['expiration_datetime'].unique()) * 2) # глубина истории по количеству серий

    df_vol_history['DateTime'] = pd.to_datetime(df_vol_history['DateTime'], format='%Y-%m-%d %H:%M:%S')
    df_vol_history.index = pd.DatetimeIndex(df_vol_history['DateTime'])
    df_vol_history = df_vol_history[(df_vol_history.type == radiobutton_value)]
    df_vol_history = df_vol_history[(df_vol_history.DateTime > limit_time)]
    # print(df_vol_history)

    # Create figure with secondary y-axis
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # График истории волатильности ПО ДАННЫМ ИЗ DAMP (из CSV OptionsVolaHistoryDamp.csv)
    exp_dates = sorted(df_vol_history['expiration_datetime'].unique())
    colors = px.colors.qualitative.Plotly

    # Сначала определяем, какие даты истекли
    current_date = datetime.now().date()
    expired_dates = set()
    active_dates = []

    for d_exp in exp_dates:
        exp_date = pd.to_datetime(d_exp).date()
        if exp_date < current_date:
            expired_dates.add(d_exp)
        else:
            active_dates.append(d_exp)

    # Создаем словарь цветов для активных опционов
    active_colors = {}
    for i, d_exp in enumerate(active_dates):
        active_colors[d_exp] = colors[i % len(colors)]

    # График истории наклона улыбки ПО ДАННЫМ ИЗ DAMP
    for d_exp in exp_dates:
        dff = df_vol_history[df_vol_history.expiration_datetime == d_exp]

        # Определяем цвет: серый для истёкших опционов
        if d_exp in expired_dates:
            color = 'gray'
        else:
            color = active_colors[d_exp]

        fig.add_trace(go.Scatter(x=dff['DateTime'], y=dff['Real_vol'], visible='legendonly',
                                 legendgroup="group",
                                 legendgrouptitle_text="RealVol",
                                 mode='lines+text',
                                 line=dict(color=color),
                                 name=d_exp), secondary_y=True)

    # График истории БИРЖЕВОЙ волатильности (из CSV OptionsVolaHistoryDamp.csv)
    for d_exp in exp_dates:
        dff = df_vol_history[df_vol_history.expiration_datetime == d_exp]

        # Определяем цвет: серый для истёкших опционов
        if d_exp in expired_dates:
            color = 'gray'
        else:
            color = active_colors[d_exp]

        fig.add_trace(go.Scatter(x=dff['DateTime'], y=dff['Quik_vol'], visible='legendonly',
                                 legendgroup="group2",
                                 legendgrouptitle_text="QuikVol",
                                 mode='lines+text',
                                 line=dict(width=2, dash='dashdot', color=color),
                                 name=d_exp), secondary_y=True)

    fig.update_layout(legend=dict(groupclick="toggleitem"))

    # График Candles
    fig.add_trace(go.Candlestick(x=df_candles['datetime'],
                                 open=df_candles['open'],
                                 high=df_candles['high'],
                                 low=df_candles['low'],
                                 close=df_candles['close'],
                                 name=f"{dropdown_value} {time_frame}",
                                 increasing_line=dict(width=1),
                                 decreasing_line=dict(width=1)),
                  secondary_y=False)

    # Убираем неторговое время
    fig.update_xaxes(
        rangebreaks=[
            dict(bounds=["sat", "mon"]),  # hide weekends, eg. hide sat to before mon
            dict(bounds=[24, 7], pattern="hour"),  # hide hours outside of 9am-24pm
        ]
    )

    fig.update_layout(xaxis_title=None)
    # Легенда справа по центру
    fig.update_layout(
        legend=dict(
            yanchor="middle",
            y=0.5,
            xanchor="left",
            x=0.96,
            orientation="v"
        )
    )

    fig.update_layout(
        title_text=f'IV ATM history, put or call option series <b>{dropdown_value}<b>',
    )
    fig.update_layout(
        margin=dict(l=5, r=5, t=30, b=0),
    )

    # Обновление сетки - добавьте эти строки перед return fig
    fig.update_xaxes(
        gridwidth=1,  # Толщина горизонтальной сетки
        gridcolor='rgba(128, 128, 128, 0.3)',  # Цвет сетки
        zeroline=False,  # Убрать нулевую линию
        showgrid=True,  # Показать сетку
        tickfont=dict(size=10)  # Размер шрифта меток
    )

    fig.update_yaxes(
        gridwidth=1,  # Толщина горизонтальной сетки
        gridcolor='rgba(128, 128, 128, 0.3)',  # Цвет сетки
        zeroline=False,  # Убрать нулевую линию
        showgrid=True,  # Показать сетку
        tickfont=dict(size=10)  # Размер шрифта меток
    )

    # Для вторичной оси
    fig.update_yaxes(
        secondary_y=True,
        gridwidth=1,  # Толщина горизонтальной сетки
        gridcolor='rgba(128, 128, 128, 0.3)',  # Цвет сетки
        zeroline=False,  # Убрать нулевую линию
        showgrid=True,  # Показать сетку
        tickfont=dict(size=10)  # Размер шрифта меток
    )

    # Убрать сетку левой оси
    fig['layout']['yaxis']['showgrid'] = False

    fig.update_layout(
        plot_bgcolor='rgb(30, 30, 30)',  # Фон графика
        paper_bgcolor='rgb(30, 30, 30)',  # Фон области рисования
        font_color='white',  # Цвет текста
        xaxis=dict(  # Цвет вертикальных линий сетки
            gridcolor='rgb(60, 60, 60)',
            gridwidth=1,
            zerolinecolor='rgb(60, 60, 60)'
        ),
        yaxis=dict(  # Цвет горизонтальных линий сетки
            gridcolor='rgb(50, 50, 50)',
            gridwidth=0.5,
            zerolinecolor='rgb(50, 50, 50)'
        )
    )

    fig.update_layout(uirevision=f'mypos-{dropdown_value}-{slider_value}')

    return fig


# Наклон улыбки (обновление данных графика истории наклона улыбки)
@app.callback(Output('naklon_history', 'figure', allow_duplicate=True),
              [Input('dropdown-selection', 'value'),
               Input('my_slider', 'value'),
               Input('interval-component', 'n_intervals'),
               Input('main-tabs', 'active_tab'),
               ],
              prevent_initial_call=True)
def update_output_history_naklon(dropdown_value, slider_value, n, active_tab):
    if active_tab != 'tab-2':
        raise PreventUpdate
    limit_time = datetime.now() - timedelta(hours=12 * slider_value)
    time_frame = 'M15'
    df_candles = get_candles_df(dropdown_value, limit_time)  # Свечи M15 из словаря баров bars

    # Проверка на пустой DataFrame
    if df_candles.empty:
        return dash.no_update  # или вернуть пустой график/данные

    # ДАННЫЕ ИЗ DAMP/csv
    # OptionsSmileNaklonHistory.csv history data options volatility
    df_vol_history_naklon = read_csv_cached('OptionsSmileNaklonHistory.csv', sep=';')
    df_vol_history_naklon = df_vol_history_naklon[(df_vol_history_naklon.base_asset_ticker == dropdown_value)]
    # df_vol_history_naklon = df_vol_history_naklon.tail(limit * len(df_vol_history_naklon['expiration_datetime'].unique()) * 2) # глубина истории по количеству серий

    df_vol_history_naklon['DateTime'] = pd.to_datetime(df_vol_history_naklon['DateTime'],
                                                       format='%Y-%m-%d %H:%M:%S')
    df_vol_history_naklon.index = pd.DatetimeIndex(df_vol_history_naklon['DateTime'])
    # df_vol_history_naklon = df_vol_history_naklon[(df_vol_history.type == radiobutton_value)]
    df_vol_history_naklon = df_vol_history_naklon[(df_vol_history_naklon.DateTime > limit_time)]
    # print(df_vol_history_naklon)

    # Create figure with secondary y-axis
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # График истории наклона улыбки ПО ДАННЫМ ИЗ DAMP (из CSV OptionsSmileNaklonHistory.csv)
    # Для графиков с истекшей датой используется серый цвет
    # Для активных графиков используются стандартные цвета Plotly по порядку

    # График истории наклона улыбки ПО ДАННЫМ ИЗ DAMP и БИРЖЕВОЙ улыбки
    # Цвета серий графиков по дате экспирации должны совпадать
    # Для истёкших опционов использовать серый цвет

    # Получаем уникальные даты экспирации и сортируем их
    expiration_dates = sorted(df_vol_history_naklon['expiration_datetime'].unique())
    current_date = datetime.now().date()

    # Получаем стандартные цвета Plotly
    colors = px.colors.qualitative.Plotly
    color_index = 0

    # Создаем словарь цветов для каждой даты экспирации
    color_map = {}
    for d_exp in expiration_dates:
        exp_date = pd.to_datetime(d_exp).date()
        if exp_date < current_date:
            color_map[d_exp] = 'gray'  # Серый для истёкших
        else:
            color_map[d_exp] = colors[color_index % len(colors)]  # Цвета из палитры для активных
            color_index += 1

    # График истории наклона улыбки ПО ДАННЫМ ИЗ DAMP
    for d_exp in expiration_dates:
        dff = df_vol_history_naklon[df_vol_history_naklon.expiration_datetime == d_exp]
        color = color_map[d_exp]

        fig.add_trace(go.Scatter(
            x=dff['DateTime'],
            y=dff['Real'],
            visible='legendonly',
            legendgroup="group",
            legendgrouptitle_text="Real",
            mode='lines+text',
            name=d_exp,
            line=dict(color=color)
        ), secondary_y=True)

    # График истории наклона БИРЖЕВОЙ улыбки
    for d_exp in expiration_dates:
        dff = df_vol_history_naklon[df_vol_history_naklon.expiration_datetime == d_exp]
        color = color_map[d_exp]

        fig.add_trace(go.Scatter(
            x=dff['DateTime'],
            y=dff['Quik'],
            line=dict(width=1, dash='dashdot', color=color),
            name=d_exp,
            legendgroup="group2",
            legendgrouptitle_text="Quik",
            mode='lines+text',
            visible='legendonly'
        ), secondary_y=True)
    fig.update_layout(legend=dict(groupclick="toggleitem"))

    # График Candles
    fig.add_trace(go.Candlestick(x=df_candles['datetime'],
                                 open=df_candles['open'],
                                 high=df_candles['high'],
                                 low=df_candles['low'],
                                 close=df_candles['close'],
                                 name=f"{dropdown_value} {time_frame}",
                                 increasing_line=dict(width=1),
                                 decreasing_line=dict(width=1)),
                  secondary_y=False)

    # Убираем неторговое время
    fig.update_xaxes(
        rangebreaks=[
            dict(bounds=["sat", "mon"]),  # hide weekends, eg. hide sat to before mon
            dict(bounds=[24, 7], pattern="hour"),  # hide hours outside of 9am-24pm
        ]
    )

    fig.update_layout(xaxis_title=None)
    # Легенда справа по центру
    fig.update_layout(
        legend=dict(
            yanchor="middle",
            y=0.5,
            xanchor="left",
            x=0.96,
            orientation="v"
        )
    )

    # fig.update_layout(
    #     title_text=f'"Наклон улыбки" of the option series <b>{dropdown_value}<b>', uirevision="Don't change"
    # )
    fig.update_layout(
        margin=dict(l=3, r=3, t=0, b=0),
    )

    fig.update_layout(
        plot_bgcolor='rgb(30, 30, 30)',
        paper_bgcolor='rgb(30, 30, 30)',
        font_color='white',
        xaxis=dict(
            gridcolor='rgb(50, 50, 50)',
            gridwidth=0.5,
            zerolinecolor='rgb(50, 50, 50)'
        ),
        yaxis=dict(
            gridcolor='rgb(60, 60, 60)',
            gridwidth=1,
            zerolinecolor='rgb(60, 60, 60)'
        )
    )

    # Обновление сетки - добавьте эти строки перед return fig
    fig.update_xaxes(
        gridwidth=1,  # Толщина горизонтальной сетки
        gridcolor='rgba(128, 128, 128, 0.3)',  # Цвет сетки
        zeroline=False,  # Убрать нулевую линию
        showgrid=True,  # Показать сетку
        tickfont=dict(size=10)  # Размер шрифта меток
    )

    fig.update_yaxes(
        gridwidth=1,  # Толщина горизонтальной сетки
        gridcolor='rgba(128, 128, 128, 0.3)',  # Цвет сетки
        zeroline=False,  # Убрать нулевую линию
        showgrid=True,  # Показать сетку
        tickfont=dict(size=10)  # Размер шрифта меток
    )

    # Для вторичной оси
    fig.update_yaxes(
        secondary_y=True,
        gridwidth=1,  # Толщина горизонтальной сетки
        gridcolor='rgba(128, 128, 128, 0.3)',  # Цвет сетки
        zeroline=False,  # Убрать нулевую линию
        showgrid=True,  # Показать сетку
        tickfont=dict(size=10)  # Размер шрифта меток
    )

    # Убрать сетку левой оси
    fig['layout']['yaxis']['showgrid'] = False

    fig.update_layout(uirevision=f'naklon-{dropdown_value}-{slider_value}')

    return fig


## EQUITY HISTORY##
@app.callback(Output('MyEquityHistory', 'figure'),
              [Input('dropdown-selection', 'value'),
               Input('my_slider', 'value'),
               Input('interval-component', 'interval-60min'),
               Input('main-tabs', 'active_tab')],
              prevent_initial_call=True)
def update_equity_history(dropdown_value, slider_value, n, active_tab):
    if active_tab != 'tab-7':
        raise PreventUpdate
    global df_combined
    limit_time = datetime.now() - timedelta(hours=10 * 12 * slider_value)
    # Создаем копию для избежания предупреждения
    df_limited = df_combined[(df_combined.Date > limit_time)].copy()
    # Преобразуем формат даты
    df_limited['Date'] = pd.to_datetime(df_limited['Date'], format='%d.%m.%Y')

    # СВЕЧИ Данные для графика базового актива

    # Будем запрашивать глубину истории 140 дней
    dt_from = datetime.now() - timedelta(days=140)
    time_frame = 'D1'
    dataname = f'SPBFUT.{dropdown_value}'

    broker = brokers['Ф']  # Брокер по ключу из Config.py словаря brokers
    symbol = broker.get_symbol_by_dataname(dataname)  # Тикер по названию
    bars = broker.get_history(symbol, time_frame, dt_from=dt_from)  # Получаем историю тикера за 140 дней
    print(f"Запрос свечей: {dataname} {time_frame} начиная с даты {dt_from}")
    # print(f"Первый бар: {bars[0]}")  # Первый бар
    # print(f"Последний бар: {bars[-1]}")  # Последний бар
    df_candles = bars_to_df(bars)  # Все бары в pandas DataFrame pd_bars
    # print(df_candles)  # Все бары в pandas DataFrame pd_bars
    df_candles.reset_index(inplace=True)
    df_candles['datetime'] = pd.to_datetime(df_candles['datetime'], format='%d.%m.%Y %H:%M')
    df_candles = df_candles[(df_candles.datetime > limit_time)]
    # print(f"Данные свечей df_candles: {df_candles}")  # Все бары в pandas DataFrame pd_bars

    # Вычисление доходности
    if len(df_limited) > 1:
        initial_money = df_limited['Money'].iloc[0]
        final_money = df_limited['Money'].iloc[-1]
        profit = ((final_money - initial_money) / initial_money) * 100
        profit_year = profit * 365 / (slider_value * 5)
    else:
        profit = 0
        profit_year = 0

    # Create figure with secondary y-axis
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # График Money
    fig.add_trace(go.Scatter(x=df_limited['Date'], y=df_limited['Money'], mode='lines+text',
                             name='Money',
                             line=dict(color='red', width=3, dash='dashdot')),
                  secondary_y=True)

    # График GM
    fig.add_trace(go.Scatter(x=df_limited['Date'], y=df_limited['GM'], mode='lines+text',
                             name='GM', visible='legendonly',
                             line=dict(color='gray', width=1, dash='dashdot')),
                  secondary_y=True)

    # График Fee
    fig.add_trace(go.Scatter(x=df_limited['Date'], y=df_limited['Fee'], mode='lines+text',
                             name="Comiss",
                             visible='legendonly',
                             line=dict(color='gray', width=1, dash='dashdot')),
                  secondary_y=True)

    # График Candles
    fig.add_trace(go.Candlestick(x=df_candles['datetime'],
                                 open=df_candles['open'],
                                 high=df_candles['high'],
                                 low=df_candles['low'],
                                 close=df_candles['close'],
                                 name=f"{dropdown_value} {time_frame}",
                                 increasing_line=dict(width=1),
                                 decreasing_line=dict(width=1)),
                  secondary_y=False)

    fig.update_layout(
        annotations=[
            dict(
                x=0.94,
                y=0.11,
                xref="paper",
                yref="paper",
                text=f'Доходность за период {slider_value * 5} дн. в процентах: {profit:.2f}%',
                showarrow=False,
                xanchor='right',
                yanchor='top'
            ),
            dict(
                x=0.94,
                y=0.11,
                xref="paper",
                yref="paper",
                text=f'Доходность за период в процентах годовых: {profit_year:.2f}%',
                showarrow=False,
                xanchor='right',
                yanchor='top',
                yshift=-20
            )
        ]
    )
    # # Убираем неторговое время
    # fig.update_xaxes(
    #     rangebreaks=[
    #         dict(bounds=["sat", "mon"]),  # hide weekends, eg. hide sat to before mon
    #     ]
    # )
    # Убираем выходные дни
    fig.update_xaxes(
        rangebreaks=[
            dict(bounds=["sat", "mon"]),  # hide weekends, eg. hide sat to before mon
        ]
    )

    fig.update_layout(xaxis_title=None)
    # Легенда справа по центру
    fig.update_layout(
        legend=dict(
            yanchor="middle",
            y=0.5,
            xanchor="left",
            x=0.96,
            orientation="v"
        )
    )

    fig.update_layout(
        margin=dict(l=3, r=3, t=0, b=0),
    )

    # Убрать сетку левой оси
    fig['layout']['yaxis']['showgrid'] = False

    # В конце функции update_output_history перед return fig
    fig.update_layout(
        xaxis=dict(
            gridwidth=1,
            gridcolor='rgba(128, 128, 128, 0.3)'
        ),
        yaxis=dict(
            gridwidth=1,
            gridcolor='rgba(128, 128, 128, 0.3)'
        ),
        yaxis2=dict(  # Для вторичной оси
            gridwidth=1,
            gridcolor='rgba(128, 128, 128, 0.3)'
        )
    )

    fig.update_layout(
        plot_bgcolor='rgb(30, 30, 30)',
        paper_bgcolor='rgb(30, 30, 30)',
        font_color='white'
    )

    fig.update_layout(uirevision=f'equity-{dropdown_value}-{slider_value}')

    return fig


# Callback to update the table "MyPos Table"
@app.callback(
    Output('table', 'data', allow_duplicate=True),
    [Input('interval-component', 'n_intervals'),
     Input('dropdown-selection', 'value'),
     Input('main-tabs', 'active_tab')],
    prevent_initial_call=True)
def updateTable(n, value, active_tab):
    if active_tab != 'tab-4':
        raise PreventUpdate
    df_pos = get_positions_df()
    # Фильтрация строк по базовому активу option_base и тикеру ticker
    df_pos = df_pos[(df_pos['option_base'] == value) | (df_pos['ticker'] == value)]
    # Присвоение фьючерсу значения дельта
    df_pos.loc[df_pos['ticker'] == value, 'Delta'] = df_pos.loc[df_pos['ticker'] == value, 'net_pos']

    # Вычисление итогов для опционов по колонке net_pos
    total_net_pos = df_pos.loc[df_pos['ticker'] != value, 'net_pos'].sum()

    # Вычисление сумм
    total_delta = df_pos['Delta'].sum() if 'Delta' in df_pos.columns else 0
    total_gamma = round(df_pos['Gamma'].sum(), 5)
    total_theta = df_pos['Theta'].sum() if 'Theta' in df_pos.columns else 0
    total_vega = df_pos['Vega'].sum() if 'Vega' in df_pos.columns else 0
    total_true_vega = df_pos['TrueVega'].sum() if 'TrueVega' in df_pos.columns else 0
    total_u_pnl = df_pos['u_pnl'].sum() if 'u_pnl' in df_pos.columns else 0

    # Сортировать датафрейм df_pos по столбцу strike
    df_pos = df_pos.sort_values(by='strike')
    # Удаляем столбец option_base
    df_pos = df_pos.drop(columns=['option_base'], errors='ignore')
    # Добавляем столбец с порядковым номером строки, начиная с 1
    df_pos['num'] = range(1, len(df_pos) + 1)
    # Переставляем столбец 'num' в начало
    cols = ['num'] + [col for col in df_pos.columns if col != 'num']
    df_pos = df_pos[cols]

    # Создание строки итогов
    total_row = {col: '' for col in df_pos.columns}
    total_row['ticker'] = 'Total options'
    total_row['net_pos'] = total_net_pos
    total_row['Delta'] = round(total_delta, 2)
    total_row['Gamma'] = round(total_gamma, 4)
    total_row['Theta'] = round(total_theta, 2)
    total_row['Vega'] = round(total_vega, 2)
    total_row['TrueVega'] = round(total_true_vega, 2)
    total_row['u_pnl'] = round(total_u_pnl, 2)

    # Добавление строки итогов к данным
    df_pos_with_total = pd.concat([df_pos, pd.DataFrame([total_row])], ignore_index=True)

    return df_pos_with_total.to_dict('records')


# Callback to update the table "MyTrades Table"
@app.callback(
    Output('trades', 'data', allow_duplicate=True),
    [Input('interval-component', 'n_intervals'),
     Input('dropdown-selection', 'value'),
     Input('main-tabs', 'active_tab')],
    prevent_initial_call=True)
def updateTrades(n, value, active_tab):
    if active_tab != 'tab-5':
        raise PreventUpdate
    df_trades = get_trades_all_df()
    # Добавляем столбец с порядковым номером строки, начиная с 1
    df_trades['num'] = range(1, len(df_trades) + 1)
    # Переставляем столбец 'num' в начало
    cols = ['num'] + [col for col in df_trades.columns if col != 'num']
    df_trades = df_trades[cols]
    # Преобразование столбца trade_id в строку
    df_trades['trade_id'] = df_trades['trade_id'].astype(str)
    # Преобразование столбца order_id в строку
    df_trades['order_id'] = df_trades['order_id'].astype(str)
    # Фильтрация строк по базовому активу
    df_trades = df_trades[df_trades['option_base'] == value]

    return df_trades.to_dict('records')


# Callback to update the table "MyOrders Table"
@app.callback(
    Output('orders', 'data', allow_duplicate=True),
    [Input('interval-component', 'n_intervals'),
     Input('dropdown-selection', 'value'),
     Input('main-tabs', 'active_tab')],
    prevent_initial_call=True)
def updateOrders(n, value, active_tab):
    if active_tab != 'tab-6':
        raise PreventUpdate
    df_orders = get_orders_df()

    # Добавляем столбец с порядковым номером строки, начиная с 1
    df_orders['num'] = range(1, len(df_orders) + 1)
    # Переставляем столбец 'num' в начало
    cols = ['num'] + [col for col in df_orders.columns if col != 'num']
    df_orders = df_orders[cols]
    # Преобразование столбца order_num в строку
    df_orders['order_num'] = df_orders['order_num'].astype(str)
    # Фильтрация строк по базовому активу
    df_orders = df_orders[df_orders['opt_base'] == value]

    return df_orders.to_dict('records')


# Callback to update the graph-gauge Спидометр TrueVega
@app.callback(
    Output('graph-gauge', 'value', allow_duplicate=True),
    [Input('interval-component', 'n_intervals'),
     Input('dropdown-selection', 'value')],
    prevent_initial_call=True
)
def updateGauge(n, value):
    df_pos = get_positions_df()
    # Фильтрация строк по базовому активу
    df_pos = df_pos[df_pos['option_base'] == value]

    # TrueVega
    tv_sum_positive = df_pos.loc[df_pos['net_pos'] > 0, 'TrueVega'].sum()
    tv_sum_negative = df_pos.loc[df_pos['net_pos'] < 0, 'TrueVega'].sum()
    tv_sum = abs(tv_sum_positive) + abs(tv_sum_negative)
    if tv_sum == 0:
        value = 0
    else:
        value = (abs(tv_sum_positive) / (abs(tv_sum_positive) + abs(tv_sum_negative))) * 10
    return value


if __name__ == '__main__':
    # Запуск Финам-стрима (позиции, заявки, сделки) в фоновом потоке
    stream_thread = threading.Thread(target=stream_main, name="FinamStreamThread", daemon=True)
    stream_thread.start()

    try:
        app.run(debug=False)  # Запускаем Dash приложение
    except KeyboardInterrupt:  # При остановке программы
        pass  # ничего не делаем, выходим
    finally:
        shutdown_bars_subscription()  # Отписка и корректное закрытие брокера