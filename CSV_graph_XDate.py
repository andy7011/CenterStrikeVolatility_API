# Импортируем необходимые библиотеки
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib
import datetime

# Указываем путь к файлу CSV
fn = r'C:\Users\шадрин\YandexDisk\_ИИС\Position\CenterStrikeVola_RTS.csv'

# # Читаем CSV/TXT файл (разделённый точкой с запятой) в DataFrame
# df = pd.read_csv(fn, sep=';', parse_dates=['DateTime'])
# df = pd.read_csv(fn, sep=';', skiprows=1, parse_dates=['DateTime'], date_parser=True)
# df = pd.read_csv(fn, sep=';', skiprows=1, parse_dates={'DateTime': ['%d.%m.%Y %H:%M:%S']})
# df = pd.read_csv(fn, sep=';', skiprows=1, infer_datetime_format=True)
# df = pd.read_csv(fn, sep=';', infer_datetime_format=True)
df = pd.read_csv(fn, sep=';')

# # Преобразуем колонку 'DateTime' в объект datetime
# df['DateTime'] = pd.to_datetime(df['DateTime'])

# # Преобразуем колонку 'DateTime' в нужный формат
# df['DateTime'] = df['DateTime'].dt.strftime('%d.%m %H:%M')
# print(df)

# Устанавливаем ограничение на количество данных
limit = 1000

# Создаём график и оси
fig, ax = plt.subplots()

# Проходимся по всем столбцам, кроме первого и последнего
for i in range(1, len(df.columns) - 1):
    # Ограничиваем данные последними строками числом limit
    df = df.tail(limit)
    # print(df.DateTime)
    # print('Текущая дата и время: {}'.format(datetime.datetime.now()))

    # Преобразуем первую колонку в объект datetime
    # DateTime = datetime.datetime.strptime(df.DateTime, "%d.%m.%Y %H:%M:%S")
    # DateTime = datetime.datetime.strptime(df['DateTime'][0], "%d.%m.%Y %H:%M:%S")
    DateTime = datetime.datetime.strptime(df['DateTime'].iloc[0], "%d.%m.%Y %H:%M:%S")

    # Строим график для каждой колонки
    # df.plot(x='DateTime', y=df.columns[i], rot=0, figsize=(16, 8), grid=True, marker=None, ax=ax, c=plt.cm.jet(i))
    df.plot(x='DateTime', y=df.columns[i], rot=0, figsize=(16, 8), grid=True, marker=None, ax=ax)

    # Добавляем подписи с последним значением
    # ax.text(x=limit + 5, y=df[df.columns[i]].iloc[len(df) - 1],
    #                 s="{:.2f}".format(df[df.columns[i]].iloc[len(df) - 1]),
    #                 color=plt.cm.jet(i))
    ax.text(x=limit + 5, y=df[df.columns[i]].iloc[len(df) - 1],
            s="{:.2f}".format(df[df.columns[i]].iloc[len(df) - 1]))

# Вызовем subplot явно, чтобы получить экземпляр класса AxesSubplot,
# из которого будем иметь доступ к осям
axes = plt.subplot(1, 1, 1)

# Поворачиваем метки на оси Y вправо
ax.yaxis.tick_right()
ax.yaxis.set_label_position("right")

# Настраиваем отображение дат на оси X
# ax.xaxis.set_major_locator(mdates.DayLocator())
# ax.xaxis.set_minor_locator(mdates.HourLocator(interval=1))
# ax.format_xdata = mdates.DateFormatter('%d.%m\n%H:%M')
plt.title("Center strike vola")  # Добавляем заголовок графика

# plt.subplots_adjust(wspace=1, hspace=1)  # Настраиваем расстояние между графиками
# plt.subplots_adjust(left=0.02, right=0.99)  # Настраиваем размер области графика
fig.tight_layout()  # Автоматически настраиваем расположение элементов графика
plt.show()  # Отображаем график