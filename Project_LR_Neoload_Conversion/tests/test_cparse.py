import unittest

from lr2nl.cparse import ParseError, literal_value, parse_c, split_args, strip_comments


class CParseTests(unittest.TestCase):
    def test_strip_comments_keeps_strings_and_lines(self):
        src = 'a(); // x\n/* y\n z */ b("// not a comment");'
        out = strip_comments(src)
        self.assertEqual(out.count("\n"), src.count("\n"))
        self.assertIn('"// not a comment"', out)
        self.assertNotIn("x", out.split("\n")[0])

    def test_split_args_respects_nesting_and_strings(self):
        self.assertEqual(split_args('"a,b", f(1, 2), LAST'), ['"a,b"', "f(1, 2)", "LAST"])

    def test_literal_concatenation_and_escapes(self):
        self.assertEqual(literal_value('"Body={\\"a\\":" "1}"'), 'Body={"a":1}')
        self.assertIsNone(literal_value("buf"))

    def test_function_and_calls(self):
        stmts = parse_c('Action()\n{\n  web_url("x", "URL=http://h/", LAST);\n  return 0;\n}\n')
        self.assertEqual(len(stmts), 1)
        fn = stmts[0]
        self.assertEqual((fn.kind, fn.name), ("func", "Action"))
        self.assertEqual(fn.body[0].kind, "call")
        self.assertEqual(fn.body[0].name, "web_url")
        self.assertEqual(fn.body[0].line, 3)

    def test_if_else_and_loops(self):
        body = parse_c("f(){ if (a == 1) { g(); } else h(); for (i=0;i<2;i++) k(); do { m(); } while (x); }")[0].body
        self.assertEqual([s.kind for s in body], ["if", "for", "do"])
        self.assertEqual(body[0].cond, "a == 1")
        self.assertEqual(body[0].orelse[0].name, "h")

    def test_assign_call_and_decl(self):
        body = parse_c("f(){ int rc; rc = web_url(\"a\", LAST); }")[0].body
        self.assertEqual(body[0].kind, "decl")
        self.assertEqual((body[1].kind, body[1].name, body[1].lhs), ("assign_call", "web_url", "rc"))

    def test_unbalanced_brace_raises(self):
        with self.assertRaises(ParseError):
            parse_c("Action() { if (1) { x(); return 0; }")


if __name__ == "__main__":
    unittest.main()
