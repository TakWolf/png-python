"""ICC named colors and profile-sequence record bounds; no color transforms."""

from struct import unpack_from

from png._icc_text import embedded_text_end, multilingual_end
from png.error import PngValidationError


def _header(data: bytes, minimum: int) -> None:
    if len(data) < minimum or any(data[4:8]):
        raise PngValidationError('ICC record tag header is truncated or has nonzero reserved bytes')


def validate_named_colors(data: bytes) -> None:
    _header(data, 84)
    count, coordinates = unpack_from('>II', data, 12)
    stride = 38 + 2 * coordinates
    if len(data) != 84 + count * stride:
        raise PngValidationError('ICC ncl2 record count or coordinate count disagrees with its size')
    _fixed_name(data, 20)
    _fixed_name(data, 52)
    for index in range(count):
        _fixed_name(data, 84 + index * stride)


def _fixed_name(data: bytes, start: int) -> None:
    field = data[start:start + 32]
    terminator = field.find(b'\0')
    if terminator < 0 or any(value > 127 for value in field[:terminator]):
        raise PngValidationError('ICC ncl2 names require null-terminated 7-bit ASCII within 32 bytes')
    # The specification does not require unused bytes following the terminator
    # to be zero. They are not part of the name and are preserved as stored.


def validate_profile_sequence(data: bytes) -> None:
    _header(data, 12)
    count, = unpack_from('>I', data, 8)
    # Every record has 20 fixed bytes and two descriptions. The shortest known
    # description is an empty 16-byte mluc placeholder.
    if count > (len(data) - 12) // 52:
        raise PngValidationError('ICC pseq record count exceeds the available data')
    cursor = 12
    view = memoryview(data)
    for _ in range(count):
        if cursor + 20 > len(data):
            raise PngValidationError('ICC pseq fixed record header is truncated')
        cursor = embedded_text_end(view, cursor + 20)
        cursor = embedded_text_end(view, cursor)
    if cursor != len(data):
        raise PngValidationError('ICC pseq descriptions do not consume its record data')


def validate_profile_identifiers(data: bytes) -> None:
    _header(data, 12)
    count, = unpack_from('>I', data, 8)
    table_end = 12 + 8 * count
    if table_end > len(data):
        raise PngValidationError('ICC psid position table exceeds the tag')
    view = memoryview(data)
    checked = set()
    for index in range(count):
        offset, size = unpack_from('>II', data, 12 + 8 * index)
        end = offset + size
        # A record contains a 16-byte profile ID and at least an empty mluc.
        if offset < table_end or offset % 4 or size < 32 or end > len(data):
            raise PngValidationError('ICC psid record offset or size is invalid')
        if any(view[end:min((end + 3) & ~3, len(data))]):
            raise PngValidationError('ICC psid record alignment padding must be zero')
        extent = (offset, size)
        if extent not in checked:
            record = view[offset:end]
            if record[16:20] != b'mluc':
                raise PngValidationError('ICC psid profile description requires mluc')
            # Limit every nested offset to this record, not the entire psid.
            multilingual_end(record, 16)
            checked.add(extent)
    # The ID identifies a component profile, not the containing profile. It may
    # be zero or any 16-byte ID; verifying it requires the original component.
    # Records may be shared and need not follow position-table order. Final
    # alignment padding may be stored outside the tag in the profile envelope.
