from AlorPy import AlorPy

# Создаем экземпляр
ap_provider = AlorPy()

# Получаем котировки для конкретного тикера
quotes = ap_provider.get_quotes('MOEX:RI97500BO6')[0]  # Получаем первую котировку
print(quotes)

# Не забываем закрыть соединение
ap_provider.close_web_socket()
