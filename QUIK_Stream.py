import logging  # Выводим лог на консоль и в файл
from datetime import datetime, UTC  # Дата и время
from scipy.stats import norm
import pandas as pd
# import json
import time  # Подписка на события по времени

import implied_volatility
import option_type
from QuikPy import QuikPy  # Работа с QUIK из Python через LUA скрипты QUIK#
from option import Option

futures_firm_id = 'SPBFUT'  # Код фирмы для фьючерсов. Измените, если требуется, на фирму, которую для фьючерсов поставил ваш брокер

'''
    :param S: Asset price
    :param K: Strike price
    :param T: Time to maturity
    :param r: risk-free rate
    :param sigma: volatility
    :param cp: Call or Put
'''

# Функция для форматирования даты и времени
# из словаря вида {'hour': 10, 'year': 2025, 'day': 14, 'week_day': 5, 'ms': 199, 'mcs': 199284, 'min': 23, 'month': 11, 'sec': 49}
# при обратном вызове on_order, on_trade в строку вида 14.11.2025 10:23:49
def format_datetime(datetime_dict):
    # Извлекаем значения даты и времени из словаря
    year = datetime_dict['year']
    month = datetime_dict['month']
    day = datetime_dict['day']
    hour = datetime_dict['hour']
    minute = datetime_dict['min']
    second = datetime_dict['sec']
    # Формируем строку в нужном формате
    formatted_datetime = f"{day:02d}.{month:02d}.{year} {hour:02d}:{minute:02d}:{second:02d}"
    return formatted_datetime

def get_time_to_maturity(expiration_datetime: int):
    difference = expiration_datetime - datetime.utcnow()
    seconds_in_year = 365 * 24 * 60 * 60
    return difference.total_seconds() / seconds_in_year

def _on_order(data):
    order_data = data
    print(order_data.get('cmd'), order_data.get('data').get('class_code'))
    # print(data)
    if order_data.get('data').get('class_code') == 'SPBOPT':
        buy = order_data.get('data').get('flags') & 0b100 != 0b100  # Заявка на покупку
        Operation = "Купля" if buy else "Продажа"
        sec_code = order_data.get('data').get('sec_code')
        si = qp_provider.get_symbol_info('SPBOPT', sec_code)  # Спецификация тикера
        # print(si)

        # Цена последней сделки базового актива (S)
        asset_price = qp_provider.get_param_ex('SPBFUT', si['base_active_seccode'], 'LAST', trans_id=0)['data']['param_value']
        asset_price = float(asset_price)
        # print(f'asset_price - Цена последней сделки базового актива: {asset_price}, тип: {type(asset_price)}')

        # Дата исполнения инструмента
        EXPDATE_image = qp_provider.get_param_ex('SPBOPT', sec_code, 'EXPDATE', trans_id=0)['data']['param_image']
        EXPDATE_str = datetime.strptime(EXPDATE_image, "%d.%m.%Y").strftime("%Y-%m-%d")
        EXPDATE = datetime.strptime(EXPDATE_str, "%Y-%m-%d")
        # print(f'EXPDATE - Дата исполнения инструмента: {EXPDATE}, тип: {type(EXPDATE)}')

        # Тип опциона
        option_type_str = qp_provider.get_param_ex(class_code, sec_code, 'OPTIONTYPE', trans_id=0)['data']['param_image']  # Тип опциона
        # print(f'option_type - Тип опциона: {option_type_str}')
        opt_type_converted = option_type.PUT if option_type_str == "Put" else option_type.CALL

        # Создание опциона
        option = Option(order_data.get('data').get('sec_code'), si["base_active_seccode"], EXPDATE, si['option_strike'], opt_type_converted)

        for item in all_rows_order_list:
            if item.get('ticker') == order_data.get('data').get('sec_code') and item.get('operation') == Operation:
                item['datetime'] = format_datetime(order_data.get('data').get('datetime')) # Дата и время новой заявки
                item['order_num'] = order_data.get('data').get('order_num') # Номер новой заявки
                item['qty'] = order_data["data"]['qty'] # Количество новой заявки
                item['price'] = order_data['data']['price'] # Цена новой заявки
                item['volume'] = order_data['data']['value'] # Объем новой заявки в денежных средствах
                item['volatility'] = round(implied_volatility.get_iv_for_option_price(asset_price, option, item['price']), 2) # IV новой заявки
                # item['time_to_maturity'] = get_time_to_maturity(item['expiration_date']) # Время до исполнения

                print(item)


