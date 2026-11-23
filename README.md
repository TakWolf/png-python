# PNG - Python

[![Python](https://img.shields.io/badge/python-3.10-brightgreen?style=flat-square)](https://www.python.org)
[![PyPI](https://img.shields.io/pypi/v/png?style=flat-square)](https://pypi.org/project/png/)

Pure Python Implementation of [Portable Network Graphics (PNG) Specification and Extensions](https://www.libpng.org/pub/png/spec/),
with PNG/APNG reading, editing, writing, and image construction.

## Installation

```shell
pip install png
```

## Tutorial

Use `PngImage` for decoded pixels, palettes, metadata, and animation. Use
`PngDocument` for an ordered list of raw chunks when editing a file without
re-encoding its pixel data. Objects expose mutable attributes; construct or edit
them directly, then call `save()` or `dump_to_bytes()` to write the result.

### Create an RGBA image

This example creates a 2 × 2 image containing red, green, blue, and a partially
transparent white pixel:

```python
from png import PngHeader, PngImage

image = PngImage(
    header=PngHeader(dimensions=(2, 2)),  # RGBA, 8 bits per sample by default
    bitmap=[
        [255, 0, 0, 255, 0, 255, 0, 255],
        [0, 0, 255, 255, 255, 255, 255, 128],
    ],
)
image.save('created.png')
```

`bitmap` is a list of rows, from top to bottom. Each row is a flat list of integer
samples, from left to right; RGBA pixels use `[r, g, b, a, ...]`. Alpha is straight
(unassociated): zero is transparent and the maximum sample value is opaque.

| `PngColorType` | Samples per pixel | Supported bit depths |
| --- | --- | --- |
| `GRAYSCALE` | Gray | 1, 2, 4, 8, 16 |
| `TRUECOLOR` | R, G, B | 8, 16 |
| `INDEXED_COLOR` | Palette index | 1, 2, 4, 8 |
| `GRAYSCALE_ALPHA` | Gray, Alpha | 8, 16 |
| `TRUECOLOR_ALPHA` | R, G, B, Alpha | 8, 16 |

Every row has `width * header.channels` integers. Color samples range from zero
to `(1 << bit_depth) - 1`; palette indices select entries from `image.palette`.
Decoded samples retain the stored bit depth, including 16-bit values.

For large images, `PngImage.load(path, compact=True)`, `parse(data, compact=True)`
and `from_document(document, compact=True)` store rows in mutable compact
containers: `bytearray` for 1–8-bit samples and `array('H')` for 16-bit samples.
Low-depth samples remain unpacked, one integer per sample. APNG local frames
use the same storage. The default remains a list of integer lists.

Compact rows support integer indexing and mutation. Their slice assignment
follows the container's own rules (`bytes`/`bytearray` for `bytearray`, and a
matching array for `array('H')`); use `list(row)` when a plain list is needed.
16-bit integers retain their numeric value on every host; the library handles
PNG's big-endian encoding. Saving never swaps the source array in place.
`deepcopy()` makes independent rows, while constructors retain supplied rows.
RGBA conversion and rendered snapshots continue to return independent list rows.
The exported `PngRow` and `PngBitmap` aliases describe the supported containers.

### Read and modify pixels

Continue with `created.png` from the previous example:

```python
from png import PngImage

image = PngImage.load('created.png')
print(image.dimensions)  # (2, 2)
print(image.header.bit_depth)  # 8
print(image.bitmap[0][:4])  # [255, 0, 0, 255]

# Replace the top-left RGBA pixel with opaque yellow.
image.bitmap[0][0:4] = [255, 255, 0, 255]
image.save('edited.png')
```

For other files, inspect `header.color_type` and `header.channels` before editing
samples. Changing the header's dimensions or color type also requires updating
the bitmap and any dependent palette, transparency, or animation data. Saving
validates the current model and re-encodes its samples.

### Convert to RGBA

`to_rgba()` returns an independent static RGBA copy of the default image:

```python
from png import PngImage

image = PngImage.load('created.png')
rgba = image.to_rgba()  # Preserve 16-bit samples; expand other inputs to RGBA8
rgba.save('rgba.png')

rgba8 = image.to_rgba(bit_depth=8)  # Explicitly scale 16-bit samples to 8 bits
rgba16 = image.to_rgba(bit_depth=16)
```

Palette entries and tRNS become alpha samples. Transparency is matched at the
original precision before scaling; explicit bit-depth changes use integer
rounding on straight color and alpha samples. The source image is unchanged.

The result copies applicable color descriptions and pHYs independently; it omits
other metadata, including palette-dependent records. Grayscale ICC profiles are
omitted because they cannot describe RGB samples. No color-space transform or
tone mapping is performed. For APNG, this converts the default image (which may
be a separate poster) and omits animation; use `render_frames()` for composited
animation snapshots.

### Work with bytes and streams

The same interfaces are available on `PngImage` and `PngDocument`:

| Input/output | Read | Write |
| --- | --- | --- |
| File path | `load(path)` | `save(path)` |
| Binary stream | `parse(stream)` | `dump(stream)` |
| Bytes | `parse(data)` | `dump_to_bytes()` |

```python
from io import BytesIO
from png import PngImage

image = PngImage.load('created.png')
data = image.dump_to_bytes()
restored = PngImage.parse(data)

stream = BytesIO()
restored.dump(stream)
stream.seek(0)
restored = PngImage.parse(stream)
```

`load()` reads a complete file and rejects content after IEND. `parse()` reads
one PNG and stops at IEND, leaving any following bytes in a caller-owned stream.
Neither `parse()` nor `dump()` closes that stream.

### Create grayscale and indexed images

Grayscale uses one sample per pixel. This example stores four 2-bit values:

```python
from png import PngColorType, PngHeader, PngImage

gray = PngImage(
    PngHeader((4, 1), bit_depth=2, color_type=PngColorType.GRAYSCALE),
    bitmap=[[0, 1, 2, 3]],
    transparent_color=(0,),  # Optional tRNS: gray zero is fully transparent
)
gray.save('gray.png')
```

For indexed images, `bitmap` contains indices and `palette` contains 8-bit RGB
triples. `palette_alpha` supplies optional 8-bit alpha values; omitted entries
are opaque:

```python
from png import PngColorType, PngHeader, PngImage

indexed = PngImage(
    PngHeader((3, 1), bit_depth=2, color_type=PngColorType.INDEXED_COLOR),
    bitmap=[[0, 1, 2]],
    palette=[(255, 0, 0), (0, 255, 0), (0, 0, 255)],
    palette_alpha=[255, 128, 0],
)
indexed.recalculate_histogram()  # Optional: create/update hIST from used indices
indexed.save('indexed.png')
```

`transparent_color` can also hold an RGB triple for a truecolor image. Images
with an alpha channel store transparency in their samples instead of tRNS.

For reference samples whose depth cannot be stored directly in PNG, use the
source-depth factory:

```python
from png import PngColorType, PngImage

scaled = PngImage.from_samples(
    dimensions=(3, 1),
    bitmap=[[0, 2048, 4095]],
    sample_depth=12,
    color_type=PngColorType.GRAYSCALE,
)
print(scaled.header.bit_depth)  # 16
print(scaled.find_metadata(b'sBIT')[0].bits)  # (12,)
scaled.save('scaled.png')
```

The factory scales into the smallest legal PNG depth and records the original
depth in sBIT. A tuple such as `(10, 10, 10, 8)` specifies separate RGBA source
depths. Palette indices use the ordinary constructor and are never scaled as
intensities.

### Add and edit metadata

Metadata objects live in `image.metadata`. Unicode text uses iTXt:

```python
from png import PngGamma, PngImage, PngInternationalText, PngText

image = PngImage.load('created.png')
image.metadata.extend(
    [
        PngText('Author', 'Example'),
        PngInternationalText(
            keyword='Description',
            text='Image description',
            language_tag='en',
            translated_keyword='Description',
            compressed=True,
        ),
        PngGamma(45455),  # Stored integer; gamma is exactly 45455/100000
    ]
)
image.save('with-metadata.png')

loaded = PngImage.load('with-metadata.png')
for entry in loaded.find_metadata(b'iTXt'):
    print(entry.keyword, entry.text, entry.language_tag)
    entry.text = 'Updated description'
loaded.save('updated-metadata.png')
```

`find_metadata()` returns references to the matching objects. Modify an existing
singleton such as gAMA rather than appending a duplicate. Remove an entry with
`image.metadata.remove(entry)`. Other structured types include color descriptions,
physical dimensions, timestamps, background colors, significant bits, and
suggested palettes.

To embed an existing ICC profile, supply its original bytes. This example needs
an RGB profile in `profile.icc`, because `created.png` is RGBA:

```python
from pathlib import Path
from png import PngIccProfile, PngImage

image = PngImage.load('created.png')
profile = PngIccProfile('RGB profile', Path('profile.icc').read_bytes())
profile.validate_profile_tags()
image.metadata.append(profile)
image.save('with-profile.png')
```

Exif similarly uses `PngExif(profile_bytes)`. Its bytes start with the TIFF
header (`II` or `MM`), without a JPEG APP1 marker or `Exif\0\0` prefix. ICC and
Exif bytes are preserved; their supported structure and field checks run before
PNG output. Exif thumbnails are retained as metadata, without JPEG/TIFF image
decoding or automatic application of historical orientation.

For a consumer that processes color descriptions, select only the formats and
parameter values it understands:

```python
from png import PngCicp, PngImage

image = PngImage.load('created.png')
image.metadata.append(PngCicp(1, 13))  # BT.709 primaries, sRGB transfer function
selected = image.select_color_metadata([b'cICP', b'sRGB', b'gAMA', b'cHRM'])
print([entry.type for entry in selected])  # [b'cICP']
```

Selection follows `cICP`, `iCCP`, `sRGB`, then `gAMA`/`cHRM` precedence and returns
independent copies. It does not transform pixel samples or tone-map HDR content.
PNG writers reject CICP code points reserved by the referenced H.273 (07/2024)
specification; `PngCicp.validate_code_points()` also exposes that check.

### Create and inspect an APNG

The default image can also be the first animation frame. Here a red canvas is
followed by a local blue pixel blended into its top-right corner:

```python
from png import (
    PngAnimation,
    PngBlendOp,
    PngDisposeOp,
    PngFrame,
    PngFrameControl,
    PngHeader,
    PngImage,
)

image = PngImage(
    PngHeader((2, 1)),
    bitmap=[[255, 0, 0, 255, 255, 0, 0, 255]],
    animation=PngAnimation(
        num_plays=0,  # Repeat indefinitely
        default_image_control=PngFrameControl((2, 1), delay_num=1, delay_den=2),
        frames=[
            PngFrame(
                control=PngFrameControl(
                    dimensions=(1, 1),
                    offset=(1, 0),
                    delay_num=1,
                    delay_den=2,
                    blend_op=PngBlendOp.OVER,
                    dispose_op=PngDisposeOp.PREVIOUS,
                ),
                bitmap=[[0, 0, 255, 128]],
            )
        ],
    ),
)
image.save('animated.png')

loaded = PngImage.load('animated.png')
print(loaded.animation.num_frames)  # 2
for number, rendered in enumerate(loaded.render_frames()):
    print(number, rendered.delay)  # Fraction(1, 2) seconds per frame
    rendered.image.save(f'frame-{number}.png')
```

`default_image_control=None` makes `image.bitmap` a separate static fallback;
all animation frames then belong in `animation.frames`. Every frame uses the
image's color type, bit depth, and palette. Frame dimensions and offsets describe
a rectangle within the canvas.

`render_frames()` yields independent full-canvas RGBA snapshots for one play,
with exact fractional delays. It does not wait or expand `num_plays` into loops.
Snapshots inherit applicable color descriptions and pHYs as independent copies;
physical pixel dimensions do not resample the stored canvas coordinates.

### Choose interlacing, filtering, and compression

```python
from png import PngCompressionStrategy, PngFilterType, PngImage, PngInterlaceMethod

image = PngImage.load('created.png')
image.header.interlace_method = PngInterlaceMethod.ADAM7
image.save(
    'interlaced.png',
    filter_type=PngFilterType.PAETH,
    compression_level=9,
    compression_strategy=PngCompressionStrategy.FILTERED,
    idat_chunk_size=32 * 1024,
)
```

The default `filter_type=None` selects filters adaptively for 8/16-bit direct-color
images; indexed and low-bit-depth images use `PngFilterType.NONE`.
Compression levels range from 0 to 9; they change encoding size and cost without
changing pixel values. `idat_chunk_size` controls how compressed data is split
into IDAT/fdAT chunks. The same options work with `to_document()`, `dump()`, and
`dump_to_bytes()`.

`compression_strategy` defaults to `PngCompressionStrategy.DEFAULT`. Other
choices are `FILTERED`, `HUFFMAN_ONLY`, `RLE`, and `FIXED`; they tune compression
of the default image and every APNG frame without changing pixel values. Try
`FILTERED` for filtered image data or `RLE` for runs of repeated bytes, and
compare file size and encoding time for your images. This option is independent
of `filter_type` and does not change compression of text or ICC metadata.

### Inspect or edit raw chunks

```python
from png import PngDocument, PngImage, PngText

document = PngDocument.load('created.png')
for chunk in document.chunks:
    print(chunk.type, chunk.length, f'{chunk.crc:08x}', chunk.safe_to_copy)

# Add a text chunk immediately before IEND; keep existing IDAT bytes intact.
document.chunks.insert(-1, PngText('Comment', 'Added without pixel re-encoding').to_chunk())
document.save('chunk-edited.png')

# Convert between raw chunks and decoded samples explicitly.
image = PngImage.from_document(document)
reencoded_document = image.to_document()
```

`document.find_chunks(b'IDAT')` returns matching chunk objects in file order.
Use a metadata type's `from_chunk()` / `to_chunk()` methods for structured edits.
Document validation checks structure and supported metadata without decoding the
pixel streams; loading `PngImage` also decodes the default image and APNG frames.

Unknown ancillary chunks retain their payloads. Editing critical chunks causes
unknown unsafe-to-copy chunks to be omitted, and placement rules still apply.
Re-encoding through `PngImage` also applies those copy rules. CRCs are checked on
read and recomputed on write.

### Set read limits and handle errors

```python
from png import PngError, PngImage, PngLimitError, PngReadLimits

limits = PngReadLimits(
    max_chunk_bytes=16 * 1024 * 1024,
    max_total_bytes=64 * 1024 * 1024,
    max_chunks=10000,
    max_pixels=4_000_000,
    max_total_pixels=16_000_000,
    max_frames=100,
    max_metadata_bytes=4 * 1024 * 1024,
    max_row_bytes=1024 * 1024,
    max_decoded_bytes=128 * 1024 * 1024,
)
try:
    image = PngImage.load('created.png', limits=limits)
except PngLimitError as error:
    print(error.limit, error.maximum, error.actual)
except PngError as error:
    print(f'PNG processing failed: {error}')
```

`PngError` is the common PNG exception base; filesystem errors use ordinary
`OSError`. `PngLimitError` reports an application policy limit, so the input may
still be valid. Omitting `limits` adds no application caps. These limits count
data sizes, not total Python memory usage. Invalid edited models raise
`PngValidationError`; unsupported profile features raise `PngUnsupportedError`.

`max_row_bytes` limits packed sample bytes in each actual scanline/pass,
excluding its filter byte. `max_decoded_bytes` limits total decompressed scanline
bytes, including filter bytes, across the default image and additional APNG
frames. Both are checked from dimensions before pixel decompression.

## Format and validation details

All standard PNG color types and bit depths, the five scanline filters, and
Adam7 are supported. APNG includes local frames, timing, default-image fallback,
and composition in the stored sample space.

ICC profiles expose derived `color_space` and `declared_size` fields. Readers
check their header and RGB/grayscale match with the PNG, preserving opaque
payloads for inspection. PNG file and image writers additionally check ICC
length/tag boundaries, selected ICC tag contents and required tags, and Exif
TIFF directory/value and strip/tile payload boundaries, text encodings, and selected
present Exif fields before writing. Errors leave the model and
output file unchanged. Unsupported ICC major versions, inner curve segment or
embedded description encodings, and Exif field types whose sizes are unsupported raise
`PngUnsupportedError`.

`PngIccProfile.validate_profile_structure()` and
`PngExif.validate_profile_structure()` expose the boundary checks explicitly.
`PngExif.validate_profile_tags()` adds selected present-field checks to its
structure checks. `PngIccProfile.validate_profile_tags()` adds header field and Profile ID checks,
common and class-specific required tags for ICC v2/v4, selected
curve, XYZ, matrix and text checks, and the `mft1`, `mft2`, `mAB` and `mBA` LUT
layouts and channel counts. It also checks multi-process element tables, channel
chains, matrices, CLUTs, segmented curves, float32 encodings, named-color records,
profile-sequence descriptions, identifier records and colorant tables. Colorant
tables require unique ASCII names with zero unused bytes; v4 `clrt`/`clot`
counts match the input/output color channels, and `clot` requires DeviceLink.
Identifier descriptions are
bounded by their individual records; shared records and different storage orders
are supported. Their IDs identify component profiles and are not compared with
the containing profile's ID. Unknown processing
elements retain their common headers and opaque payloads; a color processor must
use the ICC fallback rules for them. PNG writers also reject DeviceLink and
Abstract profiles, which cannot be embedded in images. These checks do not
evaluate transforms or validate every conditional requirement or full color
semantics. Exif checks include standard field layouts, selected closed choices,
text and variable-length formats, and cross-directory dependencies. Private
payload meanings and thumbnail pixels are not decoded.
Basic model validation and individual chunk serialization retain their inspection
role; they do not certify a whole PNG or a complete external profile.

Profile IDs may be zero (not calculated); present IDs use the ICC-defined MD5
calculation, including the v2 backport recommended by ICC. Validation preserves
the payload and does not repair IDs or change embedding flags.

V2 tag requirements follow ICC.1:2001-04 (profile version 2.4). V2 RGB display
profiles retain their matrix/TRC requirements when optional LUTs are present;
v4 also permits a LUT-only display model. Earlier v2 revisions' optional-tag
restrictions are not reproduced individually.

International text language tags are checked against RFC 5646 structure and
bundled IANA registrations, with offline snapshots dated 2026-09-17 (subtags)
and 2014-04-02 (extension singletons). Original case, deprecated registrations,
grandfathered tags, and private-use tags are preserved. Extension-specific
settings such as Unicode locale keys are not interpreted. See the
[registry sources and maintenance notes](assets/iana/README.md).

The public extensions `oFFs`, `pCAL`, `sCAL`, `gIFg`, `gIFx`, and `sTER` also
have structured models in `image.metadata`:

```python
from png import PngImage, PngOffset, PngOffsetUnit, PngPhysicalScale

image = PngImage.load('created.png')
image.metadata.append(PngOffset((-100, 200), PngOffsetUnit.MICROMETRE))
image.metadata.append(PngPhysicalScale('1.234567890123456789e-6', '1e-6'))
image.save('with-scale.png')
```

Calibration parameters and physical scales retain decimal strings without
conversion to binary floats. GIF compatibility metadata does not animate a PNG;
stereo metadata describes existing side-by-side pixels. These extensions follow
the pinned [1.6.1 editor's draft](https://github.com/w3c/png/blob/41ed1959e42c2f22706b98681b37769e00bab233/extensions/Overview.html),
separately from the PNG Third Edition Recommendation.

ICC v4 checks include the defined `tech` technology signatures and the `prmg`
reference-gamut value for `rig0`/`rig2`. Nonzero CMM, manufacturer/model, and
`ICCHDAT` reference names use the bundled official registry snapshot dated
2026-11-16. Unknown or ambiguous registrations raise `PngUnsupportedError`;
creator registration is advisory. See the
[registry provenance](assets/icc/registry/README.md).

## Development

```shell
uv sync
uv run -m ruff check --fix
uv run -m ruff format
uv run -m pytest
```

## References

- [Portable Network Graphics (PNG) Specification and Extensions](https://www.libpng.org/pub/png/spec/)
- [Portable Network Graphics (PNG) Specification (Third Edition)](https://www.w3.org/TR/png-3/)
- [libpng - GitHub](https://github.com/pnggroup/libpng)
- [PngSuite](http://www.schaik.com/pngsuite/)
- [Web Platform Tests](https://github.com/web-platform-tests/wpt)
- [ICC registry](https://registry.color.org/)
- [Internet Assigned Numbers Authority (IANA)](https://www.iana.org/)

## License

[MIT License](LICENSE)
