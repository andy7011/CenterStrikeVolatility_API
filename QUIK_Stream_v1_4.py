import logging  # Выводим лог на консоль и в файл
from datetime import datetime, UTC  # Дата и время
import pytz
from scipy.stats import norm
import pandas as pd
from string import Template
import threading
import time  # Подписка на события по времени
import implied_volatility
import option_type
from QuikPy import QuikPy  # Работа с QUIK из Python через LUA скрипты QUIK#
from option import Option

# Конфигурация для работы с файлами
temp_str = 'C:\\Users\\Андрей\\YandexDisk\\_ИИС\\Position\\$name_file'
temp_obj = Template(temp_str)

futures_firm_id = 'SPBFUT'  # Код фирмы для фьючерсов

# Глобальная переменная для хранения активных ордеров
active_orders_set = set()

def get_time_to_maturity(expiration_datetime):
    # Если expiration_datetime - это datetime объект, конвертируем в timestamp
    if isinstance(expiration_datetime, datetime):
        expiration_timestamp = expiration_datetime.timestamp()
    else:
        expiration_timestamp = expiration_datetime

    # Создаем timezone-aware datetime для текущего времени
    # now = datetime.now(UTC)
    moscow_tz = pytz.timezone('Europe/Moscow')
    now = datetime.now(moscow_tz)
    # Преобразуем expiration_timestamp в datetime с UTC временной зоной
    expiration_dt = datetime.fromtimestamp(expiration_timestamp, tz=moscow_tz)
    difference = expiration_dt - now
    seconds_in_year = 365 * 24 * 60 * 60
    return (difference.total_seconds() + 67800) / seconds_in_year # Добавляем 67800 секунд (18 ч. 50 мин.), чтобы учесть время в последний день экспирации

# Функция для форматирования даты и времени
def format_datetime(datetime_dict):
    """Форматирует дату и время из словаря в строку"""
    year = datetime_dict['year']
    month = datetime_dict['month']
    day = datetime_dict['day']
    hour = datetime_dict['hour']
    minute = datetime_dict['min']
    second = datetime_dict['sec']
    formatted_datetime = f"{day:02d}.{month:02d}.{year} {hour:02d}:{minute:02d}:{second:02d}"
    return formatted_datetime


# Глобальные переменные
all_rows_order_list = []  # Список для хранения всех заявок
qp_provider = None  # Глобальная ссылка на провайдер QUIK
class_code = 'SPBOPT'  # Глобальная переменная для класса опционов


class OrderHandler:
    """Класс для обработки событий по заявкам"""

    def trigger(self, data):
        _on_order_impl(data)


class TradeHandler:
    """Класс для обработки событий по сделкам"""

    def trigger(self, data):
        _on_trade_impl(data)


def sync_active_orders():
    global active_orders_set, all_rows_order_list, qp_provider

    try:
        # Получаем все ордера с биржи
        orders_response = qp_provider.get_all_orders()
        if orders_response and orders_response.get('data'):
            current_active_orders = set()
            # Создаем словарь order_num -> order_data для активных ордеров
            current_orders_dict = {}

            for order in orders_response['data']:
                if order.get('class_code') == 'SPBOPT':
                    # Проверяем, что ордер активен (бит 0 установлен) и не снят (бит 1 не установлен)
                    if (order.get('flags') & 0b1 == 0b1) and (order.get('flags') & 0b10 != 0b10):
                        order_num = str(order.get('order_num'))
                        current_active_orders.add(order_num)
                        current_orders_dict[order_num] = order

            # Находим ордера, которые были удалены с биржи или стали неактивными
            orders_to_remove = active_orders_set - current_active_orders

            # Удаляем неактивные ордера из нашего списка
            if orders_to_remove:
                original_count = len(all_rows_order_list)
                all_rows_order_list = [item for item in all_rows_order_list
                                       if str(item['order_num']) not in orders_to_remove]
                removed_count = original_count - len(all_rows_order_list)
                if removed_count > 0:
                    print(f"Удалено {removed_count} неактивных ордеров: {orders_to_remove}")

            # Добавляем новые активные ордера, которых нет в нашем списке
            existing_order_nums = {str(item['order_num']) for item in all_rows_order_list}
            new_orders_to_add = current_active_orders - existing_order_nums

            for order_num in new_orders_to_add:
                order_data = current_orders_dict[order_num]
                # Добавляем ордер в список (передаем сам order_data, не order_data.get('data'))
                _add_order_to_list_from_data(order_data)
                print(f"Добавлен активный ордер при синхронизации: {order_num}")

            # Обновляем список активных ордеров
            active_orders_set = current_active_orders

            # Сохраняем в файл
            _save_orders_to_csv()

    except Exception as e:
        print(f"Ошибка при синхронизации ордеров: {e}")


