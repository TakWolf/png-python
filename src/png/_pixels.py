"""PNG Third Edition sections 7-10: samples, Adam7, filters and zlib."""

import zlib
from collections.abc import Iterable, Iterator
from struct import iter_unpack, pack

from png._validation import check_integer
from png.error import PngParseError
from png.format import PngColorType, PngFilterType, PngInterlaceMethod
from png.header import PngHeader

_ADAM7 = ((0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2))


def _passes(header: PngHeader) -> Iterator[tuple[int, int, int, int, int, int]]:
    passes = _ADAM7 if header.interlace_method == PngInterlaceMethod.ADAM7 else ((0, 0, 1, 1),)
    for x, y, dx, dy in passes:
        width = max(0, (header.width - x + dx - 1) // dx)
        height = max(0, (header.height - y + dy - 1) // dy)
        if width and height:
            yield x, y, dx, dy, width, height


def _inflate(blocks: Iterable[bytes], expected_size: int) -> bytes:
    inflater = zlib.decompressobj()
    data = bytearray()
    try:
        for block in blocks:
            pending = block
            while pending and not inflater.eof:
                data.extend(inflater.decompress(pending, min(65536, expected_size - len(data) + 1)))
                if len(data) > expected_size:
                    raise PngParseError('image data contains more scanline bytes than expected')
                pending = inflater.unconsumed_tail
            if inflater.eof:
                # PNG permits unused bytes after the final zlib stream. The
                # envelope parser has already checked the CRC of every IDAT.
                break
    except zlib.error as error:
        raise PngParseError(f'invalid zlib image data: {error}') from error
    if not inflater.eof:
        raise PngParseError('incomplete zlib image data')
    if len(data) != expected_size:
        raise PngParseError(f'expected {expected_size} scanline bytes, got {len(data)}')
    return bytes(data)


def _paeth(left: int, above: int, upper_left: int) -> int:
    prediction = left + above - upper_left
    a, b, c = abs(prediction - left), abs(prediction - above), abs(prediction - upper_left)
    if a <= b and a <= c:
        return left
    if b <= c:
        return above
    return upper_left


def _unfilter(kind: int, data: bytes, previous: bytes, stride: int) -> bytes:
    if kind == 0:
        return data
    row = bytearray(data)
    if kind == 1:
        for index in range(stride, len(row)):
            row[index] = (row[index] + row[index - stride]) & 255
    elif kind == 2:
        row = bytearray((value + above) & 255 for value, above in zip(row, previous, strict=True))
    elif kind == 3:
        for index, value in enumerate(row):
            left = row[index - stride] if index >= stride else 0
            row[index] = (value + ((left + previous[index]) // 2)) & 255
    elif kind == 4:
        for index, value in enumerate(row):
            left = row[index - stride] if index >= stride else 0
            upper_left = previous[index - stride] if index >= stride else 0
            row[index] = (value + _paeth(left, previous[index], upper_left)) & 255
    else:
        raise PngParseError(f'unsupported scanline filter type: {kind}')
    return bytes(row)


def _filter(kind: int, row: bytes, previous: bytes, stride: int) -> bytes:
    if kind == 0:
        return row
    if kind == 1:
        return row[:stride] + bytes((row[index] - row[index - stride]) & 255 for index in range(stride, len(row)))
    if kind == 2:
        return bytes((value - above) & 255 for value, above in zip(row, previous, strict=True))
    filtered = bytearray(len(row))
    if kind == 3:
        for index, value in enumerate(row):
            left = row[index - stride] if index >= stride else 0
            filtered[index] = (value - ((left + previous[index]) // 2)) & 255
    else:
        for index, value in enumerate(row):
            left = row[index - stride] if index >= stride else 0
            upper_left = previous[index - stride] if index >= stride else 0
            filtered[index] = (value - _paeth(left, previous[index], upper_left)) & 255
    return bytes(filtered)


def _unpack_samples(row: bytes, depth: int, count: int) -> list[int]:
    if depth == 8:
        return list(row)
    if depth == 16:
        return [sample for (sample,) in iter_unpack('>H', row)]
    per_byte = 8 // depth
    mask = (1 << depth) - 1
    return [(row[index // per_byte] >> (8 - depth * (index % per_byte + 1))) & mask for index in range(count)]


def _pack_samples(samples: list[int], depth: int) -> bytes:
    if depth == 8:
        return bytes(samples)
    if depth == 16:
        return pack(f'>{len(samples)}H', *samples)
    data = bytearray((len(samples) * depth + 7) // 8)
    per_byte = 8 // depth
    for index, sample in enumerate(samples):
        data[index // per_byte] |= sample << (8 - depth * (index % per_byte + 1))
    return bytes(data)


def decode_pixels(header: PngHeader, blocks: Iterable[bytes]) -> list[list[int]]:
    passes = list(_passes(header))
    channels = header.channels
    expected_size = sum(((width * header.bits_per_pixel + 7) // 8 + 1) * height for _, _, _, _, width, height in passes)
    # Validate the decompressed extent before allocating the bitmap from IHDR.
    data = _inflate(blocks, expected_size)
    bitmap = (
        []
        if header.interlace_method == PngInterlaceMethod.NONE
        else [[0] * (header.width * channels) for _ in range(header.height)]
    )
    stride = max(1, (header.bits_per_pixel + 7) // 8)
    offset = 0
    for x, y, dx, dy, width, height in passes:
        row_size = (width * header.bits_per_pixel + 7) // 8
        previous = bytes(row_size)
        for row_index in range(height):
            row = _unfilter(data[offset], data[offset + 1 : offset + row_size + 1], previous, stride)
            offset += row_size + 1
            previous = row
            samples = _unpack_samples(row, header.bit_depth, width * channels)
            if header.interlace_method == PngInterlaceMethod.NONE:
                bitmap.append(samples)
                continue
            target = bitmap[y + row_index * dy]
            for index in range(width):
                start = (x + index * dx) * channels
                target[start : start + channels] = samples[index * channels : (index + 1) * channels]
    return bitmap


def encode_pixels(
    header: PngHeader,
    bitmap: list[list[int]],
    filter_type: PngFilterType | None,
    compression_level: int,
) -> bytes:
    check_integer('compression level', compression_level, -1, 9)
    if filter_type is not None:
        check_integer('filter type', filter_type, 0, 4)
    compressor = zlib.compressobj(compression_level)
    data = bytearray()
    channels = header.channels
    stride = max(1, (header.bits_per_pixel + 7) // 8)
    for x, y, dx, dy, width, height in _passes(header):
        previous = bytes((width * header.bits_per_pixel + 7) // 8)
        for row_index in range(height):
            source = bitmap[y + row_index * dy]
            samples = (
                source
                if x == 0 and dx == 1
                else [
                    sample
                    for index in range(width)
                    for sample in source[(x + index * dx) * channels : (x + index * dx + 1) * channels]
                ]
            )
            row = _pack_samples(samples, header.bit_depth)
            kind = filter_type
            if kind is None and (header.bit_depth < 8 or header.color_type == PngColorType.INDEXED_COLOR):
                kind = PngFilterType.NONE
            if kind is None:
                candidates = [(option, _filter(option, row, previous, stride)) for option in PngFilterType]
                kind, filtered = min(
                    candidates,
                    key=lambda candidate: sum(value if value < 128 else 256 - value for value in candidate[1]),
                )
            else:
                filtered = _filter(kind, row, previous, stride)
            data.extend(compressor.compress(bytes([kind]) + filtered))
            previous = row
    data.extend(compressor.flush())
    return bytes(data)
