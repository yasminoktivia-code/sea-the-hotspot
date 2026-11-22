"""
Sea the Hotspot - update dashboard dari KoboToolbox.

Mengambil semua data + foto terbaru dari project Kobo, lalu membuat ulang
Dashboard_SeaTheHotspot.html dan data_biota_terbaru.csv.

Jalankan lewat "Update Dashboard.bat" (satu folder di atas folder ini).
Pengaturan (API key, server, ID project) ada di kobo_config.ini.
"""
import argparse, base64, configparser, csv, datetime, io, json, math, os, re, statistics, sys, urllib.request
from PIL import Image, ImageOps

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE = os.path.join(HERE, "cache_foto")
OUT_HTML = os.path.join(ROOT, "Dashboard_SeaTheHotspot.html")
OUT_CSV = os.path.join(ROOT, "data_biota_terbaru.csv")
FLAG_DISTANCE_M = 150          # titik lebih jauh dari ini (dari pusat lokasinya) ditandai "cek koordinat"
PLACEHOLDER = ("data:image/svg+xml;base64," + base64.b64encode(
    b'<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300"><rect width="400" height="300" fill="#dde8ea"/>'
    b'<text x="200" y="160" font-size="28" text-anchor="middle" fill="#46606a" font-family="sans-serif">Foto tidak tersedia</text></svg>').decode())


