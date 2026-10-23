"""V5c: the example rules file (`agentfly/rules/example.toml`) and the default's header.

The example holds R1, npm-publish-after-env and the owner's ten S3 rules, and is never installed.
`rules check` and `rules test` pass on it and on the default, it fits MAX_WORK, and it loads as
the active file under D27 (SPEC section 5).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agentfly.cli import main
from agentfly.install.layout import Layout
from agentfly.recorder import rulefile
from agentfly.recorder import rules as rules_mod
from tests.rules_helpers import default_with

DEFAULT = rulefile.default_path()
EXAMPLE = DEFAULT.with_name("example.toml")
# A tie goes to file order and `rules test` wants a test's own rule to win: the rules with a more
# precise message come before R1 and before npm-publish-after-env.
EXAMPLE_IDS = (
    "s03-aws-then-no-network",
    "s04-secret-then-transfer",
    "R1",
    "s01-ssh-private-keys",
    "s02-dotenv-read",
    "s05-no-uploads",
    "s07-workflow-edit",
    "s08-write-outside-workspace",
    "s10-force-push",
    "s13-dotenv-then-publish",
    "s14-download-pipe-shell",
    "npm-publish-after-env",
)
L21 = "`init -g` replaces an unedited copy with the newest default; change any byte to keep yours"


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(["rules", *argv])
    out = capsys.readouterr()
    return code, out.out, out.err


def example() -> rulefile.RuleFile:
    return rulefile.load_bytes(EXAMPLE.read_bytes())


@pytest.mark.parametrize("path", [EXAMPLE, DEFAULT], ids=["example", "default"])
def test_rules_check_and_rules_test_pass(path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = run(capsys, "check", str(path))
    assert code == 0 and out.startswith("ok: ") and not err, (out, err)
    code, out, err = run(capsys, "test", str(path))
    assert code == 0 and " tests passed in " in out and not err, (out, err)


def test_the_example_holds_the_bundled_rules_and_the_ten_in_order() -> None:
    loaded = example()
    assert loaded.errors == ()
    assert tuple(spec.id for spec in loaded.rules) == EXAMPLE_IDS


def test_the_bundled_rules_of_the_example_are_those_of_the_default() -> None:
    default = {spec.id: spec for spec in rulefile.load_bytes(DEFAULT.read_bytes()).rules}
    for spec in example().rules:
        if spec.id in default:
            ours = default[spec.id]
            assert (spec.kind, spec.severity, spec.message) == (
                ours.kind,
                ours.severity,
                ours.message,
            )
            assert (spec.clause, spec.after, spec.then) == (ours.clause, ours.after, ours.then)


def test_the_example_fits_the_work_budget() -> None:
    assert rulefile.file_work(example().rules) <= rulefile.MAX_WORK


def test_the_example_uses_each_new_field() -> None:
    specs = {spec.id: spec for spec in example().rules}
    upload = specs["s05-no-uploads"].clause
    scope = specs["s08-write-outside-workspace"].clause
    piped = specs["s14-download-pipe-shell"].clause
    assert upload is not None and scope is not None and piped is not None
    assert ("curl", f"{rulefile.FLAG}-d") in upload.command
    assert scope.path_scope == "outside_workspace"
    assert piped.pipe_into == frozenset({"sh", "bash", "zsh", "dash", "ksh", "eval", "source"})


def test_the_example_loads_as_the_active_file(active_rules: Path) -> None:
    shutil.copyfile(EXAMPLE, active_rules)
    loaded = rules_mod.load_active()
    assert loaded.source == "active" and loaded.problem is None, loaded.problem
    assert tuple(rule.id for rule in loaded.rules if rule.id != "R0") == EXAMPLE_IDS


def test_the_example_is_never_installed() -> None:
    install = Path(rulefile.__file__).resolve().parent.parent / "install"
    assert all("example.toml" not in f.read_text(encoding="utf-8") for f in install.glob("*.py"))


def test_rules_check_refuses_path_scope_beside_a_shell_event(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rule = '\n[[rule]]\nid = "scope"\nkind = "match"\nseverity = "block"\nmessage = "m"\n'
    path = tmp_path / "scope.toml"
    path.write_text(
        default_with("", rule + 'event = ["write", "shell"]\npath_scope = "outside_workspace"\n'),
        encoding="utf-8",
    )
    code, out, err = run(capsys, "check", str(path))
    assert code == 1 and "'path_scope' needs event" in out + err, (out, err)


def test_the_default_and_the_layout_say_init_replaces_an_unedited_copy() -> None:
    header = DEFAULT.read_text(encoding="utf-8").split("\nschema = 1", 1)[0]
    assert L21 in " ".join(line.lstrip("# ") for line in header.splitlines())
    assert L21 in " ".join((Layout.rules.__doc__ or "").split())
