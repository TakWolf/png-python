from __future__ import annotations

from fractions import Fraction
from struct import pack, unpack
from typing import TYPE_CHECKING

from png._validation import check_integer
from png.chunk import PngChunk
from png.error import PngValidationError
from png.format import PngBlendOp, PngDisposeOp

if TYPE_CHECKING:
    from png.image import PngImage


class PngFrameControl:
    """Semantic fcTL fields. Sequence numbers are assigned during encoding."""

    width: int
    height: int
    offset_x: int
    offset_y: int
    delay_num: int
    delay_den: int
    dispose_op: PngDisposeOp
    blend_op: PngBlendOp

    def __init__(
            self,
            dimensions: tuple[int, int],
            offset: tuple[int, int] = (0, 0),
            delay_num: int = 1,
            delay_den: int = 10,
            dispose_op: PngDisposeOp = PngDisposeOp.NONE,
            blend_op: PngBlendOp = PngBlendOp.SOURCE,
    ) -> None:
        self.width, self.height = dimensions
        self.offset_x, self.offset_y = offset
        self.delay_num = delay_num
        self.delay_den = delay_den
        self.dispose_op = dispose_op
        self.blend_op = blend_op

    @property
    def dimensions(self) -> tuple[int, int]:
        return self.width, self.height

    @dimensions.setter
    def dimensions(self, value: tuple[int, int]) -> None:
        self.width, self.height = value

    @property
    def offset(self) -> tuple[int, int]:
        return self.offset_x, self.offset_y

    @offset.setter
    def offset(self, value: tuple[int, int]) -> None:
        self.offset_x, self.offset_y = value

    @property
    def delay(self) -> Fraction:
        """Display duration in seconds; a zero denominator means 100."""
        return Fraction(self.delay_num, self.delay_den or 100)

    @staticmethod
    def from_chunk(chunk: PngChunk) -> PngFrameControl:
        chunk.validate()
        if chunk.type != b'fcTL' or chunk.length != 26:
            raise PngValidationError('fcTL must contain 26 data bytes')
        _, width, height, x, y, numerator, denominator, disposal, blend = unpack('>IIIIIHHBB', chunk.data)
        control = PngFrameControl((width, height), (x, y), numerator, denominator, disposal, blend)
        control.validate((width + x, height + y))
        control.dispose_op = PngDisposeOp(disposal)
        control.blend_op = PngBlendOp(blend)
        return control

    def to_chunk(self, sequence_number: int) -> PngChunk:
        check_integer('sequence number', sequence_number, 0, 0x7FFFFFFF)
        self.validate((self.width + self.offset_x, self.height + self.offset_y))
        return PngChunk(b'fcTL', pack(
            '>IIIIIHHBB', sequence_number, self.width, self.height, self.offset_x, self.offset_y,
            self.delay_num, self.delay_den, self.dispose_op, self.blend_op,
        ))

    def validate(self, canvas: tuple[int, int]) -> None:
        for name, value in (('frame width', self.width), ('frame height', self.height)):
            check_integer(name, value, 1, 0x7FFFFFFF)
        for name, value in (('frame x offset', self.offset_x), ('frame y offset', self.offset_y)):
            check_integer(name, value, 0, 0x7FFFFFFF)
        if self.offset_x + self.width > canvas[0] or self.offset_y + self.height > canvas[1]:
            raise PngValidationError('frame rectangle must fit inside the canvas')
        check_integer('delay numerator', self.delay_num, 0, 65535)
        check_integer('delay denominator', self.delay_den, 0, 65535)
        for name, value, enum in (
                ('dispose operation', self.dispose_op, PngDisposeOp),
                ('blend operation', self.blend_op, PngBlendOp),
        ):
            check_integer(name, value, 0, 255)
            try:
                enum(value)
            except ValueError as error:
                raise PngValidationError(f'unsupported {name}: {value}') from error


class PngFrame:
    """A local animation frame with unpacked, interleaved sample rows."""

    control: PngFrameControl
    bitmap: list[list[int]]

    def __init__(self, control: PngFrameControl, bitmap: list[list[int]] | None = None) -> None:
        self.control = control
        self.bitmap = bitmap if bitmap is not None else []


class PngAnimation:
    """Animation frames following the default static image.

    If default_image_control is present, the default image is also the first
    animation frame. Its pixels live only in PngImage.bitmap. Otherwise the
    default image is a poster and every animation frame lives in frames.
    """

    num_plays: int
    default_image_control: PngFrameControl | None
    frames: list[PngFrame]

    def __init__(
            self,
            frames: list[PngFrame] | None = None,
            num_plays: int = 0,
            default_image_control: PngFrameControl | None = None,
    ) -> None:
        self.frames = frames if frames is not None else []
        self.num_plays = num_plays
        self.default_image_control = default_image_control

    @property
    def num_frames(self) -> int:
        return len(self.frames) + (self.default_image_control is not None)

    def validate(self, canvas: tuple[int, int]) -> None:
        check_integer('number of plays', self.num_plays, 0, 0x7FFFFFFF)
        check_integer('number of frames', self.num_frames, 1, 0x7FFFFFFF)
        if self.default_image_control is not None:
            self.default_image_control.validate(canvas)
            if (self.default_image_control.dimensions != canvas or
                    self.default_image_control.offset != (0, 0)):
                raise PngValidationError('the default frame must cover the entire canvas at offset (0, 0)')
        for frame in self.frames:
            frame.control.validate(canvas)


class PngRenderedFrame:
    """An independent full-canvas RGBA image and its exact display duration."""

    image: PngImage
    delay: Fraction

    def __init__(self, image: PngImage, delay: Fraction) -> None:
        self.image = image
        self.delay = delay
