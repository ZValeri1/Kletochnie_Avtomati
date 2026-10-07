from __future__ import annotations

import asyncio
import importlib
import inspect
from collections.abc import Mapping


def symbol(module_name: str, symbol_name: str):
    module = importlib.import_module(module_name)
    return getattr(module, symbol_name)


def value(target, name: str):
    return target[name] if isinstance(target, Mapping) else getattr(target, name)


def status_value(target) -> str:
    status = value(target, "status")
    return str(getattr(status, "value", status)).upper()


async def resolve(result):
    return await result if inspect.isawaitable(result) else result


def call(method, *args, **kwargs):
    result = method(*args, **kwargs)
    return asyncio.run(resolve(result)) if inspect.isawaitable(result) else result


def config(**overrides) -> dict:
    result = {
        "dimensions": [4, 4],
        "seed_init": 11,
        "seed_sim": 12,
        "q_max_ev": 0,
    }
    result.update(overrides)
    return result