def sync_portfolio_positions():
    """Синхронизация позиций в портфеле"""
    global qp_provider

    try:
        # Получаем информацию по инструментам в портфеле
        portfolio_positions = []

        # Получаем все классы инструментов
        class_codes = qp_provider.get_classes_list()['data']

        # Получаем позиции по фьючерсам
        futures_holdings_response = qp_provider.get_futures_holdings()
        if futures_holdings_response and futures_holdings_response.get('data'):
            active_futures_holdings = [futuresHolding for futuresHolding in futures_holdings_response['data']
                                      if futuresHolding['totalnet'] != 0]  # Активные фьючерсные позиции

            for active_futures_holding in active_futures_holdings:
                sec_code = active_futures_holding["sec_code"]
                class_code_result = qp_provider.get_security_class(class_codes, sec_code)

                if class_code_result and class_code_result.get('data'):
                    class_code = class_code_result['data']

                    if class_code == "SPBOPT":  # Берем только опционы
                        si = qp_provider.get_symbol_info(class_code, sec_code)  # Спецификация тикера

                        # Тип опциона
                        option_type_response = qp_provider.get_param_ex(class_code, sec_code, 'OPTIONTYPE', trans_id=0)
                        if not option_type_response or not option_type_response.get('data'):
                            continue
                        option_type_str = option_type_response['data']['param_image']
                        opt_type_converted = option_type.PUT if option_type_str == "Put" else option_type.CALL
                        # print(f"Опцион: {sec_code}, тип: {opt_type_converted}")

                        # Время последней сделки Last
                        time_response = qp_provider.get_param_ex(class_code, sec_code, 'TIME', trans_id=0)
                        last_time = ""
                        if time_response and time_response.get('data') and time_response['data'].get('param_image'):
                            last_time = time_response['data']['param_image']
                        # print(f"Время последней сделки: {last_time}")

                        # Цена последней сделки по опциону (LAST)
                        opt_price_response = qp_provider.get_param_ex(class_code, sec_code, 'LAST', trans_id=0)
                        opt_price = 0.0
                        if opt_price_response and opt_price_response.get('data'):
                            param_value = opt_price_response['data'].get('param_value')
                            if param_value is not None and param_value != '':
                                try:
                                    opt_price = float(param_value)
                                except ValueError:
                                    opt_price = 0.0
                        # print(f"Цена последней сделки по опциону: {opt_price}")

                        # Цена опциона BID
                        bid_response = qp_provider.get_param_ex(class_code, sec_code, 'BID', trans_id=0)
                        bid_price = 0.0
                        if bid_response and bid_response.get('data'):
                            param_value = bid_response['data'].get('param_value')
                            if param_value is not None and param_value != '':
                                try:
                                    bid_price = float(param_value)
                                except ValueError:
                                    bid_price = 0.0

                        # Цена опциона OFFER (или ASK)
                        offer_response = qp_provider.get_param_ex(class_code, sec_code, 'OFFER', trans_id=0)
                        offer_price = 0.0
                        if offer_response and offer_response.get('data'):
                            param_value = offer_response['data'].get('param_value')
                            if param_value is not None and param_value != '':
                                try:
                                    offer_price = float(param_value)
                                except ValueError:
                                    offer_price = 0.0

                        # Цена опциона THEORPRICE
                        theor_response = qp_provider.get_param_ex(class_code, sec_code, 'THEORPRICE',
                                                                  trans_id=0)
                        theor_price = 0.0
                        if theor_response and theor_response.get('data') and theor_response['data'].get(
                                'param_value'):
                            try:
                                theor_price = float(theor_response['data']['param_value'])
                            except ValueError:
                                theor_price = 0.0

                        # Цена последней сделки базового актива (S)
                        asset_price_response = qp_provider.get_param_ex('SPBFUT', si['base_active_seccode'], 'LAST', trans_id=0)
                        asset_price = 0.0
                        if asset_price_response and asset_price_response.get('data'):
                            param_value = asset_price_response['data'].get('param_value')
                            if param_value is not None and param_value != '':
                                try:
                                    asset_price = float(param_value)
                                except ValueError:
                                    asset_price = 0.0

                        # Страйк опциона (K)
                        strike_response = qp_provider.get_param_ex(class_code, sec_code, 'STRIKE', trans_id=0)
                        strike_price = 0.0
                        if strike_response and strike_response.get('data') and strike_response['data'].get(
                                'param_value'):
                            try:
                                strike_price = float(strike_response['data']['param_value'])
                            except ValueError:
                                strike_price = 0.0

                        # Волатильность опциона (sigma)
                        VOLATILITY = \
                        qp_provider.get_param_ex(class_code, sec_code, 'VOLATILITY', trans_id=0)['data'][
                            'param_value']
                        VOLATILITY = float(VOLATILITY)
                        # print(f'VOLATILITY - Волатильность опциона: {VOLATILITY}, тип: {type(VOLATILITY)}')

                        # Дата исполнения инструмента
                        EXPDATE_image = qp_provider.get_param_ex(class_code, sec_code, 'EXPDATE', trans_id=0)['data'][
                            'param_image']
                        EXPDATE_str = datetime.strptime(EXPDATE_image, "%d.%m.%Y").strftime("%Y-%m-%d")
                        EXPDATE = datetime.strptime(EXPDATE_str, "%Y-%m-%d")
                        # print(f'EXPDATE - Дата исполнения инструмента: {EXPDATE}, тип: {type(EXPDATE)}')

                        # Дата исполнения инструмента
                        expdate_response = qp_provider.get_param_ex(class_code, sec_code, 'EXPDATE', trans_id=0)
                        expdate_str_formatted = ""
                        if expdate_response and expdate_response.get('data') and expdate_response['data'].get(
                                'param_image'):
                            try:
                                expdate_image = expdate_response['data']['param_image']
                                expdate_dt = datetime.strptime(expdate_image, "%d.%m.%Y")
                                expdate_str_formatted = expdate_dt.strftime("%d.%m.%Y")
                            except ValueError:
                                expdate_str_formatted = ""

                        # Форматирование строки с датой экспирации из спецификации
                        exp_date_number = si.get('exp_date', 0)
                        formatted_exp_date = ""
                        if exp_date_number:
                            try:
                                exp_date_str = str(exp_date_number)
                                exp_date = datetime.strptime(exp_date_str, "%Y%m%d")
                                formatted_exp_date = exp_date.strftime("%d.%m.%Y")
                            except ValueError:
                                formatted_exp_date = ""

                        # Время до исполнения инструмента в долях года
                        time_to_maturity = get_time_to_maturity(EXPDATE)
                        # print(f'time_to_maturity - Время до исполнения инструмента в долях года: {time_to_maturity}, тип: {type(time_to_maturity)}')

                        # Вычисление Vega
                        sigma = VOLATILITY / 100
                        vega = implied_volatility._vega(asset_price, sigma, strike_price, time_to_maturity,
                                                        implied_volatility._RISK_FREE_INTEREST_RATE,
                                                        opt_type_converted)
                        Vega = vega / 100

                        # Число дней до экспирации
                        DAYS_TO_MAT_DATE = \
                        qp_provider.get_param_ex(class_code, sec_code, 'DAYS_TO_MAT_DATE', trans_id=0)['data'][
                            'param_value']
                        DAYS_TO_MAT_DATE = float(DAYS_TO_MAT_DATE)
                        # print(f'DAYS_TO_MAT_DATE - Число дней до погашения: {DAYS_TO_MAT_DATE}, тип: {type(DAYS_TO_MAT_DATE)}')

                        # Вычисление TrueVega
                        if DAYS_TO_MAT_DATE == 0:
                            TrueVega = 0
                        else:
                            TrueVega = Vega / (DAYS_TO_MAT_DATE ** 0.5)

                        # Создание опциона
                        option = Option(si["sec_code"], si["base_active_seccode"], EXPDATE, strike_price,
                                        opt_type_converted)

                        # Вычисление Implied Volatility Last, Bid, Offer
                        # opt_volatility_last = implied_volatility.get_iv_for_option_price(asset_price, option, opt_price)
                        # # print(f'opt_volatility_last - Implied Volatility Last: {opt_volatility_last}, тип: {type(opt_volatility_last)}')

                        # Волатильность опциона IMPLIED_VOLATILITY (IV) - через расчет по цене опциона
                        opt_volatility_last = 0.0
                        if opt_price > 0:
                            opt_volatility_last = implied_volatility.get_iv_for_option_price(asset_price, option,
                                                                                             opt_price)
                            if opt_volatility_last is None:
                                opt_volatility_last = 0.0
                        # print(f"Волатильность опциона IMPLIED_VOLATILITY (IV) - через расчет по цене опциона: {opt_volatility_last}")

                        opt_volatility_bid = implied_volatility.get_iv_for_option_price(asset_price, option, bid_price)
                        # print(f'opt_volatility_bid - Implied Volatility Bid: {opt_volatility_bid}, тип: {type(opt_volatility_bid)}')
                        opt_volatility_offer = implied_volatility.get_iv_for_option_price(asset_price, option, offer_price)
                        # print(f'opt_volatility_offer - Implied Volatility Offer: {opt_volatility_offer}, тип: {type(opt_volatility_offer)}')

                        net_pos = active_futures_holding['totalnet']
                        # OpenDateTime, OpenPrice, OpenIV = calculate_open_data_open_price_open_iv(sec_code, net_pos)
                        open_data_result = calculate_open_data_open_price_open_iv(sec_code, net_pos)
                        # Проверяем, что функция вернула корректные данные
                        if open_data_result is not None and len(open_data_result) > 2:
                            open_datetime = open_data_result[0]
                            open_price = open_data_result[1] if open_data_result[1] is not None else 0.0
                            open_iv = open_data_result[2] if open_data_result[2] is not None else 0.0
                        else:
                            open_datetime = ""
                            open_price = 0.0
                            open_iv = 0.0


                        # Добавляем данные в список
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
                            # 'P/L last': round(opt_volatility_last - open_iv, 2) if net_pos > 0 else round(open_iv - opt_volatility_last, 2),
                            'P/L last': 0 if opt_volatility_last == 0 else (round(opt_volatility_last - open_iv, 2) if net_pos > 0 else round(open_iv - opt_volatility_last, 2)),
                            'P/L market': round(opt_volatility_bid - open_iv, 2) if net_pos > 0 else round(open_iv - opt_volatility_offer, 2),
                            'Vega': round(Vega * net_pos, 2),
                            'TrueVega': round(TrueVega * net_pos, 2)
                        })
                        # print(portfolio_positions)
        # Сохраняем в CSV файл
        if portfolio_positions:
            df_portfolio = pd.DataFrame(portfolio_positions)
            df_portfolio.to_csv(temp_obj.substitute(name_file='QUIK_MyPos.csv'),
                                sep=';', encoding='utf-8', index=False)
        else:
            # Создаем пустой файл с заголовками
            empty_df = pd.DataFrame(columns=[
                'ticker', 'net_pos', 'strike', 'option_type', 'expdate', 'option_base',
                 'OpenDateTime', 'OpenPrice', 'OpenIV', 'time_last', 'bid', 'last', 'ask', 'theor',
                'QuikVola', 'bidIV', 'lastIV', 'askIV', 'P/L theor', 'P/L last', 'P/L market',
                'Vega', 'TrueVega'
            ])
            empty_df.to_csv(temp_obj.substitute(name_file='QUIK_MyPos.csv'),
                            sep=';', encoding='utf-8', index=False)

    except Exception as e:
        print(f"Ошибка при синхронизации позиций портфеля: {e}")



