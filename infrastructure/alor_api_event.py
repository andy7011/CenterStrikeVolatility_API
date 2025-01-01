EVENT_TYPE_QUOTES = 'quotes'
EVENT_TYPE_INSTRUMENT = 'instrument'


class AlorApiEvent:
    def __init__(self, ticker: str, callback: callable):
        self._ticker = ticker
        self._callback = callback

    @property
    def ticker(self) -> str:
        return self._ticker

    @property
    def callback(self) -> callable:
        return self._callback
