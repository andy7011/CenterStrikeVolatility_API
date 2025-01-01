# Страйки могут быть нецелочисленными. Для консистентности списка страйков в
# модели и в API следует вычислять их с округлением до явно указанного количества знаков после запятой
_PRECISION_DIGITS_COUNT = 5


# Формируем список страйков с учетом заданного количества страйков, шага цены страйка и центрального страйка
def get_list_of_strikes(base_asset_price, strike_step, strikes_count):
    central_strike = _calculate_central_strike(base_asset_price, strike_step)
    strikes_before_count = strikes_count // 2
    first_strike = _round_strike(central_strike - strikes_before_count * strike_step)
    strikes = []
    for i in range(strikes_count):
        strikes.append(_round_strike(first_strike + i * strike_step))

    return strikes


# Центральный страйк - наиболее близкий к цене базового актива с учётом заданного шага цены страйков
def _calculate_central_strike(base_asset_price, strike_step):
    return _round_strike(round(base_asset_price / strike_step) * strike_step)


def _round_strike(value):
    return round(value, ndigits=_PRECISION_DIGITS_COUNT)
