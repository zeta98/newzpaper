import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from newzpaper.agent_fetch import _extract_json_array  # noqa: E402


class ExtractJsonArrayTests(unittest.TestCase):
    def test_single_clean_array(self):
        text = '[{"a": 1}, {"a": 2}]'
        self.assertEqual(_extract_json_array(text), [{"a": 1}, {"a": 2}])

    def test_array_wrapped_in_markdown_fence_and_prose(self):
        text = 'Aca esta el resultado:\n```json\n[{"a": 1}]\n```\nListo.'
        self.assertEqual(_extract_json_array(text), [{"a": 1}])

    def test_incidental_empty_array_before_real_array(self):
        # An "[]" mentioned in leading prose must not short-circuit extraction of
        # the real array that follows -- this is the regression from commit b9b6d99.
        text = 'Grupos sin novedades: [].\n[{"a": 1}, {"a": 2}]'
        self.assertEqual(_extract_json_array(text), [{"a": 1}, {"a": 2}])

    def test_bracket_inside_string_value_is_not_a_new_array(self):
        text = '[{"text": "Resultado [3-2] favorable"}]'
        self.assertEqual(_extract_json_array(text), [{"text": "Resultado [3-2] favorable"}])

    def test_trailing_prose_with_brackets_does_not_break_greedy_match(self):
        text = '[{"a": 1}]\nNota: no encontre nada para [@handle]'
        self.assertEqual(_extract_json_array(text), [{"a": 1}])

    def test_multiple_top_level_arrays_are_concatenated(self):
        text = '[{"a": 1}]\nsome separator text\n[{"a": 2}]'
        self.assertEqual(_extract_json_array(text), [{"a": 1}, {"a": 2}])

    def test_no_array_returns_empty_list(self):
        self.assertEqual(_extract_json_array("no json here"), [])

    def test_leading_json_object_without_brackets_does_not_interfere(self):
        text = '{"not": "a list"} [{"a": 1}]'
        self.assertEqual(_extract_json_array(text), [{"a": 1}])


if __name__ == "__main__":
    unittest.main()
