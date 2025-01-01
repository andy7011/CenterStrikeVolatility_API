import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import datetime

fn = r'C:\Users\шадрин\YandexDisk\_ИИС\Position\CenterStrikeVola_RTS.csv'
df = pd.read_csv(fn, sep=';')
limit = 2700
fig, ax = plt.subplots()

# Определяем временные промежутки для удаления
remove_times = ['23:51-10:00', '14:01-14:05', '18:51-19:05']

# Функция для проверки, нужно ли удалять интервал
def should_remove_interval(row):
    return not any(t in str(row.DateTime) for t in remove_times)

# Применяем функцию к DataFrame
df = df[~df.apply(should_remove_interval, axis=1)]

# Преобразуем DateTime в формат datetime
df['DateTime'] = pd.to_datetime(df['DateTime'], format='%d.%m.%Y %H:%M:%S')

# Удаляем ненужные временные промежутки
df = df[(df['DateTime'] >= '10:00') &
       (df['DateTime'] <= '23:59')]

for i in range(1, len(df.columns)-1):
    df = df.tail(limit)
    df.plot(x='DateTime', y=df.columns[i], rot=0, figsize=(16, 8), grid=True, marker=None, ax=ax)

ax.yaxis.tick_right()
ax.yaxis.set_label_position("right")
fig.tight_layout()
plt.legend()
plt.show()
