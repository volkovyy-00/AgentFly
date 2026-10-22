"""V5b-fix, D27: a rules file cannot drop or weaken R1.

SPEC section 5 makes R0 and R1 the two rules v1 must have. R0 is in code; R1 is in the file, so
the program holds the least R1 may say. A file whose R1 is missing or weaker is refused like an
entry for R0: the packaged default runs and every place that reports a file says why. The
minimum is judged by the shape of R1's patterns (V5b-fix2 §6.2): for every family of SPEC section
5's secret names one pattern `P` or `P*Q` that covers it, so `.env*` in place of `.env` and `.env.*`
loads; exceptions by their own shape; and no floating folder pattern in R1 (§6.3). The old sample
grid (`tests/r1_grid.py`) and a brute force are the second opinions.
"""

from __future__ import annotations

import random
import re
import string
from pathlib import Path

import pytest

import agentfly.recorder.rules as rules_mod
from agentfly.cli import main
from agentfly.recorder import rulefile
from tests import r1_grid
from tests.rules_helpers import R0_ENTRY, default_as, default_with, list_line, ruleset_of
from tests.test_rules_cost import command

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
    assert r1_grid.SECRET_NAMES, "the second opinion has names to judge by"


def test_the_names_the_check_judges_by_are_the_ones_spec_section_5_counts() -> None:
    names = set(r1_grid.SECRET_NAMES)
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
    # `**/fixtures/**` floats, so the parser refuses it before D27 (V5b-fix2 §4.6, test_rulefile)
    "an exception for a folder anywhere": with_exemptions("**/fixtures/*"),
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


def test_the_error_names_the_bullet() -> None:
    (error,) = r1_errors(with_names(".env", ".env.*", "*.pem", "*.key", "id_rsa*"))
    assert error == (
        "rule R1: no pattern in its 'after' marks every name SPEC section 5 counts as secret under "
        "'any file whose name starts with credentials'; add one such as 'credentials*' (a single "
        "`*` and no `?` or `[`) (D27)"
    )
    (error,) = r1_errors(with_exemptions("*.example"))
    assert "exception '*.example' must be .env... ending in" in error


def test_a_literal_exemption_is_refused_for_its_shape() -> None:
    (error,) = r1_errors(with_exemptions("prod.pem"))
    assert "'prod.pem' must be .env... ending in" in error


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


@pytest.mark.parametrize("other", ["R10", "R1x", "R2"])
def test_a_broken_rule_whose_id_starts_like_r1_does_not_hide_r1s_errors(other: str) -> None:
    """Final audit A4: `rule R10: …` once counted as an error of R1's own."""
    broken = f'\n[[rule]]\nid = "{other}"\nkind = "match"\nseverity = "block"\nmessage = "x"\n'
    renamed = rulefile.default_text().replace('id = "R1"', 'id = "secret-then-send"', 1)
    for text in (default_as("warn"), renamed):  # R1 gentler, or R1 missing
        errors = rulefile.load_bytes((text + broken + 'event = ["shell"]\n').encode()).errors
        assert any(e.startswith(f"rule {other}:") for e in errors), errors
        assert any(e.startswith("rule R1:") for e in errors), errors


def test_a_broken_r1_is_reported_once_and_not_also_as_missing() -> None:
    text = BASE.replace('kind = "after_then"', 'kind = "after_then"\ncolour = "red"', 1)
    errors = rulefile.load_bytes(text.encode()).errors
    assert any("colour" in e for e in errors)
    assert not any("missing" in e for e in errors)


CLAUSE_FAULTS = {
    "after": (AFTER_LINE, AFTER_LINE[:-2] + ', colour = "red" }'),
    "then": (THEN_LINE, THEN_LINE[:-2] + ', colour = "red" }'),
    "test #1": (
        'steps = ["read: .env", "shell: curl https://x.com"]',
        'steps = ["zzz: .env"]',
    ),
}


@pytest.mark.parametrize("part", CLAUSE_FAULTS)
def test_a_fault_inside_r1s_clause_or_test_is_its_own_error_and_not_also_missing(
    part: str,
) -> None:
    """Final re-review: `rule R1 after: …`, `rule R1 then: …` and `rule R1 test #N: …` are R1's
    own errors like `rule R1: …`; R1 is dropped while parsing, but it is not also "missing"."""
    old, new = CLAUSE_FAULTS[part]
    errors = rulefile.load_bytes(changed(old, new).encode()).errors
    assert len(errors) == 1 and errors[0].startswith(f"rule R1 {part}: "), errors
    assert not any("missing" in e for e in errors), errors


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


