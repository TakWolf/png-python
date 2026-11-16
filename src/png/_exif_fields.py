"""Present-field layouts from CIPA DC-008-2024 Tables 6, 8, 9, 14 and 16.

Counts of None are variable. Namespaces are IFD roles, not global TIFF tags.
Unknown/private entries retain their declared storage types.
"""

IMAGE_FIELDS = {
    0x0100: ((3, 4), (1,)),
    0x0101: ((3, 4), (1,)),
    0x0102: ((3,), (3,)),
    0x0103: ((3,), (1,)),
    0x0106: ((3,), (1,)),
    0x0112: ((3,), (1,)),
    0x0115: ((3,), (1,)),
    0x011A: ((5,), (1,)),
    0x011B: ((5,), (1,)),
    0x011C: ((3,), (1,)),
    0x0128: ((3,), (1,)),
    0x0212: ((3,), (2,)),
    0x0213: ((3,), (1,)),
    0x0111: ((3, 4), None),
    0x0116: ((3, 4), (1,)),
    0x0117: ((3, 4), None),
    0x0201: ((4,), (1,)),
    0x0202: ((4,), (1,)),
    0x012D: ((3,), (768,)),
    0x013E: ((5,), (2,)),
    0x013F: ((5,), (6,)),
    0x0211: ((5,), (3,)),
    0x0214: ((5,), (6,)),
    0x010E: ((2, 129), None),
    0x010F: ((2, 129), None),
    0x0110: ((2, 129), None),
    0x0131: ((2, 129), None),
    0x0132: ((2,), (20,)),
    0x013B: ((2, 129), None),
    0x8298: ((2, 129), None),
}

EXIF_FIELDS = {
    0x9000: ((7,), (4,)),
    0xA000: ((7,), (4,)),
    0xA001: ((3,), (1,)),
    0xA500: ((5,), (1,)),
    0x9101: ((7,), (4,)),
    0x9102: ((5,), (1,)),
    0xA002: ((3, 4), (1,)),
    0xA003: ((3, 4), (1,)),
    0x927C: ((7,), None),
    0x9286: ((7,), None),
    0xA004: ((2,), (13,)),
    0x9003: ((2,), (20,)),
    0x9004: ((2,), (20,)),
    0x9010: ((2,), (7,)),
    0x9011: ((2,), (7,)),
    0x9012: ((2,), (7,)),
    0x9290: ((2,), None),
    0x9291: ((2,), None),
    0x9292: ((2,), None),
    0x9400: ((10,), (1,)),
    0x9401: ((5,), (1,)),
    0x9402: ((5,), (1,)),
    0x9403: ((10,), (1,)),
    0x9404: ((5,), (1,)),
    0x9405: ((10,), (1,)),
    0xA420: ((2,), (33,)),
    0xA430: ((2, 129), None),
    0xA431: ((2,), None),
    0xA432: ((5,), (4,)),
    0xA433: ((2, 129), None),
    0xA434: ((2, 129), None),
    0xA435: ((2,), None),
    0xA436: ((2, 129), None),
    0xA437: ((2, 129), None),
    0xA438: ((2, 129), None),
    0xA439: ((2, 129), None),
    0xA43A: ((2, 129), None),
    0xA43B: ((2, 129), None),
    0xA43C: ((2, 129), None),
    0x829A: ((5,), (1,)),
    0x829D: ((5,), (1,)),
    0x8822: ((3,), (1,)),
    0x8824: ((2,), None),
    0x8827: ((3,), None),
    0x8828: ((7,), None),
    0x8830: ((3,), (1,)),
    0x8831: ((4,), (1,)),
    0x8832: ((4,), (1,)),
    0x8833: ((4,), (1,)),
    0x8834: ((4,), (1,)),
    0x8835: ((4,), (1,)),
    0x9201: ((10,), (1,)),
    0x9202: ((5,), (1,)),
    0x9203: ((10,), (1,)),
    0x9204: ((10,), (1,)),
    0x9205: ((5,), (1,)),
    0x9206: ((5,), (1,)),
    0x9207: ((3,), (1,)),
    0x9208: ((3,), (1,)),
    0x9209: ((3,), (1,)),
    0x920A: ((5,), (1,)),
    0x9214: ((3,), (2, 3, 4)),
    0xA20B: ((5,), (1,)),
    0xA20C: ((7,), None),
    0xA20E: ((5,), (1,)),
    0xA20F: ((5,), (1,)),
    0xA210: ((3,), (1,)),
    0xA214: ((3,), (2,)),
    0xA215: ((5,), (1,)),
    0xA217: ((3,), (1,)),
    0xA300: ((7,), (1,)),
    0xA301: ((7,), (1,)),
    0xA302: ((7,), None),
    0xA401: ((3,), (1,)),
    0xA402: ((3,), (1,)),
    0xA403: ((3,), (1,)),
    0xA404: ((5,), (1,)),
    0xA405: ((3,), (1,)),
    0xA406: ((3,), (1,)),
    0xA407: ((3, 5), (1,)),
    0xA408: ((3,), (1,)),
    0xA409: ((3,), (1,)),
    0xA40A: ((3,), (1,)),
    0xA40B: ((7,), None),
    0xA40C: ((3,), (1,)),
    0xA460: ((3,), (1,)),
    0xA461: ((3,), (2,)),
    0xA462: ((7,), None),
}

