"""Regression tests for static typing and distribution metadata."""

import json
from email.parser import Parser
import re
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]


def _assert_bounded_runtime_dependency(metadata: str, dependency: str) -> None:
    requirements = Parser().parsestr(metadata).get_all("Requires-Dist", [])
    requirement = next(
        (
            value.split(";", 1)[0].strip()
            for value in requirements
            if re.match(
                rf"^{re.escape(dependency)}(?:\[[^]]+\])?(?=[<>=!~\s]|$)",
                value,
                flags=re.IGNORECASE,
            )
        ),
        None,
    )
    assert requirement is not None, (dependency, requirements)

    specifier = requirement[len(dependency) :].strip()
    constraints = {part.strip() for part in specifier.split(",")}
    assert any(part.startswith(">=") for part in constraints), requirement
    assert any(part.startswith("<") for part in constraints), requirement


def _build_distribution(tmp_path: Path, distribution: str) -> Path:
    build_dir = tmp_path / "dist"
    build_dir.mkdir()
    build = subprocess.run(
        ["uv", "build", f"--{distribution}", "--out-dir", str(build_dir)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr

    pattern = "*.whl" if distribution == "wheel" else "*.tar.gz"
    artifacts = list(build_dir.glob(pattern))
    assert len(artifacts) == 1
    return artifacts[0]


def _pyright_command() -> list[str]:
    local_executable = ROOT / ".venv" / "Scripts" / "pyright.exe"
    executable = (
        str(local_executable) if local_executable.exists() else shutil.which("pyright")
    )
    if executable is None:
        pytest.skip("pyright is required for typing regression tests")
    return [str(executable)]


def _run_pyright(path: Path, tmp_path: Path, *, extra_paths: list[Path]) -> dict:
    checked_path = tmp_path / path.name
    tmp_path.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, checked_path)
    config = tmp_path / "pyrightconfig.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        json.dumps(
            {
                "include": [checked_path.name],
                "extraPaths": [
                    str(item)
                    for item in [
                        *extra_paths,
                        ROOT / ".venv" / "Lib" / "site-packages",
                    ]
                ],
                "typeCheckingMode": "strict",
            }
        ),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [*_pyright_command(), "--project", str(config), "--outputjson"],
        cwd=path.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    return json.loads(completed.stdout)


@pytest.mark.parametrize(
    ("fixture_name", "expected_rule"),
    [
        ("invalid_result.py", "reportIncompatibleMethodOverride"),
        ("invalid_registration.py", "reportArgumentType"),
        ("invalid_plain_result.py", "reportInvalidTypeArguments"),
        ("invalid_plain_request.py", "reportInvalidTypeArguments"),
    ],
)
def test_invalid_public_typing_contract_is_rejected(
    fixture_name: str, expected_rule: str, tmp_path: Path
) -> None:
    report = _run_pyright(
        ROOT / "tests" / "typecheck" / fixture_name,
        tmp_path,
        extra_paths=[ROOT / "src"],
    )

    assert report["summary"]["errorCount"] == 1, report
    assert report["generalDiagnostics"][0]["rule"] == expected_rule


def test_wheel_contains_py_typed_and_supports_consumer_typecheck(
    tmp_path: Path,
) -> None:
    wheel_path = _build_distribution(tmp_path, "wheel")

    package_dir = tmp_path / "site-packages"
    package_dir.mkdir()
    with zipfile.ZipFile(wheel_path) as wheel:
        names = set(wheel.namelist())
        assert "flow_med/py.typed" in names
        metadata_path = next(
            name for name in names if name.endswith(".dist-info/METADATA")
        )
        metadata = wheel.read(metadata_path).decode()
        assert (
            "Summary: A type-safe asynchronous Mediator implementation for Python"
            in metadata
        )
        _assert_bounded_runtime_dependency(metadata, "flow-res")
        _assert_bounded_runtime_dependency(metadata, "injector")
        wheel.extractall(package_dir)

    consumer = tmp_path / "consumer.py"
    consumer.write_text(
        """\
from flow_res import AwaitableResult, Ok, Result
from flow_med import HandlerRegistry, Mediator, Request, RequestHandler
from injector import Injector


class CustomError(Exception):
    pass


class Query(Request[Result[int, CustomError]]):
    pass


class Handler(RequestHandler[Query, Result[int, CustomError]]):
    async def handle(self, request: Query) -> Result[int, CustomError]:
        return Ok(1)


registry = HandlerRegistry()
registry.handler(Handler)
mediator = Mediator(Injector(), registry)
mediator.send_async(Query())
custom_result: AwaitableResult[int, CustomError] = mediator.send_async(
    Query(), exception_mapper=lambda exc: CustomError(str(exc))
)


class BaseQuery(Request[Result[int, CustomError]]):
    pass


class ChildQuery(BaseQuery):
    pass


class BaseQueryHandler(RequestHandler[BaseQuery, Result[int, CustomError]]):
    async def handle(self, request: BaseQuery) -> Result[int, CustomError]:
        return Ok(2)


inheritance_registry = HandlerRegistry()
inheritance_registry.handler(BaseQueryHandler)
inheritance_mediator = Mediator(Injector(), inheritance_registry)
inheritance_result: AwaitableResult[int, CustomError] = (
    inheritance_mediator.send_async(ChildQuery())
)
""",
        encoding="utf-8",
    )
    report = _run_pyright(
        consumer,
        tmp_path / "consumer-config",
        extra_paths=[package_dir, ROOT / ".venv" / "Lib" / "site-packages"],
    )

    assert report["summary"]["errorCount"] == 0


def test_sdist_contains_only_publishable_project_files(tmp_path: Path) -> None:
    sdist_path = _build_distribution(tmp_path, "sdist")

    with tarfile.open(sdist_path) as sdist:
        names = {
            Path(*Path(name).parts[1:]).as_posix()
            for name in sdist.getnames()
            if len(Path(name).parts) > 1
        }

    assert names == {
        ".gitignore",
        "CHANGELOG.md",
        "LICENSE",
        "PKG-INFO",
        "README.md",
        "pyproject.toml",
        "src/flow_med/__init__.py",
        "src/flow_med/mediator.py",
        "src/flow_med/py.typed",
    }
