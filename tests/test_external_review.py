"""An external review (25.10): an unknown license read as open, and two items' clip.mp4 overwrote each other.
Red on 0.2.0."""
import hashlib
import json
import os
import sys
import tempfile
import unittest
from urllib.parse import urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import archive_broll as ab  # noqa: E402

A, B = b"item A video" * 20, b"item B video" * 20
PD = "https://creativecommons.org/publicdomain/mark/1.0/"
META = {
    "item-A": {"metadata": {"identifier": "item-A", "title": "A", "licenseurl": PD, "year": "1940"},
               "files": [{"name": "clip.mp4", "format": "h.264", "source": "derivative", "size": str(len(A)),
                          "md5": hashlib.md5(A).hexdigest()}]},
    "item-B": {"metadata": {"identifier": "item-B", "title": "B", "licenseurl": PD, "year": "1941"},
               "files": [{"name": "clip.mp4", "format": "h.264", "source": "derivative", "size": str(len(B)),
                          "md5": hashlib.md5(B).hexdigest()}]},
}


def net(url):
    u = urlparse(url)
    if u.path.startswith("/metadata/"):
        return json.dumps(META[u.path.split("/")[2]]).encode()
    if u.path.startswith("/download/"):
        return A if "/item-A/" in u.path else B
    raise AssertionError(url)


class ExternalReview(unittest.TestCase):
    def test_an_unknown_license_is_unknown_not_open(self):
        for url in ("https://creativecommons.org/licenses/not-a-real-license/4.0/",
                    "https://example.org/licenses/proprietary/1.0/",
                    "https://creativecommons.org/licenses/by/9.9/",
                    "https://creativecommons.org.evil.example/licenses/by/4.0/"):
            with self.subTest(url=url):
                self.assertEqual(ab.classify({"licenseurl": url}).kind, "unknown")
        self.assertEqual(ab.classify({"licenseurl": "creativecommons.org/licenses/by/4.0"}).kind, "open")
        # Tsaplya: userinfo before the real host
        self.assertEqual(ab.classify({"licenseurl": "https://creativecommons.org:x@evil.example/licenses/by/4.0/"}).kind,
                         "unknown")

    def test_a_file_on_disk_without_a_credit_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "clip.mp4"), "wb") as f:
                f.write(b"the user's own clip")
            e = ab.get("item-A", out=d, fmt="mp4", net=net)
            self.assertNotEqual(e["file"], "clip.mp4")
            with open(os.path.join(d, "clip.mp4"), "rb") as f:
                self.assertEqual(f.read(), b"the user's own clip")

    def test_two_items_with_the_same_file_name_keep_both_files(self):
        with tempfile.TemporaryDirectory() as d:
            ea = ab.get("item-A", out=d, fmt="mp4", net=net)
            eb = ab.get("item-B", out=d, fmt="mp4", net=net)
            self.assertNotEqual(ea["file"], eb["file"])
            with open(os.path.join(d, ea["file"]), "rb") as f:
                self.assertEqual(f.read(), A)
            with open(os.path.join(d, eb["file"]), "rb") as f:
                self.assertEqual(f.read(), B)
            creds = json.load(open(os.path.join(d, "credits.json"), encoding="utf-8"))
            self.assertEqual({(c["identifier"], c["file"]) for c in creds},
                             {("item-A", ea["file"]), ("item-B", eb["file"])})
            again = ab.get("item-A", out=d, fmt="mp4", net=net)                           # the same item again: same name
            self.assertEqual(again["file"], ea["file"])


if __name__ == "__main__":
    unittest.main()
