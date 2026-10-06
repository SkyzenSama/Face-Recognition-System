"""
Yüz Tanıma Modülü - Yüz Tanıma Yoklama Sistemi
================================================

Bu modül hem kamera/yüz tanıma işlemlerini hem de KVKK uyumlu
biyometrik fotoğraf saklama mantığını içerir.

Fotoğraflar artık:
    - `secure_faces/<uuid>.enc` olarak tahmin edilemez adlarla tutulur
    - AES-256-GCM ile şifrelenir (görüntü içeriği disk üzerinde okunamaz)
    - associated_data = "user:<id>" → başka kullanıcıya kopyalanamaz

Eski `faces/user_{id}.jpg` dosyaları ilk açılışta otomatik migrate edilir:
şifrelenir, yeni konuma taşınır, orijinali silinir.
"""

import os
import shutil
from typing import Optional, Tuple

import cv2
import numpy as np

try:
    import face_recognition
    FACE_RECOGNITION_AVAILABLE = True
except ImportError:
    FACE_RECOGNITION_AVAILABLE = False
    print("face_recognition kütüphanesi bulunamadı. OpenCV Haar Cascade kullanılacak.")

import database as db
import security
import i18n
_ = i18n.t  # kısa kısayol: _("attendance.liveness_prompt") gibi kullanılabilir

# Eski (tahmin edilebilir) ve yeni (güvenli) dizinler
LEGACY_FACES_DIR = "faces"
SECURE_FACES_DIR = "secure_faces"


# ============================================================================
# Dizin ve Yol Yönetimi
# ============================================================================

def ensure_faces_dir():
    """Şifreli fotoğraf dizinini oluştur ve izinlerini kısıtla."""
    if not os.path.exists(SECURE_FACES_DIR):
        os.makedirs(SECURE_FACES_DIR)
    # Unix'te dizini yalnızca sahibinin okumasına izin ver
    if os.name != 'nt':
        try:
            os.chmod(SECURE_FACES_DIR, 0o700)
        except OSError:
            pass


def _secure_path(file_ref: str) -> str:
    """UUID referansından şifreli dosya yolunu türet."""
    # file_ref hex karakterlerden oluşmalı; güvenlik için sanitize
    safe = ''.join(ch for ch in file_ref if ch.isalnum())
    if safe != file_ref or not safe:
        raise ValueError(f"Geçersiz dosya referansı: {file_ref}")
    return os.path.join(SECURE_FACES_DIR, f"{safe}.enc")


# ============================================================================
# Şifreli Kayıt / Yükleme
# ============================================================================

def _save_encrypted_image(image_bgr: np.ndarray, user_id: int) -> str:
    """BGR görüntüyü PNG olarak encode et, şifrele, dosyaya yaz.
    Yeni dosya referansını (UUID hex) döndürür."""
    ensure_faces_dir()

    # Görüntüyü önce PNG bayt dizisine çevir (formatı korumak için)
    success, buffer = cv2.imencode('.png', image_bgr)
    if not success:
        raise IOError("Görüntü PNG olarak kodlanamadı.")
    raw_bytes = buffer.tobytes()

    # AES-GCM ile şifrele (AAD = user ID ki başka kullanıcıya taşınamasın)
    aad = f"user:{user_id}".encode('utf-8')
    encrypted = security.encrypt_bytes(raw_bytes, associated_data=aad)

    # Tahmin edilemez dosya adı üret ve yaz
    file_ref = security.generate_file_reference()
    path = _secure_path(file_ref)

    # Atomic write: önce .tmp'ye yaz, sonra rename
    tmp = path + ".tmp"
    with open(tmp, 'wb') as f:
        f.write(encrypted)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)

    # Unix'te dosya izinlerini kısıtla
    if os.name != 'nt':
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    return file_ref


