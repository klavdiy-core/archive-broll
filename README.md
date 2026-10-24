# archive-broll

Find retro footage and music on the Internet Archive, download it, and keep the credits straight.

> RU: в Internet Archive бесплатно лежат 10 тыс. фильмов Prelinger, 187 тыс. пластинок на 78 оборотов и 300 тыс. концертов. Найти легко. Трудно потом вспомнить лицензию и автора каждого клипа. archive-broll ищет, качает и сразу пишет CREDITS.md рядом с файлами.

## What hurts

The archive.org API is free and needs no key, so finding B-roll is easy: old industrial films, newsreels, early jazz, live sets. The trouble starts at the edit: forty clips in a folder, and nobody remembers which one was Public Domain, which was CC BY (credit required), which was non-commercial, and which had no license at all.

## What it does

- **search** Prelinger films (`-c films`), 78 rpm records (`-c 78`), live concerts (`-c live`) or any collection. A text query also matches Prelinger's **shot lists**, so `search "trains" -c films` finds films that *contain* a train, not just ones named after one.
- **filters by license**, on the server and again on your machine. The default `open` keeps only items that state Public Domain, CC0, CC BY or CC BY-SA. `--license nc` adds non-commercial; `--license any` adds no-derivatives and "not stated".
- **get** downloads the file you pick, **checks its MD5** against the archive's record (a broken download is deleted), and appends the item to `credits.json` and `CREDITS.md`. A file name that Windows cannot hold (78 rpm records often carry `"FATS" WALLER` in it) is saved under a safe name; `credits.json` keeps the original as `remote_file`.
- **never guesses a license.** An item that states none is refused by default. If you take it anyway, its credit line says **LICENSE NOT STATED, check before you publish**.
- **flags the loudest lies.** Licenses on archive.org are set by whoever uploaded the item and are not verified. A Public Domain claim on a work from 1978 or later (by its year or a year in its title) is marked **CHECK**: in the US such works are not public domain by age. Searching "ocean" turns up a 2016 Godzilla film whose item ([`ShinGodzilla_201811`](https://archive.org/metadata/ShinGodzilla_201811)) carries `licenseurl: publicdomain/mark/1.0`, and the 1984 film *Threads* ([`threads_201712`](https://archive.org/metadata/threads_201712)) carries the same. That flag is for cases like this.

Standard library only, Python 3.8+.

## Install

```sh
curl -O https://raw.githubusercontent.com/klavdiy-core/archive-broll/main/archive_broll.py
```

## Use

```sh
python archive_broll.py search "trains" -c films               # Prelinger, open licenses, by relevance
python archive_broll.py search -c films -y 1940-1955 -n 50      # by popularity
python archive_broll.py search "harmonica" -c live
python archive_broll.py search "jazz" -c 78 --license any       # the 78s mostly state no license
python archive_broll.py info ThirdAve1950                       # license + files with sizes and lengths
python archive_broll.py get ThirdAve1950 -o broll                # picks the h.264 mp4
python archive_broll.py get harmonica_blues -o broll -f mp3
python archive_broll.py get SomeConcert -o broll -f flac --all   # every track
python archive_broll.py credits broll                           # rebuild CREDITS.md from credits.json
```

```
$ python archive_broll.py search "trains" -c films -n 4
AtThisMo1954                             1954  Public Domain          At This Moment (Part I)
ArmyNurs1945                             1945  Public Domain          Army Nurse, The
ThirdAve1950                             1950  Public Domain          Third Avenue El
FromDawn1937                             1937  Public Domain          From Dawn to Sunset (Part I)

$ python archive_broll.py get harmonica_blues -o broll -f mp3
saved    broll/harmonica_blues.mp3
license  CC BY 3.0 [open] (stated by the uploader)
credits  broll/CREDITS.md

$ python archive_broll.py get rptreesfortomorrow -o broll
archive-broll: refused: not stated: the item does not state a license. Check its page, then pass --license any.
```

`broll/CREDITS.md`:

```markdown
# Credits

Footage and music from the Internet Archive (archive.org).
Licenses are as stated on each item page by its uploader; the Internet Archive does not verify them.

- *Harmonica Blues* (2007) — Larry Heyl. Internet Archive, https://archive.org/details/harmonica_blues · file `harmonica_blues.mp3` · CC BY 3.0 <http://creativecommons.org/licenses/by/3.0/>
```

`credits.json` holds the same plus file URL, format, length, MD5, raw rights text and the download date, for your editor or a script.

Exit codes: `0` done, `2` network or file error, `3` refused for license.

Formats (`-f`): `mp4` (h.264 first), `mp3`, `flac`, `ogg`. Default: mp4 for films, mp3 for audio. An item with many tracks asks you for `--file` or `--all`.

## Be honest with yourself about licenses

- This is not legal advice. The tool records what the item **says**; it cannot know whether that is true.
- Prelinger films are a curated collection and mostly state Public Domain. Many Prelinger items state nothing at all, and those are refused by default.
- The 78 rpm records (Great 78 Project) mostly state no license. Whether a recording is free to use depends on its year and your country (in the US, sound recordings published before 1926 are now public domain), and the composition has its own copyright. Check before you publish.
- Live concerts (etree) are often CC BY-NC or carry a "trade-friendly" note: fine to share, not to sell. `--license nc` makes that choice explicit.
- CC BY / BY-SA require the credit line. That is what `CREDITS.md` is for: paste it into the description or the end card.

archive.org can be slow (sometimes tens of KB/s). Use `info` first to see the size, and prefer the `512kb` copies for rough cuts.

## Test

```sh
python -m unittest discover -s tests
```

Mocked API answers: license classification (PD, PDM, CC0, BY, BY-SA, NC, ND, unknown), the server filter plus the client re-check, MD5 mismatch deleting the download, refusals for unknown/NC/ND, the CHECK flag, and no duplicate credits on a second download. Tested live against archive.org on 24 Oct 2026.

## License

MIT
