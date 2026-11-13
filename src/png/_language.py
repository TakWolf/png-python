"""BCP 47 structure and registered subtags for PNG iTXt language tags.

Case and deprecated spellings remain unchanged in the public model. Extension
payload semantics (such as Unicode locale keys) belong to their own standards.
"""

from png._language_data import EXTLANG_PREFIXES, EXTENSION_SINGLETONS, GRANDFATHERED, RANGES, SUBTAGS
from png.error import PngValidationError


def _registered(kind: str, value: str) -> None:
    if value in SUBTAGS[kind]:
        return
    if any(len(value) == len(first) and first <= value <= last for first, last in RANGES[kind]):
        return
    raise PngValidationError(f'unregistered language tag {kind} subtag: {value!r}')


def validate_language_tag(encoded: bytes) -> None:
    if not encoded:
        return  # PNG's explicit unspecified-language representation.
    parts = encoded.decode('ascii').lower().split('-')
    if any(not 1 <= len(part) <= 8 or not part.isalnum() for part in parts):
        raise PngValidationError('invalid language tag syntax')
    if '-'.join(parts) in GRANDFATHERED:
        return
    if parts[0] == 'x' and len(parts) > 1:
        return
    language = parts[0]
    if not language.isalpha() or not 2 <= len(language) <= 8:
        raise PngValidationError('invalid language tag primary language')
    _registered('language', language)
    index = 1
    if len(language) <= 3 and index < len(parts) and len(parts[index]) == 3 and parts[index].isalpha():
        # The second and third extlang positions are permanently reserved.
        if EXTLANG_PREFIXES.get(parts[index]) != language:
            raise PngValidationError('language tag extlang must have its registered language prefix')
        index += 1
    if index < len(parts) and len(parts[index]) == 4 and parts[index].isalpha():
        _registered('script', parts[index])
        index += 1
    if index < len(parts) and ((len(parts[index]) == 2 and parts[index].isalpha()) or
                               (len(parts[index]) == 3 and parts[index].isdigit())):
        _registered('region', parts[index])
        index += 1
    variants = set()
    while index < len(parts):
        value = parts[index]
        if not (5 <= len(value) <= 8 or (len(value) == 4 and value[0].isdigit())):
            break
        _registered('variant', value)
        if value in variants:
            raise PngValidationError('duplicate language tag variant')
        variants.add(value)
        index += 1
    extensions = set()
    while index < len(parts) and len(parts[index]) == 1 and parts[index] != 'x':
        value = parts[index]
        if value not in EXTENSION_SINGLETONS:
            raise PngValidationError('unregistered language tag extension singleton')
        if value in extensions:
            raise PngValidationError('duplicate language tag extension singleton')
        extensions.add(value)
        index += 1
        start = index
        while index < len(parts) and len(parts[index]) >= 2:
            index += 1
        if index == start:
            raise PngValidationError('language tag extension requires a value')
    if index < len(parts) and parts[index] == 'x' and index + 1 < len(parts):
        return
    if index != len(parts):
        raise PngValidationError('invalid language tag subtag order or incomplete private use')