def calculate_open_data_open_price_open_iv(sec_code, net_pos):
    """
    Вычисляет дату открытия позиции, цену и волатильность для заданного инструмента,
    как средневзвешенные по объёму первых сделок до достижения нужного объёма.

    :param sec_code: Код инструмента
    :param net_pos: Текущая позиция (отрицательная для короткой позиции)
    :return: tuple(OpenDateTime, OpenPrice, OpenIV)
    """

    try:
        # Чтение CSV файла
        df = pd.read_csv(temp_obj.substitute(name_file='QUIK_Stream_Trades.csv'), encoding='utf-8', delimiter=';')

        # Фильтрация по инструменту
        instrument_df = df[df['ticker'] == sec_code].copy()

        if instrument_df.empty:
            print(f"Предупреждение: Нет данных для инструмента {sec_code}")
            return None, None, None

        # Преобразование datetime
        instrument_df['datetime'] = pd.to_datetime(instrument_df['datetime'], format='%d.%m.%Y %H:%M:%S')

        # Сортировка по дате
        instrument_df = instrument_df.sort_values('datetime', ascending=False)

        # Определение направления позиции
        if net_pos > 0:
            open_trades = instrument_df[instrument_df['operation'] == 'Купля']
        else:
            open_trades = instrument_df[instrument_df['operation'] == 'Продажа']

        if open_trades.empty:
            print(f"Предупреждение: Нет сделок открытия для инструмента {sec_code}")
            return None, None, None

        # Целевой объём
        required_volume = abs(net_pos)
        cumulative_volume = 0
        selected_trades = []

        # Накапливаем сделки до достижения нужного объёма
        for _, trade in open_trades.iterrows():
            volume = trade['volume']
            if volume <= 0:
                continue  # Пропускаем сделки с volume = 0
            if cumulative_volume + volume <= required_volume:
                selected_trades.append(trade)
                cumulative_volume += volume
            else:
                # Добавляем частичную сделку
                if volume <= 0:
                    continue  # Пропускаем сделки с volume = 0
                    remaining_volume = required_volume - cumulative_volume
                    partial_trade = trade.copy()
                    partial_trade['volume'] = remaining_volume
                    selected_trades.append(partial_trade)
                    break

        if not selected_trades:
            print(f"Предупреждение: Недостаточно сделок для инструмента {sec_code}")
            return None, None, None

        # Создаём DataFrame из выбранных сделок
        selected_df = pd.DataFrame(selected_trades)

        # Дата первой сделки (самой старой сделки, она в конце списка)
        OpenDateTime = selected_df.iloc[-1]['datetime'].strftime('%d.%m.%Y %H:%M:%S')

        # Средневзвешенные значения
        total_volume = selected_df['volume'].sum()
        OpenPrice = (selected_df['price'] * selected_df['volume']).sum() / total_volume
        OpenIV = (selected_df['volatility'] * selected_df['volume']).sum() / total_volume

        return OpenDateTime, OpenPrice, OpenIV

    except Exception as e:
        print(f"Ошибка при вычислении данных открытия для {sec_code}: {e}")
        return None, None, None



