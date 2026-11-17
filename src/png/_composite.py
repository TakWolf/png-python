from collections.abc import Iterator
from copy import deepcopy
from fractions import Fraction
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
    kind = image.header.color_type
    transparent = image.transparent_color
    if kind == PngColorType.TRUECOLOR_ALPHA:
        return [list(row) for row in bitmap]
    result = []
    if kind == PngColorType.INDEXED_COLOR:
        palette = image.palette
        alpha = image.palette_alpha
        # Build the table once, including implicit opaque palette entries.
        colors = [(*color, alpha[i] if i < len(alpha) else 255) for i, color in enumerate(palette)]
        for row in bitmap:
            result.append([sample for index in row for sample in colors[index]])
    elif kind in (PngColorType.GRAYSCALE, PngColorType.GRAYSCALE_ALPHA):
        has_alpha = kind == PngColorType.GRAYSCALE_ALPHA
        for row in bitmap:
            gray = row[0::2] if has_alpha else row
            if maximum != source_maximum:
                gray = [sample * maximum // source_maximum for sample in gray]
            output = [maximum] * (len(gray) * 4)
            for channel in range(3):
                output[channel::4] = gray
            if has_alpha:
                output[3::4] = row[1::2]
            elif transparent is not None:
                # Match in source precision, before low-depth expansion.
                output[3::4] = [0 if sample == transparent[0] else maximum for sample in row]
            result.append(output)
    else:
        for row in bitmap:
            output = [maximum] * (len(row) // 3 * 4)
            for channel in range(3):
                output[channel::4] = row[channel::3]
            if transparent is not None:
                red, green, blue = transparent
                output[3::4] = [
                    0 if row[i] == red and row[i + 1] == green and row[i + 2] == blue else maximum
                    for i in range(0, len(row), 3)
                ]
            result.append(output)
    return result


def _rgba_image(image: 'PngImage', bitmap: list[list[int]], depth: int) -> 'PngImage':
    """Build a static snapshot with independently copied, applicable metadata."""
    from png.image import PngImage

    metadata_types = COLOR_METADATA_TYPES | {b'pHYs'}
    if image.header.color_type in (PngColorType.GRAYSCALE, PngColorType.GRAYSCALE_ALPHA):
        # An ICC profile for gray samples cannot describe an RGB(A) snapshot.
        # Profile conversion belongs to the separate color-management layer.
        metadata_types = metadata_types - {b'iCCP'}

    return PngImage(
        PngHeader(image.dimensions, depth),
        bitmap,
        ancillary_chunks=[
            PngChunk(chunk.type, chunk.data) for chunk in image.ancillary_chunks if chunk.type in metadata_types
        ],
        metadata=[deepcopy(item) for item in image.metadata if item.type in metadata_types],
    )


def render_frames(image: 'PngImage') -> Iterator[PngRenderedFrame]:
    depth = 16 if image.header.bit_depth == 16 else 8
    maximum = (1 << depth) - 1
    width, height = image.dimensions

    if image.animation is None:
        yield PngRenderedFrame(_rgba_image(image, _rgba_rows(image, image.bitmap, depth), depth), Fraction(0))
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
            previous = [canvas[y][start:end] for y in range(control.offset_y, control.offset_y + control.height)]
        for row_index, source in enumerate(rows):
            target = canvas[control.offset_y + row_index]
            for index in range(0, len(source), 4):
                position = start + index
                red, green, blue, alpha = source[index : index + 4]
                if control.blend_op == PngBlendOp.SOURCE:
                    target[position : position + 4] = [red, green, blue, alpha]
                elif alpha:
                    destination_alpha = target[position + 3]
                    alpha_numerator = alpha * maximum + destination_alpha * (maximum - alpha)
                    for channel, value in enumerate((red, green, blue)):
                        numerator = value * alpha * maximum + target[position + channel] * destination_alpha * (
                            maximum - alpha
                        )
                        target[position + channel] = (numerator + alpha_numerator // 2) // alpha_numerator
                    target[position + 3] = (alpha_numerator + maximum // 2) // maximum
        yield PngRenderedFrame(_rgba_image(image, [row.copy() for row in canvas], depth), control.delay)
        for row_index in range(control.height):
            target = canvas[control.offset_y + row_index]
            if disposal == PngDisposeOp.BACKGROUND:
                target[start:end] = [0] * (control.width * 4)
            elif disposal == PngDisposeOp.PREVIOUS:
                target[start:end] = previous[row_index]
