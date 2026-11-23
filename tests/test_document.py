from copy import deepcopy
from io import BytesIO
from pathlib import Path

import pytest

from png import PngChunk, PngCrcError, PngDocument, PngHeader, PngParseError, PngValidationError


@pytest.fixture
def document(png_suite_dir: Path) -> PngDocument:
    return PngDocument.load(png_suite_dir.joinpath('basn2c08.png'))


def test_complete_pngsuite_is_available(png_suite_dir: Path) -> None:
    assert len([path for path in png_suite_dir.glob('*.png') if not path.name.startswith('x')]) == 162
    assert len(list(png_suite_dir.glob('x*.png'))) == 14


def test_pngsuite_file_roundtrip(png_suite_file: Path, tmp_path: Path) -> None:
    source = png_suite_file
    document = PngDocument.load(source)
    # This is a raw-chunk round trip. It must retain the original payloads,
    # chunk boundaries, repeated chunks and their ordering without decoding.
    assert document.dump_to_bytes() == source.read_bytes()
    destination = tmp_path.joinpath(source.name)
    document.save(destination)
    loaded = PngDocument.load(str(destination))
    assert [(chunk.type, chunk.data) for chunk in loaded.chunks] == [
        (chunk.type, chunk.data) for chunk in document.chunks
    ]


def test_pngsuite_damaged_files(png_suite_invalid_file: Path) -> None:
    with pytest.raises(PngParseError):
        PngDocument.load(png_suite_invalid_file)


@pytest.mark.parametrize('name', ['xcsn0g01.png', 'xhdn0g08.png'])
def test_pngsuite_bad_crc(png_suite_dir: Path, name: str) -> None:
    with pytest.raises(PngCrcError):
        PngDocument.load(png_suite_dir.joinpath(name))


def test_stream_position_and_ownership(png_suite_dir: Path) -> None:
    encoded = png_suite_dir.joinpath('basn2c08.png').read_bytes()
    stream = BytesIO(b'prefix' + encoded + b'suffix')
    stream.seek(6)
    document = PngDocument.parse(stream)
    assert stream.read() == b'suffix'
    assert not stream.closed
    output = BytesIO(b'prefix')
    output.seek(6)
    document.dump(output)
    assert output.getvalue() == b'prefix' + encoded
    assert not output.closed


def test_stream_without_seek(png_suite_dir: Path) -> None:
    class Input:
        def __init__(self, data: bytes) -> None:
            self.stream = BytesIO(data)

        def read(self, size: int) -> bytes:
            return self.stream.read(min(size, 5))

    encoded = png_suite_dir.joinpath('basn2c08.png').read_bytes()
    assert PngDocument.parse(Input(encoded)).dump_to_bytes() == encoded


@pytest.mark.parametrize('cut', [0, 1, 7, 8, 12, 16, 29, 32, 33, 40, -1, -4, -12])
def test_truncated_datastream(png_suite_dir: Path, cut: int) -> None:
    data = png_suite_dir.joinpath('basn2c08.png').read_bytes()
    with pytest.raises(PngParseError):
        PngDocument.parse(data[:cut])


def test_parse_wraps_structure_errors(document: PngDocument) -> None:
    document.chunks.insert(-1, PngChunk(b'IDAT'))
    document.chunks.insert(-2, PngChunk(b'vpAg'))
    encoded = b'\x89PNG\r\n\x1a\n' + b''.join(chunk.dump_to_bytes() for chunk in document.chunks)
    with pytest.raises(PngParseError, match='consecutive'):
        PngDocument.parse(encoded)


@pytest.mark.parametrize('kind', [b'IHDR', b'PLTE', b'gAMA', b'tIME'])
def test_singleton_chunks(document: PngDocument, kind: bytes) -> None:
    if kind == b'IHDR':
        chunk = document.chunks[0]
    else:
        chunk = PngChunk(kind, {b'PLTE': bytes(3), b'gAMA': bytes(4), b'tIME': bytes(7)}[kind])
        document.chunks.insert(1, chunk)
    document.chunks.insert(1, chunk)
    with pytest.raises(PngValidationError, match='duplicate'):
        document.validate()


