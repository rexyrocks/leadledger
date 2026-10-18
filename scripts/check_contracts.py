"""Check committed wire examples and the cross-language hash vector."""
import hashlib
import json
from pathlib import Path
from jsonschema import Draft202012Validator,FormatChecker

root=Path(__file__).resolve().parents[1]
bundle=json.loads((root/'schemas.json').read_text())
Draft202012Validator.check_schema(bundle)
examples=json.loads((root/'examples.json').read_text())
for name,value in examples.items():
    Draft202012Validator({**bundle,'$ref':f'#/$defs/{name}'},format_checker=FormatChecker()).validate(value)
vector=json.loads((root/'message-hash-vector.json').read_text())
assert hashlib.sha256(vector['canonical_json'].encode('utf-8')).hexdigest()==vector['sha256']
print(f'{len(examples)} shared examples and message hash vector passed.')
