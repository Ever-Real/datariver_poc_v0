from __future__ import annotations

from pathlib import Path


def test_bash_and_powershell_bootstrap_keep_host_secret_files_owner_only() -> None:
    root = Path(__file__).resolve().parents[3]
    shell = (root / "scripts/bootstrap.sh").read_text(encoding="utf-8")
    powershell = (root / "scripts/bootstrap.ps1").read_text(encoding="utf-8")
    writer = powershell[
        powershell.index("function Write-Secret") : powershell.index("function Get-OrCreateSecret")
    ]

    assert "umask 077" in shell
    assert "[IO.UnixFileMode]::UserRead" in writer
    assert "[IO.UnixFileMode]::UserWrite" in writer
    assert "[IO.UnixFileMode]::GroupRead" not in writer
    assert "[IO.UnixFileMode]::OtherRead" not in writer
    assert "intranet_llm_reranker_api_key" in powershell
    assert "SetAccessRuleProtection($true, $false)" in powershell
    assert 'SecurityIdentifier]::new("S-1-5-18")' in powershell
    assert "Set-OwnerOnlyWindowsAcl -Path $secretsDirectory -Directory" in powershell
    assert "Set-OwnerOnlyWindowsAcl -Path $path" in writer
    assert "Set-OwnerOnlyWindowsAcl -Path $realmPath" in powershell
