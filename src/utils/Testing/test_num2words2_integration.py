from __future__ import annotations

from importlib.metadata import distribution
from pathlib import Path
import sys


SOURCE_ROOT = Path(__file__).resolve().parents[2]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))


def test_num2words2_is_pinned_and_has_no_docopt_dependency() -> None:
    package = distribution("num2words2")

    assert package.version == "1.0.20"
    assert not any("docopt" in requirement.lower() for requirement in package.requires or ())


def test_num2words2_core_language_contract() -> None:
    from num2words2 import num2words

    assert num2words(21, lang="en") == "twenty-one"
    assert num2words(42, lang="ru") == "сорок два"
    assert num2words(-5, lang="en") == "minus five"


def test_replace_numbers_with_words_uses_num2words2_for_supported_languages() -> None:
    from utils import replace_numbers_with_words

    assert replace_numbers_with_words("I have 21 cats and -5 dogs.", lang="en") == (
        "I have twenty-one cats and minus five dogs."
    )
    assert replace_numbers_with_words("У меня 42 яблока.", lang="ru") == "У меня сорок два яблока."
    assert replace_numbers_with_words("Tenho 21 gatos.", lang="pt-br") == "Tenho vinte e um gatos."


def test_replace_numbers_with_words_falls_back_and_caches_repeated_numbers() -> None:
    from utils import replace_numbers_with_words

    assert replace_numbers_with_words("Value 7.", lang="unsupported") == "Value seven."
    assert replace_numbers_with_words("Номер 007 и 007.", lang="ru") == "Номер семь и семь."
