# -*- coding: utf-8 -*-
"""
Разовый скрипт миграции CSV-файлов сделок в новую структуру словаря trades.

Старый формат:  trade_id;symbol;price;size;side;timestamp;order_id;account_id;comment;accrued_interest;currency;trade_iv
Новый формат:   datetime;trade_id;order_id;option_base;ticker;option_type;strike;expdate;operation;volume;price;value;volatility

Требуется доступ к Finam API и MOEX API (для обогащения данных из options_chains).
Оригиналы файлов сохраняются в <имя>.migrate_backup
"""
import os
import sys
import csv
import logging
from datetime import datetime

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger("migrate")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data", "Finam")
FILES = ["Finam_Stream_Trades.csv", "Finam_Stream_Trades_ALL.csv"]

NEW_HEADERS = [
    "datetime",
    "trade_id",
    "order_id",
    "option_base",
    "ticker",
    "option_type",
    "strike",
    "expdate",
    "operation",
    "volume",
    "price",
    "value",
    "volatility",
]


def to_float(v):
    """Преобразование Decimal-поля protobuf (есть атрибут .value) в float."""
    if v is not None and hasattr(v, "value") and v.value:
        try:
            return float(v.value)
        except (TypeError, ValueError):
            return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def fmt_ru_datetime(value):
    """YYYY-MM-DD HH:MM:SS -> DD.MM.YYYY HH:MM:SS."""
    if not value:
        return ""
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").strftime(
            "%d.%m.%Y %H:%M:%S"
        )
    except (ValueError, TypeError):
        return value


def fmt_ru_date(value):
    """YYYY-MM-DD -> DD.MM.YYYY."""
    if not value:
        return ""
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d.%m.%Y")
    except (ValueError, TypeError):
        return value


def build_base_root_map(chain_map):
    """{префикс опционного символа: базовый актив} — из данных цепочек, с фолбэком на MAP."""
    from app.supported_base_asset import MAP

    roots = {}
    for sym, info in chain_map.items():
        s = sym.split("@")[0]
        letters = ""
        for c in s:
            if c.isalpha():
                letters += c
            else:
                break
        if letters:
            roots.setdefault(letters, info.get("base_ticker", ""))
    for t in MAP:
        prefix = ""
        for c in t:
            if c.isalpha():
                prefix += c
            else:
                break
        if prefix:
            roots.setdefault(prefix, t)
    return roots


def base_of_symbol(symbol, root_map):
    """Пытается определить базовый актив по префиксу опционного символа."""
    s = symbol.split("@")[0] if symbol else ""
    letters = ""
    for c in s:
        if c.isalpha():
            letters += c
        else:
            break
    return root_map.get(letters, "")


def fmt_num(value, decimals=2):
    if value is None or value == "":
        return ""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    if num == int(num):
        return str(int(num))
    return f"{num:.{decimals}f}"


def build_chain_map(provider):
    """Загружает все цепочки опционов и возвращает {symbol: info} без фильтра по страйкам."""
    from FinamPy.grpc import assets_service_pb2 as assets_service
    from moex_api import get_option_expirations
    from app.supported_base_asset import MAP
    from datetime import datetime

    chain_map = {}
    for ticker in MAP:
        try:
            expirations = get_option_expirations(ticker)
            exp_dates = sorted(set(e["expiration_date"] for e in expirations))
        except Exception as e:
            logger.error("Ошибка получения экспираций %s: %s", ticker, e)
            continue

        dataname = f"SPBFUT.{ticker}"
        finam_board, ticker_code = provider.dataname_to_finam_board_ticker(dataname)
        mic = provider.get_mic(finam_board, ticker_code)
        underlying_symbol = f"{ticker_code}@{mic}"

        for exp_date_str in exp_dates:
            d = datetime.strptime(exp_date_str, "%Y-%m-%d").date()
            request = assets_service.OptionsChainRequest(
                underlying_symbol=underlying_symbol,
                expiration_date={"year": d.year, "month": d.month, "day": d.day},
            )
            try:
                response = provider.call_function(
                    provider.assets_stub.OptionsChain, request
                )
            except Exception as e:
                logger.error("Ошибка цепочки %s %s: %s", underlying_symbol, exp_date_str, e)
                continue
            if response is None:
                continue
            for opt in response.options:
                try:
                    opt_type = assets_service.Option.Type.Name(opt.type)
                except ValueError:
                    opt_type = str(opt.type)
                exp = opt.expiration_last_day
                chain_map[opt.symbol] = {
                    "base_ticker": ticker,
                    "type": opt_type,
                    "strike": to_float(opt.strike),
                    "expiration_last_day": (
                        f"{exp.year:04d}-{exp.month:02d}-{exp.day:02d}" if exp else ""
                    ),
                }
        logger.info("Загружена цепочка %s (всего опционов: %s)", ticker, len(chain_map))
    return chain_map


