class PngError(Exception):
    pass


class PngValidationError(PngError, ValueError):
    """The current data cannot be represented by the supported PNG model."""
