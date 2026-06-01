"""订阅管理（源中心模型，与配置卡片一一对应）。

每个数据源在插件 config 里是一张卡片：``src_<key> = {enabled, schedule, targets}``，
其中 ``targets`` 是该源要推送到的会话 UMO 列表（WebUI 可视化增删，指令也可维护）。
"订阅全部" = 把 UMO 加入所有源的 targets（显式展开，无 "*" 哨兵）。

持久化：经 Config 直接改 ``src_<key>.targets`` 并 ``save()`` 落盘（参照 bilicard）。
本模块不依赖 AstrBot，可用 ``Config(普通 dict)`` 单测。
"""

from typing import List

from .config import Config


def conf_key(source_key: str) -> str:
    """源 key -> 配置卡片键。"""
    return f"src_{source_key}"


class SubscriptionStore:
    def __init__(self, cfg: Config, all_keys: List[str]):
        self._config = cfg.raw
        self._save = cfg.save
        self._all_keys = list(all_keys)

    # ------------------------------------------------------------------ #
    # 底层
    # ------------------------------------------------------------------ #
    def _src(self, key: str) -> dict:
        """取（必要时创建）某源的配置卡片，确保 targets 为 list。"""
        ck = conf_key(key)
        d = self._config.get(ck)
        if not isinstance(d, dict):
            d = {}
            self._config[ck] = d
        if not isinstance(d.get("targets"), list):
            d["targets"] = []
        return d

    def targets_of(self, key: str) -> List[str]:
        """某源的订阅会话 UMO 列表（去空白）。"""
        d = self._config.get(conf_key(key))
        if not isinstance(d, dict) or not isinstance(d.get("targets"), list):
            return []
        return [str(x).strip() for x in d["targets"] if str(x).strip()]

    # ------------------------------------------------------------------ #
    # 指令 / 批量
    # ------------------------------------------------------------------ #
    def add(self, umo: str, key: str) -> bool:
        d = self._src(key)
        if umo in d["targets"]:
            return False
        d["targets"].append(umo)
        self._save()
        return True

    def remove(self, umo: str, key: str) -> bool:
        d = self._src(key)
        if umo not in d["targets"]:
            return False
        d["targets"] = [x for x in d["targets"] if x != umo]
        self._save()
        return True

    def add_all(self, umo: str) -> int:
        """把 umo 加入所有源的 targets，返回新增到的源数量。"""
        n = 0
        for key in self._all_keys:
            d = self._src(key)
            if umo not in d["targets"]:
                d["targets"].append(umo)
                n += 1
        if n:
            self._save()
        return n

    def remove_all(self, umo: str) -> int:
        """把 umo 从所有源的 targets 移除，返回移除的源数量。"""
        n = 0
        for key in self._all_keys:
            d = self._src(key)
            if umo in d["targets"]:
                d["targets"] = [x for x in d["targets"] if x != umo]
                n += 1
        if n:
            self._save()
        return n

    def list_for_umo(self, umo: str) -> List[str]:
        """某会话订阅了哪些源（key 列表）。"""
        return [key for key in self._all_keys if umo in self.targets_of(key)]
