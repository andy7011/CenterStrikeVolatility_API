from model.base_asset import BaseAsset


class BaseAssetRepository:
    def __init__(self):
        self._base_assets_list = []

    def dump(self):
        base_asset_dumps = []
        for base_asset in self._base_assets_list:
            base_asset_dumps.append(vars(base_asset))
        return base_asset_dumps

    def get_by_ticker(self, ticker) -> BaseAsset:
        for base_asset in self._base_assets_list:
            if base_asset.ticker == ticker:
                return base_asset

        return None

    def get_all(self) -> [BaseAsset]:
        return self._base_assets_list

    def insert_base_asset(self, base_asset: BaseAsset):
        self._base_assets_list.append(base_asset)
