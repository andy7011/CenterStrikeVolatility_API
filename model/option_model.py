from model.base_asset_repository import BaseAssetRepository
from model.option_repository import OptionRepository


class OptionModel:
    def __init__(self):
        self._option_repository = OptionRepository()
        self._base_asset_repository = BaseAssetRepository()

    @property
    def option_repository(self):
        return self._option_repository

    @property
    def base_asset_repository(self):
        return self._base_asset_repository

    def dump(self):
        return [
            self._base_asset_repository.dump(),
            self._option_repository.dump(),
        ]
