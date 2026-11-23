import zlib
from io import BytesIO
from struct import pack
from unittest.mock import patch

import pytest

import png.metadata as metadata
from png import (
    PngChunk,
    PngCompressedText,
    PngCrcError,
    PngDocument,
    PngHeader,
    PngIccProfile,
    PngImage,
    PngInternationalText,
    PngLimitError,
    PngParseError,
    PngReadLimits,
    PngValidationError,
)
from png._limits import ReadBudget


@pytest.mark.parametrize('kind', ['zTXt', 'iTXt', 'iCCP'])
@pytest.mark.parametrize('entrypoint', ['parse', 'load', 'from_document'])
def test_reading_parses_compressed_metadata_once_without_encoding(kind, entrypoint, icc_profile_bytes, tmp_path):
    item = {
        'zTXt': PngCompressedText('k', 'a' * 100000),
        'iTXt': PngInternationalText('k', 'a' * 100000, compressed=True),
        'iCCP': PngIccProfile('k', icc_profile_bytes),
    }[kind]
    data = PngImage(PngHeader((1, 1)), [[1, 2, 3, 255]], metadata=[item]).dump_to_bytes()
    document = PngDocument.parse(data)
    path = tmp_path.joinpath('source.png')
    path.write_bytes(data)
    with patch.object(metadata, '_inflate', wraps=metadata._inflate) as inflated:
        with patch.object(zlib, 'compress', side_effect=AssertionError('reading must not encode metadata')):
            if entrypoint == 'from_document':
                image = PngImage.from_document(document)
            elif entrypoint == 'load':
                image = PngImage.load(path)
            else:
                image = PngImage.parse(data)
            image.validate()
    assert inflated.call_count == 1
    assert image.metadata[0] is not item
    if kind == 'iCCP':
        image.metadata[0].name = ' invalid'
    else:
        image.metadata[0].text = 'invalid\0text'
    with pytest.raises(PngValidationError):
        image.validate()


@pytest.mark.parametrize('kind', [b'tEXt', b'vpAg'])
def test_metadata_length_limit_rejects_before_payload(kind):
    prefix = b'\x89PNG\r\n\x1a\n' + PngHeader((1, 1)).to_chunk().dump_to_bytes()
    stream = BytesIO(prefix + pack('>I4s', 1000000, kind))
    with pytest.raises(PngLimitError) as caught:
        PngDocument.parse(stream, limits=PngReadLimits(max_metadata_bytes=10))
    assert caught.value.limit == 'max_metadata_bytes'
    assert stream.tell() == len(prefix) + 8


def test_invalid_international_text_prefix_is_checked_before_inflation():
    chunk = PngChunk(b'iTXt', b'k\0\x01\x00bad_tag\0\0' + zlib.compress(b'a' * 1000000))
    with patch.object(metadata, '_inflate', side_effect=AssertionError('must check prefix first')):
        with pytest.raises(PngValidationError, match='language tag'):
            metadata.parse_metadata(chunk)


def test_invalid_icc_prefix_stops_before_expanding_remaining_profile():
    chunk = PngChunk(b'iCCP', b'k\0\0' + zlib.compress(bytes(128) + b'a' * 1000000))
    budget = ReadBudget(None)
    with pytest.raises(PngValidationError, match='acsp'):
        PngIccProfile._from_chunk(chunk, budget)
    assert budget.metadata_bytes == 131


def test_compressed_metadata_limit_stops_before_later_chunks():
    prefix = b'\x89PNG\r\n\x1a\n' + PngHeader((1, 1)).to_chunk().dump_to_bytes()
    chunk = PngCompressedText('k', 'a' * 100000).to_chunk().dump_to_bytes()
    stream = BytesIO(prefix + chunk + b'unread subsequent chunks')
    with pytest.raises(PngLimitError):
        PngImage.parse(stream, limits=PngReadLimits(max_metadata_bytes=10))
    assert stream.tell() == len(prefix) + len(chunk)


def test_metadata_crc_precedes_payload_validation():
    prefix = b'\x89PNG\r\n\x1a\n' + PngHeader((1, 1)).to_chunk().dump_to_bytes()
    chunk = bytearray(PngChunk(b'iTXt', b'bad').dump_to_bytes())
    chunk[-1] ^= 1
    with pytest.raises(PngCrcError):
        PngImage.parse(prefix + chunk)


def test_mutated_document_is_revalidated():
    data = PngImage(PngHeader((1, 1)), [[1, 2, 3, 255]], metadata=[PngCompressedText('k', 'valid')]).dump_to_bytes()
    document = PngDocument.parse(data)
    document.find_chunks(b'zTXt')[0].data = b'k\0\0broken'
    with pytest.raises(PngValidationError):
        PngImage.from_document(document)
    with pytest.raises(PngParseError):
        PngImage.parse(b'\x89PNG\r\n\x1a\n' + b''.join(chunk.dump_to_bytes() for chunk in document.chunks))
