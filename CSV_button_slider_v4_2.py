from typing import Tuple
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib.widgets import RangeSlider, CheckButtons
import matplotlib
import json

ticker = "RTS. Center strike options volatility."
SMALL_SIZE = 8
matplotlib.rc('font', size=SMALL_SIZE)

# Указываем путь к файлу CSV
fn = r'C:\Users\шадрин\YandexDisk\_ИИС\Position\_TEST_CenterStrikeVola_RTS.csv'
# Начальные параметры графиков: 840 - кол.торговых минуток за сутки
limit_day = 840
# Кол.торговых минуток за месяц 17640 = 840 мин x 21 раб. день
limit_month = 17640

def format_date_time(x):
    # Разделяем строку сначала по точкам, а затем берём первые два элемента списка (дату и месяц)
    date_parts = x.split('.')
    date_part = '.'.join(date_parts[:2])
    # Добавляем к дате время
    time_part = x.split()[1]
    formatted_datetime = date_part + " " + time_part[:5]
    return formatted_datetime

def zero_to_nan(values):
    """Replace every 0 with 'nan' and return a copy."""
    return [float('nan') if x==0 else x for x in values]

def dump_graph_state_to_file():
    graph_state_file = open('graph_state_v4_2.json', 'w', encoding="utf-8")
    json.dump(graph_state, graph_state_file)
    graph_state_file.close()

