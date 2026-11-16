"""Pure helpers for sensitive file names, local hosts and the hosts a command names."""

from __future__ import annotations

import ipaddress
import re
import shlex
from collections.abc import Iterator, Sequence

from agentfly.recorder.normalize import SUB_EMPTY, SUB_PREFIX, WRAPPERS, base_name, programs


def is_sensitive(path: str) -> bool:
    """Return True if the file name alone looks like a secret-bearing file.

    The lists live in the rules file (R1's `after`, V5b); this asks the rules in force.
    """
    from agentfly.recorder.rules import is_secret_path  # rules.py imports this module

    return is_secret_path(path)


def is_local_host(host: str) -> bool:
    """Return True for loopback and RFC1918 private addresses."""
    if host.lower() == "localhost" or host == "::1":
        return True
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(addr.is_loopback or addr.is_private)


# ---------------------------------------------------------------- the hosts one word names
# (SPEC section 5, "Not blocked"; P2.) A word is read as curl reads a URL, and as ssh reads a
# destination when an `@` stands past the host. Every doubt names a host that is not this computer.
# `agentfly/hook_client.py` holds a copy for the offline guard (`_word_hosts`); a test keeps the two
# equal word for word.

_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://")
_HOST_END = re.compile(r"[/?#]")
_GLOB = re.compile(r"[{},]")


def _option_value(word: str) -> str | None:
    """Step 1 (b): the word itself or, past its leading `-opt=` spellings, their value (`--url=h`,
    `-a=-b=h`); None for an option with no `=` (`-d@f`). One pass by index, no recursion."""
    at: int = 0
    while word.startswith("-", at):
        equals: int = word.find("=", at)
        if equals < 0:
            return None
        at = equals + 1
    return word[at:]


def _url_candidates(word: str) -> list[tuple[str, bool]]:
    """Step 1: (a) the text after the word's first `://`, a URL (`-d@https://h`); (b) the value of
    `_option_value`, a URL when it starts with a scheme (dropped). Each with whether it is a URL;
    the two may be the same text (`word_hosts` keeps each host once)."""
    found: list[tuple[str, bool]] = []
    sep: int = word.find("://")
    if sep >= 0:
        found.append((word[sep + 3 :], True))
    value: str | None = _option_value(word)
    if value is not None:
        scheme: re.Match[str] | None = _SCHEME.match(value) if sep >= 0 else None
        found.append((value[scheme.end() :], True) if scheme else (value, False))
    return found


def _cut(text: str) -> int:
    """Where the host part of a URL ends: its first `/`, `?` or `#`."""
    end: re.Match[str] | None = _HOST_END.search(text)
    return end.start() if end else len(text)


def _regions(text: str, url: bool) -> list[str]:
    """Step 2: curl's host (before the cut, after the last `@` there) and, when an `@` also stands
    at or past the cut, ssh's (after the last `@`, up to its own cut; owner 2026-11-16). A word that
    is no URL is also read as scp, rsync and wget read `[user@]host:path`: before its first `:`
    when no `/` comes first, after the last `@` there (`evil.example:x@localhost`)."""
    cut: int = _cut(text)
    head: str = text[:cut]
    regions: list[str] = [head[head.rfind("@") + 1 :]]
    if text.find("@", cut) >= 0:
        tail: str = text[text.rfind("@") + 1 :]
        regions.append(tail[: _cut(tail)])
    colon: int = -1 if url else text.find(":")
    if colon >= 0 and "/" not in text[:colon]:
        before: str = text[:colon]
        regions.append(before[before.rfind("@") + 1 :])
    return regions


def _could_be_host(region: str) -> bool:
    """Step 3: a bare word names a host only if it could today: a dot, a colon or `localhost`, and
    a letter or a digit (`./`, `f` and `src` name none; `backup:` names `backup`)."""
    shaped: bool = "." in region or ":" in region or region == "localhost"
    shaped = shaped or "%2e" in region.casefold()  # curl reads `evil%2Eexample` as `evil.example`
    return shaped and any(ch.isalnum() for ch in region)


def _is_ip(text: str) -> bool:
    try:
        ipaddress.ip_address(text)
    except ValueError:
        return False
    return True


def _port_cut(region: str) -> str:
    """Step 4: the host without its `:port`. Whitespace keeps the region whole; `[v6]` and
    `[v6]:port` give the text inside (any other bracket shape: whole); an IP address (`::1`) is
    whole; else the text before the first `:` (`host:22`, `localhost::mod`), maybe empty."""
    if any(ch.isspace() for ch in region):
        return region
    if "[" in region or "]" in region:
        close: int = region.find("]")
        shaped: bool = region.startswith("[") and region.count("[") == region.count("]") == 1
        if shaped and (close == len(region) - 1 or region[close + 1] == ":"):
            return region[1:close]
        return region
    colon: int = region.find(":")
    if colon < 0 or (region.count(":", colon + 1) and _is_ip(region)):  # IPv6 has 2 colons or more
        return region
    return region[:colon]


def _host(region: str, url: bool) -> str | None:
    """Step 3 and 4: what a region names. A URL's region is always a host; a bare one only if it
    could be."""
    if not url and not _could_be_host(region):
        return None
    return _port_cut(region)


def _hosts(word: str) -> list[str]:
    """Steps 1 to 4 on one word."""
    found: list[str] = []
    for text, url in _url_candidates(word):
        for region in _regions(text, url):
            host: str | None = _host(region, url)
            if host is not None:
                found.append(host)
    return found


