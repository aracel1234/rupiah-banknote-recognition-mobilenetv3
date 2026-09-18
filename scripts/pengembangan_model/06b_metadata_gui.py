"""GUI kecil untuk meninjau pool representative dataset Tahap 6."""
import argparse
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

import pandas as pd
from PIL import Image, ImageTk

EMISSION = ["unknown", "2016", "2022", "not_applicable"]
SIDE = ["unknown", "front", "back", "not_applicable"]
CONDITION = ["unknown", "normal", "lusuh", "terlipat", "not_applicable"]
OBJECT = ["unknown", "tangan", "dompet", "kartu", "nota_kertas", "buku", "layar", "kemasan", "latar_kosong", "lainnya", "not_applicable"]

class App:
    def __init__(self, root, csv_path, data_root):
        self.root, self.csv_path, self.data_root = root, Path(csv_path), Path(data_root)
        self.df = pd.read_csv(self.csv_path, dtype=str, keep_default_na=False)
        if "reviewed" not in self.df: self.df["reviewed"] = "False"
        self.i = 0; root.title("Tahap 6 Metadata Review")
        self.image = tk.Label(root); self.image.grid(row=0, column=0, rowspan=12, padx=10, pady=10)
        self.info = tk.Label(root, justify="left", anchor="w", font=("Sans", 10)); self.info.grid(row=0, column=1, columnspan=2, sticky="w")
        self.vars = {k: tk.StringVar() for k in ("emission_year","side","condition","object_group")}
        self.boxes = {}
        rows = [("Emission year","emission_year",EMISSION),("Side","side",SIDE),("Condition","condition",CONDITION),("Object group","object_group",OBJECT)]
        for r,(title,key,values) in enumerate(rows, start=2):
            tk.Label(root,text=title).grid(row=r,column=1,sticky="w")
            box = ttk.Combobox(root,textvariable=self.vars[key],values=values,state="readonly",width=20)
            box.grid(row=r,column=2,sticky="w"); self.boxes[key] = box
        self.auto = tk.Label(root, justify="left", anchor="w"); self.auto.grid(row=7,column=1,columnspan=2,sticky="w",pady=8)
        self.reviewed = tk.BooleanVar(); ttk.Checkbutton(root,text="Reviewed",variable=self.reviewed).grid(row=8,column=1,sticky="w")
        ttk.Button(root,text="← Previous",command=self.prev).grid(row=10,column=1,sticky="ew")
        ttk.Button(root,text="Save + Next →",command=self.next).grid(row=10,column=2,sticky="ew")
        ttk.Button(root,text="Save",command=self.save).grid(row=11,column=1,sticky="ew")
        ttk.Button(root,text="Next unreviewed",command=self.next_unreviewed).grid(row=11,column=2,sticky="ew")
        root.bind("<Left>", lambda e:self.prev()); root.bind("<Right>", lambda e:self.next())
        self.show()

    def save(self):
        for k,v in self.vars.items(): self.df.at[self.i,k] = v.get()
        self.df.at[self.i,"reviewed"] = str(bool(self.reviewed.get()))
        self.df.to_csv(self.csv_path,index=False)

    def show(self):
        r = self.df.iloc[self.i]; p = self.data_root / r.file_path
        try:
            im = Image.open(p).convert("RGB"); im.thumbnail((650,650)); self.photo = ImageTk.PhotoImage(im); self.image.configure(image=self.photo,text="")
        except Exception as e: self.image.configure(image="",text=f"Gagal membuka:\n{p}\n{e}")
        for k,v in self.vars.items(): v.set(r.get(k,"unknown"))
        self.reviewed.set(str(r.get("reviewed","False")).lower()=="true")
        self.info.configure(text=f"{self.i+1}/{len(self.df)}\nID: {r.sample_id}\nLabel: {r.label}\nSource: {r.source_id}\nGroup: {r.group_id}")
        self.auto.configure(text=("Auto proxy untuk SAMPLING (bukan ground truth fisik):\n"
            f"Brightness : {r.get('brightness_proxy','unknown')}  (mean={r.get('luminance_mean','')})\n"
            f"Orientation: {r.get('orientation_proxy','unknown')}  (aspect={r.get('aspect_ratio','')})\n"
            f"Scale      : {r.get('scale_proxy','unknown')}  (relative_area={r.get('relative_area','')})"))
        is_non = r.label == "nonuang"
        for box in self.boxes.values(): box.configure(state="readonly")
        if is_non:
            for key in ("emission_year","side","condition"):
                self.vars[key].set("not_applicable"); self.boxes[key].configure(state="disabled")
        else:
            self.vars["object_group"].set("not_applicable"); self.boxes["object_group"].configure(state="disabled")

    def next(self): self.save(); self.i=min(self.i+1,len(self.df)-1); self.show()
    def prev(self): self.save(); self.i=max(self.i-1,0); self.show()
    def next_unreviewed(self):
        self.save()
        for j in list(range(self.i+1,len(self.df)))+list(range(0,self.i)):
            if str(self.df.iloc[j].get("reviewed","False")).lower() != "true": self.i=j; self.show(); return
        messagebox.showinfo("Selesai","Semua baris sudah ditandai reviewed.")

def main():
    p=argparse.ArgumentParser(); p.add_argument("--csv",type=Path,required=True)
    p.add_argument("--root",type=Path,default=Path("/home/aracel/Downloads/Skripsi/persiapan_data")); a=p.parse_args()
    root=tk.Tk(); App(root,a.csv,a.root); root.mainloop()

if __name__ == "__main__": main()
