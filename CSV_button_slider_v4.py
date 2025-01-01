from typing import Tuple
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import json
from matplotlib.widgets import RangeSlider, Slider, RadioButtons, CheckButtons

# Указываем путь к файлу CSV
fn = r'C:\Users\Андрей\YandexDisk\_ИИС\Position\_TEST_CenterStrikeVola_RTS.csv'

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
    graph_state_file = open('graph_state_v4.json', 'w', encoding="utf-8")
    json.dump(graph_state, graph_state_file)
    graph_state_file.close()

def updateGraph():
    """!!! Функция для обновления графика"""
    global slider_x_range
    global graph_axes
    global x_min
    global x_max
    global checkbuttons_grid
    global checkbuttons_series
    global rows_count
    global lines_by_label
    global graph_state  # Добавляем словарь для хранения статуса видимости графиков
    global l

    # Читаем CSV/TXT файл (разделённый точкой с запятой) в DataFrame
    df = pd.read_csv(fn, sep=';')
    rows_count = len(df)

    # # Метки столбцов
    # name1 = df.columns[1]
    # name2 = df.columns[2]
    # name3 = df.columns[3]
    # name4 = df.columns[4]
    # name5 = df.columns[5]
    # lines_by_label = {name1, name2, name3, name4, name5}
    # line_colors = {"red", "orange", "green", "cyan", "blue"}

    # Начальные параметры графиков
    # 840 - кол.торговых минуток за сутки
    limit_day = 840
    # Кол.торговых минуток за месяц 17640 = 840 мин x 21 раб.день
    limit_month = 17640
    x_max = rows_count
    x_min = rows_count - limit_day
    # print(x_min)
    # print(x_max)


    # Получаем значение интервала
    x_min, x_max = slider_x_range.val

    # Ограничиваем данные числом limit_month
    df = df.tail(limit_month)
    df_slider = df.loc[x_min:x_max]

    # unwanted = [column for column in df_slider.columns if "-" not in column]
    # print(unwanted)
    # df_slider = df_slider.drop(unwanted)
    df_slider = df_slider.drop([col for col in df_slider.columns if '-'.lower() in col.lower()], axis=1)

    t = df_slider['DateTime'].apply(lambda x: format_date_time(x))

    graph_axes.clear()

    l = {}

    for i in range(1, len(df_slider.columns)):
        # # Создаём скользящее окно
        # window = df_slider.rolling(1)  # Замените '1' на нужное вам количество строк

        # Строим график для каждой колонки
        # df.plot(x='DateTime', y=df_slider.columns[i], rot=0, figsize=(16, 8), grid=True, marker=None, label=df_slider.columns[i], ax=graph_axes)
        t = df_slider['DateTime'].apply(lambda x: format_date_time(x))
        l[i-1], = graph_axes.plot(t, zero_to_nan(df_slider[df_slider.columns[i]]), lw=2, color=plt.cm.jet(i), label=df.columns[i])
        # Добавляем подписи с последним значением
        graph_axes.text(x=len(df_slider) + 5, y=df_slider[df_slider.columns[i]].iloc[len(df_slider) - 1],
                s="{:.2f}".format(df_slider[df_slider.columns[i]].iloc[len(df_slider) - 1]), color=plt.cm.jet(i))

    lines_by_labels = []
    for i in range(1, 7):
        lines_by_label = df_slider.columns[i]
        lines_by_labels.append(lines_by_label)
    print(lines_by_labels)

    # lines_by_label = df_slider.columns[i]
    # lines_by_label = {l.get_label(): l for l in [l0, l1, l2, l3, l4, l5]}
    # line_colors = [l.get_color() for l in lines_by_label.values()]

    # Поворачиваем метки на оси Y вправо
    graph_axes.yaxis.tick_right()
    graph_axes.yaxis.set_label_position("right")

    # Настраиваем отображение дат на оси X
    graph_axes.set(xlabel=None)
    graph_axes.grid(True)
    graph_axes.xaxis.set_major_locator(plt.MultipleLocator((x_max - x_min) / 8))

    for label, visible in graph_state.items():  # Восстанавливаем статус видимости графиков
        if visible:
            lines_by_labels[label].set_visible(True)
        else:
            lines_by_labels[label].set_visible(False)

    # Определим, нужно ли показывать сетку на графике
    grid_visible = checkbuttons_grid.get_status()[0]
    graph_axes.grid(grid_visible)

    dump_graph_state_to_file()

    plt.draw()

