import pytest
from crossplay.engine.dictionary import Dictionary


@pytest.fixture
def tiny_dict(tmp_path):
    word_file = tmp_path / "words.txt"
    word_file.write_text("CAT\nCAR\nARC\nBAT\n")
    return Dictionary.load(str(word_file))


def test_valid_word_found(tiny_dict):
    assert tiny_dict.is_word("CAT")

def test_invalid_word_not_found(tiny_dict):
    assert not tiny_dict.is_word("XYZ")

def test_valid_prefix_recognized(tiny_dict):
    assert tiny_dict.is_prefix("CA")

def test_invalid_prefix_rejected(tiny_dict):
    assert not tiny_dict.is_prefix("ZZ")

def test_single_letter_not_a_word(tiny_dict):
    assert not tiny_dict.is_word("C")

def test_words_are_uppercase(tiny_dict):
    assert tiny_dict.is_word("CAT")
    assert not tiny_dict.is_word("cat")
