"""Clean shell commands before storage (SPEC section 4). Pure, no network."""

from __future__ import annotations

import os
import posixpath
import re
import shlex
import stat
from functools import cached_property
from pathlib import Path
from urllib.parse import urlparse

from agentfly.recorder.normalize import MAX_PARSE, SHELLS

# On by default. Set CLEAN_COMMANDS=0|false|no|off to store raw commands (unsafe).
CLEAN_COMMANDS: bool = os.environ.get("CLEAN_COMMANDS", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}

# C1: per web tool, the short option letters and the long option names that take no value, each
# from the tool's own manual: curl 8.7.1 (`curl --help all`), GNU Wget 1.25.0 (the gnu.org
# manual), OpenSSH 9.9 (`man ssh`, `man scp`), rsync 3.5.1 (the samba.org manual) and OpenBSD
# nc(1). Any other option takes a value, so the word after it is never saved as a website.
_NO_VALUE: dict[str, tuple[str, frozenset[str]]] = {
    "curl": (
        "#012346:BGIJLMNORSVZafgijklnpqsv",
        frozenset(
            """anyauth append basic ca-native cert-status compressed compressed-ssh create-dirs
            crlf digest disable disable-eprt disable-epsv disallow-username-in-url
            doh-cert-status doh-insecure fail fail-early fail-with-body false-start form-escape
            ftp-create-dirs ftp-pasv ftp-pret ftp-skip-pasv-ip ftp-ssl-ccc ftp-ssl-control get
            globoff haproxy-protocol head http0.9 http1.0 http1.1 http2 http2-prior-knowledge
            http3 http3-only ignore-content-length include insecure ipv4 ipv6
            junk-session-cookies list-only location location-trusted mail-rcpt-allowfails
            manual metalink negotiate netrc netrc-optional next no-alpn no-buffer no-clobber
            no-keepalive no-npn no-progress-meter no-sessionid ntlm ntlm-wb parallel
            parallel-immediate path-as-is post301 post302 post303 progress-bar proxy-anyauth
            proxy-basic proxy-ca-native proxy-digest proxy-http2 proxy-insecure proxy-negotiate
            proxy-ntlm proxy-ssl-allow-beast proxy-ssl-auto-client-cert proxy-tlsv1 proxytunnel
            raw remote-header-name remote-name remote-name-all remote-time remove-on-error
            retry-all-errors retry-connrefused sasl-ir show-error silent socks5-basic
            socks5-gssapi socks5-gssapi-nec ssl ssl-allow-beast ssl-auto-client-cert
            ssl-no-revoke ssl-reqd ssl-revoke-best-effort sslv2 sslv3 styled-output
            suppress-connect-headers tcp-fastopen tcp-nodelay tftp-no-options tlsv1 tlsv1.0
            tlsv1.1 tlsv1.2 tlsv1.3 tr-encoding trace-ids trace-time use-ascii verbose version
            xattr""".split()
        ),
    ),
    "wget": (
        "46EFHKLNSVbcdhkmpqrvx",
        frozenset(
            """version help background debug quiet verbose no-verbose keep-badhash
            metalink-over-http xattr force-html no-clobber no-netrc continue show-progress
            timestamping no-if-modified-since no-use-server-timestamps server-response spider
            random-wait no-proxy no-dns-cache inet4-only inet6-only retry-connrefused
            ask-password no-iri unlink no-directories force-directories no-host-directories
            protocol-directories adjust-extension no-http-keep-alive no-cache no-cookies
            keep-session-cookies ignore-length save-headers content-disposition
            content-on-error trust-server-names auth-no-challenge retry-on-host-error
            https-only no-check-certificate no-hsts warc-cdx no-warc-compression
            no-warc-digests no-warc-keep-log no-remove-listing no-glob no-passive-ftp
            preserve-permissions retr-symlinks ftps-implicit no-ftps-resume-ssl
            ftps-clear-data-connection ftps-fallback-to-ftp recursive delete-after
            convert-links convert-file-only backup-converted mirror page-requisites
            strict-comments follow-ftp ignore-case span-hosts relative no-parent""".split()
        ),
    ),
    "nc": ("46cDdFhklNnrStUuvz", frozenset()),
    "scp": ("346ABCOpqRrsTv", frozenset()),
    "ssh": ("46AaCfGgKkMNnqsTtVvXxYy", frozenset()),
    "rsync": (
        "0468ACDEFHIJKLNOPRSUVWXabcdghiklmnopqrstuvxyz",
        frozenset(
            """verbose quiet no-motd checksum archive recursive inc-recursive i-r
            no-inc-recursive no-i-r relative no-implied-dirs backup update inplace append
            append-verify dirs old-dirs old-d mkpath links copy-links copy-unsafe-links
            safe-links insecure-links munge-links copy-dirlinks keep-dirlinks hard-links perms
            executability acls xattrs owner group devices copy-devices write-devices specials
            drop-D times atimes open-noatime crtimes omit-dir-times omit-link-times super
            fake-super sparse preallocate dry-run whole-file no-whole-file no-W
            one-file-system existing ignore-non-existing ignore-existing remove-source-files
            del delete delete-before delete-during delete-delay delete-after delete-excluded
            ignore-missing-args delete-missing-args ignore-errors force partial delay-updates
            prune-empty-dirs numeric-ids ignore-times size-only fuzzy compress cvs-exclude
            from0 old-args secluded-args trust-sender blocking-io stats 8-bit-output
            human-readable progress itemize-changes list-only fsync ipv4 ipv6 version
            help""".split()
        ),
    ),
}
_WEB_TOOLS: frozenset[str] = frozenset(_NO_VALUE)
# C1-fix1: the programs that run the program after them, each with its short options that take a
# value. Any other option of theirs (`sudo -E`, `env -S`) leaves the rest of the part `<arg>`.
_WRAPPERS: dict[str, str] = {
    "sudo": "ughpCDrtU",
    "doas": "uC",
    "env": "uC",
    "timeout": "sk",
    "time": "",
    "nice": "n",
    "nohup": "",
    "command": "",
    "exec": "",
    "stdbuf": "ioe",
    "xargs": "nLPsdEIa",
}
# The wrapper words and opening `(` stepped over in one part; past either, the rest is `<arg>`.
MAX_WRAPPERS: int = 8
MAX_OPEN_PARENS: int = 16