# Пример использования:
# OpenDateTime, OpenPrice, OpenIV = calculate_open_data_open_price_open_iv("RI97500BX5", -10)


def _add_order_to_list_from_data(order_data):
    """Добавление ордера в список на основе данных ордера"""
    global all_rows_order_list, qp_provider

    try:
        order_num = str(order_data.get('order_num'))

        # Проверяем, нет ли уже такой заявки в списке
        existing_order = next((item for item in all_rows_order_list if str(item['order_num']) == order_num), None)
        if existing_order:
            print(f"Заявка с order_num {order_num} уже существует, пропускаем")
            return

        # Определяем тип операции
        buy = order_data.get('flags') & 0b100 != 0b100  # Заявка на покупку
        operation = "Купля" if buy else "Продажа"

        # Получаем информацию о ценной бумаге
        sec_code = order_data.get('sec_code')
        si = qp_provider.get_symbol_info('SPBOPT', sec_code)  # Спецификация тикера

        # Получаем цену базового актива
        asset_price_data = qp_provider.get_param_ex('SPBFUT', si['base_active_seccode'], 'LAST', trans_id=0)
        if not asset_price_data or not asset_price_data.get('data'):
            print(f"Не удалось получить цену базового актива для {si['base_active_seccode']}")
            return

        asset_price = float(asset_price_data['data']['param_value'])

        # Получаем дату экспирации
        expdate_data = qp_provider.get_param_ex('SPBOPT', sec_code, 'EXPDATE', trans_id=0)
        if not expdate_data or not expdate_data.get('data'):
            print(f"Не удалось получить дату экспирации для {sec_code}")
            return

        expdate_image = expdate_data['data']['param_image']
        expdate_str = datetime.strptime(expdate_image, "%d.%m.%Y").strftime("%Y-%m-%d")
        expdate = datetime.strptime(expdate_str, "%Y-%m-%d")

        # Определяем тип опциона
        option_type_data = qp_provider.get_param_ex('SPBOPT', sec_code, 'OPTIONTYPE', trans_id=0)
        if not option_type_data or not option_type_data.get('data'):
            print(f"Не удалось получить тип опциона для {sec_code}")
            return

        option_type_str = option_type_data['data']['param_image']
        opt_type_converted = option_type.PUT if option_type_str == "Put" else option_type.CALL

        # Форматируем дату экспирации
        exp_date_number = si['exp_date']
        exp_date_str = str(exp_date_number)
        exp_date = datetime.strptime(exp_date_str, "%Y%m%d")
        formatted_exp_date = exp_date.strftime("%d.%m.%Y")

        # Вычисляем количество и цену
        order_qty = order_data.get('qty') * si['lot_size']
        order_price = qp_provider.quik_price_to_price('SPBOPT', sec_code, order_data.get('price'))

        # Создаем опцион для расчета волатильности
        option = Option(sec_code, si["base_active_seccode"], expdate, si['option_strike'], opt_type_converted)

        # Добавляем заявку в список
        all_rows_order_list.append({
            'datetime': format_datetime(order_data.get('datetime')),
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
            'volatility': round(implied_volatility.get_iv_for_option_price(asset_price, option, order_price), 2)
        })

    except Exception as e:
        print(f"Ошибка при добавлении ордера {order_data.get('order_num')}: {e}")


