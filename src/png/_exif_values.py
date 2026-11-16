"""Closed choices and textual value formats in CIPA DC-008-2024 4.6."""

import re
from struct import unpack_from

from png.error import PngValidationError


EXIF_SHORT_VALUES = {
    0xA001: (1, 65535),
    0x8822: tuple(range(9)),
    0x9207: (*range(7), 255),
    0x9208: (0, 1, 2, 3, 4, *range(9, 25), 255),
    0xA210: (2, 3),
    0xA217: (1, 2, 3, 4, 5, 7, 8),
    0xA401: (0, 1),
    0xA402: (0, 1, 2),
    0xA403: (0, 1),
    0xA406: (0, 1, 2, 3),
    0xA407: (0, 1, 2, 3, 4),
    0xA408: (0, 1, 2),
    0xA409: (0, 1, 2),
    0xA40A: (0, 1, 2),
    0xA40C: (0, 1, 2, 3),
}


def validate_values(profile: bytes, endian: str, role: str, fields: dict[int, tuple[int, int, int]]) -> None:
    if role == 'exif':
        for tag, allowed in EXIF_SHORT_VALUES.items():
            if tag in fields and fields[tag][0] == 3:
                if unpack_from(endian + 'H', profile, fields[tag][2])[0] not in allowed:
                    raise PngValidationError(f'Exif field {tag:#06x} has a reserved value')
        for tag, allowed in ((0xA300, (0, 1, 2, 3)), (0xA301, (1,))):
            if tag in fields and profile[fields[tag][2]] not in allowed:
                raise PngValidationError(f'Exif field {tag:#06x} has a reserved value')
        if 0x9101 in fields:
            start = fields[0x9101][2]
            if any(value > 6 for value in profile[start : start + 4]):
                raise PngValidationError('Exif ComponentsConfiguration uses a reserved component')
        if 0x9209 in fields:
            (value,) = unpack_from(endian + 'H', profile, fields[0x9209][2])
            if value & 0xFF80 or value & 6 == 2:
                raise PngValidationError('Exif Flash uses reserved bits or return status')
    if role == 'gps' and 5 in fields and profile[fields[5][2]] > 3:
        raise PngValidationError('Exif GPSAltitudeRef uses a reserved value')

    dates = {'image': (0x0132,), 'exif': (0x9003, 0x9004), 'gps': (0x001D,)}.get(role, ())
    for tag in dates:
        if tag not in fields:
            continue
        _, count, start = fields[tag]
        value = profile[start : start + count - 1]
        pattern = rb'[0-9 ]{4}:[0-9 ]{2}:[0-9 ]{2}'
        if role != 'gps':
            pattern += rb' [0-9 ]{2}:[0-9 ]{2}:[0-9 ]{2}'
        if value.strip(b' ') and not re.fullmatch(pattern, value):
            raise PngValidationError('Exif date/time has an invalid textual format')
    if role == 'exif':
        for tag in (0x9010, 0x9011, 0x9012, 0x9290, 0x9291, 0x9292, 0xA420):
            if tag not in fields:
                continue
            _, count, start = fields[tag]
            value = profile[start : start + count - 1]
            if tag in (0x9010, 0x9011, 0x9012):
                valid = value in (b'      ', b'   :  ') or re.fullmatch(rb'[+-][0-9]{2}:[0-9]{2}', value)
            elif tag == 0xA420:
                valid = re.fullmatch(rb'[0-9a-fA-F]{32}', value)
            else:
                valid = re.fullmatch(rb'[0-9]* *', value)
            if not valid:
                raise PngValidationError(f'Exif field {tag:#06x} has an invalid textual format')
