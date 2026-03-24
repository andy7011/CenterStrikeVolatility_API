import requests
from moex_api import get_option_list_by_series, _convert_moex_data_structure_to_list_of_dicts, get_security_description, get_option_board, get_option_series, get_option_expirations

# response = get_security_description('SPBOPT')
# print(response)

data = get_option_board('RIM6', '2026-06-18')
print(f'data: {data}')


description = get_security_description('RIM6')
print(f'description {description}')


series = get_option_series('RIM6')
print(f'series: {series}')


expirations = get_option_expirations('RIM6')
print(f'expirations: {expirations}')

option_board = get_option_board('RIM6', '2026-06-18')
print(f'option_board: {option_board}')


# response = get_option_board

# list_of_dicts = _convert_moex_data_structure_to_list_of_dicts(option_list)






