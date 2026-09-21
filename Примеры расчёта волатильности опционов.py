"""
Для вашей задачи с опционами на MOEX лучше использовать формулы для фьючерсов (модель Блэка):
Для российского рынка часто используют модель Блэка-76 для опционов на фьючерсы.
Волатильность обычно выражается в процентах, поэтому при передаче в формулы нужно делить на 100.
Время T нужно вычислять как количество дней до экспирации / 365 (или / 252 для рабочих дней).
"""
def black_76_price(F, K, T, r, sigma, option_type='call'):
    """
    Модель Блэка-76 для опционов на фьючерсы
    F - цена фьючерса
    """
    d1 = (math.log(F / K) + 0.5 * sigma ** 2 * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    if option_type == 'call':
        price = math.exp(-r * T) * (F * norm.cdf(d1) - K * norm.cdf(d2))
    else:
        price = math.exp(-r * T) * (K * norm.cdf(-d2) - F * norm.cdf(-d1))

    return price

"""
Вот как использовать модель Black-76 для обратной задачи - вычисления имплицитной волатильности:
1. Простая реализация с бисекцией
"""
import math
from scipy.stats import norm


def black_76_price(F, K, T, r, sigma, option_type='call'):
    """Цена опциона по модели Блэка-76 (для опционов на фьючерсы)"""
    if sigma <= 0:
        return 0.0  # или raise ValueError

    d1 = (math.log(F / K) + 0.5 * sigma ** 2 * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    if option_type == 'call':
        price = math.exp(-r * T) * (F * norm.cdf(d1) - K * norm.cdf(d2))
    else:
        price = math.exp(-r * T) * (K * norm.cdf(-d2) - F * norm.cdf(-d1))

    return price


def implied_volatility_bisection(market_price, F, K, T, r, option_type='call',
                                 low=0.001, high=5.0, tolerance=1e-6):
    """
    Вычисление имплицитной волатильности методом бисекции

    Параметры:
    market_price - рыночная цена опциона
    F - цена фьючерса
    K - страйк
    T - время до экспирации (в годах)
    r - безрисковая ставка
    option_type - 'call' или 'put'
    low, high - границы поиска волатильности
    tolerance - точность
    """
    # Проверка на экстремальные случаи
    intrinsic_value = max(0, F - K) if option_type == 'call' else max(0, K - F)
    if market_price < intrinsic_value * math.exp(-r * T):
        return None  # Цена ниже внутренней стоимости - ошибка

    for _ in range(100):  # Максимум 100 итераций
        mid = (low + high) / 2
        price_mid = black_76_price(F, K, T, r, mid, option_type)

        if abs(price_mid - market_price) < tolerance:
            return mid

        if price_mid < market_price:
            low = mid
        else:
            high = mid

    return (low + high) / 2


# Пример использования
F = 35000  # Цена фьючерса
K = 35000  # Страйк
T = 0.25  # 3 месяца до экспирации
r = 0.10  # 10% безрисковая ставка
option_type = 'call'

# Рыночная цена (например, из стакана)
market_price = 1500

iv = implied_volatility_bisection(market_price, F, K, T, r, option_type)
print(f"Имплицитная волатильность: {iv:.4f} = {iv * 100:.2f}%")

# Проверка: пересчитываем цену с найденной волатильностью
calculated_price = black_76_price(F, K, T, r, iv, option_type)
print(f"Проверка цены: {calculated_price:.2f} (рыночная: {market_price:.2f})")


"""
2. Более эффективная реализация с Newton-Raphson
"""
from scipy.optimize import brentq, newton


def implied_volatility_newton(market_price, F, K, T, r, option_type='call',
                              initial_guess=0.2, tolerance=1e-8):
    """
    Вычисление имплицитной волатильности методом Ньютона
    Более быстрый, но требует хорошего начального приближения
    """

    def price_difference(sigma):
        return black_76_price(F, K, T, r, sigma, option_type) - market_price

    try:
        iv = newton(price_difference, initial_guess, tol=tolerance, maxiter=100)
        return iv
    except RuntimeError:
        # Если метод Ньютона не сходится, используем бисекцию
        return implied_volatility_bisection(market_price, F, K, T, r, option_type)


# Пример использования
iv_newton = implied_volatility_newton(1500, 35000, 35000, 0.25, 0.10, 'call')
print(f"IV методом Ньютона: {iv_newton:.6f} = {iv_newton * 100:.2f}%")


"""
3. Реализация с scipy.optimize.brentq (рекомендуется)
"""


def implied_volatility_brentq(market_price, F, K, T, r, option_type='call'):
    """
    Вычисление имплицитной волатильности методом Брента
    Самый надежный встроенный метод
    """

    def price_difference(sigma):
        return black_76_price(F, K, T, r, sigma, option_type) - market_price

    try:
        iv = brentq(price_difference, 0.001, 5.0)
        return iv
    except ValueError:
        # Если нет корня в диапазоне, пробуем расширить
        try:
            iv = brentq(price_difference, 0.0001, 10.0)
            return iv
        except ValueError:
            return None  # Волатильность вне разумных пределов


# Пример использования
iv_brentq = implied_volatility_brentq(1500, 35000, 35000, 0.25, 0.10, 'call')
print(f"IV методом Брента: {iv_brentq:.6f} = {iv_brentq * 100:.2f}%")


"""
4. Полная функция для вашего проекта
Учитывая ваш контекст (торговля опционами на MOEX), вот полная функция, которую можно использовать:
"""


def calculate_implied_volatility(market_price, futures_price, strike, days_to_expiry,
                                 risk_free_rate=0.10, option_type='call'):
    """
    Полная функция вычисления имплицитной волатильности для опционов на MOEX

    Параметры:
    market_price - рыночная цена опциона
    futures_price - цена фьючерса
    strike - страйк опциона
    days_to_expiry - количество дней до экспирации
    risk_free_rate - безрисковая ставка (например, 0.10 для 10%)
    option_type - 'call' или 'put'

    Возвращает:
    Имплицитная волатильность в процентах (например, 25.5 для 25.5%)
    """
    T = days_to_expiry / 365.0  # Переводим дни в годы

    # Проверка корректности входных данных
    if market_price <= 0 or futures_price <= 0 or strike <= 0 or T <= 0:
        print(f"Ошибка: недопустимые входные данные: market={market_price}, "
              f"futures={futures_price}, strike={strike}, T={T}")
        return None

    # Внутренняя стоимость опциона
    if option_type == 'call':
        intrinsic = max(0, futures_price - strike)
    else:
        intrinsic = max(0, strike - futures_price)

    # Проверка: цена опциона должна быть >= внутренней стоимости
    if market_price < intrinsic:
        print(f"Предупреждение: цена опциона ({market_price}) ниже внутренней стоимости ({intrinsic})")
        return None

    def price_difference(sigma):
        try:
            price = black_76_price(futures_price, strike, T, risk_free_rate, sigma, option_type)
            return price - market_price
        except:
            return float('inf')

    try:
        # Используем brentq для нахождения корня
        iv = brentq(price_difference, 0.001, 5.0)
        return iv * 100  # Возвращаем в процентах
    except ValueError:
        # Пробуем расширенный диапазон
        try:
            iv = brentq(price_difference, 0.0001, 10.0)
            return iv * 100
        except:
            print(f"Не удалось найти волатильность для {option_type} K={strike}")
            return None


# Пример использования с реальными данными
if __name__ == "__main__":
    # Пример для опциона на фьючерс RTS
    market_price = 1450  # Рыночная цена опциона
    futures_price = 118000  # Цена фьючерса RTS
    strike = 118000  # Страйк
    days_to_expiry = 45  # 45 дней до экспирации

    iv_call = calculate_implied_volatility(market_price, futures_price, strike,
                                           days_to_expiry, option_type='call')
    print(f"IV для call: {iv_call:.2f}%")

    # Для put
    market_price_put = 1400
    iv_put = calculate_implied_volatility(market_price_put, futures_price, strike,
                                          days_to_expiry, option_type='put')
    print(f"IV для put: {iv_put:.2f}%")


"""
5. Пакетная обработка для нескольких страйков (улыбка волатильности)
"""


def calculate_volatility_smile(futures_price, strikes, market_prices, days_to_expiry,
                               risk_free_rate=0.10):
    """
    Вычисление улыбки волатильности для серии опционов

    Параметры:
    futures_price - цена фьючерса
    strikes - список страйков
    market_prices - словарь {'call': {K: price}, 'put': {K: price}}
    days_to_expiry - дней до экспирации
    """
    volatility_smile = {}

    for option_type in ['call', 'put']:
        volatility_smile[option_type] = {}
        for strike, price in market_prices[option_type].items():
            iv = calculate_implied_volatility(price, futures_price, strike,
                                              days_to_expiry, risk_free_rate, option_type)
            if iv is not None:
                volatility_smile[option_type][strike] = iv

    return volatility_smile


# Пример использования
strikes = [115000, 117000, 118000, 119000, 121000]
market_data = {
    'call': {K: black_76_price(118000, K, 45 / 365, 0.10, 0.25, 'call') for K in strikes},
    'put': {K: black_76_price(118000, K, 45 / 365, 0.10, 0.25, 'put') for K in strikes}
}

smile = calculate_volatility_smile(118000, strikes, market_data, 45)
for option_type in ['call', 'put']:
    print(f"\n{option_type.upper()} опционы:")
    for strike, iv in smile[option_type].items():
        print(f"  Страйк {strike}: IV = {iv:.2f}%")

"""
Важные замечания:
Для MOEX обычно используют именно модель Black-76, так как опционы торгуются на фьючерсы
Время T нужно считать с учетом торгового календаря MOEX
Безрисковая ставка для рублевых опционов обычно берут RUONIA или ключевую ставку ЦБ
Начальный диапазон для волатильности: от 1% до 500% (0.01 - 5.0)
Проверяйте корректность - цена опциона не может быть ниже внутренней стоимости
Для ATM опционов (страйк близок к фьючерсу) метод Ньютона работает лучше всего
Для глубоко ITM/OTM опционов используйте бисекцию или brentq для надежности
"""

"""
для MOEX важно учитывать торговый календарь. Есть несколько подходов:
1. Стандартный подход (365/366 дней)
"""
T = days_to_expiry / 365.0  # Простой подход
"""
Этот подход часто используется, но не совсем точен для MOEX, так как:
Выходные и праздничные дни не учитываются
Опционы на MOEX экспирируются в определенные дни недели
"""

"""
2. Учет торговых дней (рекомендуется для MOEX)
"""
from FinLabPy.Schedule.MOEX import Futures  # У вас уже импортирован этот модуль

def calculate_time_to_expiry(days_to_expiry, use_trading_days=True):
    """
    Вычисление времени до экспирации с учетом торгового календаря MOEX

    Параметры:
    days_to_expiry - количество календарных дней до экспирации
    use_trading_days - если True, используем только торговые дни

    Возвращает:
    T - время в годах для модели Black-76
    """
    if use_trading_days:
        # Для MOEX: ~247 торговых дней в году (не 365)
        trading_days_per_year = 247
        # Приблизительная оценка торговых дней
        # (в неделе 5 торговых дней, но нужно учитывать праздники)
        calendar_days = days_to_expiry
        trading_days = calendar_days * 5 / 7  # Приблизительная оценка
        T = trading_days / trading_days_per_year
    else:
        T = days_to_expiry / 365.0

    return T

"""
3. Точный расчет с торговым календарем MOEX
"""
from datetime import datetime, date
from FinLabPy.Schedule.MOEX import Futures  # Расписание торгов срочного рынка


def calculate_T_moex(expiration_date, current_date=None, use_trading_days=True):
    """
    Точный расчет времени до экспирации с учетом торгового календаря MOEX

    Параметры:
    expiration_date - дата экспирации опциона
    current_date - текущая дата (если None, используется сегодня)
    use_trading_days - если True, используем только торговые дни

    Возвращает:
    T - время в годах для модели Black-76
    """
    if current_date is None:
        current_date = datetime.now().date()

    if isinstance(expiration_date, str):
        expiration_date = datetime.strptime(expiration_date, '%Y-%m-%d').date()

    # Получаем расписание торгов для фьючерсов
    futures_schedule = Futures()

    # Проверяем, является ли дата торговым днем
    def is_trading_day(date):
        # Проверяем по расписанию MOEX
        try:
            # Здесь нужно использовать реальный метод из FinLabPy
            # Например: futures_schedule.get_trading_days()
            return futures_schedule.is_trading_day(date)
        except:
            # Если не удалось определить, считаем будний день
            return date.weekday() < 5  # Пн-Пт

    if use_trading_days:
        # Считаем только торговые дни
        trading_days = 0
        current = current_date
        while current < expiration_date:
            if is_trading_day(current):
                trading_days += 1
            current += timedelta(days=1)

        # ~247 торговых дней в году для MOEX
        T = trading_days / 247.0
    else:
        # Календарные дни
        calendar_days = (expiration_date - current_date).days
        T = calendar_days / 365.0

    print(f"Календарных дней: {(expiration_date - current_date).days}, "
          f"Торговых дней: {trading_days if use_trading_days else 'N/A'}")
    print(f"T = {T:.6f} лет")

    return T

"""
4. Практическая реализация для вашего проекта
Учитывая, что у вас уже есть Futures из FinLabPy, вот более полная реализация:
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo  # Московское время
from FinLabPy.Schedule.MOEX import Futures
import calendar

# Константы для MOEX
MOEX_TRADING_DAYS_PER_YEAR = 247  # Среднее количество торговых дней в году
TRADING_HOURS_PER_DAY = 17  # Основная торговая сессия (7:00 - 23:50 МСК)


class MOEXOptionTimeCalculator:
    """Калькулятор времени для опционов MOEX"""

    def __init__(self):
        self.futures_schedule = Futures()
        self.msk_tz = ZoneInfo('Europe/Moscow')

    def is_moex_trading_day(self, date):
        """
        Проверка, является ли дата торговым днем на MOEX
        """
        # Праздничные дни MOEX (пример, нужно обновлять)
        moex_holidays = [
            '2024-01-01', '2024-01-02', '2024-01-03', '2024-01-04', '2024-01-05',  # Новогодние
            '2024-01-08',  # Рождество
            '2024-03-08',  # 8 марта
            '2024-05-01', '2024-05-09',  # Праздники мая
            '2024-06-12',  # День России
            '2024-11-04',  # День народного единства
        ]

        # Выходные
        if date.weekday() >= 5:  # Суббота (5) и Воскресенье (6)
            return False

        # Праздники
        if date.strftime('%Y-%m-%d') in moex_holidays:
            return False

        # Переносы выходных (нужно обновлять каждый год)
        transferred_days = [
            '2024-04-29', '2024-04-30',  # Перенос с праздников
            '2024-12-30', '2024-12-31',
        ]
        if date.strftime('%Y-%m-%d') in transferred_days:
            return False

        return True

    def trading_days_between(self, start_date, end_date):
        """
        Количество торговых дней между двумя датами
        """
        trading_days = 0
        current = start_date

        while current < end_date:
            if self.is_moex_trading_day(current):
                trading_days += 1
            current += timedelta(days=1)

        return trading_days

    def calculate_T(self, expiration_date, current_date=None,
                    use_trading_days=True, include_current_day=True):
        """
        Расчет T для модели Black-76

        Параметры:
        expiration_date - дата экспирации
        current_date - текущая дата
        use_trading_days - использовать торговые дни
        include_current_day - считать ли текущий день
        """
        if current_date is None:
            current_date = datetime.now(self.msk_tz).date()

        if isinstance(expiration_date, str):
            expiration_date = datetime.strptime(expiration_date, '%Y-%m-%d').date()

        if use_trading_days:
            # Точный подсчет торговых дней
            if include_current_day:
                trading_days = self.trading_days_between(current_date, expiration_date) + 1
            else:
                trading_days = self.trading_days_between(current_date, expiration_date)

            # Конвертируем в годы
            T = trading_days / MOEX_TRADING_DAYS_PER_YEAR

            # Учитываем время текущего дня
            now = datetime.now(self.msk_tz)
            end_of_day = now.replace(hour=23, minute=50, second=0)
            time_fraction = (end_of_day - now).seconds / (14 * 3600)  # Доля оставшегося времени

            T = (trading_days - 1 + time_fraction) / MOEX_TRADING_DAYS_PER_YEAR
        else:
            # Календарные дни
            calendar_days = (expiration_date - current_date).days
            T = calendar_days / 365.0

        return T


# Пример использования
time_calc = MOEXOptionTimeCalculator()

# Опция с экспирацией через 45 календарных дней
exp_date = datetime.now().date() + timedelta(days=45)

T_trading = time_calc.calculate_T(exp_date, use_trading_days=True)
T_calendar = time_calc.calculate_T(exp_date, use_trading_days=False)

print(f"T с учетом торговых дней: {T_trading:.6f}")
print(f"T по календарным дням: {T_calendar:.6f}")
print(f"Разница: {(T_trading - T_calendar) * 100:.2f}%")


"""
5. Упрощенная версия для быстрого использования
"""


def get_T_simple(days_to_expiry, use_trading_days=True):
    """
    Упрощенный расчет T

    days_to_expiry - календарных дней до экспирации
    """
    if use_trading_days:
        # Приблизительно: 5/7 дней являются торговыми
        estimated_trading_days = days_to_expiry * 5 / 7
        T = estimated_trading_days / 247
    else:
        T = days_to_expiry / 365

    return T


# Сравнение подходов для 45 дней
days = 45
print(f"Календарный подход: T = {days / 365:.6f}")
print(f"Торговые дни (приблизительно): T = {days * 5 / 7 / 247:.6f}")
# Разница ~20-25%!

"""
Рекомендации:
Для большинства расчетов используйте торговые дни (use_trading_days=True), это более точно для MOEX
Для быстрой оценки можно использовать приблизительный коэффициент 5/7
Для точных расчетов нужно иметь календарь торговых дней MOEX на текущий год
Время T влияет значительно - разница между календарным и торговым подходом может составлять 20-30%
В модели Black-76 для MOEX чаще используют ~247 торговых дней в году
В вашем коде вы можете добавить эту логику в функцию расчета волатильности:
"""


def calculate_implied_volatility_moex(market_price, futures_price, strike,
                                      expiration_date, current_date=None,
                                      use_trading_days=True):
    """Расчет IV с учетом торгового календаря MOEX"""

    # Вычисляем T с учетом торговых дней
    time_calc = MOEXOptionTimeCalculator()
    T = time_calc.calculate_T(expiration_date, current_date, use_trading_days)

    # Используем стандартную функцию black_76_price с полученным T
    return implied_volatility(market_price, futures_price, strike, T)
"""
Это позволит получать более точные значения волатильности для опционов на MOEX!
"""