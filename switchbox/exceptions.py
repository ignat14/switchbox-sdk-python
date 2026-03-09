class SwitchboxError(Exception):
    """Base exception for Switchbox SDK."""


class ConfigFetchError(SwitchboxError):
    """Raised when fetching flag config from CDN fails."""


class EvaluationError(SwitchboxError):
    """Raised when flag evaluation encounters an error."""
