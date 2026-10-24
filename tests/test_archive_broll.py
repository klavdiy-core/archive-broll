import hashlib
import json
import os
import sys
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import archive_broll as ab  # noqa: E402

VIDEO = b"\x00\x00\x00 ftypisom fake mp4 bytes" * 10
VIDEO_MD5 = hashlib.md5(VIDEO).hexdigest()

META = {
    "LightOfYourL": {
        "metadata": {
            "identifier": "LightOfYourL", "title": "Light Of Your Life, A", "creator": "General Electric",
            "year": "1949", "collection": ["prelinger", "moviesandfilms"], "mediatype": "movies",
            "licenseurl": "http://creativecommons.org/licenses/publicdomain/",
        },
        "files": [
            {"name": "LightOfYourL.mpeg", "format": "MPEG2", "source": "original", "size": "347123797"},
            {"name": "LightOfYourL.mp4", "format": "h.264", "source": "derivative", "size": str(len(VIDEO)),
             "md5": VIDEO_MD5, "length": "733.73"},
            {"name": "LightOfYourL_512kb.mp4", "format": "512Kb MPEG4", "source": "derivative", "size": "53233417"},
            {"name": "__ia_thumb.jpg", "format": "Item Tile", "source": "original", "size": "8145"},
        ],
    },
    "rptreesfortomorrow": {
        "metadata": {"identifier": "rptreesfortomorrow", "title": "Trees For Tomorrow",
                     "collection": "prelinger", "mediatype": "movies"},
        "files": [{"name": "RP-Trees_For_Tomorrow.mp4", "format": "MPEG4", "source": "original",
                   "size": str(len(VIDEO)), "md5": VIDEO_MD5}],
    },
    "ncshow": {
        "metadata": {"identifier": "ncshow", "title": "Live at the Pub", "creator": "Some Band",
                     "date": "2024-04-20", "collection": ["etree"], "mediatype": "etree",
                     "licenseurl": "https://creativecommons.org/licenses/by-nc-sa/4.0/"},
        "files": [{"name": "set1.mp3", "format": "VBR MP3", "source": "derivative",
                   "size": str(len(VIDEO)), "md5": VIDEO_MD5}],
    },
}


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class FakeNet:
    def __init__(self, corrupt=False):
        self.calls = []
        self.corrupt = corrupt

    def __call__(self, url):
        self.calls.append(url)
        u = urlparse(url)
        if u.path == "/advancedsearch.php":
            q = parse_qs(u.query)
            self.last_query = q["q"][0]
            docs = [{"identifier": "LightOfYourL", "title": "Light Of Your Life, A", "year": 1949,
                     "licenseurl": "http://creativecommons.org/licenses/publicdomain/"},
                    {"identifier": "rptreesfortomorrow", "title": "Trees For Tomorrow"}]
            return json.dumps({"response": {"numFound": 2, "docs": docs}}).encode()
        if u.path.startswith("/metadata/"):
            return json.dumps(META[u.path.split("/")[2]]).encode()
        if u.path.startswith("/download/"):
            return VIDEO[:-1] + b"X" if self.corrupt else VIDEO
        raise AssertionError(url)


class Licenses(unittest.TestCase):
    def test_classify(self):
        cases = {
            "http://creativecommons.org/licenses/publicdomain/": ("Public Domain", "open"),
            "https://creativecommons.org/publicdomain/mark/1.0/": ("Public Domain Mark 1.0", "open"),
            "http://creativecommons.org/publicdomain/zero/1.0/": ("CC0 1.0", "open"),
            "https://creativecommons.org/licenses/by/4.0/": ("CC BY 4.0", "open"),
            "http://creativecommons.org/licenses/by-sa/3.0/": ("CC BY-SA 3.0", "open"),
            "https://creativecommons.org/licenses/by-nc-sa/4.0/": ("CC BY-NC-SA 4.0", "nc"),
            "https://creativecommons.org/licenses/by-nd/4.0/": ("CC BY-ND 4.0", "nd"),
            "https://creativecommons.org/licenses/by-nc-nd/3.0/": ("CC BY-NC-ND 3.0", "nd"),
        }
        for url, want in cases.items():
            with self.subTest(url=url):
                lic = ab.classify({"licenseurl": url})
                self.assertEqual((lic.name, lic.kind), want)

    def test_pd_claim_on_a_modern_work_is_flagged(self):
        pd = ab.classify({"licenseurl": "https://creativecommons.org/publicdomain/mark/1.0/"})
        self.assertTrue(ab.suspicious({"title": "SHIN GODZILLA", "year": "2016"}, pd))
        self.assertTrue(ab.suspicious({"title": "Threads 1984"}, pd))
        self.assertFalse(ab.suspicious({"title": "A is for Atom", "year": "1953"}, pd))
        by = ab.classify({"licenseurl": "https://creativecommons.org/licenses/by/4.0/"})
        self.assertFalse(ab.suspicious({"title": "Live 2021", "year": "2021"}, by))

    def test_unknown_is_never_guessed(self):
        self.assertEqual(ab.classify({"collection": "prelinger"}).kind, "unknown")
        self.assertEqual(ab.classify({"rights": "Public Domain"}).kind, "open")
        self.assertEqual(ab.classify({"rights": "All rights reserved"}).kind, "unknown")