def _on_trade(data): logger.info(f'Сделка - {data}')
    # 'trade_num'


if __name__ == '__main__':  # Точка входа при запуске этого скрипта
    logger = logging.getLogger('QuikPy.Accounts')  # Будем вести лог
    qp_provider = QuikPy()  # Подключение к локальному запущенному терминалу QUIK



    # Закомментировать, чтобы не было логов
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  # Формат сообщения
                        datefmt='%d.%m.%Y %H:%M:%S',  # Формат даты
                        level=logging.DEBUG,  # Уровень логируемых событий NOTSET/DEBUG/INFO/WARNING/ERROR/CRITICAL
                        handlers=[logging.FileHandler('QUIK_Stream.log', encoding='utf-8'), logging.StreamHandler()])  # Лог записываем в файл и выводим на консоль
    logging.Formatter.converter = lambda *args: datetime.now(tz=qp_provider.tz_msk).timetuple()  # В логе время указываем по МСК



    class_codes = qp_provider.get_classes_list()['data']  # Режимы торгов через запятую
    class_codes_list = class_codes[:-1].split(',')  # Удаляем последнюю запятую, разбиваем значения по запятой в список режимов торгов
    trade_accounts = qp_provider.get_trade_accounts()['data']  # Все торговые счета
    money_limits = qp_provider.get_money_limits()['data']  # Все денежные лимиты (остатки на счетах)
    depo_limits = qp_provider.get_all_depo_limits()['data']  # Все лимиты по бумагам (позиции по инструментам)
    orders = qp_provider.get_all_orders()['data']  # Все заявки
    stop_orders = qp_provider.get_all_stop_orders()['data']  # Все стоп заявки

    i = 0  # Номер учетной записи
    for trade_account in trade_accounts:  # Пробегаемся по всем счетам (Коды клиента/Фирма/Счет)
        trade_account_class_codes = trade_account['class_codes'][1:-1].split('|')  # Режимы торгов счета. Удаляем первую и последнюю вертикальную черту, разбиваем значения по вертикальной черте
        intersection_class_codes = list(set(trade_account_class_codes).intersection(class_codes_list))  # Режимы торгов, которые есть и в списке и в торговом счете
        # for class_code in intersection_class_codes:  # Пробегаемся по всем режимам торгов
        #     class_info = qp_provider.get_class_info(class_code)['data']  # Информация о режиме торгов
        #     logger.info(f'- Режим торгов {class_code} ({class_info["name"]}), Тикеров {class_info["nsecs"]}')
        #     class_securities = qp_provider.get_class_securities(class_code)['data'][:-1].split(',')  # Список инструментов режима торгов. Удаляем последнюю запятую, разбиваем значения по запятой
        #     logger.info(f'  - Тикеры ({class_securities})')

        # Получаем информацию о счете
        firm_id = trade_account['firmid']  # Фирма
        trade_account_id = trade_account['trdaccid']  # Счет
        client_code = next((moneyLimit['client_code'] for moneyLimit in money_limits if moneyLimit['firmid'] == firm_id), None)  # Код клиента
        logger.info(f'Учетная запись #{i}, Код клиента {client_code if client_code else "не задан"}, Фирма {firm_id}, Счет {trade_account_id} ({trade_account["description"]})')
        logger.info(f'Режимы торгов: {intersection_class_codes}')
        # Получаем информацию по инструментам в портфеле
        if firm_id == futures_firm_id:  # Для фирмы фьючерсов
            active_futures_holdings = [futuresHolding for futuresHolding in qp_provider.get_futures_holdings()['data'] if futuresHolding['totalnet'] != 0]  # Активные фьючерсные позиции
            all_rows_table_list = []
            for active_futures_holding in active_futures_holdings:  # Пробегаемся по всем активным позициям
                sec_code = active_futures_holding["sec_code"]  # Код тикера
                class_code = qp_provider.get_security_class(class_codes, sec_code)['data']  # Код режима торгов из всех режимов по тикеру
                if class_code == "SPBOPT": # Берем только опционы
                    si = qp_provider.get_symbol_info(class_code, active_futures_holding['sec_code'])  # Спецификация тикера
                    # print(si)

                    # Тип опциона
                    option_type_str = qp_provider.get_param_ex(class_code, sec_code, 'OPTIONTYPE', trans_id=0)['data']['param_image'] # Тип опциона
                    # print(f'option_type - Тип опциона: {option_type_str}')
                    opt_type_converted = option_type.PUT if option_type_str == "Put" else option_type.CALL

                    # Цена последней сделки по опциону (LAST)
                    opt_price_str = qp_provider.get_param_ex(class_code, sec_code, 'LAST', trans_id=0)['data']['param_value']
                    opt_price = float(opt_price_str)
                    # print(f'opt_price - Цена последней сделки: {opt_price}, тип: {type(opt_price)}')

                    # Цена опциона BID
                    BID = qp_provider.get_param_ex(class_code, sec_code, 'BID', trans_id=0)['data']['param_value']
                    BID = float(BID)
                    # print(f'BID - Цена BID: {BID}, тип: {type(BID)}')

                    # Цена опциона OFFER (или ASK)
                    OFFER = qp_provider.get_param_ex(class_code, sec_code, 'OFFER', trans_id=0)['data']['param_value']
                    OFFER = float(OFFER)
                    # print(f'OFFER - Цена ASK: {OFFER}, тип: {type(OFFER)}')

                    # Время последней сделки Last
                    TIME = qp_provider.get_param_ex(class_code, sec_code, 'TIME', trans_id=0)['data']['param_image']
                    # print(f'TIME - Время последней сделки: {TIME}')

                    # Цена последней сделки базового актива (S)
                    asset_price = qp_provider.get_param_ex('SPBFUT', si['base_active_seccode'], 'LAST', trans_id=0)['data']['param_value']
                    asset_price = float(asset_price)
                    # print(f'asset_price - Цена последней сделки базового актива: {asset_price}, тип: {type(asset_price)}')

                    # Страйк опциона (K)
                    STRIKE = qp_provider.get_param_ex(class_code, sec_code, 'STRIKE', trans_id=0)['data']['param_value']
                    STRIKE = float(STRIKE)
                    # print(f'STRIKE - Страйк опциона: {STRIKE}, тип: {type(STRIKE)}')

                    # Волатильность опциона (sigma)
                    VOLATILITY = qp_provider.get_param_ex(class_code, sec_code, 'VOLATILITY', trans_id=0)['data']['param_value']
                    VOLATILITY = float(VOLATILITY)
                    # print(f'VOLATILITY - Волатильность опциона: {VOLATILITY}, тип: {type(VOLATILITY)}')

                    ## Теоретическая цена
                    # THEORPRICE = qp_provider.get_param_ex(class_code, sec_code, 'THEORPRICE', trans_id=0)['data']['param_value']
                    # THEORPRICE = float(THEORPRICE)
                    # print(f'THEORPRICE - Теоретическая цена опциона: {THEORPRICE}')

                    # Дата исполнения инструмента
                    EXPDATE_image = qp_provider.get_param_ex(class_code, sec_code, 'EXPDATE', trans_id=0)['data']['param_image']
                    EXPDATE_str = datetime.strptime(EXPDATE_image, "%d.%m.%Y").strftime("%Y-%m-%d")
                    EXPDATE = datetime.strptime(EXPDATE_str, "%Y-%m-%d")
                    # print(f'EXPDATE - Дата исполнения инструмента: {EXPDATE}, тип: {type(EXPDATE)}')

                    # Время до исполнения инструмента в долях года
                    time_to_maturity = get_time_to_maturity(EXPDATE)
                    # print(f'time_to_maturity - Время до исполнения инструмента в долях года: {time_to_maturity}, тип: {type(time_to_maturity)}')

                    # Число дней до экспирации
                    DAYS_TO_MAT_DATE = qp_provider.get_param_ex(class_code, sec_code, 'DAYS_TO_MAT_DATE', trans_id=0)['data']['param_value']
                    DAYS_TO_MAT_DATE = float(DAYS_TO_MAT_DATE)
                    # print(f'DAYS_TO_MAT_DATE - Число дней до погашения: {DAYS_TO_MAT_DATE}, тип: {type(DAYS_TO_MAT_DATE)}')

                    # Вычисление Vega
                    sigma = VOLATILITY / 100
                    vega = implied_volatility._vega(asset_price, sigma, STRIKE, time_to_maturity, implied_volatility._RISK_FREE_INTEREST_RATE, opt_type_converted)
                    Vega = vega / 100

                    # Вычисление TrueVega
                    if DAYS_TO_MAT_DATE == 0:
                        TrueVega = 0
                    else:
                        TrueVega = Vega / (DAYS_TO_MAT_DATE ** 0.5)

                    # Создание опциона
                    option = Option(si["sec_code"], si["base_active_seccode"], EXPDATE, STRIKE, opt_type_converted)

                    # Вычисление Implied Volatility Last, Bid, Offer
                    opt_volatility_last = implied_volatility.get_iv_for_option_price(asset_price, option, opt_price)
                    opt_volatility_bid = implied_volatility.get_iv_for_option_price(asset_price, option, BID)
                    opt_volatility_offer = implied_volatility.get_iv_for_option_price(asset_price, option, OFFER)

                    # Текущие чистые позиции (totalnet)
                    net_pos = active_futures_holding['totalnet']
                    # print(f'net_pos - Текущие чистые позиции {si["sec_code"]}: {net_pos}, тип: {type(net_pos)}')

                    # print(f'opt_volatility - Волатильность опциона Last {si["sec_code"]} {option_type_str}: {opt_volatility_last}, {opt_price_str}, {TIME}')
                    # print(f'opt_volatility_bid - Волатильность опциона Bid {si["sec_code"]} {option_type_str}: {opt_volatility_bid}, {BID}')
                    # print(f'opt_volatility_offer - Волатильность опциона Ask {si["sec_code"]} {option_type_str}: {opt_volatility_offer}, {OFFER}')
                    # print(f'Vega опциона {si["sec_code"]} {option_type_str}: {Vega}')
                    # print(f'TrueVega опциона {si["sec_code"]} {option_type_str}: {TrueVega}')
                    # print('\n')

                    # === СОБИРАЕМ СТРОКИ В СПИСОК ===
                    # Добавляем строку
                    all_rows_table_list.append({
                        'ticker': si['sec_code'],
                        'net_pos': net_pos,
                        'strike': int(STRIKE),
                        'option_type': option_type_str,
                        'expdate': EXPDATE_image,
                        'dayexp': int(DAYS_TO_MAT_DATE),
                        'option_base': si['base_active_seccode'],
                        'OpenDateTime': "",
                        'OpenPrice': "",
                        'OpenIV': "",
                        'QuikVola': round(VOLATILITY, 2),
                        'BidIV': round(opt_volatility_bid, 2),
                        'AskIV': opt_volatility_offer,
                        'P/L theor': '', # round(VOLATILITY - OpenIV, 2) if net_pos > 0 else round(OpenIV - VOLATILITY, 2),
                        'P/L market': "", # round(opt_volatility_bid - OpenIV, 2) if net_pos > 0 else round(OpenIV - opt_volatility_offer, 2),
                        'Vega': round(Vega, 2),
                        'TrueVega': round(TrueVega, 2)
                    })

                    # logger.info(f'- Позиция {si["class_code"]}.{si["sec_code"]} ({si["short_name"]}) {active_futures_holding["totalnet"]} @ {active_futures_holding["cbplused"]}')
                    # info_portfolio = {'sec_code': si['sec_code'], 'base_active_seccode': si['base_active_seccode'], 'class_code': si['class_code'], 'exp_date': si['exp_date'], 'option_strike': si['option_strike'], 'totalnet': active_futures_holding['totalnet'], 'avrposnprice': active_futures_holding['avrposnprice']}
                    # print(info_portfolio)

                    # print(active_futures_holding)
                    # data_portfolio = {active_futures_holding['totalnet'], active_futures_holding['avrposnprice']}
                    # print(data_portfolio)

            print(all_rows_table_list) # список словарей с данными по позициям

            df_table_quik = pd.DataFrame(all_rows_table_list) # DataFrame с данными по позициям
            print(df_table_quik)

            # Видео: https://www.youtube.com/watch?v=u2C7ElpXZ4k
            # Баланс = Лимит откр.поз. + Вариац.маржа + Накоплен.доход
            # Лимит откр.поз. = Сумма, которая была на счету вчера в 19:00 МСК (после вечернего клиринга)
            # Вариац.маржа = Рассчитывается с 19:00 предыдущего дня без учета комисии. Перейдет в Накоплен.доход и обнулится в 14:00 (на дневном клиринге)
            # Накоплен.доход включает Биржевые сборы
            # Тек.чист.поз. = Заблокированное ГО под открытые позиции
            # План.чист.поз. = На какую сумму можете открыть еще позиции
            futures_limit = qp_provider.get_futures_limit(firm_id, trade_account_id, 0, qp_provider.currency)['data']  # Фьючерсные лимиты по денежным средствам (limit_type=0)
            value = futures_limit['cbplused']  # Стоимость позиций
            cash = futures_limit['cbplimit'] + futures_limit['varmargin'] + futures_limit['accruedint']  # Свободные средства = Лимит откр.поз. + Вариац.маржа + Накоплен.доход
            logger.info(f'- Позиции {value:.2f} + Свободные средства {cash:.2f} = {(value + cash):.2f} {futures_limit["currcode"]}')
        else:  # Для остальных фирм
            firm_money_limits = [moneyLimit for moneyLimit in money_limits if moneyLimit['firmid'] == firm_id]  # Денежные лимиты по фирме
            for firm_money_limit in firm_money_limits:  # Пробегаемся по всем денежным лимитам
                limit_kind = firm_money_limit['limit_kind']  # День лимита
                firm_kind_depo_limits = [depoLimit for depoLimit in depo_limits if
                                         depoLimit['firmid'] == firm_id and
                                         depoLimit['limit_kind'] == limit_kind and
                                         depoLimit['currentbal'] != 0]  # Берем только открытые позиции по фирме и дню
                for firm_kind_depo_limit in firm_kind_depo_limits:  # Пробегаемся по всем позициям
                    sec_code = firm_kind_depo_limit["sec_code"]  # Код тикера
                    class_code = qp_provider.get_security_class(class_codes, sec_code)['data']  # Код режима торгов из всех режимов по тикеру
                    entry_price = qp_provider.quik_price_to_price(class_code, sec_code, float(firm_kind_depo_limit["wa_position_price"]))  # Цена входа в рублях за штуку
                    last_price = qp_provider.quik_price_to_price(class_code, sec_code, float(qp_provider.get_param_ex(class_code, sec_code, 'LAST')['data']['param_value']))  # Последняя цена сделки в рублях за штуку
                    si = qp_provider.get_symbol_info(class_code, sec_code)  # Спецификация тикера
                    logger.info(f'- Позиция {class_code}.{sec_code} ({si["short_name"]}) {int(firm_kind_depo_limit["currentbal"])} @ {entry_price} / {last_price}')
                logger.info(f'- T{limit_kind}: Свободные средства {firm_money_limit["currentbal"]} {firm_money_limit["currcode"]}')

        # Активные заявки
        firm_orders = [order for order in orders if order['firmid'] == firm_id and order['flags'] & 0b1 == 0b1]  # Активные заявки по фирме
        all_rows_order_list = [] # Пустой список всех заявок
        for firm_order in firm_orders:  # Пробегаемся по всем заявкам
            # print(firm_order)
            buy = firm_order['flags'] & 0b100 != 0b100  # Заявка на покупку
            class_code = firm_order['class_code']  # Код режима торгов
            sec_code = firm_order["sec_code"]  # Тикер
            order_price = qp_provider.quik_price_to_price(class_code, sec_code, firm_order['price'])  # Цена заявки в рублях за штуку
            si = qp_provider.get_symbol_info(class_code, sec_code)  # Спецификация тикера
            # print(si)

            order_qty = firm_order['qty'] * si['lot_size']  # Кол-во в штуках
            logger.info(f'- Заявка номер {firm_order["order_num"]} {"Купля" if buy else "Продажа"} {class_code}.{sec_code} {order_qty} @ {order_price}')

            # Цена последней сделки базового актива (S)
            asset_price = qp_provider.get_param_ex('SPBFUT', si['base_active_seccode'], 'LAST', trans_id=0)['data']['param_value']
            asset_price = float(asset_price)
            # print(f'asset_price - Цена последней сделки базового актива: {asset_price}, тип: {type(asset_price)}')

            # Дата исполнения инструмента
            EXPDATE_image = qp_provider.get_param_ex(class_code, sec_code, 'EXPDATE', trans_id=0)['data']['param_image']
            EXPDATE_str = datetime.strptime(EXPDATE_image, "%d.%m.%Y").strftime("%Y-%m-%d")
            EXPDATE = datetime.strptime(EXPDATE_str, "%Y-%m-%d")
            # print(f'EXPDATE - Дата исполнения инструмента: {EXPDATE}, тип: {type(EXPDATE)}')

            # Тип опциона
            option_type_str = qp_provider.get_param_ex(class_code, sec_code, 'OPTIONTYPE', trans_id=0)['data']['param_image']
            # print(f'option_type - Тип опциона: {option_type_str}')
            opt_type_converted = option_type.PUT if option_type_str == "Put" else option_type.CALL

            # Форматирование строки с датой экспирации
            exp_date_number = si['exp_date']
            # Преобразуем число в строку
            exp_date_str = str(exp_date_number)
            # Преобразуем строку в объект datetime
            exp_date = datetime.strptime(exp_date_str, "%Y%m%d")
            # Форматируем дату в нужный формат
            formatted_exp_date = exp_date.strftime("%d.%m.%Y")

            # Создание опциона
            option = Option(si["sec_code"], si["base_active_seccode"], EXPDATE, si['option_strike'], opt_type_converted)

            # === СОБИРАЕМ ВСЕ СТРОКИ В СПИСОК ===
            # Добавляем строки
            all_rows_order_list.append({
                'datetime': format_datetime(firm_order['datetime']),
                'order_num': firm_order["order_num"],
                'option_base': si['base_active_seccode'],
                'ticker': si['sec_code'],
                'option_type': option_type_str,
                'strike': int(si['option_strike']),
                'expdate': formatted_exp_date,
                'operation': "Купля" if buy else "Продажа",
                'volume': order_qty,
                'price': order_price,
                'value': order_qty * order_price,
                'volatility': round(implied_volatility.get_iv_for_option_price(asset_price, option, order_price), 2)
            })

        print(all_rows_order_list) # Список словарей с данными о заявках

        df_order_quik = pd.DataFrame(all_rows_order_list) # Создаем DataFrame с данными о заявках
        print(df_order_quik)



        # Стоп заявки
        firm_stop_orders = [stopOrder for stopOrder in stop_orders if stopOrder['firmid'] == firm_id and stopOrder['flags'] & 0b1 == 0b1]  # Активные стоп заявки по фирме
        for firm_stop_order in firm_stop_orders:  # Пробегаемся по всем стоп заявкам
            buy = firm_stop_order['flags'] & 0b100 != 0b100  # Заявка на покупку
            class_code = firm_stop_order['class_code']  # Код режима торгов
            sec_code = firm_stop_order['sec_code']  # Тикер
            stop_order_price = qp_provider.quik_price_to_price(class_code, sec_code, firm_stop_order['price'])  # Цена срабатывания стоп заявки в рублях за штуку
            si = qp_provider.get_symbol_info(class_code, sec_code)  # Спецификация тикера
            stop_order_qty = firm_stop_order['qty'] * si['lot_size']  # Кол-во в штуках
            logger.info(f'- Стоп заявка номер {firm_stop_order["order_num"]} {"Покупка" if buy else "Продажа"} {class_code}.{sec_code} {stop_order_qty} @ {stop_order_price}')
        i += 1  # Переходим к следующей учетной записи

    # Подписки
    # qp_provider.on_trade = lambda data: logger.info(data)  # Обработчик получения сделки
    # logger.info(f'Подписка на мои сделки {class_code}.{sec_code}')
    # qp_provider.on_order = lambda data: logger.info(data)  # Обработчик получения сделки
    # logger.info(f'Подписка на мои заявки {class_code}.{sec_code}')
    qp_provider.on_order.subscribe(_on_order)  # Подписываемся на зявки
    qp_provider.on_trade.subscribe(_on_trade)  # Подписываемся на сделки
    # # sleep_sec = 10  # Кол-во секунд получения сделок
    # # logger.info(f'Секунд моих сделок: {sleep_sec}')
    # # time.sleep(sleep_sec)  # Ждем кол-во секунд получения сделок
    # # logger.info(f'Отмена подписки на сделки')
    # # qp_provider.on_all_trade = qp_provider.default_handler  # Возвращаем обработчик по умолчанию
    #
    # time.sleep(10)  # Ждем 10 секунд
    #
    # Выход
    input('Enter - выход\n')
    qp_provider.on_order.unsubscribe(_on_order)  # Отменяем подписку на зявки
    qp_provider.on_trade.unsubscribe(_on_trade)  # Отменяем подписку на сделки
    qp_provider.close_connection_and_thread()  # Перед выходом закрываем соединение для запросов и поток обработки функций обратного вызова
