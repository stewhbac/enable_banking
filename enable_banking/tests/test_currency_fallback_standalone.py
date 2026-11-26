"""Offline regression tests for Enable Banking currency onboarding.

Usage: python -m unittest -v test_currency_fallback_standalone.py
Place onboarding.py beside this test. Requires only the Python standard library.
Tests the real _upsert_discovered_account function extracted from its source.
Does not contact banks or change ERPNext.
"""
import ast
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


class FrappeError(Exception):
    pass


class FakeFrappe:
    def __init__(self):
        self.db = Mock()
        self.db.get_value.return_value = None
        self.created = []
        self.db.exists.return_value = True

    def throw(self, text):
        raise FrappeError(text)

    def get_doc(self, document_type):
        self.created.append(document_type)
        return FakeDocument(document_type)


class FakeDocument:
    def __init__(self, data):
        self.data = data

    def insert(self, ignore_permissions=False):
        return self.data


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        code = (Path(__file__).resolve().parent.parent / "onboarding.py").read_text(encoding="utf-8")
        tree = ast.parse(code)
        selected = next(node for node in tree.body
                        if isinstance(node, ast.FunctionDef)
                        and node.name == '_upsert_discovered_account')
        cls.code = compile(ast.Module(body=[selected], type_ignores=[]), '<onboarding-function>', 'exec')

    def setUp(self):
        self.frappe = FakeFrappe()
        self.connection = SimpleNamespace(name='conn1', company='EI Kine', automatic_sync=1)
        self.sample = {'identification_hash': 'hash-bank', 'uid': 'uid1', 'currency': 'XXX'}
        namespace = {
            'frappe': self.frappe,
            '_': lambda txt: txt,
            'json': json,
            '_account_identity_hash': lambda s: hashlib.sha256(str(s).encode()).hexdigest(),
            '_masked_identifier': lambda _: '••••1234',
            'minimal_account_metadata': lambda _: {},
            'ACCOUNT_DOCTYPE': 'Enable Banking Account',
            'internal_operation': __import__('contextlib').nullcontext,
        }
        exec(self.code, namespace)
        self.upsert = namespace['_upsert_discovered_account']

    def test_xxx_is_eur_with_explicit_eur_fallback(self):
        result = self.upsert(self.connection, self.sample, fallback_currency='EUR')
        self.assertEqual(result['currency'], 'EUR')
        self.assertEqual(result['provider_currency'], 'XXX')

    def test_xxx_can_use_usd_if_selected(self):
        result = self.upsert(self.connection, self.sample, fallback_currency='USD')
        self.assertEqual(result['currency'], 'USD')
        self.assertEqual(result['provider_currency'], 'XXX')

    def test_valid_currency_preserved(self):
        item = {**self.sample, 'currency': 'EUR'}
        result = self.upsert(self.connection, item, fallback_currency='EUR')
        self.assertEqual(result['currency'], 'EUR')
        self.assertEqual(result['provider_currency'], 'EUR')

    def test_valid_usd_without_fallback(self):
        item = {**self.sample, 'currency': 'USD'}
        result = self.upsert(self.connection, item)
        self.assertEqual(result['currency'], 'USD')

    def test_mismatch_rejected(self):
        item = {**self.sample, 'currency': 'USD'}
        with self.assertRaisesRegex(FrappeError, 'Currency mismatch'):
            self.upsert(self.connection, item, fallback_currency='EUR')

    def test_xxx_without_fallback_rejected(self):
        with self.assertRaisesRegex(FrappeError, 'unknown currency'):
            self.upsert(self.connection, self.sample)

    def test_missing_uid_rejected(self):
        with self.assertRaisesRegex(FrappeError, 'resource UID'):
            self.upsert(self.connection, {**self.sample, 'uid': None}, fallback_currency='EUR')

    def test_missing_identification_hash_rejected(self):
        with self.assertRaisesRegex(FrappeError, 'identification hash'):
            self.upsert(self.connection, {**self.sample, 'identification_hash': None}, fallback_currency='EUR')

    def test_missing_currency_rejected(self):
        # Currently this is a defect: None is persisted without an explicit failure.
        with self.assertRaises(FrappeError):
            self.upsert(self.connection, {**self.sample, 'currency': None}, fallback_currency='EUR')


if __name__ == '__main__':
    unittest.main(verbosity=2)
