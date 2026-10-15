"""Rollback checks in isolated storage; never reads user uploads."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi import HTTPException
from app import documents
from test_documents import PNG


class MedicalStorageTests(unittest.TestCase):
    def test_failed_replacement_index_write_preserves_original(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(documents,'UPLOAD_DIRECTORY',Path(folder)):
            original=documents.save_document('medical_certificates','demo.png','image/png',PNG,medical_type='medical_hiv_certificate')
            before={p.name:p.read_bytes() for p in Path(folder).iterdir()}
            with patch.object(documents,'write_index',side_effect=OSError('synthetic failure')):
                with self.assertRaises(HTTPException):
                    documents.save_document('medical_certificates','new.png','image/png',PNG,replace_id=original['document_id'])
            self.assertEqual({p.name:p.read_bytes() for p in Path(folder).iterdir()},before)

    def test_failed_deletion_index_write_restores_file(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(documents,'UPLOAD_DIRECTORY',Path(folder)):
            original=documents.save_document('medical_certificates','demo.png','image/png',PNG,medical_type='medical_hiv_certificate')
            before={p.name:p.read_bytes() for p in Path(folder).iterdir()}
            with patch.object(documents,'write_index',side_effect=OSError('synthetic failure')):
                with self.assertRaises(HTTPException): documents.delete_medical_file(original['document_id'])
            self.assertEqual({p.name:p.read_bytes() for p in Path(folder).iterdir()},before)