def test_the_coverage_is_judged_once_per_clause() -> None:
    rulefile._coverage_problems.cache_clear()
    rulefile.load_bytes(BASE.encode())
    rulefile.load_bytes(BASE.encode())
    assert rulefile._coverage_problems.cache_info().misses == 1


def test_the_minimum_does_not_read_default_toml() -> None:
    """It is measured against the program's own minimum, so a later default cannot refuse an
    older file (D27). Nothing in the check opens the packaged file."""
    source = Path(rulefile.__file__).read_text(encoding="utf-8")
    start = source.index("the minimum for R1 (D27)")
    end = source.index("---- files", start)
    assert not re.search(r"default_(text|path)|load_default", source[start:end])


# ---------------------------------------------------------------- one table for "secret" (6.1)


def _spec_secret_before(name: str) -> bool:
    """`rulefile.spec_secret` as it was before the table (kept here as the second opinion)."""
    folded = name.casefold()
    if folded == ".env" or (
        folded.startswith(".env.") and not folded.endswith((".example", ".sample", ".template"))
    ):
        return True
    if folded.endswith((".pem", ".key")):
        return True
    if folded.startswith("id_rsa") and not folded.endswith(".pub"):
        return True
    return folded.startswith("credentials")


def _grid_without_the_filter() -> set[str]:
    """The old `_secret_names` grid before it kept only what `spec_secret` counts."""
    names = {family + tail for family in r1_grid._FAMILIES for tail in r1_grid._TAILS}
    for stem in (".env.", "id_rsa", "credentials"):
        names |= {stem + char for char in r1_grid._SWEEP}
    for char in r1_grid._SWEEP:
        names |= {char + ".pem", char + ".key", f".env.{char}x"}
    return names | set(r1_grid._LITERALS)


def _random_names(count: int, seed: int) -> list[str]:
    rng = random.Random(seed)
    pieces = [".env", ".", "pem", "key", "id_rsa", "credentials", "pub", "example"]
    pieces += [".sample", ".template"]
    out: list[str] = []
    for _ in range(count):
        parts: list[str] = []
        for _ in range(rng.randint(1, 4)):
            if rng.random() < 0.7:
                part = rng.choice(pieces)
            else:
                part = "".join(rng.choices(string.ascii_letters + "_-", k=rng.randint(1, 3)))
            parts.append(part.upper() if rng.random() < 0.1 else part)
        out.append("".join(parts))
    return out


def test_spec_secret_from_the_table_answers_as_before() -> None:
    random_names = _random_names(20_000, seed=2026)
    names = [*r1_grid.SECRET_NAMES, *sorted(_grid_without_the_filter()), *random_names]
    assert len(names) > 20_300
    wrong = [n for n in names if rulefile.spec_secret(n) != _spec_secret_before(n)]
    assert wrong[:5] == []
    # the comparison is not vacuous: the random names fall on both sides, and in every family
    answers = [_spec_secret_before(n) for n in random_names]
    assert 2_000 < sum(answers) < len(answers) - 2_000
    for family in rulefile.SECRET_FAMILIES:
        assert any(family.has(n.casefold()) for n in random_names), family.bullet


def test_the_table_holds_the_six_families_of_spec_section_5_in_order() -> None:
    shape = [(f.start, f.end, f.exact, f.unless) for f in rulefile.SECRET_FAMILIES]
    assert shape == [
        (".env", ".env", True, ()),
        (".env.", "", False, (".example", ".sample", ".template")),
        ("", ".pem", False, ()),
        ("", ".key", False, ()),
        ("id_rsa", "", False, (".pub",)),
        ("credentials", "", False, ()),
    ]
    assert all(f.bullet and f.start == f.start.casefold() for f in rulefile.SECRET_FAMILIES)
    assert len({f.bullet for f in rulefile.SECRET_FAMILIES}) == 6
    # derived from the table, with the value the exception-shape check has always had
    assert rulefile.EXEMPTIONS == (
        (".env", (".example", ".sample", ".template")),
        ("id_rsa", (".pub",)),
    )


