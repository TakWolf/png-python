from copy import deepcopy
import hashlib
import json
from pathlib import Path
import runpy
import zlib

import pytest

from png import PngChunk, PngDocument, PngImage, PngInternationalText, PngParseError, PngValidationError

# Fixed examples from PNG Third Edition 11.3.3.4 and RFC 5646 Appendix A.
_EXAMPLES = [
    '',
    'en',
    'en-GB',
    'es-419',
    'zh-Hans',
    'zh-Hans-CN',
    'tlh-Cyrl-AQ',
    'ar-AE-u-nu-latn',
    'x-private',
    'de',
    'fr',
    'ja',
    'i-enochian',
    'zh-Hant',
    'sr-Cyrl',
    'sr-Latn',
    'zh-cmn-Hans-CN',
    'cmn-Hans-CN',
    'zh-yue-HK',
    'yue-HK',
    'sr-Latn-RS',
    'sl-rozaj',
    'sl-rozaj-biske',
    'sl-nedis',
    'de-CH-1901',
    'sl-IT-nedis',
    'hy-Latn-IT-arevela',
    'de-DE',
    'en-US',
    'de-CH-x-phonebk',
    'az-Arab-x-AZE-derbend',
    'x-whatever',
    'qaa-Qaaa-QM-x-southern',
    'de-Qaaa',
    'sr-Latn-QM',
    'sr-Qaaa-RS',
    'en-US-u-islamcal',
]
_GRANDFATHERED = [
    'en-GB-oed',
    'i-ami',
    'i-bnn',
    'i-default',
    'i-enochian',
    'i-hak',
    'i-klingon',
    'i-lux',
    'i-mingo',
    'i-navajo',
    'i-pwn',
    'i-tao',
    'i-tay',
    'i-tsu',
    'sgn-BE-FR',
    'sgn-BE-NL',
    'sgn-CH-DE',
    'art-lojban',
    'cel-gaulish',
    'no-bok',
    'no-nyn',
    'zh-guoyu',
    'zh-hakka',
    'zh-min',
    'zh-min-nan',
    'zh-xiang',
]


@pytest.mark.parametrize('tag', _EXAMPLES)
@pytest.mark.parametrize('compressed', [False, True])
def test_specification_language_tag_examples(tag: str, compressed: bool) -> None:
    item = PngInternationalText('Description', '说明', tag, '说明', compressed)
    chunk = item.to_chunk()
    assert chunk.data.startswith(b'Description\0' + bytes([compressed, 0]) + tag.encode('ascii') + b'\0')
    restored = PngInternationalText.from_chunk(chunk)
    assert restored.language_tag == tag
    assert restored.text == '说明'
    assert restored.translated_keyword == '说明'


@pytest.mark.parametrize('tag', _GRANDFATHERED)
def test_all_fixed_grandfathered_tags_preserve_spelling(tag: str) -> None:
    # The fixed list is independent of the generated tables and their formatter.
    for spelling in (tag, tag.upper(), tag.lower()):
        item = PngInternationalText('K', 'text', spelling)
        assert PngInternationalText.from_chunk(item.to_chunk()).language_tag == spelling


@pytest.mark.parametrize(
    'tag',
    [
        'EN-latn-us',
        'iw',
        'ji',
        'in',
        'en-BU',  # Deprecated values remain valid.
        'qaa',
        'qtz',
        'en-Qaaa',
        'en-Qabx',
        'en-QM',
        'en-QZ',
        'en-XA',
        'en-XZ',
        'en-AA',
        'en-ZZ',
        'qtz-Qabx-XZ',
        'en-x-a-x-a',
        'x-a-a-a',
        'x-12345678',
        'X-u-ca-foo',
        'en-u-ca-gregory-t-en',
        'en-t-de-DE-u-ca-gregory',
        'en-x-Abcd-123-a',
        'de-1901-1996',
    ],
)
def test_case_deprecated_private_use_and_extension_sequences(tag: str) -> None:
    item = PngInternationalText('K', '', tag)
    assert PngInternationalText.from_chunk(item.to_chunk()).language_tag == tag


@pytest.mark.parametrize(
    'tag',
    [
        'a',
        'x',
        'i',
        'a-DE',
        'en-a',
        'en-u',
        'en-t',
        'en-x',
        'en-u-x-private',
        'en-t-u-ca-gregory',
        'de-419-DE',
        'en-US-Latn',
        'en-Latn-Cyrl',
        'en-US-US',
        'en--US',
        '-en',
        'en-',
        'en_US',
        'en US',
        ' en',
        'en\n',
        'ｅｎ',
        'en-中文',
        'en-123456789',
        'abcdefghi',
        'en-12',
        'en-1',
        'en-1234',
        'en-abcde-ABCDE',
        'sl-rozaj-ROZAJ',
        'en-u-ca-gregory-U-nu-latn',
        'en-t-en-T-de',
        'ar-a-aaa-b-bbb-a-ccc',
        'zz',
        'en-Abcd',
        'en-AB',
        'en-QB',
        'en-abcdef',
        'en-cmn',
        'zh-cmn-yue',
        'zh-cmn-yue-gan',
        'i-klingon-x-private',
        'en-GB-oed-extra',
        'en-a-myext',
        'en-0-myext',
    ],
)
def test_invalid_language_tags_are_rejected_when_reading_and_writing(tag: str) -> None:
    with pytest.raises(PngValidationError):
        PngInternationalText('K', 'text', tag).validate()
    for compressed in (False, True):
        text = zlib.compress(b'text') if compressed else b'text'
        data = b'K\0' + bytes([compressed, 0]) + tag.encode('utf-8') + b'\0\0' + text
        with pytest.raises(PngValidationError):
            PngInternationalText.from_chunk(PngChunk(b'iTXt', data))


