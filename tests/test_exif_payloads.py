from io import BytesIO
from struct import pack

import pytest

from png import PngExif, PngImage, PngValidationError
from tests.test_profiles import _tiff


def _payload_arrays(endian, offsets_tag, count_tag, kind, offsets, sizes):
    # Two fields, optional external arrays, followed by data bytes.
    start = 38
    external = bytearray()
    fields = []
    for tag, values, value_kind in ((offsets_tag, offsets, 4 if offsets_tag == 0x144 else kind),
                                     (count_tag, sizes, kind)):
        encoded = pack(endian + ('H' if value_kind == 3 else 'I') * len(values), *values)
        if len(encoded) > 4:
            value = pack(endian + 'I', start + len(external))
            external.extend(encoded)
        else:
            value = encoded + bytes(4 - len(encoded))
        fields.append((tag, value_kind, len(values), value))
    return _tiff(fields, endian=endian, tail=bytes(external) + bytes(32))


@pytest.mark.parametrize('endian', ['<', '>'])
@pytest.mark.parametrize(('offsets_tag', 'count_tag'), [(0x111, 0x117), (0x144, 0x145)])
@pytest.mark.parametrize('kind', [3, 4])
def test_strip_tile_payload_arrays_with_mixed_storage(endian, offsets_tag, count_tag, kind):
    # Odd image data addresses are valid, unlike TIFF field-value offsets.
    profile = _payload_arrays(endian, offsets_tag, count_tag, kind, [55, 57], [1, 2])
    PngExif(profile).validate_profile_structure()
    PngExif(profile).validate_profile_tags()


@pytest.mark.parametrize('damage', ['outside', 'length', 'unpaired', 'counts', 'bad_type'])
@pytest.mark.parametrize(('offsets_tag', 'count_tag'), [(0x111, 0x117), (0x144, 0x145)])
def test_strip_tile_payload_errors(offsets_tag, count_tag, damage):
    offsets, lengths = [55, 57], [1, 2]
    if damage == 'outside': offsets[0] = 0xFFFFFFFE
    elif damage == 'length': lengths[0] = 0xFFFFFFFF
    elif damage == 'counts': lengths = [1]
    data = _payload_arrays('>', offsets_tag, count_tag, 4, offsets, lengths)
    if damage == 'unpaired':
        data = _tiff([(offsets_tag, 4, 1, pack('>I', 26))], tail=b'abc')
    elif damage == 'bad_type':
        data = data[:12] + pack('>H', 7) + data[14:]
    with pytest.raises(PngValidationError, match='Exif'):
        PngExif(data).validate_profile_structure()


@pytest.mark.parametrize('endian', ['<', '>'])
@pytest.mark.parametrize('value', ['', 'A', '字', 'PNG\U0001f600'])
def test_exif_utf8_type_129(endian, value, png_suite_dir):
    encoded = value.encode('utf-8') + b'\0'
    inline = encoded + bytes(4 - len(encoded)) if len(encoded) <= 4 else pack(endian + 'I', 26)
    data = _tiff([(0x010E, 129, len(encoded), inline)], endian=endian,
                 tail=encoded if len(encoded) > 4 else b'')
    PngExif(data).validate_profile_tags()
    assert PngExif.from_chunk(PngExif(data).to_chunk()).profile == data
    image = PngImage.load(png_suite_dir.joinpath('basn2c08.png'))
    image.metadata.append(PngExif(data))
    restored = PngImage.parse(image.dump_to_bytes())
    assert restored.find_metadata(b'eXIf')[0].profile == data
    assert restored.bitmap == image.bitmap


@pytest.mark.parametrize(('kind', 'encoded'), [(129, b'\xc0\x80\0'), (129, b'\xed\xa0\x80\0'),
                                               (129, b'no\0x'), (2, b'\x80\0'), (2, b'no\0x')])
def test_exif_text_requires_valid_encoding_and_terminator(kind, encoded):
    data = _tiff([(0x010E, kind, len(encoded), encoded + bytes(4 - len(encoded)))])
    with pytest.raises(PngValidationError, match='Exif'):
        PngExif(data).validate_profile_structure()


@pytest.mark.parametrize(('kind', 'count', 'value'), [(4, 1, 1), (3, 2, 1), (3, 1, 0), (3, 1, 9)])
def test_orientation_errors_are_retained_but_block_png_writes(png_suite_dir, kind, count, value):
    data = _tiff([(0x0112, kind, count, pack('>I', value) if kind == 4 else pack('>HH', value, 0))])
    metadata = PngExif(data)
    metadata.validate_profile_structure()
    image = PngImage.load(png_suite_dir.joinpath('basn2c08.png'))
    image.metadata.append(metadata)
    document = image.to_document()
    for model in (image, document):
        stream = BytesIO(b'unchanged')
        with pytest.raises(PngValidationError, match='Exif'): model.dump(stream)
        assert stream.getvalue() == b'unchanged'


def test_exif_image_directory_chain_is_distinct_from_tiff_structure():
    # Three complete linked TIFF directories are structurally sound, but APP1
    # permits only a 0th image IFD and an optional 1st thumbnail IFD.
    entry = pack('>HHIHH', 0x0112, 3, 1, 1, 0)
    profile = b'MM\0*' + pack('>I', 8)
    profile += b''.join(pack('>H', 1) + entry + pack('>I', following) for following in (26, 44, 0))
    PngExif(profile).validate_profile_structure()
    with pytest.raises(PngValidationError, match='primary and thumbnail'):
        PngExif(profile).validate_profile_tags()


@pytest.mark.parametrize(('tag', 'kind', 'count'), [(0x9000, 2, 4), (0x9000, 7, 3),
                                                  (0xA001, 4, 1), (0xA002, 3, 2), (0x010E, 7, 1)])
def test_present_exif_standard_fields_have_their_declared_types(tag, kind, count):
    metadata = PngExif(_tiff([(tag, kind, count, bytes(4))]))
    metadata.validate_profile_structure()
    with pytest.raises(PngValidationError, match='Exif'):
        metadata.validate_profile_tags()
