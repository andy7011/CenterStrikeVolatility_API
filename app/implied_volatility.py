import math
import numpy as np
from scipy.stats import norm

from model import option_type
from model.option import Option

_RISK_FREE_INTEREST_RATE = 0  # risk-free interest rate
_VOLATILITY_CALCULATION_ITERATIONS_LIMIT = 100


def get_iv_for_option_price(asset_price: int, option: Option, opt_price: int):
    strike_price = option.strike
    for param in (asset_price, strike_price, opt_price, option.type):
        if param is None:
            return None

    time_to_maturity = option.get_time_to_maturity()

    tolerance = 10 ** -8
    try:
        iv = _implied_vol(opt_price, asset_price, strike_price, _RISK_FREE_INTEREST_RATE, time_to_maturity, tolerance, option.type)
    except ZeroDivisionError:
        iv = None

    if not iv or math.isinf(iv) or math.isnan(iv):
        return None
    return iv * 100


def _implied_vol(C, S, K, r, T, tol, opt_type=option_type.CALL):
    x0 = _inflexion_point(S, K, T, r)
    p = _option_price(S, x0, K, T, r, opt_type)
    v = _vega(S, x0, K, T, r, opt_type)
    if not v:
        return None

    # infinite loop is possible here, so we count iterations
    i = 0
    while abs((p - C) / v) > tol and i < _VOLATILITY_CALCULATION_ITERATIONS_LIMIT:
        i += 1
        x0 = x0 - (p - C) / v
        p = _option_price(S, x0, K, T, r, opt_type)
        v = _vega(S, x0, K, T, r, opt_type)
        if not v:
            return None

    if i >= _VOLATILITY_CALCULATION_ITERATIONS_LIMIT:
        return None

    return x0


def _inflexion_point(S, K, T, r):
    m = S / (K * math.exp(-r * T))
    return math.sqrt(2 * np.abs(math.log(m)) / T)


def _option_price(S, sigma, K, T, r, opt_type=option_type.CALL):
    d1 = (math.log(S / K) + (r + .5 * sigma ** 2) * T) / (sigma * T ** .5)
    d2 = d1 - sigma * T ** 0.5
    price = 0
    if opt_type == option_type.CALL:
        n1 = norm.cdf(d1)
        n2 = norm.cdf(d2)
        DF = math.exp(-r * T)
        price = S * n1 - K * DF * n2
    elif opt_type == option_type.PUT:
        n1 = norm.cdf(-d1)
        n2 = norm.cdf(-d2)
        DF = math.exp(-r * T)
        price = K * DF * n2 - S * n1
    return price


def _vega(S, sigma, K, T, r, opt_type=option_type.CALL):
    d1 = (math.log(S / K) + (r + .5 * sigma ** 2) * T) / (sigma * T ** .5)
    v = 0
    if opt_type == option_type.CALL:
        v = S * T ** 0.5 * norm.pdf(d1)
    elif opt_type == option_type.PUT:
        v = S * T ** 0.5 * norm.pdf(-d1)
    return v