def onCheckClicked1(label):
    """" Обработчик события при нажатии на флажок"""
    ln = lines_by_label[label]
    ln.set_visible(not ln.get_visible())
    series_visible = checkbuttons_series.get_status()[0]

    # Здесь добавляем логику для отображения или скрытия серии опционов
    if series_visible:
        print("Серия опционов видна")
        ln.figure.canvas.draw_idle()
    else:
        ln.set_visible(not ln.get_visible())
        print("Серия опционов скрыта")
        plt.draw()
        updateGraph()

    # Сохраняем статус видимости графиков
    global graph_state
    graph_state[label] = ln.get_visible()

def onCheckClicked2(value: str):
    """ Обработчик события при нажатии на флажок"""
    updateGraph()

def onChangeXRange(value: Tuple[np.float64, np.float64]):
    """Обработчик события измерения значения интервала по оси X"""
    updateGraph()

if __name__ == "__main__":
    global limit_month
    global x_min
    global x_max
    # Читаем CSV/TXT файл (разделённый точкой с запятой) в DataFrame
    df = pd.read_csv(fn, sep=';')
    rows_count = len(df)

    # line_colors = {"red", "orange", "green", "cyan", "blue"}

    # Начальные параметры графиков
    # 840 - кол. торговых минуток за сутки
    limit_day = 840
    # Кол.торговых минуток за месяц 17640 = 840 мин x 21 раб.день
    limit_month = 17640
    x_max = rows_count
    x_min = rows_count - limit_day

    # Ограничиваем данные числом limit_month
    df = df.tail(limit_month)
    df_slider = df.loc[x_min:x_max]
    df_slider = df_slider.drop([col for col in df_slider.columns if '-'.lower() in col.lower()], axis=1)

    # Создадим окно с графиком
    fig, graph_axes = plt.subplots(figsize=(10, 5))

    # Выделим область, которую будет занимать график
    fig.subplots_adjust(left=0.01, right=0.95, top=0.99, bottom=0.1)

    # plt.title("Center strike vola RTS")  # Добавляем заголовок графика
    # plt.title("Center strike vola RTS", color="blue", size=14, y=0.95, loc="left")

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
    axes_checkbuttons1 = plt.axes([0.01, 0.1, 0.14, 0.36])

    # Инициализируем словарь для хранения статуса видимости графиков
    graph_state_file = open('graph_state_v4.json', 'r', encoding="utf-8")
    graph_state = json.load(graph_state_file)
    graph_state_file.close()

    checkbuttonLabels = []
    checkbuttonStates = []
    for i in range(1, 7):
        checkbuttonLabel = df_slider.columns[i]
        checkbuttonLabels.append(checkbuttonLabel)
        checkbuttonStates.append(graph_state[checkbuttonLabel])
    print(checkbuttonLabels)
    print(checkbuttonStates)

    # Создадим флажок выключателя опционных серий
    checkbuttons_series = CheckButtons(
        ax=axes_checkbuttons1,
        labels=checkbuttonLabels,
        actives=checkbuttonStates,
        label_props={'color':["red", "orange", "green", "cyan", "blue"]},
        frame_props={'edgecolor': 'black'},
        check_props={'facecolor': 'black'},
    )

    # # Инициализируем словарь для хранения статуса видимости графиков
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
    plt.show()