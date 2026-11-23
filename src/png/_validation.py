from png.error import PngValidationError


def check_integer(name: str, value: int, minimum: int, maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise PngValidationError(f'{name} must be an integer in [{minimum}, {maximum}]')


def check_boolean(name: str, value: bool) -> None:
    if not isinstance(value, bool):
        raise PngValidationError(f'{name} must be bool')
