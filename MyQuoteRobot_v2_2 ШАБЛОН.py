import tkinter as tk
from tkinter import ttk
import time


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("My Quote Robot")
        self.root.geometry("200x700")

        self.running = False
        self.counter = 0

        # Label My Quote Robot
        self.label = tk.Label(self.root, text="My Quote Robot v2.2")
        self.label.pack(pady=5)

        # Выбор базового актива
        base_tickers = ["AAPL", "GOOG", "MSFT"]
        self.combobox_sell = ttk.Combobox(self.root, values=base_tickers)
        self.combobox_sell.set(base_tickers[0])  # Установить первый элемент по умолчанию
        self.combobox_sell.pack(pady=5)
        # self.combobox_sell.bind("<<ComboboxSelected>>", selected_sell)

        # Выбор опционной серии
        self.combobox_expire = ttk.Combobox(self.root, values=["1d", "1w", "1m"])
        self.combobox_expire.set("1d")  # Установить первый
        self.combobox_expire.pack(pady=5)
        # self.combobox_sell.bind("<<ComboboxSelected>>", expiration_date)

        # Выбор тип опциона на продажу (Call/Put)
        radio_frame = tk.Frame(self.root)
        radio_frame.pack(pady=5)
        self.option_type = tk.StringVar(value="Call")
        self.call_radio = tk.Radiobutton(radio_frame, text="Call", variable=self.option_type, value="Call")
        self.put_radio = tk.Radiobutton(radio_frame, text="Put", variable=self.option_type, value="Put")
        self.call_radio.pack(side=tk.LEFT, padx=10)
        self.put_radio.pack(side=tk.LEFT, padx=10)

        # Выбор опциона на продажу
        sell_tickers = ["AAPL", "GOOG", "MSFT"]
        self.combobox_sell = ttk.Combobox(self.root, values=sell_tickers)
        self.combobox_sell.set(base_tickers[0])  # Установить первый
        self.combobox_sell.pack(pady=5)
        # self.combobox_sell.bind("<<ComboboxSelected>>", selected_sell)

        # Выбор тип опциона на покупку(Call/Put)
        radio_frame = tk.Frame(self.root)
        radio_frame.pack(pady=5)
        self.option_type = tk.StringVar(value="Put")  # Установить Put по умолчанию
        self.call_radio = tk.Radiobutton(radio_frame, text="Call", variable=self.option_type, value="Call")
        self.put_radio = tk.Radiobutton(radio_frame, text="Put", variable=self.option_type, value="Put")
        self.call_radio.pack(side=tk.LEFT, padx=10)
        self.put_radio.pack(side=tk.LEFT, padx=10)

        # Выбор опциона на покупку
        buy_tickers = ["AAPL", "GOOG", "MSFT"]
        self.combobox_buy = ttk.Combobox(self.root, values=buy_tickers)
        self.combobox_buy.set(base_tickers[0])  # Установить первый
        self.combobox_buy.pack(pady=5)
        # self.combobox_sell.bind("<<ComboboxSelected>>", selected_buy)

        # Метка Expected profit, %:
        self.expected_profit_label = tk.Label(self.root, text="Expected profit, % : ")
        self.expected_profit_label.pack(pady=10)

        # Спинбокс spinbox_profit Expected profit
        # self.spinbox_profit = tk.Spinbox(self.root, from_=-10, to=10, increment=0.1, format="%.1f", width=8, textvariable=2.0, command=selected_profit)
        self.spinbox_profit_var = tk.DoubleVar(value=5.0)
        self.spinbox_profit = tk.Spinbox(self.root, from_=-10, to=10, increment=0.1, format="%.1f", width=8, textvariable=self.spinbox_profit_var)
        self.spinbox_profit.pack(pady=5)

        # Label Lot count
        self.lot_count_label = tk.Label(self.root, text="Lot count: ")
        self.lot_count_label.pack(pady=5)

        # # Spinbox Переменная Lot_count
        self.lot_count_var = tk.IntVar(value=1)
        self.lot_count = tk.Spinbox(self.root, from_=1, to=100, increment=1, width=8, textvariable=self.lot_count_var)
        self.lot_count.pack(pady=5)

        # Label Basket size
        self.basket_size_label = tk.Label(self.root, text="Basket size: ")
        self.basket_size_label.pack(pady=5)

        # Spinbox Переменная Basket_size
        self.basket_size_var = tk.IntVar(value=1)
        self.basket_size = tk.Spinbox(self.root, from_=1, to=100, increment=1, width=8, textvariable=self.basket_size_var)
        self.basket_size.pack(pady=5)

        # Label Timeout
        self.timeout_label = tk.Label(self.root, text="Timeout: ")
        self.timeout_label.pack(pady=5)

        # Spinbox Переменная Timeout
        self.timeout_var = tk.IntVar(value=1)
        self.timeout = tk.Spinbox(self.root, from_=1, to=30, increment=1, width=8, textvariable=self.timeout_var)
        self.timeout.pack(pady=5)

        # Создаем кнопки
        self.start_button = tk.Button(self.root, text="Start", command=self.start_loop)
        self.start_button.pack(pady=10)

        self.stop_button = tk.Button(self.root, text="Stop", command=self.stop_loop)
        self.stop_button.pack(pady=10)

        # Button Exit
        self.exit_button = tk.Button(self.root, text="Exit", command=self.exit)
        self.exit_button.pack(pady=10)

        self.status_label = tk.Label(self.root, text="Status: Stopped")
        self.status_label.pack(pady=10)

        self.counter_label = tk.Label(self.root, text="Счётчик циклов: 0")
        self.counter_label.pack(pady=10)

    def loop_function(self):
        """Функция, которая будет выполняться в цикле"""
        if self.running:
            self.counter += 1
            self.counter_label.config(text=f"Счётчик циклов: {self.counter}")
            self.status_label.config(text="Status: Running")

            # Планируем следующий вызов через 100 мс
            self.root.after(1000, self.loop_function)

    def start_loop(self):
        """Запуск цикла"""
        if not self.running:
            self.running = True
            self.loop_function()  # Запускаем цикл

    def stop_loop(self):
        """Остановка цикла"""
        self.running = False
        self.status_label.config(text="Status: Stopped")

    def exit(self):
        """Выход из приложения"""
        self.root.destroy()


# Запуск приложения
if __name__ == "__main__":
    app = App()
    app.root.mainloop()
