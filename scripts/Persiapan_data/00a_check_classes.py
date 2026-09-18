import json
import os

raw_data_path = "/home/aracel/Downloads/Skripsi/raw_data"
all_categories = set()

for ds in os.listdir(raw_data_path):
    ds_path = os.path.join(raw_data_path, ds)
    if os.path.isdir(ds_path):
        # Cek di folder mana saja (train, test, valid)
        for split in ['train', 'valid', 'test']:
            json_file = os.path.join(ds_path, split, "_annotations.coco.json")
            if os.path.exists(json_file):
                with open(json_file, 'r') as f:
                    data = json.load(f)
                    for cat in data['categories']:
                        all_categories.add(cat['name'])

print("Daftar semua kelas yang ditemukan di 10 dataset:")
for name in sorted(all_categories):
    print(f"- {name}")