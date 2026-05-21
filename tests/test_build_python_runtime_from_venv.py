from pathlib import Path

import pytest

from tools import build_python_runtime_from_venv as builder


def _write(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_find_venv_python_accepts_windows_layout(tmp_path):
    python = tmp_path / "venv" / "Scripts" / "python.exe"
    _write(python)

    assert builder.find_venv_python(tmp_path / "venv") == python


def test_build_python_runtime_from_venv_merges_base_runtime_and_site_packages(monkeypatch, tmp_path):
    base = tmp_path / "Python310"
    venv = tmp_path / "venv"
    output = tmp_path / "runtime"
    _write(base / "python.exe", "python")
    _write(base / "python310.dll", "dll")
    _write(base / "vcruntime140.dll", "dll")
    _write(base / "Lib" / "os.py", "# os")
    _write(base / "Lib" / "venv" / "__init__.py", "# venv")
    _write(base / "Lib" / "site-packages" / "global_pkg.py", "# global")
    _write(base / "Lib" / "__pycache__" / "os.pyc", "cache")
    _write(base / "Lib" / "test" / "test_os.py", "test")
    _write(base / "DLLs" / "_sqlite3.pyd", "dll")
    _write(venv / "Scripts" / "python.exe", "python")
    _write(venv / "Lib" / "site-packages" / "pkg" / "__init__.py", "value = 1")
    _write(venv / "Lib" / "site-packages" / "pkg" / "README.md", "docs")
    _write(venv / "Lib" / "site-packages" / "PyQt6" / "QtCore.pyd", "desktop")
    _write(venv / "Lib" / "site-packages" / "pkg" / "__pycache__" / "__init__.pyc", "cache")
    _write(venv / "Lib" / "site-packages" / "pkg" / "tests" / "test_pkg.py", "test")

    monkeypatch.setattr(builder, "query_venv", lambda _venv: {
        "executable": str(venv / "Scripts" / "python.exe"),
        "base_executable": str(base / "python.exe"),
        "prefix": str(venv),
        "base_prefix": str(base),
        "version": "3.10.fake",
        "purelib": str(venv / "Lib" / "site-packages"),
        "platlib": str(venv / "Lib" / "site-packages"),
    })
    monkeypatch.setattr(builder, "run_smoke", lambda _output, imports: {
        "ok": True,
        "imports": imports,
    })

    result = builder.build_python_runtime_from_venv(
        venv_root=venv,
        output_root=output,
        copy=True,
        smoke_imports=["pkg"],
    )

    assert result.ok is True
    assert (output / "python.exe").is_file()
    assert (output / "python310.dll").is_file()
    assert (output / "Lib" / "os.py").is_file()
    assert (output / "Lib" / "venv" / "__init__.py").is_file()
    assert (output / "DLLs" / "_sqlite3.pyd").is_file()
    assert (output / "Lib" / "site-packages" / "pkg" / "__init__.py").is_file()
    assert not (output / "Lib" / "site-packages" / "global_pkg.py").exists()
    assert not (output / "Lib" / "site-packages" / "pkg" / "README.md").exists()
    assert not (output / "Lib" / "site-packages" / "PyQt6").exists()
    assert not any(output.rglob("__pycache__"))
    assert not any(path.name == "tests" for path in output.rglob("*"))
    assert (output / "NAIA_PYTHON_RUNTIME_MANIFEST.json").is_file()


def test_build_python_runtime_base_only_keeps_venv_but_skips_site_packages(monkeypatch, tmp_path):
    base = tmp_path / "Python310"
    venv = tmp_path / "venv"
    output = tmp_path / "runtime"
    _write(base / "python.exe", "python")
    _write(base / "Lib" / "os.py", "# os")
    _write(base / "Lib" / "venv" / "__init__.py", "# venv")
    _write(venv / "Scripts" / "python.exe", "python")
    _write(venv / "Lib" / "site-packages" / "fastapi" / "__init__.py", "# fastapi")

    monkeypatch.setattr(builder, "query_venv", lambda _venv: {
        "executable": str(venv / "Scripts" / "python.exe"),
        "base_executable": str(base / "python.exe"),
        "prefix": str(venv),
        "base_prefix": str(base),
        "version": "3.10.fake",
        "purelib": str(venv / "Lib" / "site-packages"),
        "platlib": str(venv / "Lib" / "site-packages"),
    })
    monkeypatch.setattr(builder, "run_smoke", lambda _output, imports: {
        "ok": True,
        "imports": imports,
    })

    result = builder.build_python_runtime_from_venv(
        venv_root=venv,
        output_root=output,
        copy=True,
        base_only=True,
    )

    assert result.ok is True
    assert result.base_only is True
    assert result.smoke_imports == ["venv", "ensurepip"]
    assert (output / "python.exe").is_file()
    assert (output / "Lib" / "venv" / "__init__.py").is_file()
    assert not (output / "Lib" / "site-packages" / "fastapi").exists()


def test_build_python_runtime_from_python_base_only(monkeypatch, tmp_path):
    base = tmp_path / "Python312"
    output = tmp_path / "runtime"
    python = base / "python.exe"
    _write(python, "python")
    _write(base / "python312.dll", "dll")
    _write(base / "Lib" / "os.py", "# os")
    _write(base / "Lib" / "venv" / "__init__.py", "# venv")
    _write(base / "Lib" / "site-packages" / "global_pkg.py", "# global")

    monkeypatch.setattr(builder, "query_python_executable", lambda _python: {
        "executable": str(python),
        "base_executable": str(python),
        "prefix": str(base),
        "base_prefix": str(base),
        "version": "3.12.fake",
        "version_info": [3, 12, 0],
        "purelib": str(base / "Lib" / "site-packages"),
        "platlib": str(base / "Lib" / "site-packages"),
    })
    monkeypatch.setattr(builder, "run_smoke", lambda _output, imports: {
        "ok": True,
        "imports": imports,
    })

    result = builder.build_python_runtime_from_python(
        python_executable=python,
        output_root=output,
        copy=True,
    )

    assert result.ok is True
    assert result.source_kind == "python"
    assert result.source_python == str(python)
    assert result.base_only is True
    assert (output / "python.exe").is_file()
    assert (output / "python312.dll").is_file()
    assert (output / "Lib" / "venv" / "__init__.py").is_file()
    assert not (output / "Lib" / "site-packages" / "global_pkg.py").exists()


def test_build_python_runtime_refuses_nonempty_output(monkeypatch, tmp_path):
    base = tmp_path / "Python310"
    venv = tmp_path / "venv"
    output = tmp_path / "runtime"
    _write(base / "python.exe")
    _write(base / "Lib" / "os.py")
    _write(venv / "Lib" / "site-packages" / "pkg.py")
    _write(output / "old.txt")

    monkeypatch.setattr(builder, "query_venv", lambda _venv: {
        "executable": str(venv / "Scripts" / "python.exe"),
        "base_executable": str(base / "python.exe"),
        "prefix": str(venv),
        "base_prefix": str(base),
        "version": "3.10.fake",
        "purelib": str(venv / "Lib" / "site-packages"),
        "platlib": str(venv / "Lib" / "site-packages"),
    })

    with pytest.raises(RuntimeError, match="output directory is not empty"):
        builder.build_python_runtime_from_venv(
            venv_root=venv,
            output_root=output,
            copy=True,
        )
