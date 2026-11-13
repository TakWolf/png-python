"""PNG Third Edition section 5.6 ordering and basic payload constraints.

This module does not decompress image data or interpret all metadata payloads.
"""

from png.chunk import PngChunk
from png._apng import scan_animation
from png.error import PngValidationError
from png.format import PngColorType
from png.header import PngHeader
from png.metadata import METADATA_TYPES, validate_metadata_chunks

CRITICAL_TYPES = frozenset((b'IHDR', b'PLTE', b'IDAT', b'IEND'))
# Only these chunks have semantic handling for critical edits at this stage.
UNDERSTOOD_TYPES = CRITICAL_TYPES | {b'tRNS', b'acTL', b'fcTL', b'fdAT'} | METADATA_TYPES

_BEFORE_PALETTE = frozenset((b'cHRM', b'cICP', b'gAMA', b'iCCP', b'mDCV', b'cLLI', b'sBIT', b'sRGB'))
_AFTER_PALETTE = frozenset((b'bKGD', b'hIST', b'tRNS'))
_BEFORE_DATA = _BEFORE_PALETTE | _AFTER_PALETTE | {b'PLTE', b'acTL', b'eXIf', b'pHYs', b'sPLT'}
_SINGLETONS = _BEFORE_DATA - {b'sPLT'} | {b'IHDR', b'IEND', b'tIME'}
_FIXED_LENGTHS = {
    b'IEND': 0, b'cHRM': 32, b'gAMA': 4, b'cICP': 4, b'mDCV': 24,
    b'cLLI': 8, b'sRGB': 1, b'pHYs': 9, b'tIME': 7, b'acTL': 8, b'fcTL': 26,
}


def validate_structure(chunks: list[PngChunk]) -> None:
    if not chunks or chunks[0].type != b'IHDR':
        raise PngValidationError('IHDR must be the first chunk')
    if chunks[-1].type != b'IEND':
        raise PngValidationError('IEND must be the last chunk')
    header = PngHeader.from_chunk(chunks[0])
    positions: dict[bytes, list[int]] = {}
    for index, chunk in enumerate(chunks):
        chunk.validate()
        kind = chunk.type
        if chunk.is_critical and kind not in CRITICAL_TYPES:
            raise PngValidationError(f'unknown critical chunk: {kind!r}')
        positions.setdefault(kind, []).append(index)
        if kind in _SINGLETONS and len(positions[kind]) > 1:
            raise PngValidationError(f'duplicate {kind!r} chunk')
        if kind in _FIXED_LENGTHS and chunk.length != _FIXED_LENGTHS[kind]:
            raise PngValidationError(f'{kind!r} must contain {_FIXED_LENGTHS[kind]} data bytes')
        if kind == b'fdAT' and chunk.length < 4:
            raise PngValidationError('fdAT requires a four-byte sequence number')
    if b'IDAT' not in positions:
        raise PngValidationError('at least one IDAT chunk is required')
    data_positions = positions[b'IDAT']
    first_data = data_positions[0]
    if data_positions[-1] - first_data + 1 != len(data_positions):
        raise PngValidationError('IDAT chunks must be consecutive')
    palette_position = positions.get(b'PLTE', [first_data])[0]
    for kind, indexes in positions.items():
        if kind in _BEFORE_DATA and indexes[-1] >= first_data:
            raise PngValidationError(f'{kind!r} must precede IDAT')
        if kind in _BEFORE_PALETTE and indexes[-1] >= palette_position:
            raise PngValidationError(f'{kind!r} must precede PLTE and IDAT')
        if kind in _AFTER_PALETTE and b'PLTE' in positions and indexes[0] <= palette_position:
            raise PngValidationError(f'{kind!r} must follow PLTE')
    if len([index for index in positions.get(b'fcTL', []) if index < first_data]) > 1:
        raise PngValidationError('at most one fcTL may precede IDAT')
    if any(index < first_data for index in positions.get(b'fdAT', [])):
        raise PngValidationError('fdAT must follow IDAT')

    palette_size = 0
    if b'PLTE' in positions:
        palette = chunks[palette_position]
        if not 3 <= palette.length <= 768 or palette.length % 3:
            raise PngValidationError('PLTE requires between 1 and 256 RGB entries')
        if header.color_type in (PngColorType.GRAYSCALE, PngColorType.GRAYSCALE_ALPHA):
            raise PngValidationError('PLTE is forbidden for grayscale images')
        palette_size = palette.length // 3
    if header.color_type == PngColorType.INDEXED_COLOR:
        if not 1 <= palette_size <= 1 << header.bit_depth:
            raise PngValidationError('indexed images require a PLTE fitting the bit depth')
    if b'tRNS' in positions:
        transparency = chunks[positions[b'tRNS'][0]]
        if header.color_type == PngColorType.INDEXED_COLOR:
            if transparency.length > palette_size:
                raise PngValidationError('tRNS has more entries than PLTE')
        elif header.color_type in (PngColorType.GRAYSCALE, PngColorType.TRUECOLOR):
            if transparency.length != header.channels * 2:
                raise PngValidationError('tRNS must contain two bytes per transparent color sample')
        else:
            raise PngValidationError('tRNS is forbidden for images with an alpha channel')
    if b'hIST' in positions:
        if not palette_size or chunks[positions[b'hIST'][0]].length != palette_size * 2:
            raise PngValidationError('hIST requires one two-byte entry per PLTE entry')
    if b'bKGD' in positions:
        background = chunks[positions[b'bKGD'][0]]
        size = {0: 2, 2: 6, 3: 1, 4: 2, 6: 6}[header.color_type]
        if background.length != size:
            raise PngValidationError('bKGD has the wrong size for the color type')
        if header.color_type == PngColorType.INDEXED_COLOR and background.data[0] >= palette_size:
            raise PngValidationError('bKGD index is outside PLTE')
    if b'sBIT' in positions:
        significant = chunks[positions[b'sBIT'][0]]
        channels = 3 if header.color_type == PngColorType.INDEXED_COLOR else header.channels
        maximum = 8 if header.color_type == PngColorType.INDEXED_COLOR else header.bit_depth
        if significant.length != channels or any(not 1 <= value <= maximum for value in significant.data):
            raise PngValidationError('sBIT sample depths must fit the color type and bit depth')
    scan_animation(chunks, header)
    validate_metadata_chunks(chunks)
