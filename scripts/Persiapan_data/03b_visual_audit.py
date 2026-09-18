import json
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import messagebox

import pandas as pd
from PIL import Image, ImageTk


DATA = Path("/home/aracel/Downloads/Skripsi/persiapan_data")
AUDIT_FILE = DATA / "03_curated/visual_audit.csv"
RESULT_FILE = DATA / "03_curated/visual_audit_reviewed.csv"
SUMMARY_FILE = DATA / "03_curated/visual_audit_result_summary.json"

MAX_WIDTH = 1100
MAX_HEIGHT = 650

EXCLUDE_REASONS = {
    "1": "wrong_label",
    "2": "object_incomplete",
    "3": "other_banknote_dominant",
    "4": "poor_visual_quality",
    "5": "invalid_object",
}


def load_data():
    path = RESULT_FILE if RESULT_FILE.exists() else AUDIT_FILE
    df = pd.read_csv(path)

    for col in ["decision", "notes", "exclude_reason", "reviewed_at"]:
        if col not in df.columns:
            df[col] = ""

    df[["decision", "notes", "exclude_reason", "reviewed_at"]] = (
        df[["decision", "notes", "exclude_reason", "reviewed_at"]]
        .fillna("")
        .astype(str)
    )

    return df


class AuditViewer:
    def __init__(self, root):
        self.root = root
        self.df = load_data()
        self.queue = self.make_queue()
        self.position = 0
        self.history = []
        self.waiting_reason = False
        self.photo = None

        root.title("Audit Visual Dataset Uang")
        root.geometry("1200x850")

        self.info = tk.Label(
            root,
            font=("Arial", 13),
            justify="left"
        )
        self.info.pack(pady=8)

        self.image_label = tk.Label(root)
        self.image_label.pack(expand=True)

        self.help_label = tk.Label(
            root,
            font=("Arial", 12),
            text=(
                "V = Valid    E = Exclude    R = Review    "
                "U = Undo    Q = Simpan & Keluar"
            )
        )
        self.help_label.pack(pady=10)

        root.bind("<Key>", self.handle_key)

        if not self.queue:
            self.finish()
        else:
            self.show_current()

    def make_queue(self):
        undecided = self.df.index[
            self.df["decision"].str.strip() == ""
        ].tolist()

        if undecided:
            return undecided

        # Jika semua sudah diperiksa, buka kembali yang masih review
        return self.df.index[
            self.df["decision"] == "review"
        ].tolist()

    def show_current(self):
        if self.position >= len(self.queue):
            self.finish()
            return

        idx = self.queue[self.position]
        row = self.df.loc[idx]

        image_path = DATA / row["file_path"]

        if not image_path.exists():
            self.df.at[idx, "decision"] = "exclude"
            self.df.at[idx, "exclude_reason"] = "missing_file"
            self.save()
            self.position += 1
            self.show_current()
            return

        image = Image.open(image_path).convert("RGB")
        image.thumbnail((MAX_WIDTH, MAX_HEIGHT))

        self.photo = ImageTk.PhotoImage(image)
        self.image_label.configure(image=self.photo)

        total_done = (
            self.df["decision"].str.strip() != ""
        ).sum()

        self.info.configure(
            text=(
                f"Audit {self.position + 1} / {len(self.queue)}"
                f"     |     Total tersimpan: {total_done}"
                f" / {len(self.df)}\n"
                f"Kelas: Rp{row['label']}"
                f"     |     Alasan audit: {row['audit_reason']}\n"
                f"{row['sample_id']}"
            )
        )

        self.help_label.configure(
            text=(
                "V = Valid    E = Exclude    R = Review    "
                "U = Undo    Q = Simpan & Keluar"
            )
        )

        self.waiting_reason = False

    def handle_key(self, event):
        key = event.keysym.lower()

        if self.waiting_reason:
            if key in EXCLUDE_REASONS:
                self.record(
                    "exclude",
                    EXCLUDE_REASONS[key]
                )
            elif key == "escape":
                self.waiting_reason = False
                self.show_current()
            return

        if key == "v":
            self.record("valid")

        elif key == "r":
            self.record("review")

        elif key == "e":
            self.waiting_reason = True
            self.help_label.configure(
                text=(
                    "ALASAN EXCLUDE: "
                    "1 = Label salah   "
                    "2 = Uang terpotong   "
                    "3 = Uang lain dominan   "
                    "4 = Kualitas buruk   "
                    "5 = Objek tidak valid   "
                    "Esc = Batal"
                )
            )

        elif key == "u":
            self.undo()

        elif key == "q":
            self.save()
            self.write_summary()
            self.root.destroy()

    def record(self, decision, reason=""):
        idx = self.queue[self.position]

        self.history.append(idx)

        self.df.at[idx, "decision"] = decision
        self.df.at[idx, "exclude_reason"] = reason
        self.df.at[idx, "reviewed_at"] = (
            datetime.now().isoformat(timespec="seconds")
        )

        self.save()

        self.position += 1
        self.show_current()

    def undo(self):
        if not self.history:
            return

        idx = self.history.pop()

        self.df.at[idx, "decision"] = ""
        self.df.at[idx, "exclude_reason"] = ""
        self.df.at[idx, "reviewed_at"] = ""

        if self.position > 0:
            self.position -= 1

        self.save()
        self.show_current()

    def save(self):
        self.df.to_csv(RESULT_FILE, index=False)

    def write_summary(self):
        decisions = self.df["decision"].str.strip()

        total = len(self.df)
        valid = int((decisions == "valid").sum())
        excluded = int((decisions == "exclude").sum())
        review = int((decisions == "review").sum())
        pending = int((decisions == "").sum())
        reviewed = total - pending

        def pct(value, denominator):
            if denominator == 0:
                return 0.0
            return round(value / denominator * 100, 2)

        reason_counts = (
            self.df.loc[
                self.df["decision"] == "exclude",
                "exclude_reason"
            ]
            .value_counts()
            .to_dict()
        )

        summary = {
            "audit_required": total,
            "reviewed": reviewed,
            "pending": pending,
            "completion_percent": pct(reviewed, total),

            "valid": valid,
            "valid_percent_of_reviewed": pct(valid, reviewed),

            "excluded": excluded,
            "excluded_percent_of_reviewed": pct(
                excluded, reviewed
            ),

            "review": review,
            "review_percent_of_reviewed": pct(
                review, reviewed
            ),

            "exclude_reasons": reason_counts,
        }

        with open(
            SUMMARY_FILE,
            "w",
            encoding="utf-8"
        ) as f:
            json.dump(
                summary,
                f,
                indent=2,
                ensure_ascii=False
            )

    def finish(self):
        self.save()
        self.write_summary()

        decisions = self.df["decision"].str.strip()
        review_count = int((decisions == "review").sum())
        pending = int((decisions == "").sum())

        if pending == 0 and review_count == 0:
            messagebox.showinfo(
                "Audit selesai",
                "Seluruh sampel telah memperoleh keputusan final."
            )
            self.root.destroy()

        elif pending == 0 and review_count > 0:
            messagebox.showinfo(
                "Putaran pertama selesai",
                f"Masih terdapat {review_count} sampel berstatus "
                "review.\n\nJalankan kembali program untuk "
                "memeriksa sampel tersebut."
            )
            self.root.destroy()


root = tk.Tk()
app = AuditViewer(root)
root.mainloop()