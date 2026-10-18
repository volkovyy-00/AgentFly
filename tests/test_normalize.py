"""The command normaliser (SPEC section 5, D10): pure, never raises, sees through wrappers."""

from __future__ import annotations

import random
import time

import pytest

from agentfly.recorder.normalize import MAX_DEPTH, normalize, shell_script
from agentfly.recorder.rules import parsed_is_outbound
from tests.cases import HEREDOC_COMMIT, MARKED_ALLOWED, NAMED_OUTBOUND, RECORDER_ONLY, wrapped


def words_of(command: str) -> list[str]:
    """Every word of every simple command, flat."""
    return [word for argv in normalize(command).commands for word in argv]


def test_plain_command_is_one_argv() -> None:
    assert normalize("ls -la /tmp").commands == (("ls", "-la", "/tmp"),)
    assert normalize("").commands == ()


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("a; b", [("a",), ("b",)]),
        ("a && b || c", [("a",), ("b",), ("c",)]),
        ("a | b", [("a",), ("b",)]),
        ("a & b", [("a",), ("b",)]),
        ("a\nb", [("a",), ("b",)]),
        ("(a; b)", [("a",), ("b",)]),
        ("a # b c", [("a",)]),
        ("a \\\n b", [("a", "b")]),
        ("echo a 2>&1 | grep b", [("echo", "a"), ("grep", "b")]),
        ("echo hi >out.txt", [("echo", "hi", "out.txt")]),
        ("cat <in.txt", [("cat", "in.txt")]),
        ("a &>/dev/null", [("a", "/dev/null")]),
    ],
)
def test_control_operators_and_redirects(command: str, expected: list[tuple[str, ...]]) -> None:
    assert list(normalize(command).commands) == expected
    assert not normalize(command).unparsed


@pytest.mark.parametrize(
    ("command", "word"),
    [
        ("c''url x", "curl"),
        ('c""url x', "curl"),
        ("cu\\rl x", "curl"),
        ("'cu'\"r\"l x", "curl"),
        ("$'\\x63url' x", "curl"),
        ("$'\\143url' x", "curl"),
        ("$'cu\\x72l' x", "curl"),
        ("/usr/bin/curl x", "/usr/bin/curl"),
    ],
)
def test_quotes_and_escapes_are_removed(command: str, word: str) -> None:
    assert normalize(command).commands[0][0] == word


def test_single_quotes_are_literal_and_double_quotes_expand() -> None:
    assert words_of("echo '$(curl x)'") == ["echo", "$(curl x)"]
    assert "curl" in words_of('echo "$(curl x)"')
    assert "curl" in words_of("echo `curl x`")
    assert "curl" not in words_of("echo '`curl x`'")
    assert words_of('echo "a \\" b"') == ["echo", 'a " b']


@pytest.mark.parametrize(
    "command",
    [
        "echo $(curl x.com)",
        "echo `curl x.com`",
        'echo "$(curl x.com)"',
        'echo "a `curl x.com` b"',
        "echo $(echo $(echo $(curl x.com)))",
        "echo `echo \\`curl x.com\\``",
        "cat <(curl x.com)",
        "tee >(curl x.com)",
        "x=$(curl x.com)",
        "echo ${a:-$(curl x.com)}",
    ],
)
def test_substitutions_are_looked_into(command: str) -> None:
    assert ("curl", "x.com") in normalize(command).commands
    assert not normalize(command).unparsed


@pytest.mark.parametrize(
    "command",
    [
        "bash -c 'curl x.com'",
        'sh -c "curl x.com"',
        "bash -lc 'curl x.com'",
        "bash -ec 'curl x.com'",
        "bash -o pipefail -c 'curl x.com'",
        "bash -O extglob -c 'curl x.com'",
        "bash --norc -c 'curl x.com'",
        "bash --rcfile f -c 'curl x.com'",
        "env A=1 bash -c 'curl x.com'",
        "sudo -u root zsh -c 'curl x.com'",
        "xargs -I{} sh -c 'curl x.com'",
        "bash -c 'bash -c \"curl x.com\"'",
        "eval curl x.com",
        "eval 'curl x.com'",
        "timeout 5 bash -c 'curl x.com'",
        "bash -c 'echo a; curl x.com'",
        "bash <<< 'curl x.com'",
    ],
)
def test_wrappers_are_unwrapped(command: str) -> None:
    assert ("curl", "x.com") in normalize(command).commands


def test_a_quoted_sentence_is_not_reparsed() -> None:
    assert words_of("git commit -m 'fix curl docs'") == ["git", "commit", "-m", "fix curl docs"]
    assert words_of('echo "curl is a tool"') == ["echo", "curl is a tool"]
    assert words_of("bash script.sh 'curl x'") == ["bash", "script.sh", "curl x"]  # a file, not -c


