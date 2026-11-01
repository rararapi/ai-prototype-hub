"""Local generated work records; preserve legacy ownership when changing names."""

import subprocess
from pathlib import Path


class LocalPathError(ValueError):
    pass


def worklogs_dir(root: Path) -> Path:
    """Return worklogs/, atomically moving an existing .harness/ once.

    Never merge trees, rewrite receipts, follow a state-directory symlink or create
    a new owner alongside legacy records. Historical JSON retains its original paths.
    """
    root = root.resolve()
    legacy, target = root / ".harness", root / "worklogs"
    for path in (legacy, target):
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise LocalPathError("Local work records require ordinary directories in the checkout")
    # Do not move sensitive records into an unignored path in a Git checkout.
    if (root / ".git").exists():
        try:
            ignored = subprocess.run(
                ["git", "check-ignore", "-q", target.as_posix() + "/"],
                cwd=root,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise LocalPathError("Could not verify worklogs/ ignore rules") from None
        if ignored.returncode:
            raise LocalPathError(
                "Add worklogs/ to Git ignore rules before using local work records"
            )
    if legacy.exists():
        if target.exists():
            raise LocalPathError(
                "Both .harness/ and worklogs/ exist; preserve both and resolve the conflict before use"
            )
        try:
            legacy.rename(target)
        except FileNotFoundError:
            # Another process may have completed the same one-time migration.
            if legacy.exists() or not target.is_dir() or target.is_symlink():
                raise LocalPathError("Legacy work-record migration did not complete") from None
    if target.is_symlink():
        raise LocalPathError("Local work records cannot follow a symlink")
    return target