def updateGraph():
    # print("RUN updateGraph!")
    """!!! Функция для обновления графика"""
    global slider_x_range
    global graph_axes
    global checkbuttons_grid
    global checkbuttons_series
    global rows_count
    global lines_by_label
    global text_by_label
    global series_visible
    global ln
    global graph_state  # Добавляем словарь для хранения статуса видимости графиков
    global valmin
    global valmax
    global df

    df_slider = df.loc[x_min:x_max]
    t = df_slider['DateTime'].apply(lambda x: format_date_time(x))

    graph_axes.clear()

    # Создаём скользящее окно
    window = df.rolling(1)  # Замените '1' на нужное вам количество строк

    l0, = graph_axes.plot(t, zero_to_nan(df_slider[df.columns[1]]), lw=2, color='red', label=df.columns[1])
    l1, = graph_axes.plot(t, zero_to_nan(df_slider[df.columns[2]]), lw=2, color='orange', label=df.columns[2])
    l2, = graph_axes.plot(t, zero_to_nan(df_slider[df.columns[3]]), lw=2, color='green', label=df.columns[3])
    l3, = graph_axes.plot(t, zero_to_nan(df_slider[df.columns[4]]), lw=2, color='aqua', label=df.columns[4])
    l4, = graph_axes.plot(t, zero_to_nan(df_slider[df.columns[5]]), lw=2, color='blue', label=df.columns[5])
    l5, = graph_axes.plot(t, zero_to_nan(df_slider[df.columns[6]]), lw=2, color='lightcoral', label=df.columns[6])
    l6, = graph_axes.plot(t, zero_to_nan(df_slider[df.columns[7]]), lw=2, color='moccasin', label=df.columns[7])
    l7, = graph_axes.plot(t, zero_to_nan(df_slider[df.columns[8]]), lw=2, color='lime', label=df.columns[8])
    l8, = graph_axes.plot(t, zero_to_nan(df_slider[df.columns[9]]), lw=2, color='paleturquoise', label=df.columns[9])
    l9, = graph_axes.plot(t, zero_to_nan(df_slider[df.columns[10]]), lw=2, color='cornflowerblue', label=df.columns[10])

    lines_by_label = {l.get_label(): l for l in [l0, l1, l2, l3, l4, l5, l6, l7, l8, l9]}

    # Поворачиваем метки на оси Y вправо
    graph_axes.yaxis.tick_right()
    graph_axes.yaxis.set_label_position("right")

    # Настраиваем отображение дат на оси X
    graph_axes.set(xlabel=None)
    graph_axes.grid(True)
    graph_axes.xaxis.set_major_locator(plt.MultipleLocator((x_max - x_min) / 8))

    # Определим, нужно ли показывать сетку на графике
    grid_visible = checkbuttons_grid.get_status()[0]
    graph_axes.grid(grid_visible)

    # Добавляем подписи с последним значением
    tx0 = graph_axes.text(x=len(df_slider) + 2, y=df_slider[df.columns[1]].iloc[len(df_slider) - 1],
                    s="{:.2f}".format(df_slider[df.columns[1]].iloc[len(df_slider) - 1]),
                    color="red", fontsize=9, label=df.columns[1])
    tx1 = graph_axes.text(x=len(df_slider) + 2, y=df_slider[df.columns[2]].iloc[len(df_slider) - 1],
                    s="{:.2f}".format(df_slider[df.columns[2]].iloc[len(df_slider) - 1]),
                    color="orange", fontsize=9, label=df.columns[2])
    tx2 = graph_axes.text(x=len(df_slider) + 2, y=df_slider[df.columns[3]].iloc[len(df_slider) - 1],
                    s="{:.2f}".format(df_slider[df.columns[3]].iloc[len(df_slider) - 1]),
                    color="green", fontsize=9, label=df.columns[3])
    tx3 = graph_axes.text(x=len(df_slider) + 2, y=df_slider[df.columns[4]].iloc[len(df_slider) - 1],
                    s="{:.2f}".format(df_slider[df.columns[4]].iloc[len(df_slider) - 1]),
                    color="aqua", fontsize=9, label=df.columns[4])
    tx4 = graph_axes.text(x=len(df_slider) + 2, y=df_slider[df.columns[5]].iloc[len(df_slider) - 1],
                    s="{:.2f}".format(df_slider[df.columns[5]].iloc[len(df_slider) - 1]),
                    color="blue", fontsize=9, label=df.columns[5])
    tx5 = graph_axes.text(x=len(df_slider) + 2, y=df_slider[df.columns[6]].iloc[len(df_slider) - 1],
                    s="{:.2f}".format(df_slider[df.columns[6]].iloc[len(df_slider) - 1]),
                    color="lightcoral", fontsize=9, label=df.columns[6])
    tx6 = graph_axes.text(x=len(df_slider) + 2, y=df_slider[df.columns[7]].iloc[len(df_slider) - 1],
                    s="{:.2f}".format(df_slider[df.columns[7]].iloc[len(df_slider) - 1]),
                    color="moccasin", fontsize=9, label=df.columns[7])
    tx7 = graph_axes.text(x=len(df_slider) + 2, y=df_slider[df.columns[8]].iloc[len(df_slider) - 1],
                    s="{:.2f}".format(df_slider[df.columns[8]].iloc[len(df_slider) - 1]),
                    color="lime", fontsize=9, label=df.columns[8])
    tx8 = graph_axes.text(x=len(df_slider) + 2, y=df_slider[df.columns[9]].iloc[len(df_slider) - 1],
                    s="{:.2f}".format(df_slider[df.columns[9]].iloc[len(df_slider) - 1]),
                    color="paleturquoise", fontsize=9, label=df.columns[9])
    tx9 = graph_axes.text(x=len(df_slider) + 2, y=df_slider[df.columns[10]].iloc[len(df_slider) - 1],
                    s="{:.2f}".format(df_slider[df.columns[10]].iloc[len(df_slider) - 1]),
                    color="cornflowerblue", fontsize=9, label=df.columns[10])
    text_by_label = {tx.get_label(): tx for tx in [tx0, tx1, tx2, tx3, tx4, tx5, tx6, tx7, tx8, tx9]}

    for label, visible in graph_state.items():  # Восстанавливаем статус видимости графиков и IV
        if visible:
            lines_by_label[label].set_visible(True)
            text_by_label[label].set_visible(True)
        else:
            lines_by_label[label].set_visible(False)
            text_by_label[label].set_visible(False)

    dump_graph_state_to_file()
    plt.draw()

def onCheckClicked1(label):
    """" Обработчик события при нажатии на флажок"""
    ln = lines_by_label[label]
    txn = text_by_label[label]
    ln.set_visible(not ln.get_visible())
    txn.set_visible(not txn.get_visible())
    series_visible = checkbuttons_series.get_status()[1]

    # Здесь добавляем логику для отображения или скрытия серии опционов
    if ln.get_visible():
        plt.draw()
    else:
        ln.figure.canvas.draw_idle()
        txn.figure.canvas.draw_idle()
        plt.draw()

    # Сохраняем статус видимости графиков
    global graph_state
    graph_state[label] = ln.get_visible()

def onCheckClicked2(value: str):
    """ Обработчик события при нажатии на флажок"""
    updateGraph()

