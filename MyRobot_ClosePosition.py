import logging # Выводим лог на консоль и в файл
# logging.basicConfig(level=logging.WARNING) # уровень логгирования
import tkinter as tk
from tkinter import ttk
import time
from threading import Thread  # Запускаем поток подписки
from AlorPy import AlorPy  # Работа с Alor OpenAPI V2
from FinamPy import FinamPy
from FinLabPy.Config import brokers, default_broker  # Все брокеры и брокер по умолчанию
from QUIK_Stream_v1_7 import calculate_open_data_open_price_open_iv
import math
import numpy as np
from datetime import datetime, timezone  # Дата и время
from time import sleep  # Задержка в секундах перед выполнением операций
from scipy.stats import norm
from google.type.decimal_pb2 import Decimal

# Глобальные переменные
global theor_profit_buy, theor_profit_sell, base_asset_ticker
theor_profit_buy = 0.0
theor_profit_sell = 0.0
base_asset_ticker = 0.0
CALL = 'C'
PUT = 'P'
r = 0 # Безрисковая ставка
# Список GUID для отписки
guids = []
global dataname_sell, dataname_buy, expected_profit, Lot_count, Basket_size, Timeout, running
dataname_sell = ''
dataname_buy = ''
expected_profit = 5.0
Lot_count = 1
Basket_size = 1
Timeout = 8
running = False

Lot_count_step = 0
sleep_time = 5  # Время ожидания в секундах

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  # Формат сообщения
                            datefmt='%d.%m.%Y %H:%M:%S',  # Формат даты
                            level=logging.INFO,  # Уровень логируемых событий NOTSET/DEBUG/INFO/WARNING/ERROR/CRITICAL
                            handlers=[logging.FileHandler('MyControlPanel.log', encoding='utf-8'),
                                      logging.StreamHandler()])  # Лог записываем в файл и выводим на консоль
# logging.Formatter.converter = lambda *args: datetime.now(tz=fp_provider.tz_msk).timetuple()  # В логе время указываем по МСК

class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("MyQuoteRobot_v1_5.py")
        self.root.geometry("400x600")

        # Создаем фрейм для размещения элементов
        self.main_frame = ttk.Frame(self.root, padding="10")
        self.main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Конфигурируем вес для растягивания
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        self.main_frame.columnconfigure(1, weight=1)

        # Переменные для хранения значений
        self.sell_var = tk.StringVar()
        self.buy_var = tk.StringVar()
        self.expected_profit_var = tk.DoubleVar(value=expected_profit)
        self.lot_count_var = tk.IntVar(value=Lot_count)
        self.basket_size_var = tk.IntVar(value=Basket_size)
        self.timeout_var = tk.IntVar(value=Timeout)

        # Элементы интерфейса
        # Выбор продаваемого опциона
        ttk.Label(self.main_frame, text="Продаваемый опцион:").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.sell_combo = ttk.Combobox(self.main_frame, textvariable=self.sell_var, width=30)
        self.sell_combo.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=2)
        self.sell_combo.bind('<<ComboboxSelected>>', self.on_sell_selected)

        # Выбор покупаемого опциона
        ttk.Label(self.main_frame, text="Покупаемый опцион:").grid(row=2, column=0, sticky=tk.W, pady=2)
        self.buy_combo = ttk.Combobox(self.main_frame, textvariable=self.buy_var, width=30)
        self.buy_combo.grid(row=3, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=2)

        # Ожидаемая прибыль
        ttk.Label(self.main_frame, text="Ожидаемая прибыль (%):").grid(row=4, column=0, sticky=tk.W, pady=2)
        self.profit_spinbox = ttk.Spinbox(self.main_frame, from_=0, to=100, textvariable=self.expected_profit_var, width=10)
        self.profit_spinbox.grid(row=5, column=0, sticky=tk.W, pady=2)

        # Количество лотов
        ttk.Label(self.main_frame, text="Количество лотов:").grid(row=6, column=0, sticky=tk.W, pady=2)
        self.lot_spinbox = ttk.Spinbox(self.main_frame, from_=1, to=100, textvariable=self.lot_count_var, width=10)
        self.lot_spinbox.grid(row=7, column=0, sticky=tk.W, pady=2)

        # Размер корзины
        ttk.Label(self.main_frame, text="Размер корзины:").grid(row=8, column=0, sticky=tk.W, pady=2)
        self.basket_spinbox = ttk.Spinbox(self.main_frame, from_=1, to=100, textvariable=self.basket_size_var, width=10)
        self.basket_spinbox.grid(row=9, column=0, sticky=tk.W, pady=2)

        # Таймаут
        ttk.Label(self.main_frame, text="Таймаут (сек):").grid(row=10, column=0, sticky=tk.W, pady=2)
        self.timeout_spinbox = ttk.Spinbox(self.main_frame, from_=1, to=300, textvariable=self.timeout_var, width=10)
        self.timeout_spinbox.grid(row=11, column=0, sticky=tk.W, pady=2)

        # Кнопки управления
        self.start_button = ttk.Button(self.main_frame, text="Старт", command=self.start_operation)
        self.start_button.grid(row=12, column=0, pady=10)

        self.stop_button = ttk.Button(self.main_frame, text="Стоп", command=self.stop_operation)
        self.stop_button.grid(row=12, column=1, pady=10)

        # Метка статуса
        self.status_label = ttk.Label(self.main_frame, text="Статус: Готов", foreground="blue")
        self.status_label.grid(row=13, column=0, columnspan=2, pady=5)

        # Поле вывода информации
        self.output_text = tk.Text(self.main_frame, height=15, width=50)
        self.output_text.grid(row=14, column=0, columnspan=2, pady=10, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Скроллбар для текстового поля
        scrollbar = ttk.Scrollbar(self.main_frame, orient="vertical", command=self.output_text.yview)
        scrollbar.grid(row=14, column=2, sticky=(tk.N, tk.S))
        self.output_text.configure(yscrollcommand=scrollbar.set)

        # Связываем события изменения значений
        self.sell_combo.bind('<<ComboboxSelected>>', self.on_sell_selected)
        self.buy_combo.bind('<<ComboboxSelected>>', self.on_buy_selected)

    def on_sell_selected(self, event):
        # Обработчик выбора продаваемого опциона
        selected = self.sell_var.get()
        self.output_text.insert(tk.END, f"Выбран продаваемый опцион: {selected}\n")
        self.output_text.see(tk.END)

    def on_buy_selected(self, event):
        # Обработчик выбора покупаемого опциона
        selected = self.buy_var.get()
        self.output_text.insert(tk.END, f"Выбран покупаемый опцион: {selected}\n")
        self.output_text.see(tk.END)

    def start_operation(self):
        # Запуск операции
        self.status_label.config(text="Статус: Работает", foreground="green")
        self.output_text.insert(tk.END, "Операция запущена\n")
        self.output_text.see(tk.END)

    def stop_operation(self):
        # Остановка операции
        self.status_label.config(text="Статус: Остановлен", foreground="red")
        self.output_text.insert(tk.END, "Операция остановлена\n")
        self.output_text.see(tk.END)

    def update_output(self, message):
        # Метод для обновления текстового поля
        self.output_text.insert(tk.END, message + "\n")
        self.output_text.see(tk.END)

# Запуск приложения
if __name__ == "__main__":
    app = App()
    app.root.mainloop()