# A long option name is kept only if it looks like a name; anything else may be a value.
_LONG_OPTION_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,39}")
# A program name made of anything else (spaces, quotes, `$`) may be part of a secret.
_PROGRAM_NAME = re.compile(r"[\w./+~-]+")
# `NAME=`, `NAME+=` and `NAME[i]=` set a variable; the index is dropped, it is not a name.
_ASSIGN_NAME = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)(?:\[[^\]=]*\])?\+?")
# What a host written without a scheme may look like. A data argument (`token=a.b`, `hi a.com`)
# is not one.
_HOST_WORD = re.compile(r"[A-Za-z0-9._-]+")
# A word longer than this (in characters) is never looked up as a file (V5b-fix2 §5).
MAX_PATH_WORD: int = 1024
# What the words of one command may cost the file system (V5d): a step for each `lstat` and each
# `readlink` that is not answered from what the hook already learned. Measured on the author's
# Mac, a call takes 4.6 us on a short path and 8.5 us on one of 753 characters, so the price is
# per call. A test pins the number.
LOOKUP_STEPS: int = 4_000
# A word's links are followed at most this often (the system's own limit is near it), and each
# crossing costs a step and one more for each LINK_PARTS characters of its target, which are
# walked as well (a target of 1,023 characters holds as many parts, and a word may cross 32).
MAX_LINK_HOPS: int = 32
LINK_PARTS: int = 64
# `path_scope` (V5c): an event's `workspace_roots` past this many are not read; the path then
# counts as outside. Cursor sends one root a folder of the workspace, and its count is the agent's
# to steer (a `.code-workspace` file), so the walk over them is bounded by this and by the steps.
MAX_ROOTS: int = 32
# F18: what one command may cost the split below. Past MAX_PARTS parts the rest is not read, and
# past MAX_PIECES pieces (words' runs, quoted runs, blanks, operators) the part in progress ends at
# its last word break; the saved command then ends in `<unparsed>`. Since C1-fix1 each new line and
# `&` ends a part, and the loop reads one piece at a time in Python.
MAX_PARTS: int = 1_000
MAX_PIECES: int = 20_000

# The scans below read a command in C-speed regular expressions where the old loops read one
# character at a time in Python (V5b-fix2 §4.5); their answers are the same, character for
# character. A quoted run: single quotes hold everything up to the next `'`; in double quotes a
# backslash keeps the character after it.
_SINGLE: str = r"'[^']*+"
_DOUBLE: str = r'"[^"\\]*+(?:\\.[^"\\]*+)*+'
# A closed quoted run, or a quote that is never closed (it runs to the end).
_QUOTE_SCAN = re.compile(rf"""{_SINGLE}'|{_DOUBLE}"|['"]""", re.DOTALL)
# The pieces `_split_keeping_seps` reads a command in, one after another: a quoted run (an
# unclosed one runs to the end, a lone backslash at the end with it), a line continuation (`\` and
# a new line: cut, and the word goes on), a run of a word's other text with each character a
# backslash keeps (`\;`, `\>`: never an operator), a `#`, a redirection operator holding `&` or
# `|` (`2>&1`, `<&3`, `&>f`, `>|f`), a separator (C1-fix1: `&`, `|&` and a new line too) and a
# word break.
# A word's `${`, `}` and the characters a backslash keeps (`\${` opens nothing).
_BRACE_SCAN = re.compile(r"\\.|\$\{|\}")
_SPLIT_TOKEN = re.compile(
    rf"""(?P<quoted>{_SINGLE}(?:'|\Z)|{_DOUBLE}(?:"|\\?\Z))|(?P<join>\\\n)"""
    r"""|(?P<text>(?:[^ \t\r\n;&|()<>'"\\#]|\\[^\n])++|\\\Z)|(?P<hash>\#)"""
    r"""|(?P<redirect>[<>]&|&>|>\|)|(?P<sep>\|\||\|&|&&|[&|;\n])|(?P<blank>[ \t\r]++|[()<>])""",
    re.DOTALL,
)
# `shlex.split` (POSIX, no comments) cuts words on these four characters only, not on every
# character `str.split` calls a space.
_SHELL_SPACE: str = " \t\r\n"
_PLAIN_WORD = re.compile(r"[^ \t\r\n]+")
# A whole word, then the space after it or the end.
_SHELL_WORD = re.compile(
    rf"""((?:[^ \t\r\n'"\\]++|\\.|{_SINGLE}'|{_DOUBLE}")++)(?:[ \t\r\n]++|\Z)""", re.DOTALL
)
# One piece of a whole shell word: a character after a backslash, the inside of a single- or
# double-quoted run, or plain text.
_WORD_PIECE = re.compile(
    r"""\\(.)|'([^']*+)'|"([^"\\]*+(?:\\.[^"\\]*+)*+)"|([^'"\\]++)""", re.DOTALL
)
# In double quotes a backslash goes only before `"` and before another backslash.
_DOUBLE_ESCAPE = re.compile(r'\\(["\\])')
# C1-fix1: a redirection at a word's start as written (`>f`, `2>&1`, `&>f`, `<f`, `{fd}>f`); when
# it is the whole word (`>`, `2>`, `{fd}>`) the next word is its target.
_REDIRECT = re.compile(r"(?:[0-9]*|&|\{[A-Za-z_]\w*\})(?:>>|>\||>&|<>|<&|>|<)(?!\()")
# In a word's unquoted text, what may make it no word or several: a `$` (a variable may be empty
# or hold spaces), a glob character (it may match a file named `-d`), a `<` or `>` after the
# word's start (the shell cuts the word there), a process substitution (`<(cmd)`, whose words may
# run on) and a brace list or range (`{,}` is no word). The
# brace part never steps back (possessive, and its first run stops at the first `,` or `..`), so
# an unclosed `{,,,…` is read in one pass.
_LOOSE_TEXT = re.compile(r"[$*?\[]|(?!\A)[<>]|\A[<>]\(|\{(?:[^{},.]|\.(?!\.))*+(?:,|\.\.)[^{}]*+\}")


