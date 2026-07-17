# Expiry cam project
- Project for managing expiry dates on products using Raspberry Pi and camera module. The project captures images of expiry dates, processes them, and extracts the relevant information for further analysis. 
- User takes a photo of the expiry date using a hand scanner (to be developed) or a mobile phone, and the image is sent to the Raspberry Pi for processing. The system extracts the expiry date from the image, then user scans the product barcode and the system associates the expiry date with the product in a database. 
- Telegram bot is used for notifications and interaction with the user. It sends notifications about approaching expiry dates and allows users to query the status of products.

## Hardware structure
- Raspberry Pi 5, 8GB RAM
- Active Cooler
- Raspberry Pi 27W USB-C Power Supply
- MicroSD A2
- Raspberry Pi camera module v3 (temporary, to be replaced with a hand scanner)

### Scanner structure (to be developed)
- Microcontroller suited to take pictures by camera module and send it via wifi to main station (tba.)
- Raspberry Pi camera module v3
- 3D printed case with a button to take pictures
- NeoPixel Ring (WS2812B 12 or 16 diodes) (optional)
- Display to show the status of the scanner (tba.)
- Laser sensor to scan the barcode of the product (tba.)



## Capture settings
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