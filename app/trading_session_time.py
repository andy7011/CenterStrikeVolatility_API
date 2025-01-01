from datetime import datetime, time

from model import option_series_type

# For reference see https://www.moex.com/ru/derivatives/

_DAILY_SESSION_START_TIME_UTC = time(6, 0)     # 9:00 in MSK
_EVENING_SESSION_START_TIME_UTC = time(16, 5)  # 19:05 in MSK
_EVENING_SESSION_END_TIME_UTC = time(20, 50)   # 23:50 in MSK


_DEFAULT_OPTION_EXPIRATION_TIME_UTC = time(15, 50)          # 18:50 in MSK
_CURRENCY_QUARTER_OPTION_EXPIRATION_TIME_UTC = time(11, 0)  # 14:00 in MSK


def is_trading_session_active_now() -> bool:
    now = datetime.utcnow()
    return _is_datetime_in_today_daily_session(now) or _is_datetime_in_today_evening_session(now)


def is_datetime_in_current_trading_session(datetime_to_check: datetime) -> bool:
    now = datetime.utcnow()
    is_in_daily_session = _is_datetime_in_today_daily_session(now) and _is_datetime_in_today_daily_session(datetime_to_check)
    is_in_evening_session = _is_datetime_in_today_evening_session(now) and _is_datetime_in_today_evening_session(datetime_to_check)
    return is_in_daily_session or is_in_evening_session


def get_option_expiration_datetime(base_asset_code: str, series_type: str, expiration_date_str: str):
    expiration_date = datetime.fromisoformat(expiration_date_str)

    expiration_datetime = datetime.combine(expiration_date, _DEFAULT_OPTION_EXPIRATION_TIME_UTC)
    currency_base_asset_codes = ('Si', 'Eu', 'Cn')
    if base_asset_code in currency_base_asset_codes and series_type == option_series_type.QUARTER:
        expiration_datetime = datetime.combine(expiration_date, _CURRENCY_QUARTER_OPTION_EXPIRATION_TIME_UTC)

    return expiration_datetime


def _get_today_datetime(time_position: time) -> datetime:
    current_date = datetime.today().date()
    return datetime.combine(current_date, time_position)


def _get_today_daily_session_start_datetime() -> datetime:
    return _get_today_datetime(_DAILY_SESSION_START_TIME_UTC)


def _get_today_evening_session_start_datetime() -> datetime:
    return _get_today_datetime(_EVENING_SESSION_START_TIME_UTC)


def _get_today_evening_session_end_datetime() -> datetime:
    return _get_today_datetime(_EVENING_SESSION_END_TIME_UTC)


def _is_datetime_in_today_daily_session(dtime: datetime) -> bool:
    daily_session_start_datetime = _get_today_daily_session_start_datetime()
    evening_session_start_datetime = _get_today_evening_session_start_datetime()
    return daily_session_start_datetime < dtime < evening_session_start_datetime


def _is_datetime_in_today_evening_session(dtime: datetime) -> bool:
    evening_session_start_datetime = _get_today_evening_session_start_datetime()
    evening_session_end_datetime = _get_today_evening_session_end_datetime()
    return evening_session_start_datetime < dtime < evening_session_end_datetime