GPS_FIELDS = {
    0x0000: ((1,), (4,)),
    0x0001: ((2,), (2,)),
    0x0002: ((5,), (3,)),
    0x0003: ((2,), (2,)),
    0x0004: ((5,), (3,)),
    0x0005: ((1,), (1,)),
    0x0006: ((5,), (1,)),
    0x0007: ((5,), (3,)),
    0x0008: ((2,), None),
    0x0009: ((2,), (2,)),
    0x000A: ((2,), (2,)),
    0x000B: ((5,), (1,)),
    0x000C: ((2,), (2,)),
    0x000D: ((5,), (1,)),
    0x000E: ((2,), (2,)),
    0x000F: ((5,), (1,)),
    0x0010: ((2,), (2,)),
    0x0011: ((5,), (1,)),
    0x0012: ((2,), None),
    0x0013: ((2,), (2,)),
    0x0014: ((5,), (3,)),
    0x0015: ((2,), (2,)),
    0x0016: ((5,), (3,)),
    0x0017: ((2,), (2,)),
    0x0018: ((5,), (1,)),
    0x0019: ((2,), (2,)),
    0x001A: ((5,), (1,)),
    0x001B: ((7,), None),
    0x001C: ((7,), None),
    0x001D: ((2,), (11,)),
    0x001E: ((3,), (1,)),
    0x001F: ((5,), (1,)),
}

INTEROP_FIELDS = {
    0x0001: ((2,), None),
}


def validate_fields(profile: bytes, endian: str, role: str, fields: dict[int, tuple[int, int, int]]) -> None:
    from struct import unpack_from
    from png.error import PngValidationError

    rules = {'image': IMAGE_FIELDS, 'exif': EXIF_FIELDS, 'gps': GPS_FIELDS, 'interop': INTEROP_FIELDS}[role]
    version = b''
    if role == 'exif' and 0x9000 in fields:
        _, _, start = fields[0x9000]
        version = profile[start:start + 4]
    for tag, (kind, count, start) in fields.items():
        rule = rules.get(tag)
        if rule is None:
            continue
        kinds, counts = rule
        # DC-008-2024 Table 8 says RATIONAL for GainControl, whereas
        # 4.6.6.7.41 says SHORT. Preserve both without inventing a version change.
        if kind not in kinds or (counts is not None and count not in counts):
            raise PngValidationError(f'Exif {role} field {tag:#06x} has an invalid type or count')
    if role == 'image':
        short_values = {0x0103: (1, 6), 0x0106: (2, 6), 0x0112: tuple(range(1, 9)),
                        0x0115: (3,), 0x011C: (1, 2), 0x0128: (2, 3), 0x0213: (1, 2)}
        for tag, allowed in short_values.items():
            if tag in fields and unpack_from(endian + 'H', profile, fields[tag][2])[0] not in allowed:
                raise PngValidationError(f'Exif {role} field {tag:#06x} has a reserved value')
        if 0x0102 in fields and unpack_from(endian + '3H', profile, fields[0x0102][2]) != (8, 8, 8):
            raise PngValidationError('Exif BitsPerSample must specify three eight-bit components')
        if 0x0212 in fields and unpack_from(endian + '2H', profile, fields[0x0212][2]) not in ((2, 1), (2, 2)):
            raise PngValidationError('Exif YCbCrSubSampling uses a reserved value')
    if role == 'gps':
        ascii_values = {1: b'NS', 3: b'EW', 9: b'AV', 10: b'23', 12: b'KMN',
                        14: b'TM', 16: b'TM', 19: b'NS', 21: b'EW', 23: b'TM', 25: b'KMN'}
        for tag, allowed in ascii_values.items():
            if tag in fields and profile[fields[tag][2]] not in allowed:
                raise PngValidationError(f'Exif GPS field {tag:#06x} has a reserved reference value')
        if 30 in fields and unpack_from(endian + 'H', profile, fields[30][2])[0] not in (0, 1):
            raise PngValidationError('Exif GPSDifferential must be zero or one')
    if role == 'exif':
        from png._exif_binary import validate_binary
        for tag in (0x8828, 0xA20C, 0xA302, 0xA40B, 0xA462, 0x9286):
            if tag in fields:
                _, size, start = fields[tag]
                validate_binary(tag, profile[start:start + size], endian, version)
        for tag in (0x8831, 0x8832, 0x8833):
            if tag in fields and not {0x8827, 0x8830}.issubset(fields):
                raise PngValidationError('Exif sensitivity values require PhotographicSensitivity and SensitivityType')
        if (0x8834 in fields or 0x8835 in fields) and not {0x8833, 0x8834, 0x8835}.issubset(fields):
            raise PngValidationError('Exif ISO speed latitude requires both latitude values and ISOSpeed')
        if 0x8830 in fields and unpack_from(endian + 'H', profile, fields[0x8830][2])[0] > 7:
            raise PngValidationError('Exif SensitivityType uses a reserved value')
        if 0xA460 in fields:
            composite = unpack_from(endian + 'H', profile, fields[0xA460][2])[0]
            if composite > 3 or (composite == 3 and not {0xA461, 0xA462}.issubset(fields)):
                raise PngValidationError('Exif composite capture requires source counts and exposure times')
        if 0xA461 in fields:
            total, used = unpack_from(endian + '2H', profile, fields[0xA461][2])
            if total < 2 or (used and not 2 <= used <= total):
                raise PngValidationError('Exif composite source image counts are inconsistent')
    if role == 'exif' and (len(version) != 4 or not version.isdigit()):
        raise PngValidationError('Exif IFD requires a four-digit ExifVersion')
    if role == 'gps' and any(tag in GPS_FIELDS and tag != 0 for tag in fields) and 0 not in fields:
        raise PngValidationError('Exif GPS fields require GPSVersionID')
    from png._exif_values import validate_values
    validate_values(profile, endian, role, fields)
