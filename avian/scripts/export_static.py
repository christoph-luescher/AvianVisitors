#!/usr/bin/env python3
"""Export the AvianVisitors collage + atlas as a static site.

The generated site has no PHP or SQLite dependency. It copies the frontend and
bird artwork, then writes JSON snapshots that match the live API shapes used by
apt.js. Intended to run periodically on the Pi and publish the output directory
with rsync or similar.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import urllib.parse
import urllib.request
from collections import OrderedDict
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AVIAN = ROOT / "avian"
FRONTEND = AVIAN / "frontend"
ASSETS = AVIAN / "assets"
DEFAULT_DB = ROOT / "scripts" / "birds.db"
DEFAULT_OUT = ROOT / "avian-static"
WINDOWS = (1, 12, 24, 168, 1000000)


def slugify(s: str) -> str:
    return re.sub(r"(^-|-$)", "", re.sub(r"[^a-z0-9]+", "-", s.lower()))


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n")


def rows(conn: sqlite3.Connection, sql: str, params=()) -> list[dict]:
    cur = conn.execute(sql, params)
    return [dict(row) for row in cur.fetchall()]


def one(conn: sqlite3.Connection, sql: str, params=()) -> dict | None:
    found = rows(conn, sql, params)
    return found[0] if found else None


def read_conf(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        val = val.strip()
        if len(val) >= 2 and val[0] == '"' and val[-1] == '"':
            val = val[1:-1]
        out[key.strip()] = val
    return out


def language_names() -> dict[str, str]:
    return {
        "af": "Afrikaans", "ar": "Arabic", "bg": "Bulgarian", "ca": "Catalan",
        "cs": "Czech", "da": "Danish", "de": "German", "en": "English",
        "es": "Spanish", "et": "Estonian", "fi": "Finnish", "fr": "French",
        "hr": "Croatian", "hu": "Hungarian", "id": "Indonesian",
        "is": "Icelandic", "it": "Italian", "ja": "Japanese", "ko": "Korean",
        "lt": "Lithuanian", "lv": "Latvian", "nl": "Dutch", "no": "Norwegian",
        "pl": "Polish", "pt": "Portuguese", "ro": "Romanian", "ru": "Russian",
        "sk": "Slovak", "sl": "Slovenian", "sr": "Serbian", "sv": "Swedish",
        "th": "Thai", "tr": "Turkish", "uk": "Ukrainian", "vi": "Vietnamese",
        "zh_CN": "Chinese (Simplified)", "zh_TW": "Chinese (Traditional)",
    }


def atlas_labels(conf_path: Path) -> dict:
    conf = read_conf(conf_path)
    l18n_dir = ROOT / "model" / "l18n"
    available = {
        p.name.removeprefix("labels_").removesuffix(".json"): p
        for p in l18n_dir.glob("labels_*.json")
    }
    default = conf.get("DATABASE_LANG") if conf.get("DATABASE_LANG") in available else "en"
    selected = [
        conf.get("ATLAS_LANGUAGE_1", default),
        conf.get("ATLAS_LANGUAGE_2", "none"),
        conf.get("ATLAS_LANGUAGE_3", "none"),
    ]
    names = language_names()
    languages = []
    labels = OrderedDict()
    for code in selected:
        if code == "none" or code not in available or code in labels:
            continue
        decoded = json.loads(available[code].read_text())
        languages.append({"code": code, "label": names.get(code, code)})
        labels[code] = decoded
    return {"languages": languages, "labels": labels}


def export_lifelist(conn: sqlite3.Connection) -> dict:
    species = rows(conn, """
        SELECT Sci_Name AS sci, Com_Name AS com,
               MIN(Date||' '||Time) AS first_seen,
               MAX(Date||' '||Time) AS last_seen,
               COUNT(*) AS n,
               MAX(Confidence) AS best_conf
        FROM detections
        GROUP BY Sci_Name
        ORDER BY first_seen ASC
    """)
    return {"species": species, "as_of": datetime.now().astimezone().isoformat()}


def export_recent(conn: sqlite3.Connection, hours: int) -> dict:
    species = rows(conn, """
        SELECT Sci_Name AS sci, Com_Name AS com, COUNT(*) AS n,
               MAX(Confidence) AS best_conf,
               MAX(Date||' '||Time) AS last_seen
        FROM detections
        WHERE (julianday('now','localtime') - julianday(Date||' '||Time)) * 24 <= ?
        GROUP BY Sci_Name
        ORDER BY last_seen DESC
    """, (hours,))
    for row in species:
        best = one(conn, """
            SELECT File_Name AS file, Date AS d, Time AS t, Confidence AS conf
            FROM detections
            WHERE Sci_Name = ?
              AND (julianday('now','localtime') - julianday(Date||' '||Time)) * 24 <= ?
            ORDER BY Confidence DESC
            LIMIT 1
        """, (row["sci"], hours))
        row["top_file"] = best["file"] if best else None
        row["top_at"] = f"{best['d']} {best['t']}" if best else None
    return {"hours": hours, "species": species, "as_of": datetime.now().astimezone().isoformat()}


def export_species(conn: sqlite3.Connection, sci: str) -> dict:
    summary = one(conn, """
        SELECT Com_Name AS com, COUNT(*) AS total,
               MIN(Date||' '||Time) AS first_seen,
               MAX(Date||' '||Time) AS last_seen,
               MAX(Confidence) AS best_conf
        FROM detections
        WHERE Sci_Name = ?
    """, (sci,))
    return {"sci": sci, "summary": summary, "detections": []}


def fetch_wiki(sci: str, cache_path: Path, refresh: bool = False) -> dict:
    if cache_path.is_file() and not refresh:
        try:
            return json.loads(cache_path.read_text())
        except json.JSONDecodeError:
            pass
    url = "https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(sci)
    req = urllib.request.Request(url, headers={"User-Agent": "AvianVisitors/1.0 static export"})
    data = {"extract": None, "thumbnail": None, "title": None}
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        thumb = raw.get("thumbnail", {}).get("source")
        data = {"extract": raw.get("extract"), "thumbnail": {"source": thumb} if thumb else None, "title": raw.get("title")}
    except Exception:
        pass
    write_json(cache_path, data)
    return data


def copy_frontend(out: Path) -> None:
    shutil.copy2(FRONTEND / "styles.css", out / "styles.css")
    shutil.copy2(FRONTEND / "apt.js", out / "apt.js")
    if (ASSETS / "favicon.png").is_file():
        shutil.copy2(ASSETS / "favicon.png", out / "favicon.png")

    html = (FRONTEND / "index.html").read_text()
    html = re.sub(r'\s*<button class="menu-btn" id="menuBtn">menu</button>', "", html)
    html = re.sub(r'\s*<aside id="menu-dd" aria-hidden="true">.*?</aside>', "", html, flags=re.DOTALL)
    html = re.sub(r'\s*<!-- ========== View 2 - Stats ========== -->.*?(?=\n\s*<!-- ========== View 3 - Atlas ========== -->)', "", html, flags=re.DOTALL)
    html = re.sub(r'\s*<button type="button" data-i="1">stats</button>', "", html)
    html = html.replace('<button type="button" data-i="2">atlas</button>', '<button type="button" data-i="1">atlas</button>')
    html = html.replace('<button data-h="24"  type="button" aria-current="true">24H</button>', '<button data-h="24"  type="button">24H</button>')
    html = html.replace('<button data-h="1000000" type="button">ALL</button>', '<button data-h="1000000" type="button" aria-current="true">ALL</button>')
    html = html.replace('<script src="./apt.js"></script>', '<script src="./static-config.js"></script>\n<script src="./apt.js"></script>')
    (out / "index.html").write_text(html)

    asset_out = out / "avian" / "assets"
    for name in ("illustrations", "cutouts"):
        src = ASSETS / name
        if src.is_dir():
            shutil.copytree(src, asset_out / name, dirs_exist_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="BirdNET-Pi birds.db path")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Static export directory")
    parser.add_argument("--conf", type=Path, default=ROOT / "birdnet.conf", help="birdnet.conf path")
    parser.add_argument("--refresh-wiki", action="store_true", help="Refetch cached Wikipedia summaries")
    args = parser.parse_args()

    if not args.db.is_file():
        raise SystemExit(f"birds.db not found: {args.db}")

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    copy_frontend(out)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    lifelist = export_lifelist(conn)
    write_json(out / "data" / "lifelist.json", lifelist)
    write_json(out / "data" / "atlas-labels.json", atlas_labels(args.conf))
    for hours in WINDOWS:
        key = "all" if hours >= 1000000 else str(hours)
        write_json(out / "data" / f"recent-{key}.json", export_recent(conn, hours))

    for sp in lifelist["species"]:
        sci = sp["sci"]
        slug = slugify(sci)
        write_json(out / "data" / "species" / f"{slug}.json", export_species(conn, sci))
        fetch_wiki(sci, out / "data" / "wiki" / f"{slug}.json", refresh=args.refresh_wiki)

    generated = datetime.now().astimezone().isoformat()
    (out / "static-config.js").write_text(
        "window.AVIAN_STATIC = " + json.dumps({"generatedAt": generated}, separators=(",", ":")) + ";\n"
    )
    print(f"Exported {len(lifelist['species'])} species to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
