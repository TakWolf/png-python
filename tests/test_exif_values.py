from struct import pack

import pytest

from png import PngValidationError
from png._exif_values import validate_values


def test_exif_closed_choices_keep_unknown_values_but_reject_reserved():
    # Unknown/other are assigned choices, distinct from reserved encodings.
    for tag, good, bad in [
        (0xA001, 65535, 2),
        (0x8822, 0, 9),
        (0x9207, 255, 7),
        (0x9208, 255, 5),
        (0xA217, 1, 6),
        (0xA407, 4, 5),
        (0xA408, 0, 3),
        (0x9209, 0x7D, 0x02),
        (0x9209, 0, 0x80),
    ]:
        validate_values(pack('>H', good), '>', 'exif', {tag: (3, 1, 0)})
        with pytest.raises(PngValidationError):
            validate_values(pack('>H', bad), '>', 'exif', {tag: (3, 1, 0)})


@pytest.mark.parametrize(
    'tag,valid,invalid',
    [
        (0x9003, b'2024:01:02 03:04:05', b'2024-01-02 03:04:05'),
        (0x9004, b'    :  :     :  :  ', b'2024:01:02T03:04:05'),
        (0x9010, b'+08:00', b'080000'),
        (0x9011, b'   :  ', b'++8:00'),
        (0x9290, b'123   ', b'12 3'),
        (0xA420, b'0123456789abcdefABCDEF0123456789', b'Z123456789abcdefABCDEF0123456789'),
    ],
)
def test_exif_text_formats_and_unknown_spaces(tag, valid, invalid):
    for value, succeeds in ((valid, True), (invalid, False)):
        data = value + b'\0'
        if succeeds:
            validate_values(data, '>', 'exif', {tag: (2, len(data), 0)})
        else:
            with pytest.raises(PngValidationError):
                validate_values(data, '>', 'exif', {tag: (2, len(data), 0)})
