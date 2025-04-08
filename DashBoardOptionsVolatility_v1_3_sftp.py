import os
import math
import time
import random
import socket
import shutil
import logging
import threading
from queue import Queue
from functools import lru_cache
from string import Template
from datetime import datetime, timedelta

import dash
from dash import dcc, html, Input, Output, callback, dash_table, State
import dash_daq as daq
from dash.exceptions import PreventUpdate
import pandas as pd
import requests
import paramiko
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from pytz import utc, timezone

# Локальные импорты
from central_strike import _calculate_central_strike
from supported_base_asset import MAP

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Конфигурация
SFTP_CONFIG = {
    "host": os.getenv("SFTP_HOST", "195.146.92.68"),
    "port": int(os.getenv("SFTP_PORT", 22)),
    "username": os.getenv("SFTP_USER", "sftpuser"),
    "password": os.getenv("SFTP_PASS", "25JQrAnT7")
}

API_ENDPOINT = "https://option-volatility-dashboard.ru/dump_model"
TEMP_FILE_PATH = Template('C:\\Users\\sftpuser\\Position\\$name_file')

# Инициализация приложения Dash
app = dash.Dash(__name__)
server = app.server


class APILoader:
    """Класс для асинхронной загрузки данных с API"""

    def __init__(self):
        self.queue = Queue()
        self.running = False
        self.thread = None

    def start(self):
        """Запуск потока загрузки данных"""
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._load_data, daemon=True)
            self.thread.start()

    def stop(self):
        """Остановка потока"""
        self.running = False
        if self.thread:
            self.thread.join()

    def _load_data(self):
        """Основной метод загрузки данных"""
        while self.running:
            try:
                model_data = get_object_from_json_endpoint_with_retry(
                    API_ENDPOINT,
                    timeout=5
                )
                self.queue.put({
                    'status': 'success',
                    'data': model_data,
                    'timestamp': datetime.now()
                })
            except Exception as e:
                logger.error(f"API Loader error: {str(e)}")
                self.queue.put({
                    'status': 'error',
                    'error': str(e),
                    'timestamp': datetime.now()
                })
            time.sleep(10)  # Интервал между запросами


class SFTPManager:
    """Менеджер SFTP соединений с обработкой ошибок"""

    def __init__(self, host, port, username, password):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.transport = None
        self.sftp_client = None
        self.queue = Queue()
        self.running = False
        self.chunk_size = 1024 * 1024  # 1MB chunks
        self.reconnect_attempts = 3
        self.reconnect_delay = 1  # секунды
        self.lock = threading.Lock()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

    def connect(self):
        """Установка соединения с SFTP сервером"""
        for attempt in range(self.reconnect_attempts):
            try:
                self.transport = paramiko.Transport((self.host, self.port))
                self.transport.default_window_size = 4294967294
                self.transport.packetizer.REKEY_BYTES = pow(2, 32)
                self.transport.packetizer.REKEY_PACKETS = pow(2, 32)
                self.transport.connect(
                    username=self.username,
                    password=self.password
                )
                self.sftp_client = paramiko.SFTPClient.from_transport(self.transport)
                self.running = True
                logger.info("SFTP connection established")
                return True
            except Exception as e:
                logger.warning(f"Connection attempt {attempt + 1} failed: {str(e)}")
                if attempt < self.reconnect_attempts - 1:
                    time.sleep(self.reconnect_delay)
                continue
        logger.error("Failed to establish SFTP connection")
        return False

    def disconnect(self):
        """Закрытие соединения"""
        if self.sftp_client:
            self.sftp_client.close()
        if self.transport:
            self.transport.close()
        self.running = False
        logger.info("SFTP connection closed")

    def download_file(self, remote_path, local_path):
        """
        Безопасная загрузка файла с проверками:
        - Доступность директории
        - Права на запись
        - Достаточно места на диске
        """
        try:
            # Проверка и создание директории
            local_dir = os.path.dirname(local_path)
            os.makedirs(local_dir, exist_ok=True)

            if not os.access(local_dir, os.W_OK):
                raise PermissionError(f"No write permissions for directory {local_dir}")

            # Проверка свободного места
            remote_size = self.sftp_client.stat(remote_path).st_size
            free_space = shutil.disk_usage(local_dir).free

            if free_space < remote_size:
                raise IOError(f"Not enough disk space. Required: {remote_size}, Available: {free_space}")

            # Загрузка файла с прогрессом
            start_time = time.time()
            downloaded = 0

            with self.sftp_client.open(remote_path, 'rb', bufsize=self.chunk_size) as remote:
                remote.prefetch(remote_size)

                with open(local_path, 'wb') as local:
                    while True:
                        chunk = remote.read(self.chunk_size)
                        if not chunk:
                            break

                        local.write(chunk)
                        downloaded += len(chunk)
                        progress = (downloaded / remote_size) * 100

                        self.queue.put({
                            'progress': progress,
                            'status': 'downloading',
                            'downloaded': downloaded,
                            'total': remote_size
                        })

                        if time.time() - start_time > 300:  # 5 minutes timeout
                            raise TimeoutError("File download timeout exceeded")

            self.queue.put({
                'status': 'completed',
                'progress': 100,
                'file_size': remote_size
            })
            return True

        except Exception as e:
            logger.error(f"File download failed: {str(e)}")
            self.queue.put({
                'status': 'error',
                'error': str(e)
            })
            return False