def command_for_storage(cmd: str, project_root: Path) -> str:
    """Return cleaned command when CLEAN_COMMANDS is on; otherwise raw cmd."""
    if not CLEAN_COMMANDS:
        return cmd
    return clean_command(cmd, project_root)


def clean_command(cmd: str, project_root: Path, lookups: Lookups | None = None) -> str:
    """Redact secrets from a shell command for safe storage.

    `lookups` is the hook's budget of file-system look-ups; the caller that goes on to ask more
    about the same words (the step record) passes the one it also uses. Without one the command
    gets a budget of its own.
    """
    stripped: str = cmd.strip()
    if not stripped:
        return ""

    # P1 (owner 2026-10-25): a command the recorder does not parse is saved unread; its program
    # is named from its start only (the token walk below is Python, a character at a time)
    if len(stripped) > MAX_PARSE:
        return f"{_first_program(stripped[:4096])} <unparsed>"
    if _needs_unparsed(stripped):
        return f"{_first_program(stripped)} <unparsed>"

    split: tuple[list[tuple[str, str]], bool] | None = _split_keeping_seps(stripped)
    if split is None:
        return f"{_first_program(stripped)} <unparsed>"
    parts, cut = split
    disk: Lookups = lookups if lookups is not None else Lookups(project_root)
    cleaned_bits: list[str] = []
    for text, sep in parts:
        cleaned_bits.append(_clean_segment(text.strip(), disk))
        if sep:
            cleaned_bits.append(f" {sep} ")
    cleaned: str = "".join(cleaned_bits).strip()
    return f"{cleaned} <unparsed>".lstrip() if cut else cleaned  # where the unread rest was


def _needs_unparsed(cmd: str) -> bool:
    # C1-fix1: the shell reads a `\r` as part of a word, which the word splitting here does not
    if "`" in cmd or "$(" in cmd or "<<" in cmd or "\r" in cmd:
        return True
    return not _quotes_balanced(cmd)


def _quotes_balanced(cmd: str) -> bool:
    return all(len(run.group()) > 1 for run in _QUOTE_SCAN.finditer(cmd))


def _assign_name(token: str) -> str | None:
    """The variable name if the token is an assignment (`K=v`, `K+=v`, `K[i]=v`), else None."""
    if "=" not in token:
        return None
    match = _ASSIGN_NAME.fullmatch(token.split("=", 1)[0])
    return match.group(1) if match else None


def _is_env_assign(token: str) -> bool:
    return _assign_name(token) is not None


def _rough_tokens(cmd: str) -> list[str]:
    """Split on whitespace, | ; & outside quotes. Tolerates unbalanced quotes; keeps quotes."""
    tokens: list[str] = []
    buf: list[str] = []
    quote: str = ""
    i: int = 0
    while i < len(cmd):
        ch: str = cmd[i]
        if ch == "\\" and quote == '"' and i + 1 < len(cmd):
            buf.append(cmd[i : i + 2])
            i += 2
            continue
        if ch in {"'", '"'} and quote in {"", ch}:
            quote = "" if quote else ch
        elif not quote and (ch.isspace() or ch in "|;&"):
            if buf:
                tokens.append("".join(buf))
                buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    if buf:
        tokens.append("".join(buf))
    return tokens


def _first_program(cmd: str) -> str:
    for token in _rough_tokens(cmd):
        if _is_env_assign(token):
            continue  # a quoted value stays inside its token, so no part of it is read
        bare: str = token.strip("'\"")
        name: str = Path(bare).name or bare
        return name if _PROGRAM_NAME.fullmatch(name) else "cmd"
    return "cmd"


def _split_keeping_seps(cmd: str) -> tuple[list[tuple[str, str]], bool] | None:
    """Split on |, |&, &, &&, ||, ; and new lines outside quotes; return (segment,
    following_sep) pairs and whether the command was cut (F18): past `MAX_PARTS` parts the rest is
    not read, and past `MAX_PIECES` pieces the part in progress ends at its last word break (a
    space or a separator), so a word cut between its pieces (`x.com'/p'`) is dropped whole. A line
    continuation and a comment (`#` where a word starts, to the end of its line; a continuation
    does not start a word) are cut out of the segment's text; a new line is saved as `;`, and one
    with nothing before it since the last separator is dropped. None when an unquoted `${` is not
    closed in its word: the shell reads its spaces and separators as part of the word
    (`${X:-a b}`), which this splitting does not."""
    segments: list[tuple[str, str]] = []
    pieces: list[str] = []  # the segment's text, without its continuations and comments
    start: int = 0  # where the segment's text goes on
    at: int = 0
    word_start: bool = True  # a `#` here starts a comment
    braces: int = 0  # the word's unquoted `${` not yet closed
    read: int = 0  # the pieces read
    kept: tuple[int, int, int] = (0, 0, 0)  # at the last word break: len(pieces), start, at
    while (found := _SPLIT_TOKEN.match(cmd, at)) is not None:
        read += 1
        if read > MAX_PIECES or len(segments) >= MAX_PARTS:
            count, begin, end = kept
            segments.append(("".join(pieces[:count]) + cmd[begin:end], ""))
            return segments, True
        kind: str | None = found.lastgroup
        if kind == "text" and (braces or "${" in found.group()):
            braces = _open_braces(found.group(), braces)
        elif braces and kind in ("redirect", "sep", "blank"):
            return None
        if kind == "hash" and word_start:
            line_end: int = cmd.find("\n", at)
            pieces.append(cmd[start:at])
            at = start = len(cmd) if line_end < 0 else line_end
            kept = (len(pieces), start, at)
            continue
        if kind in ("join", "sep"):
            pieces.append(cmd[start:at])
            start = found.end()
        if kind == "sep":
            text: str = "".join(pieces)
            pieces = []
            if found.group() != "\n":
                segments.append((text, found.group()))
            elif text.strip(_SHELL_SPACE):
                segments.append((text, ";"))
        if kind != "join":
            word_start = kind in ("redirect", "sep", "blank")
        at = found.end()
        if kind == "sep" or (kind == "blank" and found.group()[0] in _SHELL_SPACE):
            kept = (len(pieces), start, at)  # the words split on spaces only, not on `(` or `>`
    if braces:
        return None
    pieces.append(cmd[start:])
    segments.append(("".join(pieces), ""))
    return segments, False


