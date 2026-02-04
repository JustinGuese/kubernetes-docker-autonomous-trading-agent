"""Tests for tools/fs_tool.py — read_file, list_files, path validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.fs_tool import list_files, read_file


@pytest.fixture
def project_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a tmp tree with tools/ and experiments/, set cwd to tmp_path."""
    (tmp_path / "tools").mkdir()
    (tmp_path / "experiments").mkdir()
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestReadFile:
    def test_read_file_returns_content(self, project_root: Path) -> None:
        (project_root / "tools" / "sample.py").write_text("print(1)")
        assert read_file("tools/sample.py") == "print(1)"

    def test_read_file_nonexistent_raises(self, project_root: Path) -> None:
        with pytest.raises(FileNotFoundError, match="is not a file"):
            read_file("tools/nonexistent.py")

    def test_read_file_disallowed_dir_raises(self, project_root: Path) -> None:
        (project_root / "core").mkdir()
        (project_root / "core" / "foo.py").write_text("x")
        with pytest.raises(PermissionError, match="outside allowed"):
            read_file("core/foo.py")

    def test_read_file_path_traversal_raises(self, project_root: Path) -> None:
        # Path that resolves outside cwd (project_root) so relative_to raises
        with pytest.raises(PermissionError, match="escapes the project root"):
            read_file("../other/file.txt")

    def test_read_file_experiments_allowed(self, project_root: Path) -> None:
        (project_root / "experiments" / "run.txt").write_text("data")
        assert read_file("experiments/run.txt") == "data"


class TestListFiles:
    def test_list_files_returns_sorted_paths(self, project_root: Path) -> None:
        (project_root / "tools" / "a.py").write_text("")
        (project_root / "tools" / "b.py").write_text("")
        (project_root / "tools" / "sub").mkdir()
        (project_root / "tools" / "sub" / "c.py").write_text("")
        result = list_files("tools")
        assert result == sorted(result)
        assert "tools/a.py" in result
        assert "tools/b.py" in result
        assert "tools/sub/c.py" in result

    def test_list_files_experiments(self, project_root: Path) -> None:
        (project_root / "experiments" / "x.json").write_text("{}")
        result = list_files("experiments")
        assert "experiments/x.json" in result

    def test_list_files_not_directory_raises(self, project_root: Path) -> None:
        (project_root / "tools" / "file.py").write_text("")
        with pytest.raises(FileNotFoundError, match="is not a directory"):
            list_files("tools/file.py")

    def test_list_files_disallowed_dir_raises(self, project_root: Path) -> None:
        (project_root / "core").mkdir()
        with pytest.raises(PermissionError, match="outside allowed"):
            list_files("core")
