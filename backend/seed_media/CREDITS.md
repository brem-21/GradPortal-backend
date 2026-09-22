# Background media

These files are the **seed set** only. Site media is managed by admins at
`/admin/media` and stored by core-api under `backend/.media`, so uploading a new
photograph extends the slideshow without a deploy.

`python -m scripts.bootstrap seed-media` (from `backend/`) imports the files here
into that store on a fresh install.

## Seed photographs

Source: **Pexels** (https://www.pexels.com) — free for commercial use, no
attribution required. Licence: https://www.pexels.com/license/

| File | Pexels ID | Subject |
| --- | --- | --- |
| `campus-walk.jpg` | 1454360 | Students with backpacks walking a campus path in autumn |
| `campus-building.jpg` | 2305098 | Red-brick university building behind a tree |
| `campus-lawn.jpg` | 6147369 | Two students studying together on a campus lawn |
| `library-study.jpg` | 1595391 | Study group around a laptop |
| `library-celebrate.jpg` | 8199562 | Students celebrating in a library |
| `study-desk.jpg` | 4778611 | Notebooks, notes and coffee on a desk |

All were re-graded locally to the Aker palette before being committed:
saturation dropped to ~0.30, a cool colour-balance shift, and a brightness
reduction so Paper-white text stays legible over them.

## Removed

The earlier landscape and code clips (`coastline`, `tide`, `code`) were dropped:
they were off-brief for a graduate portal and the surf footage read as a
waterfall. Everything shipping now is campus photography.

## Not used, deliberately

- **iStock / Getty** — paid stock. Using those images without buying a licence is
  copyright infringement, however the URL was obtained.
- **Google image-search (`gstatic`) thumbnails** — a cache of someone else's
  image. Low resolution, unstable URLs, unknown underlying rights.
