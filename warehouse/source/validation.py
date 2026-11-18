import json
import math


class SourceValidationError(ValueError):
    pass


def snapshot_json_value(value, path='$', active=None):
    active = set() if active is None else active
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise SourceValidationError(f'{path}: non-finite number')
        return value
    if type(value) not in (list, dict):
        raise SourceValidationError(f'{path}: unsupported JSON value')
    identity = id(value)
    if identity in active:
        raise SourceValidationError(f'{path}: cyclic value')
    active.add(identity)
    try:
        if type(value) is list:
            return [snapshot_json_value(v, f'{path}[{i}]', active)
                    for i, v in enumerate(value)]
        result = {}
        for key, item in value.items():
            if type(key) is not str:
                raise SourceValidationError(f'{path}: keys must be strings')
            result[key] = snapshot_json_value(item, f'{path}.{key}', active)
        return result
    finally:
        active.remove(identity)


def validate_records(records):
    if type(records) not in (list, tuple):
        raise SourceValidationError('records must be an ordered list or tuple')
    result = []
    for index, record in enumerate(records):
        if type(record) is not dict:
            raise SourceValidationError(f'$[{index}]: record must be an object')
        result.append(snapshot_json_value(record, f'$[{index}]'))
    return result


def canonical_payload(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)
