from tkinter import *
from tkinter import ttk
from config import dataname_sell, dataname_buy, expected_profit, Lot_count, Basket_size, Timeout, running  # Импортируем конфиг

root = Tk()
root.title("MyQuoteRobot_v1_5.py")
root.geometry("200x410")

# Фрейм для центрирования элементов
main_frame = Frame(root)
main_frame.pack(expand=True, fill=BOTH)

# Элементы управления
label = ttk.Label(main_frame, text="Sell option")
label.pack(anchor=CENTER)

SELL = ["SPBOPT.Si84000BO6", "SPBOPT.Si85000BO6", "SPBOPT.Si86000BO6"]
combobox_sell = ttk.Combobox(main_frame, values=SELL)
combobox_sell.set(dataname_sell)
combobox_sell.pack(pady=5)

label = ttk.Label(main_frame, text="Buy option")
label.pack(anchor=CENTER)

BUY = ["SPBOPT.Si80000BC6", "SPBOPT.Si81000BC6", "SPBOPT.Si82000BC6"]
combobox_buy = ttk.Combobox(main_frame, values=BUY)
combobox_buy.set(dataname_buy)
combobox_buy.pack(pady=5)

label = ttk.Label(main_frame, text="Expected profit, %:")
label.pack(anchor=CENTER)

spinbox_profit = ttk.Spinbox(main_frame, from_=-10, to=10, increment=0.1, format="%.1f", width=8, justify=CENTER)
spinbox_profit.set(expected_profit)
spinbox_profit.pack(pady=5)

label = ttk.Label(main_frame, text="Lot count:")
label.pack(anchor=CENTER)

spinbox_lot = ttk.Spinbox(main_frame, from_=1, to=100, increment=1, width=8, justify=CENTER)
spinbox_lot.set(Lot_count)
spinbox_lot.pack(pady=5)

label = ttk.Label(main_frame, text="Basket size:")
label.pack(anchor=CENTER)

spinbox_basket = ttk.Spinbox(main_frame, from_=1, to=100, increment=1, width=8, justify=CENTER)
spinbox_basket.set(Basket_size)
spinbox_basket.pack(pady=5)

label = ttk.Label(main_frame, text="Timeout:")
label.pack(anchor=CENTER)

spinbox_timeout = ttk.Spinbox(main_frame, from_=1, to=30, increment=1, width=8, justify=CENTER)
spinbox_timeout.set(Timeout)
spinbox_timeout.pack(pady=5)

# Кнопки вертикально в центре
button_frame = Frame(main_frame)
button_frame.pack(pady=10)

def save_config():
    import config
    config.dataname_sell = combobox_sell.get()
    config.dataname_buy = combobox_buy.get()
    config.expected_profit = float(spinbox_profit.get())
    config.Lot_count = int(spinbox_lot.get())
    config.Basket_size = int(spinbox_basket.get())
    config.Timeout = int(spinbox_timeout.get())
    config.running = False  # Сброс флага перед запуском
    print("Настройки сохранены")

def start_program():
    running = True
    print(running)
    print("Программа запущена")

def stop_program():
    running = False
    print("Программа остановлена")

btn_save = ttk.Button(button_frame, text="SAVE", command=save_config)
btn_save.pack(pady=2)

btn_start = ttk.Button(button_frame, text="START", command=start_program)
btn_start.pack(pady=2)

btn_stop = ttk.Button(button_frame, text="STOP", command=stop_program)
btn_stop.pack(pady=2)

root.mainloop()
