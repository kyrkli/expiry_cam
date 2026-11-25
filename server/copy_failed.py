import os
import shutil

# Список нераспознанных файлов
failed_files = [
    "006_frame_00-03-2027_18h14m07s.jpg", "007_frame_00-03-2027_18h14m18s.jpg",
    "013_frame_00-09-2025_17h29m50s.jpg", "015_frame_00-09-2025_17h31m11s.jpg",
    "016_frame_00-09-2025_17h31m35s.jpg", "024_frame_03-06-0000_17h47m01s.jpg",
    "027_frame_04-12-2027_18h30m31s.jpg", "030_frame_05-08-2027_17h02m44s.jpg",
    "031_frame_05-08-2027_17h03m05s.jpg", "039_frame_09-06-2026_17h52m08s.jpg",
    "040_frame_09-06-2026_17h52m18s.jpg", "041_frame_12-06-0000_17h43m35s.jpg",
    "042_frame_12-06-0000_17h43m47s.jpg", "043_frame_12-06-0000_17h43m59s.jpg",
    "044_frame_12-06-0000_17h44m14s.jpg", "047_frame_13-04-2027_17h17m31s.jpg",
    "049_frame_15-09-2026_17h36m50s.jpg", "050_frame_15-09-2026_17h37m57s.jpg",
    "051_frame_15-09-2026_17h38m29s.jpg", "052_frame_15-09-2026_17h39m03s.jpg",
    "062_frame_22-03-2029_18h41m10s.jpg", "063_frame_22-03-2029_18h41m22s.jpg",
    "065_frame_24-09-2026_18h35m12s.jpg", "066_frame_24-09-2026_18h35m22s.jpg",
    "067_frame_24-09-2026_18h35m41s.jpg", "068_frame_24-09-2026_18h35m59s.jpg",
    "071_frame_27-07-2026_16h40m07s.jpg", "072_frame_27-07-2026_16h41m55s.jpg",
    "074_frame_28-11-2028_18h07m45s.jpg", "080_frame_29-02-2028_17h25m27s.jpg",
    "082_frame_30-05-2029_17h56m37s.jpg", "083_frame_30-05-2029_17h56m48s.jpg",
    "087_frame_30-10-2027_18h04m22s.jpg", "088_frame_30-10-2027_18h04m43s.jpg",
    "093_frame_31-05-2028_18h00m46s.jpg", "094_frame_31-05-2028_18h00m54s.jpg",
    "095_frame_31-05-2028_18h01m13s.jpg", "096_frame_31-05-2028_18h01m50s.jpg",
    "098_frame_31-10-2027_16h44m52s.jpg"
]

source_dir = "dataset"
target_dir = "unsuccessful_parse"

os.makedirs(target_dir, exist_ok=True)

copied = 0
for f in failed_files:
    src_path = os.path.join(source_dir, f)
    dst_path = os.path.join(target_dir, f)
    
    if os.path.exists(src_path):
        shutil.copy2(src_path, dst_path)
        copied += 1
    else:
        print(f"Файл не найден в {source_dir}: {f}")

print(f"Готово! Скопировано {copied} файлов в папку {target_dir}")