def _open_braces(text: str, braces: int) -> int:
    """The unquoted `${` still open after a run of a word's text, `braces` open before it."""
    for found in _BRACE_SCAN.finditer(text):
        if found.group() == "${":
            braces += 1
        elif found.group() == "}" and braces:
            braces -= 1
    return braces


def _shell_words(segment: str) -> list[str]:
    """`shlex.split(segment)`, the same words. A segment that is not whole words (an unclosed
    quote, a backslash at the end) goes to `shlex.split`, which raises `ValueError` as before."""
    return [word for _, word in _raw_words(segment)]


def _raw_words(segment: str) -> list[tuple[str, str]]:
    """`_shell_words`, each word with its text as written: the quoting says what the shell does
    with it (a redirection, a `$`)."""
    if not _has_quoting(segment):
        return [(word, word) for word in _PLAIN_WORD.findall(segment)]
    pairs: list[tuple[str, str]] = []
    at: int = len(segment) - len(segment.lstrip(_SHELL_SPACE))
    while at < len(segment):
        found = _SHELL_WORD.match(segment, at)
        if found is None:
            return [(word, word) for word in shlex.split(segment)]
        pairs.append((found.group(1), _unquote(found.group(1))))
        at = found.end()
    return pairs


def _out_of_step(raw: str) -> bool:
    """Whether a word as written may stand for no word or several, so that the words after it
    may not be the ones they look like (C1-fix1): an unquoted `$`, glob character, brace list or
    `<`/`>` after its start, or a double-quoted `"$@"` or `"${X[@]}"`. A quoted `"$X"` is one
    word. A redirection is no word, whatever its target holds."""
    if _REDIRECT.match(raw):
        return False
    if not _has_quoting(raw):
        return _LOOSE_TEXT.search(raw) is not None
    plain: list[str] = []  # the unquoted text, each quoted or escaped piece one `_`
    for piece in _WORD_PIECE.finditer(raw):
        if piece.lastindex == 4:
            plain.append(piece.group(4))
            continue
        quoted: str = piece.group(piece.lastindex or 0)
        if piece.lastindex == 3 and (
            "$@" in quoted or "${@" in quoted or ("[@]" in quoted and "$" in quoted)
        ):
            return True
        plain.append("_")
    return _LOOSE_TEXT.search("".join(plain)) is not None


def _without_closing(segment: str) -> str:
    """The segment without the `)` that close it, glued to its last word or alone (`x.com)`,
    `x.com ) )`); an escaped `\\)` stays."""
    kept: str = segment.rstrip(_SHELL_SPACE + ")")
    if _ends_in_escape(kept):
        kept = segment[: len(kept) + 1]  # the backslash keeps the character after it
    return kept


def _ends_in_escape(text: str) -> bool:
    """Whether `text` ends in a backslash that keeps the character after it (an odd run)."""
    return (len(text) - len(text.rstrip("\\"))) % 2 == 1


def cleaned_words(command: str) -> list[str]:
    """The words of a cleaned command as `names.words` gives them (`shlex.split`, and a plain
    `split` when the quoting does not balance), at regular-expression speed: the cleaner already
    has the same words as `shlex.split`, and a command of 300 long paths takes `shlex` 0.35 s."""
    try:
        return _shell_words(command)
    except ValueError:
        return command.split()


def _has_quoting(text: str) -> bool:
    return "'" in text or '"' in text or "\\" in text


def _unquote(word: str) -> str:
    """A whole shell word's text as shlex gives it: the quotes go, a backslash outside quotes
    keeps the character after it, and one in double quotes goes only before `"` or `\\`."""
    if not _has_quoting(word):
        return word
    texts: list[str] = []
    for piece in _WORD_PIECE.finditer(word):
        text: str = piece.group(piece.lastindex or 0)
        texts.append(_DOUBLE_ESCAPE.sub(r"\1", text) if piece.lastindex == 3 else text)
    return "".join(texts)


def _clean_segment(segment: str, disk: Lookups) -> str:
    segment = _without_closing(segment)
    if not segment:
        return ""
    try:
        pairs: list[tuple[str, str]] = _raw_words(segment)
    except ValueError:
        return f"{_first_program(segment)} <unparsed>"

    out: list[str] = []
    found: tuple[int, str, str] | None = _program_index(pairs, out, disk)
    if found is None:
        return " ".join(out)

    idx, raw, program = found
    out.append(program if _PROGRAM_NAME.fullmatch(program) else "<arg>")
    prog_base: str = posixpath.basename(program).lower()
    rest: list[tuple[str, str]] = pairs[idx + 1 :]
    if prog_base in _WEB_TOOLS:
        out.extend(_clean_web_words(rest, prog_base, disk))
    elif prog_base == "eval":
        _rest_unread(rest, 0, out)
    else:
        # a shell's words from its `-c` on are a script and its arguments: never read
        end: int = _script_start(rest) if prog_base in SHELLS else len(rest)
        out.extend(_clean_other_words(rest[:end], disk, loose=_out_of_step(raw)))
        _rest_unread(rest, end, out)
    return " ".join(out)


