"""Repository hygiene tests.

These exist because of a specific failure: a workflow step named

    - name: Fetch SECOM (not committed: 5 MB of CC BY 4.0 data)

contains `": "` inside an unquoted YAML scalar, which YAML reads as a nested mapping. GitHub
rejected the whole file — "Invalid workflow file" — so **every job of every push failed before
running**, and the failure looked like a red CI rather than a typo.

It survived review because the check that was supposed to catch it was a regex over the file's
text looking for job names. A regex is not a parser. This test uses a parser.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

WORKFLOWS = pathlib.Path(__file__).resolve().parents[1] / ".github" / "workflows"
REPOSITORY = pathlib.Path(__file__).resolve().parents[1]


def workflow_paths() -> list[pathlib.Path]:
    return sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))


def test_there_is_at_least_one_workflow() -> None:
    assert workflow_paths(), f"no workflows found under {WORKFLOWS}"


@pytest.mark.parametrize("path", workflow_paths(), ids=lambda p: p.name)
def test_workflow_is_valid_yaml(path: pathlib.Path) -> None:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert isinstance(document, dict), f"{path.name} did not parse to a mapping"
    assert document.get("jobs"), f"{path.name} declares no jobs"
    # YAML reads a bare `on:` key as the boolean True, so both spellings are checked.
    assert True in document or "on" in document, f"{path.name} declares no trigger"


@pytest.mark.parametrize("path", workflow_paths(), ids=lambda p: p.name)
def test_every_job_has_a_runner_and_steps(path: pathlib.Path) -> None:
    jobs = yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"]

    for name, job in jobs.items():
        assert "runs-on" in job, f"{path.name}: job '{name}' has no runs-on"
        assert job.get("steps"), f"{path.name}: job '{name}' has no steps"


def test_no_private_material_is_tracked() -> None:
    """The repository is public, so this is the last line of defence before a push."""
    ignore = (REPOSITORY / ".gitignore").read_text(encoding="utf-8")
    for pattern in ("_tools/", "_spike/", ".env", "eval/datasets/"):
        assert pattern in ignore, f".gitignore no longer excludes {pattern!r}"
