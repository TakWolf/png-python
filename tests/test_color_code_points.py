from io import BytesIO

import pytest

from png import PngCicp, PngDocument, PngImage, PngValidationError


@pytest.mark.parametrize('primaries', [1, 2, 4, 9, 10, 12, 22])
@pytest.mark.parametrize('transfer', [1, 2, 4, 13, 16, 18])
def test_defined_h273_code_points_include_unspecified(primaries, transfer):
    PngCicp(primaries, transfer).validate_code_points()


@pytest.mark.parametrize(('primaries', 'transfer'), [(0, 1), (3, 1), (13, 1), (21, 1), (23, 1), (255, 1),
                                                     (1, 0), (1, 3), (1, 19), (1, 255)])
def test_reserved_h273_values_are_inspectable_but_not_written(png_suite_dir, tmp_path, primaries, transfer):
    image = PngImage.load(png_suite_dir.joinpath('basn2c08.png'))
    image.metadata.append(PngCicp(primaries, transfer))
    document = image.to_document()
    raw = b'\x89PNG\r\n\x1a\n' + b''.join(chunk.dump_to_bytes() for chunk in document.chunks)
    restored = PngImage.parse(raw)
    assert restored.find_metadata(b'cICP')[0].color_primaries == primaries
    for model in (restored, PngDocument.parse(raw)):
        stream = BytesIO(b'unchanged')
        with pytest.raises(PngValidationError, match='reserved'):
            model.dump(stream)
        assert stream.getvalue() == b'unchanged'
        target = tmp_path.joinpath('existing.png')
        target.write_bytes(b'unchanged')
        with pytest.raises(PngValidationError, match='reserved'): model.save(target)
        assert target.read_bytes() == b'unchanged'
