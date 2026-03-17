# Исходные данные
dataname_buy = 'RI95000BO6'  # Option BUY Si78000BO6
stop_iv_buy = 0  # Стоп iv покупки (если 0, то стопом будет теоретическая цена QUIK)

dataname_sell = 'RI120000BC6'  # Option SELL
stop_iv_sell = 0  # Стоп iv продажи (если 0, то стопом будет теоретическая цена QUIK)

expected_profit = 3.0 # Ожидаемый profit в %

Lot_count = 5 # Количество лотов
Basket_size = 1 # Размер лота

Timeout = 8 # Срок действия ордера в секундах

running = False