# Глобальные объекты (инициализируются в callbacks)
api_loader = None
sftp_manager = None


def download_file_via_sftp(remote_filename, local_filename):
    """Безопасная загрузка файла через SFTP с глобальным менеджером"""
    global sftp_manager

    try:
        # Проверка входных параметров
        if not remote_filename or not isinstance(remote_filename, str):
            raise ValueError(f"Invalid remote filename: {remote_filename}")

        if not local_filename or not isinstance(local_filename, str):
            raise ValueError(f"Invalid local filename: {local_filename}")

        # Инициализация SFTP соединения
        if sftp_manager is None:
            sftp_manager = SFTPManager(**SFTP_CONFIG)
            if not sftp_manager.connect():
                raise Exception("Failed to initialize SFTP connection")

        # Формирование путей
        remote_path = TEMP_FILE_PATH.safe_substitute(name_file=remote_filename)
        local_dir = os.path.dirname(local_filename)

        logger.info(f"Starting download: {remote_path} -> {local_filename}")

        # Создание локальной директории
        os.makedirs(local_dir, exist_ok=True)

        # Проверка существования удаленного файла
        try:
            sftp_manager.sftp_client.stat(remote_path)
        except FileNotFoundError:
            raise Exception(f"Remote file not found: {remote_path}")

        # Выполнение загрузки
        success = sftp_manager.download_file(remote_path, local_filename)

        if not success:
            raise Exception(f"Download failed for {remote_filename}")

        logger.info(f"Successfully downloaded: {remote_path}")
        return True

    except Exception as e:
        logger.error(f"File download error: {str(e)}")
        if 'sftp_manager' in globals() and sftp_manager:
            sftp_manager.disconnect()
        raise

# Вспомогательные функции
def utc_to_msk_datetime(dt, tzinfo=False):
    """Перевод времени из UTC в московское"""
    if not dt.tzinfo:
        dt = utc.localize(dt)
    tz_msk = timezone('Europe/Moscow')
    dt_msk = dt.astimezone(tz_msk)
    return dt_msk if tzinfo else dt_msk.replace(tzinfo=None)


def utc_timestamp_to_msk_datetime(seconds) -> datetime:
    """Перевод UNIX timestamp в московское время"""
    dt_utc = datetime.fromtimestamp(seconds, tz=utc)
    return utc_to_msk_datetime(dt_utc)


