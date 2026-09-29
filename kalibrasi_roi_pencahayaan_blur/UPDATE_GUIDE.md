# Update Project ke v0.3.0

Metode paling aman adalah mengganti source project dengan folder dari ZIP baru, bukan menimpa file satu per satu. Data hasil capture berada di penyimpanan aplikasi pada perangkat Android, bukan di folder source Android Studio, sehingga penggantian folder source tidak menghapus dataset pada HP.

## 1. Tutup project di Android Studio

Pastikan proses Gradle/build sudah berhenti.

## 2. Backup folder source lama

Contoh jika project lama berada di `~/Downloads/RupiahCalibrationCollector`:

```bash
cd ~/Downloads
mv RupiahCalibrationCollector RupiahCalibrationCollector_backup_v2
```

## 3. Extract ZIP v0.3.0

```bash
unzip RupiahCalibrationCollector_v3.zip
```

Jika folder hasil extract bernama `RupiahCalibrationCollector_v3`, ubah menjadi nama project biasa:

```bash
mv RupiahCalibrationCollector_v3 RupiahCalibrationCollector
```

## 4. Kembalikan file lokal build yang tidak disertakan ZIP

### local.properties

```bash
cp ~/Downloads/RupiahCalibrationCollector_backup_v2/local.properties \
   ~/Downloads/RupiahCalibrationCollector/local.properties
```

Lakukan hanya jika file tersebut memang ada pada project lama.

### Gradle Wrapper

ZIP tidak membawa binary `gradle-wrapper.jar`. Salin dari project lama yang sudah berhasil dibangun:

```bash
mkdir -p ~/Downloads/RupiahCalibrationCollector/gradle/wrapper

cp ~/Downloads/RupiahCalibrationCollector_backup_v2/gradle/wrapper/gradle-wrapper.jar \
   ~/Downloads/RupiahCalibrationCollector/gradle/wrapper/

cp ~/Downloads/RupiahCalibrationCollector_backup_v2/gradlew \
   ~/Downloads/RupiahCalibrationCollector/

cp ~/Downloads/RupiahCalibrationCollector_backup_v2/gradlew.bat \
   ~/Downloads/RupiahCalibrationCollector/

chmod +x ~/Downloads/RupiahCalibrationCollector/gradlew
```

Jika project lama tidak memiliki wrapper binary, salin dari `implementasi_android` yang menggunakan Gradle 8.9.

## 5. Pertahankan repository Git bila ada

Jika project lama sudah memiliki `.git`:

```bash
cp -a ~/Downloads/RupiahCalibrationCollector_backup_v2/.git \
      ~/Downloads/RupiahCalibrationCollector/
```

Lalu:

```bash
cd ~/Downloads/RupiahCalibrationCollector
git status
```

## 6. Buka project baru

Android Studio → Open → pilih:

```text
~/Downloads/RupiahCalibrationCollector
```

Jalankan Gradle Sync.

## 7. Build

```bash
cd ~/Downloads/RupiahCalibrationCollector
./gradlew clean
./gradlew assembleDebug
```

APK debug berada di:

```text
app/build/outputs/apk/debug/app-debug.apk
```

## 8. Update aplikasi pada HP tanpa menghapus data

Jangan uninstall aplikasi lama dan jangan Clear Data. `applicationId` tetap `id.ac.ub.rupiah.calibration`, sedangkan `versionCode` v0.3.0 sudah dinaikkan menjadi 3.

Dengan ADB:

```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

`-r` memperbarui aplikasi sambil mempertahankan data aplikasi. Jika Android Studio memakai tombol Run dengan signing debug yang sama, Android Studio juga dapat melakukan update langsung.

## 9. Verifikasi setelah update

Buka aplikasi dan cek:

- progress lama masih tampil;
- sampel lama masih berstatus `SAVED`;
- filter `Tersimpan` tersedia;
- ketuk sampel `SAVED` → pratinjau muncul;
- tombol `Hapus citra` tersedia;
- folder Drive yang sebelumnya dipilih masih memiliki izin; jika tidak, pilih kembali folder yang sama.

Jangan hapus folder backup sampai aplikasi v0.3.0 berhasil dibangun dan dijalankan di kedua perangkat.
