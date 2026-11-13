from __future__ import annotations

from io import BytesIO
from os import PathLike
from typing import BinaryIO

from png._stream import read_exact, write_all
from png._limits import ReadBudget
from png._structure import ChunkStructure, UNDERSTOOD_TYPES, validate_structure
from png.chunk import PngChunk
from png.error import PngParseError, PngValidationError
from png.header import PngHeader
from png.limits import PngReadLimits

_SIGNATURE = b'\x89PNG\r\n\x1a\n'


class PngDocument:
    """The ordered, encoded chunk representation of a PNG datastream.

    Repeated chunks and their positions are retained. Decoded pixels belong to
    PngImage instead; no automatic synchronization between the two is performed.
    """

    chunks: list[PngChunk]
    _original_chunks: tuple[tuple[PngChunk, bytes, bytes], ...] | None

    def __init__(self, chunks: list[PngChunk] | None = None) -> None:
        self.chunks = chunks if chunks is not None else []
        self._original_chunks = None

    @staticmethod
    def parse(stream: bytes | BinaryIO, *, limits: PngReadLimits | None = None) -> PngDocument:
        """Read one PNG datastream, stopping immediately after IEND.

        Checks the envelope and implemented structure rules, not compressed
        pixels or the complete semantics of metadata and animation chunks.
        A supplied stream is neither closed nor rewound.
        """
        budget = ReadBudget(limits)
        budget.signature()
        if isinstance(stream, bytes):
            stream = BytesIO(stream)
        if read_exact(stream, 8) != _SIGNATURE:
            raise PngParseError('not a valid PNG signature')
        document = PngDocument()
        structure = ChunkStructure()
        while True:
            try:
                chunk = PngChunk._parse(stream, budget, check_header=structure.check)
                if not document.chunks:
                    structure.header = PngHeader.from_chunk(chunk)
            except PngValidationError as error:
                raise PngParseError(str(error)) from error
            budget.inspect(chunk.type, chunk.data)
            document.chunks.append(chunk)
            if chunk.type == b'IEND':
                break
        try:
            document.validate(limits=limits)
        except PngValidationError as error:
            raise PngParseError(str(error)) from error
        document._original_chunks = tuple((chunk, chunk.type, chunk.data) for chunk in document.chunks)
        return document

    @staticmethod
    def load(file_path: str | PathLike[str], *, limits: PngReadLimits | None = None) -> PngDocument:
        """Read an entire PNG file; reject any content following IEND."""
        with open(file_path, 'rb') as file:
            document = PngDocument.parse(file, limits=limits)
            if file.read(1):
                raise PngParseError('unexpected data after IEND')
            return document

    def find_chunks(self, chunk_type: bytes) -> list[PngChunk]:
        """Return references to matching chunks, in document order."""
        return [chunk for chunk in self.chunks if chunk.type == chunk_type]

    def validate(self, *, limits: PngReadLimits | None = None) -> None:
        """Check envelope fields, core chunk payloads and standard ordering.

        CRCs are checked while parsing and recomputed while writing. This does
        not decompress IDAT or validate all metadata/APNG payload semantics.
        """
        validate_structure(self.chunks, limits=limits)

    def _output_chunks(self) -> list[PngChunk]:
        chunks = self.chunks
        if self._original_chunks is not None:
            original_critical = [(kind, data) for _, kind, data in self._original_chunks if not kind[0] & 0x20]
            for chunk in chunks:
                chunk.validate()
            current_critical = [(chunk.type, chunk.data) for chunk in chunks if chunk.is_critical]
            critical_changed = current_critical != original_critical
            original_histograms = {data for _, kind, data in self._original_chunks if kind == b'hIST'}
            locations: dict[int, tuple[bytes, int, bool]] = {}
            copied_locations: dict[tuple[bytes, bytes], list[tuple[int, bool]]] = {}
            critical_count = 0
            before_data = True
            for original, kind, data in self._original_chunks:
                locations[id(original)] = (kind, critical_count, before_data)
                if kind[0] & 0x20 and kind not in UNDERSTOOD_TYPES:
                    copied_locations.setdefault((kind, data), []).append((critical_count, before_data))
                critical_count += not bool(kind[0] & 0x20)
                if kind == b'IDAT':
                    before_data = False
            chunks = []
            critical_count = 0
            before_data = True
            for chunk in self.chunks:
                # Pixel-dependent zero frequencies cannot be checked without
                # decoding. Drop a loaded histogram after raw critical edits;
                # PngImage can instead validate or explicitly recalculate it.
                if chunk.type == b'hIST' and critical_changed and chunk.data in original_histograms:
                    continue
                if not chunk.is_critical and chunk.type not in UNDERSTOOD_TYPES:
                    # PNG section 14.2: never preserve unknown unsafe chunks
                    # after any addition, deletion, edit or reorder of criticals.
                    if not chunk.safe_to_copy and critical_changed:
                        continue
                    location = locations.get(id(chunk))
                    if location is not None and location[0] == chunk.type:
                        possible_locations = [(location[1], location[2])]
                    else:
                        # Copying/reconstructing a chunk object must not bypass
                        # the placement rules for its original encoded payload.
                        possible_locations = copied_locations.get((chunk.type, chunk.data), [])
                    if possible_locations:
                        if chunk.safe_to_copy and all(before_data != place[1] for place in possible_locations):
                            raise PngValidationError(f'cannot move unknown {chunk.type!r} across IDAT')
                        if not chunk.safe_to_copy and all(critical_count != place[0] for place in possible_locations):
                            raise PngValidationError(f'cannot move unknown {chunk.type!r} across critical chunks')
                chunks.append(chunk)
                critical_count += chunk.is_critical
                if chunk.type == b'IDAT':
                    before_data = False
        validate_structure(chunks, check_profile_structure=True)
        if any(chunk.reserved_bit for chunk in chunks):
            raise PngValidationError('cannot encode a chunk with a reserved lowercase third letter')
        return chunks

    @staticmethod
    def _dump(stream: BinaryIO, chunks: list[PngChunk]) -> None:
        write_all(stream, _SIGNATURE)
        for chunk in chunks:
            chunk.dump(stream)

    def dump(self, stream: BinaryIO) -> None:
        """Write raw chunks, applying unknown-chunk editing rules.

        Loaded unknown unsafe chunks are omitted if critical chunks changed.
        ICC and Exif structure is checked before writing any bytes. This does
        not modify self.chunks or re-encode compressed pixels.
        """
        self._dump(stream, self._output_chunks())

    def dump_to_bytes(self) -> bytes:
        stream = BytesIO()
        self.dump(stream)
        return stream.getvalue()

    def save(self, file_path: str | PathLike[str]) -> None:
        # Validate before opening so invalid in-memory data cannot truncate a
        # destination file. Operating-system errors propagate to the caller.
        chunks = self._output_chunks()
        with open(file_path, 'wb') as file:
            self._dump(file, chunks)
