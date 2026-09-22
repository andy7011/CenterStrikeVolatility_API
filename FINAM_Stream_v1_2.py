import logging  # Модуль для ведения логов
from threading import Thread, Event  # Модуль для создания потоков и событий
from datetime import datetime  # Модуль для работы с датой и временем
from time import sleep  # Функция для приостановки выполнения программы
import traceback  # Модуль для получения полной информации об ошибке

from FinamPy import FinamPy  # Основной класс библиотеки FinamPy
from FinamPy.grpc import orders_service_pb2 as orders_service
from FinamPy.grpc import assets_service_pb2 as assets_service
from FinLabPy.Schedule.MOEX import Futures  # Расписание торгов
from app.supported_base_asset import MAP  # Список базовых активов

# Логгер на уровне модуля
logger = logging.getLogger('FinamPy.Stream')

# ---------------------------------------------------------------------------
# Глобальные переменные состояния
# ---------------------------------------------------------------------------
fp_provider = None  # Глобальный экземпляр FinamPy
account_id = None   # Текущий идентификатор аккаунта

# Множество символов базовых фьючерсов, например {'RIZ6@RTSX', 'SiZ6@RTSX', ...}
# Заполняется в subscribe_base_assets и используется для фильтрации опционов.
base_symbols = set()

# Все опционные символы, которые уже были обработаны (чтобы не подписываться повторно)
_known_symbols = set()

# Последние наборы символов из позиций и заявок (для быстрой проверки изменений)
_last_positions_symbols = set()
_last_orders_symbols = set()

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
                logger.info(f"Активная заявка #{order_id}: {active_orders[order_id]}")
            else:
                # Терминальный статус — удаляем заявку
                if order_id in active_orders:
                    removed = active_orders.pop(order_id)
                    logger.info(f"Заявка #{order_id} удалена (статус: {status}). Была: {removed}")

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


# ---------------------------------------------------------------------------
# Обработчик котировок (базовые активы + опционы)
# ---------------------------------------------------------------------------
def _on_quote(quote):
    """
    Обработчик котировок базовых активов и опционов.

    - При первом появлении символа создаётся запись, содержащая ВСЕ поля
      из структуры ответа сервера. Поля, отсутствующие в текущем сообщении,
      получают значение None.
    - При последующих получениях обновляются только те поля, которые реально
      пришли в сообщении. Остальные поля сохраняют предыдущие значения.
    """
    if not quote.quote:
        logger.warning("Получена пустая котировка")
        return

    # Все поля верхнего уровня (кроме symbol и timestamp)
    top_level_fields = [
        'ask', 'ask_size', 'bid', 'bid_size', 'last', 'last_size',
        'volume', 'turnover', 'open', 'high', 'low', 'close', 'change',
        'open_interest'
    ]

    # Все поля объекта option
    option_fields = [
        'open_interest', 'implied_volatility', 'theoretical_price',
        'delta', 'gamma', 'theta', 'vega', 'rho'
    ]

    for q in quote.quote:
        full_symbol = q.symbol  # например, 'RI85000BW6@RTSX'

        # --- Обработка опционов ---
        if full_symbol in subscribed_option_symbols:
            if full_symbol not in option_quotes:
                # Первое появление символа: строим полную структуру
                option_quotes[full_symbol] = {}

                # Поля верхнего уровня
                for field in top_level_fields:
                    if q.HasField(field) and getattr(q, field).value:
                        try:
                            option_quotes[full_symbol][field] = float(getattr(q, field).value)
                        except (ValueError, TypeError):
                            option_quotes[full_symbol][field] = None
                    else:
                        option_quotes[full_symbol][field] = None

                # Поля option
                if q.HasField('option'):
                    opt = q.option
                    for field in option_fields:
                        if opt.HasField(field) and getattr(opt, field).value:
                            try:
                                option_quotes[full_symbol][field] = float(getattr(opt, field).value)
                            except (ValueError, TypeError):
                                option_quotes[full_symbol][field] = None
                        else:
                            option_quotes[full_symbol][field] = None
                else:
                    for field in option_fields:
                        option_quotes[full_symbol][field] = None

                option_quotes[full_symbol]['symbol'] = full_symbol
                option_quotes[full_symbol]['time'] = datetime.now().strftime('%H:%M:%S')

            else:
                # Символ уже есть — обновляем только пришедшие поля
                for field in top_level_fields:
                    if q.HasField(field) and getattr(q, field).value:
                        try:
                            option_quotes[full_symbol][field] = float(getattr(q, field).value)
                        except (ValueError, TypeError):
                            option_quotes[full_symbol][field] = None

                if q.HasField('option'):
                    opt = q.option
                    for field in option_fields:
                        if opt.HasField(field) and getattr(opt, field).value:
                            try:
                                option_quotes[full_symbol][field] = float(getattr(opt, field).value)
                            except (ValueError, TypeError):
                                option_quotes[full_symbol][field] = None

                option_quotes[full_symbol]['time'] = datetime.now().strftime('%H:%M:%S')

        # --- Обработка базовых активов ---
        else:
            ticker = full_symbol.split('@')[0]
            if ticker not in MAP:
                continue

            # Для базовых активов храним основные поля
            if ticker not in base_asset_quotes:
                base_asset_quotes[ticker] = {
                    'ask': None, 'bid': None, 'last': None, 'time': None
                }

            if q.HasField('ask') and q.ask.value:
                base_asset_quotes[ticker]['ask'] = float(q.ask.value)
            if q.HasField('bid') and q.bid.value:
                base_asset_quotes[ticker]['bid'] = float(q.bid.value)
            if q.HasField('last') and q.last.value:
                base_asset_quotes[ticker]['last'] = float(q.last.value)

            base_asset_quotes[ticker]['time'] = datetime.now().strftime('%H:%M:%S')


