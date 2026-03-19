from tkinter import *
from tkinter import ttk
from FinLabPy.Config import brokers, default_broker  # Все брокеры и брокер по умолчанию

global dataname_sell, dataname_buy, expected_profit, Lot_count, Basket_size, Timeout
dataname_sell = ''
dataname_buy = ''
expected_profit = 2.0
Lot_count = 1
Basket_size = 1
Timeout = 8
running = False

# print(dataname_sell, dataname_buy, expected_profit, Lot_count, Basket_size, Timeout, running)

# Получение позиций по инструментам портфеля проданным и купленным
def get_position_finam():
    SELL = []
    BUY = []
    for position in default_broker.get_positions():  # Пробегаемся по всем позициям брокера
        # print(f'  - {position.dataname} {position.quantity}')
        # Получаем dataname и quantity, сохраняем в список SELL dataname отрицательных позиций quantity, в список BUY - с положительными позициями
        if position.dataname.startswith('SPBOPT.') and position.quantity > 0:
            SELL.append(position.dataname)
        elif position.dataname.startswith('SPBOPT.') and position.quantity < 0:
            BUY.append(position.dataname)
    # print(f'SELL: {SELL}')
    # print(f'BUY: {BUY}')
    default_broker.close()  # Закрываем брокера
    return SELL, BUY

SELL, BUY = get_position_finam()  # Списки для панели управления MyControlPanel.py

root = Tk()
root.title("MyQuoteRobot_v1_5.py")
root.geometry("200x410")

def selected_sell(event):
    # получаем выделенный элемент
    dataname_sell = combobox_sell.get()
    print(dataname_sell)
    # label["text"] = f"вы выбрали: {dataname_sell}"

def selected_buy(event):
    # получаем выделенный элемент
    dataname_buy = combobox_buy.get()
    print(dataname_buy)
    # label["text"] = f"вы выбрали: {dataname_buy}"

def selected_profit():
    # получаем выделенный выбранный процент
    expected_profit = spinbox_profit.get()
    print(expected_profit)
    # label["text"] = f"вы выбрали: {expected_profit}"

def selected_lot():
    # получаем выделенный выбранный лот
    Lot_count = spinbox_lot.get()
    print(Lot_count)
    # label["text"] = f"вы выбрали: {Lot_count}"

def selected_basket():
    # получаем выделенный выбранный баскет
    Basket_size = spinbox_basket.get()
    print(Basket_size)
    # label["text"] = f"вы выбрали: {Basket_size}"

def selected_timeout():
    # получаем выделенный выбранный таймаут
    Timeout = spinbox_timeout.get()
    print(Timeout)
    # label["text"] = f"вы выбрали: {Timeout}"

# Фрейм для центрирования элементов
main_frame = Frame(root)
main_frame.pack(expand=True, fill=BOTH)

# Элементы управления
label = ttk.Label(main_frame, text="Sell option")
label.pack(anchor=CENTER)

# Переменная dataname_sell
# SELL = ["SPBOPT.Si84000BO6", "SPBOPT.Si85000BO6", "SPBOPT.Si86000BO6"]
combobox_sell = ttk.Combobox(main_frame, values=SELL)
combobox_sell.set(SELL[0])  # Установить первый элемент по умолчанию
combobox_sell.pack(pady=5)
combobox_sell.bind("<<ComboboxSelected>>", selected_sell)

label = ttk.Label(main_frame, text="Buy option")
label.pack(anchor=CENTER)

# Переменная dataname_buy
# BUY = ["SPBOPT.Si80000BC6", "SPBOPT.Si81000BC6", "SPBOPT.Si82000BC6"]
combobox_buy = ttk.Combobox(main_frame, values=BUY)
combobox_buy.set(BUY[0])  # Установить первый элемент по умолчанию
combobox_buy.pack(pady=5)
combobox_buy.bind("<<ComboboxSelected>>", selected_buy)

label = ttk.Label(main_frame, text="Expected profit, %:")
label.pack(anchor=CENTER)

# Переменная expected_profit
spinbox_profit = ttk.Spinbox(main_frame, from_=-10, to=10, increment=0.1, format="%.1f", width=8, justify=CENTER, textvariable=2.0, command=selected_profit)
spinbox_profit.set(2.0)  # Установить значение по умолчанию
spinbox_profit.pack(pady=5)

label = ttk.Label(main_frame, text="Lot count:")
label.pack(anchor=CENTER)

# Переменная Lot_count
spinbox_lot = ttk.Spinbox(main_frame, from_=1, to=100, increment=1, width=8, justify=CENTER, command=selected_lot)
spinbox_lot.set(1)
spinbox_lot.pack(pady=5)

label = ttk.Label(main_frame, text="Basket size:")
label.pack(anchor=CENTER)

# Переменная Basket_size
spinbox_basket = ttk.Spinbox(main_frame, from_=1, to=100, increment=1, width=8, justify=CENTER, command=selected_basket)
spinbox_basket.set(1)
spinbox_basket.pack(pady=5)

label = ttk.Label(main_frame, text="Timeout:")
label.pack(anchor=CENTER)

# Переменная Timeout
spinbox_timeout = ttk.Spinbox(main_frame, from_=1, to=30, increment=1, width=8, justify=CENTER, command=selected_timeout)
spinbox_timeout.set(8)
spinbox_timeout.pack(pady=5)

# Кнопки вертикально в центре
button_frame = Frame(main_frame)
button_frame.pack(pady=10)


def save_config():
    # global dataname_sell, dataname_buy, expected_profit, Lot_count, Basket_size, Timeout, running
    dataname_sell = combobox_sell.get()
    dataname_buy = combobox_buy.get()
    expected_profit = float(spinbox_profit.get())
    Lot_count = int(spinbox_lot.get())
    Basket_size = int(spinbox_basket.get())
    Timeout = int(spinbox_timeout.get())
    running = False  # Сброс флага перед запуском
    print("Настройки сохранены")
    return dataname_sell, dataname_buy, expected_profit, Lot_count, Basket_size, Timeout, running

def start_program():
    # global running
    running = True
    print(f"Программа запущена {running}")
    return running

def stop_program():
    # global running
    running = False
    print("Программа остановлена")
    return running

btn_save = ttk.Button(button_frame, text="SAVE", command=save_config)
btn_save.pack(pady=2)

btn_start = ttk.Button(button_frame, text="START", command=start_program)
btn_start.pack(pady=2)

btn_stop = ttk.Button(button_frame, text="STOP", command=stop_program)
btn_stop.pack(pady=2)

root.mainloop()
