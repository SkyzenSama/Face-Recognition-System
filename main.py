"""
Yüz Tanıma Yoklama Sistemi - Ana Çalıştırma Dosyası
Bitirme Projesi

Kullanım:
    python main.py

Gereksinimler:
    - Python 3.8+
    - cryptography (AES-GCM şifreleme için, ZORUNLU)
    - OpenCV (cv2)
    - Pillow
    - tkinter (Python ile birlikte gelir)
    - face_recognition (opsiyonel, daha iyi tanıma için)
"""

import sys
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))


def check_dependencies():
    """Bağımlılıkları kontrol et."""
    missing = []

    try:
        import cryptography  # noqa: F401
        print("✓ cryptography yüklü (AES-GCM şifreleme aktif)")
    except ImportError:
        missing.append("cryptography")
        print("✗ cryptography bulunamadı (BİYOMETRİK ŞİFRELEME İÇİN GEREKLİ)")

    try:
        import cv2
        print(f"✓ OpenCV yüklü (versiyon: {cv2.__version__})")
    except ImportError:
        missing.append("opencv-python")
        print("✗ OpenCV bulunamadı")

    try:
        import numpy
        print(f"✓ NumPy yüklü (versiyon: {numpy.__version__})")
    except ImportError:
        missing.append("numpy")
        print("✗ NumPy bulunamadı")

    try:
        import PIL  # noqa: F401
        print("✓ Pillow yüklü")
    except ImportError:
        missing.append("Pillow")
        print("✗ Pillow bulunamadı")

    try:
        import face_recognition  # noqa: F401
        print("✓ face_recognition yüklü (gelişmiş yüz tanıma aktif)")
    except ImportError:
        print("○ face_recognition bulunamadı (temel yüz tanıma kullanılacak)")

    try:
        import tkinter  # noqa: F401
        print("✓ Tkinter yüklü")
    except ImportError:
        missing.append("tkinter")
        print("✗ Tkinter bulunamadı")

    if missing:
        print("\n" + "=" * 50)
        print("EKSİK BAĞIMLILIKLAR!")
        print("=" * 50)
        print("Aşağıdaki paketleri yükleyin:")
        print(f"pip install {' '.join(missing)}")
        print("=" * 50)
        return False

    return True


def main():
    print("=" * 50)
    print("YÜZ TANIMA YOKLAMA SİSTEMİ")
    print("Bitirme Projesi")
    print("=" * 50)
    print()

    print("Bağımlılıklar kontrol ediliyor...")
    print("-" * 30)

    if not check_dependencies():
        print("\nBağımlılıkları yükledikten sonra tekrar çalıştırın.")
        input("Çıkmak için Enter'a basın...")
        sys.exit(1)

    print("-" * 30)
    print("\nUygulama başlatılıyor...")
    print()

    # 1) Güvenlik modülünü hazırla (master key yoksa oluştur)
    import security
    if not security.is_available():
        print("✗ Güvenlik modülü aktif değil. Çıkılıyor.")
        sys.exit(1)
    print(f"✓ Master key konumu: {security.get_key_location()}")
    print("  (Bu dosyayı KAYBETMEYİN, YEDEKLEYİN, proje klasörüne kopyalamayın!)")

    # 2) Veritabanı + migration (plaintext encoding varsa şifrelenir)
    import database as db
    db.init_database()
    db.init_default_data()
    print("✓ Veritabanı hazır")

    # 3) Şifreli fotoğraf klasörü + eski faces/user_X.jpg migration
    import face_module as fm
    fm.ensure_faces_dir()
    fm.migrate_legacy_photos()
    print("✓ Yüz kayıt klasörü hazır")

    # 4) GUI başlat
    from gui import AttendanceSystem
    print("✓ Arayüz yüklendi")
    print()
    print("=" * 50)
    print("Uygulama açılıyor...")
    print("=" * 50)

    app = AttendanceSystem()
    app.run()


if __name__ == "__main__":
    main()
