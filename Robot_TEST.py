"""
Парный торговый робот для опционов на Московской бирже через FinamPy.

Назначение:
    Реализует классическую стратегию pairs trading, но не на ценах активов,
    а на их подразумеваемой волатильности (implied volatility, IV).
    Когда спред IV между двумя опционами значительно отклоняется от среднего,
    робот одновременно продаёт «дорогой» по IV опцион и покупает «дешёвый»,
    ожидая возврата спреда к равновесию.

Методы работы:
    1. Получение исторических внутридневных данных (M5) по опционам и базовым фьючерсам.
    2. Восстановление IV из рыночных цен опционов (методом бисекции).
    3. Построение спреда IV со скользящим hedge-ratio.
    4. Расчёт z-score спреда для определения переоценённости/недооценённости.
    5. Real-time подписка на котировки всех инструментов.
    6. При срабатывании порогов входа (|z| > Z_ENTRY) — открытие позиции:
       продажа одного опциона, покупка другого, с подбором вега-нейтрального
       количества лотов.
    7. При возврате z-score к нулю (|z| < Z_EXIT) — закрытие позиции.

Автор: (ваше имя)
Дата: (дата)
"""
import logging
from datetime import datetime, timedelta
from time import sleep
from threading import Thread
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import numpy as np
from scipy.stats import norm

from FinamPy import FinamPy
from FinamPy.grpc import marketdata_service_pb2 as marketdata_service
from FinamPy.grpc import orders_service_pb2 as orders_service
from FinamPy.grpc import side_pb2 as side
from FinamPy.grpc.orders_service_pb2 import Order, OrderState, OrderType

# ======================= НАСТРОЙКИ =======================
logger = logging.getLogger('PairsTrader')
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%d.%m.%Y %H:%M:%S',
    level=logging.INFO,
    handlers=[logging.FileHandler('PairsTrader.log', encoding='utf-8'), logging.StreamHandler()]
)

# --- Подключение (токен из keyring или укажите явно) ---
fp_provider = FinamPy()  # или FinamPy('<ВАШ_ТОКЕН>')

# --- Опцион A ---
OPTION_A_DATANAME = 'SPBOPT.RI80000BS6D'   # Тикер опциона A
UNDERLYING_A_DATANAME = 'SPBFUT.RIH6'      # Базовый фьючерс для опциона A
STRIKE_A = 300000                          # Страйк опциона A
EXPIRY_A = datetime(2025, 6, 20)           # Дата экспирации

# --- Опцион B ---
OPTION_B_DATANAME = 'SPBOPT.RI80000BS6E'   # Тикер опциона B
UNDERLYING_B_DATANAME = 'SPBFUT.RIH6'      # Базовый фьючерс для опциона B
STRIKE_B = 320000                          # Страйк опциона B
EXPIRY_B = datetime(2025, 6, 20)

# --- Параметры стратегии ---
TIMEFRAME = 'M5'                 # Таймфрейм для построения истории
HISTORY_COUNT = 500              # Сколько M5-баров хранить (≈ 3-4 торговых дня)
Z_ENTRY = 2.0                    # Порог входа в позицию (|z| > Z_ENTRY)
Z_EXIT = 0.5                     # Порог выхода из позиции (|z| < Z_EXIT)
Z_WINDOW = 30                    # Окно для скользящего среднего/ско (в барах)
QTY_A = 1                        # Базовое количество лотов опциона A
RISK_FREE_RATE = 0.0             # Безрисковая ставка (упрощение)

# --- Глобальное состояние ---
position = None                  # Текущая открытая позиция: {'buy_symbol': ..., 'sell_symbol': ..., 'qty_buy': ..., 'qty_sell': ...}
last_prices = {}                 # Кэш последних цен по символам: {symbol: last_price}
iv_history = {}                  # История IV и веги по символам: {symbol: DataFrame(date, iv, vega)}
# =========================================================


# ---------- Вспомогательные функции ----------