# ---------------------------------------------------------------------------
# Подписка на котировки базовых активов
# ---------------------------------------------------------------------------
def subscribe_base_assets(fp_provider):
    """Подписка на котировки всех базовых активов из MAP."""
    global base_symbols

    # Очищаем множество базовых символов перед заполнением (актуально при переподключении)
    base_symbols.clear()
    symbols_for_subscription = []

    for ticker in MAP.keys():
        dataname = f'SPBFUT.{ticker}'
        try:
            finam_board, ticker_code = fp_provider.dataname_to_finam_board_ticker(dataname)
            mic = fp_provider.get_mic(finam_board, ticker_code)
            symbol = f'{ticker_code}@{mic}'
            symbols_for_subscription.append(symbol)
            base_symbols.add(symbol)
        except Exception as e:
            logger.error(f"Не удалось определить биржу для {ticker}: {e}")

    if not symbols_for_subscription:
        logger.warning("Нет доступных базовых активов для подписки")
        return

    fp_provider.on_quote.subscribe(_on_quote)
    thread = Thread(
        target=fp_provider.subscribe_quote_thread,
        name='BaseAssetsQuoteThread',
        args=(tuple(symbols_for_subscription),),
        daemon=True
    )
    thread.start()
    logger.info(f"Подписка на базовые активы запущена: {list(MAP.keys())}")
    return thread


# ---------------------------------------------------------------------------
# Подписка на котировки опционов
# ---------------------------------------------------------------------------
def subscribe_option_quotes(symbols):
    """
    Подписка на котировки опционов по списку символов.
    Подписывается только на те символы, которые ещё не были подписаны.
    """
    new_symbols = set(symbols) - subscribed_option_symbols
    if not new_symbols:
        return

    subscribed_option_symbols.update(new_symbols)

    # Запускаем поток подписки на новые символы
    Thread(
        target=fp_provider.subscribe_quote_thread,
        name='OptionQuotesThread',
        args=(tuple(new_symbols),),
        daemon=True
    ).start()

    logger.info(f"Подписка на котировки опционов запущена: {new_symbols}")


