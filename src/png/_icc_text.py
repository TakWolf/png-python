"""ICC text validation and self-delimiting embedded description extents."""

from struct import unpack_from

from png.error import PngUnsupportedError, PngValidationError


def ascii_terminated(data: bytes | memoryview) -> None:
    if not data or data[-1] != 0 or any(value > 127 for value in data):
        raise PngValidationError('ICC text requires null-terminated 7-bit ASCII')


def _header(data: memoryview, start: int, minimum: int) -> None:
    if start + minimum > len(data) or any(data[start + 4:start + 8]):
        raise PngValidationError('ICC embedded text header is truncated or has nonzero reserved bytes')


def description_end(data: memoryview, start: int = 0) -> int:
    _header(data, start, 12)
    ascii_end = start + 12 + unpack_from('>I', data, start + 8)[0]
    if ascii_end + 8 > len(data):
        raise PngValidationError('ICC description ASCII data exceeds the tag')
    ascii_terminated(data[start + 12:ascii_end])
    unicode_count, = unpack_from('>I', data, ascii_end + 4)
    unicode_end = ascii_end + 8 + 2 * unicode_count
    end = unicode_end + 70
    if end > len(data):
        raise PngValidationError('ICC description Unicode or ScriptCode extent is invalid')
    if unicode_count and any(data[unicode_end - 2:unicode_end]):
        raise PngValidationError('ICC description Unicode string requires a terminator')
    script_count = data[unicode_end + 2]
    if script_count > 67 or (script_count and data[unicode_end + 2 + script_count] != 0):
        raise PngValidationError('ICC description ScriptCode string is invalid')
    return end


def multilingual_end(data: memoryview, start: int = 0) -> int:
    _header(data, start, 16)
    count, stride = unpack_from('>II', data, start + 8)
    table_size = 16 + count * stride
    end = start + table_size
    if stride < 12 or end > len(data):
        raise PngValidationError('ICC multilingual record table is invalid')
    checked = set()
    for index in range(count):
        length, offset = unpack_from('>II', data, start + 20 + index * stride)
        string_start = start + offset
        string_end = string_start + length
        if length % 2 or offset < table_size or string_end > len(data):
            raise PngValidationError('ICC multilingual string exceeds the tag or has an odd length')
        extent = (offset, length)
        if extent not in checked:
            try:
                data[string_start:string_end].tobytes().decode('utf-16-be')
            except UnicodeDecodeError as error:
                raise PngValidationError('ICC multilingual string is not UTF-16BE') from error
            checked.add(extent)
        end = max(end, string_end)
    return end


def embedded_text_end(data: memoryview, start: int) -> int:
    _header(data, start, 8)
    kind = bytes(data[start:start + 4])
    if kind == b'desc':
        return description_end(data, start)
    if kind == b'mluc':
        return multilingual_end(data, start)
    raise PngUnsupportedError(f'ICC embedded description type {kind!r} cannot be delimited')
