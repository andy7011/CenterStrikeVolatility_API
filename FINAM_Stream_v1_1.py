import logging  # Модуль для ведения логов
from threading import Thread, Event  # Модуль для создания потоков и событий
from datetime import datetime  # Модуль для работы с датой и временем
from time import sleep  # Функция для приостановки выполнения программы
import traceback  # Модуль для получения полной информации об ошибке

from FinamPy import FinamPy  # Основной класс библиотеки FinamPy
from FinamPy.grpc import orders_service_pb2 as orders_service
from FinLabPy.Schedule.MOEX import Futures  # Расписание торгов
from app.supported_base_asset import MAP  # Список базовых активов

# Логгер на уровне модуля
logger = logging.getLogger('FinamPy.Stream')

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

                def to_float(decimal_field):
                    if decimal_field and hasattr(decimal_field, 'value') and decimal_field.value:
                        try:
                            return float(decimal_field.value)
                        except (ValueError, TypeError):
                            return 0.0
                    return 0.0

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

        # --- Временный лог: количество активных заявок в хранилище ---
        logger.info(f"Активных заявок в хранилище: {len(active_orders)}")

    except Exception as e:
        logger.error(f"Ошибка в _on_order: {e}\n{traceback.format_exc()}")



def is_order_status_active(status: str) -> bool:
    """Определяет, является ли статус заявки активным."""
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


def subscribe_orders(fp_provider, account_id):
    """Подписка на события по собственным заявкам"""
    fp_provider.on_order.subscribe(_on_order)
    thread = Thread(
        target=fp_provider.subscribe_orders_thread,  # ← исправлено
        name='OrdersThread',
        args=(account_id,),
        daemon=True
    )
    thread.start()
    logger.info(f"Подписка на собственные заявки аккаунта {account_id} запущена")
    return thread



# Хранилище последних котировок базовых активов
base_asset_quotes = {}


def _on_quote(quote):
    """Обработчик котировок базовых активов"""
    if not quote.quote:
        logger.warning("Получена пустая котировка")
        return

    for q in quote.quote:
        symbol = q.symbol.split('@')[0]
        if symbol not in MAP:
            continue

        ask = float(q.ask.value) if q.HasField('ask') and q.ask.value else 0.0
        bid = float(q.bid.value) if q.HasField('bid') and q.bid.value else 0.0
        last = float(q.last.value) if q.HasField('last') and q.last.value else 0.0

        base_asset_quotes[symbol] = {
            'ask': ask,
            'bid': bid,
            'last': last,
            'time': datetime.now().strftime('%H:%M:%S')
        }

        # logger.info(f"{symbol}: ask={ask:.2f}, bid={bid:.2f}, last={last:.2f}")