def test_required_chunks_and_iend_payload(document: PngDocument) -> None:
    with pytest.raises(PngValidationError, match='IHDR'):
        PngDocument(document.chunks[1:]).validate()
    with pytest.raises(PngValidationError, match='IEND'):
        PngDocument(document.chunks[:-1]).validate()
    with pytest.raises(PngValidationError, match='IDAT'):
        PngDocument([chunk for chunk in document.chunks if chunk.type != b'IDAT']).validate()
    document.chunks[-1].data = b'nonempty'
    with pytest.raises(PngValidationError, match='IEND'):
        document.validate()


def test_unknown_critical_chunk(document: PngDocument) -> None:
    document.chunks.insert(1, PngChunk(b'VpAg'))
    with pytest.raises(PngValidationError, match='unknown critical'):
        document.dump_to_bytes()


@pytest.mark.parametrize('kind', [b'gAMA', b'cHRM', b'sRGB', b'pHYs', b'eXIf', b'sPLT', b'tRNS'])
def test_pre_data_chunks_cannot_follow_idat(document: PngDocument, kind: bytes) -> None:
    document.chunks = [chunk for chunk in document.chunks if chunk.type != kind]
    size = {b'gAMA': 4, b'cHRM': 32, b'sRGB': 1, b'pHYs': 9, b'tRNS': 6}.get(kind, 0)
    document.chunks.insert(-1, PngChunk(kind, bytes(size)))
    with pytest.raises(PngValidationError, match='precede IDAT'):
        document.validate()


def test_palette_order_and_size(document: PngDocument) -> None:
    palette = PngChunk(b'PLTE', bytes(3))
    document.chunks.insert(1, palette)
    with pytest.raises(PngValidationError, match='precede PLTE'):
        document.validate()  # The original gAMA now follows PLTE.
    document.chunks.remove(palette)
    document.chunks.insert(-2, palette)
    document.validate()
    palette.data = bytes(4)
    with pytest.raises(PngValidationError, match='RGB entries'):
        document.validate()


def test_indexed_palette_and_transparency(png_suite_dir: Path) -> None:
    document = PngDocument.load(png_suite_dir.joinpath('basn3p01.png'))
    palette = document.find_chunks(b'PLTE')[0]
    palette.data += bytes(3)
    with pytest.raises(PngValidationError, match='bit depth'):
        document.validate()
    palette.data = palette.data[:-3]
    document.chunks.insert(-2, PngChunk(b'tRNS', bytes(3)))
    with pytest.raises(PngValidationError, match='more entries'):
        document.validate()
    document.find_chunks(b'tRNS')[0].data = b'\x00'
    document.validate()
    document.chunks.remove(palette)
    with pytest.raises(PngValidationError, match='PLTE'):
        document.validate()


@pytest.mark.parametrize(('kind', 'data'), [(b'PLTE', bytes(3)), (b'tRNS', bytes(2))])
def test_color_type_restrictions(png_suite_dir: Path, kind: bytes, data: bytes) -> None:
    name = 'basn0g08.png' if kind == b'PLTE' else 'basn6a08.png'
    document = PngDocument.load(png_suite_dir.joinpath(name))
    document.chunks.insert(-2, PngChunk(kind, data))
    with pytest.raises(PngValidationError, match='forbidden'):
        document.validate()


@pytest.mark.parametrize('kind', [b'gAMA', b'sRGB', b'cICP', b'mDCV', b'cLLI', b'pHYs', b'tIME'])
def test_fixed_metadata_lengths(document: PngDocument, kind: bytes) -> None:
    document.chunks = [chunk for chunk in document.chunks if chunk.type != kind]
    document.chunks.insert(1, PngChunk(kind))
    with pytest.raises(PngValidationError, match='data bytes'):
        document.validate()


def test_palette_dependent_metadata(document: PngDocument) -> None:
    document.chunks.insert(-2, PngChunk(b'hIST', bytes(2)))
    with pytest.raises(PngValidationError, match='PLTE'):
        document.validate()
    document.chunks.insert(-3, PngChunk(b'PLTE', bytes(3)))
    document.validate()
    document.find_chunks(b'hIST')[0].data = bytes(4)
    with pytest.raises(PngValidationError, match='hIST'):
        document.validate()


