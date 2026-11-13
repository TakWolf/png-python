"""Checks for opaque ICC and Exif payloads, without color transforms."""

from struct import unpack_from

from png._icc_header import validate_header_fields
from png._icc_lut import LUT_TYPES, curve_end, validate_lut, validate_lut_context
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


_ICC_MATRIX_TAGS = frozenset((b'rXYZ', b'gXYZ', b'bXYZ', b'rTRC', b'gTRC', b'bTRC'))
_ICC_SINGLE_XYZ_TAGS = frozenset((b'wtpt', b'bkpt', b'lumi', b'rXYZ', b'gXYZ', b'bXYZ'))
_ICC_TRC_TAGS = frozenset((b'kTRC', b'rTRC', b'gTRC', b'bTRC'))


def validate_icc_tags(profile: bytes) -> None:
    """Check common required tags and selected tag encodings, not all ICC semantics."""
    validate_icc_structure(profile)
    version = profile[8]
    if version not in (2, 4):
        raise PngUnsupportedError(f'ICC version {version} tag requirements are not supported')
    profile_class = profile[12:16]
    if profile_class not in (b'scnr', b'mntr', b'prtr', b'link', b'spac', b'abst', b'nmcl'):
        raise PngValidationError('ICC profile class is not recognized')
    validate_header_fields(profile)
    count, = unpack_from('>I', profile, 128)
    tags = {}
    checked = set()
    for index in range(count):
        signature, offset, size = unpack_from('>4sII', profile, 132 + index * 12)
        kind = profile[offset:offset + 4]
        tags[signature] = kind
        allowed = None
        if signature == b'desc':
            allowed = (b'mluc',) if version == 4 else (b'desc',)
        elif signature == b'cprt':
            allowed = (b'mluc',) if version == 4 else (b'text',)
        elif signature in _ICC_SINGLE_XYZ_TAGS:
            allowed = (b'XYZ ',)
            if size != 20:
                raise PngValidationError(f'ICC {signature!r} requires one XYZ value')
        elif signature in _ICC_TRC_TAGS:
            allowed = (b'curv', b'para') if version == 4 else (b'curv',)
        elif signature == b'chad':
            allowed = (b'sf32',)
            if size != 44:
                raise PngValidationError('ICC chad requires a nine-element matrix')
            if version == 4:
                a, b, c, d, e, f, g, h, i = unpack_from('>9i', profile, offset + 8)
                if a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g) == 0:
                    raise PngValidationError('ICC chad matrix must be invertible')
        elif signature in (b'A2B0', b'A2B1', b'A2B2'):
            allowed = (b'mft1', b'mft2', b'mAB ') if version == 4 else (b'mft1', b'mft2')
        elif signature in (b'B2A0', b'B2A1', b'B2A2', b'gamt'):
            allowed = (b'mft1', b'mft2', b'mBA ') if version == 4 else (b'mft1', b'mft2')
        elif signature in (b'pseq', b'ncl2'):
            allowed = (signature,)
        if allowed is not None and kind not in allowed:
            raise PngValidationError(f'ICC {signature!r} has an invalid tag type {kind!r}')
        extent = (offset, size)
        if extent not in checked:
            _validate_icc_tag_data(profile[offset:offset + size])
            checked.add(extent)
        if kind in LUT_TYPES:
            validate_lut_context(profile, signature, memoryview(profile)[offset:offset + size])

    required = {b'desc', b'cprt'}
    if profile_class != b'link':
        required.add(b'wtpt')
    # ICC v2's common tags are checked above. Its class-specific rules differ
    # between historical revisions; do not impose v4-only requirements on v2.
    if version == 4:
        if profile_class in (b'scnr', b'mntr', b'prtr'):
            if profile[16:20] == b'GRAY':
                required.add(b'kTRC')
            elif profile_class == b'prtr':
                required.update((b'A2B0', b'A2B1', b'A2B2', b'B2A0', b'B2A1', b'B2A2', b'gamt'))
            elif _ICC_MATRIX_TAGS.issubset(tags) and profile[20:24] == b'XYZ ':
                pass  # The matrix/TRC model is a complete alternative to a LUT.
            else:
                required.add(b'A2B0')
                if profile_class == b'mntr':
                    required.add(b'B2A0')
        elif profile_class == b'spac':
            required.update((b'A2B0', b'B2A0'))
        elif profile_class == b'link':
            required.update((b'A2B0', b'pseq'))
        elif profile_class == b'abst':
            required.add(b'A2B0')
        elif profile_class == b'nmcl':
            required.add(b'ncl2')
    missing = required.difference(tags)
    if missing:
        raise PngValidationError(f'ICC required tags are missing: {sorted(missing)!r}')


def _validate_icc_tag_data(data: bytes) -> None:
    kind = data[:4]
    size = len(data)
    if kind in (b'curv', b'para'):
        if curve_end(data) != size:
            raise PngValidationError('ICC curve count does not match tag size')
    elif kind in LUT_TYPES:
        validate_lut(data)
    elif kind == b'XYZ ':
        if size < 20 or (size - 8) % 12:
            raise PngValidationError('ICC XYZ array has an invalid size')
    elif kind == b'sf32':
        if (size - 8) % 4:
            raise PngValidationError('ICC fixed-point array has an invalid size')
    elif kind == b'text':
        _validate_icc_ascii(data[8:])
    elif kind == b'desc':
        if size < 12:
            raise PngValidationError('ICC description lacks its ASCII count')
        ascii_end = 12 + unpack_from('>I', data, 8)[0]
        if ascii_end + 8 > size:
            raise PngValidationError('ICC description ASCII data exceeds the tag')
        _validate_icc_ascii(data[12:ascii_end])
        unicode_count, = unpack_from('>I', data, ascii_end + 4)
        unicode_end = ascii_end + 8 + 2 * unicode_count
        if unicode_end + 70 != size:
            raise PngValidationError('ICC description Unicode or ScriptCode extent is invalid')
        if unicode_count and data[unicode_end - 2:unicode_end] != bytes(2):
            raise PngValidationError('ICC description Unicode string requires a terminator')
        script_count = data[unicode_end + 2]
        if script_count > 67 or (script_count and data[unicode_end + 2 + script_count] != 0):
            raise PngValidationError('ICC description ScriptCode string is invalid')
    elif kind == b'mluc':
        if size < 16:
            raise PngValidationError('ICC multilingual tag lacks its record header')
        count, stride = unpack_from('>II', data, 8)
        table_end = 16 + count * stride
        if stride < 12 or table_end > size:
            raise PngValidationError('ICC multilingual record table is invalid')
        checked = set()
        for index in range(count):
            length, offset = unpack_from('>II', data, 20 + index * stride)
            if length % 2 or offset < table_end or offset + length > size:
                raise PngValidationError('ICC multilingual string exceeds the tag or has an odd length')
            extent = (offset, length)
            if extent not in checked:
                try:
                    data[offset:offset + length].decode('utf-16-be')
                except UnicodeDecodeError as error:
                    raise PngValidationError('ICC multilingual string is not UTF-16BE') from error
                checked.add(extent)


def _validate_icc_ascii(data: bytes) -> None:
    if not data or data[-1] != 0 or any(value > 127 for value in data):
        raise PngValidationError('ICC text requires null-terminated 7-bit ASCII')


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
