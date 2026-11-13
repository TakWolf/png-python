from copy import copy, deepcopy
from fractions import Fraction

import pytest

from png import (
    PngAnimation, PngBlendOp, PngChunk, PngColorType, PngDocument,
    PngFrame, PngFrameControl, PngHeader, PngImage, PngValidationError,
)


def test_raw_chunk_flags_and_derived_fields() -> None:
    chunk = PngChunk(b'vpAg', b'original')
    assert not chunk.is_critical
    assert chunk.is_private
    assert not chunk.reserved_bit
    assert chunk.safe_to_copy
    crc = chunk.crc
    chunk.data = b'new'
    assert chunk.length == 3
    assert chunk.crc != crc
    assert PngChunk(b'IHDR').is_critical
    assert not PngChunk(b'IHDR').safe_to_copy
    # A future reserved bit can be retained by the raw model.
    assert PngChunk(b'vpgg').reserved_bit


@pytest.mark.parametrize('chunk_type', [b'', b'abc', b'abcde', b'ab1d', b'\xffabc', 'IHDR'])
def test_invalid_chunk_type(chunk_type: bytes) -> None:
    with pytest.raises(PngValidationError):
        PngChunk(chunk_type).validate()


def test_document_preserves_order_repetition_and_references() -> None:
    first = PngChunk(b'tEXt', b'Title\0First')
    second = PngChunk(b'tEXt', b'Title\0Second')
    middle = PngChunk(b'vpAg')
    document = PngDocument([first, middle, second])
    assert document.find_chunks(b'tEXt') == [first, second]
    assert document.chunks[1] is middle
    document.find_chunks(b'tEXt')[0].data = b'Title\0Edited'
    assert document.chunks[0].data == b'Title\0Edited'
    assert PngDocument().chunks is not PngDocument().chunks


def test_image_samples_and_copy_semantics() -> None:
    image = PngImage(PngHeader((1, 1), bit_depth=16), [[65535, 12345, 0, 32768]])
    image.validate()
    shallow = copy(image)
    independent = deepcopy(image)
    image.bitmap[0][1] = 54321
    assert shallow.bitmap[0][1] == 54321
    assert independent.bitmap[0][1] == 12345
    assert independent.header is not image.header
    assert PngImage(PngHeader((1, 1))).palette is not image.palette


@pytest.mark.parametrize('bitmap', [[], [[]], [[0, 0, 0]], [[0, 0, 0, 256]], [[0, -1, 0, 255]], [[0, 0, 0, True]]])
def test_invalid_bitmap(bitmap: list[list[int]]) -> None:
    with pytest.raises(PngValidationError):
        PngImage(PngHeader((1, 1)), bitmap).validate()


def test_indexed_samples_and_palette_transparency() -> None:
    image = PngImage(
        PngHeader((2, 1), bit_depth=1, color_type=PngColorType.INDEXED_COLOR),
        bitmap=[[0, 1]], palette=[(0, 0, 0), (255, 255, 255)], palette_alpha=[0],
    )
    image.validate()
    assert image.bitmap == [[0, 1]]
    # A valid bit-depth value can still be an invalid palette index.
    image.palette.pop()
    with pytest.raises(PngValidationError):
        image.validate()
    image.bitmap = [[0, 0]]
    image.validate()
    image.palette_alpha.extend([255])
    with pytest.raises(PngValidationError):
        image.validate()


@pytest.mark.parametrize(('color', 'depth', 'bitmap', 'transparent'), [
    (PngColorType.GRAYSCALE, 2, [[0, 3]], (3,)),
    (PngColorType.TRUECOLOR, 16, [[0, 1, 65535]], (0, 1, 65535)),
])
def test_transparent_sample_depth(color, depth, bitmap, transparent) -> None:
    width = len(bitmap[0]) // color.channels
    image = PngImage(PngHeader((width, 1), depth, color), bitmap, transparent_color=transparent)
    image.validate()
    image.transparent_color = (1 << depth,) * color.channels
    with pytest.raises(PngValidationError):
        image.validate()


def test_palette_constraints_and_alpha_conflicts() -> None:
    image = PngImage(PngHeader((1, 1), color_type=PngColorType.GRAYSCALE), [[0]], palette=[(0, 0, 0)])
    with pytest.raises(PngValidationError):
        image.validate()
    image = PngImage(PngHeader((1, 1)), [[0, 0, 0, 255]], transparent_color=(0, 0, 0))
    with pytest.raises(PngValidationError):
        image.validate()
    image.transparent_color = None
    image.palette_alpha = [0]
    with pytest.raises(PngValidationError):
        image.validate()


def test_default_frame_has_one_pixel_source() -> None:
    image = PngImage(PngHeader((2, 1)), [[255, 0, 0, 255, 0, 255, 0, 255]])
    image.animation = PngAnimation(default_image_control=PngFrameControl((2, 1)))
    image.validate()
    assert image.animation.num_frames == 1
    frame = PngFrame(PngFrameControl((1, 1), offset=(1, 0), blend_op=PngBlendOp.OVER), [[0, 0, 255, 128]])
    image.animation.frames.append(frame)
    image.validate()
    assert image.animation.num_frames == 2
    image.bitmap[0][0] = 128
    image.validate()


def test_poster_is_not_an_animation_frame() -> None:
    image = PngImage(PngHeader((2, 1)), [[0] * 8], animation=PngAnimation(frames=[
        PngFrame(PngFrameControl((1, 1), offset=(1, 0)), [[255] * 4]),
    ]))
    image.validate()
    assert image.animation.num_frames == 1
    image.animation.frames[0].control.offset_x = 2
    with pytest.raises(PngValidationError):
        image.validate()


def test_animation_frames_inherit_sample_format() -> None:
    image = PngImage(
        PngHeader((1, 1), bit_depth=2, color_type=PngColorType.GRAYSCALE), [[3]],
        animation=PngAnimation(frames=[PngFrame(PngFrameControl((1, 1)), [[4]])]),
    )
    with pytest.raises(PngValidationError):
        image.validate()


def test_frame_delay_preserves_zero_denominator() -> None:
    control = PngFrameControl((1, 1), delay_num=3, delay_den=0)
    assert control.delay == Fraction(3, 100)
    assert control.delay_den == 0
    control.delay_num = 0
    assert control.delay == 0
    control.delay_den = 60
    control.delay_num = 1
    assert control.delay == Fraction(1, 60)


@pytest.mark.parametrize(('field', 'value'), [
    ('width', 0), ('height', -1), ('offset_x', -1), ('offset_y', 1),
    ('delay_num', 65536), ('delay_den', -1), ('dispose_op', 3), ('blend_op', 2),
])
def test_frame_validation(field: str, value: int) -> None:
    control = PngFrameControl((1, 1))
    setattr(control, field, value)
    with pytest.raises(PngValidationError):
        control.validate((1, 1))


def test_invalid_animation_structure() -> None:
    with pytest.raises(PngValidationError):
        PngAnimation().validate((2, 2))
    with pytest.raises(PngValidationError):
        PngAnimation(default_image_control=PngFrameControl((1, 1))).validate((2, 2))
    with pytest.raises(PngValidationError):
        PngAnimation(num_plays=-1, default_image_control=PngFrameControl((2, 2))).validate((2, 2))


def test_ancillary_data_has_no_duplicate_image_structure() -> None:
    image = PngImage(PngHeader((1, 1)), [[0] * 4], ancillary_chunks=[PngChunk(b'tEXt', b'Title\0Test')])
    image.validate()
    image.ancillary_chunks.append(PngChunk(b'tRNS'))
    with pytest.raises(PngValidationError):
        image.validate()
