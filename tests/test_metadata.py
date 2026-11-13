from copy import deepcopy
from fractions import Fraction
from pathlib import Path
from struct import pack
import zlib

import pytest

from png import (
    PngChunk, PngChromaticities, PngCicp, PngCompressedText, PngContentLightLevel,
    PngDocument, PngExif, PngGamma, PngHeader, PngIccProfile, PngImage,
    PngInternationalText, PngMasteringDisplayColorVolume, PngPhysicalDimensions,
    PngPhysicalUnit, PngRenderingIntent, PngSrgb, PngText, PngTime,
    PngParseError, PngValidationError,
)

_ROOT = Path(__file__).parents[1]
_SUITE = _ROOT.joinpath('assets', 'png-suite')
_WPT = _ROOT.joinpath('assets', 'wpt', 'png', 'support')
_VALID = sorted(path.name for path in _SUITE.glob('*.png') if not path.name.startswith('x'))


@pytest.mark.parametrize('name', _VALID)
def test_pngsuite_metadata_is_preserved(png_suite_dir: Path, name: str) -> None:
    image = PngImage.load(png_suite_dir.joinpath(name))
    restored = PngImage.parse(image.dump_to_bytes())
    assert [(item.type, item.to_chunk().data) for item in restored.metadata] == [
        (item.type, item.to_chunk().data) for item in image.metadata
    ]


@pytest.mark.parametrize('path', sorted(_WPT.glob('*.png')), ids=lambda path: path.name)
def test_wpt_color_and_exif_metadata(path: Path) -> None:
    image = PngImage.load(path)
    restored = PngImage.parse(image.dump_to_bytes())
    assert restored.bitmap == image.bitmap
    assert [(item.type, item.to_chunk().data) for item in restored.metadata] == [
        (item.type, item.to_chunk().data) for item in image.metadata
    ]


@pytest.mark.parametrize(('metadata', 'expected'), [
    (PngGamma(45455), bytes.fromhex('0000b18f')),
    (PngSrgb(PngRenderingIntent.SATURATION), b'\x02'),
    (PngCicp(9, 16), bytes.fromhex('09100001')),
    (PngContentLightLevel(10000000, 2500000), bytes.fromhex('00989680002625a0')),
    (PngPhysicalDimensions(11811, 11811, PngPhysicalUnit.METRE), bytes.fromhex('00002e2300002e2301')),
    (PngTime(2016, 12, 31, 23, 59, 60), bytes.fromhex('07e00c1f173b3c')),
    (PngText('Title', 'Café'), b'Title\0Caf\xe9'),
    (PngInternationalText('Title', '测试', 'zh', '标题'),
     b'Title\0\0\0zh\0' + '标题'.encode() + b'\0' + '测试'.encode()),
])
def test_fixed_reference_payloads(metadata, expected: bytes) -> None:
    assert metadata.to_chunk().data == expected
    assert type(metadata).from_chunk(PngChunk(metadata.type, expected)).to_chunk().data == expected


def test_gamma_exact_units_and_mutation() -> None:
    gamma = PngGamma(45455)
    assert gamma.gamma == Fraction(45455, 100000)
    gamma.raw_gamma = 100000
    assert gamma.gamma == 1


def test_hdr_example_and_official_whitepoint_erratum() -> None:
    metadata = PngMasteringDisplayColorVolume(
        (35400, 14600), (8500, 39850), (6550, 2300), (15635, 16450), 40000000, 5,
    )
    # The erratum corrects D65 x to 0x3d13, not the old example's 0x3c05.
    expected = bytes.fromhex('8a48390821349baa199608fc3d13404202625a0000000005')
    assert metadata.to_chunk().data == expected
    parsed = PngMasteringDisplayColorVolume.from_chunk(PngChunk(b'mDCV', expected))
    assert parsed.white_point == (15635, 16450)
    assert parsed.maximum_luminance == 40000000


def test_chromaticity_field_order() -> None:
    raw = pack('>8I', 1, 2, 3, 4, 5, 6, 7, 8)
    value = PngChromaticities.from_chunk(PngChunk(b'cHRM', raw))
    assert value.white_point == (1, 2)
    assert value.red == (3, 4)
    assert value.green == (5, 6)
    assert value.blue == (7, 8)


