import requests
from moex_api import get_option_list_by_series, _convert_moex_data_structure_to_list_of_dicts, get_security_description, get_option_board

# response = get_security_description('SPBOPT')
# print(response)

data = get_option_board('RIM6', '2026-06-18')
print(data)

# response = get_option_board

# list_of_dicts = _convert_moex_data_structure_to_list_of_dicts(option_list)






