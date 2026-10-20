"""V5b-fix, D27: a rules file cannot drop or weaken R1.

SPEC section 5 makes R0 and R1 the two rules v1 must have. R0 is in code; R1 is in the file, so
the program holds the least R1 may say. A file whose R1 is missing or weaker is refused like an
entry for R0: the packaged default runs and every place that reports a file says why. The
minimum is judged on the names SPEC section 5 counts as secrets (and by the shape of the
exceptions), never on how a list is spelled, so `.env*` in place of `.env` and `.env.*` loads.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import agentfly.recorder.rules as rules_mod
from agentfly.cli import main
from agentfly.recorder import rulefile
from tests.rules_helpers import R0_ENTRY, default_as, default_with, list_line

BASE = rulefile.default_text()
OK_LINE = 'secret_names_ok = [".env*.example", ".env*.sample", ".env*.template", "id_rsa*.pub"]'
NAMES_LINE = 'secret_names = [".env", ".env.*", "*.pem", "*.key", "id_rsa*", "credentials*"]'
AFTER_LINE = (
    'after = { event = ["read", "shell"], path = "secret_names", path_except = "secret_names_ok" }'
)
THEN_LINE = 'then = { event = ["shell"], command_class = "outbound" }'


def changed(old: str, new: str) -> str:
    """The packaged default with one line changed (the test fails if the line is not there)."""
    assert old in BASE, old
    return BASE.replace(old, new, 1)


def with_exemptions(*entries: str) -> str:
    kept = [".env*.example", ".env*.sample", ".env*.template", "id_rsa*.pub", *entries]
    return changed(OK_LINE, list_line("secret_names_ok", *kept).rstrip("\n"))


def with_names(*names: str) -> str:
    return changed(NAMES_LINE, list_line("secret_names", *names).rstrip("\n"))


def r1_errors(text: str) -> list[str]:
    return [e for e in rulefile.load_bytes(text.encode()).errors if e.startswith("rule R1")]


def r1_without_after_then(rest: str) -> str:
    """The default with R1 swapped for an entry of the given text (no other change)."""
    return default_with(drop_r1=True) + rest


# ---------------------------------------------------------------- the packaged default passes


def test_the_packaged_default_meets_the_minimum() -> None:
    loaded = rulefile.load_bytes(BASE.encode())
    assert loaded.errors == () and loaded.lint == ()
    assert rulefile.SECRET_NAMES, "the check has names to judge by"


def test_the_names_the_check_judges_by_are_the_ones_spec_section_5_counts() -> None:
    names = set(rulefile.SECRET_NAMES)
    assert {".env", ".env.local", "id_rsa", "id_rsa2", "credentials.json", "server.key"} <= names
    assert {"x.pem", ".pem", ".key", ".env.example.local", ".env._x", "id_rsa.example"} <= names
    for sample in (".env.example", ".env.sample", ".env.template", "id_rsa.pub", "x.pem.example"):
        assert not rulefile.spec_secret(sample), sample
        assert sample not in names
    assert len(names) > 300


# ---------------------------------------------------------------- weakened or missing: refused

WEAKENED: dict[str, str] = {
    "no R1 at all": default_with(drop_r1=True),
    "R1 as a match rule": r1_without_after_then(
        '\n[[rule]]\nid = "R1"\nkind = "match"\nseverity = "block"\nmessage = "x"\n'
        'event = ["shell"]\ncommand_class = "outbound"\n'
    ),
    "a warn": default_as("warn"),
    "a highlight": default_as("highlight"),
    "after on reads only": changed(AFTER_LINE, AFTER_LINE.replace('["read", "shell"]', '["read"]')),
    "after on shell only": changed(
        AFTER_LINE, AFTER_LINE.replace('["read", "shell"]', '["shell"]')
    ),
    "after also needing a command": changed(
        AFTER_LINE,
        AFTER_LINE.replace('["read", "shell"]', '["shell"]').replace(
            "path_except =", 'command = "publish_tools", path_except ='
        ),
    ),
    "then with a path": changed(THEN_LINE, THEN_LINE.replace("}", ', path = "secret_names" }')),
    "then with a command": changed(
        THEN_LINE, THEN_LINE.replace("}", ', command = "publish_tools" }')
    ),
    "then with a host list": changed(
        THEN_LINE, THEN_LINE.replace("}", ', host_not_in = "dotenv_names" }')
    ),
    "then on every shell command": changed(THEN_LINE, 'then = { event = ["shell"] }'),
    "then on reads too": changed(THEN_LINE, 'then = { event = ["shell", "read"] }'),
    # lists that miss names SPEC section 5 counts
    "no .env.* in the list": with_names(".env", "*.pem", "*.key", "id_rsa*", "credentials*"),
    "no credentials": with_names(".env", ".env.*", "*.pem", "*.key", "id_rsa*"),
    "no id_rsa prefix": with_names(".env", ".env.*", "*.pem", "*.key", "id_rsa", "credentials*"),
    "id_rsa spelled out": with_names(
        ".env", ".env.*", "*.pem", "*.key", "id_rsa", "id_rsa.*", "id_rsa_*", "credentials*"
    ),
    "only letters after .env.": with_names(
        ".env", ".env.[a-z]*", ".env.[0-9]*", "*.pem", "*.key", "id_rsa*", "credentials*"
    ),
    "no bare .pem": with_names(".env", ".env.*", "?*.pem", "*.key", "id_rsa*", "credentials*"),
    "only the names it was shown": with_names(".env", ".env.local", "prod.pem", "id_rsa"),
    # exceptions wider than SPEC section 5's
    "an exception for a literal name": with_exemptions("prod.pem"),
    "an exception for a .env name": with_exemptions(".env.staging"),
    "an exception for a file type": with_exemptions("*.yml"),
    "an exception for a folder": with_exemptions("/tmp/**"),
    "an exception for a folder anywhere": with_exemptions("**/fixtures/**"),
    "an exception that runs past .example": with_exemptions(".env*.example*"),
    "an exception for .example on every secret": with_exemptions("*.example"),
    "an exception for .pub on every secret": with_exemptions("*.pub"),
    "an exception for .sample on every secret": with_exemptions("*.sample"),
    # shaped like the default's, but wide enough to hide a name SPEC counts as secret
    "an exception that hides credentials-prod.example": with_exemptions("*-prod.example"),
    "an exception that hides credentials.pem.example": with_exemptions("*.pem.example"),
    "an exception that hides credentials-prod.pub": with_exemptions("credentials-*.pub"),
    "an exception that hides .env.key.pub": with_exemptions("*key.pub"),
    "a .pub exception on .env names": with_exemptions(".env*.pub"),
    "an .example exception on id_rsa names": with_exemptions("id_rsa*.example"),
}


@pytest.mark.parametrize("name", WEAKENED)
def test_a_weaker_r1_is_refused_and_the_error_names_r1(name: str) -> None:
    assert rulefile.parse(WEAKENED[name]).errors == (), "a valid file: only D27 can refuse it"
    errors = r1_errors(WEAKENED[name])
    assert errors, f"{name} was accepted"


@pytest.mark.parametrize("name", WEAKENED)
def test_rules_check_exits_1_and_names_r1(
    name: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    draft = tmp_path / "mine.toml"
    draft.write_text(WEAKENED[name], encoding="utf-8")
    assert main(["rules", "check", str(draft)]) == 1
    assert "rule R1" in capsys.readouterr().err
    assert main(["rules", "test", str(draft)]) == 1


@pytest.mark.parametrize("name", WEAKENED)
def test_the_recorder_refuses_a_weaker_r1_and_the_default_runs(
    name: str, active_rules: Path
) -> None:
    active_rules.write_text(WEAKENED[name], encoding="utf-8")
    loaded = rules_mod.load_active()
    assert loaded.source == "default" and loaded.rules == rules_mod.DEFAULT.rules
    assert "rule R1" in (loaded.problem or "")
    assert (loaded.problem or "").endswith("the packaged default rules are in force")


def test_the_error_names_a_name_that_is_left_unmarked() -> None:
    (error,) = r1_errors(with_names(".env", ".env.*", "*.pem", "*.key", "id_rsa*"))
    assert "'credentials' unmarked" in error and "and 87 more" in error
    errors = r1_errors(with_exemptions("*.example"))
    assert any("unmarked" in e and "SPEC section 5" in e for e in errors), errors
    assert any("exception '*.example' must be .env... ending in" in e for e in errors), errors


def test_a_literal_exemption_is_refused_for_its_shape_and_for_what_it_hides() -> None:
    errors = r1_errors(with_exemptions("prod.pem"))
    assert any("'prod.pem' must be .env... ending in" in e for e in errors)
    assert any("leaves 'prod.pem' unmarked" in e for e in errors)


# ---------------------------------------------------------------- wider or reworded: accepted

ACCEPTED: dict[str, str] = {
    ".env* in place of .env and .env.*": with_names(
        ".env*", "*.pem", "*.key", "id_rsa*", "credentials*"
    ),
    "more names": with_names(
        ".env", ".env.*", "*.pem", "*.key", "id_rsa*", "credentials*", "*.p12"
    ),
    "a name from a folder": with_names(
        ".env", ".env.*", "*.pem", "*.key", "id_rsa*", "credentials*", "~/.aws/config"
    ),
    "everything with a dot": with_names(".*", "*.pem", "*.key", "id_rsa*", "credentials*"),
    "no exceptions at all": changed(
        AFTER_LINE, AFTER_LINE.replace(', path_except = "secret_names_ok"', "")
    ),
    "a narrower exception": with_exemptions(".env.local*.example", "id_rsa_work*.pub"),
    "a reworded message": BASE.replace("Blocked by rule R1: a secret", "R1 says: a secret", 1),
    "write added to the trigger": changed(
        AFTER_LINE, AFTER_LINE.replace('["read", "shell"]', '["read", "shell", "write"]')
    ),
    "another rule after R1": default_with(
        "",
        '\n[[rule]]\nid = "x"\nkind = "match"\nseverity = "highlight"\nmessage = "x"\n'
        'event = ["shell"]\ncommand = "publish_tools"\n'
        '  [[rule.test]]\n  steps = ["shell: npm publish"]\n  expect = "highlight"\n',
    ),
}


@pytest.mark.parametrize("name", ACCEPTED)
def test_a_wider_or_reworded_r1_loads(name: str) -> None:
    loaded = rulefile.load_bytes(ACCEPTED[name].encode())
    assert loaded.errors == (), loaded.errors


def test_a_file_that_widens_the_lists_is_the_one_the_recorder_runs(active_rules: Path) -> None:
    active_rules.write_text(ACCEPTED["more names"], encoding="utf-8")
    loaded = rules_mod.load_active()
    assert (loaded.source, loaded.problem) == ("active", None)
    rules_mod.activate(loaded)
    assert rules_mod.is_secret_path("/w/store.p12") and rules_mod.is_secret_path("/w/.env.local")


# ---------------------------------------------------------------- what else is said


def test_another_rules_error_does_not_hide_a_weak_r1() -> None:
    text = default_as("warn") + '\n[[rule]]\nid = "bad"\nkind = "nonsense"\n'
    errors = rulefile.load_bytes(text.encode()).errors
    assert any(e.startswith("rule R1") for e in errors) and any("bad" in e for e in errors)


def test_a_broken_r1_is_reported_once_and_not_also_as_missing() -> None:
    text = BASE.replace('kind = "after_then"', 'kind = "after_then"\ncolour = "red"', 1)
    errors = rulefile.load_bytes(text.encode()).errors
    assert any("colour" in e for e in errors)
    assert not any("missing" in e for e in errors)


def test_a_file_refused_before_its_rules_were_read_does_not_also_claim_r1_is_missing() -> None:
    for raw in (b"schema = 1\n[[rule]\n", b"\xff\xfe\x00", b"x" * (rulefile.MAX_FILE_BYTES + 1)):
        errors = rulefile.load_bytes(raw).errors
        assert len(errors) == 1 and "R1" not in errors[0]


def test_an_empty_file_with_a_schema_says_r1_is_missing() -> None:
    errors = rulefile.load_bytes(b"schema = 1\n").errors
    assert errors and "rule R1: missing" in errors[0]


def test_an_entry_for_r0_is_still_refused_next_to_a_good_r1() -> None:
    errors = rulefile.load_bytes(default_with("", R0_ENTRY).encode()).errors
    assert any("R0" in e for e in errors) and not any(e.startswith("rule R1") for e in errors)


def test_a_ruleset_cannot_be_built_without_r1() -> None:
    bare = rulefile.parse(default_with(drop_r1=True))
    assert bare.errors == ()  # `parse` is structural: only `load_bytes` judges R1
    with pytest.raises(ValueError, match="R1"):
        rules_mod.build_ruleset(bare, source="x", path="x")


def test_the_grid_is_judged_once_per_clause() -> None:
    rulefile._unmarked.cache_clear()
    rulefile.load_bytes(BASE.encode())
    rulefile.load_bytes(BASE.encode())
    assert rulefile._unmarked.cache_info().misses == 1


def test_the_minimum_does_not_read_default_toml() -> None:
    """It is measured against the program's own minimum, so a later default cannot refuse an
    older file (D27). Nothing in the check opens the packaged file."""
    source = Path(rulefile.__file__).read_text(encoding="utf-8")
    start = source.index("the minimum for R1 (D27)")
    end = source.index("---- files", start)
    assert not re.search(r"default_(text|path)|load_default", source[start:end])
