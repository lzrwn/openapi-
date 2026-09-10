from deepdiff import DeepDiff


class DiffHelper:
    def __init__(self, old: dict | None, new: dict):
        self._old = old
        self._new = new

    def diff(self) -> dict:
        if not self._old:
            return {"added": [], "modified": {}, "deleted": []}
        result = DeepDiff(self._old, self._new, ignore_order=True)
        modified = {}
        for key, change in (result.get("values_changed") or {}).items():
            modified[key] = {"old": change.get("old_value"), "new": change.get("new_value")}
        for key, change in (result.get("type_changes") or {}).items():
            modified[key] = {"old": change.get("old_value"), "new": change.get("new_value")}
        return {
            "added": sorted(result.get("dictionary_item_added") or []),
            "modified": modified,
            "deleted": sorted(result.get("dictionary_item_removed") or []),
        }
