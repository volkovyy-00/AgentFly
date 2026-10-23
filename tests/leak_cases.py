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
    # C1-fix1: what c7ab4d7 saved with a web tool that is not its part's first word
    (f"sudo curl -d https://{JWT} x.com", "sudo curl -d <arg> x.com", "abcDEF", ("x.com",)),
    (f"exec curl -d https://{JWT} x.com", "exec curl -d <arg> x.com", "abcDEF", ("x.com",)),
    (
        "curl x.com & ssh h.com tok.abc",
        "curl x.com & ssh h.com <arg>",
        "tok.abc",
        ("x.com", "h.com"),
    ),
    (
        "curl x.com\nssh h.com tok.abc",
        "curl x.com ; ssh h.com <arg>",
        "tok.abc",
        ("x.com", "h.com"),
    ),
    ("curl -d \\\n tok.abc x.com", "curl -d <arg> x.com", "tok.abc", ("x.com",)),
    ("curl -d >out tok.abc x.com", "curl -d <arg> <arg> x.com", "tok.abc", ("x.com",)),
    ("curl -d $EMPTY tok.abc x.com", "curl -d <arg> <arg> x.com", "tok.abc", ("x.com",)),
    (r"curl -d a\;tok.abc x.com", "curl -d <arg> x.com", "tok.abc", ("x.com",)),
    (f'sudo bash -c "curl -d https://{JWT} x.com"', "sudo bash -c <arg>", "abcDEF", ()),
)

# C1-fix1: the brief's commands with a web tool behind a wrapper or `(`, now saved with its name
# and its host, as (command, what is saved, the tool).
NEWLY_SAVED: tuple[tuple[str, str, str], ...] = (
    ("sudo curl -s x.com", "sudo curl -s x.com", "curl"),
    ("sudo -u bob curl -s x.com", "sudo -u <arg> curl -s x.com", "curl"),
    ("env A=1 curl -L x.com", "env A=<removed> curl -L x.com", "curl"),
    ("timeout 5 wget -q x.com", "timeout <arg> wget -q x.com", "wget"),
    ("nice -n 5 curl -s x.com", "nice -n <arg> curl -s x.com", "curl"),
    ("exec curl -s x.com", "exec curl -s x.com", "curl"),
    ("(curl -s x.com)", "curl -s x.com", "curl"),
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
    "ssh -i -p h.com {V}",
    "curl -5 {V} x.com",
)
# C1-fix1: a value behind each listed wrapper and its options (one unlisted, `caffeinate`, and
# `sudo -E`, which leave the rest `<arg>`), in `( … )`, after `&`, `|&`, a new line and a
# continuation; around each redirection form; after each word that may be no word or several.
# (`{{` and `}}` are a brace in a form.)
_WRAPPED: tuple[str, ...] = (
    "sudo",
    "sudo -u bob",
    "sudo -ubob",
    "doas -u bob",
    "env A=1",
    "env -u A",
    "timeout 5",
    "timeout -s KILL 5",
    "time",
    "nice -n 5",
    "nohup",
    "command",
    "exec",
    "stdbuf -oL",
    "xargs",
    "xargs -I{{}}",
    "sudo env A=1 timeout 5 nice -n 5",
    "sudo -E",
    "caffeinate",
)
_VALUE_FORMS += tuple(f"{w} curl -d {v} x.com" for w in _WRAPPED for v in ("{V}", "https://{V}"))
_VALUE_FORMS += (
    "(curl -d {V} x.com)",
    "( curl -d https://{V} x.com )",
    "((curl -d {V} x.com) )",
    "cd a & curl -d {V} x.com",
    "curl x.com & ssh h.com {V}",
    "curl x.com |& ssh h.com {V}",
    "cd a\ncurl -d {V} x.com",
    "curl x.com\nssh h.com {V}",
    "curl -d \\\n {V} x.com",
    "curl -d a\\;{V} x.com",
    "curl x.com &<in ssh h.com {V}",
    "curl x.com # \\\nssh h.com {V}",
    "arr=(a {V})",
    "curl -d>out {V} x.com",
    "curl -d$s {V} x.com",
    "ssh -i $K h.com {V}",
    "ssh $O h.com {V}",
    "sudo ssh h.com cat {V}",
    "timeout $T curl -d {V} x.com",
    # final verification: a character a backslash keeps is no operator and no word break, a
    # continuation does not end a word, a redirection does not end a wrapper's options, `env -`
    "echo \\>& ssh h.com curl https://{V}",
    "echo \\>| ssh h.com https://{V}",
    "ssh h.com \\>#b \\\nx https://{V}",
    "ssh h.com a\\ #b \\\nx https://{V}",
    "ssh h.com a\\;#b \\\nx https://{V}",
    "ssh h.com a\\\n#b \\\nx https://{V}",
    "sudo >out -u bob ssh h.com curl https://{V}",
    "env 2>/dev/null -u X ssh h.com curl https://{V}",
    "env - ssh h.com curl https://{V}",
    "env - PATH=/bin ssh h.com curl https://{V}",
    "sudo/ {V}",
    # lenses: `${…}` holding a space or a separator is one word to the shell (zsh, or bash with
    # IFS changed), `\r` is no word break, and `<(…)` / `>(…)` is no redirection
    "curl -d ${{X:-a b {V} c}} x.com",
    "curl -d ${{X:-a;{V} x}} x.com",
    "caffeinate curl -d ${{X:-a b https://{V} c}}",
    "curl -d a\r{V} x.com",
    "ssh -p 22\r{V} h.com",
    "caffeinate curl -d a\rhttps://{V}",
    "ssh -o <(x) h.com {V}",
    "ssh -F >(cat) h.com {V}",
)
_REDIRECTIONS: tuple[str, ...] = (
    ">out",
    "> out",
    ">>log",
    "2>&1",
    "2> err",
    "&>log",
    "<in",
    "< in",
    ">| out",
    "{{fd}}>out",
)
_VALUE_FORMS += tuple(
    f"{tool} {r} {{V}} x.com" for tool in ("curl -d", "wget -O") for r in _REDIRECTIONS
)
_LOOSE: tuple[str, ...] = ("$E", "${{E}}", "a$E", '"$@"', '"${{A[@]}}"', "{{,}}", "?d")
_VALUE_FORMS += tuple(f"curl -d {w} {{V}} x.com" for w in _LOOSE)
_HOST_SHAPED: tuple[str, ...] = (f"{SECRET}.abc", f"eyJhbGciOiJIUzI1NiJ9.{SECRET}.abc")

LEAKY_COMMANDS += tuple(form.format(V=value) for form in _VALUE_FORMS for value in _HOST_SHAPED)
