from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

DAGS_DIRECTORY = Path(__file__).resolve().parents[1] / "dags"
sys.path.insert(0, str(DAGS_DIRECTORY))

import datariver_auth  # noqa: E402


class DataRiverPocAuthTests(unittest.TestCase):
    def test_explicit_poc_service_token_is_returned_exactly(self) -> None:
        token = "poc-worker-token-1234567890abcdef"  # noqa: S105 - inert test fixture
        with patch.dict(
            "os.environ",
            {"DATARIVER_POC_SERVICE_TOKEN": token},
            clear=True,
        ):
            self.assertEqual(datariver_auth.service_token(), token)

    def test_missing_or_malformed_poc_token_does_not_relax_the_oidc_boundary(self) -> None:
        for value in ("", "short", "contains whitespace but is long enough"):
            with self.subTest(value=value), patch.dict(
                "os.environ",
                {"DATARIVER_POC_SERVICE_TOKEN": value},
                clear=True,
            ):
                with self.assertRaises((KeyError, RuntimeError)):
                    datariver_auth.service_token()


if __name__ == "__main__":
    unittest.main()