# ---------------------------------------------------------------- D27 by structure (6.2, 6.3)

ENV, ENV_DOT, PEM, KEY, ID_RSA, CREDENTIALS = rulefile.SECRET_FAMILIES
DEFAULT_NAMES = (".env", ".env.*", "*.pem", "*.key", "id_rsa*", "credentials*")
# §6.2's examples, per family: what covers it by its shape, and what does not.
COVERING: dict[rulefile.Family, tuple[str, ...]] = {
    ENV: (".env", ".env*", ".*", "*env", ".e*v", "*.env"),
    ENV_DOT: (".env.*", ".env*", ".*", ".en*"),
    PEM: ("*.pem", "*pem", "*m"),
    KEY: ("*.key", "*key", "*y"),
    ID_RSA: ("id_rsa*", "id_*"),
    CREDENTIALS: ("credentials*", "cred*"),
}
NOT_COVERING: dict[rulefile.Family, tuple[str, ...]] = {
    ENV: (".env*.env", ".env.*", ".env?", "*.env.", "e*"),
    ENV_DOT: (".env.?*", ".env.[!s]*", ".env", ".env.**", "*."),
    PEM: ("?*.pem", "*.pe?", "prod.pem", "*.pem*", "x*.pem"),
    KEY: ("?*.key", "*.ke?", "server.key", "*.pem"),
    ID_RSA: ("id_rsa", "id_rsa.*", "id_rsa*.pub*", "*id_rsa"),
    CREDENTIALS: ("credentials", "credentials[!$ ]*", "credentials.*", "credentials**"),
}


def _shape_cases() -> list[tuple[str, rulefile.Family, bool]]:
    cases = [(text, family, True) for family, texts in COVERING.items() for text in texts]
    return cases + [
        (text, family, False) for family, texts in NOT_COVERING.items() for text in texts
    ]


@pytest.mark.parametrize(
    ("text", "family", "expected"),
    _shape_cases(),
    ids=[f"{t}-{f.start or f.end}-{e}" for t, f, e in _shape_cases()],
)
def test_covers_follows_the_shape_rule(text: str, family: rulefile.Family, expected: bool) -> None:
    assert rulefile.covers(text, family) is expected


def test_the_families_have_the_shape_covers_relies_on() -> None:
    """`covers` is sound because every name of a family starts with its start, ends with its end
    and is at least as long as both; the exact family is `.env` alone."""
    names = {*r1_grid.SECRET_NAMES, *_grid_without_the_filter(), *_random_names(5_000, seed=10)}
    names = {name.casefold() for name in names}
    for family in rulefile.SECRET_FAMILIES:
        members = [name for name in names if family.has(name)]
        assert members, family.bullet
        if family.exact:
            assert members == [".env"] and family.start == family.end == ".env"
            continue
        for name in members:
            assert name.startswith(family.start) and name.endswith(family.end), name
            assert len(name) >= len(family.start) + len(family.end), name


REST = ("*.pem", "*.key", "id_rsa*", "credentials*")
# The brief's three: each loaded under the sample grid and left a SPEC section 5 secret unmarked.
BRIEF_DODGES: dict[str, tuple[rulefile.Family, tuple[str, ...]]] = {
    "misses .env.secret": (
        ENV_DOT,
        (".env", ".env.[!s]*", ".env.s", ".env.s[!e]*", ".env.se", ".env.se[!c]*", *REST),
    ),
    "misses credentials copy.json": (
        CREDENTIALS,
        (".env", ".env.*", "*.pem", "*.key", "id_rsa*", "credentials", "credentials[!$ ]*"),
    ),
    "misses .env.production-eu-west-1": (
        ENV_DOT,
        (".env", *(".env." + "?" * n for n in range(1, 16)), *REST),
    ),
}


