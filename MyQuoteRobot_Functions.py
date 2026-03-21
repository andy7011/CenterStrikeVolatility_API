from FinLabPy.Config import brokers, default_broker  # Все брокеры и брокер по умолчанию
from QUIK_Stream_v1_7 import calculate_open_data_open_price_open_iv
import math
import numpy as np
from datetime import datetime, timezone  # Дата и время
from time import sleep  # Задержка в секундах перед выполнением операций
from scipy.stats import norm
from google.type.decimal_pb2 import Decimal

# Глобальные переменные
CALL = 'C'
PUT = 'P'
r = 0  # Безрисковая ставка
global dataname_sell, dataname_buy
dataname_sell = ''
dataname_buy = ''


# Получение позиций по инструментам портфеля проданным и купленным
def get_position_finam():
    SELL = {}
    BUY = {}
    for position in default_broker.get_positions():  # Пробегаемся по всем позициям брокера
        # print(f'  - {position.dataname} {position.quantity}')
        # Получаем dataname и quantity, сохраняем в словарь SELL dataname отрицательных позиций quantity, в словарь BUY - с положительными позициями
        if position.dataname.startswith('SPBOPT.') and position.quantity > 0:
            SELL[position.dataname] = position.quantity
        elif position.dataname.startswith('SPBOPT.') and position.quantity < 0:
            BUY[position.dataname] = position.quantity
        elif position.dataname.startswith('SPBOPT.') and position.quantity == 0:
            # Можно добавить обработку нулевых позиций, если нужно
            pass
    # print(f'SELL: {SELL}')
    # print(f'BUY: {BUY}')
    default_broker.close()  # Закрываем брокера
    return SELL, BUY

# Получаем данные по опционам, сохраняем в словарь
opions_data = {}

def get_opion_data_alor(dataname):
    alor_board, symbol = ap_provider.dataname_to_alor_board_symbol(dataname)  # Код режима торгов Алора и код и тикер
    exchange = ap_provider.get_exchange(alor_board, symbol)  # Код биржи
    si = ap_provider.get_symbol_info(exchange, symbol)  # Получаем информацию о тикере
    # print(si)
    # Создаем словарь для опциона
    opions_data[dataname] = {
        'ticker': si['shortname'],
        'theorPrice': si['theorPrice'],
        'volatility': float(si['volatility']),
        'strikePrice': float(si['strikePrice']),
        'endExpiration': si['endExpiration'],
        'base_asset_ticker': si['underlyingSymbol'],
        'optionSide': si['optionSide'],
        'lot_size': si['lotsize'],
        'minstep': si['minstep'],
        'decimals': si['decimals']
    }
    # print(f'opions_data {opions_data}')
    guid = ap_provider.quotes_subscribe(exchange, symbol)  # Получаем код подписки
    guids.append(guid)
    logger.info(f'Подписка на котировки {guid} тикера {dataname} создана')
    return opions_data

# Сбор данных по опциону и БА для расчета цены опциона
def get_option_data_for_calc_price(dataname):
    base_asset_ticker = opions_data[dataname]['base_asset_ticker']
    S = float(new_quotes[base_asset_ticker]['last_price'])
    K = float(opions_data[dataname]['strikePrice'])
    expiration_datetime = opions_data[dataname]['endExpiration']
    expiration_dt = datetime.fromisoformat(expiration_datetime.replace('Z', '+00:00'))
    T_razн = (expiration_dt - datetime.today()).days
    T = float((T_razн + 1.151) / 365)
    opt_type = CALL if opions_data[dataname]['optionSide'] == 'Call' else PUT
    # print(f'S: {S}, K: {K}, T: {T}, opt_type: {opt_type}')
    return S, K, T, opt_type


# Вычисление стоимости опциона по формуле Black-Scholes
def option_price(S, sigma, K, T, r: float, opt_type):
    d1 = (math.log(S / K) + (r + .5 * sigma ** 2) * T) / (sigma * T ** .5)
    d2 = d1 - sigma * T ** 0.5
    price = 0
    if opt_type == CALL:
        n1 = norm.cdf(d1)
        n2 = norm.cdf(d2)
        DF = math.exp(-r * T)
        price = S * n1 - K * DF * n2
    elif opt_type == PUT:
        n1 = norm.cdf(-d1)
        n2 = norm.cdf(-d2)
        DF = math.exp(-r * T)
        price = K * DF * n2 - S * n1
    return price