def _save_orders_to_csv():
    """Сохранение ордеров в CSV"""
    if all_rows_order_list:
        df_order_quik = pd.DataFrame(all_rows_order_list)
        df_order_quik.to_csv(temp_obj.substitute(name_file='QUIK_Stream_Orders.csv'),
                             sep=';', encoding='utf-8', index=False)
    else:
        empty_df = pd.DataFrame(columns=['datetime', 'order_num', 'option_base', 'ticker',
                                         'option_type', 'strike', 'expdate', 'operation',
                                         'volume', 'price', 'value', 'volatility'])
        empty_df.to_csv(temp_obj.substitute(name_file='QUIK_Stream_Orders.csv'),
                        sep=';', encoding='utf-8', index=False)


def _add_order_to_list(order_data):
    """Добавление ордера в список (логика как в _on_order_impl)"""
    _add_order_to_list_from_data(order_data.get('data'))


def sync_orders_worker():
    """Фоновый поток для периодической синхронизации ордеров и позиций портфеля"""
    while True:
        try:
            time.sleep(10)  # Проверяем каждые 10 секунд
            sync_active_orders()
            sync_portfolio_positions()  # Добавляем синхронизацию позиций портфеля
        except Exception as e:
            print(f"Ошибка в потоке синхронизации: {e}")
            time.sleep(5)  # При ошибке ждем 5 секунд перед повтором

