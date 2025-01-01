from typing import Tuple
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib.widgets import RangeSlider, CheckButtons
import json

# Указываем путь к файлу CSV
fn = r'C:\Users\Андрей\YandexDisk\_ИИС\Position\CenterStrikeVola_RTS.csv'
ticker = "RTS"
# Начальные параметры графиков: 840 - кол.торговых минуток за сутки
limit_day = 840
# Кол.торговых минуток за месяц 17640 = 840 мин x 21 раб.день
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
    graph_state_file = open('graph_state.json', 'w', encoding="utf-8")
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
    l3, = graph_axes.plot(t, zero_to_nan(df_slider[df.columns[4]]), lw=2, color='cyan', label=df.columns[4])
    l4, = graph_axes.plot(t, zero_to_nan(df_slider[df.columns[5]]), lw=2, color='blue', label=df.columns[5])

    lines_by_label = {l.get_label(): l for l in [l0, l1, l2, l3, l4]}
    line_colors = [l.get_color() for l in lines_by_label.values()]

    # Поворачиваем метки на оси Y вправо
    graph_axes.yaxis.tick_right()
    graph_axes.yaxis.set_label_position("right")

    # Настраиваем отображение дат на оси X
    graph_axes.set(xlabel=None)
    graph_axes.grid(True)
    graph_axes.xaxis.set_major_locator(plt.MultipleLocator((x_max - x_min) / 8))

    # Определим, нужно ли показывать серию опционов на графике
    series_visible = checkbuttons_series.get_status()[1]
    #print(series_visible)
    # # ln.figure.canvas.draw_idle()


    for label, visible in graph_state.items():  # Восстанавливаем статус видимости графиков
        if visible:
            lines_by_label[label].set_visible(True)
        else:
            lines_by_label[label].set_visible(False)

    # Определим, нужно ли показывать сетку на графике
    grid_visible = checkbuttons_grid.get_status()[0]
    graph_axes.grid(grid_visible)

    # Добавляем подписи с последним значением
    graph_axes.text(x=len(df_slider) + 2, y=df_slider[df.columns[1]].iloc[len(df_slider) - 1],
                    s="{:.2f}".format(df_slider[df.columns[1]].iloc[len(df_slider) - 1]),
                    color="red", fontsize=9)
    graph_axes.text(x=len(df_slider) + 2, y=df_slider[df.columns[2]].iloc[len(df_slider) - 1],
                    s="{:.2f}".format(df_slider[df.columns[2]].iloc[len(df_slider) - 1]),
                    color="orange", fontsize=9)
    graph_axes.text(x=len(df_slider) + 2, y=df_slider[df.columns[3]].iloc[len(df_slider) - 1],
                    s="{:.2f}".format(df_slider[df.columns[3]].iloc[len(df_slider) - 1]),
                    color="green", fontsize=9)
    graph_axes.text(x=len(df_slider) + 2, y=df_slider[df.columns[4]].iloc[len(df_slider) - 1],
                    s="{:.2f}".format(df_slider[df.columns[4]].iloc[len(df_slider) - 1]),
                    color="cyan", fontsize=9)
    graph_axes.text(x=len(df_slider) + 2, y=df_slider[df.columns[5]].iloc[len(df_slider) - 1],
                    s="{:.2f}".format(df_slider[df.columns[5]].iloc[len(df_slider) - 1]),
                    color="blue", fontsize=9)
    dump_graph_state_to_file()
    plt.draw()

def onCheckClicked1(label):
    """" Обработчик события при нажатии на флажок"""
    ln = lines_by_label[label]
    ln.set_visible(not ln.get_visible())
    series_visible = checkbuttons_series.get_status()[0]

    # Здесь добавляем логику для отображения или скрытия серии опционов
    if ln.get_visible():
        # print("Серия опционов ", label, " видна")
        # ln.figure.canvas.draw_idle()
        plt.draw()
    else:
        # print("Серия опционов ", label, " скрыта")
        ln.figure.canvas.draw_idle()
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
    updateGraph()

if __name__ == "__main__":
    # Читаем CSV/TXT файл (разделённый точкой с запятой) в DataFrame
    df = pd.read_csv(fn, sep=';')
    rows_count = len(df)

    lines_by_label = {df.columns[1], df.columns[2], df.columns[3], df.columns[4], df.columns[5]}
    line_colors = {"red", "orange", "green", "cyan", "blue"}

    x_max = rows_count
    x_min = rows_count - limit_day

    # Создадим окно с графиком
    fig, graph_axes = plt.subplots(figsize=(10, 5))

    # Выделим область, которую будет занимать график
    fig.subplots_adjust(left=0.01, right=0.95, top=0.99, bottom=0.1)

    # plt.title("Center strike vola RTS")  # Добавляем заголовок графика
    # plt.title("Center strike vola RTS", color="blue", size=14, y=0.95, loc="left")
    plt.text(0.1, 0.95, "ticker", size=30)

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
    axes_checkbuttons1 = plt.axes([0.01, 0.1, 0.11, 0.26])

    # Инициализируем словарь для хранения статуса видимости графиков
    graph_state_file = open('graph_state.json', 'r', encoding="utf-8")
    graph_state = json.load(graph_state_file)
    graph_state_file.close()

    checkbuttonLabels = []
    checkbuttonStates = []
    for i in range(1, 6):
        checkbuttonLabel = df.columns[i]
        checkbuttonLabels.append(checkbuttonLabel)
        checkbuttonStates.append(graph_state[checkbuttonLabel])

    # Создадим флажок выключателя опционных серий
    checkbuttons_series = CheckButtons(
        ax=axes_checkbuttons1,
        labels=checkbuttonLabels,
        actives=checkbuttonStates,
        label_props={'color':["red", "orange", "green", "cyan", "blue"]},
        frame_props={'edgecolor': 'black'},
        check_props={'facecolor': 'black'},
    )

    # graph_state = {label: True for label in lines_by_label}
    # print(graph_state)

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
