import csv
import pandas as pd
from string import Template

# Конфигурация для работы с файлами
temp_str = 'C:\\Users\\ashadrin\\YandexDisk\\_ИИС\\Position\\$name_file'
temp_obj = Template(temp_str)


# Чтение csv файла
data_options_vola = pd.read_csv(temp_obj.substitute(name_file='OptionsVolaHistoryDamp.csv'), sep=';')

print(data_options_vola['expiration_datetime'])
# print(data_options_vola.columns)

# # Удалить столбец из DataFrame
# data_options_vola = data_options_vola.drop('last_price_timestamp', axis=1)
# print(data_options_vola)
# print(data_options_vola.columns)

# Конвертирование столбца с датой в виде строки 'expiration_datetime' в формат дата и время
data_options_vola['expiration_datetime'] = pd.to_datetime(data_options_vola['expiration_datetime'])


print(data_options_vola['expiration_datetime'])
# Конвертирование столбца с датой 'expiration_datetime' в строку формата '%Y-%m-%d %H:%M:%S'
data_options_vola['expiration_datetime'] = data_options_vola['expiration_datetime'].dt.strftime('%Y-%m-%d')
print(data_options_vola['expiration_datetime'])


# Запись в csv файл
data_options_vola.to_csv(temp_obj.substitute(name_file='OptionsVolaHistoryDamp.csv'), sep=';', index=False)



