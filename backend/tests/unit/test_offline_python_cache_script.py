from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_export_accepts_plain_pinned_uv_version(tmp_path: Path) -> None:
    fake_python = tmp_path / "python3.12"
    fake_python.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "${1:-}" = "--version" ]; then\n'
        "  printf '%s\\n' 'Python 3.12.12'\n"
        "fi\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    fake_uv = tmp_path / "uv"
    fake_uv.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "${1:-}" = "--version" ]; then\n'
        "  printf '%s\\n' 'uv 0.9.17'\n"
        'elif [ "${1:-}" = "python" ] && [ "${2:-}" = "find" ]; then\n'
        f"  printf '%s\\n' '{fake_python}'\n"
        'elif [ "${1:-}" = "sync" ]; then\n'
        "  exit 0\n"
        "else\n"
        "  exit 2\n"
        "fi\n",
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)

    output = tmp_path / "artifacts"
    result = subprocess.run(  # noqa: S603 - fixed repository script and temporary fake tools
        [
            "/bin/bash",
            str(ROOT / "scripts" / "export_offline_python_cache.sh"),
            "--uv-bin",
            str(fake_uv),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        env={**os.environ, "TMPDIR": str(tmp_path)},
        check=True,
        capture_output=True,
        text=True,
    )

    archives = tuple(output.glob("datariver-uv-cache-*.tar.gz"))
    assert len(archives) == 1
    assert archives[0].with_name(f"{archives[0].name}.sha256").is_file()
    assert archives[0].with_suffix("").with_suffix(".manifest.tsv").is_file()
    assert "Verified offline dependency installation with uv 0.9.17." in result.stdout
