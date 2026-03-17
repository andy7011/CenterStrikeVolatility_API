# test_vars.py
import sys
sys.path.append('.')

# Импортируем переменные
from DashBoardOptionsVolatility_v1_16 import dataname_buy, dataname_sell, expected_profit, Lot_count, Basket_size, Timeout, running

print("Переменные из DashBoardOptionsVolatility_v1_16:")
print(f"dataname_buy: {dataname_buy}")
print(f"dataname_sell: {dataname_sell}")
print(f"expected_profit: {expected_profit}")
print(f"Lot_count: {Lot_count}")
print(f"Basket_size: {Basket_size}")
print(f"Timeout: {Timeout}")
print(f"running: {running}")