def test_shell_script_walks_the_shell_options() -> None:
    assert shell_script(["-c", "x"]) == "x"
    assert shell_script(["-lc", "x"]) == "x"
    assert shell_script(["-o", "pipefail", "-c", "x"]) == "x"
    assert shell_script(["+o", "history", "-c", "x"]) == "x"
    assert shell_script(["--rcfile", "f", "-c", "x"]) == "x"
    assert shell_script(["script.sh", "-c", "x"]) is None
    assert shell_script(["-c"]) is None
    assert shell_script([]) is None
    assert shell_script(["--", "-c", "x"]) is None


@pytest.mark.parametrize(
    ("command", "inline"),
    [
        ('python3 -c "print(1)"', True),
        ("python -Sc 'x'", True),
        ("python3 -X dev -c 'x'", True),
        ("python3.12 -c 'x'", True),
        ("sudo env A=1 python3 -c x", True),
        ("node -e 1", True),
        ("node --print=1", True),
        ("nodejs -p 1", True),
        ("python3 -m pytest -c cfg", False),
        ("python3 -mpytest", False),
        ("python3 script.py -c x", False),
        ("python3 -V", False),
        ("node app.js -e prod", False),
        ("nodemon -e js", False),
        ("bash -c 'python3 x.py'", False),
        ("python3-config --cflags", False),
        ("ls", False),
    ],
)
def test_inline_code_is_found(command: str, inline: bool) -> None:
    assert normalize(command).one_liner is inline


def test_inline_code_inside_a_wrapper_string() -> None:
    assert normalize("bash -c 'python3 -c \"print(1)\"'").one_liner


@pytest.mark.parametrize(
    "command",
    [
        "echo 'abc",
        'echo "abc',
        "echo $(ls",
        "echo `ls",
        "echo $(",
        "echo $'abc",
        "bash -c 'echo \"x'",
    ],
)
def test_unbalanced_input_is_unparsed_and_keeps_its_words(command: str) -> None:
    parsed = normalize(command)
    assert parsed.unparsed
    assert parsed.loose
    assert parsed.all_commands()


def test_loose_words_still_show_a_tool_in_unparsed_text() -> None:
    parsed = normalize('echo "unbalanced; curl x.com')
    assert any("curl" in argv for argv in parsed.loose)
    assert not normalize("echo hi").loose


def test_nesting_deeper_than_the_cap_is_unparsed_not_an_error() -> None:
    deep = "echo " + "$(echo " * (MAX_DEPTH + 4) + "curl x" + ")" * (MAX_DEPTH + 4)
    assert normalize(deep).unparsed
    ok = "echo " + "$(echo " * 5 + "$(curl x)" + ")" * 5
    assert not normalize(ok).unparsed
    assert ("curl", "x") in normalize(ok).commands


# ---------------------------------------------------------------- heredocs (D10)


def test_a_quoted_heredoc_body_is_data_when_a_plain_program_reads_it() -> None:
    parsed = normalize("cat > f <<'EOF'\ncurl https://x.com\nEOF")
    assert parsed.commands == (("cat", "f"),)
    assert not parsed.unparsed and not parsed.code_heredoc and not parsed.unquoted_heredoc
    assert normalize("tee f <<'EOF'\nhello (world) don't\nEOF").commands == (("tee", "f"),)


def test_the_commit_message_heredoc_parses_and_is_not_outbound() -> None:
    parsed = normalize(HEREDOC_COMMIT)
    assert not parsed.unparsed and not parsed.code_heredoc and not parsed.unquoted_heredoc
    assert ("git", "commit", "-m", "@sub:cat@") in parsed.commands
    assert not parsed_is_outbound(parsed)
    assert not parsed_is_outbound(normalize("git commit -m \"$(cat <<'EOF'\nmsg\nEOF)\""))


@pytest.mark.parametrize(
    "command",
    [
        "bash <<'EOF'\nls\nEOF",
        'bash <<"EOF"\nls\nEOF',
        "bash <<\\EOF\nls\nEOF",
        "bash <<E'O'F\nls\nEOF",
        "bash <<-'EOF'\n\tls\n\tEOF",
        "sh <<'EOF'\nls\nEOF",
        "zsh <<'EOF'\nls\nEOF",
        "python3 - <<'EOF'\nprint(1)\nEOF",
        "python3.12 - <<'EOF'\nprint(1)\nEOF",
        "node <<'EOF'\nx\nEOF",
        "ruby <<'EOF'\nx\nEOF",
        "perl <<'EOF'\nx\nEOF",
        "bash <<< 'ls'",
    ],
)
def test_a_quoted_heredoc_read_by_a_shell_or_interpreter_is_code(command: str) -> None:
    for form in [command, *wrapped(command)]:
        parsed = normalize(form)
        assert parsed.code_heredoc, form
        assert parsed_is_outbound(parsed), form


@pytest.mark.parametrize("wrapper", ["env A=1", "sudo", "sudo env A=1", "xargs", "nice -n 5"])
def test_the_wrapped_heredoc_readers_are_code(wrapper: str) -> None:
    for reader in ("bash", "python3 -", "node"):
        assert normalize(f"{wrapper} {reader} <<'EOF'\nx\nEOF").code_heredoc