# ---------------------------------------------------------------------------
# Проверка появления новых опционов в портфеле/заявках
# ---------------------------------------------------------------------------
def update_option_subscriptions_from_portfolio():
    """
    Проверяет, появились ли новые опционные символы в портфеле/заявках.
    Выполняет подписку только при обнаружении новых инструментов.
    """
    global _known_symbols, _last_positions_symbols, _last_orders_symbols

    # Текущие символы из позиций
    positions = _account_data[0].get('positions', {})
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

    # Формируем множество всех текущих символов
    all_symbols = current_positions | current_orders

    # Исключаем базовые фьючерсы (они уже подписаны)
    option_symbols = {s for s in all_symbols if s not in base_symbols}

    # Новые опционы — те, которых ещё нет в _known_symbols
    new_symbols = option_symbols - _known_symbols
    if not new_symbols:
        return

    # Запоминаем все текущие опционы, чтобы не переподписываться на старые
    _known_symbols.update(option_symbols)

    # Подписываемся только на новые
    subscribe_option_quotes(new_symbols)


# ---------------------------------------------------------------------------
# Загрузка цепочек опционов
# ---------------------------------------------------------------------------
def load_options_chains(fp_provider):
    """
    Однократно загружает цепочки опционов для всех базовых активов из MAP.
    Результат сохраняется в глобальный словарь options_chains.
    Ключ — символ опциона (например, 'RI85000BW6@RTSX').
    """
    global _options_chains_loaded
    if _options_chains_loaded:
        return options_chains
    _options_chains_loaded = True

    for ticker in MAP.keys():
        try:
            # Определяем символ базового актива для API (тикер@биржа)
            dataname = f'SPBFUT.{ticker}'
            finam_board, ticker_code = fp_provider.dataname_to_finam_board_ticker(dataname)
            mic = fp_provider.get_mic(finam_board, ticker_code)
            underlying_symbol = f'{ticker_code}@{mic}'

            # Запрашиваем цепочку опционов
            request = assets_service.OptionsChainRequest(underlying_symbol=underlying_symbol)
            response = fp_provider.call_function(fp_provider.assets_stub.OptionsChain, request)

            if response is None:
                logger.error(f"Не удалось получить цепочку опционов для {underlying_symbol}")
                continue

            for opt in response.options:
                # Тип опциона: CALL / PUT
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
                    'strike': to_float(opt.strike),
                    'multiplier': to_float(opt.multiplier),
                    'expiration_first_day': fmt_date(opt.expiration_first_day),
                    'expiration_last_day': fmt_date(opt.expiration_last_day),
                }

            logger.info(f"Цепочка опционов для {underlying_symbol}: {len(response.options)} опционов")

        except Exception as e:
            logger.error(f"Ошибка при получении цепочки опционов для {ticker}: {e}")

    logger.info(f"Всего опционов загружено: {len(options_chains)}")
    return options_chains


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


