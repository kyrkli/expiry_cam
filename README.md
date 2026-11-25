# Expiry cam project
- Project for managing expiry dates on products using main station Raspberry Pi 5 and hand scanner. The project captures images of expiry dates, processes them, and extracts the relevant information for further analysis. 
- User takes a photo of the expiry date using a hand scanner (to be developed) or a mobile phone (outside of the scope currently), and the image is sent to the Raspberry Pi for processing. The system extracts the expiry date from the image, then user scans the product barcode and the system associates the expiry date with the product in a database. 
- Telegram bot is used for notifications and interaction with the user. It sends notifications about approaching expiry dates and allows users to query the status of products.

## System architecture
```
Hand scanner (Pi 3A+)                                          Main station (Pi 5, 8GB)
──────────────────────────────────────────────────────────────────────────────────────────────
[button] short press
  → rpicam-still capture   ──POST /image (JPEG, 5GHz WiFi)──▶  FastAPI ingest
[button] barcode trigger                                       → OCR pipeline (expiry date)
  → GM67 UART scan         ──POST /barcode (EAN-13)─────────▶  → Open Food Facts lookup

SQLite/Postgres DB
[OLED status]              ◀── ack / status ──                 → Telegram bot (notifications)
```

## Hardware structure
### Main station
- Raspberry Pi 5, 8GB RAM
- Active Cooler
- Raspberry Pi 27W USB-C Power Supply
- MicroSD A2

### Scanner component list

| Component | Choice | Note |
|-----------|--------|------|
| Compute (have, berrybase) | **Raspberry Pi 3A+** | 5 GHz WiFi, native 15-pin CSI for v3 (chosen over Zero 2 W) |
| MicroSD (have, amazon) | "SANDISK 64GB A2 Extreme microSDXC Card + SD Adapter, up to 170 MB/s Read" | For **Raspberry Pi 3A+** |
| Camera (have, berrybase) | Raspberry Pi Camera Module v3 | IMX708, autofocus |
| Barcode (have, aliexpress) | WAVGAT GM67 UART module (~12 €) | UART 3.3V Logic Level |
| Trigger (have, ebay, DIDNT USED) | Omron D2F-01L | Short = photo, long = barcode |
| Trigger (have, amazon) | Button Push & Hold-ON, Release-OFF | Short = photo, long = barcode |
| Display (have) | 1,3 Zoll OLED I2C 128x64 Pixel | WiFi / success / queue status, bad image |
| [Power] Accumulator (have, akkuteile) | Keeppower 2S1P 18650 3400 mAh (NCR18650B, BMS 4–7 A) | 7.2 V nom / 8.4 V full / cutoff 5.0 V; charge 8.4 V CC-CV (normal 1625 mA, fast 2380 mA); wires: red +, black −, white = Temp (isolated) |
| [Power] Power Button (have, amazon) | Button Push & Hold-ON, Release-OFF | 1 Long = Shutdown, 2 Short = Reboot |
| [Power] Buck Converter (have, eBay) | Mini560 PRO 5V 5A + heatsink | synchronous buck, fixed 5.0 V DC out, real continuous ~3 A (rated 5 A only peak) |
| [Power] USB Charging Module (have, amazon) | Hailege 2S USB-C boost charger, 8.4 V CC/CV | style "2S 2A" (2 pcs); "2A" = input current, real charge 1.1 A |
| [Power] Switch (have, aliexpress) | Rocker Switch 3 pin KCD3 | For modes {Power ON / Power OFF / Charge the device} |
| [Power] Battery charge status (have, amazon) | ADS1115 16-bit I2C ADC module + divider 100k/47k (1%) + 100nF Ceramic Capacitor | For monitoring battery voltage and charge level |
| [Power] JST-XH 2-pin kit (have, amazon) | 22 AWG | For connection betweenbattery and other components |
| [Power] Micro usb connector (have, amazon) | For powering raspberry pi via USB | |
| [Build] Case (develop) | 3D-printed wand/pistol grip | Camera + GM67 at nose, battery in the handle |
| [Build] Screws (have, amazon) | FandWay 900 pcs M2/M2.5/M3 | Cylinder head hex socket (DIN912-style) |
| [Build] Heat-set inserts (have, aliexpress) | | Kit 750 pcs brass knurled, 15 sizes, M2/M2.5/M3 only |
| [Build] Wires (have, amazon) | AWG 22 for power, AWG 28 for signals | |