def get_symbol_data(dataname: str) -> tuple:
    """
    Преобразует тикер в формате «SPBOPT.TICKER» или «SPBFUT.TICKER»
    в кортеж (symbol, finam_board, mic), используемый в запросах к API.

    :param dataname: Тикер в формате Finam, например 'SPBOPT.RI80000BS6D'
    :return: (symbol, finam_board, mic), где symbol — полный код для gRPC,
             finam_board — режим торгов ('OPT' или 'FUT'),
             mic — биржа ('MISX' или 'RTSX')
    """
    finam_board, ticker = fp_provider.dataname_to_finam_board_ticker(dataname)
    mic = fp_provider.get_mic(finam_board, ticker)
    return f'{ticker}@{mic}', finam_board, mic


def get_candles(symbol: str, count: int = HISTORY_COUNT) -> pd.DataFrame:
    """
    Загружает исторические свечи заданного таймфрейма (по умолчанию M5).

    :param symbol: Полный код инструмента (например, 'RI80000BS6D@RTSX')
    :param count: Количество запрашиваемых баров
    :return: DataFrame с колонками ['date', 'close'] (время МСК, цена закрытия)
    """
    # Переводим наш таймфрейм 'M5' в формат Finam и получаем макс. глубину истории
    finam_tf, _, _ = fp_provider.timeframe_to_finam_timeframe(TIMEFRAME)
    request = marketdata_service.GetCandlesRequest(
        symbol=symbol,
        timeframe=finam_tf,
        count=count
    )
    response = fp_provider.call_function(fp_provider.marketdata_stub.GetCandles, request)
    if response is None:
        logger.error(f'Не удалось получить свечи для {symbol}')
        return pd.DataFrame()

    # Преобразуем protobuf-ответ в pandas DataFrame
    rows = []
    for candle in response.candles:
        dt = fp_provider.timestamp_to_msk_datetime(candle.ts)
        rows.append({
            'date': dt,
            'close': float(candle.close.value),
        })
    return pd.DataFrame(rows).dropna()


def place_order(symbol: str, side_value: int, quantity: int):
    """
    Размещает рыночную заявку на покупку/продажу.

    :param symbol: Полный код инструмента
    :param side_value: Сторона сделки (side.SIDE_BUY или side.SIDE_SELL)
    :param quantity: Количество лотов
    :return: OrderState или None при ошибке
    """
    order = Order(
        account_id=fp_provider.account_ids[0],  # Используем первый счёт из токена
        symbol=symbol,
        quantity=quantity,
        side=side_value,
        type=OrderType.ORDER_TYPE_MARKET,
        client_order_id=str(int(datetime.now().timestamp()))  # Уникальный ID для отслеживания
    )
    order_state: OrderState = fp_provider.call_function(fp_provider.orders_stub.PlaceOrder, order)
    if order_state is None:
        logger.error(f'Ошибка размещения заявки: {symbol}')
        return None
    logger.info(f'Заявка {order_state.order_id}: {side_value} {quantity} {symbol} -> {order_state.status}')
    return order_state


def place_pair_orders(buy_symbol: str, sell_symbol: str, qty_buy: int, qty_sell: int):
    """
    Отправляет две рыночные заявки (покупку и продажу) практически одновременно,
    используя два параллельных потока.

    :param buy_symbol: Символ инструмента для покупки
    :param sell_symbol: Символ инструмента для продажи
    :param qty_buy: Количество лотов для покупки
    :param qty_sell: Количество лотов для продажи
    """
    with ThreadPoolExecutor(max_workers=2) as executor:
        buy_future = executor.submit(place_order, buy_symbol, side.SIDE_BUY, qty_buy)
        sell_future = executor.submit(place_order, sell_symbol, side.SIDE_SELL, qty_sell)
        buy_future.result()
        sell_future.result()


# ---------- Опционные расчёты ----------

