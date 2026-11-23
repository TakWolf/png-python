"""PNG Third Edition sections 7-10: samples, Adam7, filters and zlib."""

import sys
import zlib
from array import array
from collections import deque
from collections.abc import Iterable, Iterator
from struct import iter_unpack, pack

from png._scanlines import scan_passes
from png._validation import check_integer
from png.bitmap import PngBitmap, PngRow
from png.error import PngParseError
from png.format import PngColorType, PngCompressionStrategy, PngFilterType, PngInterlaceMethod
from png.header import PngHeader

_FILTER_COST = bytes(value if value < 128 else 256 - value for value in range(256))


def _passes(header: PngHeader) -> Iterator[tuple[int, int, int, int, int, int]]:
    return scan_passes(header.width, header.height, header.interlace_method)


def _inflate_parts(blocks: Iterable[bytes | memoryview], expected_size: int) -> Iterator[bytes]:
    inflater = zlib.decompressobj()
    total = 0
    try:
        for block in blocks:
            pending = block
            while pending and not inflater.eof:
                part = inflater.decompress(pending, min(65536, expected_size - total + 1))
                total += len(part)
                if total > expected_size:
                    raise PngParseError('image data contains more scanline bytes than expected')
                pending = inflater.unconsumed_tail
                if part:
                    yield part
            if inflater.eof:
                # PNG permits unused bytes after the final zlib stream. The
                # envelope parser has already checked the CRC of every IDAT.
                break
    except zlib.error as error:
        raise PngParseError(f'invalid zlib image data: {error}') from error
    if not inflater.eof:
        raise PngParseError('incomplete zlib image data')
    if total != expected_size:
        raise PngParseError(f'expected {expected_size} scanline bytes, got {total}')


class _ScanlineReader:
    def __init__(self, parts: Iterator[bytes]) -> None:
        self.parts = parts
        self.pending = memoryview(b'')

    def read(self, size: int) -> bytes:
        data = bytearray()
        while len(data) < size:
            if not self.pending:
                try:
                    self.pending = memoryview(next(self.parts))
                except StopIteration as error:
                    raise PngParseError('incomplete scanline data') from error
            count = min(size - len(data), len(self.pending))
            data.extend(self.pending[:count])
            self.pending = self.pending[count:]
        return bytes(data)

    def finish(self) -> None:
        for _part in self.parts:
            pass


# Keep Paeth prediction inline in the three byte loops below. The distances
# |p-left|, |p-above|, |p-upper_left| reduce to |above-upper_left|,
# |left-upper_left|, |above+left-2*upper_left|, with left-first tie breaking.
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
        # With no left/upper-left byte, Paeth is the Up predictor.
        for index in range(min(stride, len(row))):
            row[index] = (row[index] + previous[index]) & 255
        for index in range(stride, len(row)):
            left, above, upper_left = row[index - stride], previous[index], previous[index - stride]
            horizontal, vertical = above - upper_left, left - upper_left
            a, b, c = abs(horizontal), abs(vertical), abs(horizontal + vertical)
            predictor = left if a <= b and a <= c else above if b <= c else upper_left
            row[index] = (row[index] + predictor) & 255
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
        for index in range(min(stride, len(row))):
            filtered[index] = (row[index] - previous[index]) & 255
        for index in range(stride, len(row)):
            left, above, upper_left = row[index - stride], previous[index], previous[index - stride]
            horizontal, vertical = above - upper_left, left - upper_left
            a, b, c = abs(horizontal), abs(vertical), abs(horizontal + vertical)
            predictor = left if a <= b and a <= c else above if b <= c else upper_left
            filtered[index] = (row[index] - predictor) & 255
    return bytes(filtered)


