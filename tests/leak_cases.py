"""Dummy secrets in every shape the cleaner must drop (SPEC section 4). Shared by tests."""

from __future__ import annotations

SECRET: str = "SEKRET9"
JWT: str = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.abcDEF"

# C1: what d62ea42 saved with an option's value or ssh's remote command as a website, as
# (command, what is saved now, the kept part that must go, the step's hosts).
OBSERVED_VALUE_LEAKS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("curl -d token.abc host.com", "curl -d <arg> host.com", "token.abc", ("host.com",)),
    (
        f"curl -d {JWT} api.example.com",
        "curl -d <arg> api.example.com",
        "abcDEF",
        ("api.example.com",),
    ),
    (f"wget --post-data {JWT} x.com", "wget --post-data <arg> x.com", "abcDEF", ("x.com",)),
    ("curl x.com -d sk_live.abc123", "curl x.com -d <arg>", "sk_live", ("x.com",)),
    (f"curl -d https://{JWT} x.com", "curl -d <arg> x.com", "abcDEF", ("x.com",)),
    ("ssh h.com cat tok.abc", "ssh h.com <arg> <arg>", "tok.abc", ("h.com",)),
)

LEAKY_COMMANDS: tuple[str, ...] = (
    # attached short options
    f"curl -uuser:{SECRET} https://h.com",
    f"curl -u'user:{SECRET}' h.com",
    f"mysql -p{SECRET} db",
    f"mysql -p'{SECRET}' db",
    f"curl -H'Authorization: Bearer {SECRET}' https://h.com",
    f"tool -p={SECRET}",
    # long options
    f"curl --password={SECRET} h.com",
    f"tool --token={SECRET}",
    f"tool --api-key={SECRET}",
    f"tool --x:{SECRET}",
    # URL credentials
    f"curl https://user:{SECRET}@host.com/path?t=1",
    f"git clone https://user:{SECRET}@host.com/r.git",
    f"curl https://u:{SECRET}@[host/",
    # env-prefix and export assignments
    f"TOKEN={SECRET} make",
    f"A=1 TOKEN={SECRET} make",
    f"export K={SECRET}",
    f"export K={SECRET} && curl https://x.com",
    f"TOKEN='my {SECRET}' curl $(x)",
    f"export K='a {SECRET}' && echo `x`",
    f"K='a {SECRET}' cat <<EOF\nbody\nEOF",
    # data arguments that only look like a host name, and other assignment forms
    f"curl -d token={SECRET}.abc https://x.com",
    f"curl -d @{SECRET}.json https://x.com",
    f"curl -d 'hello {SECRET}.com' https://x.com",
    f"K+={SECRET} make",
    f"K+='{SECRET} x' make",
    f"a[0]={SECRET} make",
    f"'sec {SECRET}' --flag",
    # inside a pipeline
    f"cat .env | curl -uadmin:{SECRET} https://w.site",
)

# C1: an option's value, and every word after ssh's destination, shaped like a host. Each form a
# web tool has (short, a cluster ending in a value letter, attached, long, `=`, after the
# destination); nc, scp and ssh have no long options.
_VALUE_FORMS: tuple[str, ...] = (
    "curl -d {V} x.com",
    "curl -sd {V} x.com",
    "curl -d{V} x.com",
    "curl --data {V} x.com",
    "curl --data={V} x.com",
    "curl x.com -d {V}",
    "curl -d https://{V} x.com",
    "wget -O {V} x.com",
    "wget -qO {V} x.com",
    "wget -O{V} x.com",
    "wget --post-data {V} x.com",
    "wget --post-data={V} x.com",
    "wget x.com --post-data {V}",
    "nc -s {V} h.com 80",
    "nc -vs {V} h.com 80",
    "nc -s{V} h.com 80",
    "nc h.com 80 -s {V}",
    "scp -i {V} f user@h.com:/p",
    "scp -qi {V} f user@h.com:/p",
    "scp -i{V} f user@h.com:/p",
    "scp f user@h.com:/p -i {V}",
    "ssh -i {V} h.com",
    "ssh -qi {V} h.com",
    "ssh -i{V} h.com",
    "ssh h.com -i {V}",
    "ssh h.com cat {V}",
    "rsync -e {V} src h.com:dst",
    "rsync -ae {V} src h.com:dst",
    "rsync -e{V} src h.com:dst",
    "rsync --rsh {V} src h.com:dst",
    "rsync --rsh={V} src h.com:dst",
    "rsync src h.com:dst -e {V}",
    # a value option right after a glued value or an unlisted option, which the cleaner already
    # read as taking the next word; and ssh's remote command after a glued value
    "curl -XPOST -d {V} x.com",
    "curl --no-fail -d {V} x.com",
    "curl -d -d {V} x.com",
    "wget --quie -O {V} x.com",
    "nc -s1.2.3.4 -s {V} h.com 80",
    "scp -P22 -i {V} f user@h.com:/p",
    "rsync --no-perms -e {V} src h.com:dst",
    "ssh -p22 -i {V} h.com",
    "ssh -p2222 h.com {V}",
    "ssh -p2222 h.com https://{V}",
    "ssh -oBatchMode=no h.com {V}",
    "ssh -i~/.ssh/id h.com {V}",
)
_HOST_SHAPED: tuple[str, ...] = (f"{SECRET}.abc", f"eyJhbGciOiJIUzI1NiJ9.{SECRET}.abc")

LEAKY_COMMANDS += tuple(form.format(V=value) for form in _VALUE_FORMS for value in _HOST_SHAPED)