# ---------------------------------------------------------------------------
# Цикл контроля подписок и переподключения
# ---------------------------------------------------------------------------
def run_subscription_loop(stop_event):
    """
    Запускает подписку и контролирует её работу в течение текущей сессии.
    Возвращает True, если подписка завершилась из-за ошибки (нужно перезапускать),
    и False, если сессия закончилась и надо просто ждать следующей.
    """
    global fp_provider, account_id

    stream_thread = start_account_stream(fp_provider, account_id)
    retry_delay = 5
    max_delay = 60

    while not stop_event.is_set():
        now = get_market_now()
        if not schedule.trade_session(now):
            logger.info("Торговая сессия закончилась.")
            return False

        if not stream_thread.is_alive():
            logger.warning("Поток подписки завершился. Пытаемся переподключиться...")
            try:
                fp_provider.close_channel()
            except Exception:
                pass

            sleep(retry_delay)
            retry_delay = min(retry_delay * 2, max_delay)

            try:
                # Пересоздаём соединение и все подписки
                fp_provider = FinamPy()
                if not fp_provider.account_ids:
                    fp_provider.account_ids = list(fp_provider.token_details().account_ids)
                account_id = fp_provider.account_ids[0]

                # Сбрасываем состояние подписок на опционы
                subscribed_option_symbols.clear()
                option_quotes.clear()
                _known_symbols.clear()
                _last_positions_symbols.clear()
                _last_orders_symbols.clear()
                _options_chains_loaded = False

                stream_thread = start_account_stream(fp_provider, account_id)
                subscribe_base_assets(fp_provider)
                load_options_chains(fp_provider)
                update_option_subscriptions_from_portfolio()
                subscribe_orders(fp_provider, account_id)

                logger.info("Переподключение выполнено успешно")
                retry_delay = 5
            except Exception as e:
                logger.error(f"Ошибка при переподключении: {e}\n{traceback.format_exc()}")
                continue

        stop_event.wait(1)

    return False


# ---------------------------------------------------------------------------
# Отладочный вывод котировок опционов (периодический)
# ---------------------------------------------------------------------------
def print_option_quotes_periodically(stop_event):
    """Раз в 5 секунд выводит содержимое option_quotes."""
    while not stop_event.is_set():
        stop_event.wait(5)  # ждём 5 секунд или сигнал остановки
        if option_quotes:
            print(f"\n=== option_quotes ({len(option_quotes)} символов) ===")
            for symbol, quote in option_quotes.items():
                print(f"{symbol}: {quote}")


# ---------------------------------------------------------------------------
# Основная функция
# ---------------------------------------------------------------------------
def main():
    """Основная функция: работает по расписанию биржи, восстанавливается при сбоях"""
    logger.info("Запуск программы мониторинга аккаунта по расписанию биржи")
    global fp_provider, account_id
    stop_event = Event()

    # Периодический вывод котировок опционов (для отладки)
    Thread(target=print_option_quotes_periodically, args=(stop_event,), daemon=True).start()

    try:
        while not stop_event.is_set():
            # Ждём начала торговой сессии
            try:
                wait_for_trading_session(stop_event)
            except KeyboardInterrupt:
                logger.info("Получен сигнал остановки. Завершаем работу...")
                stop_event.set()
                break
            if stop_event.is_set():
                break

            try:
                # Закрываем предыдущий канал, если он был открыт
                if fp_provider is not None:
                    try:
                        fp_provider.close_channel()
                    except Exception:
                        pass

                # Инициализация подключения
                fp_provider = FinamPy()
                if not fp_provider.account_ids:
                    fp_provider.account_ids = list(fp_provider.token_details().account_ids)

                if not fp_provider.account_ids:
                    logger.error("Не найдено ни одного торгового счёта")
                    stop_event.wait(60)
                    continue

                account_id = fp_provider.account_ids[0]
                logger.info(f"Начинаем работу с аккаунтом {account_id}")

                # Запускаем подписку на аккаунт, базовые активы, заявки
                subscribe_base_assets(fp_provider)
                load_options_chains(fp_provider)
                update_option_subscriptions_from_portfolio()
                subscribe_orders(fp_provider, account_id)

                # Входим в цикл контроля сессии
                run_subscription_loop(stop_event)

            except KeyboardInterrupt:
                logger.info("Получен сигнал остановки. Завершаем работу...")
                stop_event.set()
                break

            except Exception as e:
                logger.error(f"Ошибка в основном цикле: {e}\n{traceback.format_exc()}")
                stop_event.wait(30)

    finally:
        # Гарантированное закрытие канала при выходе из программы
        if fp_provider is not None:
            try:
                fp_provider.close_channel()
            except Exception:
                pass
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
