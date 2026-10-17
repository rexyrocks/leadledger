"""The committed schema bundle is the shared wire-format source of truth."""
import json
from pathlib import Path
from uuid import uuid4
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = json.loads((ROOT / 'schemas.json').read_text())


def validate(name, value):
    Draft202012Validator({**BUNDLE, '$ref': f'#/$defs/{name}'},
                         format_checker=FormatChecker()).validate(value)
    return value


def project(name, value):
    """Strip graph-private properties before serializing shared DTOs."""
    fields = BUNDLE['$defs'][name]['properties']
    return {key: value.get(key) for key in fields}


def uid(prefix):
    return f'{prefix}-{uuid4().hex}'


class Problem(Exception):
    def __init__(self, code, message, status=409, details=None):
        self.status = status
        self.body = {'error': {'code': code, 'message': message, 'details': details or {}}}
        super().__init__(message)


def conflict(message='The lead changed. Refresh and try again.'):
    return Problem('VERSION_CONFLICT', message)
