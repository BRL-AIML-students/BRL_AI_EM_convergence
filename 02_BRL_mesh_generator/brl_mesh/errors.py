class ConfigurationError(ValueError):
    """Invalid or currently unsupported input."""


class MeshBlocked(RuntimeError):
    """A required mesh, quality or NAS check failed."""
