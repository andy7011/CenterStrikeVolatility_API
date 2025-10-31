import pandas as pd

# Предполагается:
# - result_up и result_down: DataFrame после groupby + weighted_mean
# - Они имеют колонки: optionbase, expdate, Real_vol_up, QuikVola_up, MyPosTilt_up (и аналогично _down)
# - current_DateTimestamp: объект datetime.datetime

# Шаг 1: Слияние по optionbase и expdate
merged = pd.merge(
    result_up,
    result_down,
    on=['optionbase', 'expdate'],
    suffixes=('_up', '_down'),
    how='inner'  # только где есть и up, и down
)

# Шаг 2: Вычисляем тилты (разности)
merged['RealTilt'] = merged['Real_vol_up'] - merged['Real_vol_down']
merged['QuikTilt'] = merged['QuikVola_up'] - merged['QuikVola_down']
merged['MyPosTilt'] = merged['MyPosTilt_up'] - merged['MyPosTilt_down']

# Шаг 3: Формируем итоговый DataFrame
output_df = pd.DataFrame({
    'DateTime': current_DateTimestamp.strftime('%Y-%m-%d %H:%M:%S'),  # одинаковое время для всех строк
    'expdate': pd.to_datetime(merged['expdate']).dt.strftime('%Y-%m-%d'),  # формат ГГГГ-ММ-ДД
    'optionbase': merged['optionbase'],
    'RealTilt': merged['RealTilt'],
    'QuikTilt': merged['QuikTilt'],
    'MyPosTilt': merged['MyPosTilt']
})

# Шаг 4: Сохраняем в CSV с разделителем ';'
output_df.to_csv('MyPosTilt.csv', sep=';', index=False, float_format='%.2f')

print("Файл MyPosTilt.csv успешно сохранён.")