@pytest.mark.parametrize("name", BRIEF_DODGES)
def test_the_brief_dodge_files_are_refused_naming_r1(
    name: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    family, names = BRIEF_DODGES[name]
    draft = tmp_path / "dodge.toml"
    draft.write_text(with_names(*names), encoding="utf-8")
    assert main(["rules", "check", str(draft)]) == 1
    err = capsys.readouterr().err
    assert "rule R1: " in err and family.bullet in err, err


LOADING: dict[str, str] = {
    "the default": BASE,
    "a file that only adds names": with_names(*DEFAULT_NAMES, "*.p12", "secrets.yml"),
    ".env* in place of .env and .env.*": with_names(
        ".env*", "*.pem", "*.key", "id_rsa*", "credentials*"
    ),
    ".* in place of both": with_names(".*", "*.pem", "*.key", "id_rsa*", "credentials*"),
    "*pem in place of *.pem": with_names(
        ".env", ".env.*", "*pem", "*.key", "id_rsa*", "credentials*"
    ),
    "the default plus ~/.ssh/**": with_names(*DEFAULT_NAMES, "~/.ssh/**"),
}


@pytest.mark.parametrize("name", LOADING)
def test_the_brief_loading_list_loads(name: str) -> None:
    assert rulefile.load_bytes(LOADING[name].encode()).errors == ()


@pytest.mark.parametrize("pattern", [".ssh/**", "a/**/b", "**/x/**"])
def test_r1s_floating_folder_patterns_are_refused(pattern: str) -> None:
    (error,) = r1_errors(with_names(*DEFAULT_NAMES, pattern))
    assert error.startswith(
        f"rule R1: pattern {pattern!r} costs more the deeper a path is, and R1 is never cut short; "
        "anchor it ("
    )
    assert error.endswith(") or put it in a rule of its own (D27)")
    if pattern == ".ssh/**":
        assert error == (
            "rule R1: pattern '.ssh/**' costs more the deeper a path is, and R1 is never cut "
            "short; anchor it ('~/.ssh/**' or '/...') or put it in a rule of its own (D27)"
        )


@pytest.mark.parametrize(
    "pattern", ["~/.aws/config", "~/.aws/**", "~/.ssh/**", "/etc/ssl/private/*"]
)
def test_r1s_anchored_folder_patterns_load(pattern: str) -> None:
    assert rulefile.load_bytes(with_names(*DEFAULT_NAMES, pattern).encode()).errors == ()


def test_a_floating_r1_is_refused_and_the_recorder_runs_the_default(active_rules: Path) -> None:
    """Before this check an R1 widened with `.ssh/**` loaded, and its `after` raised the meter's
    `WorkLimit` out of `mark` (a 500); now it never loads."""
    active_rules.write_text(with_names(*DEFAULT_NAMES, ".ssh/**"), encoding="utf-8")
    loaded = rules_mod.load_active()
    assert loaded.source == "default" and loaded.rules == rules_mod.DEFAULT.rules
    assert "rule R1: pattern '.ssh/**'" in (loaded.problem or "")


def test_the_packaged_r1_never_charges_the_meter(monkeypatch: pytest.MonkeyPatch) -> None:
    charged: list[int] = []
    monkeypatch.setattr(rulefile, "_charge", charged.append)
    ruleset = ruleset_of(BASE)
    session = rules_mod.Session(id="s", marked=False, start_time="t", next_step=1)
    actions = [
        {"hook_event_name": "beforeShellExecution", "command": command(60)},
        {"hook_event_name": "beforeReadFile", "file_path": "/w/.env"},
    ]
    with rules_mod.one_hook() as meter:
        after = [rules_mod.mark(action, session, ruleset) for action in actions]
    assert [s.marked for s in after] == [False, True]
    assert charged == [] and meter.left == rulefile.FLOAT_STEPS and meter.unfinished == []


@pytest.mark.parametrize("name", [*ACCEPTED, *LOADING])
def test_the_grid_finds_nothing_unmarked_in_any_accepted_file(name: str) -> None:
    loaded = rulefile.load_bytes((ACCEPTED.get(name) or LOADING[name]).encode())
    assert loaded.errors == ()
    (r1,) = [spec for spec in loaded.rules if spec.id == rulefile.MARK_RULE]
    assert r1.after is not None and r1_grid.unmarked(r1.after) == ()


# ---------------------------------------------------------------- the brute force (the brief's)

EDIT_CHARS = ". e n v p m k y i d _ r s a c l * ? [ ! ]".split()
# The brief's five, and two that would cover `.env` but for its length bound (|P| + |Q| <= 4).
FIXED_NEAR_MISSES = (
    *(".env.?*", ".env.[!s]*", "?*.pem", "id_rsa.*", "credentials"),
    *(".env*.env", ".en*nv"),
)
MIDDLE_CHARS = (".", "e", "s", "x", " ", "_")
EXCEPTION_SETS: tuple[tuple[str, ...] | None, ...] = (
    (".env*.example", ".env*.sample", ".env*.template", "id_rsa*.pub"),
    (".env.local*.example", "id_rsa_work*.pub"),
    None,
)


def _edited(text: str, rng: random.Random) -> str:
    """`text` after one random one-character insert, delete or replace."""
    at = rng.randrange(len(text) + 1)
    how = rng.choice(("insert", "delete", "replace")) if text else "insert"
    if how == "insert":
        return text[:at] + rng.choice(EDIT_CHARS) + text[at:]
    at = min(at, len(text) - 1)
    keep = "" if how == "delete" else rng.choice(EDIT_CHARS)
    return text[:at] + keep + text[at + 1 :]


def _near_miss(rng: random.Random) -> str:
    if rng.random() < 0.2:
        return rng.choice(FIXED_NEAR_MISSES)
    text = rng.choice(COVERING[rng.choice(rulefile.SECRET_FAMILIES)])
    for _ in range(rng.randint(1, 2)):
        text = _edited(text, rng)
    return text or "x"


def _r1_names(rng: random.Random) -> list[str]:
    names = [rng.choice(COVERING[family]) for family in rulefile.SECRET_FAMILIES]
    for at in rng.sample(range(len(names)), rng.randint(0, 2)):
        names[at] = _near_miss(rng)
    return names + [_near_miss(rng) for _ in range(rng.randint(0, 3))]


def _r1_file(names: list[str], exceptions: tuple[str, ...] | None) -> str:
    if exceptions is None:
        text = changed(AFTER_LINE, AFTER_LINE.replace(', path_except = "secret_names_ok"', ""))
    else:
        text = changed(OK_LINE, list_line("secret_names_ok", *exceptions).rstrip("\n"))
    names_line = list_line("secret_names", *names).rstrip("\n")
    assert NAMES_LINE in text
    return text.replace(NAMES_LINE, names_line, 1)


def _brute_names() -> list[str]:
    """For each family its start, every middle of up to 2 characters, and its end (the exact
    family: its one name); the same with every exempt ending after it. Only SPEC's secrets."""
    middles = ["", *MIDDLE_CHARS, *(a + b for a in MIDDLE_CHARS for b in MIDDLE_CHARS)]
    endings = ["", *(end for family in rulefile.SECRET_FAMILIES for end in family.unless)]
    names: set[str] = set()
    for family in rulefile.SECRET_FAMILIES:
        bases = [family.start] if family.exact else [family.start + m + family.end for m in middles]
        names |= {base + ending for base in bases for ending in endings}
    return sorted(name for name in names if rulefile.spec_secret(name))


@pytest.mark.slow
def test_brute_force_finds_no_accepted_r1_that_misses_a_secret_name() -> None:
    rng = random.Random(27)
    names = _brute_names()
    assert len(names) > 500 and all(any(f.has(n) for n in names) for f in rulefile.SECRET_FAMILIES)
    accepted = refused = 0
    missed: list[tuple[list[str], str]] = []
    for _ in range(1000):
        r1_names = _r1_names(rng)
        loaded = rulefile.load_bytes(_r1_file(r1_names, rng.choice(EXCEPTION_SETS)).encode())
        if loaded.errors:
            refused += 1
            continue
        accepted += 1
        (r1,) = [spec for spec in loaded.rules if spec.id == rulefile.MARK_RULE]
        assert r1.after is not None
        for name in names:
            if not r1.after.matches({"hook_event_name": "beforeReadFile", "file_path": name}, {}):
                missed.append((r1_names, name))
        for name in rng.sample(names, 20):
            shell = {"hook_event_name": "beforeShellExecution", "command": f"cat '{name}'"}
            if not r1.after.matches(shell, {}):
                missed.append((r1_names, f"shell: {name}"))
    assert missed[:5] == []
    assert accepted >= 100 and refused >= 100, (accepted, refused)
