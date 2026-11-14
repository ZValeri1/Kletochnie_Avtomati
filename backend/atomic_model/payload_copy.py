"""Copy acyclic JSON-like model payloads without deepcopy's per-scalar memo work."""
from copy import deepcopy


def copy_payload(value):
    kind = type(value)
    if kind in (str, int, float, bool, type(None)):
        return value
    if kind is dict:
        return {key: copy_payload(item) for key, item in value.items()}
    if kind is list:
        return [copy_payload(item) for item in value]
    if kind is tuple:
        return tuple(copy_payload(item) for item in value)
    return deepcopy(value)
