from string import Template
import csv

# Конфигурация для работы с файлами
# Путь к файлу на sftp
temp_str_sftp = 'C:\\Users\\sftpuser\\Position\\$name_file'
temp_obj_sftp = Template(temp_str_sftp)
# Путь к файлу на yandex disk
temp_str_ydisk = 'C:\\Users\\ashadrin\\YandexDisk\\_ИИС\\Position\\$name_file'
temp_obj_ydisk = Template(temp_str_ydisk)

with open(temp_obj_sftp.substitute(name_file='BaseAssetPriceHistoryDamp.csv'), 'a', newline='') as f_sftp:
    writer = csv.writer(f_sftp, delimiter=";", lineterminator="\r")
    for asset in base_asset_list:
        DateTime = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ticker = asset.get('_ticker')
        base_asset_last_price = asset.get('_last_price')
        data_price = [DateTime, ticker, base_asset_last_price]
        writer.writerow(data_price)
        strike_step = MAP[ticker]['strike_step']
        central_strike = _calculate_central_strike(base_asset_last_price, strike_step)
        central_strikes_map[ticker] = central_strike
        asset.update({
            'central_strike': central_strike
        })
f_sftp.close()

with open(temp_obj_sftp.substitute(name_file='OptionsVolaHistoryDamp.csv'), 'a', newline='') as f_sftp:
    writer = csv.writer(f_sftp, delimiter=";", lineterminator="\r")
    for option in filtered_option_list:
        current_DateTimestamp = datetime.now()
        currentTimestamp = int(datetime.timestamp(current_DateTimestamp))

        if option['_last_price_timestamp'] is not None and currentTimestamp - option[
            '_last_price_timestamp'] < last_price_lifetime:
            Real_vol = option['_last_price_iv']
        else:
            if option['_ask_iv'] is None or option['_bid_iv'] is None:
                Real_vol = option['_volatility']
            else:
                if option['_ask_iv'] is not None and option['_bid_iv'] is not None and \
                        option['_ask_iv'] > option['_volatility'] > option['_bid_iv']:
                    Real_vol = option['_volatility']
                else:
                    if option['_ask_iv'] < option['_volatility'] and option['_bid_iv'] < option['_volatility'] \
                            or option['_volatility'] < option['_bid_iv']:
                        Real_vol = (option['_ask_iv'] + option['_bid_iv']) / 2

        option['_real_vol'] = Real_vol
        if option['_type'] == 'C':
            option['_type'] = 'Call'
        elif option['_type'] == 'P':
            option['_type'] = 'Put'

        data_options_vola = [current_DateTimestamp.strftime('%Y-%m-%d %H:%M:%S'), option['_type'],
                             option['_expiration_datetime'], option['_base_asset_ticker'], Real_vol]
        writer.writerow(data_options_vola)
f_sftp.close()