def black_scholes_price(S: float, K: float, T: float, r: float, sigma: float, option_type: str = 'C') -> float:
    """
    Цена европейского опциона по модели Блэка-Шоулза.

    :param S: Цена базового актива
    :param K: Страйк
    :param T: Время до экспирации в годах
    :param r: Безрисковая ставка
    :param sigma: Волатильность (IV)
    :param option_type: 'C' — колл, 'P' — пут
    :return: Теоретическая цена опциона
    """
    if T <= 0 or sigma <= 0:
        return np.nan
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    if option_type == 'C':
        return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    else:
        return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def black_scholes_vega(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """
    Вега опциона — чувствительность цены к изменению волатильности.

    :param S: Цена базового актива
    :param K: Страйк
    :param T: Время до экспирации в годах
    :param r: Безрисковая ставка
    :param sigma: Волатильность (IV)
    :return: Вега (производная цены по sigma)
    """
    if T <= 0 or sigma <= 0:
        return np.nan
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    return S * np.sqrt(T) * norm.pdf(d1)


def implied_volatility(market_price: float, S: float, K: float, T: float, r: float, option_type: str = 'C') -> float:
    """
    Восстанавливает подразумеваемую волатильность (IV) из рыночной цены опциона
    методом бисекции. Это устойчивый, но не самый быстрый метод.

    :param market_price: Рыночная цена опциона
    :param S: Цена базового актива
    :param K: Страйк
    :param T: Время до экспирации в годах
    :param r: Безрисковая ставка
    :param option_type: 'C' — колл, 'P' — пут
    :return: IV (дробное число, например 0.25 = 25%)
    """
    if market_price <= 0 or S <= 0 or K <= 0 or T <= 0:
        return np.nan
    lo, hi = 1e-4, 5.0  # Начальные границы для поиска (0.01% ... 500%)
    for _ in range(64):  # 64 итераций достаточно для сходимости
        mid = 0.5 * (lo + hi)
        bs = black_scholes_price(S, K, T, r, mid, option_type)
        if bs > market_price:
            hi = mid  # Теоретическая цена выше рыночной — волатильность завышена
        else:
            lo = mid  # Теоретическая цена ниже — волатильность занижена
    return 0.5 * (lo + hi)


def get_iv_vega_from_price(opt_price: float, und_price: float, strike: float, expiry: datetime, option_type: str = 'C') -> tuple:
    """
    Рассчитывает текущие IV и вегу опциона по последним ценам.

    :param opt_price: Текущая цена опциона
    :param und_price: Текущая цена базового актива
    :param strike: Страйк опциона
    :param expiry: Дата экспирации
    :param option_type: Тип опциона ('C' или 'P')
    :return: Кортеж (IV, vega)
    """
    T = (expiry - datetime.now()).days / 365.0  # Время до экспирации в годах
    if T <= 0:
        return np.nan, np.nan
    iv = implied_volatility(opt_price, und_price, strike, T, RISK_FREE_RATE, option_type)
    vega = black_scholes_vega(und_price, strike, T, RISK_FREE_RATE, iv)
    return iv, vega


def init_history(option_dataname: str, underlying_dataname: str, strike: float, expiry: datetime, option_type: str = 'C') -> pd.DataFrame:
    """
    Загружает историю IV и веги для опциона на основе исторических свечей M5.

    :param option_dataname: Тикер опциона (например, 'SPBOPT.RI80000BS6D')
    :param underlying_dataname: Тикер базового фьючерса (например, 'SPBFUT.RIH6')
    :param strike: Страйк опциона
    :param expiry: Дата экспирации
    :param option_type: Тип опциона ('C' или 'P')
    :return: DataFrame с колонками ['date', 'iv', 'vega']
    """
    opt_symbol, _, _ = get_symbol_data(option_dataname)
    und_symbol, _, _ = get_symbol_data(underlying_dataname)

    opt_df = get_candles(opt_symbol, HISTORY_COUNT)
    und_df = get_candles(und_symbol, HISTORY_COUNT)
    if opt_df.empty or und_df.empty:
        return pd.DataFrame()

    # Объединяем свечи по времени (внутридневные бары должны совпадать)
    df = opt_df.merge(und_df, on='date', suffixes=('_opt', '_und')).dropna()
    df['T'] = (expiry - df['date']).dt.days / 365.0  # Время до экспирации для каждого бара
    df = df[df['T'] > 0].copy()

    rows = []
    for _, row in df.iterrows():
        # Для каждого исторического бара восстанавливаем IV из цены опциона и базового актива
        iv = implied_volatility(row['close_opt'], row['close_und'], strike,
                                row['T'], RISK_FREE_RATE, option_type)
        if np.isnan(iv):
            continue
        vega = black_scholes_vega(row['close_und'], strike, row['T'], RISK_FREE_RATE, iv)
        rows.append({'date': row['date'], 'iv': iv, 'vega': vega})

    hist = pd.DataFrame(rows)
    iv_history[opt_symbol] = hist  # Сохраняем в глобальный словарь
    return hist


def update_m5_history(symbol: str, iv: float, vega: float, now: datetime):
    """
    Обновляет историю IV/веги для символа в реальном времени.

    Если текущий 5-минутный бар уже существует в истории — обновляет его значения,
    иначе добавляет новый бар. История ограничена HISTORY_COUNT последними записями.

    :param symbol: Полный код инструмента
    :param iv: Текущее значение IV
    :param vega: Текущее значение веги
    :param now: Текущее время (для определения начала бара)
    """
    # Определяем начало текущего 5-минутного бара (округляем вниз до 5 минут)
    bar_start = now.replace(minute=(now.minute // 5) * 5, second=0, microsecond=0)

    hist = iv_history.get(symbol, pd.DataFrame())
    if not hist.empty:
        last_date = hist['date'].iloc[-1]
        if last_date == bar_start:
            # Обновляем последний бар (котировки приходят чаще, чем раз в 5 минут)
            hist.loc[hist.index[-1], 'iv'] = iv
            hist.loc[hist.index[-1], 'vega'] = vega
        else:
            # Начался новый бар — добавляем строку
            new_row = pd.DataFrame({'date': [bar_start], 'iv': [iv], 'vega': [vega]})
            hist = pd.concat([hist, new_row], ignore_index=True)
    else:
        hist = pd.DataFrame({'date': [bar_start], 'iv': [iv], 'vega': [vega]})

    # Оставляем только последние HISTORY_COUNT баров для эффективности расчётов
    iv_history[symbol] = hist.tail(HISTORY_COUNT).reset_index(drop=True)


def build_spread_zscore(hist_a: pd.DataFrame, hist_b: pd.DataFrame, window: int) -> pd.DataFrame:
    """
    Строит спред IV между двумя опционами и рассчитывает его z-score.

    Используется скользящий hedge-ratio (отношение ковариации к дисперсии),
    чтобы учесть разную чувствительность опционов к изменениям рынка.

    :param hist_a: DataFrame истории IV для опциона A (колонки date, iv)
    :param hist_b: DataFrame истории IV для опциона B (колонки date, iv)
    :param window: Окно для расчёта скользящих статистик
    :return: DataFrame с колонками date, spread, zscore (и вспомогательными)
    """
    df = hist_a[['date', 'iv']].merge(hist_b[['date', 'iv']], on='date', suffixes=('_a', '_b'))
    df = df.dropna()

    if len(df) < window:
        return pd.DataFrame()  # Недостаточно данных для расчёта

    # Скользящий hedge-ratio: beta = Cov(A,B) / Var(B)
    df['hedge'] = (df['iv_a'].rolling(window).cov(df['iv_b']) /
                   df['iv_b'].rolling(window).var())

    # Спред = IV_A - beta * IV_B
    df['spread'] = df['iv_a'] - df['hedge'] * df['iv_b']

    # Скользящие среднее и стандартное отклонение спреда
    df['spread_mean'] = df['spread'].rolling(window).mean()
    df['spread_std'] = df['spread'].rolling(window).std()

    # Z-score = (текущий спред - среднее) / стандартное отклонение
    df['zscore'] = (df['spread'] - df['spread_mean']) / df['spread_std']

    return df.dropna()


def calc_vega_neutral_qty(qty_a: int, vega_a: float, vega_b: float) -> int:
    """
    Подбирает количество лотов опциона B для достижения вега-нейтральности позиции.

    Условие нейтральности: qty_a * vega_a - qty_b * vega_b ≈ 0
    Отсюда qty_b = qty_a * vega_a / vega_b.

    :param qty_a: Количество лотов опциона A (базовое)
    :param vega_a: Вега опциона A
    :param vega_b: Вега опциона B
    :return: Целое количество лотов опциона B (минимум 1)
    """
    if abs(vega_b) < 1e-8:  # Защита от деления на ноль
        return qty_a
    optimal = abs(qty_a * vega_a / vega_b)
    return max(1, int(round(optimal)))


# ---------- Торговые действия ----------

def open_pair(buy_dataname: str, sell_dataname: str, qty_buy: int, qty_sell: int):
    """
    Открывает парную позицию: покупает один опцион, продаёт другой.

    :param buy_dataname: Тикер опциона для покупки (например, 'SPBOPT.XXX')
    :param sell_dataname: Тикер опциона для продажи
    :param qty_buy: Количество лотов для покупки
    :param qty_sell: Количество лотов для продажи
    """
    global position
    buy_symbol, _, _ = get_symbol_data(buy_dataname)
    sell_symbol, _, _ = get_symbol_data(sell_dataname)
    logger.info(f'ВХОД: BUY {qty_buy} {buy_dataname}, SELL {qty_sell} {sell_dataname}')
    place_pair_orders(buy_symbol, sell_symbol, qty_buy, qty_sell)
    # Запоминаем позицию для последующего закрытия
    position = {
        'buy_symbol': buy_symbol,
        'sell_symbol': sell_symbol,
        'qty_buy': qty_buy,
        'qty_sell': qty_sell
    }


def close_pair():
    """Закрывает текущую парную позицию: продаёт купленное, выкупает проданное."""
    global position
    if position is None:
        return
    logger.info('ВЫХОД: закрываем позиции')
    # Отправляем встречные заявки
    place_pair_orders(
        position['buy_symbol'],
        position['sell_symbol'],
        position['qty_buy'],
        position['qty_sell']
    )
    position = None


# ---------- Обработка котировок (real-time) ----------

def on_quote(event):
    """
    Callback-функция, вызываемая при каждой новой котировке любого инструмента.

    Обновляет кэш последних цен. Когда получены цены для всех четырёх инструментов
    (два опциона и два базовых фьючерса), запускает проверку торговых сигналов.

    :param event: Событие подписки (содержит поле quote)
    """
    try:
        quote = event.quote
        symbol = quote.symbol
        price = float(quote.last.value)
        last_prices[symbol] = price  # Обновляем кэш цен

        # Проверяем, собраны ли цены всех необходимых инструментов
        required = {
            'opt_a': get_symbol_data(OPTION_A_DATANAME)[0],
            'opt_b': get_symbol_data(OPTION_B_DATANAME)[0],
            'und_a': get_symbol_data(UNDERLYING_A_DATANAME)[0],
            'und_b': get_symbol_data(UNDERLYING_B_DATANAME)[0],
        }
        if all(sym in last_prices for sym in required.values()):
            check_and_trade(required['opt_a'], required['opt_b'])
    except Exception as e:
        # Ловим исключения, чтобы поток подписки не прекращал работу
        logger.exception(f'Ошибка в on_quote: {e}')


def check_and_trade(opt_a_sym: str, opt_b_sym: str):
    """
    Основная торговая логика: пересчёт IV, z-score и принятие решений о входе/выходе.

    Вызывается из on_quote каждый раз, когда обновляются цены всех компонентов.

    :param opt_a_sym: Полный символ опциона A
    :param opt_b_sym: Полный символ опциона B
    """
    try:
        global position

        # Получаем символы базовых активов
        und_a_sym, _, _ = get_symbol_data(UNDERLYING_A_DATANAME)
        und_b_sym, _, _ = get_symbol_data(UNDERLYING_B_DATANAME)

        # Берём последние цены из кэша
        opt_a_price = last_prices.get(opt_a_sym)
        opt_b_price = last_prices.get(opt_b_sym)
        und_a_price = last_prices.get(und_a_sym)
        und_b_price = last_prices.get(und_b_sym)

        if None in (opt_a_price, opt_b_price, und_a_price, und_b_price):
            return  # Не все цены получены

        # Расчёт текущих IV и вег
        iv_a, vega_a = get_iv_vega_from_price(opt_a_price, und_a_price, STRIKE_A, EXPIRY_A)
        iv_b, vega_b = get_iv_vega_from_price(opt_b_price, und_b_price, STRIKE_B, EXPIRY_B)

        if np.isnan(iv_a) or np.isnan(iv_b):
            return  # Ошибка в расчёте IV

        # Обновляем историю M5 для обоих опционов (текущий бар)
        now = datetime.now()
        update_m5_history(opt_a_sym, iv_a, vega_a, now)
        update_m5_history(opt_b_sym, iv_b, vega_b, now)

        # Строим спред и z-score
        hist_a = iv_history[opt_a_sym]
        hist_b = iv_history[opt_b_sym]
        data = build_spread_zscore(hist_a, hist_b, Z_WINDOW)
        if data.empty:
            return  # Недостаточно данных для z-score

        latest = data.iloc[-1]
        z = latest['zscore']
        logger.info(f'Real-time z-score: {z:.2f} (IV_A={iv_a:.4f}, IV_B={iv_b:.4f})')

        # --- Выход из позиции, если она открыта ---
        if position is not None:
            if abs(z) < Z_EXIT:
                close_pair()  # Спред вернулся к норме — закрываемся
            return  # Позиция уже есть, новые входы не рассматриваем

        # --- Вход в позицию по сигналу ---
        if z > Z_ENTRY:
            # Спред слишком высокий: IV_A переоценён, IV_B недооценён
            # Продаём A, покупаем B
            qty_b = calc_vega_neutral_qty(QTY_A, vega_a, vega_b)
            open_pair(OPTION_B_DATANAME, OPTION_A_DATANAME, qty_b, QTY_A)
        elif z < -Z_ENTRY:
            # Спред слишком низкий: IV_B переоценён, IV_A недооценён
            # Покупаем A, продаём B
            qty_b = calc_vega_neutral_qty(QTY_A, vega_a, vega_b)
            open_pair(OPTION_A_DATANAME, OPTION_B_DATANAME, QTY_A, qty_b)

    except Exception as e:
        # Аналогично, не даём потоку умереть из-за ошибки
        logger.exception(f'Ошибка в check_and_trade: {e}')


# ---------- Запуск подписок ----------

def start_quote_subscriptions():
    """
    Запускает поток подписки на котировки всех необходимых инструментов:
    двух опционов и двух базовых фьючерсов.

    Подписка выполняется в отдельном daemon-потоке, чтобы не блокировать
    основной цикл программы.
    """
    opt_a_sym, _, _ = get_symbol_data(OPTION_A_DATANAME)
    opt_b_sym, _, _ = get_symbol_data(OPTION_B_DATANAME)
    und_a_sym, _, _ = get_symbol_data(UNDERLYING_A_DATANAME)
    und_b_sym, _, _ = get_symbol_data(UNDERLYING_B_DATANAME)

    symbols = [opt_a_sym, opt_b_sym, und_a_sym, und_b_sym]

    # Регистрируем обработчик события on_quote
    fp_provider.on_quote.subscribe(on_quote)

    # Запускаем поток подписки (subscribe_quote_thread — метод из FinamPy)
    Thread(target=fp_provider.subscribe_quote_thread, args=(symbols,), daemon=True).start()


# ======================= MAIN =======================
def main():
    """
    Главная функция: инициализирует историю, запускает подписки и
    поддерживает работу робота до остановки пользователем.
    """
    # 1. Загружаем историю IV/веги для обоих опционов на M5
    init_history(OPTION_A_DATANAME, UNDERLYING_A_DATANAME, STRIKE_A, EXPIRY_A)
    init_history(OPTION_B_DATANAME, UNDERLYING_B_DATANAME, STRIKE_B, EXPIRY_B)

    # 2. Запускаем real-time подписку на котировки
    start_quote_subscriptions()

    # 3. Основной цикл ожидания (подписка работает в фоне)
    logger.info('Робот запущен, ожидаем котировки...')
    try:
        while True:
            sleep(1)  # Просто держим процесс живым
    except KeyboardInterrupt:
        logger.info('Остановка робота')
        fp_provider.close_channel()  # Закрываем gRPC-канал


if __name__ == '__main__':
    main()
