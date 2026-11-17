# Sea the Hotspot: dashboard biota laut

Dashboard pengamatan biota laut Pantai Lendang Luar, Lombok. Halaman ini dibuat ulang
otomatis dari data KoboToolbox setiap 30 menit dan diterbitkan di GitHub Pages.

Isi repository:

| File | Fungsi |
|---|---|
| `.github/workflows/update-dashboard.yml` | Jadwal otomatis: ambil data Kobo, buat dashboard, terbitkan |
| `update/update_dashboard.py` | Skrip yang mengolah data Kobo menjadi dashboard |
| `update/template_dashboard.html` | Tampilan dashboard |
| `update/fakta_biota.json` | Fakta seru & peringatan per jenis biota (boleh diedit) |
| `update/leaflet-1.9.4.css` | Gaya peta |

Data pengamatan dan foto **tidak** disimpan di repository ini; semuanya diambil langsung dari Kobo
saat dashboard dibuat. API key Kobo disimpan sebagai *repository secret* bernama `KOBO_TOKEN`.

## Mengedit fakta seru

Buka `update/fakta_biota.json` di GitHub, klik ikon pensil, tambahkan atau ubah entri, lalu
**Commit changes**. Dashboard otomatis dibuat ulang dalam beberapa menit.

```json
"Nama ilmiah atau nama lokal": {
  "fakta": "Kalimat fakta seru untuk peserta.",
  "bahaya": ""
}
```

## Mengecek atau menjalankan update manual

Tab **Actions** > **Update dashboard**. Tanda centang hijau berarti berhasil. Untuk update saat itu juga,
klik **Run workflow**.
