import unittest

from lr2nl.jstranslate import c_to_js, function_to_js
from lr2nl.yamlout import dump


class JsTranslateTests(unittest.TestCase):
    def test_declarations_and_string_helpers(self):
        js, left = c_to_js('char buf[64]; int n = atoi("3"); strcpy(buf, "a"); strcat(buf, "b"); sprintf(buf, "%d", n);')
        self.assertIn("var buf;", js)
        self.assertIn("var n = atoi", js)
        self.assertIn('buf = "a";', js)
        self.assertIn('buf += "b";', js)
        self.assertIn('buf = sprintf("%d", n);', js)
        self.assertEqual(left, [])

    def test_leftovers_are_reported(self):
        _js, left = c_to_js('web_url("x", LAST); memcpy(a, b, 3);')
        self.assertTrue(any("web_url" in item for item in left))
        self.assertTrue(any("memcpy" in item for item in left))

    def test_function_signature(self):
        js, _ = function_to_js("f", "int a, char *b, char c[10]", "return a;")
        self.assertTrue(js.startswith("function f(a, b, c) {"))


class YamlTests(unittest.TestCase):
    def test_nested_lists_comments_and_commented_blocks(self):
        text = dump({"steps": [{"__comment__": "note"}, {"delay": "1s"},
                               {"__commented__": [{"request": {"url": "/b"}}]}]})
        self.assertEqual(text, 'steps:\n  # note\n  - delay: "1s"\n  # - request:\n  #     url: "/b"\n')

    def test_scalars_are_quoted_safely(self):
        text = dump({"body": 'a: "b"\nc', "n": 3, "flag": True})
        self.assertIn('body: "a: \\"b\\"\\nc"', text)
        self.assertIn("n: 3", text)
        self.assertIn("flag: true", text)


if __name__ == "__main__":
    unittest.main()
