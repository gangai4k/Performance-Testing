import os
import shutil
import tempfile
import textwrap
import unittest

from lr2nl.lrproject import load_script
from lr2nl.mapper import map_script


def make_script(files):
    d = tempfile.mkdtemp(prefix="lr2nl_")
    path = os.path.join(d, "Demo")
    os.makedirs(path)
    for name, content in files.items():
        with open(os.path.join(path, name), "w", encoding="utf-8") as fh:
            fh.write(textwrap.dedent(content))
    return path


def flat(steps):
    """All request/transaction/delay steps, depth first (comments excluded)."""
    for s in steps:
        if "transaction" in s:
            yield s
            yield from flat(s["transaction"]["steps"])
        elif "__commented__" not in s and "__comment__" not in s:
            yield s


class MapperTests(unittest.TestCase):
    def convert(self, action, **extra):
        files = {"Action.c": "Action()\n{\n" + textwrap.dedent(action) + "\nreturn 0;\n}\n"}
        files.update(extra)
        path = make_script(files)
        self.addCleanup(shutil.rmtree, os.path.dirname(path), True)
        return map_script(load_script(path))

    def test_request_with_correlation_and_check(self):
        m = self.convert('''
            web_reg_save_param("tok", "LB=id=\\"", "RB=\\"", LAST);
            web_reg_find("Text=Error", "Fail=Found", LAST);
            web_url("home", "URL=https://app.test:8443/a?b={p}", "Mode=HTML", LAST);
        ''')
        req = m.sections["actions"][0]["request"]
        self.assertEqual(req["url"], "/a?b=${p}")
        self.assertEqual(req["method"], "GET")
        self.assertEqual(req["extractors"][0]["name"], "tok")
        self.assertEqual(req["extractors"][0]["regexp"], '(?s)id="(.*?)"')
        self.assertEqual(req["assertions"], [{"not_contains": "Error"}])
        self.assertEqual(list(m.servers.values()), ["app_test"])
        self.assertIn(("https", "app.test", 8443), m.servers)
        # {p} is undefined -> flagged
        self.assertTrue(any(i.construct == "parameter" and "{p}" in i.message for i in m.issues))

    def test_transactions_nest_and_think_time(self):
        m = self.convert('''
            lr_start_transaction("T1");
            web_url("a", "URL=http://h/a", LAST);
            lr_think_time(2);
            lr_end_transaction("T1", LR_AUTO);
        ''')
        tx = m.sections["actions"][0]["transaction"]
        self.assertEqual(tx["name"], "T1")
        self.assertEqual([list(s)[0] for s in tx["steps"]], ["request", "delay"])
        self.assertEqual(tx["steps"][1]["delay"], "2s")
        self.assertEqual(m.tally.pct, 100.0)

    def test_submit_data_builds_form_body(self):
        m = self.convert('''
            web_submit_data("login", "Action=http://h/login", "Method=POST", ITEMDATA,
                "Name=user", "Value={UserName}", ENDITEM,
                "Name=q", "Value=a b&c", ENDITEM, LAST);
        ''')
        req = m.sections["actions"][0]["request"]
        self.assertEqual(req["body"], "user=${UserName}&q=a+b%26c")
        self.assertIn({"Content-Type": "application/x-www-form-urlencoded"}, req["headers"])

    def test_auto_header_and_next_header(self):
        m = self.convert('''
            web_add_auto_header("A", "1");
            web_add_header("B", "2");
            web_url("x", "URL=http://h/x", LAST);
            web_url("y", "URL=http://h/y", LAST);
        ''')
        h1 = m.sections["actions"][0]["request"]["headers"]
        h2 = m.sections["actions"][1]["request"]["headers"]
        self.assertEqual(h1, [{"A": "1"}, {"B": "2"}])
        self.assertEqual(h2, [{"A": "1"}])

    def test_if_else_with_requests_comments_else_branch(self):
        m = self.convert('''
            if (x > 0) {
                web_url("a", "URL=http://h/a", LAST);
            } else {
                web_url("b", "URL=http://h/b", LAST);
            }
        ''')
        steps = m.sections["actions"]
        active = [s["request"]["name"] for s in flat(steps) if "request" in s]
        self.assertEqual(active, ["a"])
        commented = [s for s in steps if "__commented__" in s]
        self.assertEqual(commented[0]["__commented__"][0]["request"]["name"], "b")
        self.assertTrue(any(i.construct == "if-flow" for i in m.issues))

    def test_unsupported_api_is_flagged_not_dropped(self):
        m = self.convert('''
            web_url("a", "URL=http://h/a", LAST);
            web_websocket_connect("ID=1", "URI=ws://h/", LAST);
        ''')
        self.assertTrue(any(i.construct == "web_websocket_connect" and i.severity == "REVIEW" for i in m.issues))
        self.assertLess(m.tally.pct, 100.0)

    def test_parameters_from_prm_share_one_file_variable(self):
        prm = '''
            [parameter:User]
            Type="Table"
            Table="users.dat"
            ColumnName="User"
            SelectNextRow="Sequential"
            [parameter:Pwd]
            Type="Table"
            Table="users.dat"
            ColumnName="Pwd"
            SelectNextRow="Same line as User"
        '''
        m = self.convert('web_url("a", "URL=http://h/a?u={User}&p={Pwd}", LAST);',
                         **{"Demo.prm": prm, "users.dat": "User,Pwd\nu1,p1\n"})
        files = [v["file"] for v in m.variables if "file" in v]
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0]["column_names"], ["User", "Pwd"])
        self.assertEqual(m.sections["actions"][0]["request"]["url"], "/a?u=${users.User}&p=${users.Pwd}")

    def test_helper_function_goes_to_js(self):
        m = self.convert('my_helper("x");', **{"helpers.c": "int my_helper(char *s)\n{\n  lr_output_message(\"%s\", s);\n  return 0;\n}\n"})
        js = "\n".join(m.js_chunks)
        self.assertIn("function my_helper(s)", js)
        self.assertTrue(any(i.construct == "custom-function-call" for i in m.issues))


if __name__ == "__main__":
    unittest.main()
