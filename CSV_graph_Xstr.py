# Импортируем необходимые библиотеки
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib
import datetime

# Указываем путь к файлу CSV
fn = r'C:\Users\Андрей\YandexDisk\_ИИС\Position\CenterStrikeVola_RTS.csv'

# # Читаем CSV/TXT файл (разделённый точкой с запятой) в DataFrame
df = pd.read_csv(fn, sep=';')

# Устанавливаем ограничение на количество данных
limit = 1000

# Создаём график и оси
fig, ax = plt.subplots()

# Ограничиваем данные последними строками числом limit
df = df.tail(limit)

# Проходимся по всем столбцам, кроме первого и последнего
for i in range(1, len(df.columns) - 1):
    # # Ограничиваем данные последними строками числом limit
    # df = df.tail(limit)

    # Преобразуем первую колонку в объект datetime
    DateTime = datetime.datetime.strptime(df['DateTime'].iloc[0], "%d.%m.%Y %H:%M:%S")

    # Строим график для каждой колонки
    df.plot(x='DateTime', y=df.columns[i], rot=0, figsize=(16, 8), grid=True, marker=None, ax=ax)

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
plt.title("Center strike vola")  # Добавляем заголовок графика

fig.tight_layout()  # Автоматически настраиваем расположение элементов графика
plt.show()  # Отображаем график