def _script_start(pairs: list[tuple[str, str]]) -> int:
    """The index after a shell's short option holding `c` (`-c`, `-lc`), or the end."""
    for at, (_, word) in enumerate(pairs):
        if word.startswith("-") and not word.startswith("--") and "c" in word:
            return at + 1
    return len(pairs)


def _redirection_step(raw: str, target: bool) -> bool | None:
    """None when the word is neither a redirection nor the target of a bare one just before it
    (`target`); else whether the word after it is its target (`>`, `2>`, `{fd}>` alone)."""
    if target:
        return False
    if _REDIRECT.match(raw):
        return _REDIRECT.fullmatch(raw) is not None
    return None


def _clean_other_words(pairs: list[tuple[str, str]], disk: Lookups, *, loose: bool) -> list[str]:
    """The words of a program that is no web tool, read as any program's (C1-fix1 backstop): a
    word with `://` right after an option, or after a word that may be no word or several
    (`loose`), is that one's value, `<arg>`. Redirections and their targets are passed over."""
    out: list[str] = []
    target: bool = False  # the word after a bare redirection is its target
    for raw, word in pairs:
        if (after := _redirection_step(raw, target)) is not None:
            out.append(_classify_word(word, disk, web_tool=False))
            target = after
            continue
        if loose and "://" in word:
            out.append("<arg>")
        else:
            out.append(_classify_word(word, disk, web_tool=False))
        loose = (_is_option(word) and word != "--") or _out_of_step(raw)
    return out


def _program_index(
    pairs: list[tuple[str, str]], out: list[str], disk: Lookups
) -> tuple[int, str, str] | None:
    """Save into `out` the words before the part's program (C1-fix1): opening `(` (not saved),
    assignments, redirections with their targets, and wrappers with their options. Returns the
    program's index and its word as written and as read, its `(` cut off; or None when there is
    none or the rest of the part is saved as `<arg>`: past `MAX_OPEN_PARENS` `(` or
    `MAX_WRAPPERS` wrappers, after a wrapper option no table lists, or where a wrapper's word may
    be no word or several."""
    opened: int = 0
    wrappers: int = 0
    target: bool = False  # the word after a bare redirection is its target
    idx: int = 0
    while idx < len(pairs):
        raw, word = pairs[idx]
        opens: int = 0 if target else len(raw) - len(raw.lstrip("("))
        if opens:
            opened += opens
            if opened > MAX_OPEN_PARENS:
                _rest_unread(pairs, idx, out)
                return None
            raw, word = raw[opens:], word[opens:]  # unquoted, so `word` starts with them too
            if not raw:
                idx += 1
                continue
        if (after := _redirection_step(raw, target)) is not None:
            out.append(_classify_word(word, disk, web_tool=False))
            target = after
            idx += 1
        elif (name := _assign_name(word)) is not None:
            out.append(f"{name}=<removed>")
            idx = _after_assignment(pairs, idx)
        elif (wrapper := posixpath.basename(word).lower()) in _WRAPPERS:  # `sudo/` is a folder
            wrappers += 1
            if wrappers > MAX_WRAPPERS:
                _rest_unread(pairs, idx, out)
                return None
            out.append(word if _PROGRAM_NAME.fullmatch(word) else "<arg>")
            if (next_idx := _after_wrapper(pairs, idx + 1, wrapper, out, disk)) is None:
                return None
            idx = next_idx
        else:
            return idx, raw, word
    return None


def _rest_unread(pairs: list[tuple[str, str]], at: int, out: list[str]) -> None:
    """Save the part's words from `at` on as `<arg>`: where they cannot be read."""
    out.extend("<arg>" for _ in range(at, len(pairs)))


def _after_assignment(pairs: list[tuple[str, str]], at: int) -> int:
    """The index after the assignment at `at`; an array `NAME=(…)` runs to the word that closes
    it, or to the part's end (its `)` may have been cut as the part's)."""
    raw: str = pairs[at][0]
    if not raw.partition("=")[2].startswith("(") or _closes(raw):
        return at + 1
    for end in range(at + 1, len(pairs)):
        if _closes(pairs[end][0]):
            return end + 1
    return len(pairs)


def _closes(raw: str) -> bool:
    """Whether a word as written ends in a `)` that no backslash keeps."""
    return raw.endswith(")") and not _ends_in_escape(raw[:-1])


def _after_wrapper(
    pairs: list[tuple[str, str]], at: int, wrapper: str, out: list[str], disk: Lookups
) -> int | None:
    """Save a wrapper's options from `at` on (C1-fix1): an option in its table takes the next
    word or a glued value as `<arg>`, `--` ends them, `env` and `sudo` take `NAME=value`, and
    `timeout` then takes its duration; a redirection and its target are passed over. Returns where
    its program is expected, or None when the rest of the part is saved as `<arg>` (as after an
    option no table lists, `env -` too)."""
    values: str = _WRAPPERS[wrapper]
    target: bool = False  # the word after a bare redirection is its target
    while at < len(pairs):
        raw, word = pairs[at]
        if (after := _redirection_step(raw, target)) is not None:
            out.append(_classify_word(word, disk, web_tool=False))
            target = after
            at += 1
            continue
        if _out_of_step(raw):
            _rest_unread(pairs, at, out)
            return None
        if wrapper in ("env", "sudo") and (name := _assign_name(word)) is not None:
            out.append(f"{name}=<removed>")
            at = _after_assignment(pairs, at)
            continue
        if not _is_option(word) and word != "-":
            break
        at += 1
        if word == "--":
            out.append(word)
            break
        if word == "-" or word.startswith("--") or word[1] not in values:
            out.append(_classify_word(word, disk, web_tool=False))
            _rest_unread(pairs, at, out)
            return None
        if len(word) > 2:
            out.append(f"{word[:2]}<arg>")
            continue
        out.append(word)
        if (after := _wrapper_value(pairs, at, out)) is None:
            return None
        at = after
    return _wrapper_value(pairs, at, out) if wrapper == "timeout" else at