# Сбор данных опциона CALL для расчета IV
def option_data_for_IV_calculation_call(dataname, price_call):
    # S: последняя цена БА из обновляемого словаря new_quotes
    # K: strike price
    # T: time to maturity
    # C: Call value
    # r: interest rate
    # sigma: volatility of underlying asset
    base_asset_ticker = opions_data[dataname]['base_asset_ticker']
    S = float(new_quotes[base_asset_ticker]['last_price'])
    K = float(opions_data[dataname]['strikePrice'])
    expiration_datetime = opions_data[dataname]['endExpiration']
    expiration_dt = datetime.fromisoformat(expiration_datetime.replace('Z', '+00:00'))
    T_razн = (expiration_dt - datetime.today()).days
    T = float((T_razн + 1.151) / 365)
    C = price_call
    sigma = opions_data[dataname]['volatility'] / 100
    return S, K, T, C, sigma


# Сбор данных опциона PUT для расчета IV
def option_data_for_IV_calculation_put(dataname, price_put):
    # S: последняя цена БА из обновляемого словаря new_quotes
    # K: strike price
    # T: time to maturity
    # P: Put value
    # r: interest rate
    # sigma: volatility of underlying asset
    base_asset_ticker = opions_data[dataname]['base_asset_ticker']
    S = float(new_quotes[base_asset_ticker]['last_price'])
    K = float(opions_data[dataname]['strikePrice'])
    expiration_datetime = opions_data[dataname]['endExpiration']
    expiration_dt = datetime.fromisoformat(expiration_datetime.replace('Z', '+00:00'))
    T_razн = (expiration_dt - datetime.today()).days
    T = float((T_razн + 1.151) / 365)
    P = price_put
    sigma = opions_data[dataname]['volatility'] / 100
    return S, K, T, P, sigma


# Расчет IV Метод Ньютона для опциона CALL
def newton_vol_call(S, K, T, C, r, sigma):
    # S: spot price
    # K: strike price
    # T: time to maturity
    # C: Call value
    # r: interest rate
    # sigma: volatility of underlying asset

    tolerance = 0.000001
    max_iterations = 100
    x0 = sigma
    xnew = x0
    xold = x0 - 1
    iteration = 0

    while abs(xnew - xold) > tolerance and iteration < max_iterations:
        # Функция Black-Scholes для CALL
        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * T ** 0.5)
        d2 = d1 - sigma * T ** 0.5
        n1 = norm.cdf(d1)
        n2 = norm.cdf(d2)
        DF = math.exp(-r * T)
        price = S * n1 - K * DF * n2

        # Частная производная от цены по волатильности (vega)
        vega = S * norm.pdf(d1) * T ** 0.5

        # Метод Ньютона
        xold = xnew
        xnew = xold - (price - C) / vega

        iteration += 1

    return xnew if iteration < max_iterations else x0


# Расчет IV Метод Ньютона для опциона PUT
def newton_vol_put(S, K, T, P, r, sigma):
    # S: spot price
    # K: strike price
    # T: time to maturity
    # P: Put value
    # r: interest rate
    # sigma: volatility of underlying asset

    tolerance = 0.000001
    max_iterations = 100
    x0 = sigma
    xnew = x0
    xold = x0 - 1
    iteration = 0

    while abs(xnew - xold) > tolerance and iteration < max_iterations:
        # Функция Black-Scholes для PUT
        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * T ** 0.5)
        d2 = d1 - sigma * T ** 0.5
        n1 = norm.cdf(-d1)
        n2 = norm.cdf(-d2)
        DF = math.exp(-r * T)
        price = K * DF * n2 - S * n1

        # Частная производная от цены по волатильности (vega)
        vega = S * norm.pdf(d1) * T ** 0.5

        # Метод Ньютона
        xold = xnew
        xnew = xold - (price - P) / vega

        iteration += 1

    return xnew if iteration < max_iterations else x0