def subscribe_base_assets(fp_provider):
    """Подписка на котировки всех базовых активов из MAP."""
    symbols_for_subscription = []

    for ticker in MAP.keys():
        dataname = f'SPBFUT.{ticker}'
        try:
            finam_board, ticker_code = fp_provider.dataname_to_finam_board_ticker(dataname)
            mic = fp_provider.get_mic(finam_board, ticker_code)
            symbols_for_subscription.append(f'{ticker_code}@{mic}')
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
            data['equity'] = float(account_response.equity.value) if account_response.equity.value else 0.0
        if hasattr(account_response, 'unrealized_profit') and account_response.unrealized_profit:
            data['unrealized_profit'] = float(
                account_response.unrealized_profit.value) if account_response.unrealized_profit.value else 0.0

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
        if hasattr(account_response, 'portfolio_forts') and account_response.HasField('portfolio_forts'):
            data['portfolio_type'] = 'FORTS'
            forts = account_response.portfolio_forts
            data['margin'] = {
                'available_cash': float(forts.available_cash.value) if forts.available_cash else 0.0,
                'money_reserved': float(forts.money_reserved.value) if forts.money_reserved else 0.0,
            }
            data['cash']['RUB'] = {
                'balance': float(forts.available_cash.value) if forts.available_cash else 0.0,
                'blocked': float(forts.money_reserved.value) if forts.money_reserved else 0.0,
                'free': float(forts.available_cash.value) if forts.available_cash else 0.0,
                'GM': (float(forts.money_reserved.value) / data['equity']) * 100 if data['equity'] else 0.0,
            }
        elif hasattr(account_response, 'portfolio_mc') and account_response.HasField('portfolio_mc'):
            data['portfolio_type'] = 'MC'
            mc = account_response.portfolio_mc
            data['margin'] = {
                'available_cash': float(mc.available_cash.value) if mc.available_cash else 0.0,
                'initial_margin': float(mc.initial_margin.value) if mc.initial_margin else 0.0,
                'maintenance_margin': float(mc.maintenance_margin.value) if mc.maintenance_margin else 0.0,
            }
        elif hasattr(account_response, 'portfolio_mct') and account_response.HasField('portfolio_mct'):
            data['portfolio_type'] = 'MCT'
            mct = account_response.portfolio_mct
            data['margin'] = {
                'available_cash': float(mct.available_cash.value) if mct.available_cash else 0.0,
                'initial_margin': float(mct.initial_margin.value) if mct.initial_margin else 0.0,
                'maintenance_margin': float(mct.maintenance_margin.value) if mct.maintenance_margin else 0.0,
            }

        # --- Парсим позиции ---
        data['positions'] = {}

        for position in account_response.positions:
            try:
                symbol = position.symbol if hasattr(position, 'symbol') else 'UNKNOWN'

                quantity = 0.0
                if hasattr(position, 'quantity') and position.quantity and position.quantity.value:
                    quantity = float(position.quantity.value)

                current_price = 0.0
                if hasattr(position, 'current_price') and position.current_price and position.current_price.value:
                    current_price = float(position.current_price.value)

                average_price = 0.0
                if hasattr(position, 'average_price') and position.average_price and position.average_price.value:
                    average_price = float(position.average_price.value)

                maintenance_margin = 0.0
                if hasattr(position, 'maintenance_margin') and position.maintenance_margin and position.maintenance_margin.value:
                    maintenance_margin = float(position.maintenance_margin.value)

                daily_pnl = 0.0
                if hasattr(position, 'daily_pnl') and position.daily_pnl and position.daily_pnl.value:
                    daily_pnl = float(position.daily_pnl.value)

                unrealized_pnl = 0.0
                if hasattr(position, 'unrealized_pnl') and position.unrealized_pnl and position.unrealized_pnl.value:
                    unrealized_pnl = float(position.unrealized_pnl.value)

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

        # # Вывод в консоль (для отладки)
        # print(data['positions'])
        # print(data['cash'])
        # print(data['margin'])
        # print(f"equity: {data['equity']}")
        # print(f"unrealized_profit: {data['unrealized_profit']}")
        # rub_cash = data['cash'].get('RUB', {})
        # print(f"GM: {rub_cash.get('GM', 0.0)}")

    except Exception as e:
        logger.error(f"Необработанная ошибка в _on_account_info: {e}\n{traceback.format_exc()}")


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


def get_market_now():
    """Возвращает текущее время в часовой зоне биржи (Москва) как naive datetime."""
    return datetime.now(schedule.market_timezone).replace(tzinfo=None)


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


def run_subscription_loop(fp_provider, account_id, stop_event):
    """
    Запускает подписку и контролирует её работу в течение текущей сессии.
    Возвращает True, если подписка завершилась из-за ошибки (нужно перезапускать),
    и False, если сессия закончилась и надо просто ждать следующей.
    """
    stream_thread = start_account_stream(fp_provider, account_id)
    retry_delay = 5
    max_delay = 60

    while not stop_event.is_set():
        # Проверяем, что текущее время всё ещё внутри торговой сессии
        now = get_market_now()
        if not schedule.trade_session(now):
            logger.info("Торговая сессия закончилась.")
            return False

        # Если поток подписки умер — пробуем переподключиться
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
                stream_thread = start_account_stream(fp_provider, account_id)
                subscribe_base_assets(fp_provider)  # ВАЖНО: переподписываемся и на базовые активы
                subscribe_orders(fp_provider, account_id)
                logger.info("Переподключение выполнено успешно")
                retry_delay = 5
            except Exception as e:
                logger.error(f"Ошибка при переподключении: {e}\n{traceback.format_exc()}")
                continue

        stop_event.wait(1)

    return False


def main():
    """Основная функция: работает по расписанию биржи, восстанавливается при сбоях"""
    logger.info("Запуск программы мониторинга аккаунта по расписанию биржи")

    stop_event = Event()

    while not stop_event.is_set():
        # Ждём начала торговой сессии
        wait_for_trading_session(stop_event)
        if stop_event.is_set():
            break

        try:
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

            # Запускаем подписку на аккаунт и на базовые активы
            subscribe_base_assets(fp_provider)
            subscribe_orders(fp_provider, account_id)

            # Входим в цикл контроля сессии
            run_subscription_loop(fp_provider, account_id, stop_event)

            # После окончания сессии закрываем соединение
            try:
                fp_provider.close_channel()
            except Exception:
                pass

        except KeyboardInterrupt:
            logger.info("Получен сигнал остановки. Завершаем работу...")
            stop_event.set()

        except Exception as e:
            logger.error(f"Ошибка в основном цикле: {e}\n{traceback.format_exc()}")
            stop_event.wait(30)

    logger.info("Программа остановлена")


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