def _wrapper_value(pairs: list[tuple[str, str]], at: int, out: list[str]) -> int | None:
    """Save the wrapper's value at `at` as `<arg>` and return the index after it; None (the rest
    saved as `<arg>`) when the word may be no word or several, or is a redirection."""
    if at >= len(pairs):
        return at
    raw: str = pairs[at][0]
    if _out_of_step(raw) or _REDIRECT.match(raw):
        _rest_unread(pairs, at, out)
        return None
    out.append("<arg>")
    return at + 1


def _clean_web_words(pairs: list[tuple[str, str]], tool: str, disk: Lookups) -> list[str]:
    """A web tool's words (C1): the word after an option that takes a value is that value, and
    every word after ssh's destination is its remote command; neither is ever a website. Where
    the reading may be a word out of step it falls toward `<arg>`: an option where a value was
    expected is saved as that value and its own value comes next, and the word after an option
    that may already hold its value (`-p22`) may be ssh's destination. C1-fix1: a redirection
    and its target use up no value; the word after one that may be no word or several is a
    value, and for ssh that word and the rest are its command (it may hold the destination)."""
    out: list[str] = []
    value_next: bool = False
    may_be_whole: bool = False  # the option before this value may already hold its own value
    options_ended: bool = False
    remote: bool = False
    target: bool = False  # the word after a bare redirection is its target
    for raw, word in pairs:
        loose: bool = not remote and _out_of_step(raw)
        if remote or (loose and tool == "ssh"):
            out.append("<arg>")
            remote = True
            continue
        if (after := _redirection_step(raw, target)) is not None:
            out.append(_classify_word(word, disk, web_tool=True))
            target = after
            continue
        if value_next:
            out.append(disk.project_relative(word) or "<arg>")
            if _is_option(word) and word != "--":
                # the tool may have read it as the value it stands in place of, so the word
                # after it may be no value at all (ssh's destination)
                value_next = _takes_value(word, tool)
                may_be_whole = True
            else:
                value_next = False
                remote = may_be_whole and tool == "ssh"
        else:
            out.append(_classify_word(word, disk, web_tool=True))
            if options_ended or not _is_option(word):
                remote = tool == "ssh"  # the first word that is no option is ssh's destination
            else:
                options_ended = word == "--"
                value_next = not options_ended and _takes_value(word, tool)
                may_be_whole = _may_hold_value(word, tool)
        if loose:  # after the option's own reading: `-d$s` still waits for a value
            value_next = may_be_whole = True
    return out


def _is_option(word: str) -> bool:
    """`-x`, `-xyz`, `--name`, `--name=v` and `--`; a lone `-` is a word (standard input)."""
    return word.startswith("-") and word != "-"


def _takes_value(option: str, tool: str) -> bool:
    """Whether the word after `option` (`-x`, `-xyz`, `--name`, `--name=v`) is its value. A
    cluster is judged by its last letter, and an option the tool's table lacks takes a value."""
    short, long = _NO_VALUE[tool]
    if option.startswith("--"):
        return "=" not in option and option[2:] not in long
    return option[-1] not in short


def _may_hold_value(option: str, tool: str) -> bool:
    """Whether `option` may carry its own value, so that the word after it is no value: a long
    option, or a cluster with a letter before its last that is not listed as taking none (the
    tool reads the rest of the word as that letter's value). Only ssh asks: its destination."""
    if tool != "ssh":
        return False
    short, _ = _NO_VALUE[tool]
    return option.startswith("--") or bool(option[1:-1].strip(short))  # strip: C speed


def _classify_word(word: str, disk: Lookups, *, web_tool: bool) -> str:
    # (1) options: keep names, drop values, also a value stuck onto its option (-pSECRET)
    if word == "--":
        return word
    if word.startswith("--"):
        name: str = word[2:].split("=", 1)[0]
        if not _LONG_OPTION_NAME.fullmatch(name):
            return "<arg>"
        return f"--{name}=<arg>" if "=" in word else word
    if _is_option(word):
        # -pX and -la look alike, so a cluster keeps only its first letter.
        return word if len(word) == 2 else f"{word[:2]}<arg>"

    # (2) web address
    if "://" in word or web_tool:
        site: str | None = _website_name(word)
        if site is not None:
            return site
        if "://" in word:
            return "<arg>"

    # (3) existing file inside project_root
    rel: str | None = disk.project_relative(word)
    if rel is not None:
        return rel

    # (4) everything else
    return "<arg>"


def website_name(word: str) -> str | None:
    """Public alias for host extraction from a command token."""
    return _website_name(word)


def _website_name(word: str) -> str | None:
    host: str | None = None
    if "://" in word:
        try:
            host = urlparse(word).hostname
        except ValueError:  # e.g. an unbalanced [ in the address
            return None
    else:
        if word.startswith("@"):  # curl -d @file is a file, not a host
            return None
        # scp/rsync user@host:path
        candidate: str = word
        if "@" in candidate:
            candidate = candidate.rsplit("@", 1)[-1]
        if ":" in candidate and not candidate.startswith("["):
            # host:path or host:port — prefer left side if it looks like a name
            left: str = candidate.split(":", 1)[0]
            if left and "/" not in left:
                candidate = left
        # strip path-like suffix
        candidate = candidate.split("/")[0]
        if _HOST_WORD.fullmatch(candidate) and ("." in candidate or candidate == "localhost"):
            host = candidate

    if host is None or host == "":
        return None

    reduced: str = _reduce_host_labels(host)
    if _host_looks_encoded(reduced):
        return None
    return reduced


