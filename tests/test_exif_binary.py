from io import BytesIO
from struct import pack

import pytest

from png import PngExif, PngImage, PngValidationError
from png._exif_binary import validate_binary


@pytest.mark.parametrize('endian', ['<', '>'])
def test_exif_variable_payload_layouts(endian):
    table = pack(endian + 'HH', 1, 1) + b'Name\0' + pack(endian + 'ii', 1, 1)
    for tag in (0x8828, 0xA20C):
        validate_binary(tag, table, endian, b'0300')
        with pytest.raises(PngValidationError):
            validate_binary(tag, table[:-1], endian, b'0300')
    for tag, data in [
        (0xA302, pack(endian + 'HH', 2, 2) + bytes((1, 0, 2, 1))),
        (0xA40B, pack(endian + 'HH', 2, 1) + 'Setting\0'.encode('utf-16')),
        (0xA462, bytes(56) + pack(endian + 'HHII', 1, 2, 1, 1) + pack(endian + 'II', 2, 1)),
    ]:
        validate_binary(tag, data, endian, b'0300')
        with pytest.raises(PngValidationError):
            validate_binary(tag, data[:-1], endian, b'0300')


def test_exif_multicode_versions_and_undefined_text():
    validate_binary(0x9286, b'UNICODE\0' + '字'.encode('utf-8'), '>', b'0300')
    validate_binary(0x9286, b'UNICODE\0' + '字'.encode('utf-16-be'), '>', b'0232')
    validate_binary(0x9286, b'ASCII\0\0\0hello', '>', b'0300')
    validate_binary(0x9286, bytes(8) + b'\xff', '>', b'0300')
    with pytest.raises(PngValidationError):
        validate_binary(0x9286, b'UNICODE\0\xff', '>', b'0300')
    with pytest.raises(PngValidationError):
        validate_binary(0x9286, b'short', '>', b'0300')


def _profile(entries):
    # Root at 8, Exif IFD at 26. Strings/arrays follow its directory.
    root = b'MM\0*' + pack('>IH', 8, 1) + pack('>HHII', 0x8769, 4, 1, 26) + bytes(4)
    entries = [(0x9000, 7, b'0300')] + entries
    start = 26 + 2 + 12 * len(entries) + 4
    table, body = bytearray(), bytearray()
    for tag, kind, value in sorted(entries):
        count = len(value) // {3: 2, 4: 4, 5: 8}.get(kind, 1)
        field = value + bytes(4 - len(value)) if len(value) <= 4 else pack('>I', start + len(body))
        table.extend(pack('>HHI', tag, kind, count) + field)
        if len(value) > 4:
            body.extend(value)
            body.extend(bytes(-len(body) % 2))
    return root + pack('>H', len(entries)) + table + bytes(4) + body


@pytest.mark.parametrize(
    'entries',
    [
        [(0x8831, 4, pack('>I', 100))],
        [(0x8834, 4, pack('>I', 100))],
        [(0xA460, 3, pack('>H', 3))],
        [(0xA430, 2, b'A\0')],
        [(0xA439, 2, b'A\0')],
        [(0xA302, 7, pack('>HH', 2, 2) + b'\0')],
    ],
)
def test_binary_and_dependency_errors_block_writing(entries, png_suite_dir):
    profile = _profile(entries)
    metadata = PngExif(profile)
    metadata.validate_profile_structure()
    image = PngImage.load(png_suite_dir.joinpath('basn2c08.png'))
    image.metadata.append(metadata)
    for model in (image, image.to_document()):
        stream = BytesIO(b'unchanged')
        with pytest.raises(PngValidationError):
            model.dump(stream)
        assert stream.getvalue() == b'unchanged'


def test_valid_sensitivity_and_composite_dependencies():
    PngExif(
        _profile([(0x8827, 3, pack('>H', 100)), (0x8830, 3, pack('>H', 1)), (0x8831, 4, pack('>I', 100))])
    ).validate_profile_tags()
    PngExif(
        _profile([(0xA460, 3, pack('>H', 3)), (0xA461, 3, pack('>HH', 2, 2)), (0xA462, 7, bytes(56) + pack('>H', 0))])
    ).validate_profile_tags()