try:  # emoji-safe output in any Windows console / scheduled task
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------- Kobo access
class Kobo:
    def __init__(self, server, token):
        self.server, self.token = server.rstrip("/"), token

    def get(self, url):
        req = urllib.request.Request(url, headers={"Authorization": f"Token {self.token}", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read()

    def json(self, url):
        return json.loads(self.get(url))


def load_from_kobo(cfg):
    kobo = Kobo(cfg["server"], cfg["token"])
    uid = cfg["asset_uid"]
    asset = kobo.json(f"{kobo.server}/api/v2/assets/{uid}/?format=json")
    rows, url = [], f"{kobo.server}/api/v2/assets/{uid}/data/?format=json&limit=500"
    while url:
        page = kobo.json(url)
        rows += page["results"]
        url = page.get("next")
    return asset, rows, kobo


# ---------------------------------------------------------------- helpers
def label_of(choice):
    lab = choice.get("label", choice.get("name", ""))
    if isinstance(lab, list):  # one entry per form language; some may be empty (null)
        lab = next((x for x in lab if x), "")
    return lab or choice.get("name", "")


def split_label(label):
    """'Kelomang Anemon (Dardanus deformis)' -> ('Kelomang Anemon', 'Dardanus deformis')"""
    m = re.match(r"^(.*?)\s*\(([^()]+)\)\s*$", label or "")
    return (m.group(1).strip(), m.group(2).strip()) if m else ((label or "").strip(), "")


def title(s):
    return " ".join(w[:1].upper() + w[1:] for w in s.split())


def from_note(pattern, note):
    m = re.search(pattern, note or "")
    return m.group(1).strip() if m else ""


def encode(img, size, quality):
    im = img.copy()
    im.thumbnail((size, size))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality, optimize=True, progressive=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def photo_for(row, kobo):
    """Return (full, thumb) data URIs for the submission's photo, using/refreshing the local cache."""
    atts = [a for a in row.get("_attachments", []) if not a.get("is_deleted")]
    want = row.get("foto")
    att = next((a for a in atts if a.get("question_xpath") == "foto"), None) or \
          next((a for a in atts if a.get("media_file_basename") == want), None) or (atts[0] if atts else None)
    if not att:
        return PLACEHOLDER, PLACEHOLDER
    base = att.get("media_file_basename") or os.path.basename(att.get("filename", "foto.jpg"))
    path = os.path.join(CACHE, f"{row['_id']}_{base}")
    if not os.path.exists(path) and kobo:
        try:
            data = kobo.get(att["download_url"])
            with open(path, "wb") as f:
                f.write(data)
        except Exception as e:  # noqa: BLE001
            log(f"  ! foto {base} gagal diunduh: {e}")
    if not os.path.exists(path):
        return PLACEHOLDER, PLACEHOLDER
    try:
        img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    except Exception as e:  # noqa: BLE001
        log(f"  ! foto {base} tidak bisa dibaca: {e}")
        return PLACEHOLDER, PLACEHOLDER
    return encode(img, 1600, 68), encode(img, 400, 70)


# ---------------------------------------------------------------- transform
def build_records(asset, rows, kobo):
    choices = {}
    for c in asset.get("content", {}).get("choices", []):
        choices.setdefault(c.get("list_name"), {})[c.get("name")] = label_of(c)
    sp_labels, kat_labels = choices.get("spesies", {}), choices.get("kategori", {})

    recs, skipped = [], 0
    for row in rows:
        if (row.get("_validation_status") or {}).get("uid") == "validation_status_not_approved":
            skipped += 1
            continue
        geo = row.get("_geolocation") or [None, None]
        if geo[0] is None:
            parts = (row.get("titik") or "").split()
            geo = [float(parts[0]), float(parts[1])] if len(parts) >= 2 else [None, None]
        if geo[0] is None:
            skipped += 1
            continue
        note = row.get("catatan", "") or ""
        ts = row.get("start") or row.get("_submission_time") or ""
        kel = row.get("kelompok") or "lainnya"
        if "bukan biota laut" in note.lower():
            kel = "non_laut"

        sp = row.get("spesies") or "tidak_tahu"
        lab_local, lab_sci = split_label(sp_labels.get(sp, ""))
        note_local = from_note(r"Nama lokal: (.+?)\.", note)
        note_sci = from_note(r"Nama ilmiah: (.+?)\. Jumlah", note) or from_note(r"Nama ilmiah: (.+?)\.", note)
        note_saran = from_note(r"Saran ID \(belum diverifikasi\): (.+?)\. Jumlah", note)
        status = row.get("status_verifikasi", "")
        if sp == "tidak_tahu":
            lain = (row.get("spesies_lain") or "").strip()
            local = note_local or (title(split_label(lain)[0]) if lain else "Belum teridentifikasi")
            sci = note_sci
        else:
            local, sci = note_local or lab_local or sp, note_sci or lab_sci
        if status == "perlu_identifikasi":
            saran, nama_ilmiah = note_saran or sci, ""
        else:
            saran, nama_ilmiah = "", sci
        key = lab_sci or note_sci or local

        qc = [q.strip() for q in from_note(r"QC: (.+?)\. File asli", note).split(";") if q.strip()]
        foto, thumb = photo_for(row, kobo)
        recs.append({
            "id": str(row.get("_id")), "tanggal": ts[:10], "jam": ts[11:16] or "00:00",
            "nama_lokal": local, "nama_ilmiah": nama_ilmiah, "saran_identifikasi": saran,
            "kelompok": kel, "spesies_key": key, "lat": geo[0], "lon": geo[1],
            "lokasi": row.get("lokasi_lain") or row.get("lokasi") or "",
            # name sits inside the "identitas" group since form v10; phone & email are never copied to the dashboard
            "pengamat": row.get("identitas/pengamat") or row.get("pengamat", ""), "kategori": kat_labels.get(row.get("kategori"), row.get("kategori", "")),
            "status_verifikasi": status, "catatan_kualitas": qc, "foto": foto, "thumb": thumb,
        })

    # coordinate check: distance from the median point of the same location
    by_loc = {}
    for r in recs:
        by_loc.setdefault(r["lokasi"], []).append(r)
    for group in by_loc.values():
        mlat = statistics.median(r["lat"] for r in group)
        mlon = statistics.median(r["lon"] for r in group)
        for r in group:
            dy = (r["lat"] - mlat) * 110574
            dx = (r["lon"] - mlon) * 111320 * math.cos(math.radians(mlat))
            dist = math.hypot(dx, dy)
            r["cek_koordinat"] = dist > FLAG_DISTANCE_M or any("salah ketik" in q for q in r["catatan_kualitas"])
    recs.sort(key=lambda r: (r["tanggal"], r["jam"], r["id"]))
    return recs, skipped


# ---------------------------------------------------------------- satellite tiles
TILE_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
TILE_CACHE = os.path.join(HERE, "cache_tiles")
MAX_TILES = 160


def tile_xy(lat, lon, z):
    n = 2 ** z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return x, y


def embedded_tiles(recs):
    """Satellite tiles around every observation (zoom 15-19), cached locally, as data URIs."""
    if not recs:
        return {}
    os.makedirs(TILE_CACHE, exist_ok=True)
    pad = 0.0012  # ~130 m margin around the points
    lat0, lat1 = min(r["lat"] for r in recs) - pad, max(r["lat"] for r in recs) + pad
    lon0, lon1 = min(r["lon"] for r in recs) - pad, max(r["lon"] for r in recs) + pad
    wanted = []
    for z in range(15, 20):
        x0, y0 = tile_xy(lat1, lon0, z)
        x1, y1 = tile_xy(lat0, lon1, z)
        level = [(z, x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]
        if len(wanted) + len(level) > MAX_TILES:
            break
        wanted += level
    out, fetched = {}, 0
    for z, x, y in wanted:
        path = os.path.join(TILE_CACHE, f"{z}_{x}_{y}.jpg")
        if not os.path.exists(path):
            try:
                req = urllib.request.Request(TILE_URL.format(z=z, x=x, y=y), headers={"User-Agent": "SeaTheHotspotDashboard/1.0"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    data = r.read()
                with open(path, "wb") as f:
                    f.write(data)
                fetched += 1
            except Exception as e:  # noqa: BLE001
                log(f"  ! citra satelit {z}/{x}/{y} gagal diunduh: {e}")
                continue
        out[f"{z}/{x}/{y}"] = "data:image/jpeg;base64," + base64.b64encode(open(path, "rb").read()).decode()
    log(f"• Citra satelit: {len(out)} potongan ({fetched} baru diunduh)")
    return out


# ---------------------------------------------------------------- output
SHARE_HTML = os.path.join(HERE, "share", "dashboard_share.html")


def write_outputs(recs):
    tpl = open(os.path.join(HERE, "template_dashboard.html"), encoding="utf-8").read()
    facts = json.load(open(os.path.join(HERE, "fakta_biota.json"), encoding="utf-8"))
    leaflet_css = open(os.path.join(HERE, "leaflet-1.9.4.css"), encoding="utf-8").read()
    now = datetime.datetime.now()
    bulan = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"]
    data = {"diperbarui": f"{now.day} {bulan[now.month - 1]} {now.year}, {now:%H.%M}", "records": recs, "tiles": embedded_tiles(recs)}
    html = (tpl.replace("__LEAFLET_CSS__", leaflet_css)
               .replace("__FACTS__", json.dumps(facts, ensure_ascii=False))
               .replace("__DATA__", json.dumps(data, ensure_ascii=False)))
    tmp = OUT_HTML + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(html)
    os.replace(tmp, OUT_HTML)

    # share version for the online link: same page without the outer document tags (the host adds them)
    share = re.sub(r"(?is)^\s*<!doctype html>\s*<html[^>]*>\s*<head>\s*", "", html, count=1)
    share = re.sub(r'(?is)<meta charset="utf-8">\s*<meta name="viewport"[^>]*>\s*', "", share, count=1)
    share = re.sub(r"(?is)</head>\s*<body>", "", share, count=1)
    share = re.sub(r"(?is)</body>\s*</html>\s*$", "", share, count=1)
    if SHARE_HTML:
        os.makedirs(os.path.dirname(SHARE_HTML), exist_ok=True)
        with open(SHARE_HTML, "w", encoding="utf-8") as f:
            f.write(share)
        size_mb = os.path.getsize(SHARE_HTML) / 1e6
        if size_mb > 15.5:
            log(f"⚠ Ukuran dashboard {size_mb:.1f} MB, mendekati batas 16 MB untuk link Claude.")

    if OUT_CSV:
        cols = ["id", "tanggal", "jam", "lokasi", "pengamat", "kategori", "kelompok", "nama_lokal", "nama_ilmiah",
                "saran_identifikasi", "status_verifikasi", "lat", "lon", "cek_koordinat"]
        with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(recs)
    missing = sorted({r["spesies_key"] for r in recs} - set(facts))
    return missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", help="(untuk uji coba) folder berisi asset.json & data.json, tanpa akses internet")
    ap.add_argument("--out", help="(GitHub Pages) folder tujuan; dashboard ditulis sebagai index.html, tanpa CSV dan versi share")
    args = ap.parse_args()
    global CACHE, OUT_HTML, OUT_CSV, SHARE_HTML
    if args.fixture:  # test mode: keep cache & outputs inside the fixture folder
        CACHE = os.path.join(args.fixture, "cache_foto")
        OUT_HTML = os.path.join(args.fixture, "Dashboard_test.html")
        OUT_CSV = os.path.join(args.fixture, "data_test.csv")
        SHARE_HTML = os.path.join(args.fixture, "share_test.html")
    if args.out:  # website build: only the public page
        os.makedirs(args.out, exist_ok=True)
        OUT_HTML = os.path.join(args.out, "index.html")
        OUT_CSV = SHARE_HTML = None
    os.makedirs(CACHE, exist_ok=True)
    log("🌊 Sea the Hotspot: update dashboard")

    if args.fixture:
        asset = json.load(open(os.path.join(args.fixture, "asset.json"), encoding="utf-8"))
        rows = json.load(open(os.path.join(args.fixture, "data.json"), encoding="utf-8"))
        kobo = None
    else:
        cp = configparser.ConfigParser()
        cp.read(os.path.join(HERE, "kobo_config.ini"), encoding="utf-8")
        cfg = dict(cp["kobo"]) if cp.has_section("kobo") else {}
        # environment variables win (used by GitHub Actions, where the key is a repository secret)
        for key, env in (("token", "KOBO_TOKEN"), ("server", "KOBO_SERVER"), ("asset_uid", "KOBO_ASSET_UID")):
            if os.environ.get(env):
                cfg[key] = os.environ[env].strip()
        cfg.setdefault("server", "https://kf.kobotoolbox.org")
        if not cfg.get("asset_uid"):
            log("✗ ID project Kobo (asset_uid) belum diisi.")
            return 1
        if not cfg.get("token") or "TEMPEL" in cfg.get("token", ""):
            log("✗ API key Kobo belum diisi. Buka update\\kobo_config.ini lalu isi baris 'token =' "
                "(di GitHub: Settings > Secrets > KOBO_TOKEN). Lihat panduannya.")
            return 1
        log("• Mengambil data dari KoboToolbox...")
        try:
            asset, rows, kobo = load_from_kobo(cfg)
        except urllib.error.HTTPError as e:
            log(f"✗ Kobo menolak permintaan ({e.code}). Cek API key dan asset_uid di kobo_config.ini.")
            return 1
        except Exception as e:  # noqa: BLE001
            log(f"✗ Tidak bisa terhubung ke Kobo: {e}. Cek koneksi internet.")
            return 1
    log(f"• {len(rows)} data diterima. Menyiapkan foto (foto baru akan diunduh)...")
    recs, skipped = build_records(asset, rows, kobo)
    missing = write_outputs(recs)
    log(f"✓ Dashboard diperbarui: {len(recs)} pengamatan" + (f" ({skipped} dilewati: ditolak panitia / tanpa lokasi)" if skipped else ""))
    log(f"  → {OUT_HTML}")
    if missing:
        log("ℹ Jenis tanpa fakta seru (bisa ditambahkan di update\\fakta_biota.json):")
        for k in missing:
            log(f"   - {k}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
