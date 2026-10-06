# 🎓 Yüz Tanıma Yoklama Sistemi

## Bitirme Projesi - Mühendislik Fakültesi

Bu uygulama, yüz tanıma teknolojisi kullanarak öğrenci ve personel yoklaması alan kapsamlı bir sistemdir.

---

## 📋 Özellikler

### Kullanıcı Rolleri

| Rol | Açıklama | Yetkiler |
|-----|----------|----------|
| **Admin** | Rektör, Dekan, Bölüm Başkanı | Tüm yetkiler: Kullanıcı yönetimi, yetki atama, tüm yoklamaları görme |
| **Akademisyen** | Hocalar | Öğrenci yoklamalarını görme, öğrenci ekleme/çıkarma, derslerini yönetme |
| **Personel** | Hademe, Teknisyen vb. | Kendi yoklamasını görme, ders programını görme |
| **Öğrenci** | Öğrenciler | Sadece kendi yoklamasını alma ve görme |

### Mekanlar
- 🏛️ **Mühendislik Fakültesi**
  - Z-17
  - Z-18
  - Z-20
  - Z-23
  - Computer Lab
  - 118 Amfi
  - 102 Amfi

### Varsayılan Kullanıcılar
1. **Selma Toker** - Öğrenci
2. **Emir Koray Çoban** - Personel (Tesisatçı)
3. **Ziya Karakaya** - Admin (Bölüm Başkanı)
4. **Rahmi Er** - Admin (Rektör)
5. **Güven Orkun Tanık** - Akademisyen (Yapay Zeka Dersi)

---

## 🚀 Kurulum

### Adım 1: Python Kurulumu
Python 3.8 veya üzeri gereklidir. [Python İndir](https://www.python.org/downloads/)

### Adım 2: Proje Dosyalarını İndirme
Tüm dosyaları bir klasöre kopyalayın:
```
face_attendance_system/
├── main.py
├── gui.py
├── database.py
├── face_module.py
├── requirements.txt
└── faces/          (otomatik oluşturulur)
```

### Adım 3: Bağımlılıkları Yükleme

**Windows (CMD veya PowerShell):**
```bash
cd face_attendance_system
pip install -r requirements.txt
```

**Veya tek tek:**
```bash
pip install opencv-python numpy Pillow
```

### Adım 4 (Opsiyonel): Gelişmiş Yüz Tanıma
Daha iyi yüz tanıma için `face_recognition` kütüphanesini kurun:

**Windows:**
1. Visual Studio Build Tools kurun
2. CMake kurun
3. ```pip install dlib face_recognition```

**Linux/Mac:**
```bash
pip install dlib face_recognition
```

---

## 💻 PyCharm'da Çalıştırma

### Yöntem 1: Direkt Çalıştırma
1. PyCharm'da `face_attendance_system` klasörünü açın
2. `main.py` dosyasını açın
3. Sağ tıklayıp **"Run 'main'"** seçin

### Yöntem 2: Konfigürasyon Oluşturma
1. **Run > Edit Configurations** menüsüne gidin
2. **+ > Python** tıklayın
3. **Script path:** `main.py` dosyasını seçin
4. **Working directory:** Proje klasörünü seçin
5. **OK** tıklayın ve çalıştırın

### Yöntem 3: Terminal'den
1. PyCharm'ın alt kısmındaki **Terminal** sekmesini açın
2. Şu komutu çalıştırın:
```bash
python main.py
```

---

## 📖 Kullanım Kılavuzu

### İlk Çalıştırma
1. Uygulama açıldığında giriş ekranı gelir
2. İlk olarak **"Yeni Yüz Kaydı"** ile kullanıcıların yüzlerini kaydedin
3. Sonra **"Yüz ile Giriş Yap"** ile sisteme girin

### Yüz Kaydı
1. Ana menüden **"Yeni Yüz Kaydı"** tıklayın
2. Listeden kullanıcı seçin
3. **Kameradan Kaydet** veya **Dosyadan Kaydet** seçin
4. Kamera açılınca yüzünüzü gösterin ve SPACE tuşuna basın

### Yoklama Alma (Öğrenci)
1. Yüz ile giriş yapın
2. Sol panelden bir sınıf seçin (örn: Z-17)
3. **"GİRİŞ YAP"** butonuna tıklayın
4. Kameraya yüzünüzü gösterin
5. "Sayın [İsim], Hoş Geldiniz!" mesajı görünür
6. Çıkışta **"ÇIKIŞ YAP"** butonunu kullanın

### Admin Paneli
- **Kullanıcı Yönetimi:** Yeni kullanıcı ekle/düzenle/sil
- **Yetki Yönetimi:** Kullanıcı rollerini değiştir
- **Ders Yönetimi:** Ders ekle, öğrenci ata
- **Tüm Yoklamalar:** Tarih aralığına göre filtreleme

### Akademisyen Paneli
- **Derslerim:** Verdiğiniz dersleri görün
- **Öğrenci Yoklamaları:** Öğrencilerin devamsızlığını takip edin
- **Öğrenci Yönetimi:** Öğrenci ekle/çıkar

### Personel Paneli
- **Yoklamalarım:** Kendi giriş/çıkış kayıtlarınız
- **Ders Programı:** Hangi sınıfta ne zaman ders var

---

## 🔧 Sorun Giderme

### "Kamera açılamadı" hatası
- Bilgisayarınızda webcam olduğundan emin olun
- Başka bir uygulama kamerayı kullanıyor olabilir, kapatın
- Kamera sürücülerinizi güncelleyin

### "Yüz tespit edilemedi" hatası
- Yeterli aydınlatma olduğundan emin olun
- Yüzünüzü kameraya düzgün gösterin
- Gözlük, maske gibi engelleyicileri çıkarın

### "face_recognition bulunamadı" uyarısı
- Bu normal bir uyarıdır, temel yüz tanıma çalışır
- Daha iyi tanıma için kurulum talimatlarına bakın

### Veritabanı Sıfırlama
`attendance_system.db` dosyasını silip uygulamayı yeniden başlatın.

---

## 📁 Dosya Yapısı

```
face_attendance_system/
├── main.py              # Ana çalıştırma dosyası
├── gui.py               # Tkinter arayüzü
├── database.py          # SQLite veritabanı işlemleri
├── face_module.py       # Yüz tanıma modülü
├── requirements.txt     # Bağımlılıklar
├── README.md            # Bu dosya
├── attendance_system.db # Veritabanı (otomatik oluşur)
└── faces/               # Yüz fotoğrafları klasörü
    ├── user_1.jpg
    ├── user_2.jpg
    └── ...
```

---

## 🛠️ Teknolojiler

- **Python 3.8+** - Ana programlama dili
- **Tkinter** - GUI framework
- **OpenCV** - Kamera ve görüntü işleme
- **face_recognition** - Yüz tanıma (opsiyonel)
- **SQLite** - Veritabanı

---

## 📝 Notlar

- Sistem her çalıştığında veritabanı kontrol edilir
- Silinen kullanıcılar "soft delete" ile işaretlenir (veriler kaybolmaz)
- Yüz fotoğrafları `faces/` klasöründe saklanır
- Kamera çözünürlüğü otomatik ayarlanır

---

## 📄 Lisans

Bu proje eğitim amaçlı geliştirilmiştir.

---

**Geliştirici:** [Adınız]  
**Tarih:** 2024  
**Kurum:** [Üniversiteniz]
