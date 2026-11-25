# Hardware

Wiring, pinout and lessons learned are in the main [README](../README.md#2-scanner-hardware).
This folder is for the KiCad project of the scanner (schematic, `.kicad_*` files) and the
parts list below.

## Main station

- Raspberry Pi 5, 8 GB RAM
- Active Cooler
- Raspberry Pi 27 W USB-C power supply
- microSD A2

## Scanner parts list

| Component | Choice | Note |
|-----------|--------|------|
| Compute (have, berrybase) | **Raspberry Pi 3A+** | 5 GHz Wi-Fi, native 15-pin CSI for Camera Module 3 (chosen over Zero 2 W) |
| microSD (have, amazon) | SanDisk 64 GB A2 Extreme microSDXC + SD adapter, up to 170 MB/s read | for the Raspberry Pi 3A+ |
| Camera (have, berrybase) | Raspberry Pi Camera Module 3 | IMX708, autofocus |
| Barcode (have, aliexpress) | WAVGAT GM67 UART module (~12 €) | UART, 3.3 V logic level |
| Trigger (have, ebay, not used) | Omron D2F-01L | |
| Trigger (have, amazon) | push button, ON while held | short = photo, long = barcode |
| Display (have) | 1.3" OLED I²C 128×64 (SH1106) | status, results, battery |
| [Power] Battery (have, akkuteile) | Keeppower 2S1P 18650 3400 mAh (NCR18650B, BMS 4–7 A) | 7.2 V nominal / 8.4 V full / cut-off 5.0 V; charge 8.4 V CC-CV (normal 1625 mA, fast 2380 mA); wires: red +, black −, white = temperature (isolated) |
| [Power] Power button (have, amazon) | push button, ON while held | hold = shutdown, double press = reboot |
| [Power] Buck converter (have, ebay) | Mini560 PRO 5 V 5 A + heatsink | synchronous buck, fixed 5.0 V out, about 3 A continuous (5 A only peak) |
| [Power] USB charging module (have, amazon) | Hailege 2S USB-C boost charger, 8.4 V CC/CV | "2S 2A" version; 2 A = input current, real charge current about 1.1 A |
| [Power] Switch (have, aliexpress) | rocker switch KCD3, 3 pins (ON-OFF-ON) | CHARGE / OFF / RUN |
| [Power] Battery monitor (have, amazon) | ADS1115 16-bit I²C ADC + divider 100k/47k (1 %) + 100 nF ceramic capacitor | battery voltage and charge level |
| [Power] JST-XH 2-pin kit (have, amazon) | 22 AWG | battery connection |
| [Power] Micro-USB plug (have, amazon) | with screw terminals | powers the Pi from the buck converter |
| [Build] Case (in progress) | 3D-printed wand / pistol grip | camera + GM67 at the nose, battery in the handle |
| [Build] Screws (have, amazon) | FandWay 900 pcs M2/M2.5/M3 | cylinder head hex socket (DIN 912 style) |
| [Build] Heat-set inserts (have, aliexpress) | 750 pcs brass, knurled, M2/M2.5/M3 | |
| [Build] Wires (have, amazon) | AWG 22 for power, AWG 28 for signals | solder I²C, no thin wires in WAGO clamps |
