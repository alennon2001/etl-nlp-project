"""Fixture integrity and byte-for-byte v2 reproduction without legacy inputs."""
import hashlib
import importlib
import json
from pathlib import Path
import random
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
generator = importlib.import_module("generate_transactions_v2")
loader = importlib.import_module("load_transactions_snowflake")
EXPECTED_CSV_SHA256 = "119498f5d5fbc3dde9f3da8fee4e3b7e45e89ee0bd453a877d31cf62c68f0f74"


class ReproductionTests(unittest.TestCase):
    def test_exact_reproduction_and_both_metadata_formats(self):
        accounts, hashes = generator.read_and_validate_accounts()
        rng = random.Random(generator.SEED)
        payments = generator.generate_payments(accounts, rng)
        rows = payments + generator.generate_refunds(payments, rng)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "banking-v2"
            csv_path = generator.write_versioned_output(rows, accounts, hashes, output)
            self.assertEqual(hashlib.sha256(csv_path.read_bytes()).hexdigest(), EXPECTED_CSV_SHA256)
            self.assertEqual(loader.read_validated_input(output), rows)
            metadata_path = output / "generation.json"
            metadata = json.loads(metadata_path.read_text())
            metadata["input_sha256"] = dict(loader.LEGACY_INPUT_SHA256)
            metadata_path.write_text(json.dumps(metadata))
            self.assertEqual(loader.read_validated_input(output), rows)
            metadata["input_sha256"]["cards.csv"] = "0" * 64
            metadata_path.write_text(json.dumps(metadata))
            with self.assertRaises(loader.LoadError):
                loader.read_validated_input(output)
            metadata["input_sha256"] = dict(hashes, unexpected="0" * 64)
            metadata_path.write_text(json.dumps(metadata))
            with self.assertRaises(loader.LoadError):
                loader.read_validated_input(output)
            with self.assertRaisesRegex(ValueError, "overwrite"):
                generator.write_versioned_output(rows, accounts, hashes, output)

    def test_fixture_hash_and_manifest_rejections(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            manifest = (generator.FIXTURE_DIR / "SHA256SUMS").read_text()
            (target / "SHA256SUMS").write_text(manifest)
            (target / "accounts.csv").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                generator.read_and_validate_accounts(target)
            for content in ("", manifest + manifest,
                            manifest + "0" * 64 + "  customers.csv\n"):
                (target / "SHA256SUMS").write_text(content)
                with self.assertRaises(ValueError):
                    generator.read_manifest(target)


if __name__ == "__main__":
    unittest.main()
