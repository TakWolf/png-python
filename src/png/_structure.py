"""PNG Third Edition section 5.6 ordering and basic payload constraints.

This module does not decompress image data or interpret all metadata payloads.
"""

from png._apng import scan_animation
from png._limits import ReadBudget
from png.chunk import PngChunk
from png.error import PngValidationError
from png.format import PngColorType
from png.header import PngHeader
from png.limits import PngReadLimits
from png.metadata import METADATA_TYPES, validate_metadata_chunks

CRITICAL_TYPES = frozenset((b'IHDR', b'PLTE', b'IDAT', b'IEND'))
# Only these chunks have semantic handling for critical edits at this stage.
UNDERSTOOD_TYPES = CRITICAL_TYPES | {b'tRNS', b'acTL', b'fcTL', b'fdAT'} | METADATA_TYPES

_BEFORE_PALETTE = frozenset((b'cHRM', b'cICP', b'gAMA', b'iCCP', b'mDCV', b'cLLI', b'sBIT', b'sRGB'))
_AFTER_PALETTE = frozenset((b'bKGD', b'hIST', b'tRNS'))
_BEFORE_DATA = (
    _BEFORE_PALETTE
    | _AFTER_PALETTE
    | {
        b'PLTE',
        b'acTL',
        b'eXIf',
        b'pHYs',
        b'sPLT',
        b'oFFs',
        b'pCAL',
        b'sCAL',
        b'sTER',
    }
)
_SINGLETONS = _BEFORE_DATA - {b'sPLT'} | {b'IHDR', b'IEND', b'tIME'}
_FIXED_LENGTHS = {
    b'IHDR': 13,
    b'IEND': 0,
    b'cHRM': 32,
    b'gAMA': 4,
    b'cICP': 4,
    b'mDCV': 24,
    b'cLLI': 8,
    b'sRGB': 1,
    b'pHYs': 9,
    b'tIME': 7,
    b'acTL': 8,
    b'fcTL': 26,
    b'oFFs': 9,
    b'sTER': 1,
}


class ChunkStructure:
    """Forward chunk-header checks shared by streaming and in-memory validation.

    This is operation-local parser state, never a cache attached to a document.
    The parser supplies header after validating the first IHDR payload and CRC.
    """

    def __init__(self, header: PngHeader | None = None) -> None:
        self.header = header
        self.seen: set[bytes] = set()
        self.palette_size = 0
        self.seen_data = False
        self.data_ended = False
        self.pre_data_frame = False

    def check(self, kind: bytes, length: int) -> None:
        if not self.seen and kind != b'IHDR':
            raise PngValidationError('IHDR must be the first chunk')
        if b'IEND' in self.seen:
            raise PngValidationError('IEND must be the last chunk')
        if not kind[0] & 0x20 and kind not in CRITICAL_TYPES:
            raise PngValidationError(f'unknown critical chunk: {kind!r}')
        if kind in _SINGLETONS and kind in self.seen:
            raise PngValidationError(f'duplicate {kind!r} chunk')
        if kind in _FIXED_LENGTHS and length != _FIXED_LENGTHS[kind]:
            raise PngValidationError(f'{kind!r} must contain {_FIXED_LENGTHS[kind]} data bytes')
        if kind == b'fdAT' and length < 4:
            raise PngValidationError('fdAT requires a four-byte sequence number')
        if kind in _BEFORE_DATA and self.seen_data:
            raise PngValidationError(f'{kind!r} must precede IDAT')
        if kind in _BEFORE_PALETTE and b'PLTE' in self.seen:
            raise PngValidationError(f'{kind!r} must precede PLTE and IDAT')
        if kind == b'PLTE':
            preceding = _AFTER_PALETTE & self.seen
            if preceding:
                previous = min(preceding)
                raise PngValidationError(f'{previous!r} must follow PLTE')
        if kind == b'IDAT' and self.data_ended:
            raise PngValidationError('IDAT chunks must be consecutive')
        if kind == b'fcTL' and not self.seen_data:
            if self.pre_data_frame:
                raise PngValidationError('at most one fcTL may precede IDAT')
            self.pre_data_frame = True
        if kind == b'fdAT' and not self.seen_data:
            raise PngValidationError('fdAT must follow IDAT')
        if kind == b'IEND' and not self.seen_data:
            raise PngValidationError('at least one IDAT chunk is required')
        if self.header is not None:
            self._check_color_payload_length(self.header, kind, length)
        self.seen.add(kind)
        if kind == b'IDAT':
            self.seen_data = True
        elif self.seen_data:
            self.data_ended = True

    def _check_color_payload_length(self, header: PngHeader, kind: bytes, length: int) -> None:
        indexed = header.color_type == PngColorType.INDEXED_COLOR
        gray = header.color_type in (PngColorType.GRAYSCALE, PngColorType.GRAYSCALE_ALPHA)
        if kind == b'PLTE':
            if not 3 <= length <= 768 or length % 3:
                raise PngValidationError('PLTE requires between 1 and 256 RGB entries')
            if gray:
                raise PngValidationError('PLTE is forbidden for grayscale images')
            self.palette_size = length // 3
            if indexed and self.palette_size > 1 << header.bit_depth:
                raise PngValidationError('indexed images require a PLTE fitting the bit depth')
        if indexed and kind in (b'IDAT', b'tRNS', b'bKGD') and not self.palette_size:
            raise PngValidationError('indexed images require a PLTE fitting the bit depth')
        if kind == b'tRNS':
            if indexed and length > self.palette_size:
                raise PngValidationError('tRNS has more entries than PLTE')
            if header.color_type in (PngColorType.GRAYSCALE, PngColorType.TRUECOLOR):
                if length != header.channels * 2:
                    raise PngValidationError('tRNS must contain two bytes per transparent color sample')
            elif not indexed:
                raise PngValidationError('tRNS is forbidden for images with an alpha channel')
        if kind == b'bKGD':
            expected = 1 if indexed else (2 if gray else 6)
            if length != expected:
                raise PngValidationError('bKGD has the wrong payload length for the color type')
        if kind == b'hIST' and (not self.palette_size or length != 2 * self.palette_size):
            raise PngValidationError('hIST requires one two-byte entry per PLTE entry')
        if kind == b'sBIT' and length != (3 if indexed else header.channels):
            raise PngValidationError('sBIT has the wrong sample count for the color type')


def validate_structure(
    chunks: list[PngChunk],
    *,
    limits: PngReadLimits | None = None,
    check_profile_structure: bool = False,
) -> None:
    budget = ReadBudget(limits)
    budget.signature()
    if not chunks or chunks[0].type != b'IHDR':
        raise PngValidationError('IHDR must be the first chunk')
    if chunks[-1].type != b'IEND':
        raise PngValidationError('IEND must be the last chunk')
    header = PngHeader.from_chunk(chunks[0])
    structure = ChunkStructure(header)
    for chunk in chunks:
        chunk.validate()
        structure.check(chunk.type, chunk.length)
        budget.chunk(chunk.length)
        budget.inspect(chunk.type, chunk.data)
    scan_animation(chunks, header)
    validate_metadata_chunks(
        chunks, header, structure.palette_size, budget=budget, check_profile_structure=check_profile_structure
    )
