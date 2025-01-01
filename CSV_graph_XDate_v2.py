import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import datetime

# Указываем путь к файлу CSV
fn = r'C:\Users\шадрин\YandexDisk\_ИИС\Position\CenterStrikeVola_RTS.csv'

# Читаем CSV/TXT файл (разделённый точкой с запятой) в DataFrame
df = pd.read_csv(fn, sep=';')

# Устанавливаем ограничение на количество данных
limit = 1000

# Создаём график и оси
fig, ax = plt.subplots()

# Проходимся по всем столбцам, кроме первого и последнего
for i in range(1, len(df.columns)-1):
    # Ограничиваем данные последними строками числом limit
    df = df.tail(limit)

    # Преобразуем первую колонку в объект datetime
    # df['DateTime'] = pd.to_datetime(df['DateTime'], format='%d.%m.%Y %H:%M:%S')
    df['DateTime'] = pd.to_datetime(df['DateTime'], dayfirst=True)

    # Строим график для каждой колонки
    df.plot(x='DateTime', y=df.columns[i], rot=0, figsize=(16, 8), grid=True, marker=None, ax=ax)

    # Добавляем подписи с последним значением
    ax.text(x=df['DateTime'].iloc[len(df) - 1], y=df[df.columns[i]].iloc[len(df) - 1], s="{:.2f}".format(df[df.columns[i]].iloc[len(df) - 1]),
            color=plt.cm.jet(i))  # Последнее значение


# Настройка отображения дат на оси X
locator = mdates.HourLocator() # устанавливаем локатор для дней
formatter = mdates.DateFormatter('%d.%m %H:%M') # устанавливаем формат отображения дат
plt.gca().xaxis.set_major_locator(locator) # применяем локатор к оси X
# plt.gca().xaxis.set_minor_locator(mdates.HourLocator(interval=1)) # добавляем второстепенные линии сетки по часам
plt.gca().format_xdata = formatter # отображаем даты в нужном формате

# Вызовем subplot явно, чтобы получить экземпляр класса AxesSubplot,
# из которого будем иметь доступ к осям
axes = plt.subplot(1, 1, 1)

# Поворачиваем метки на оси Y вправо
ax.yaxis.tick_right()
ax.yaxis.set_label_position("right")

# Автоматически настраиваем расположение элементов графика
fig.tight_layout()
plt.legend()  # Отображаем легенду
plt.show()  # Отображаем график