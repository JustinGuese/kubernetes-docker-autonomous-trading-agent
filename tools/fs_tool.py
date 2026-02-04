"""File-system tool — reads and lists files, constrained to tools/ and experiments/."""

from __future__ import annotations

from pathlib import Path

_ALLOWED_DIRS = ("tools", "experiments")


def _resolve_and_validate(path: str) -> Path:
    """Resolve the path (collapses ../) then check it stays inside allowed dirs."""
    resolved = Path(path).resolve()
    cwd = Path.cwd().resolve()
    try:
        relative = resolved.relative_to(cwd)
    except ValueError:
        raise PermissionError(f"Path '{path}' escapes the project root")
    if relative.parts[0] not in _ALLOWED_DIRS:
        raise PermissionError(
            f"Path '{path}' (resolved: '{relative}') is outside allowed directories"
        )
    return resolved


def read_file(path: str) -> str:
    """Read and return file contents.  Raises PermissionError on path-traversal."""
    resolved = _resolve_and_validate(path)
    if not resolved.is_file():
        raise FileNotFoundError(f"{path} is not a file")
    return resolved.read_text()


def list_files(directory: str = "tools") -> list[str]:
    """List files recursively under an allowed directory."""
    resolved = _resolve_and_validate(directory)
    if not resolved.is_dir():
        raise FileNotFoundError(f"{directory} is not a directory")
    return sorted(str(p.relative_to(Path.cwd())) for p in resolved.rglob("*") if p.is_file())
