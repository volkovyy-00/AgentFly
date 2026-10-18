"""System install (`agentfly init -g`) and removal (`agentfly uninstall`), SPEC section 7."""

from __future__ import annotations


class InstallError(Exception):
    """A refusal or failure with a message the user can act on. Nothing is half-written."""
