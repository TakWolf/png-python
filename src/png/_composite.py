from collections.abc import Iterator
from fractions import Fraction
from copy import deepcopy
from typing import TYPE_CHECKING

from png.animation import PngRenderedFrame
from png.chunk import PngChunk
from png.format import PngBlendOp, PngColorType, PngDisposeOp
from png.header import PngHeader
from png.metadata import COLOR_METADATA_TYPES

if TYPE_CHECKING:
    from png.image import PngImage


def _rgba_rows(image: 'PngImage', bitmap: list[list[int]], depth: int) -> list[list[int]]:
    maximum = (1 << depth) - 1
    source_maximum = (1 << image.header.bit_depth) - 1
    channels = image.header.channels
    result = []
    for row in bitmap:
        output = []
        for index in range(0, len(row), channels):
            samples = tuple(row[index:index + channels])
            kind = image.header.color_type
            if kind == PngColorType.INDEXED_COLOR:
                palette_index = samples[0]
                red, green, blue = image.palette[palette_index]
                alpha = image.palette_alpha[palette_index] if palette_index < len(image.palette_alpha) else 255
            elif kind in (PngColorType.GRAYSCALE, PngColorType.GRAYSCALE_ALPHA):
                red = green = blue = samples[0] * maximum // source_maximum
                alpha = samples[1] if kind == PngColorType.GRAYSCALE_ALPHA else maximum
                if kind == PngColorType.GRAYSCALE and samples == image.transparent_color:
                    alpha = 0
            else:
                red, green, blue = samples[:3]
                alpha = samples[3] if kind == PngColorType.TRUECOLOR_ALPHA else maximum
                if kind == PngColorType.TRUECOLOR and samples == image.transparent_color:
                    alpha = 0
            output.extend((red, green, blue, alpha))
        result.append(output)
    return result


def render_frames(image: 'PngImage') -> Iterator[PngRenderedFrame]:
    from png.image import PngImage

    depth = 16 if image.header.bit_depth == 16 else 8
    maximum = (1 << depth) - 1
    width, height = image.dimensions
    metadata_types = COLOR_METADATA_TYPES | {b'pHYs'}
    if image.header.color_type in (PngColorType.GRAYSCALE, PngColorType.GRAYSCALE_ALPHA):
        # An ICC profile for gray samples cannot describe an RGB(A) snapshot.
        # Profile conversion belongs to the separate color-management layer.
        metadata_types = metadata_types - {b'iCCP'}

    def snapshot(bitmap: list[list[int]]) -> PngImage:
        return PngImage(
            PngHeader(image.dimensions, depth), bitmap,
            ancillary_chunks=[PngChunk(chunk.type, chunk.data) for chunk in image.ancillary_chunks
                              if chunk.type in metadata_types],
            metadata=[deepcopy(item) for item in image.metadata if item.type in metadata_types],
        )

    if image.animation is None:
        yield PngRenderedFrame(snapshot(_rgba_rows(image, image.bitmap, depth)), Fraction(0))
        return
    frames = [(frame.control, frame.bitmap) for frame in image.animation.frames]
    if image.animation.default_image_control is not None:
        frames.insert(0, (image.animation.default_image_control, image.bitmap))
    canvas = [[0] * (width * 4) for _ in range(height)]
    for frame_index, (control, bitmap) in enumerate(frames):
        rows = _rgba_rows(image, bitmap, depth)
        start, end = control.offset_x * 4, (control.offset_x + control.width) * 4
        disposal = control.dispose_op
        if frame_index == 0 and disposal == PngDisposeOp.PREVIOUS:
            disposal = PngDisposeOp.BACKGROUND
        previous = []
        if disposal == PngDisposeOp.PREVIOUS:
            previous = [canvas[y][start:end]
                        for y in range(control.offset_y, control.offset_y + control.height)]
        for row_index, source in enumerate(rows):
            target = canvas[control.offset_y + row_index]
            for index in range(0, len(source), 4):
                position = start + index
                red, green, blue, alpha = source[index:index + 4]
                if control.blend_op == PngBlendOp.SOURCE:
                    target[position:position + 4] = [red, green, blue, alpha]
                elif alpha:
                    destination_alpha = target[position + 3]
                    alpha_numerator = alpha * maximum + destination_alpha * (maximum - alpha)
                    for channel, value in enumerate((red, green, blue)):
                        numerator = value * alpha * maximum + target[position + channel] * destination_alpha * (maximum - alpha)
                        target[position + channel] = (numerator + alpha_numerator // 2) // alpha_numerator
                    target[position + 3] = (alpha_numerator + maximum // 2) // maximum
        yield PngRenderedFrame(snapshot([row.copy() for row in canvas]), control.delay)
        for row_index in range(control.height):
            target = canvas[control.offset_y + row_index]
            if disposal == PngDisposeOp.BACKGROUND:
                target[start:end] = [0] * (control.width * 4)
            elif disposal == PngDisposeOp.PREVIOUS:
                target[start:end] = previous[row_index]
