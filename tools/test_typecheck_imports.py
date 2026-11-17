"""Actual-checker regressions for independently shipped package copies."""
from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from tools import typecheck


@pytest.mark.parametrize("invalid", [False, True])
@pytest.mark.parametrize("test_only", [False, True])
def test_selected_source_package_wins_over_bundled_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str], invalid: bool, test_only: bool,
) -> None:
    root = tmp_path / "source"
    selected = "standalone/src/example"
    bundled = "plugins/consumer/vendor/src/example"
    for package, argument_type in ((selected, "int"), (bundled, "str")):
        directory = root / package
        directory.mkdir(parents=True)
        (directory / "__init__.py").write_text("", encoding="utf-8")
        (directory / "contract.py").write_text(
            f"def accept(value: {argument_type}) -> int:\n    return 1\n",
            encoding="utf-8",
        )
    argument = "'wrong'" if invalid else "1"
    target = "standalone/tests/test_caller.py" if test_only else f"{selected}/caller.py"
    (root / target).parent.mkdir(parents=True, exist_ok=True)
    (root / target).write_text(
        f"from example.contract import accept\nresult: int = accept({argument})\n",
        encoding="utf-8",
    )
    environment = tmp_path / "environment"
    environment.mkdir()
    (environment / ".typecheck-prepared").write_text("test-context\n", encoding="utf-8")
    released: list[bool] = []
    monkeypatch.setattr(typecheck, "environment_path", lambda *args: (environment, "test-context"))
    monkeypatch.setattr(typecheck, "environment_python", lambda path: Path(sys.executable))
    monkeypatch.setattr(
        typecheck, "acquire_environment",
        lambda *args: SimpleNamespace(release=lambda: released.append(True)),
    )
    monkeypatch.setenv("AGENT_SCRATCH_ROOT", str(tmp_path / "scratch"))
    project = typecheck.Project(
        "standalone", ("standalone",), (), "strict", "3.11",
        ("linux", "win32"), "requirements.txt",
    )
    paths = (target, *(
        f"{package}/{name}.py"
        for package in (selected, bundled) for name in ("__init__", "contract")
    ))
    assert typecheck.check_project(root, project, (target,), all_paths=paths) == int(invalid)
    output = capsys.readouterr().out
    if invalid:
        assert "[arg-type]" in output
    else:
        assert output.count("Success: no issues found") == 2
    assert released == [True]