def test_create_edit_repeated_multilingual_metadata() -> None:
    image = PngImage(PngHeader((1, 1)), [[255, 0, 0, 255]], metadata=[
        PngGamma(45455), PngPhysicalDimensions(11811, 11811, PngPhysicalUnit.METRE),
        PngText('Author', 'First'), PngText('Author', 'Second'),
        PngInternationalText('Description', '中文说明', 'zh-Hans', '说明', compressed=True),
        PngCompressedText('Comment', 'Café\nComments'),
    ])
    restored = PngImage.parse(image.dump_to_bytes())
    assert [entry.text for entry in restored.find_metadata(b'tEXt')] == ['First', 'Second']
    restored.find_metadata(b'tEXt')[1].text = 'Edited'
    restored.find_metadata(b'gAMA')[0].raw_gamma = 50000
    independent = deepcopy(restored)
    independent.find_metadata(b'tEXt')[0].text = 'Copy'
    assert restored.find_metadata(b'tEXt')[0].text == 'First'
    output = PngImage.parse(restored.dump_to_bytes())
    assert output.find_metadata(b'gAMA')[0].gamma == Fraction(1, 2)
    assert [entry.text for entry in output.find_metadata(b'tEXt')] == ['First', 'Edited']
    assert output.find_metadata(b'iTXt')[0].text == '中文说明'


@pytest.mark.parametrize('compressed', [False, True])
def test_large_international_text(compressed: bool) -> None:
    text = '中文abc\n' * 20000
    source = PngInternationalText('Description', text, compressed=compressed)
    decoded = PngInternationalText.from_chunk(source.to_chunk())
    assert decoded.text == text
    assert decoded.compressed is compressed


def test_compression_is_standard_zlib_and_methods_are_handled_correctly() -> None:
    source = PngCompressedText('Comment', 'é' * 100000)
    assert zlib.decompress(source.to_chunk().data.split(b'\0', 1)[1][1:]).decode('latin-1') == source.text
    assert PngCompressedText.from_chunk(source.to_chunk()).text == source.text
    # Decoders must ignore the method when iTXt's compression flag is zero.
    raw = PngChunk(b'iTXt', b'Title\0\0\xffen\0Title\0Text')
    decoded = PngInternationalText.from_chunk(raw)
    assert decoded.text == 'Text'
    assert decoded.to_chunk().data == b'Title\0\0\0en\0Title\0Text'


@pytest.mark.parametrize('keyword', ['', ' leading', 'trailing ', 'two  spaces', 'line\nbreak', '\xa0', 'x' * 80, '中文'])
def test_invalid_keywords(keyword: str) -> None:
    with pytest.raises(PngValidationError):
        PngText(keyword, 'text').to_chunk()


@pytest.mark.parametrize('chunk', [
    PngChunk(b'tEXt', b'no separator'),
    PngChunk(b'tEXt', b'Keyword\0text\0'),
    PngChunk(b'zTXt', b'Keyword\0\x01' + zlib.compress(b'text')),
    PngChunk(b'zTXt', b'Keyword\0\0' + zlib.compress(b'text')[:-1]),
    PngChunk(b'zTXt', b'Keyword\0\0' + zlib.compress(b'text') + b'extra'),
    PngChunk(b'iTXt', b'Keyword\0\x02\0\0\0text'),
    PngChunk(b'iTXt', b'Keyword\0\x01\x01\0\0' + zlib.compress(b'text')),
    PngChunk(b'iTXt', b'Keyword\0\0\0en\0'),
    PngChunk(b'iTXt', b'Keyword\0\0\0\0\0\xff'),
    PngChunk(b'iCCP', b'Profile\0\x01' + zlib.compress(b'data')),
    PngChunk(b'iCCP', b'Profile\0\0' + zlib.compress(b'')),
    PngChunk(b'eXIf', b'Exif\0\0II*\0'),
])
def test_malformed_payloads(chunk: PngChunk) -> None:
    from png.metadata import parse_metadata
    with pytest.raises(PngValidationError):
        parse_metadata(chunk)


