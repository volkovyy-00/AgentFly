"""V5b-fix, D28: the package knows the hash of every default rules file it has carried.

`init -g` replaces the installed rules file only when its hash is in this set (the owner never
edited it). So the set must hold the current default, and every earlier one, or an old install is
never refreshed (a missing hash) or an edit is overwritten (a hash that is not a default).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agentfly.recorder import rulefile

FIXTURES = Path(__file__).parent / "fixtures" / "shipped_defaults"
EARLIER = sorted(FIXTURES.glob("*.toml"))
CURRENT = rulefile.default_path().read_bytes()


def test_the_current_default_is_the_last_hash_in_the_set() -> None:
    assert rulefile.sha256_of(CURRENT) == rulefile.SHIPPED_DEFAULTS[-1], (
        "default.toml changed: add its sha256 as the new last entry of SHIPPED_DEFAULTS (keep the "
        "old ones) and copy the old file to tests/fixtures/shipped_defaults/"
    )


def test_the_set_holds_valid_distinct_hashes() -> None:
    shipped = rulefile.SHIPPED_DEFAULTS
    assert len(set(shipped)) == len(shipped) >= 4
    assert all(re.fullmatch(r"[0-9a-f]{64}", sha) for sha in shipped)


def test_every_earlier_default_is_kept_as_text_and_its_hash_is_in_the_set() -> None:
    assert EARLIER, "the fixtures are missing"
    hashes = {rulefile.sha256_of(path.read_bytes()) for path in EARLIER}
    assert hashes == set(rulefile.SHIPPED_DEFAULTS[:-1]), (
        "SHIPPED_DEFAULTS and tests/fixtures/shipped_defaults/ must list the same earlier files"
    )


@pytest.mark.parametrize("path", EARLIER, ids=[p.stem for p in EARLIER])
def test_an_earlier_default_is_a_valid_file_so_it_loads_and_only_gets_an_advice(
    path: Path,
) -> None:
    loaded = rulefile.load_bytes(path.read_bytes())
    assert loaded.errors == () and loaded.sha256 in rulefile.SHIPPED_DEFAULTS


def test_older_means_every_hash_but_the_current_one() -> None:
    current = rulefile.SHIPPED_DEFAULTS[-1]
    assert not rulefile.is_older_default(current)
    assert all(rulefile.is_older_default(sha) for sha in rulefile.SHIPPED_DEFAULTS[:-1])
    assert not rulefile.is_older_default(rulefile.sha256_of(b"# an edit\n" + CURRENT))
    assert not rulefile.is_older_default("")


def test_load_bytes_hashes_the_bytes_it_was_given_bom_and_all() -> None:
    raw = b"\xef\xbb\xbf" + CURRENT
    loaded = rulefile.load_bytes(raw)
    assert loaded.errors == () and loaded.sha256 == rulefile.sha256_of(raw)
    assert loaded.sha256 != rulefile.sha256_of(CURRENT)
    assert rulefile.load_bytes(b"\xff\xfe").sha256 == rulefile.sha256_of(b"\xff\xfe")