def _load_encrypted_image(file_ref: str, user_id: int) -> Optional[np.ndarray]:
    """Şifreli dosyayı diskten oku, çöz, OpenCV BGR görüntüsüne dönüştür."""
    path = _secure_path(file_ref)
    if not os.path.exists(path):
        return None

    with open(path, 'rb') as f:
        encrypted = f.read()

    try:
        aad = f"user:{user_id}".encode('utf-8')
        raw_bytes = security.decrypt_bytes(encrypted, associated_data=aad)
    except Exception as e:
        print(f"⚠ user_id={user_id} için fotoğraf çözülemedi: {e}")
        db.audit_biometric(user_id, 'read_photo', False, str(e)[:200])
        return None

    # PNG bayt dizisini geri OpenCV matrisine çevir
    arr = np.frombuffer(raw_bytes, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    return image


def delete_user_photo(file_ref: Optional[str]) -> bool:
    """Şifreli fotoğraf dosyasını diskten sil (KVKK unutulma hakkı)."""
    if not file_ref:
        return False
    try:
        path = _secure_path(file_ref)
        if os.path.exists(path):
            # İçeriği üzerine yazarak silmek (best-effort secure delete).
            # Gerçek düşük seviyeli silme için OS desteği gerekir; bu iyi bir
            # minimum seviyedir.
            try:
                size = os.path.getsize(path)
                with open(path, 'r+b') as f:
                    f.write(b'\x00' * size)
                    f.flush()
                    os.fsync(f.fileno())
            except Exception:
                pass
            os.remove(path)
            return True
    except Exception as e:
        print(f"⚠ Fotoğraf silinirken hata: {e}")
    return False


# ============================================================================
# Eski faces/user_X.jpg Dosyalarını Migrate Et
# ============================================================================

def migrate_legacy_photos():
    """Eski `faces/user_{id}.jpg` dosyalarını tespit edip şifreli dizine taşı.

    İlk kez çalıştırıldığında bir kerelik yapılır. İdempotenttir: zaten
    migrate edilmiş olanlara dokunmaz."""
    if not os.path.isdir(LEGACY_FACES_DIR):
        return

    ensure_faces_dir()
    migrated = 0

    for fname in os.listdir(LEGACY_FACES_DIR):
        if not fname.startswith("user_") or not fname.endswith(".jpg"):
            continue
        try:
            # user_1.jpg → user_id = 1
            user_id_str = fname[len("user_"):-len(".jpg")]
            user_id = int(user_id_str)
        except ValueError:
            continue

        legacy_path = os.path.join(LEGACY_FACES_DIR, fname)

        # Kullanıcı hâlâ mevcut mu? Zaten bir ref'i var mı?
        user = db.get_user_by_id(user_id)
        if user is None:
            # Yetim dosya: kullanıcı yok. Güvenli tarafta kalıp dokunmayalım;
            # admin manuel incelesin. Ama log'a düşürelim.
            db.audit_biometric(None, 'migrate_skip_orphan', True, fname)
            continue
        if db.get_user_face_ref(user_id):
            # Zaten şifreli hali var, eski dosyayı sessizce sil
            try:
                os.remove(legacy_path)
            except OSError:
                pass
            continue

        try:
            image = cv2.imread(legacy_path)
            if image is None:
                continue
            file_ref = _save_encrypted_image(image, user_id)
            db.update_user_face_ref(user_id, file_ref)

            # Orijinal .jpg'yi üzerine yazarak sil
            try:
                size = os.path.getsize(legacy_path)
                with open(legacy_path, 'r+b') as f:
                    f.write(b'\x00' * size)
                    f.flush()
                    os.fsync(f.fileno())
            except Exception:
                pass
            os.remove(legacy_path)

            db.audit_biometric(user_id, 'migrate_photo', True,
                               f'faces/{fname} -> secure_faces/*.enc')
            migrated += 1
        except Exception as e:
            print(f"⚠ {fname} migrate edilemedi: {e}")
            db.audit_biometric(user_id, 'migrate_photo', False, str(e)[:200])

    if migrated:
        print(f"✓ {migrated} eski fotoğraf şifrelenip güvenli dizine taşındı.")

    # Eski dizin boşaldıysa sil
    try:
        if os.path.isdir(LEGACY_FACES_DIR) and not os.listdir(LEGACY_FACES_DIR):
            os.rmdir(LEGACY_FACES_DIR)
    except OSError:
        pass


# ============================================================================
# Canlılık Algılama (Liveness / Kafa Hareketi Kontrolü)
# ============================================================================
#
# Amaç: Vesikalık fotoğraf, telefon ekranındaki video veya çıktı tutularak
# yapılan sahte giriş (spoofing) denemelerini engellemek.
#
# Yöntem (yalnızca OpenCV Haar yüz sınıflandırıcısı ile, ek paket gerektirmez):
#   1. Her karede yüz tespit edilir ve yüz merkezinin konumu izlenir.
#   2. İlk kararlı yüz konumu "başlangıç (baseline)" olarak alınır.
#   3. Kullanıcı kafasını hafifçe oynattığında yüz merkezi başlangıç konumundan
#      uzaklaşır. Bu sapma, yüz genişliğine oranlanarak (mesafeden bağımsız)
#      ölçülür; küçük bir eşik aşıldığında canlılık doğrulanır.
# Sabit tutulan bir fotoğraf/ekran kıpırdamadığı için yüz merkezi sabit kalır,
# eşik aşılamaz ve canlılık kontrolü başarısız olur. Ufak bir hareket yeterlidir.

# Eşik parametreleri (donanım/ışığa göre ince ayarlanabilir)
LIVENESS_MOVE_RATIO = 0.08   # yüz genişliğine oranla gereken min. hareket (çok ufak)
LIVENESS_TIMEOUT = 10        # saniye cinsinden zaman aşımı


# Türkçe karakterler ve emoji OpenCV'nin Hershey fontlarında düzgün
# çizilemediği için kameraya basılacak metinler ASCII'ye indirgenir.
# (i18n metinleri yine doğru/çok dilli kalır; sadece kamera overlay'i sadeleşir.)
_TR_ASCII_MAP = str.maketrans({
    'ç': 'c', 'Ç': 'C', 'ğ': 'g', 'Ğ': 'G', 'ı': 'i', 'İ': 'I',
    'ö': 'o', 'Ö': 'O', 'ş': 's', 'Ş': 'S', 'ü': 'u', 'Ü': 'U',
})


def _ascii_safe(text: str) -> str:
    """Türkçe karakterleri ASCII'ye çevir, çizilemeyen sembolleri (emoji vb.) at.

    cv2.putText yalnızca temel Latin karakterleri çizebildiği için kamera
    penceresine yazılacak i18n metinleri bu fonksiyondan geçirilir.
    """
    if not text:
        return ""
    text = text.translate(_TR_ASCII_MAP)
    # Yalnızca cv2.putText'in güvenle çizebileceği basit ASCII karakterleri bırak
    return ''.join(ch for ch in text if 32 <= ord(ch) < 127)


def run_liveness_check(cap,
                       face_cascade: cv2.CascadeClassifier,
                       window_title: str,
                       timeout: int = LIVENESS_TIMEOUT,
                       move_ratio: float = LIVENESS_MOVE_RATIO) -> str:
    """Açık bir kamera (cap) üzerinde kafa hareketi tabanlı canlılık kontrolü yapar.

    Yüz tanıma/kayıt mantığından ÖNCE çağrılır ve kameradan kare tüketir.
    Yüz merkezinin başlangıç konumundan (yüz genişliğine oranlı) yeterince
    uzaklaşması canlılık kanıtı sayılır. Ufak bir kafa hareketi yeterlidir.

    Dönüş değerleri:
        'passed'    → canlılık doğrulandı (yeterli kafa hareketi algılandı)
        'timeout'   → süre içinde doğrulanamadı (muhtemel fotoğraf/spoof)
        'cancelled' → kullanıcı 'Q' ile iptal etti
        'no_camera' → kameradan kare okunamadı
    """
    import time

    baseline = None        # ilk kararlı yüz merkezi (cx, cy)
    baseline_w = None      # baz alınan yüz genişliği (normalizasyon için)
    max_disp = 0.0         # baz konumdan ölçülen en büyük oransal sapma
    start_time = time.time()

    prompt_txt = _ascii_safe(_('attendance.liveness_prompt'))

    while True:
        ret, frame = cap.read()
        if not ret:
            return 'no_camera'

        frame_flipped = cv2.flip(frame, 1)
        elapsed = time.time() - start_time
        if elapsed > timeout:
            return 'timeout'

        display = frame_flipped.copy()
        gray = cv2.cvtColor(frame_flipped, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, 1.3, 5)

        if len(faces) > 0:
            # En büyük yüzü baz al (kullanıcının kendisi)
            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
            cx, cy = x + w / 2.0, y + h / 2.0
            cv2.rectangle(display, (x, y), (x + w, y + h), (255, 200, 0), 2)

            if baseline is None:
                # İlk yüz konumunu başlangıç (baseline) olarak sabitle
                baseline = (cx, cy)
                baseline_w = float(max(w, 1))
            else:
                # Sapmayı yüz genişliğine oranla → kullanıcının kameraya
                # uzaklığından bağımsız, tutarlı bir ölçü elde edilir
                dx = abs(cx - baseline[0]) / baseline_w
                dy = abs(cy - baseline[1]) / baseline_w
                disp = max(dx, dy)
                if disp > max_disp:
                    max_disp = disp

        # --- Ekran bilgilendirmeleri ---
        cv2.putText(display, prompt_txt, (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        # Hareket ilerleme yüzdesi (0..100): kullanıcıya görsel geri bildirim
        progress = min(100, int((max_disp / move_ratio) * 100)) if move_ratio > 0 else 0
        cv2.putText(display,
                    _ascii_safe(_('attendance.liveness_progress', percent=progress)),
                    (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        remaining = max(0, int(timeout - elapsed))
        cv2.putText(display, f"Sure: {remaining}s | Q: Iptal", (10, 90),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 2)

        # Yeterli hareket toplandıysa doğrulandı
        if baseline is not None and max_disp >= move_ratio:
            cv2.putText(display, _ascii_safe(_('attendance.liveness_success')),
                        (10, 130), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
            cv2.imshow(window_title, display)
            cv2.waitKey(800)  # kullanıcı "doğrulandı" mesajını görsün
            return 'passed'

        cv2.imshow(window_title, display)
        key = cv2.waitKey(1) & 0xFF
        if key in (ord('q'), ord('Q')):
            return 'cancelled'


def _show_liveness_failure(window_title: str, frame=None) -> None:
    """Kamera penceresinde kırmızı renkle 'Canlılık Doğrulanamadı!' göster."""
    try:
        if frame is None:
            frame = np.zeros((240, 640, 3), dtype=np.uint8)
        cv2.putText(frame, _ascii_safe(_('attendance.liveness_failed')),
                    (10, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)
        cv2.imshow(window_title, frame)
        cv2.waitKey(1500)
    except Exception:
        pass


# ============================================================================
# Kameradan Yüz Yakala ve Kaydet
# ============================================================================

def capture_face_from_camera(user_id: Optional[int] = None,
                             window_title: str = "Yüz Kayıt"
                             ) -> Tuple[bool, Optional[np.ndarray], str]:
    """Kameradan yüz yakala. Başarılıysa (True, encoding, mesaj) döndürür.
    user_id verilirse fotoğraf şifreli olarak saklanır ve encoding DB'ye yazılır."""
    ensure_faces_dir()

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        if user_id is not None:
            db.audit_biometric(user_id, 'register_attempt', False, 'Kamera açılamadı')
        return False, None, "Kamera açılamadı!"

    face_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
    )

    # --- CANLILIK (LIVENESS) KONTROLÜ ---
    # Yüz kayıt mantığı tetiklenmeden önce kafa hareketi ile canlılık doğrulanır.
    # Statik fotoğrafla kayıt (spoofing) bu aşamada engellenir.
    liveness = run_liveness_check(cap, face_cascade, window_title)
    if liveness != 'passed':
        _show_liveness_failure(window_title)
        cap.release()
        cv2.destroyAllWindows()
        if liveness == 'cancelled':
            return False, None, _('attendance.liveness_cancelled')
        # timeout / no_camera → muhtemel fotoğraf; KVKK denetim günlüğüne yaz
        db.audit_biometric(user_id, 'liveness_failed', False,
                           "Kafa hareketi algılanamadı (Muhtemel Fotoğraf)")
        return False, None, _('attendance.liveness_failed')

    captured_frame = None
    face_encoding = None

    print("Yüzünüzü kameraya gösterin. 'SPACE' ile fotoğraf çekin, 'Q' ile iptal edin.")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame = cv2.flip(frame, 1)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, 1.3, 5)

        display_frame = frame.copy()
        for (x, y, w, h) in faces:
            cv2.rectangle(display_frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.putText(display_frame, "Yuz Tespit Edildi", (x, y - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        cv2.putText(display_frame, "SPACE: Kaydet | Q: Iptal", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        cv2.imshow(window_title, display_frame)
        key = cv2.waitKey(1) & 0xFF

        if key == ord(' '):
            if len(faces) == 1:
                captured_frame = frame.copy()

                if FACE_RECOGNITION_AVAILABLE:
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    face_locations = face_recognition.face_locations(rgb_frame)
                    if face_locations:
                        face_encoding = face_recognition.face_encodings(
                            rgb_frame, face_locations
                        )[0]
                else:
                    x, y, w, h = faces[0]
                    face_region = gray[y:y + h, x:x + w]
                    face_region = cv2.resize(face_region, (128, 128))
                    face_encoding = face_region.flatten().astype(float) / 255.0
                break
            elif len(faces) == 0:
                print("Yüz tespit edilemedi! Tekrar deneyin.")
            else:
                print("Birden fazla yüz tespit edildi! Tek başınıza olun.")
        elif key in (ord('q'), ord('Q')):
            break

    cap.release()
    cv2.destroyAllWindows()

    if captured_frame is not None and face_encoding is not None:
        if user_id is not None:
            try:
                # Eski şifreli fotoğrafı varsa sil
                old_ref = db.get_user_face_ref(user_id)
                if old_ref:
                    delete_user_photo(old_ref)

                # Yeni şifreli fotoğrafı kaydet
                file_ref = _save_encrypted_image(captured_frame, user_id)
                db.update_user_face_ref(user_id, file_ref)
                # Encoding'i şifreli sakla
                db.update_user_face(user_id, face_encoding)
                db.audit_biometric(user_id, 'register_camera', True)
            except Exception as e:
                print(f"⚠ Şifreli kayıt başarısız: {e}")
                db.audit_biometric(user_id, 'register_camera', False, str(e)[:200])
                return False, None, f"Kayıt sırasında hata: {e}"

        return True, face_encoding, "Yüz başarıyla kaydedildi!"

    if user_id is not None:
        db.audit_biometric(user_id, 'register_camera', False, 'Kayıt iptal/başarısız')
    return False, None, "Yüz kaydedilemedi!"


# ============================================================================
# Kameradan Yüz Tanı
# ============================================================================

def recognize_face_from_camera(timeout: int = 10):
    """Kameradan yüz tanı. Her deneme audit log'a yazılır."""
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        db.audit_biometric(None, 'recognize_attempt', False, 'Kamera açılamadı')
        return None, None, "Kamera açılamadı!"

    face_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
    )

    # Kayıtlı yüzleri al (encoding'ler şifreden çözülerek gelir)
    known_faces = db.get_all_face_encodings()
    if not known_faces:
        cap.release()
        db.audit_biometric(None, 'recognize_attempt', False, 'Kayıtlı yüz yok')
        return None, None, "Sistemde kayıtlı yüz bulunamadı!"

    known_encodings = [f['encoding'] for f in known_faces]
    known_ids = [f['id'] for f in known_faces]
    known_names = [f['name'] for f in known_faces]

    # Not: Canlılık (kafa hareketi) kontrolü YALNIZCA yüz KAYDI sırasında
    # yapılır (capture_face_from_camera). Yüz ile giriş/yoklamada kullanıcının
    # kimliği kayıtlı yüz koduyla zaten doğrulandığı için tekrar canlılık
    # testi istenmez; bu da girişi hızlandırır.

    recognized_id = None
    recognized_name = None

    import time
    start_time = time.time()

    print("Yüzünüzü kameraya gösterin...")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame = cv2.flip(frame, 1)
        elapsed = time.time() - start_time
        if elapsed > timeout:
            break

        display_frame = frame.copy()

        if FACE_RECOGNITION_AVAILABLE:
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            face_locations = face_recognition.face_locations(rgb_frame)

            if face_locations:
                face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)
                for (top, right, bottom, left), face_encoding in zip(face_locations, face_encodings):
                    matches = face_recognition.compare_faces(
                        known_encodings, face_encoding, tolerance=0.6
                    )
                    if True in matches:
                        match_index = matches.index(True)
                        recognized_id = known_ids[match_index]
                        recognized_name = known_names[match_index]
                        cv2.rectangle(display_frame, (left, top), (right, bottom), (0, 255, 0), 2)
                        cv2.putText(display_frame, recognized_name, (left, top - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                    else:
                        cv2.rectangle(display_frame, (left, top), (right, bottom), (0, 0, 255), 2)
                        cv2.putText(display_frame, "Taninmadi", (left, top - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        else:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, 1.3, 5)
            for (x, y, w, h) in faces:
                face_region = gray[y:y + h, x:x + w]
                face_region = cv2.resize(face_region, (128, 128))
                current_encoding = face_region.flatten().astype(float) / 255.0

                min_dist = float('inf')
                best_match = -1
                for i, known_enc in enumerate(known_encodings):
                    if len(known_enc) == len(current_encoding):
                        dist = np.linalg.norm(current_encoding - known_enc)
                        if dist < min_dist:
                            min_dist = dist
                            best_match = i

                threshold = 15.0
                if best_match >= 0 and min_dist < threshold:
                    recognized_id = known_ids[best_match]
                    recognized_name = known_names[best_match]
                    cv2.rectangle(display_frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
                    cv2.putText(display_frame, recognized_name, (x, y - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                else:
                    cv2.rectangle(display_frame, (x, y), (x + w, y + h), (0, 0, 255), 2)
                    cv2.putText(display_frame, "Taninmadi", (x, y - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

        remaining = int(timeout - elapsed)
        cv2.putText(display_frame, f"Kalan sure: {remaining}s | Q: Iptal", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.imshow("Yuz Tanima", display_frame)

        if recognized_id:
            cv2.waitKey(1500)
            break

        key = cv2.waitKey(1) & 0xFF
        if key in (ord('q'), ord('Q')):
            break

    cap.release()
    cv2.destroyAllWindows()

    if recognized_id:
        db.audit_biometric(recognized_id, 'recognize', True, 'Başarılı eşleşme')
        return recognized_id, recognized_name, "Yüz tanındı!"

    db.audit_biometric(None, 'recognize', False, 'Eşleşme bulunamadı')
    return None, None, "Yüz tanınamadı!"


# ============================================================================
# Dosyadan Yüz Kaydı (şifreli olarak saklanır)
# ============================================================================

def load_face_from_image(image_path: str):
    if not os.path.exists(image_path):
        return None

    image = cv2.imread(image_path)
    if image is None:
        return None

    if FACE_RECOGNITION_AVAILABLE:
        rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        face_locations = face_recognition.face_locations(rgb_image)
        if face_locations:
            return face_recognition.face_encodings(rgb_image, face_locations)[0]
    else:
        face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        )
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, 1.3, 5)
        if len(faces) > 0:
            x, y, w, h = faces[0]
            face_region = gray[y:y + h, x:x + w]
            face_region = cv2.resize(face_region, (128, 128))
            return face_region.flatten().astype(float) / 255.0

    return None


def register_face_from_file(user_id: int, image_path: str) -> Tuple[bool, str]:
    """Dosyadan yüz kaydı yap; fotoğraf şifreli olarak saklanır."""
    ensure_faces_dir()

    face_encoding = load_face_from_image(image_path)
    if face_encoding is None:
        db.audit_biometric(user_id, 'register_file', False, 'Yüz tespit edilemedi')
        return False, "Fotoğrafta yüz tespit edilemedi!"

    try:
        image = cv2.imread(image_path)
        if image is None:
            return False, "Fotoğraf okunamadı!"

        # Eski referansı temizle
        old_ref = db.get_user_face_ref(user_id)
        if old_ref:
            delete_user_photo(old_ref)

        file_ref = _save_encrypted_image(image, user_id)
        db.update_user_face_ref(user_id, file_ref)
        db.update_user_face(user_id, face_encoding)
        db.audit_biometric(user_id, 'register_file', True)
    except Exception as e:
        db.audit_biometric(user_id, 'register_file', False, str(e)[:200])
        return False, f"Şifreli kayıt başarısız: {e}"

    return True, "Yüz başarıyla kaydedildi!"


def get_user_photo(user_id: int):
    """Kullanıcının fotoğrafını şifreden çözerek BGR olarak döndür."""
    ref = db.get_user_face_ref(user_id)
    if not ref:
        return None
    return _load_encrypted_image(ref, user_id)


# ============================================================================
# KVKK: Unutulma Hakkı
# ============================================================================

def purge_user_biometrics(user_id: int) -> bool:
    """Kullanıcının tüm biyometrik verilerini kalıcı olarak sil
    (encoding + şifreli fotoğraf + audit kaydı)."""
    old_ref = db.delete_user_biometrics(user_id)
    if old_ref:
        delete_user_photo(old_ref)
    db.audit_biometric(user_id, 'purge_biometrics', True, 'KVKK unutulma hakkı uygulandı')
    return True


# ============================================================================
# Kamera Testi
# ============================================================================

def test_camera():
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Kamera açılamadı!")
        return False

    print("Kamera çalışıyor. 'Q' ile çıkın.")
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        cv2.imshow("Kamera Testi", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()
    return True


if __name__ == "__main__":
    print("Kamera testi başlatılıyor...")
    test_camera()
