# OCR research

Experiments that led to the OCR pipeline in `server/ocr/`: a labelled dataset of expiry date
photos, a benchmark and helper scripts. Nothing here runs in production.

## Files

| File | What it does |
|---|---|
| `benchmark.py` | runs the OCR pipeline on every photo in `dataset/`, compares with the date in the filename, prints accuracy per category and the median time |
| `collect_data.py` | takes photos with `rpicam-still` and saves them into `dataset/` |
| `copy_failed.py` | copies the photos the OCR got wrong into `unsuccessful_parse/` |
| `_paths.py` | shared paths; puts the server code (`core/`, `ocr/`) on `sys.path` |

`dataset/`, `unsuccessful_parse/` and `bench.db` stay on the Pi 5 and are not in git.
The benchmark writes into its own `bench.db`, never into the real product list.

## Running on the Pi 5

The research folder lives inside the server folder on the Pi 5, so it uses the same venv and
the same OCR code:

```bash
# on the PC, from the repo root
./deploy.sh research

# on the Pi 5 (once: move the dataset from its old place)
mv ~/expiry_cam/dataset ~/expiry_cam/unsuccessful_parse ~/expiry_cam/ocr_research/ 2>/dev/null

cd ~/expiry_cam
.venv/bin/python ocr_research/benchmark.py
```

## Dataset

File name: `<number>_<tags>_frame_<DD-MM-YYYY>_<time>.jpg`, the date is the ground truth
(`00` = no day, `0000` = no year).

| Tag | Meaning | Count |
|-----|---------|-------|
| `blur` | blurred expiry date, bad focus | 16 |
| `curv` | curved expiry date | 3 |
| `diag` | expiry date written diagonally | 58 |
| `dot` | expiry date written in dots | 43 |
| `glare` | glare, too bright | 12 |
| `inv` | expiry date upside down | 31 |
| `lowc` | low contrast | 15 |
| `norm` | ideal photo | 9 |
| `vert` | expiry date written vertically | 8 |

Photos were taken with (the scanner now uses 2304×1296, see the main README):

```
rpicam-still --autofocus-mode auto --autofocus-range macro --nopreview --timeout 2500
             --width 4608 --height 2592 --sharpness 1.2 --quality 100 --denoise cdn_off
```

`--ev -1.5` can reduce glare but not reliably; a polarizing filter on the lens works best.

## Best result

```
Overall accuracy: 70/100 (70.00%)

Accuracy by category (tags):
[ blur  ] : 10/16 ( 62.50%)
[ curv  ] :  3/ 3 (100.00%)
[ diag  ] : 37/58 ( 63.79%)
[  dot  ] : 27/43 ( 62.79%)
[ glare ] :  3/12 ( 25.00%)
[  inv  ] : 20/31 ( 64.52%)
[ lowc  ] :  9/15 ( 60.00%)
[ norm  ] :  8/ 9 ( 88.89%)
[ vert  ] :  5/ 8 ( 62.50%)

Median analysis time: 3.411 s across 100 images
```

Unsuccessful parses in that run:

```
006_diag_frame_00-03-2027_18h14m07s.jpg
008_inv-diag_frame_00-03-2027_18h14m33s.jpg
013_glare-dot_frame_00-09-2025_17h29m50s.jpg
016_dot-vert_frame_00-09-2025_17h31m35s.jpg
024_blur_frame_03-06-0000_17h47m01s.jpg
025_norm_frame_04-12-2027_18h29m53s.jpg
030_dot-inv-diag_frame_05-08-2027_17h02m44s.jpg
038_diag_frame_09-06-2026_17h51m52s.jpg
039_diag_frame_09-06-2026_17h52m08s.jpg
041_dot-glare-diag_frame_12-06-0000_17h43m35s.jpg
042_dot-glare-diag_frame_12-06-0000_17h43m47s.jpg
044_dot-inv-diag-blur_frame_12-06-0000_17h44m14s.jpg
049_dot-lowc-inv-diag-blur_frame_15-09-2026_17h36m50s.jpg
050_dot-lowc-inv-diag-glare_frame_15-09-2026_17h37m57s.jpg
051_dot-lowc-vert-glare-blur_frame_15-09-2026_17h38m29s.jpg
052_dot-lowc-inv-diag-glare_frame_15-09-2026_17h39m03s.jpg
058_diag_frame_21-07-2027_18h19m05s.jpg
063_blur-diag_frame_22-03-2029_18h41m22s.jpg
065_lowc_frame_24-09-2026_18h35m12s.jpg
067_lowc-diag_frame_24-09-2026_18h35m41s.jpg
072_dot-diag-inv_frame_27-07-2026_16h41m55s.jpg
074_dot-diag-inv_frame_28-11-2028_18h07m45s.jpg
083_vert_frame_30-05-2029_17h56m48s.jpg
087_glare-inv-diag_frame_30-10-2027_18h04m22s.jpg
089_diag_frame_31-03-2029_17h26m42s.jpg
090_diag_frame_31-03-2029_17h26m53s.jpg
093_dot_frame_31-05-2028_18h00m46s.jpg
094_dot-diag-glare_frame_31-05-2028_18h00m54s.jpg
095_dot-blur-diag-inv_frame_31-05-2028_18h01m13s.jpg
096_dot-glare-inv_frame_31-05-2028_18h01m50s.jpg
```