def test_extension_payloads_are_separate_from_language_registry_checks() -> None:
    # t/u have registered authorities. Their payload semantics are not RFC 5646
    # subtag registry entries, and validating Unicode locale keys is separate.
    item = PngInternationalText('K', 'text', 'en-u-madeup')
    item.validate()
    assert PngInternationalText.from_chunk(item.to_chunk()).language_tag == 'en-u-madeup'


def test_mutation_does_not_canonicalize_or_change_other_metadata() -> None:
    item = PngInternationalText('K', 'text', 'iw')
    copied = deepcopy(item)
    copied.language_tag = 'HE-latn-il'
    copied.validate()
    assert item.language_tag == 'iw'
    assert copied.language_tag == 'HE-latn-il'


def test_invalid_tag_in_official_image_uses_parse_error(png_suite_dir: Path) -> None:
    document = PngDocument.load(png_suite_dir.joinpath('basn2c08.png'))
    document.chunks.insert(1, PngChunk(b'iTXt', b'K\0\0\0en-u\0\0text'))
    with pytest.raises(PngValidationError, match='language tag'):
        document.validate()
    data = b'\x89PNG\r\n\x1a\n' + b''.join(chunk.dump_to_bytes() for chunk in document.chunks)
    with pytest.raises(PngParseError, match='language tag'):
        PngImage.parse(data)


def test_official_image_keeps_repeated_language_metadata(png_suite_dir: Path) -> None:
    image = PngImage.load(png_suite_dir.joinpath('basn6a16.png'))
    image.metadata.extend(
        [
            PngInternationalText('Description', '中文', 'zh-Hans-CN', compressed=True),
            PngInternationalText('Description', 'Private', 'x-Owner-A'),
            PngInternationalText('Description', 'Old spelling', 'i-klingon'),
        ]
    )
    restored = PngImage.parse(image.dump_to_bytes())
    assert [entry.language_tag for entry in restored.find_metadata(b'iTXt')] == ['zh-Hans-CN', 'x-Owner-A', 'i-klingon']
    assert restored.bitmap == image.bitmap


def test_original_iana_snapshots_and_generated_module(project_root_dir: Path) -> None:
    directory = project_root_dir.joinpath('assets', 'iana')
    manifest = json.loads(directory.joinpath('SOURCE.json').read_text())
    assert [record['file_date'] for record in manifest['files']] == ['2026-09-17', '2014-04-02']
    for record in manifest['files']:
        data = directory.joinpath(record['path']).read_bytes()
        assert hashlib.sha256(data).hexdigest() == record['sha256']
        assert data.startswith(('File-Date: ' + record['file_date']).encode('ascii'))
    generator = runpy.run_path(str(project_root_dir.joinpath('tools', 'generate_language_registry.py')))
    assert generator['generate']() == project_root_dir.joinpath('src', 'png', '_language_data.py').read_text(
        encoding='utf-8'
    )


def test_every_registry_entry_can_be_used_in_its_registered_position(project_root_dir: Path) -> None:
    # Read raw records independently of the generator. This also detects values
    # split or lost when formatting the compact generated tables.
    source = project_root_dir.joinpath('assets', 'iana', 'language-subtag-registry.txt').read_text(encoding='utf-8')
    counts = {}
    for block in source.split('%%')[1:]:
        fields = {}
        for line in block.splitlines():
            if not line.startswith(' ') and ': ' in line:
                key, value = line.split(': ', 1)
                fields.setdefault(key, []).append(value)
        if not fields:
            continue
        kind = fields['Type'][0]
        value = fields.get('Subtag', fields.get('Tag'))[0]
        values = value.split('..') if '..' in value else [value]
        for value in values:
            if kind in ('language', 'grandfathered', 'redundant'):
                tag = value
            elif kind in ('script', 'region'):
                tag = 'en-' + value
            elif kind == 'variant':
                tag = fields.get('Prefix', ['en'])[0] + '-' + value
            else:
                assert kind == 'extlang'
                tag = fields['Prefix'][0] + '-' + value
            PngInternationalText('K', '', tag).validate()
        counts[kind] = counts.get(kind, 0) + 1
    assert counts == {
        'language': 8276,
        'extlang': 258,
        'script': 225,
        'region': 305,
        'variant': 139,
        'grandfathered': 26,
        'redundant': 67,
    }