def onChangeXRange(value: Tuple[np.float64, np.float64]):
    # print("Обработчик события изменения значения интервала по оси X")
    """Обработчик события изменения значения интервала по оси X"""
    global rows_count
    global x_max
    global x_min
    global valmax
    global df
    global df_slider
    # Получаем значение интервала
    x_min, x_max = slider_x_range.val

    # Читаем CSV/TXT файл (разделённый точкой с запятой) в DataFrame
    df = pd.read_csv(fn, sep=';')
    rows_count = len(df)
    df_slider = df.loc[x_min:x_max]
    # x_max = rows_count
    valmax = x_max
    # print("x_min onChangeXRange = ", x_min)
    # print("x_max onChangeXRange = ", x_max)
    plt.draw()
    updateGraph()

if __name__ == "__main__":
    # print("RUN main!")
    # Читаем CSV/TXT файл (разделённый точкой с запятой) в DataFrame
    df = pd.read_csv(fn, sep=';')
    rows_count = len(df)

    lines_by_label = {df.columns[1], df.columns[2], df.columns[3], df.columns[4], df.columns[5], df.columns[6],
                      df.columns[7], df.columns[8], df.columns[9], df.columns[10]}
    text_by_label = {df.columns[1], df.columns[2], df.columns[3], df.columns[4], df.columns[5], df.columns[6],
                      df.columns[7], df.columns[8], df.columns[9], df.columns[10]}
    line_colors = {"red", "orange", "green", "aqua", "blue", "lightcoral", "moccasin", "lime", "paleturquoise", "cornflowerblue"}

    x_max = rows_count
    x_min = rows_count - limit_day

    # Создадим окно с графиком
    fig, graph_axes = plt.subplots(figsize=(10, 5), num=ticker)

    # Выделим область, которую будет занимать график
    fig.subplots_adjust(left=0.01, right=0.96, top=0.99, bottom=0.1)

    # Создадим слайдер для задания интервала по оси X
    # (координата X левой границы, координата Y нижней границы, ширина, высота)
    axes_slider_x_range = plt.axes([0.1, 0.01, 0.75, 0.04])
    slider_x_range = RangeSlider(
        axes_slider_x_range,
        label="x",
        valmin=rows_count - limit_month,
        valmax=rows_count,
        valinit=(x_min, x_max),
        valstep=1,
        valfmt="%0.0f",
    )

    # Создадим оси для флажка выключателя опционных серий
    axes_checkbuttons1 = plt.axes([0.01, 0.1, 0.14, 0.4])

    # Инициализируем словарь для хранения статуса видимости графиков
    graph_state_file = open('graph_state_v4_2.json', 'r', encoding="utf-8")
    graph_state = json.load(graph_state_file)
    graph_state_file.close()

    checkbuttonLabels = []
    checkbuttonStates = []
    for i in range(1, 11):
        checkbuttonLabel = df.columns[i]
        checkbuttonLabels.append(checkbuttonLabel)
        checkbuttonStates.append(graph_state[checkbuttonLabel])

    # Создадим флажок выключателя опционных серий
    checkbuttons_series = CheckButtons(
        ax=axes_checkbuttons1,
        labels=checkbuttonLabels,
        actives=checkbuttonStates,
        label_props={'color':["red", "orange", "green", "aqua", "blue", "lightcoral", "moccasin", "lime", "paleturquoise", "cornflowerblue"]},
        frame_props={'edgecolor': 'black'},
        check_props={'facecolor': 'black'},
    )

    # # Инициализируем словарь для хранения статуса видимости графиков
    # graph_state = {label: True for label in lines_by_label}

    # Создадим оси для флажка выключателя сетки
    axes_checkbuttons2 = plt.axes([0.01, 0.01, 0.06, 0.044])

    # Создадим флажок выключателя сетки
    checkbuttons_grid = CheckButtons(axes_checkbuttons2, ["Сетка"], [True])

    # Подпишемся на событие изменения интервала по оси X
    slider_x_range.on_changed(onChangeXRange)

    # Подпишемся на событие при клике по флажку выключателя опционных серий
    checkbuttons_series.on_clicked(onCheckClicked1)

    # Подпишемся на событие при клике по флажку выключателя сетки
    checkbuttons_grid.on_clicked(onCheckClicked2)

    updateGraph()

def animate(i):
    # print("RUN animate!")
    global rows_count
    global x_max
    global valmax
    global df
    rows_count_old = rows_count
    # Читаем CSV/TXT файл (разделённый точкой с запятой) в DataFrame
    df = pd.read_csv(fn, sep=';')
    rows_count = len(df)
    if rows_count > rows_count_old:
        x_max = rows_count
        valmax = x_max
    updateGraph()

ani = animation.FuncAnimation(fig, animate, interval=10000, cache_frame_data=False)
plt.show()