def test_unknown_chunks_and_ancillary_only_edits(document: PngDocument) -> None:
    # The original file acts as the source of the pixels; custom chunks are
    # inserted solely to exercise the standard's editor rules.
    document.chunks.insert(1, PngChunk(b'vpAg', b'safe'))
    document.chunks.insert(1, PngChunk(b'vpAG', b'unsafe'))
    original = PngDocument.parse(document.dump_to_bytes())
    original.chunks.insert(1, PngChunk(b'tEXt', b'Title\0Edited'))
    reparsed = PngDocument.parse(original.dump_to_bytes())
    assert reparsed.find_chunks(b'vpAg')[0].data == b'safe'
    assert reparsed.find_chunks(b'vpAG')[0].data == b'unsafe'


def test_critical_edit_omits_unknown_unsafe_chunks(document: PngDocument) -> None:
    document.chunks.insert(1, PngChunk(b'vpAg', b'safe'))
    document.chunks.insert(1, PngChunk(b'vpAG', b'unsafe'))
    original = PngDocument.parse(document.dump_to_bytes())
    cloned = deepcopy(original)
    # Splitting IDAT changes critical chunks, but retains the encoded pixels.
    index = next(index for index, chunk in enumerate(cloned.chunks) if chunk.type == b'IDAT')
    payload = cloned.chunks[index].data
    cloned.chunks[index : index + 1] = [PngChunk(b'IDAT', payload[:1]), PngChunk(b'IDAT', payload[1:])]
    output = PngDocument.parse(cloned.dump_to_bytes())
    assert output.find_chunks(b'vpAg')[0].data == b'safe'
    assert not output.find_chunks(b'vpAG')
    assert output.find_chunks(b'gAMA')  # Supported color metadata survives a critical edit.
    assert cloned.find_chunks(b'vpAG')  # Saving does not mutate the model.
    assert len(original.find_chunks(b'IDAT')) == 1
    assert b''.join(chunk.data for chunk in output.find_chunks(b'IDAT')) == payload


@pytest.mark.parametrize('kind', [b'vpAg', b'vpAG'])
@pytest.mark.parametrize('reconstruct', [False, True])
def test_unknown_chunk_cannot_cross_idat(document: PngDocument, kind: bytes, reconstruct: bool) -> None:
    document.chunks.insert(1, PngChunk(kind, b'payload'))
    loaded = PngDocument.parse(document.dump_to_bytes())
    unknown = loaded.find_chunks(kind)[0]
    loaded.chunks.remove(unknown)
    if reconstruct:
        unknown = PngChunk(unknown.type, unknown.data)
    loaded.chunks.insert(-1, unknown)
    with pytest.raises(PngValidationError, match='cannot move unknown'):
        loaded.dump_to_bytes()


def test_read_future_reserved_name_but_do_not_encode_it(document: PngDocument) -> None:
    unknown = PngChunk(b'vpag', b'future')
    chunks = document.chunks[:-1] + [unknown, document.chunks[-1]]
    encoded = b'\x89PNG\r\n\x1a\n' + b''.join(chunk.dump_to_bytes() for chunk in chunks)
    loaded = PngDocument.parse(encoded)
    assert loaded.find_chunks(b'vpag')[0].data == b'future'
    with pytest.raises(PngValidationError, match='reserved'):
        loaded.dump_to_bytes()


def test_invalid_document_does_not_truncate_destination(document: PngDocument, tmp_path: Path) -> None:
    destination = tmp_path.joinpath('existing.png')
    original = document.dump_to_bytes()
    destination.write_bytes(original)
    document.chunks.pop()
    with pytest.raises(PngValidationError):
        document.save(destination)
    assert destination.read_bytes() == original


def test_header_edit_is_explicit(document: PngDocument) -> None:
    header = PngHeader.from_chunk(document.chunks[0])
    header.width = 1
    assert PngHeader.from_chunk(document.chunks[0]).width == 32
    document.chunks[0] = header.to_chunk()
    assert PngHeader.from_chunk(document.chunks[0]).width == 1
