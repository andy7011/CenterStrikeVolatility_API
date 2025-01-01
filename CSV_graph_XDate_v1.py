import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import datetime

# Указываем путь к файлу CSV
fn = r'C:\Users\шадрин\YandexDisk\_ИИС\Position\CenterStrikeVola_RTS.csv'

# Читаем CSV/TXT файл (разделённый точкой с запятой) в DataFrame
df = pd.read_csv(fn, sep=';')

# Устанавливаем ограничение на количество данных
limit = 2700

# Создаём график и оси
fig, ax = plt.subplots()

# Проходимся по всем столбцам, кроме первого и последнего
for i in range(1, len(df.columns) - 1):
    # Ограничиваем данные последними строками числом limit
    df = df.tail(limit)

    # Преобразуем первую колонку в объект datetime
    DateTime = datetime.datetime.strptime(df['DateTime'].iloc[0], "%d.%m.%Y %H:%M:%S")

    # Строим график для каждой колонки
    df.plot(x='DateTime', y=df.columns[i], rot=0, figsize=(16, 8), grid=True, marker=None, ax=ax)

    # Получаем последнее значение из текущей столбца
    last_value = df[df.columns[i]].iloc[-1]

    # Добавляем текст с последним значением справа от графика
    ax.text(x=DateTime, y=last_value, s=f"{last_value:.2f}", color="red")

    # # Добавляем подписи с первым и последним значением
    # ax.text(x=df['DateTime'][0], y=df[df.columns[i]].max(), s=f"Первое значение: {df[df.columns[i]][0]:.2f}", color="red")  # Первое значение
    # ax.text(x=df['DateTime'][-1], y=df[df.columns[i]].min(), s=f"Последнее значение: {df[df.columns[i]][-1]:.2f}", color="green")  # Последнее значение

# Вызовем subplot явно, чтобы получить экземпляр класса AxesSubplot,
# из которого будем иметь доступ к осям
axes = plt.subplot(1, 1, 1)

# # Поворачиваем метки на оси Y вправо
# ax.yaxis.tick_right()
# ax.yaxis.set_label_position("right")

# Настраиваем отображение дат на оси X
# plt.gca().xaxis.set_major_locator(mdates.DayLocator())
# plt.gca().xaxis.set_minor_locator(mdates.HourLocator(interval=1))
# plt.gca().format_xdata = mdates.DateFormatter('%d.%m\n%H:%M')
plt.title("Center strike vola")  # Добавляем заголовок графика

# Автоматически настраиваем расположение элементов графика
fig.tight_layout()
plt.show()  # Отображаем график