class Search(unittest.TestCase):
    def test_open_filter_goes_to_the_server_and_is_rechecked(self):
        net = FakeNet()
        hits = ab.search("trains", collection="films", net=net)
        self.assertIn("collection:(prelinger)", net.last_query)
        self.assertIn("licenseurl:", net.last_query)
        # the server returned an item without a license; it must still be dropped
        self.assertEqual([h["identifier"] for h in hits], ["LightOfYourL"])

    def test_any_license_keeps_unknown(self):
        hits = ab.search("trains", collection="films", license="any", net=FakeNet())
        self.assertEqual(len(hits), 2)


class Get(unittest.TestCase):
    def test_download_writes_file_and_credits(self):
        with tempfile.TemporaryDirectory() as d:
            entry = ab.get("LightOfYourL", out=d, fmt="mp4", net=FakeNet())
            self.assertEqual(entry["file"], "LightOfYourL.mp4")   # h.264 preferred over the 512kb copy
            with open(os.path.join(d, "LightOfYourL.mp4"), "rb") as f:
                self.assertEqual(f.read(), VIDEO)
            with open(os.path.join(d, "credits.json")) as f:
                cred = json.load(f)
            self.assertEqual(cred[0]["license"], "Public Domain")
            self.assertEqual(cred[0]["item_url"], "https://archive.org/details/LightOfYourL")
            md = read(os.path.join(d, "CREDITS.md"))
            self.assertIn("Light Of Your Life, A", md)
            self.assertIn("General Electric", md)
            self.assertIn("Public Domain", md)
            self.assertIn("does not verify", md)
            self.assertNotIn("CHECK", md)
            # a second download of the same file does not duplicate the credit
            ab.get("LightOfYourL", out=d, fmt="mp4", net=FakeNet())
            with open(os.path.join(d, "credits.json")) as f:
                self.assertEqual(len(json.load(f)), 1)

    def test_unknown_license_is_refused_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ab.LicenseError):
                ab.get("rptreesfortomorrow", out=d, net=FakeNet())
            self.assertEqual(os.listdir(d), [])

    def test_unknown_license_when_allowed_is_flagged_loudly(self):
        with tempfile.TemporaryDirectory() as d:
            ab.get("rptreesfortomorrow", out=d, license="any", net=FakeNet())
            md = read(os.path.join(d, "CREDITS.md"))
            self.assertIn("LICENSE NOT STATED", md)

    def test_nc_needs_its_own_permission(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ab.LicenseError):
                ab.get("ncshow", out=d, fmt="mp3", net=FakeNet())
            e = ab.get("ncshow", out=d, fmt="mp3", license="nc", net=FakeNet())
            self.assertEqual(e["license"], "CC BY-NC-SA 4.0")
            md = read(os.path.join(d, "CREDITS.md"))
            self.assertIn("non-commercial", md)

    def test_checksum_mismatch_deletes_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ab.DownloadError):
                ab.get("LightOfYourL", out=d, fmt="mp4", net=FakeNet(corrupt=True))
            self.assertFalse(os.path.exists(os.path.join(d, "LightOfYourL.mp4")))
            self.assertFalse(os.path.exists(os.path.join(d, "credits.json")))


if __name__ == "__main__":
    unittest.main()