def word_hosts(word: str) -> tuple[str, ...]:
    """The hosts one word names, in order, each once. A word holding `$` or a substitution's output
    (`normalize` writes `$(…)`, backticks and `<(…)` as `@sub:…@` or `@sub@`) names one host nobody
    can read, `$`: the shell may split it into more words (`localhost/$(echo a evil.example)`), and
    quotes are not seen. A word with `{` is also read piece by piece (curl's globbing, `{a,b}`)."""
    if "$" in word or SUB_PREFIX in word or SUB_EMPTY in word:
        return ("$",)
    if "." not in word and ":" not in word and "%" not in word and "localhost" not in word:
        return ()  # no part of it could be a host (`curl`, `-sS`, `src/`)
    found: list[str] = _hosts(word)
    if "{" in word:
        for piece in _GLOB.split(word):
            found.extend(_hosts(piece))
    return tuple(dict.fromkeys(found)) if len(found) > 1 else tuple(found)


# ---------------------------------------------------------------- the hosts a command names

# curl reads `@name` as a file after these options: `curl -d @data.json` sends a file, it names no
# host. After any other word an `@` word is a URL (`curl -s @evil.example`). A short option counts
# when its letter ends the cluster (`-sd @f`); `--expand-<option>` (curl 8.3) is the same option.
_AT_FILE_LONG: frozenset[str] = frozenset(
    {"--data", "--data-ascii", "--data-binary", "--data-urlencode", "--json", "--header"}
    | {"--url-query", "--variable"}
)
_AT_FILE_SHORT: str = "dH"
# curl's form options read a file from `name=@file` or `name=<file`.
_FORM_LONG: frozenset[str] = frozenset({"--form", "--form-string"})
_FORM_SHORT: str = "F"
# curl's short option letters and long option names that take no value: the cleaner's curl row
# (`clean._NO_VALUE`, curl 8.7.1 `--help all`); a test keeps the two equal. Any other option
# takes a value.
CURL_NO_VALUE: tuple[str, frozenset[str]] = (
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
)


def _long_name(option: str) -> str:
    name: str = option.casefold().removeprefix("--expand-")
    return name if name.startswith("--") else f"--{name}"


def _cluster_value_letter(option: str) -> str | None:
    """The letter of a short-option cluster whose value is the next word, or None. curl reads the
    letters in turn; the first that takes a value takes the rest of the cluster (`-m5`), or, when
    it ends the cluster, the next word (`-sd @f`)."""
    for at in range(1, len(option)):
        if option[at] not in CURL_NO_VALUE[0]:
            return option[at] if at == len(option) - 1 else None
    return None


def _curl_option_in(option: str, long: frozenset[str], short: str) -> bool:
    """Is this curl option one of these (a long name, or a cluster whose value letter is listed)?
    `-d @data.json` and `-F file=@data.json` name a file: `_AT_FILE_*` and `_FORM_*`."""
    if option.startswith("--"):
        return _long_name(option) in long
    letter: str | None = _cluster_value_letter(option) if option.startswith("-") else None
    return letter is not None and letter in short


def _takes_next_word(option: str) -> bool:
    """Does this curl option take the next word as its value? One curl's table lacks does."""
    if option.startswith("--"):
        return option[2:].casefold() not in CURL_NO_VALUE[1]
    return len(option) == 1 or _cluster_value_letter(option) is not None


def _maybe_data_file(argv: Sequence[str], at: int) -> bool:
    """The word at `at` stands where curl may read a file: after a data option (an `@` word) or a
    form option (`name=@file`, `name=<file`). Looks at two words only."""
    if at < 2:
        return False
    word: str = argv[at]
    option: str = argv[at - 1]
    if word.startswith("@") and _curl_option_in(option, _AT_FILE_LONG, _AT_FILE_SHORT):
        return True
    return ("=@" in word or "=<" in word) and _curl_option_in(option, _FORM_LONG, _FORM_SHORT)


def _plain_curl(argv: Sequence[str]) -> tuple[int, int]:
    """Where curl stands when it is the program run plainly (alone, or at the end of a chain of
    wrappers: `sudo curl`), and where the first `--` after it stands; (-1, 0) when it is not."""
    chain: tuple[int, ...] = programs(argv, narrow=True)
    if not chain or base_name(argv[chain[-1]]) != "curl":
        return -1, 0
    if any(base_name(argv[at]) not in WRAPPERS for at in chain[:-1]):
        return -1, 0
    curl: int = chain[-1]
    try:
        return curl, argv.index("--", curl + 1)
    except ValueError:
        return curl, len(argv)


def _is_data_file(argv: Sequence[str], at: int, curl: int, dashes: int) -> bool:
    """`_maybe_data_file` holds, and the option before it is curl's option, not a value: the word
    before the option is curl, a word that is no option, or an option that takes no value. curl
    is the plain program before the option, and no `--` stands between it and the word."""
    before: str = argv[at - 2]
    option_is_option: bool = not before.startswith("-") or not _takes_next_word(before)
    return option_is_option and 0 <= curl < at - 1 and dashes > at


def hosts_in_command(argv: Sequence[str]) -> Iterator[str]:
    """The hosts a simple command names, word by word and lazily (R1 stops at the first that is not
    this computer). A curl data file (`curl -d @data.json`, `-F file=@data.json`) names none."""
    curl: int | None = None  # worked out once, and only when some word may be a data file
    dashes: int = 0
    for at, word in enumerate(argv):
        if _maybe_data_file(argv, at):
            if curl is None:
                curl, dashes = _plain_curl(argv)
            if _is_data_file(argv, at, curl, dashes):
                continue
        yield from word_hosts(word)


def words(cmd: str) -> list[str]:
    """Split a shell command into words; fall back if shlex fails."""
    try:
        return shlex.split(cmd)
    except ValueError:
        return cmd.split()
