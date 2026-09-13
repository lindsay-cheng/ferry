"""Merge-layer errors for Cerebras integration."""


class MergeError(Exception):
    """Base error for merge failures."""


class MergeResponseError(MergeError):
    """Model output was empty or unusable."""


class MergeClientError(MergeError):
    """Cerebras HTTP client or configuration failure."""
