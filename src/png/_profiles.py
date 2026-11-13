"""Structural bounds for opaque ICC and Exif payloads, without color transforms."""

from struct import unpack_from

from png.error import PngUnsupportedError, PngValidationError


def validate_icc_structure(profile: bytes) -> None:
    if not isinstance(profile, bytes) or len(profile) < 132:
        raise PngValidationError('ICC profile requires a header and tag count')
    if profile[36:40] != b'acsp':
        raise PngValidationError('ICC profile requires the acsp header signature')
    declared, = unpack_from('>I', profile)
    if declared != len(profile):
        raise PngValidationError(f'ICC declared size {declared} does not match {len(profile)} payload bytes')
    count, = unpack_from('>I', profile, 128)
    table_end = 132 + count * 12
    if table_end > len(profile):
        raise PngValidationError('ICC tag table exceeds the profile')
    signatures = set()
    ranges = set()
    for index in range(count):
        signature, offset, size = unpack_from('>4sII', profile, 132 + index * 12)
        if signature in signatures:
            raise PngValidationError('duplicate ICC tag signature')
        signatures.add(signature)
        if offset % 4 or offset < table_end:
            raise PngValidationError('ICC tag offset must be aligned and follow the tag table')
        if size < 8 or offset + size > len(profile):
            raise PngValidationError('ICC tag data exceeds the profile or lacks its type header')
        if profile[offset + 4:offset + 8] != bytes(4):
            raise PngValidationError('ICC tag type reserved bytes must be zero')
        ranges.add((offset, offset + size))
    previous_end = table_end
    for start, end in sorted(ranges):
        if start < previous_end:
            raise PngValidationError('ICC tag data must not partially overlap')
        if profile[8] == 4:
            # ICC v4 requires contiguous elements with up to three zero pad bytes.
            if start != ((previous_end + 3) & ~3) or any(profile[previous_end:start]):
                raise PngValidationError('ICC v4 tag data has gaps or nonzero padding')
        previous_end = end
    if profile[8] == 4:
        if len(profile) != ((previous_end + 3) & ~3) or any(profile[previous_end:]):
            raise PngValidationError('ICC v4 final padding or profile extent is invalid')


_TIFF_TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8}
_EXIF_IFD_POINTERS = frozenset((0x8769, 0x8825, 0xA005))


def validate_exif_structure(profile: bytes) -> None:
    if not isinstance(profile, bytes) or len(profile) < 8 or profile[:4] not in (b'II*\0', b'MM\0*'):
        raise PngValidationError('Exif requires a complete eight-byte TIFF header')
    endian = '<' if profile[:2] == b'II' else '>'

    def uint32(offset: int) -> int:
        return unpack_from(endian + 'I', profile, offset)[0]

    def extent(offset: int, size: int, name: str) -> None:
        if offset < 8 or offset % 2 or offset + size > len(profile):
            raise PngValidationError(f'Exif {name} has an invalid offset or exceeds the profile')

    first = uint32(4)
    if not first:
        raise PngValidationError('Exif requires a nonzero first IFD offset')
    states: dict[int, int] = {}
    pending = [(first, False)]
    while pending:
        offset, leaving = pending.pop()
        if leaving:
            states[offset] = 2
            continue
        if states.get(offset) == 1:
            raise PngValidationError('Exif IFD pointers contain a cycle')
        if states.get(offset) == 2:
            continue  # Sharing an entire already-checked directory is harmless.
        extent(offset, 2, 'IFD')
        count, = unpack_from(endian + 'H', profile, offset)
        if not count:
            raise PngValidationError('Exif IFD must contain at least one entry')
        size = 2 + count * 12 + 4
        extent(offset, size, 'IFD table')
        states[offset] = 1
        pending.append((offset, True))
        children = []
        previous_tag = -1
        thumbnail = {}
        for index in range(count):
            entry = offset + 2 + index * 12
            tag, kind, number = unpack_from(endian + 'HHI', profile, entry)
            if tag <= previous_tag:
                raise PngValidationError('Exif IFD tags must be unique and sorted')
            previous_tag = tag
            if kind not in _TIFF_TYPE_SIZES:
                raise PngUnsupportedError(f'Exif TIFF field type {kind} cannot be structurally checked')
            value_size = number * _TIFF_TYPE_SIZES[kind]
            if value_size > 4:
                extent(uint32(entry + 8), value_size, 'field data')
            if tag in _EXIF_IFD_POINTERS or tag in (0x0201, 0x0202):
                if kind != 4 or number != 1:
                    raise PngValidationError('Exif directory/thumbnail pointers require one LONG value')
                value = uint32(entry + 8)
                if tag in _EXIF_IFD_POINTERS:
                    if value:
                        children.append(value)
                else:
                    thumbnail[tag] = value
        if thumbnail:
            if set(thumbnail) != {0x0201, 0x0202} or not thumbnail[0x0202]:
                raise PngValidationError('Exif JPEG thumbnail requires an offset and nonzero length')
            extent(thumbnail[0x0201], thumbnail[0x0202], 'JPEG thumbnail')
        following = uint32(offset + 2 + count * 12)
        if following:
            children.append(following)
        pending.extend((child, False) for child in reversed(children))
