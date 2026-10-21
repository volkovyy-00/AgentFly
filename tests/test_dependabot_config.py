"""`.github/dependabot.yml` keeps the one entry the owner approved (F9). Standard library only.

Dependabot proposes updates to the GitHub Actions that `ci.yml` uses, and to nothing else
(AGENTS.md, "CI:"). The file is read with the YAML-subset reader of `test_ci_workflow.py`, so an
edit cannot hide an entry or a key from these checks. No workflow other than `ci.yml` may exist.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from tests.helpers import REPO
from tests.test_ci_workflow import WORKFLOW, YamlError, parse, unknown_keys
from tests.test_ci_workflow import problems as workflow_problems

GITHUB = REPO / ".github"
DEPENDABOT = GITHUB / "dependabot.yml"
AGENTS = REPO / "AGENTS.md"

# Default-deny: a key that is not listed (target-branch, ignore, labels, open-pull-requests-limit,
# registries, ...) can send a PR somewhere else or switch updates off, so it needs a deliberate
# edit of this test.
TOP_KEYS = {"version", "updates"}
ENTRY_KEYS = {"package-ecosystem", "directory", "schedule", "groups", "cooldown"}
ECOSYSTEM = "github-actions"
SCHEDULE = {"interval": "weekly"}
COOLDOWN = {"default-days": "7"}
GROUPS = {"github-actions": {"patterns": ["*"]}}

# ---------------------------------------------------------------- the pinned properties


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def ecosystems(updates: list[Any]) -> list[Any]:
    return [item.get("package-ecosystem") if isinstance(item, dict) else item for item in updates]


def entry_problems(entry: dict[str, Any]) -> list[str]:
    found = unknown_keys("the update entry", entry, ENTRY_KEYS)
    expected = {
        "package-ecosystem": ECOSYSTEM,
        "directory": "/",
        "schedule": SCHEDULE,
        "groups": GROUPS,
        "cooldown": COOLDOWN,
    }
    return found + [
        f"{key} must be exactly {value}, got {entry.get(key)}"
        for key, value in expected.items()
        if entry.get(key) != value
    ]


def problems(text: str) -> list[str]:
    try:
        doc = parse(text)
    except YamlError as exc:
        return [f"outside the YAML subset this test reads: {exc}"]
    if not isinstance(doc, dict):
        return ["the file is not a mapping"]
    found = unknown_keys("the file", doc, TOP_KEYS)
    if doc.get("version") != "2":
        found.append(f"version must be 2, got {doc.get('version')!r}")
    updates = doc.get("updates")
    if not (isinstance(updates, list) and len(updates) == 1 and isinstance(updates[0], dict)):
        seen = ecosystems(updates) if isinstance(updates, list) else updates
        return [*found, f"updates must hold exactly one {ECOSYSTEM} entry, found {seen}"]
    return [*found, *entry_problems(updates[0])]


def layout_problems(github: Path) -> list[str]:
    """AGENTS.md: `ci.yml` only; ask before another workflow. One config file, not two."""
    found = []
    # Finder makes .DS_Store in any folder it opens; .gitignore keeps it out of the repo.
    names = [p.name for p in (github / "workflows").glob("*") if p.name != ".DS_Store"]
    if "ci.yml" not in names:
        found.append("ci.yml is missing from .github/workflows")
    if extra := sorted(set(names) - {"ci.yml"}):
        found.append(f".github/workflows may hold only ci.yml (ask before another), found {extra}")
    twin = github / "dependabot.yaml"
    if twin.exists() or twin.is_symlink():
        found.append("dependabot.yaml next to dependabot.yml: keep one config file")
    return found


def bump(text: str) -> str:
    """What a Dependabot PR does: another 40-hex SHA and another tag on every `uses:` line."""
    pin = re.compile(r"(uses: [\w./-]+@)[0-9a-f]{40}( # )v[\d.]+")
    return pin.sub(rf"\g<1>{'a' * 40}\g<2>v99.9.9", text)


# ---------------------------------------------------------------- tests


def test_the_config_keeps_its_approved_shape() -> None:
    assert problems(read(DEPENDABOT)) == []


def test_the_workflows_folder_holds_only_ci_yml() -> None:
    assert layout_problems(GITHUB) == []


def test_a_dependabot_pr_to_ci_yml_keeps_the_ci_checks_green() -> None:
    text = read(WORKFLOW)
    bumped = bump(text)
    assert bumped.count("a" * 40) == len(re.findall(r"\buses: ", text)) > 0
    assert workflow_problems(bumped, read(AGENTS)) == []


SCHEDULE_AT = "      interval: weekly\n"
COOLDOWN_AT = "    cooldown:\n      default-days: 7\n"
GROUPS_AT = '    groups:\n      github-actions:\n        patterns:\n          - "*"\n'


def another_entry(ecosystem: str) -> str:
    return f"  - package-ecosystem: {ecosystem}\n    directory: /\n    schedule:\n{SCHEDULE_AT}"


# (what is edited, the text to replace, its replacement, a fragment of the problem it must raise)
MUTATIONS = [
    *[
        (f"a {name} entry", COOLDOWN_AT, COOLDOWN_AT + another_entry(name), name)
        for name in ("pip", "uv", "npm")
    ],
    (
        "a second github-actions entry",
        COOLDOWN_AT,
        COOLDOWN_AT + another_entry(ECOSYSTEM),
        "exactly one",
    ),
    ("the ecosystem pip", f"package-ecosystem: {ECOSYSTEM}", "package-ecosystem: pip", "pip"),
    ("a daily schedule", "interval: weekly", "interval: daily", "schedule"),
    ("a schedule day", "interval: weekly", "interval: weekly\n      day: monday", "schedule"),
    ("another directory", "directory: /", "directory: /ui", "directory"),
    ("version 1", "version: 2", "version: 1", "version"),
    ("no groups", GROUPS_AT, "", "groups"),
    ("another group pattern", '- "*"', '- "actions/*"', "groups"),
    ("an extra group pattern", '- "*"', '- "*"\n          - "x"', "groups"),
    (
        "a second group",
        GROUPS_AT,
        GROUPS_AT + '      other:\n        patterns:\n          - "x"\n',
        "groups",
    ),
    (
        "a group update-types",
        "        patterns:",
        "        update-types:\n          - minor\n        patterns:",
        "groups",
    ),
    ("no cooldown", COOLDOWN_AT, "", "cooldown"),
    ("a shorter cooldown", "default-days: 7", "default-days: 3", "cooldown"),
    (
        "a semver cooldown",
        "default-days: 7",
        "default-days: 7\n      semver-major-days: 30",
        "cooldown",
    ),
    *[
        (f"the key {key}", "    directory: /\n", f"    directory: /\n    {key}\n", "does not allow")
        for key in (
            "open-pull-requests-limit: 5",
            "target-branch: dev",
            "labels: [x]",
            "ignore:\n      - actions/checkout",
        )
    ],
    (
        "a top-level registries key",
        "version: 2\n",
        "version: 2\nregistries:\n  hub:\n    type: docker-registry\n",
        "does not allow",
    ),
    ("a bare star", '- "*"', "- *", "YAML subset"),
    ("a duplicate key", "interval: weekly", "interval: weekly\n      interval: daily", "duplicate"),
]


@pytest.mark.parametrize(
    ("old", "new", "fragment"), [m[1:] for m in MUTATIONS], ids=[m[0] for m in MUTATIONS]
)
def test_the_check_notices_an_edit_that_breaks_a_property(
    old: str, new: str, fragment: str
) -> None:
    text = read(DEPENDABOT)
    assert old in text, f"the mutation no longer applies to dependabot.yml: {old!r}"
    found = problems(text.replace(old, new, 1))
    assert any(fragment in problem for problem in found), (fragment, found)


def test_an_empty_file_is_refused() -> None:
    assert problems("") == ["the file is not a mapping"]


def make_github(root: Path, *workflows: str, dirs: tuple[str, ...] = ()) -> Path:
    github = root / ".github"
    (github / "workflows").mkdir(parents=True)
    for name in workflows:
        (github / "workflows" / name).write_text("name: x\n", encoding="utf-8")
    for name in dirs:
        (github / "workflows" / name).mkdir()
    return github


def test_finders_ds_store_is_not_a_workflow(tmp_path: Path) -> None:
    assert layout_problems(make_github(tmp_path, "ci.yml", ".DS_Store")) == []


@pytest.mark.parametrize("extra", ["codeql.yml", "ci.yaml", ".hidden.yml"])
def test_any_other_file_in_workflows_is_refused(tmp_path: Path, extra: str) -> None:
    found = layout_problems(make_github(tmp_path, "ci.yml", extra))
    assert any(extra in problem and "only ci.yml" in problem for problem in found), found


def test_a_subfolder_in_workflows_is_refused(tmp_path: Path) -> None:
    found = layout_problems(make_github(tmp_path, "ci.yml", dirs=("nested",)))
    assert any("nested" in problem for problem in found), found


def test_a_link_in_workflows_is_refused(tmp_path: Path) -> None:
    github = make_github(tmp_path, "ci.yml")
    (github / "workflows" / "other.yml").symlink_to(github / "workflows" / "ci.yml")
    assert any("other.yml" in problem for problem in layout_problems(github))


def test_a_missing_ci_yml_or_folder_is_refused(tmp_path: Path) -> None:
    for github in (make_github(tmp_path / "a"), tmp_path / "b" / ".github"):
        assert any("ci.yml is missing" in problem for problem in layout_problems(github))


def test_a_dependabot_yaml_twin_is_refused(tmp_path: Path) -> None:
    github = make_github(tmp_path, "ci.yml")
    (github / "dependabot.yaml").write_text("version: 2\n", encoding="utf-8")
    assert any("dependabot.yaml" in problem for problem in layout_problems(github))