# Запуск потока синхронизации при старте
def start_sync_thread():
    sync_thread = threading.Thread(target=sync_orders_worker, daemon=True)
    sync_thread.start()
    print("Поток синхронизации ордеров и позиций портфеля запущен")


# Обновленная функция _on_order_impl
def _on_order_impl(data):
    """Реализация обработчика событий по заявкам"""
    global all_rows_order_list, qp_provider, class_code, active_orders_set

    order_data = data

    # Проверяем, что это опцион
    if order_data.get('data').get('class_code') == 'SPBOPT':
        order_num = str(order_data.get('data').get('order_num'))

        # Проверяем, что ордер активен (бит 0 установлен) и не снят (бит 1 не установлен)
        if (order_data.get('data').get('flags') & 0b1 != 0b1) or (order_data.get('data').get('flags') & 0b10 == 0b10):
            print(f"{format_datetime(order_data.get('data').get('datetime'))} Заявка снята: {order_num}")
            # Удаляем из списка активных ордеров
            active_orders_set.discard(order_num)
            # Удаляем из нашего списка
            original_count = len(all_rows_order_list)
            all_rows_order_list = [item for item in all_rows_order_list if str(item['order_num']) != order_num]
            # removed_count = original_count - len(all_rows_order_list)
            # if removed_count > 0:
                # print(f"Удалено {removed_count} записей с order_num: {order_num}")
        else:
            print(f"{format_datetime(order_data.get('data').get('datetime'))} Новая заявка: {order_num}")
            # Добавляем в список активных ордеров
            active_orders_set.add(order_num)

            # Определяем тип операции
            buy = order_data.get('data').get('flags') & 0b100 != 0b100  # Заявка на покупку
            operation = "Купля" if buy else "Продажа"

            # Получаем информацию о ценной бумаге
            sec_code = order_data.get('data').get('sec_code')
            si = qp_provider.get_symbol_info('SPBOPT', sec_code)  # Спецификация тикера

            # Получаем цену базового актива
            asset_price = qp_provider.get_param_ex('SPBFUT', si['base_active_seccode'], 'LAST', trans_id=0)['data'][
                'param_value']
            asset_price = float(asset_price)

            # Получаем дату экспирации
            expdate_image = qp_provider.get_param_ex('SPBOPT', sec_code, 'EXPDATE', trans_id=0)['data']['param_image']
            expdate_str = datetime.strptime(expdate_image, "%d.%m.%Y").strftime("%Y-%m-%d")
            expdate = datetime.strptime(expdate_str, "%Y-%m-%d")

            # Определяем тип опциона
            option_type_str = qp_provider.get_param_ex('SPBOPT', sec_code, 'OPTIONTYPE', trans_id=0)['data'][
                'param_image']
            opt_type_converted = option_type.PUT if option_type_str == "Put" else option_type.CALL

            # Форматируем дату экспирации
            exp_date_number = si['exp_date']
            exp_date_str = str(exp_date_number)
            exp_date = datetime.strptime(exp_date_str, "%Y%m%d")
            formatted_exp_date = exp_date.strftime("%d.%m.%Y")

            # Вычисляем количество и цену
            order_qty = order_data.get('data').get('qty') * si['lot_size']
            order_price = qp_provider.quik_price_to_price('SPBOPT', sec_code, order_data.get('data').get('price'))

            # Создаем опцион для расчета волатильности
            option = Option(sec_code, si["base_active_seccode"], expdate, si['option_strike'], opt_type_converted)

            # Проверяем, нет ли уже такой заявки в списке
            existing_order = next((item for item in all_rows_order_list if str(item['order_num']) == order_num), None)
            if existing_order:
                print(f"Заявка с order_num {order_num} уже существует, пропускаем")
                return

            # Добавляем заявку в список
            all_rows_order_list.append({
                'datetime': format_datetime(order_data.get('data').get('datetime')),
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
                'volatility': round(implied_volatility.get_iv_for_option_price(asset_price, option, order_price), 2)
            })

        # Создаем DataFrame и сохраняем в CSV только если есть изменения
        if all_rows_order_list:
            df_order_quik = pd.DataFrame(all_rows_order_list)
            df_order_quik.to_csv(temp_obj.substitute(name_file='QUIK_Stream_Orders.csv'), sep=';', encoding='utf-8',
                                 index=False)
        else:
            # Если список пуст, создаем пустой файл с заголовками
            empty_df = pd.DataFrame(columns=['datetime', 'order_num', 'option_base', 'ticker', 'option_type',
                                             'strike', 'expdate', 'operation', 'volume', 'price', 'value',
                                             'volatility'])
            empty_df.to_csv(temp_obj.substitute(name_file='QUIK_Stream_Orders.csv'), sep=';', encoding='utf-8',
                            index=False)



