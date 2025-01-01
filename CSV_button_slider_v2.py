from typing import Tuple
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# Импортируем классы кнопки и слайдера
from matplotlib.widgets import RangeSlider, Slider, RadioButtons, CheckButtons, Button

# Указываем путь к файлу CSV
fn = r'C:\Users\Андрей\YandexDisk\_ИИС\Position\CenterStrikeVola_RTS.csv'

def format_date_time(x):
    # Разделяем строку сначала по точкам, а затем берём первые два элемента списка (дату и месяц)
    date_parts = x.split('.')
    date_part = '.'.join(date_parts[:2])

    # Добавляем к дате время
    time_part = x.split()[1]
    formatted_datetime = date_part + " " + time_part[:5]

    return formatted_datetime

def updateGraph():
    """!!! Функция для обновления графика"""
    global slider_x_range
    global graph_axes
    global x_min
    global x_max

    # Получаем значение интервала
    x_min, x_max = slider_x_range.val
    x = np.arange(x_min, x_max, 1)
    # ax.clear()
    ax.set_xlim(x_min, x_max)
    print(x_min)
    print(x_max)

    # t = t.iloc[50410:51250]

    # Настраиваем отображение дат на оси X
    ax.set(xlabel=None)
    ax.grid(True)
    # ax.set_xticks(ax.get_xticks()[::120])
    ax.xaxis.set_major_locator(plt.MultipleLocator((x_max - x_min) / 8))

    # Поворачиваем метки на оси Y вправо
    ax.yaxis.tick_right()
    ax.yaxis.set_label_position("right")

    # ax.clear()
    # l0, = ax.plot(t, s0, lw=2, color='red', label=df.columns[1])
    # l1, = ax.plot(t, s1, lw=2, color='orange', label=df.columns[2])
    # l2, = ax.plot(t, s2, lw=2, color='green', label=df.columns[3])
    # l3, = ax.plot(t, s3, visible=False, lw=2, color='cyan', label=df.columns[4])
    # l4, = ax.plot(t, s4, visible=False, lw=2, color='blue', label=df.columns[5])
    # ax.set_xlim(x_min, x_max)
    # ani = animation.FuncAnimation(fig, animate, interval=10000, cache_frame_data=False)
    plt.draw()

def onChangeXRange(value: Tuple[np.float64, np.float64]):
    '''Обработчик события измерения значения интервала по оси X'''
    updateGraph()

def callback(label):
    ln = lines_by_label[label]
    ln.set_visible(not ln.get_visible())
    ln.figure.canvas.draw_idle()
    plt.draw()

if __name__ == '__main__':
    # Читаем CSV/TXT файл (разделённый точкой с запятой) в DataFrame
    df = pd.read_csv(fn, sep=';')
    rows_count = len(df)

    # Начальные параметры графиков (ограничение на количество данных)
    limit = 840
    x_max = 20160
    x_min = x_max - limit

    # Создадим окно с графиком
    fig, ax = plt.subplots(figsize=(10, 5))
    # Выделим область, которую будет занимать график
    fig.subplots_adjust(left=0.01, right=0.95, top=0.95, bottom=0.1)

    # Ограничиваем данные последними строками числом limit
    df = df.tail(x_max)

    # # Очищаем текущее окно
    # plt.cla()

    t = df['DateTime'].apply(lambda x: format_date_time(x))

    name1 = df.columns[1]
    name2 = df.columns[2]
    name3 = df.columns[3]
    name4 = df.columns[4]
    name5 = df.columns[5]
    s0 = df[name1]
    s1 = df[name2]
    s2 = df[name3]
    s3 = df[name4]
    s4 = df[name5]

    # Создаём скользящее окно
    window = df.rolling(1)  # Замените '1' на нужное вам количество строк

    # Строим график для каждой колонки в скользящем окне
    l0, = ax.plot(t, s0, lw=2, color='red', label=df.columns[1])
    l1, = ax.plot(t, s1, lw=2, color='orange', label=df.columns[2])
    l2, = ax.plot(t, s2, lw=2, color='green', label=df.columns[3])
    l3, = ax.plot(t, s3, visible=False, lw=2, color='cyan', label=df.columns[4])
    l4, = ax.plot(t, s4, visible=False, lw=2, color='blue', label=df.columns[5])

    # Добавляем подписи с последним значением
    ax.text(x=limit + 2, y=df[df.columns[1]].iloc[len(df) - 1], s="{:.2f}".format(df[df.columns[1]].iloc[len(df) - 1]),
            color="red", fontsize=9)
    ax.text(x=limit + 2, y=df[df.columns[2]].iloc[len(df) - 1], s="{:.2f}".format(df[df.columns[2]].iloc[len(df) - 1]),
            color="orange", fontsize=9)
    ax.text(x=limit + 2, y=df[df.columns[3]].iloc[len(df) - 1], s="{:.2f}".format(df[df.columns[3]].iloc[len(df) - 1]),
            color="green", fontsize=9)
    ax.text(x=limit + 2, y=df[df.columns[4]].iloc[len(df) - 1], s="{:.2f}".format(df[df.columns[4]].iloc[len(df) - 1]),
            color="cyan", fontsize=9)
    ax.text(x=limit + 2, y=df[df.columns[5]].iloc[len(df) - 1], s="{:.2f}".format(df[df.columns[5]].iloc[len(df) - 1]),
            color="blue", fontsize=9)

    lines_by_label = {l.get_label(): l for l in [l0, l1, l2, l3, l4]}
    line_colors = [l.get_color() for l in lines_by_label.values()]

    # Создадим слайдер для задания интервала по оси X
    axes_slider_x_range = plt.axes([0.03, 0.01, 0.80, 0.04])
    slider_x_range = RangeSlider(
        axes_slider_x_range,
        label="x",
        valmin=0,
        valmax=20160,
        valinit=(x_min, x_max),
        valstep=1,
        valfmt="%0.0f",
    )

    # !!! Подпишемся на событие изменения интервала по оси X
    slider_x_range.on_changed(onChangeXRange)

    # Make checkbuttons with all plotted lines with correct visibility (координата X левой границы, координата Y нижней границы, ширина, высота)
    rax = ax.inset_axes([0.01, 0.01, 0.12, 0.26])
    check = CheckButtons(
        ax=rax,
        labels=lines_by_label.keys(),
        actives=[l.get_visible() for l in lines_by_label.values()],
        label_props={'color': line_colors},
        frame_props={'edgecolor': line_colors},
        check_props={'facecolor': line_colors},
    )

    check.on_clicked(callback)

    updateGraph()
    plt.show()