"""Dummy secrets in every shape the cleaner must drop (SPEC section 4). Shared by tests."""

from __future__ import annotations

SECRET: str = "SEKRET9"

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
