import flask
from flask import Flask, jsonify, request
import threading

from app import supported_base_asset
from werkzeug.middleware.proxy_fix import ProxyFix
from infrastructure import env_utils

_BASE_ASSET_TICKER_QUERY_PARAM = 'base_asset_ticker'

class FlaskApp:
    def __init__(self):
        self._option_app = None

    def set_option_app(self, option_app):
        self._option_app = option_app

    def start_app_in_thread(self):
        # Start Flask app in a separate thread
        flask_thread = threading.Thread(target=self._run_flask_app)
        flask_thread.daemon = True
        flask_thread.start()

    def dump_model(self):
        return jsonify(self._option_app.dump_model())

    def dump_watched_instruments(self):
        return jsonify(self._option_app.dump_watched_instruments())

    def get_index_html(self, error_message=None):
        tickers = supported_base_asset.MAP.keys()
        return flask.render_template('index.html', error_message=error_message, tickers=tickers)

    def get_chart_html(self):
        base_asset_ticker = request.args.get(_BASE_ASSET_TICKER_QUERY_PARAM)
        if base_asset_ticker not in supported_base_asset.MAP:
            error_message = f'Тикер ({base_asset_ticker}) не поддерживается. Ниже ссылки на диаграммы по поддерживаемым тикерам.'
            result = self.get_index_html(error_message=error_message)
        else:
            result = flask.render_template('chart.html', base_asset_ticker=base_asset_ticker)
        return result

    def get_chart_json(self):
        base_asset_ticker = request.args.get(_BASE_ASSET_TICKER_QUERY_PARAM)
        result = self._option_app.get_diagram_data(base_asset_ticker)
        return jsonify(result)

    def _run_flask_app(self):
        port = int(env_utils.get_env_or_exit('BACKEND_PORT'))
        app.run(host='0.0.0.0', port=port)


app = Flask(__name__)
app.json_provider_class.compact = False
app.wsgi_app = ProxyFix(
    app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1
)

_flask_app = FlaskApp()


def get_flask_app():
    return _flask_app


@app.route('/', methods=['GET'])
def get_index_html():
    return _flask_app.get_index_html()


@app.route('/chart.json', methods=['GET'])
def get_chart_json():
    return _flask_app.get_chart_json()


@app.route('/chart.html', methods=['GET'])
def get_chart_html():
    return _flask_app.get_chart_html()


@app.route('/dump_model', methods=['GET'])
def dump_model():
    return _flask_app.dump_model()


@app.route('/dump_watched_instruments', methods=['GET'])
def dump_watched_instruments():
    return _flask_app.dump_watched_instruments()
