# Импортируем необходимые библиотеки
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import matplotlib.dates as mdates
import matplotlib
import datetime

# Указываем путь к файлу CSV
fn = r'C:\Users\шадрин\YandexDisk\_ИИС\Position\CenterStrikeVola_RTS.csv'

# Создаём график и оси
fig, ax = plt.subplots()

# Устанавливаем ограничение на количество данных
limit = 1200

# def init():
#     line.set_data(x[:2],y[:2])
#     return line,

def animate(i):
    # Читаем CSV/TXT файл (разделённый точкой с запятой) в DataFrame
    df = pd.read_csv(fn, sep=';')

    # Ограничиваем данные последними строками числом limit
    df = df.tail(limit)

    # Преобразуем первую колонку в объект datetime
    DateTime = datetime.datetime.strptime(df['DateTime'].iloc[0], "%d.%m.%Y %H:%M:%S")

    # Очищаем текущее окно
    plt.cla()

    # Создаём скользящее окно
    window = df.rolling(1)  # Замените '10' на нужное вам количество строк

    # Строим график для каждой колонки в скользящем окне
    for i in range(1, len(df.columns) - 1):
        df.plot(x='DateTime', y=df.columns[i], rot=0, figsize=(12, 6), grid=True, marker=None, ax=ax)

        # Добавляем подписи с последним значением
        ax.text(x=limit + 5, y=df[df.columns[i]].iloc[len(df) - 1],
                s="{:.2f}".format(df[df.columns[i]].iloc[len(df) - 1]), color=plt.cm.jet(i))

    # Вызовем subplot явно, чтобы получить экземпляр класса AxesSubplot,
    # из которого будем иметь доступ к осям
    axes = plt.subplot(1, 1, 1)

    # Поворачиваем метки на оси Y вправо
    ax.yaxis.tick_right()
    ax.yaxis.set_label_position("right")

    # Настраиваем отображение дат на оси X
    plt.title("Center strike vola RTS")  # Добавляем заголовок графика

    fig.tight_layout()  # Автоматически настраиваем расположение элементов графика

ani = animation.FuncAnimation(fig, animate, interval=60000, cache_frame_data=False)
plt.show()  # Отображаем график