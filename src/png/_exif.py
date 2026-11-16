"""TIFF/Exif field and image-payload bounds, without rendering thumbnails."""

from struct import unpack_from

from png._exif_fields import validate_fields
from png.error import PngUnsupportedError, PngValidationError

_TIFF_TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 129: 1}
_EXIF_IFD_POINTERS = frozenset((0x8769, 0x8825, 0xA005))


def validate_exif_structure(profile: bytes, *, check_fields: bool = False) -> None:
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
    if check_fields:
        following = first
        for _ in range(2):
            if not following:
                break
            extent(following, 2, 'primary IFD')
            (count,) = unpack_from(endian + 'H', profile, following)
            extent(following, 2 + 12 * count + 4, 'primary IFD table')
            following = uint32(following + 2 + 12 * count)
        if following:
            raise PngValidationError('Exif APP1 permits only the primary and thumbnail image IFDs')
    directories = {}
    states: dict[tuple[int, str], int] = {}
    pending = [(first, False, 'image')]
    while pending:
        offset, leaving, role = pending.pop()
        key = (offset, role)
        if leaving:
            states[key] = 2
            continue
        if states.get(key) == 1:
            raise PngValidationError('Exif IFD pointers contain a cycle')
        if states.get(key) == 2:
            continue  # Sharing an entire already-checked directory is harmless.
        extent(offset, 2, 'IFD')
        (count,) = unpack_from(endian + 'H', profile, offset)
        if not count:
            raise PngValidationError('Exif IFD must contain at least one entry')
        size = 2 + count * 12 + 4
        extent(offset, size, 'IFD table')
        states[key] = 1
        pending.append((offset, True, role))
        children = []
        previous_tag = -1
        fields = {}
        thumbnail = {}
        image_data = {}
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
            value_start = uint32(entry + 8) if value_size > 4 else entry + 8
            fields[tag] = (kind, number, value_start)
            if kind in (2, 129):
                value = profile[value_start : value_start + value_size]
                if not value or value[-1] != 0:
                    raise PngValidationError('Exif ASCII/UTF-8 fields require a null terminator')
                try:
                    if kind == 129 and value.startswith(b'\xef\xbb\xbf'):
                        raise PngValidationError('Exif UTF-8 must not contain a BOM')
                    value.decode('ascii' if kind == 2 else 'utf-8')
                except UnicodeDecodeError as error:
                    raise PngValidationError('Exif text field has invalid character encoding') from error
            if tag in (0x0111, 0x0117, 0x0144, 0x0145):
                if kind not in (3, 4) or (tag == 0x0144 and kind != 4) or not number:
                    raise PngValidationError('Exif strip/tile arrays require SHORT or LONG entries')
                image_data[tag] = (kind, number, value_start)
            if tag in _EXIF_IFD_POINTERS or tag in (0x0201, 0x0202):
                if kind != 4 or number != 1:
                    raise PngValidationError('Exif directory/thumbnail pointers require one LONG value')
                value = uint32(entry + 8)
                if tag in _EXIF_IFD_POINTERS:
                    if value:
                        children.append((value, {0x8769: 'exif', 0x8825: 'gps', 0xA005: 'interop'}[tag]))
                else:
                    thumbnail[tag] = value
        if check_fields:
            validate_fields(profile, endian, role, fields)
            directories[key] = fields
        if thumbnail:
            if set(thumbnail) != {0x0201, 0x0202} or not thumbnail[0x0202]:
                raise PngValidationError('Exif JPEG thumbnail requires an offset and nonzero length')
            extent(thumbnail[0x0201], thumbnail[0x0202], 'JPEG thumbnail')
        for offsets_tag, lengths_tag in ((0x0111, 0x0117), (0x0144, 0x0145)):
            if offsets_tag not in image_data and lengths_tag not in image_data:
                continue
            if offsets_tag not in image_data or lengths_tag not in image_data:
                raise PngValidationError('Exif strip/tile offsets and byte counts must be paired')
            offsets_kind, number, offsets_start = image_data[offsets_tag]
            lengths_kind, lengths_number, lengths_start = image_data[lengths_tag]
            if lengths_number != number:
                raise PngValidationError('Exif strip/tile offset and byte count arrays must have equal counts')
            for index in range(number):
                (location,) = unpack_from(
                    endian + ('H' if offsets_kind == 3 else 'I'),
                    profile,
                    offsets_start + index * _TIFF_TYPE_SIZES[offsets_kind],
                )
                (length,) = unpack_from(
                    endian + ('H' if lengths_kind == 3 else 'I'),
                    profile,
                    lengths_start + index * _TIFF_TYPE_SIZES[lengths_kind],
                )
                # Compressed strips need not start at a word boundary. A zero
                # byte count does not imply data to decode; retain empty entries.
                if location > len(profile) or (length and (location < 8 or location + length > len(profile))):
                    raise PngValidationError('Exif strip/tile image data exceeds the profile')
        following = uint32(offset + 2 + count * 12)
        if following:
            children.append((following, role))
        pending.extend((child, False, child_role) for child, child_role in reversed(children))
    if check_fields:
        for (_offset, role), fields in directories.items():
            if role != 'image' or 0x8769 not in fields:
                continue
            child = uint32(fields[0x8769][2])
            exif = directories.get((child, 'exif'), {})
            if any(tag in exif for tag in (0xA430, 0xA437, 0xA438)) and 0x013B not in fields:
                raise PngValidationError('Exif owner/photographer/editor fields require Artist')
            if any(tag in exif for tag in (0xA439, 0xA43A, 0xA43B, 0xA43C)) and 0x0131 not in fields:
                raise PngValidationError('Exif firmware/developing/editing fields require Software')
        from png._exif_binary import validate_binary

        root = directories.get((first, 'image'), {})
        source = directories.get((uint32(root[0x8769][2]), 'exif'), {}) if 0x8769 in root else {}
        version = profile[source[0x9000][2] : source[0x9000][2] + 4] if 0x9000 in source else b''
        for (_offset, role), fields in directories.items():
            if role == 'gps':
                for tag in (0x001B, 0x001C):
                    if tag in fields:
                        _, size, start = fields[tag]
                        validate_binary(tag, profile[start : start + size], endian, version)
