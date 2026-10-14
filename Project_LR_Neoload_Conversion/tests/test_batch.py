import csv
import os
import shutil
import tempfile
import time
import unittest

from lr2nl.converter import convert_batch, discover_scripts

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES = os.path.join(HERE, "..", "sample_data", "lr_scripts")


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="lr2nl_out_")
        self.addCleanup(shutil.rmtree, self.out, True)

    def test_sample_dataset(self):
        results = {r.name: r for r in convert_batch(SAMPLES, self.out)}
        self.assertEqual(set(results), {"WebShop_Login_Search", "Checkout_REST", "Legacy_Broken"})
        self.assertEqual(results["Legacy_Broken"].status, "FAILED")
        self.assertEqual(results["WebShop_Login_Search"].status, "PARTIAL")
        self.assertGreater(results["WebShop_Login_Search"].pct, 90)
        self.assertEqual(results["Checkout_REST"].status, "PARTIAL")
        for name in ("WebShop_Login_Search", "Checkout_REST"):
            self.assertTrue(os.path.isfile(os.path.join(self.out, name, "default.yaml")))
        self.assertTrue(os.path.isfile(os.path.join(self.out, "WebShop_Login_Search", "data", "users.csv")))
        self.assertTrue(os.path.isfile(os.path.join(self.out, "Checkout_REST", "custom_js", "Checkout_REST.js")))
        for report in ("conversion_summary.csv", "manual_review.csv", "conversion_report.html", "conversion_summary.json"):
            self.assertTrue(os.path.isfile(os.path.join(self.out, "reports", report)))
        with open(os.path.join(self.out, "reports", "conversion_summary.csv"), encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual({r["Status"] for r in rows}, {"PARTIAL", "FAILED"})

    def test_hundred_scripts_in_one_batch(self):
        src = tempfile.mkdtemp(prefix="lr2nl_src_")
        self.addCleanup(shutil.rmtree, src, True)
        for i in range(100):
            shutil.copytree(os.path.join(SAMPLES, "WebShop_Login_Search"), os.path.join(src, f"Script_{i:03d}"))
        self.assertEqual(len(discover_scripts(src)), 100)
        start = time.time()
        results = convert_batch(src, self.out, workers=4)
        self.assertEqual(len(results), 100)
        self.assertTrue(all(r.status == "PARTIAL" for r in results))
        self.assertLess(time.time() - start, 60)


if __name__ == "__main__":
    unittest.main()
