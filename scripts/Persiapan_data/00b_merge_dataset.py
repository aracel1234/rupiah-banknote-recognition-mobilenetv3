import json
import os
import shutil

# 1. DEFINISI TARGET
target_categories = [
    {"id": 1, "name": "seribu"},
    {"id": 2, "name": "dua ribu"},
    {"id": 3, "name": "lima ribu"},
    {"id": 4, "name": "sepuluh ribu"},
    {"id": 5, "name": "dua puluh ribu"},
    {"id": 6, "name": "lima puluh ribu"},
    {"id": 7, "name": "seratus ribu"}
]

# 2. MAPPING LENGKAP (Berdasarkan list Anda)
category_mapping = {
    "1-rb": "seribu", "1000": "seribu", "1k": "seribu", "1ribu": "seribu", "seribu": "seribu",
    "2000": "dua ribu", "2k": "dua ribu", "2ribu": "dua ribu", "dua ribu": "dua ribu",
    "5000": "lima ribu", "5k": "lima ribu", "5ribu": "lima ribu", "lima ribu": "lima ribu",
    "10000": "sepuluh ribu", "10k": "sepuluh ribu", "10ribu": "sepuluh ribu", "sepuluh ribu": "sepuluh ribu",
    "20000": "dua puluh ribu", "20k": "dua puluh ribu", "20rb": "dua puluh ribu", "20ribu": "dua puluh ribu", "dua puluh ribu": "dua puluh ribu",
    "50000": "lima puluh ribu", "50k": "lima puluh ribu", "50ribu": "lima puluh ribu", "lima puluh ribu": "lima puluh ribu",
    "100000": "seratus ribu", "100k": "seratus ribu", "100ribu": "seratus ribu", "seratus ribu": "seratus ribu"
}

raw_base = "raw_data"
out_img_folder = "merged_dataset/all_images"
out_json = "merged_dataset/all_data_merged.json"

if not os.path.exists(out_img_folder): os.makedirs(out_img_folder)

new_images, new_annotations = [], []
img_id_gen, ann_id_gen = 1, 1
target_name_to_id = {c['name']: c['id'] for c in target_categories}

for ds in sorted(os.listdir(raw_base)):
    ds_path = os.path.join(raw_base, ds)
    if not os.path.isdir(ds_path): continue

    for split in ['train', 'valid', 'test']:
        split_path = os.path.join(ds_path, split)
        json_file = os.path.join(split_path, "_annotations.coco.json")
        
        if not os.path.exists(json_file): continue # Lewati jika folder test/valid tidak ada

        with open(json_file, 'r') as f:
            data = json.load(f)

        # Map ID lama ke Nama Target
        old_cat_id_to_name = {c['id']: category_mapping.get(c['name']) for c in data['categories']}
        old_img_id_to_new = {}

        for img in data['images']:
            new_filename = f"{ds}_{split}_{img['file_name']}"
            # Cek lokasi gambar: langsung di folder atau di dalam sub-folder 'image'
            src_path = os.path.join(split_path, img['file_name'])
            if not os.path.exists(src_path):
                src_path = os.path.join(split_path, "image", img['file_name'])

            if os.path.exists(src_path):
                shutil.copy(src_path, os.path.join(out_img_folder, new_filename))
                old_img_id_to_new[img['id']] = img_id_gen
                img.update({"id": img_id_gen, "file_name": new_filename})
                new_images.append(img)
                img_id_gen += 1

        for ann in data['annotations']:
            target_name = old_cat_id_to_name.get(ann['category_id'])
            if target_name and ann['image_id'] in old_img_id_to_new:
                ann.update({
                    "id": ann_id_counter,
                    "image_id": old_img_id_to_new[ann['image_id']],
                    "category_id": target_name_to_id[target_name]
                })
                new_annotations.append(ann)
                ann_id_gen += 1
    print(f"Selesai menggabungkan: {ds}")

with open(out_json, 'w') as f:
    json.dump({"images": new_images, "annotations": new_annotations, "categories": target_categories}, f)