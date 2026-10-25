#!/usr/bin/env python3
"""archive-broll: find retro footage and music on the Internet Archive, download it, keep the credits.

Searches Prelinger films, 78 rpm records, live concerts or any collection through
the free archive.org APIs (no key), downloads the file you pick, checks its MD5,
and writes CREDITS.md + credits.json next to it: title, creator, year, source
URL and the license as the item states it. It never guesses a license: by
default it only takes items that state Public Domain, CC0, CC BY or CC BY-SA.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
from dataclasses import dataclass
from urllib.parse import quote, urlencode

__version__ = "0.2.0"
API = "https://archive.org"
UA = f"archive-broll/{__version__} (+https://github.com/klavdiy-core/archive-broll)"

COLLECTIONS = {"films": "prelinger", "78": "georgeblood", "live": "etree"}
FORMATS = {
    "mp4": ["h.264", "MPEG4", "h.264 IA", "HiRes MPEG4", "512Kb MPEG4"],
    "mp3": ["VBR MP3", "128Kbps MP3", "64Kbps MP3"],
    "flac": ["Flac", "24bit Flac"],
    "ogg": ["Ogg Vorbis", "Ogg Video"],
}
# what each --license level lets through
LEVELS = {"open": {"open"}, "nc": {"open", "nc"}, "any": {"open", "nc", "nd", "unknown"}}
OPEN_QUERY = ('(licenseurl:(*publicdomain* OR *zero* OR *licenses\\/by\\/* OR *licenses\\/by-sa\\/*)'
              ' OR rights:"public domain")')


class LicenseError(Exception):
    pass


class DownloadError(Exception):
    pass


@dataclass
class License:
    name: str
    url: str
    kind: str   # open | nc | nd | unknown


# ---------- licenses ----------

def classify(meta):
    url = meta.get("licenseurl") or ""
    if isinstance(url, list):
        url = url[0] if url else ""
    u = url.lower().rstrip("/")
    if u:
        parts = u.split("/")
        ver = parts[-1] if parts[-1].replace(".", "").isdigit() else ""
        if "publicdomain/zero" in u:
            return License(f"CC0 {ver}".strip(), url, "open")
        if "publicdomain/mark" in u:
            return License(f"Public Domain Mark {ver}".strip(), url, "open")
        if "publicdomain" in u:
            return License("Public Domain", url, "open")
        if "/licenses/" in u:
            code = u.split("/licenses/")[1].split("/")[0]
            name = f"CC {code.upper()} {ver}".strip()
            if "nd" in code.split("-"):
                return License(name, url, "nd")
            if "nc" in code.split("-"):
                return License(name, url, "nc")
            return License(name, url, "open")
    rights = meta.get("rights") or ""
    if isinstance(rights, list):
        rights = " ".join(rights)
    if "public domain" in rights.lower() and "not" not in rights.lower():
        return License("Public Domain (stated in rights)", "", "open")
    return License("not stated", "", "unknown")


def _check(lic, level):
    if lic.kind in LEVELS[level]:
        return
    why = {
        "unknown": "the item does not state a license. Check its page, then pass --license any",
        "nc": "it is non-commercial only. Pass --license nc if your use is non-commercial",
        "nd": "it allows no derivatives, and an edit is one. Pass --license any only if you will not cut it",
    }
    raise LicenseError(f"refused: {lic.name}: {why[lic.kind]}.")


# ---------- network ----------

def _http(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except OSError:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))


def _stream(url, path, net=None):
    if net is not None:
        with open(path, "wb") as f:
            f.write(net(url))
        return
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r, open(path, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total and sys.stderr.isatty():
                print(f"\r  {done >> 20} / {total >> 20} MB", end="", file=sys.stderr)
        if total and sys.stderr.isatty():
            print(file=sys.stderr)


def _json(url, net=None):
    return json.loads((net or _http)(url).decode("utf-8"))


# ---------- search / info / get ----------

def suspicious(d, lic):
    """A Public Domain claim on a work from 1978 or later: in the US such works are not PD by age.

    Licenses on archive.org are set by uploaders and not verified; this catches the loudest mistakes.
    """
    if lic.kind != "open" or not lic.name.startswith("Public Domain"):  # CC0 and CC BY are the author's own grant
        return False
    years = [str(_first(d.get("year")) or ""), str(_first(d.get("date")) or "")[:4]]
    years += re.findall(r"(?<!\d)(19[7-9]\d|20\d\d)(?!\d)", str(_first(d.get("title"))))
    return any(y.isdigit() and int(y) >= 1978 for y in years)


def _format_query(fmt=None):
    """Only items that have a file `get` can download: without this, metadata-only items were listed."""
    wanted = FORMATS[fmt] if fmt else [f for fs in FORMATS.values() for f in fs]
    return "format:(" + " OR ".join(f'"{f}"' for f in wanted) + ")"


def search(text="", collection=None, mediatype=None, license="open", year=None, rows=20, page=1, net=None,
           sort=None, fmt=None, max_pages=5):
    q = []
    if text:
        q.append(f"({text})")
    if collection:
        q.append(f"collection:({COLLECTIONS.get(collection, collection)})")
    if mediatype:
        q.append(f"mediatype:({mediatype})")
    if year:
        lo, _, hi = str(year).partition("-")
        q.append(f"year:[{lo} TO {hi or lo}]")
    if license == "open":
        q.append(OPEN_QUERY)
    q.append(_format_query(fmt))
    fields = ["identifier", "title", "creator", "year", "date", "mediatype", "licenseurl", "rights", "downloads"]
    order = {"downloads": "downloads desc", "year": "year asc", "relevance": None}[
        sort or ("relevance" if text else "downloads")]
    base = [("q", " AND ".join(q) or "*:*")] + [("fl[]", f) for f in fields]
    base += [("sort[]", order)] if order else []
    hits = []
    # the license is rechecked here, after the server's page: keep paging until `rows` hits pass, or the archive runs out
    for p in range(page, page + max_pages):
        params = base + [("rows", rows), ("page", p), ("output", "json")]
        data = _json(f"{API}/advancedsearch.php?{urlencode(params)}", net)
        if "response" not in data:
            raise DownloadError(f"search failed: {data.get('error') or str(data)[:200]}")
        docs = data["response"]["docs"]
        for d in docs:
            lic = classify(d)
            if lic.kind in LEVELS[license]:
                d["license"], d["license_kind"] = lic.name, lic.kind
                d["check"] = suspicious(d, lic)
                hits.append(d)
        if len(hits) >= rows or len(docs) < rows or p * rows >= data["response"].get("numFound", 0):
            break
    return hits[:rows]


def info(identifier, net=None):
    return _json(f"{API}/metadata/{quote(identifier)}", net)


def _year(md):
    """The year as the item states it: 1949 from a year or a 1949-05-01 date; an approximate date is kept whole
    (ca. 1950s), never cut to its first four characters."""
    y = str(_first(md.get("year")) or "").strip()
    if y:
        return y
    date = str(_first(md.get("date")) or "").strip()
    if re.match(r"\d{4}", date):
        return date[:4]
    return date[:20] if re.search(r"\d{4}", date) else ""


def _first(v):
    return v[0] if isinstance(v, list) and v else (v or "")


def pick_files(meta, fmt=None, name=None):
    files = meta.get("files", [])
    if name:
        return [f for f in files if f["name"] == name]
    if fmt is None:
        mt = meta.get("metadata", {}).get("mediatype")
        fmt = "mp4" if mt == "movies" else "mp3"
    for wanted in FORMATS[fmt]:
        got = [f for f in files if f.get("format") == wanted]
        if got:
            return got
    return []


def _credit_line(c):
    who = f" — {c['creator']}" if c.get("creator") else ""
    when = f" ({c['year']})" if re.search(r"\d{4}", str(c.get("year") or "")) else ""
    lic = c["license"] + (f" <{c['license_url']}>" if c.get("license_url") else "")
    if c["license_kind"] == "unknown":
        lic = "**LICENSE NOT STATED on the item page: check before you publish.**"
    elif c["license_kind"] == "nc":
        lic += " (non-commercial use only)"
    elif c["license_kind"] == "nd":
        lic += " (no derivatives: do not cut or edit)"
    if c.get("check"):
        lic += " **CHECK: a PD claim on a work from 1978 or later is probably an uploader's mistake.**"
    return f"- *{c['title']}*{when}{who}. Internet Archive, {c['item_url']} · file `{c['file']}` · {lic}"


def write_credits(out):
    path = os.path.join(out, "credits.json")
    with open(path, encoding="utf-8") as f:
        creds = json.load(f)
    lines = ["# Credits", "", "Footage and music from the Internet Archive (archive.org).",
             "Licenses are as stated on each item page by its uploader; the Internet Archive does not verify them.",
             ""]
    lines += [_credit_line(c) for c in creds]
    with open(os.path.join(out, "CREDITS.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _add_credit(out, entry):
    path = os.path.join(out, "credits.json")
    creds = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            creds = json.load(f)
    creds = [c for c in creds if not (c["identifier"] == entry["identifier"] and c["file"] == entry["file"])]
    creds.append(entry)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(creds, f, indent=2, ensure_ascii=False)
    write_credits(out)


RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def safe_name(name):
    """A local file name that works on Windows, macOS and Linux (78 rpm items carry quotes and colons)."""
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).rstrip(" .")
    return "_" + s if s.split(".")[0].upper() in RESERVED else (s or "_")


def creator_text(md):
    c = md.get("creator", "")
    return ", ".join(c) if isinstance(c, list) else str(c or "")


def get(identifier, out=".", fmt=None, name=None, all_files=False, license="open", net=None):
    """Download one file of an item (or all of the chosen format) and record its credit. Returns the last entry."""
    meta = info(identifier, net)
    md = meta.get("metadata") or {}
    if not md:
        raise DownloadError(f"no such item: {identifier}")
    lic = classify(md)
    _check(lic, license)
    files = pick_files(meta, fmt, name)
    if not files:
        raise DownloadError(f"{identifier}: no file matches (try `info {identifier}` and --file)")
    if len(files) > 1 and not all_files:
        names = "\n  ".join(f["name"] for f in files[:30])
        raise DownloadError(f"{identifier} has {len(files)} matching files; pick one with --file, or --all:\n  {names}")
    os.makedirs(out, exist_ok=True)
    entry = None
    for f in files:
        local = os.path.join(out, safe_name(os.path.basename(f["name"])))
        url = f"{API}/download/{quote(identifier)}/{quote(f['name'])}"
        part = local + ".part"
        _stream(url, part, net)
        if f.get("md5"):
            h = hashlib.md5()
            with open(part, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            if h.hexdigest() != f["md5"]:
                os.remove(part)
                raise DownloadError(f"{f['name']}: MD5 mismatch, download deleted")
        os.replace(part, local)
        entry = {
            "identifier": identifier,
            "title": _first(md.get("title")) or identifier,
            "creator": creator_text(md),
            "year": _year(md),
            "collection": md.get("collection"),
            "item_url": f"{API}/details/{identifier}",
            "file": os.path.basename(local),
            "remote_file": os.path.basename(f["name"]),
            "file_url": url,
            "format": f.get("format"),
            "length_s": f.get("length"),
            "md5": f.get("md5"),
            "license": lic.name,
            "license_url": lic.url,
            "license_kind": lic.kind,
            "rights": md.get("rights", ""),
            "downloaded": time.strftime("%Y-%m-%d"),
        }
        entry["check"] = suspicious(md, lic)
        _add_credit(out, entry)
    return entry


# ---------- CLI ----------

def _fmt_len(s):
    try:
        s = float(s)
    except (TypeError, ValueError):
        return str(s or "")
    return f"{int(s // 60)}:{int(s % 60):02d}"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="archive-broll", description=__doc__.splitlines()[0])
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="search items")
    s.add_argument("text", nargs="?", default="")
    s.add_argument("-c", "--collection", help="films (Prelinger), 78 (78 rpm records), live (etree) or any collection id")
    s.add_argument("-t", "--type", dest="mediatype", help="movies, audio, etree ...")
    s.add_argument("-y", "--year", help="1950 or 1940-1960")
    s.add_argument("-n", "--rows", type=int, default=20)
    s.add_argument("--page", type=int, default=1)
    s.add_argument("-l", "--license", choices=LEVELS, default="open")
    s.add_argument("-s", "--sort", choices=["relevance", "downloads", "year"],
                   help="default: relevance with text, downloads without")
    s.add_argument("-f", "--format", choices=FORMATS, help="only items with a file in this format (default: any video or audio)")
    s.add_argument("--json", action="store_true")

    i = sub.add_parser("info", help="show an item: license and downloadable files")
    i.add_argument("identifier")

    g = sub.add_parser("get", help="download a file and record its credit")
    g.add_argument("identifier")
    g.add_argument("-o", "--out", default="broll")
    g.add_argument("-f", "--format", choices=FORMATS)
    g.add_argument("--file", help="exact file name inside the item")
    g.add_argument("--all", action="store_true", help="every file of the chosen format")
    g.add_argument("-l", "--license", choices=LEVELS, default="open")

    c = sub.add_parser("credits", help="rebuild CREDITS.md from credits.json")
    c.add_argument("dir", nargs="?", default="broll")
    a = ap.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    try:
        if a.cmd == "search":
            hits = search(a.text, a.collection, a.mediatype, a.license, a.year, a.rows, a.page, sort=a.sort,
                          fmt=a.format)
            if a.json:
                print(json.dumps(hits, indent=2, ensure_ascii=False))
            for h in hits if not a.json else []:
                yr = _year(h)
                flag = "CHECK" if h["check"] else ""
                print(f"{h['identifier']:<40} {str(yr):<5} {h['license']:<22} {flag:<6}{_first(h.get('title'))[:64]}")
            if not hits:
                print("nothing found" + (" with an open license (try --license any)" if a.license == "open" else ""))
        elif a.cmd == "info":
            meta = info(a.identifier)
            md = meta.get("metadata") or {}
            if not md:
                raise DownloadError(f"no such item: {a.identifier}")
            lic = classify(md)
            yr = _year(md)
            print(f"{_first(md.get('title'))}" + (f"  ({yr})" if yr.isdigit() else ""))
            print(f"creator  {creator_text(md)}")
            print(f"license  {lic.name} [{lic.kind}] {lic.url}  (stated by the uploader, not verified)"
                  + ("  CHECK: PD claim on a 1978+ work" if suspicious(md, lic) else ""))
            print(f"page     {API}/details/{a.identifier}")
            for f in meta.get("files", []):
                if any(f.get("format") in v for v in FORMATS.values()):
                    mb = int(f.get("size") or 0) / 1e6
                    print(f"  {f['name']:<50} {f.get('format', ''):<14} {mb:8.1f} MB  {_fmt_len(f.get('length'))}")
        elif a.cmd == "get":
            e = get(a.identifier, a.out, a.format, a.file, a.all, a.license)
            print(f"saved    {os.path.join(a.out, e['file'])}")
            print(f"license  {e['license']} [{e['license_kind']}] (stated by the uploader)"
                  + ("  CHECK: PD claim on a 1978+ work" if e["check"] else ""))
            print(f"credits  {os.path.join(a.out, 'CREDITS.md')}")
        elif a.cmd == "credits":
            write_credits(a.dir)
            print(f"wrote {os.path.join(a.dir, 'CREDITS.md')}")
    except (LicenseError, DownloadError) as e:
        print(f"archive-broll: {e}", file=sys.stderr)
        return 3 if isinstance(e, LicenseError) else 2
    except OSError as e:
        print(f"archive-broll: network or disk error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