def check_port_availability(host, port, timeout=5):
    """Проверка доступности порта"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            result = sock.connect_ex((host, port))
            return result == 0
    except Exception as e:
        logger.error(f"Port check error: {str(e)}")
        return False


@lru_cache(maxsize=32)
def get_object_from_json_endpoint_with_retry(url, method='GET', params=None, max_delay=180, timeout=10):
    """
    Получение JSON данных с endpoint с повторными попытками при ошибках
    """
    params = params or {}
    attempt = 0

    while True:
        try:
            response = requests.request(
                method,
                url,
                params=params,
                timeout=timeout
            )
            response.raise_for_status()
            return response.json()

        except requests.exceptions.HTTPError as e:
            if response.status_code != 502:
                raise

            attempt += 1
            delay = min(2 ** attempt, max_delay)
            wait_time = delay * random.uniform(0.5, 1.5)

            logger.warning(
                f"Attempt {attempt}: Got 502 error. Waiting {wait_time:.1f} seconds"
            )
            time.sleep(wait_time)

        except requests.exceptions.Timeout:
            logger.error(f"Timeout while requesting {url}")
            raise
        except Exception as e:
            logger.error(f"Request error: {str(e)}")
            raise


# Layout приложения
app.layout = html.Div([
    # Первый ряд: график улыбки и панель управления
    html.Div([
        # График улыбки волатильности
        html.Div([
            dcc.Graph(id='plot_smile'),
        ], style={'width': '87%', 'display': 'inline-block'}),

        # Панель управления
        html.Div([
            html.H6(id='last_update_time'),

            html.Div([
                dcc.Dropdown(
                    id='dropdown-selection',
                    placeholder="Select base asset"
                ),
            ]),

            daq.Gauge(
                id="graph-gauge",
                units="TrueVega",
                label='TrueVega',
                labelPosition='bottom',
                color={
                    "ranges": {
                        "red": [0, 2],
                        "pink": [2, 4],
                        "#ADD8E6": [4, 6],
                        "#4169E1": [6, 8],
                        "blue": [8, 10],
                    },
                },
                scale={
                    "custom": {
                        1: {"label": "Strong Sell"},
                        3: {"label": "Sell"},
                        5: {"label": "Neutral"},
                        7: {"label": "Buy"},
                        9: {"label": "Strong Buy"},
                    }
                },
                value=0,
                max=10,
                min=0,
            ),
        ], style={'width': '13%', 'display': 'inline-block', 'verticalAlign': 'top'}),
    ], style={'display': 'flex'}),

    # Второй ряд: история волатильности
    html.Div([
        dcc.RadioItems(
            id='my-radio-buttons-final',
            options=['Call', 'Put'],
            value='Call',
            inline=True,
            style={'display': 'flex', 'justifyContent': 'right'}
        ),

        dcc.Graph(id='plot_history'),

        dcc.Slider(
            id='my_slider',
            min=0,
            max=28,
            step=None,
            marks={
                1: '0.5d',
                2: '1d',
                6: '3d',
                14: '7d',
                28: '14d'
            },
            value=1
        ),

        html.Div(id='slider-output-1'),

        dcc.Interval(
            id='interval-component',
            interval=1000 * 10,  # 10 seconds
            n_intervals=0
        ),

        # Таблица позиций
        html.Div(id='intermediate-value', style={'display': 'none'}),
        dash_table.DataTable(
            id='table',
            page_size=20,
            style_table={'overflowX': 'auto'},
            style_data_conditional=[
                {
                    'if': {'filter_query': '{P/L} > 1', 'column_id': 'P/L'},
                    'backgroundColor': '#3D9970',
                    'color': 'white'
                }
            ]
        ),
    ])
])


# Callbacks
@app.callback(
    Output('dropdown-selection', 'options'),
    Output('dropdown-selection', 'value'),
    Input('interval-component', 'n_intervals')
)
def update_dropdown(n):
    """Обновление списка базовых активов"""
    try:
        model_data = get_object_from_json_endpoint_with_retry(API_ENDPOINT)
        base_assets = model_data[0]
        options = [{'label': asset['_ticker'], 'value': asset['_ticker']} for asset in base_assets]
        value = base_assets[0]['_ticker'] if base_assets else None
        return options, value
    except Exception as e:
        logger.error(f"Dropdown update error: {str(e)}")
        raise PreventUpdate


@app.callback(
    Output('plot_smile', 'figure'),
    Input('dropdown-selection', 'value'),
    Input('interval-component', 'n_intervals'),
    prevent_initial_call=True
)
def update_volatility_smile(selected_asset, n):
    """Обновление графика улыбки волатильности"""
    global api_loader # Объявляем api_loader как глобальную переменную

    if api_loader is None:
        api_loader = APILoader()
        api_loader.start()

    try:
        if api_loader.queue.empty():
            raise PreventUpdate

        result = api_loader.queue.get()
        if result['status'] != 'success':
            raise Exception(result.get('error', 'Unknown error'))

        model_data = result['data']
        base_assets = model_data[0]
        options = model_data[1]

        # Находим выбранный базовый актив
        selected_base = next((a for a in base_assets if a['_ticker'] == selected_asset), None)
        if not selected_base:
            raise PreventUpdate

        last_price = selected_base['_last_price']

        # Фильтрация опционов
        df = pd.DataFrame(options)
        df = df[df['_volatility'] > 0]
        df['_expiration_datetime'] = pd.to_datetime(df['_expiration_datetime'])
        df['expiration_date'] = df['_expiration_datetime'].dt.strftime('%d.%m.%Y')
        df = df[df['_base_asset_ticker'] == selected_asset]

        # Загрузка данных позиций
        download_file_via_sftp('MyPos.csv', 'data/local_MyPos.csv')
        df_pos = pd.read_csv('data/local_MyPos.csv', sep=';')
        print(df_pos)
        df_pos_buy = df_pos[(df_pos['optionbase'] == selected_asset) & (df_pos['net_pos'] > 0)]
        df_pos_sell = df_pos[(df_pos['optionbase'] == selected_asset) & (df_pos['net_pos'] < 0)]
        print(df_pos_buy)

        # Загрузка данных ордеров
        download_file_via_sftp('MyOrders.csv', 'data/local_MyOrders.csv')
        df_orders = pd.read_csv('data/local_MyOrders.csv', sep=';')
        df_orders = df_orders[df_orders['optionbase'] == selected_asset]

        logger.info(f"Base assets data: {base_assets}")
        logger.info(f"Options data sample: {df.head(2).to_dict()}")
        logger.info(f"Positions data: {df_pos_buy.head(2).to_dict()}")


        # Создание фигуры
        fig = make_subplots(specs=[[{"secondary_y": True}]])

        # Добавление линий для каждого экспаира
        for exp_date in df['expiration_date'].unique():
            exp_data = df[df['expiration_date'] == exp_date]
            fig.add_trace(
                go.Scatter(
                    x=exp_data['_strike'],
                    y=exp_data['_volatility'],
                    mode='lines',
                    name=exp_date,
                    legendgroup='volatility'
                ),
                secondary_y=False
            )

        # Добавление позиций
        fig.add_trace(
            go.Scatter(
                x=df_pos_buy['strike'],
                y=df_pos_buy['OpenIV'],
                mode='markers',
                marker=dict(
                    size=11,
                    symbol="triangle-up",
                    color='green'
                ),
                name='Buy Positions',
                customdata=df_pos_buy[['optiontype', 'net_pos', 'expdate', 'ticker']],
                hovertemplate="<b>%{customdata}</b>"
            )
        )

        fig.add_trace(
            go.Scatter(
                x=df_pos_sell['strike'],
                y=df_pos_sell['OpenIV'],
                mode='markers',
                marker=dict(
                    size=11,
                    symbol="triangle-down",
                    color='red'
                ),
                name='Sell Positions',
                customdata=df_pos_sell[['optiontype', 'net_pos', 'expdate', 'ticker']],
                hovertemplate="<b>%{customdata}</b>"
            )
        )

        # Добавление ордеров
        if not df_orders.empty:
            fig.add_trace(
                go.Scatter(
                    x=df_orders['strike'],
                    y=df_orders['volatility'],
                    mode='markers',
                    marker=dict(
                        size=8,
                        symbol="x",
                        color='orange'
                    ),
                    name='Orders',
                    customdata=df_orders[['operation', 'optiontype', 'expdate', 'price', 'ticker']],
                    hovertemplate="<b>%{customdata}</b>"
                )
            )

        # Добавление вертикальной линии с ценой базового актива
        fig.add_vline(
            x=last_price,
            line_dash='dash',
            line_color='firebrick',
            annotation_text=f'Spot: {last_price}',
            annotation_position='top right'
        )

        fig.update_layout(
            title=f"Volatility Smile - {selected_asset}",
            xaxis_title="Strike",
            yaxis_title="Volatility",
            uirevision='constant'
        )

        # Добавьте вывод информации о графике
        logger.info(f"Figure traces: {fig.to_dict()['data']}")
        logger.info(f"Figure layout: {fig.to_dict()['layout']}")

        return fig

    except Exception as e:
        logger.error(f"Volatility smile update error: {str(e)}")
        raise PreventUpdate


@app.callback(
    Output('plot_history', 'figure'),
    Input('dropdown-selection', 'value'),
    Input('my_slider', 'value'),
    Input('my-radio-buttons-final', 'value'),
    Input('interval-component', 'n_intervals'),
    prevent_initial_call=True
)
def update_history(selected_asset, slider_value, option_type, n):
    """Обновление графика истории волатильности"""
    try:
        # Загрузка исторических данных
        download_file_via_sftp('BaseAssetPriceHistoryDamp.csv', 'data/local_BaseAssetPriceHistoryDamp.csv')
        download_file_via_sftp('OptionsVolaHistoryDamp.csv', 'data/local_OptionsVolaHistoryDamp.csv')

        # Чтение данных
        df_price = pd.read_csv('data/local_BaseAssetPriceHistoryDamp.csv', sep=';')
        df_vol = pd.read_csv('data/local_OptionsVolaHistoryDamp.csv', sep=';')

        # Фильтрация по выбранному активу
        df_price = df_price[df_price['ticker'] == selected_asset]
        df_vol = df_vol[df_vol['base_asset_ticker'] == selected_asset]

        # Фильтрация по типу опциона
        df_vol = df_vol[df_vol['option_type'] == option_type[0]]  # 'C' или 'P'

        # Обработка временных меток
        df_price['DateTime'] = pd.to_datetime(df_price['DateTime'])
        df_vol['DateTime'] = pd.to_datetime(df_vol['DateTime'])

        # Определение временного диапазона
        end_time = df_price['DateTime'].max()
        start_time = end_time - timedelta(hours=12 * slider_value)

        # Фильтрация по времени
        df_price = df_price[df_price['DateTime'] >= start_time]
        df_vol = df_vol[df_vol['DateTime'] >= start_time]

        # Создание графика
        fig = make_subplots(specs=[[{"secondary_y": True}]])

        # Добавление цены базового актива
        fig.add_trace(
            go.Scatter(
                x=df_price['DateTime'],
                y=df_price['price'],
                name='Base Asset Price',
                line=dict(color='blue')
            ),
            secondary_y=False
        )

        # Добавление волатильности для каждого экспаира
        for exp_date in df_vol['expiration_datetime'].unique():
            exp_data = df_vol[df_vol['expiration_datetime'] == exp_date]
            fig.add_trace(
                go.Scatter(
                    x=exp_data['DateTime'],
                    y=exp_data['Real_vol'],
                    name=f"Vol {exp_date}",
                    line=dict(width=1)
                ),
                secondary_y=True
            )

        fig.update_layout(
            title=f"Historical Volatility - {selected_asset} {option_type}",
            xaxis_title="Time",
            yaxis_title="Price",
            yaxis2_title="Volatility",
            uirevision='constant'
        )

        return fig

    except Exception as e:
        logger.error(f"History update error: {str(e)}")
        raise PreventUpdate


@app.callback(
    Output('table', 'data'),
    Input('interval-component', 'n_intervals'),
    Input('dropdown-selection', 'value'),
    prevent_initial_call=True
)
def update_table(n, selected_asset):
    """Обновление таблицы позиций"""
    try:
        # Загрузка данных позиций
        download_file_via_sftp('MyPos.csv', 'data/local_MyPos.csv')

        # Чтение и фильтрация данных
        df = pd.read_csv('data/local_MyPos.csv', sep=';')
        df = df[df['optionbase'] == selected_asset]

        return df.to_dict('records')

    except Exception as e:
        logger.error(f"Table update error: {str(e)}")
        raise PreventUpdate


@app.callback(
    Output('graph-gauge', 'value'),
    Input('interval-component', 'n_intervals'),
    Input('dropdown-selection', 'value'),
    prevent_initial_call=True
)
def update_gauge(n, selected_asset):
    """Обновление индикатора TrueVega"""
    try:
        # Загрузка данных позиций
        download_file_via_sftp('MyPos.csv', 'data/local_MyPos.csv')

        # Чтение и фильтрация данных
        df = pd.read_csv('data/local_MyPos.csv', sep=';')
        df = df[df['optionbase'] == selected_asset]

        # Расчет показателя TrueVega
        tv_buy = df[df['net_pos'] > 0]['TrueVega'].sum()
        tv_sell = df[df['net_pos'] < 0]['TrueVega'].sum()
        total = abs(tv_buy) + abs(tv_sell)

        if total == 0:
            return 0
        return (abs(tv_buy) / total) * 10  # Масштабирование до 0-10

    except Exception as e:
        logger.error(f"Gauge update error: {str(e)}")
        raise PreventUpdate

@app.callback(
    Output('last_update_time', 'children'),
    Input('interval-component', 'n_intervals')
)
def update_time(n):
    """Обновление времени последнего обновления"""
    return f"Last update: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

if __name__ == '__main__':
    try:
        # Инициализация SFTP менеджера
        with SFTPManager(**SFTP_CONFIG) as sftp_manager:
            # Загрузка начальных данных
            download_file_via_sftp('MyPos.csv', 'data/local_MyPos.csv')
            download_file_via_sftp('MyOrders.csv', 'data/local_MyOrders.csv')
            download_file_via_sftp('BaseAssetPriceHistoryDamp.csv', 'data/local_BaseAssetPriceHistoryDamp.csv')
            download_file_via_sftp('OptionsVolaHistoryDamp.csv', 'data/local_OptionsVolaHistoryDamp.csv')

            # Запуск Dash приложения
            app.run_server(debug=True, port=8050)

    except Exception as e:
        logger.critical(f"Application failed: {str(e)}")
    finally:
        # Гарантированное освобождение ресурсов
        if api_loader:
            api_loader.stop()
        logger.info("Application shutdown complete")