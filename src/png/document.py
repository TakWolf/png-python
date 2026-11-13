from png.chunk import PngChunk


class PngDocument:
    """The ordered, encoded chunk representation of a PNG datastream.

    Repeated chunks and their positions are retained. Decoded pixels belong to
    PngImage instead; no automatic synchronization between the two is performed.
    """

    chunks: list[PngChunk]

    def __init__(self, chunks: list[PngChunk] | None = None) -> None:
        self.chunks = chunks if chunks is not None else []

    def find_chunks(self, chunk_type: bytes) -> list[PngChunk]:
        """Return references to matching chunks, in document order."""
        return [chunk for chunk in self.chunks if chunk.type == chunk_type]