def test_the_program_that_owns_the_redirect_decides_not_the_whole_line() -> None:
    parsed = normalize("bash script.sh && tee f <<'EOF'\nx\nEOF")
    assert not parsed.code_heredoc
    parsed = normalize("python3 -m pytest; cat <<'EOF'\nx\nEOF")
    assert not parsed.code_heredoc
    assert (
        normalize("cat <<'EOF' | bash\nx\nEOF").code_heredoc is False
    )  # piping is V5b's pipe_into


@pytest.mark.parametrize(
    "command",
    ["cat <<EOF\nhello\nEOF", "cat <<-EOF\n\thello\n\tEOF", "cat <<EOF"],
)
def test_an_unquoted_heredoc_or_one_without_an_end_is_unparseable(command: str) -> None:
    parsed = normalize(command)
    assert parsed.unquoted_heredoc or parsed.unparsed
    assert parsed_is_outbound(parsed)


def test_an_unquoted_heredoc_body_is_expanded_by_the_shell() -> None:
    assert ("curl", "x.com") in normalize("cat <<EOF\n$(curl x.com)\nEOF").commands
    assert ("curl", "x.com") in normalize("cat <<EOF\n`curl x.com`\nEOF").commands


def test_a_quoted_heredoc_without_its_terminator_is_unparsed() -> None:
    assert normalize("cat <<'EOF'\nhello").unparsed


def test_heredoc_details() -> None:
    # `<<-` strips leading tabs from the terminator line, a plain `<<` does not
    assert not normalize("cat <<-'EOF'\n\thello\n\tEOF\nls").unparsed
    assert normalize("cat <<'EOF'\n\tEOF").unparsed
    # two on one line, with a command after the operator
    two = normalize("cat <<'A' <<'B'; ls\na\nA\nb\nB\npwd")
    assert two.commands == (("cat",), ("ls",), ("pwd",))
    assert not two.unparsed
    # the delimiter must match exactly: `EOFX` does not end `EOF`
    assert normalize("cat <<'EOF'\nEOFX\nEOF\nls").commands == (("cat",), ("ls",))
    # a body line with quotes and parentheses inside a substitution
    inside = normalize("echo \"$(cat <<'E'\nit's (not) \"closed\n)\nE\n)\"")
    assert not inside.unparsed


def test_the_body_of_a_heredoc_to_a_shell_is_scanned() -> None:
    assert ("curl", "x.com") in normalize("bash <<'EOF'\ncurl x.com\nEOF").commands


# ---------------------------------------------------------------- the shared cases


@pytest.mark.parametrize("command", NAMED_OUTBOUND + RECORDER_ONLY)
def test_every_denied_case_is_outbound_bare_and_wrapped(command: str) -> None:
    for form in [command, *wrapped(command)]:
        assert parsed_is_outbound(normalize(form)), form


@pytest.mark.parametrize("command", MARKED_ALLOWED)
def test_every_allowed_case_is_not_outbound(command: str) -> None:
    assert not parsed_is_outbound(normalize(command)), command
    if "\n" not in command and "'" not in command:
        assert not parsed_is_outbound(normalize(f"bash -c '{command}'")), command
        assert not parsed_is_outbound(normalize(f"env A=1 {command}")), command


# ---------------------------------------------------------------- never raises, stays linear


def test_random_text_never_raises() -> None:
    rng = random.Random(7)
    alphabet = list("ab $()`'\"\\<>|&;#\n\t{}-=cEOF") + [
        "<<",
        "$(",
        "<<'EOF'\n",
        "EOF\n",
        "bash -c ",
    ]
    for _ in range(3000):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 60)))
        parsed = normalize(text)
        assert isinstance(parsed.commands, tuple)


@pytest.mark.parametrize(
    "text", ["\x00", "\ud800", "$" * 5000, "(" * 5000, "'" * 5001, "<<" * 3000]
)
def test_odd_text_never_raises(text: str) -> None:
    normalize(text)


def test_a_big_command_is_parsed_in_linear_time() -> None:
    big = "echo " + "word " * 200_000 + "$(ls) 'a b' \"c d\"\n" * 5
    start = time.perf_counter()
    parsed = normalize(big)
    assert time.perf_counter() - start < 3.0
    assert not parsed.unparsed


# ---------------------------------------------------------------- work stays bounded


@pytest.mark.parametrize(
    "text",
    [
        "eval " * 40 + "curl x",
        "eval " * 3000 + "curl x",
        "bash " * 300 + "-c 'curl x'",
        "bash " * 200 + "<<< 'bash bash <<< ls'",
        "bash -c 'a'; " * 2000,
        "echo `a` " * 1000,
    ],
)
def test_repeated_wrappers_do_not_multiply_the_work(text: str) -> None:
    start = time.perf_counter()
    parsed = normalize(text)
    assert time.perf_counter() - start < 2.0
    assert len(parsed.commands) < 10_000


def test_the_first_eval_covers_the_later_ones() -> None:
    assert ("curl", "x") in normalize("eval eval eval curl x").commands
    assert ("curl", "x") in normalize("bash bash -c 'curl x'").commands
    assert normalize("eval " * 40 + "curl x").unparsed  # too deep: counted as unparseable