def convert_row(row, chain_map, root_map):
    symbol = (row.get("symbol") or "").strip()
    ticker = symbol.split("@")[0] if symbol else ""
    info = chain_map.get(symbol) or {}

    side = row.get("side", "")
    side_upper = side.upper()
    if "BUY" in side_upper or side == "1":
        operation = "Купля"
    elif "SELL" in side_upper or side == "2":
        operation = "Продажа"
    else:
        operation = side

    size = to_float(row.get("size", ""))
    price = to_float(row.get("price", ""))

    opt_type_raw = info.get("type", "")
    if "PUT" in opt_type_raw.upper():
        opt_type = "Put"
    elif "CALL" in opt_type_raw.upper():
        opt_type = "Call"
    else:
        opt_type = ""

    return {
        "datetime": fmt_ru_datetime(row.get("timestamp", "")),
        "trade_id": row.get("trade_id", ""),
        "order_id": row.get("order_id", ""),
        "option_base": info.get("base_ticker", "") or base_of_symbol(symbol, root_map),
        "ticker": ticker,
        "option_type": opt_type,
        "strike": info.get("strike", ""),
        "expdate": fmt_ru_date(info.get("expiration_last_day", "")),
        "operation": operation,
        "volume": size,
        "price": price,
        "value": price * size,
        "volatility": row.get("trade_iv", ""),
    }


def migrate_file(path, chain_map, root_map):
    if not os.path.exists(path):
        logger.warning("Файл не найден, пропускаю: %s", path)
        return

    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        headers = reader.fieldnames or []
        rows = list(reader)

    if "symbol" not in headers:
        logger.info("Файл уже в новом формате (нет колонки symbol), пропускаю: %s", path)
        return

    logger.info("Мигрирую %s: %s записей", os.path.basename(path), len(rows))
    converted = [convert_row(r, chain_map, root_map) for r in rows]

    backup = path + ".migrate_backup"
    with open(path, "r", encoding="utf-8") as src, open(backup, "w", encoding="utf-8") as dst:
        dst.write(src.read())
    logger.info("Бэкап сохранён: %s", backup)

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=NEW_HEADERS, delimiter=";")
        writer.writeheader()
        for r in converted:
            writer.writerow(
                {
                    k: ("" if v is None else (fmt_num(v) if k in {"strike", "volume", "price", "value", "volatility"} else v))
                    for k, v in r.items()
                }
            )
    logger.info("Готово: %s (%s записей)", path, len(converted))


def main():
    sys.path.insert(0, BASE_DIR)
    from FinamPy.FinamPy import FinamPy

    logger.info("Подключаюсь к Finam API...")
    provider = FinamPy()
    if not provider.account_ids:
        provider.account_ids = list(provider.token_details().account_ids)
    if not provider.account_ids:
        logger.error("Не найдено торговых счетов. Выход.")
        return
    logger.info("Аккаунт: %s", provider.account_ids[0])

    chain_map = build_chain_map(provider)
    logger.info("Всего опционов в карте: %s", len(chain_map))
    root_map = build_base_root_map(chain_map)
    logger.info("Базовые префиксы: %s", root_map)

    os.makedirs(DATA_DIR, exist_ok=True)
    for fn in FILES:
        migrate_file(os.path.join(DATA_DIR, fn), chain_map, root_map)

    logger.info("Миграция завершена.")


if __name__ == "__main__":
    main()
