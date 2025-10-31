import csv
import os
from datetime import datetime

# Путь к файлу через шаблон
file_path = temp_obj.substitute(name_file='MyPosTilt.csv')

# Формируем данные для записи (по одной строке на каждую запись)
rows_to_write = []
for _, row in merged.iterrows():
    rows_to_write.append([
        current_DateTimestamp.strftime('%Y-%m-%d %H:%M:%S'),
        pd.to_datetime(row['expdate']).strftime('%Y-%m-%d'),
        row['optionbase'],
        round(row['Real_vol_up'] - row['Real_vol_down'], 2),
        round(row['QuikVola_up'] - row['QuikVola_down'], 2),
        round(row['MyPosTilt_up'] - row['MyPosTilt_down'], 2)
    ])

# Определяем, существует ли файл и пустой ли он
file_exists = os.path.isfile(file_path)
file_empty = not file_exists or os.path.getsize(file_path) == 0

# Открываем файл на дозапись
with open(file_path, 'a', newline='', encoding='utf-8') as f:
    writer = csv.writer(f, delimiter=';', lineterminator='\r\n')  # \r\n — стандартный перенос для Windows

    # Если файл новый или пустой — пишем заголовок
    if file_empty:
        writer.writerow(['DateTime', 'expdate', 'optionbase', 'RealTilt', 'QuikTilt', 'MyPosTilt'])

    # Пишем данные
    writer.writerows(rows_to_write)

print(f"Данные добавлены в {file_path}")