def _label_triggers_reduction(label: str) -> bool:
    if len(label) > 30:
        return True
    if len(label) >= 16 and any(c.isalpha() for c in label) and any(c.isdigit() for c in label):
        return True
    return False


def _reduce_host_labels(host: str) -> str:
    parts: list[str] = host.split(".")
    if len(parts) >= 3 and any(_label_triggers_reduction(p) for p in parts):
        return ".".join(parts[-2:])
    return host


def _host_looks_encoded(host: str) -> bool:
    return any(_label_triggers_reduction(p) for p in host.split("."))


def resolved_or_none(path: Path) -> Path | None:
    """`path.resolve()`, or None when the system cannot say: a part over its name limit, a lone
    surrogate or a NUL (`OSError`, `ValueError`), a link that leads back to itself
    (`RuntimeError`)."""
    try:
        return path.resolve()
    except (OSError, ValueError, RuntimeError):
        return None


def contained_relative(path: str, root: str) -> str | None:
    """`path` relative to `root`, both resolved and written with `/`, or None when it is outside.

    A string test: `Path.relative_to` is quadratic in the depth on Python 3.12. The root itself is
    ".". A root that already ends in "/" (the folder "/") is used as it is.
    """
    if path == root:
        return "."
    prefix: str = root if root.endswith("/") else root + "/"
    return path[len(prefix) :] if path.startswith(prefix) else None


def _folded(text: str) -> str:
    """An absolute path with `.` and `..` folded as text, no file system."""
    return posixpath.normpath("/" + text.lstrip("/"))  # normpath keeps a leading `//`


def home_expanded(path: str, home: str) -> str:
    """A leading `~`, `$HOME` or `${HOME}` is the home folder (rules' paths and `path_scope`)."""
    for prefix in ("~", "$HOME", "${HOME}"):
        if path == prefix or path.startswith(prefix + "/"):
            return home + path[len(prefix) :]
    return path


class _OverBudget(Exception):
    """The hook's look-ups are used up; the word being walked is not looked up."""


def _joined(here: str, rest: list[str]) -> str:
    return f"{here.rstrip('/')}/{'/'.join(rest)}" if rest else here


