"""Explicit country mapping, independent of universities."""
import json
from pathlib import Path


def configuration():
    return json.loads((Path(__file__).resolve().parents[2] / 'config/entry_regimes.json').read_text(encoding='utf-8'))


def citizenship_code(citizenship):
    code = citizenship.strip().upper()
    return configuration()['aliases'].get(code, code)


def entry_regime_for(citizenship):
    return configuration()['countries'].get(citizenship_code(citizenship), 'unknown')