## Capture settings/
```
command = [
    "rpicam-still",
    "--autofocus-mode", "auto",
    "--autofocus-range", "macro",
    "--nopreview",
    "--timeout", "2500",
    "--width", "4608",
    "--height", "2592",
    "--sharpness", "1.2",
    "--quality", "100",
    "--denoise", "cdn_off",
    "-o", save_path
]
```
- "--ev", "-1.5" could help to reduce glare, but it is not always effective. The best way to reduce glare is to use a polarizing filter on the camera lens.

## Data set
|Category|Meaning|Count|
|--------|-------|-----|
|[**blur**]|Blurred expiry date, bad focus|16|
|[**curv**]|Curved expiry date|3|
|[**diag**]|Expiry date written diagonally|58|
|[**dot**]|Expiry date written in dots|43|
|[**glare**]|Glare expiry date, too bright|12|
|[**inv**]|Expiry date written inverted, upside down|31|
|[**lowc**]|Low contrast of the expiry date|15|
|[**norm**]|Expiry date represented ideally|9|
|[**vert**]|Expiry date written vertically|8|

### Best result
```
==================================================
📊 FINAL ANALYTICS (SLICE-BASED EVALUATION)
==================================================
Overall accuracy: 70/100 (70.00%)

Accuracy by category (Tags):
----------------------------------------
[ blur  ] : 10/16 ( 62.50%)
[ curv  ] :  3/ 3 (100.00%)
[ diag  ] : 37/58 ( 63.79%)
[  dot  ] : 27/43 ( 62.79%)
[ glare ] :  3/12 ( 25.00%)
[  inv  ] : 20/31 ( 64.52%)
[ lowc  ] :  9/15 ( 60.00%)
[ norm  ] :  8/ 9 ( 88.89%)
[ vert  ] :  5/ 8 ( 62.50%)
----------------------------------------

List of unsuccessful parses:
 - 006_diag_frame_00-03-2027_18h14m07s.jpg
 - 008_inv-diag_frame_00-03-2027_18h14m33s.jpg
 - 013_glare-dot_frame_00-09-2025_17h29m50s.jpg
 - 016_dot-vert_frame_00-09-2025_17h31m35s.jpg
 - 024_blur_frame_03-06-0000_17h47m01s.jpg
 - 025_norm_frame_04-12-2027_18h29m53s.jpg
 - 030_dot-inv-diag_frame_05-08-2027_17h02m44s.jpg
 - 038_diag_frame_09-06-2026_17h51m52s.jpg
 - 039_diag_frame_09-06-2026_17h52m08s.jpg
 - 041_dot-glare-diag_frame_12-06-0000_17h43m35s.jpg
 - 042_dot-glare-diag_frame_12-06-0000_17h43m47s.jpg
 - 044_dot-inv-diag-blur_frame_12-06-0000_17h44m14s.jpg
 - 049_dot-lowc-inv-diag-blur_frame_15-09-2026_17h36m50s.jpg
 - 050_dot-lowc-inv-diag-glare_frame_15-09-2026_17h37m57s.jpg
 - 051_dot-lowc-vert-glare-blur_frame_15-09-2026_17h38m29s.jpg
 - 052_dot-lowc-inv-diag-glare_frame_15-09-2026_17h39m03s.jpg
 - 058_diag_frame_21-07-2027_18h19m05s.jpg
 - 063_blur-diag_frame_22-03-2029_18h41m22s.jpg
 - 065_lowc_frame_24-09-2026_18h35m12s.jpg
 - 067_lowc-diag_frame_24-09-2026_18h35m41s.jpg
 - 072_dot-diag-inv_frame_27-07-2026_16h41m55s.jpg
 - 074_dot-diag-inv_frame_28-11-2028_18h07m45s.jpg
 - 083_vert_frame_30-05-2029_17h56m48s.jpg
 - 087_glare-inv-diag_frame_30-10-2027_18h04m22s.jpg
 - 089_diag_frame_31-03-2029_17h26m42s.jpg
 - 090_diag_frame_31-03-2029_17h26m53s.jpg
 - 093_dot_frame_31-05-2028_18h00m46s.jpg
 - 094_dot-diag-glare_frame_31-05-2028_18h00m54s.jpg
 - 095_dot-blur-diag-inv_frame_31-05-2028_18h01m13s.jpg
 - 096_dot-glare-inv_frame_31-05-2028_18h01m50s.jpg

Median analysis time:
3.411s across 100 analyzed images
```