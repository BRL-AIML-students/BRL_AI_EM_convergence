"""Shared strict schema primitives; booleans are never accepted as numbers."""
import math
from .errors import ConfigurationError


def object_value(value, allowed, required, name):
    if not isinstance(value, dict):
        raise ConfigurationError(f'{name}: object가 필요합니다')
    unknown, missing = set(value)-allowed, required-set(value)
    if unknown or missing:
        raise ConfigurationError(f'{name}: 알 수 없는 키 {sorted(unknown)}, 누락된 키 {sorted(missing)}')
    return value


def number(value, name, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ConfigurationError(f'{name}: 유한한 숫자가 필요합니다')
    try:
        result = float(value)
    except OverflowError as exc:
        raise ConfigurationError(f'{name}: 숫자 범위를 초과했습니다') from exc
    if not math.isfinite(result) or (positive and result <= 0):
        raise ConfigurationError(f'{name}: 양의 유한한 숫자가 필요합니다' if positive else f'{name}: 유한한 숫자가 필요합니다')
    return result


def integer(value, name, low=1, high=1_000_000):
    if type(value) is not int or not low <= value <= high:
        raise ConfigurationError(f'{name}: {low}–{high} 정수가 필요합니다')
    return value


def boolean(value, name):
    if type(value) is not bool:
        raise ConfigurationError(f'{name}: bool이 필요합니다')
    return value