def _filter_and_score(kind: int, row: bytes, previous: bytes, stride: int, trial: bytearray, minimum: int) -> int:
    # libpng's unweighted heuristic: generate and score together, abandoning
    # candidates that already exceed the best complete score. Partial trial
    # rows must never become the selected output.
    score = 0
    costs = _FILTER_COST
    if kind == 1:
        for index, sample in enumerate(row):
            value = trial[index] = (sample - (row[index - stride] if index >= stride else 0)) & 255
            score += costs[value]
            if score > minimum:
                return score
    elif kind == 2:
        for index, sample in enumerate(row):
            value = trial[index] = (sample - previous[index]) & 255
            score += costs[value]
            if score > minimum:
                return score
    elif kind == 3:
        for index, sample in enumerate(row):
            left = row[index - stride] if index >= stride else 0
            value = trial[index] = (sample - ((left + previous[index]) // 2)) & 255
            score += costs[value]
            if score > minimum:
                return score
    else:
        for index in range(min(stride, len(row))):
            value = trial[index] = (row[index] - previous[index]) & 255
            score += costs[value]
            if score > minimum:
                return score
        for index in range(stride, len(row)):
            left, above, upper_left = row[index - stride], previous[index], previous[index - stride]
            horizontal, vertical = above - upper_left, left - upper_left
            a, b, c = abs(horizontal), abs(vertical), abs(horizontal + vertical)
            predictor = left if a <= b and a <= c else above if b <= c else upper_left
            value = trial[index] = (row[index] - predictor) & 255
            score += costs[value]
            if score > minimum:
                return score
    return score


def _unpack_samples(row: bytes, depth: int, count: int, *, compact: bool = False) -> PngRow:
    if depth == 8:
        return bytearray(row) if compact else list(row)
    if depth == 16:
        if compact:
            samples = array('H')
            if samples.itemsize == 2:
                samples.frombytes(row)
                if sys.byteorder == 'little':
                    samples.byteswap()
            else:
                samples.extend(sample for (sample,) in iter_unpack('>H', row))
            return samples
        return [sample for (sample,) in iter_unpack('>H', row)]
    per_byte = 8 // depth
    mask = (1 << depth) - 1
    if compact:
        return bytearray(
            (row[index // per_byte] >> (8 - depth * (index % per_byte + 1))) & mask for index in range(count)
        )
    return [(row[index // per_byte] >> (8 - depth * (index % per_byte + 1))) & mask for index in range(count)]


def _pack_samples(samples: PngRow, depth: int) -> bytes:
    if depth == 8:
        return bytes(samples)
    if depth == 16:
        if isinstance(samples, array) and samples.typecode == 'H' and samples.itemsize == 2:
            if sys.byteorder == 'little':
                samples = array('H', samples)
                samples.byteswap()
            return samples.tobytes()
        return pack(f'>{len(samples)}H', *samples)
    data = bytearray((len(samples) * depth + 7) // 8)
    per_byte = 8 // depth
    for index, sample in enumerate(samples):
        data[index // per_byte] |= sample << (8 - depth * (index % per_byte + 1))
    return bytes(data)


def _empty_row(count: int, depth: int, compact: bool) -> PngRow:
    if not compact:
        return [0] * count
    if depth == 16:
        return array('H', [0]) * count
    return bytearray(count)


def decode_pixels(header: PngHeader, blocks: Iterable[bytes | memoryview], *, compact: bool = False) -> PngBitmap:
    passes = list(_passes(header))
    channels = header.channels
    expected_size = sum(((width * header.bits_per_pixel + 7) // 8 + 1) * height for _, _, _, _, width, height in passes)
    # Validate the decompressed extent before allocating the bitmap from IHDR.
    encoded = tuple(blocks)
    parts = _inflate_parts(encoded, expected_size)
    if expected_size <= 65536:
        parts = iter(tuple(parts))
    else:
        deque(parts, maxlen=0)
        parts = _inflate_parts(encoded, expected_size)
    reader = _ScanlineReader(parts)
    bitmap = (
        []
        if header.interlace_method == PngInterlaceMethod.NONE
        else [_empty_row(header.width * channels, header.bit_depth, compact) for _row in range(header.height)]
    )
    stride = max(1, (header.bits_per_pixel + 7) // 8)
    for x, y, dx, dy, width, height in passes:
        row_size = (width * header.bits_per_pixel + 7) // 8
        previous = bytes(row_size)
        for row_index in range(height):
            scanline = reader.read(row_size + 1)
            row = _unfilter(scanline[0], scanline[1:], previous, stride)
            previous = row
            samples = _unpack_samples(row, header.bit_depth, width * channels, compact=compact)
            if header.interlace_method == PngInterlaceMethod.NONE:
                bitmap.append(samples)
                continue
            target = bitmap[y + row_index * dy]
            for index in range(width):
                start = (x + index * dx) * channels
                target[start : start + channels] = samples[index * channels : (index + 1) * channels]
    reader.finish()
    return bitmap


def encode_pixels(
    header: PngHeader,
    bitmap: PngBitmap,
    filter_type: PngFilterType | None,
    compression_level: int,
    compression_strategy: PngCompressionStrategy = PngCompressionStrategy.DEFAULT,
) -> bytes:
    return b''.join(encode_pixel_blocks(header, bitmap, filter_type, compression_level, compression_strategy))


def encode_pixel_blocks(
    header: PngHeader,
    bitmap: PngBitmap,
    filter_type: PngFilterType | None,
    compression_level: int,
    compression_strategy: PngCompressionStrategy = PngCompressionStrategy.DEFAULT,
    *,
    block_size: int = 65536,
) -> Iterator[bytes]:
    check_integer('IDAT chunk size', block_size, 1, 0x7FFFFFFF)
    parts = _encode_parts(header, bitmap, filter_type, compression_level, compression_strategy)
    return _split_blocks(parts, block_size)


def _split_blocks(parts: Iterable[bytes], size: int) -> Iterator[bytes]:
    buffer = bytearray()
    for part in parts:
        offset = 0
        if buffer:
            count = min(size - len(buffer), len(part))
            buffer.extend(part[:count])
            offset = count
            if len(buffer) == size:
                yield bytes(buffer)
                buffer.clear()
        while len(part) - offset >= size:
            yield part[offset : offset + size]
            offset += size
        buffer.extend(part[offset:])
    if buffer:
        yield bytes(buffer)


def _encode_parts(
    header: PngHeader,
    bitmap: PngBitmap,
    filter_type: PngFilterType | None,
    compression_level: int,
    compression_strategy: PngCompressionStrategy,
) -> Iterator[bytes]:
    check_integer('compression level', compression_level, -1, 9)
    check_integer('compression strategy', compression_strategy, 0, 4)
    if filter_type is not None:
        check_integer('filter type', filter_type, 0, 4)
    adaptive = filter_type is None and header.bit_depth >= 8 and header.color_type != PngColorType.INDEXED_COLOR
    if filter_type is None and not adaptive:
        filter_type = PngFilterType.NONE
    compressor = zlib.compressobj(compression_level, strategy=compression_strategy)
    channels = header.channels
    stride = max(1, (header.bits_per_pixel + 7) // 8)
    for x, y, dx, dy, width, height in _passes(header):
        row_size = (width * header.bits_per_pixel + 7) // 8
        previous = bytes(row_size)
        if adaptive:
            # Keep the best candidate and a scratch row; swap rather than copy.
            best = bytearray(row_size)
            trial = bytearray(row_size)
            first_options = (3,) if width == 1 else (1, 3)
            later_options = (2, 3) if width == 1 else (1, 2, 3, 4)
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
            if adaptive:
                kind, filtered = 0, row
                minimum = sum(row.translate(_FILTER_COST))
                for option in first_options if row_index == 0 else later_options:
                    if minimum == 0:
                        break
                    score = _filter_and_score(option, row, previous, stride, trial, minimum - 1)
                    if score < minimum:
                        minimum = score
                        best, trial = trial, best
                        kind, filtered = option, best
            else:
                filtered = _filter(kind, row, previous, stride)
            part = compressor.compress(bytes([kind]) + filtered)
            if part:
                yield part
            previous = row
    yield compressor.flush()