class Walker:
    """A budget of file-system look-ups (`lstat`, `readlink`) and what they learned, for one hook.

    `_walk` resolves a path one part at a time from a folder: each call is a step of the budget,
    a link is followed by its target's parts, and folders seen to be no link are not asked again.
    The step record's command words (`Lookups`) and a rule's `path_scope` (`inside_any`) each walk
    with one. Never the network, never `Path.resolve()`: a step count bounds the work.
    """

    def __init__(self, steps: int | None = None) -> None:
        self.left: int = LOOKUP_STEPS if steps is None else steps  # read now: a test lowers it
        self._plain: set[str] = set()  # paths seen to be no link (so every part above is a folder)
        self._links: dict[str, str] = {}
        self._roots: dict[str, str | None] = {}  # a root as sent -> resolved (`_resolved_root`)
        self._inside: dict[tuple[tuple[str, ...], str, str], bool] = {}

    def _spend(self, steps: int) -> None:
        if self.left < steps:
            raise _OverBudget
        self.left -= steps

    def _walk(self, start: str, parts: list[str], *, missing_text: bool = False) -> str | None:
        """The physical path `parts` lead to from `start`, or None when a call fails or there are
        too many links. Raises `_OverBudget` when the calls do not fit.

        A missing part ends the walk with None, unless `missing_text`: then it and the parts after
        it are joined as text with `..` folded. A `..` that cancels every missing part brings the
        walk back to a folder that exists, and it goes on from there (`new/../link/f` follows
        `link`)."""
        here: str = start
        pending: list[str] = parts[::-1]
        hops: int = 0
        while pending:
            name: str = pending.pop()
            if name in ("", "."):
                continue
            if name == "..":
                here = posixpath.dirname(here)
                continue
            path: str = f"{here}{name}" if here.endswith("/") else f"{here}/{name}"
            if path in self._plain:
                here = path
                continue
            target: str | None = self._links.get(path)
            if target is None:
                self._spend(1)
                try:
                    if not stat.S_ISLNK(os.lstat(path).st_mode):
                        self._plain.add(path)
                        here = path
                        continue
                    self._spend(1)
                    target = os.readlink(path)
                except FileNotFoundError:
                    if not missing_text:
                        return None
                    missing: list[str] = [name]
                    while pending and missing:
                        part: str = pending.pop()
                        if part == "..":
                            missing.pop()
                        elif part not in ("", "."):
                            missing.append(part)
                    if missing:
                        return _joined(here, missing)
                    continue  # back in `here`, which exists: walk the rest
                except (OSError, ValueError):
                    return None
                self._links[path] = target
            hops += 1
            if hops > MAX_LINK_HOPS:
                return None
            self._spend(1 + len(target) // LINK_PARTS)  # the target's parts are walked too
            if target.startswith("/"):
                here = "/"
            pending.extend(target.split("/")[::-1])
        return here

    def _resolved_root(self, root: str) -> str | None:
        """A root resolved by the walk, missing parts as text (a test root such as `/work/app`
        need not exist); None when it cannot be (an error, too many links, no steps left)."""
        if root not in self._roots:
            try:
                self._roots[root] = self._walk("/", root.split("/"), missing_text=True)
            except _OverBudget:
                self._roots[root] = None
        return self._roots[root]

    def inside_any(self, roots: object, path: str, home: str) -> bool:
        """Is `path` inside one of `roots` (an event's `workspace_roots`)? Every doubt is outside.

        Outside with no disk call: more than MAX_ROOTS roots, none usable (an absolute string of
        at most MAX_PATH_WORD characters that is not `/` as text or resolved), no path, a path
        over MAX_PATH_WORD, a relative path when the first root is not usable, or a path whose
        text (`~` and `$HOME` read as `home`, relative joined to the first root, `..` folded) is
        under no root as sent or as resolved. Otherwise the path is walked as sent and, if it
        holds `..`, as folded text too (a tool may fold it before the system does); it is inside
        only when every walk ends inside a resolved root, letter for letter."""
        if not isinstance(roots, list) or len(roots) > MAX_ROOTS or not path:
            return False
        sent: tuple[str, ...] = tuple(r if isinstance(r, str) else "" for r in roots)
        key: tuple[tuple[str, ...], str, str] = (sent, path, home)
        if key not in self._inside:
            self._inside[key] = self._judge(sent, path, home)
        return self._inside[key]

    def _usable(self, root: str) -> tuple[str, str] | None:
        """A root as folded text and as resolved, or None when it is not usable."""
        if not root.startswith("/") or len(root) > MAX_PATH_WORD or _folded(root) == "/":
            return None
        resolved: str | None = self._resolved_root(root)
        return None if resolved is None or resolved == "/" else (_folded(root), resolved)

    def _judge(self, sent: tuple[str, ...], path: str, home: str) -> bool:
        path = home_expanded(path, home)
        if not path.startswith("/"):
            if not sent or self._usable(sent[0]) is None:
                return False
            path = f"{sent[0]}/{path}"
        if len(path) > MAX_PATH_WORD:
            return False
        usable: list[tuple[str, str]] = [u for r in sent if (u := self._usable(r)) is not None]
        folded: str = _folded(path)
        if not any(
            contained_relative(folded, text) is not None
            or contained_relative(folded, resolved) is not None
            for text, resolved in usable
        ):
            return False  # outside as text: never looked up
        forms: list[str] = [path, folded] if ".." in path.split("/") else [path]
        try:
            ends: list[str | None] = [
                self._walk("/", form.split("/"), missing_text=True) for form in forms
            ]
        except _OverBudget:
            return False
        return all(
            end is not None
            and any(contained_relative(end, resolved) is not None for _, resolved in usable)
            for end in ends
        )


class Lookups(Walker):
    """The file-system look-ups of one hook's command words (V5d). One per hook, shared by the
    cleaner and the step record, so the words of a command spend one budget between them.

    A word is judged as text first, with no file-system call: joined to the root when it is
    relative, `.` and `..` folded, `~` not expanded, and tried against the root as sent and as
    resolved. A word outside both is outside; a link from outside that leads into the project does
    not make it inside. Only a word inside as text is walked: one `lstat` per part below the root,
    a link followed by its target's parts, a missing part ends the walk, and the end must still be
    inside the resolved root. It answers as `os.path.realpath(strict=True)` does (a test compares
    them). Each call is a step of the budget; a word that does not fit is left unresolved, which
    reads as "not a project file", so the record holds less, never more. What the walk learned
    (folders that are not links, links and their targets, each word's answer) is not asked again.
    """

    def __init__(self, project_root: Path, steps: int | None = None) -> None:
        super().__init__(steps)
        self._project_root: Path = project_root
        # The root as typed names a place by its text only if no `..` can climb out of a link.
        typed: bool = project_root.is_absolute() and ".." not in project_root.parts
        self._sent: str | None = str(project_root) if typed else None
        self._answers: dict[str, str | None] = {}

    def project_relative(self, word: str) -> str | None:
        """The word as a path inside the project when it names an existing file there, else None.
        Never raises; a word over `MAX_PATH_WORD` characters is not looked up."""
        if len(word) > MAX_PATH_WORD:
            return None
        if word not in self._answers:
            try:
                self._answers[word] = self._look_up(word)
            except _OverBudget:
                self._answers[word] = None
        return self._answers[word]

    def names_file(self, word: str) -> bool:
        return self.project_relative(word) is not None

    @cached_property
    def _root(self) -> str | None:
        """The resolved root, worked out once: None when the system cannot say or it is gone."""
        resolved: Path | None = resolved_or_none(self._project_root)
        if resolved is None:
            return None
        try:
            os.lstat(resolved)
        except (OSError, ValueError):
            return None
        self._plain.add(resolved.as_posix())
        return resolved.as_posix()

    def _look_up(self, word: str) -> str | None:
        root: str | None = self._root
        if root is None:
            return None
        absolute: bool = word.startswith("/")
        bases: tuple[str, ...] = (root,)
        if self._sent is not None and self._sent != root:
            bases = (self._sent, root)  # a word may sit in either
        if not any(
            contained_relative(_folded(word if absolute else f"{base}/{word}"), base) is not None
            for base in bases
        ):
            return None  # outside as text: never looked up
        # A word that starts with the root as typed walks from the resolved root, whose parts are
        # known; any other absolute word walks from `/`.
        start, rest = ("/", word) if absolute else (root, word)
        for base in bases if absolute else ():
            rel: str | None = contained_relative(word, base)
            if rel is not None:
                start, rest = root, rel
                break
        # Words in one folder share all but the last part: when the folder is already known to be
        # plain (no link above it), only the last part is looked at.
        head, _, leaf = f"{start.rstrip('/')}/{rest.lstrip('/')}".rpartition("/")
        if leaf not in ("", ".", "..") and (head or "/") in self._plain:
            start, rest = head or "/", leaf
        end: str | None = self._walk(start, rest.split("/"))
        return None if end is None else contained_relative(end, root)


def _project_relative(word: str, project_root: Path) -> str | None:
    """`Lookups.project_relative` for one word, with a budget of its own."""
    return Lookups(project_root).project_relative(word)
