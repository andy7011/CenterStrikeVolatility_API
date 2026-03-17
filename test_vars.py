import sys
sys.path.append('.')

def get_current_config():
    # Импортируем актуальные значения
    from DashBoardOptionsVolatility_v1_16 import dataname_buy, dataname_sell, expected_profit, Lot_count, Basket_size, Timeout, running
    return {
        'dataname_buy': dataname_buy,
        'dataname_sell': dataname_sell,
        'expected_profit': expected_profit,
        'Lot_count': Lot_count,
        'Basket_size': Basket_size,
        'Timeout': Timeout,
        'running': running
    }

# Используйте эту функцию для получения текущих значений
config = get_current_config()
print("Текущие значения:")
for key, value in config.items():
    print(f"{key}: {value}")