from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

DAGS_DIRECTORY = Path(__file__).resolve().parents[1] / "dags"
sys.path.insert(0, str(DAGS_DIRECTORY))

import datariver_auth  # noqa: E402


class DataRiverPocAuthTests(unittest.TestCase):
    def test_explicit_poc_mode_returns_only_the_fixed_sentinel(self) -> None:
        with patch.dict(
            "os.environ",
            {"DATARIVER_POC_OPEN_ACCESS": "true"},
            clear=True,
        ):
            self.assertEqual(datariver_auth.service_token(), "datariver-poc-open-access")

    def test_similar_values_do_not_relax_the_oidc_boundary(self) -> None:
        for value in ("1", "yes", "enabled", "true-extra"):
            with self.subTest(value=value), patch.dict(
                "os.environ",
                {"DATARIVER_POC_OPEN_ACCESS": value},
                clear=True,
            ):
                with self.assertRaises(KeyError):
                    datariver_auth.service_token()


if __name__ == "__main__":
    unittest.main()
