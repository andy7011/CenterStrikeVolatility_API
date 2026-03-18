import math
import numpy as np
from scipy.stats import norm

CALL = 'C'
PUT = 'P'
r = 0 # Безрисковая ставка

# Сбор данных по опциону и БА для расчета цены опциона
def get_option_data_for_calc_price(dataname):
    base_asset_ticker = opions_data[dataname]['base_asset_ticker']
    S = float(new_quotes[base_asset_ticker]['last_price'])
    K = float(opions_data[dataname]['strikePrice'])
    expiration_datetime = opions_data[dataname]['endExpiration']
    expiration_dt = datetime.fromisoformat(expiration_datetime.replace('Z', '+00:00'))
    T_razn = (expiration_dt - datetime.today()).days
    T = float((T_razn + 1.151) / 365)
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
    T_razn = (expiration_dt - datetime.today()).days
    T = float((T_razn + 1.151) / 365)
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
    T_razn = (expiration_dt - datetime.today()).days
    T = float((T_razn + 1.151) / 365)
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
        xold = xnew
        d1 = (np.log(S / K) + (r - 0.5 * xnew ** 2) * T) / (xnew * np.sqrt(T))
        d2 = d1 - xnew * np.sqrt(T)
        fx = S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2) - C
        vega = S * np.sqrt(T) * np.exp(-0.5 * d1 ** 2) / np.sqrt(2 * np.pi)
        if abs(vega) < 1e-10:  # Избегаем деления на ноль
            break
        xnew = xnew - fx / vega
        iteration += 1
    return abs(xnew)

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
        xold = xnew
        d1 = (np.log(S / K) + (r - 0.5 * xnew ** 2) * T) / (xnew * np.sqrt(T))
        d2 = d1 - xnew * np.sqrt(T)
        fx = K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1) - P
        vega = S * np.sqrt(T) * np.exp(-0.5 * d1 ** 2) / np.sqrt(2 * np.pi)
        if abs(vega) < 1e-10:  # Избегаем деления на ноль
            break
        xnew = xnew - fx / vega
        iteration += 1
    return abs(xnew)