def _on_trade_impl(data):
    """Реализация обработчика событий по сделкам"""
    global qp_provider, class_code

    trade_data = data
    row_trade_list = []  # Список для новой сделки

    # Проверяем, что это опцион
    if trade_data.get('data').get('class_code') == 'SPBOPT':
        print("Новая сделка")

        # Определяем тип операции
        buy = trade_data.get('data').get('flags') & 0b100 != 0b100  # Заявка на покупку
        operation = "Купля" if buy else "Продажа"

        # Получаем информацию о ценной бумаге
        sec_code = trade_data.get('data').get('sec_code')
        si = qp_provider.get_symbol_info('SPBOPT', sec_code)

        # Получаем цену базового актива
        asset_price = qp_provider.get_param_ex('SPBFUT', si['base_active_seccode'], 'LAST', trans_id=0)['data'][
            'param_value']
        asset_price = float(asset_price)

        # Получаем дату экспирации
        expdate_image = qp_provider.get_param_ex('SPBOPT', sec_code, 'EXPDATE', trans_id=0)['data']['param_image']
        expdate_str = datetime.strptime(expdate_image, "%d.%m.%Y").strftime("%Y-%m-%d")
        expdate = datetime.strptime(expdate_str, "%Y-%m-%d")

        # Определяем тип опциона
        option_type_str = qp_provider.get_param_ex('SPBOPT', sec_code, 'OPTIONTYPE', trans_id=0)['data']['param_image']
        opt_type_converted = option_type.PUT if option_type_str == "Put" else option_type.CALL

        # Форматируем дату экспирации
        exp_date_number = si['exp_date']
        exp_date_str = str(exp_date_number)
        exp_date = datetime.strptime(exp_date_str, "%Y%m%d")
        formatted_exp_date = exp_date.strftime("%d.%m.%Y")

        # Вычисляем количество и цену
        trade_qty = trade_data.get('data').get('qty') * si['lot_size']
        trade_price = qp_provider.quik_price_to_price('SPBOPT', sec_code, trade_data.get('data').get('price'))

        # Создаем опцион для расчета волатильности
        option = Option(sec_code, si["base_active_seccode"], expdate, si['option_strike'], opt_type_converted)

        # Добавляем сделку в список
        row_trade_list.append({
            'datetime': format_datetime(trade_data.get('data').get('datetime')),
            'order_num': trade_data.get('data').get('trade_num'),
            'option_base': si['base_active_seccode'],
            'ticker': sec_code,
            'option_type': option_type_str,
            'strike': int(si['option_strike']),
            'expdate': formatted_exp_date,
            'operation': operation,
            'volume': trade_qty,
            'price': trade_price,
            'value': trade_qty * trade_price,
            'volatility': round(implied_volatility.get_iv_for_option_price(asset_price, option, trade_price), 2)
        })

        # Создаем DataFrame и добавляем в CSV файл
        df_trade_quik = pd.DataFrame(row_trade_list)
        print(df_trade_quik)
        df_trade_quik.to_csv(temp_obj.substitute(name_file='QUIK_Stream_Trades.csv'), mode='a', sep=';', index=False,
                             header=False)


if __name__ == '__main__':  # Точка входа при запуске этого скрипта
    # Настройка логирования
    logger = logging.getLogger('QuikPy.Accounts')
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%d.%m.%Y %H:%M:%S',
        level=logging.DEBUG,
        handlers=[
            logging.FileHandler('QUIK_Stream.log', encoding='utf-8'),
            logging.StreamHandler()
        ]
    )

    # Подключение к QUIK
    qp_provider = QuikPy()

    # Сразу выполняем синхронизацию активных ордеров и инструментов портфеля
    sync_active_orders()
    sync_portfolio_positions()

    # Запускаем поток синхронизации
    start_sync_thread()

    # Создаем обработчики событий
    order_handler = OrderHandler()
    trade_handler = TradeHandler()

    # Подписка на события через объекты с методом trigger
    qp_provider.on_order = order_handler
    qp_provider.on_trade = trade_handler

    # Основной цикл
    try:
        print("Сервис запущен. Нажмите Ctrl+C для остановки.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Остановка сервиса...")
        qp_provider.close_connection_and_thread()
        print("Сервис остановлен")