@pytest.mark.parametrize('value', [
    PngGamma(0), PngGamma(0x80000000), PngSrgb(4), PngSrgb(True),
    PngCicp(1, 1, matrix_coefficients=1), PngCicp(1, 1, video_full_range_flag=2),
    PngPhysicalDimensions(-1, 1), PngPhysicalDimensions(1, 1, unit=2),
    PngTime(2026, 13, 1), PngTime(2026, 1, 0), PngTime(2026, 1, 1, second=61),
    PngContentLightLevel(0x80000000, 0), PngText('Title', '中文'),
    PngInternationalText('Title', 'text', language_tag='en_US'),
    PngInternationalText('Title', 'nul\0text'),
])
def test_invalid_metadata_fields(value) -> None:
    with pytest.raises(PngValidationError):
        value.validate()


def test_icc_profile_bytes_preserved_and_decoded_with_independent_zlib() -> None:
    document = PngDocument.load(_WPT.joinpath('cICP-and-iCCP.png'))
    raw = document.find_chunks(b'iCCP')[0]
    expected = zlib.decompress(raw.data.split(b'\0', 1)[1][1:])
    image = PngImage.from_document(document)
    profile = image.find_metadata(b'iCCP')[0]
    assert isinstance(profile, PngIccProfile)
    assert profile.profile == expected
    assert profile.profile[36:40] == b'acsp'
    assert PngImage.parse(image.dump_to_bytes()).find_metadata(b'iCCP')[0].profile == expected


def test_exif_profile_bytes_are_not_rewritten() -> None:
    document = PngDocument.load(_WPT.joinpath('exif-orientation-bottom-right.png'))
    original = document.find_chunks(b'eXIf')[0].data
    image = PngImage.from_document(document)
    assert isinstance(image.find_metadata(b'eXIf')[0], PngExif)
    assert image.find_metadata(b'eXIf')[0].profile == original
    assert image.to_document().find_chunks(b'eXIf')[0].data == original


def test_text_placement_and_independent_models(png_suite_dir: Path) -> None:
    document = PngDocument.load(png_suite_dir.joinpath('basn2c08.png'))
    document.chunks.insert(1, PngText('Title', 'Before').to_chunk())
    document.chunks.insert(-1, PngCompressedText('Comment', 'After').to_chunk())
    image = PngImage.from_document(document)
    image.find_metadata(b'tEXt')[0].text = 'Edited'
    assert document.find_chunks(b'tEXt')[0].data == b'Title\0Before'
    output = image.to_document()
    kinds = [chunk.type for chunk in output.chunks]
    assert kinds.index(b'tEXt') < kinds.index(b'IDAT') < kinds.index(b'zTXt')


def test_duplicate_raw_and_structured_metadata_is_rejected() -> None:
    image = PngImage(PngHeader((1, 1)), [[0] * 4], metadata=[PngGamma(45455)],
                     ancillary_chunks=[PngGamma(45455).to_chunk()])
    with pytest.raises(PngValidationError, match='duplicate'):
        image.validate()


def test_srgb_consistency_and_hdr_dependency() -> None:
    image = PngImage(PngHeader((1, 1)), [[0] * 4], metadata=[PngSrgb(), PngGamma(100000)])
    with pytest.raises(PngValidationError, match='45455'):
        image.validate()
    image.metadata[1] = PngGamma(45455)
    image.validate()
    image.metadata.append(PngChromaticities((0, 0), (0, 0), (0, 0), (0, 0)))
    with pytest.raises(PngValidationError, match='chromaticities'):
        image.validate()
    image.metadata = [PngMasteringDisplayColorVolume((1, 2), (3, 4), (5, 6), (7, 8), 10000, 0)]
    with pytest.raises(PngValidationError, match='cICP'):
        image.validate()
    image.metadata.append(PngCicp(9, 16))
    image.validate()


def test_invalid_metadata_parse_error(png_suite_dir: Path) -> None:
    document = PngDocument.load(png_suite_dir.joinpath('basn2c08.png'))
    document.find_chunks(b'gAMA')[0].data = bytes(4)
    raw = b'\x89PNG\r\n\x1a\n' + b''.join(chunk.dump_to_bytes() for chunk in document.chunks)
    with pytest.raises(PngParseError, match='gamma'):
        PngImage.parse(raw)


def test_color_metadata_in_composited_snapshots_is_independent() -> None:
    image = PngImage(PngHeader((1, 1)), [[0] * 4], metadata=[PngGamma(45455)])
    snapshot = next(image.render_frames()).image
    snapshot.find_metadata(b'gAMA')[0].raw_gamma = 100000
    assert image.find_metadata(b'gAMA')[0].raw_gamma == 45455
