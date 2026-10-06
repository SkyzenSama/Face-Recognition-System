"""
Veritabanı Modülü - Yüz Tanıma Yoklama Sistemi
===============================================

KVKK uyumlu biyometrik veri saklama:
    - face_encoding artık AES-256-GCM ile şifrelenmiş (base64 metin) olarak saklanır
    - face_image_ref (UUID) kolonu: secure_faces/<ref>.enc şifreli dosyasına işaret eder
    - biometric_audit_log tablosu: her biyometrik erişim kaydedilir
    - Eski plaintext verileri otomatik olarak şifreleyen migration

Tüm biyometrik erişimler audit_biometric() üzerinden logalanır.
"""

import sqlite3
import os
import json
import base64
import struct
from datetime import datetime
from typing import Optional

import numpy as np

import security  # yeni güvenlik modülü

DATABASE_PATH = "attendance_system.db"


def get_connection():
    """Veritabanı bağlantısı oluştur."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ============================================================================
# Şema Oluşturma ve Migration
# ============================================================================

def _table_has_column(cursor, table: str, column: str) -> bool:
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())


def init_database():
    """Veritabanını başlat, tabloları oluştur, gerekirse eski şemayı yükselt."""
    conn = get_connection()
    cursor = conn.cursor()

    # Kullanıcılar tablosu
    #   face_encoding: AES-GCM ciphertext, base64 kodlu
    #   face_image_ref: UUID → secure_faces/<ref>.enc
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin', 'akademisyen', 'personel', 'ogrenci')),
            sub_role TEXT,
            face_encoding TEXT,
            face_image_ref TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active INTEGER DEFAULT 1
        )
    ''')

    # Eski kurulumlar için: eksik kolonu ekle
    if not _table_has_column(cursor, 'users', 'face_image_ref'):
        cursor.execute("ALTER TABLE users ADD COLUMN face_image_ref TEXT")

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            parent_id INTEGER,
            location_type TEXT CHECK(location_type IN ('fakulte', 'sinif')),
            FOREIGN KEY (parent_id) REFERENCES locations(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            akademisyen_id INTEGER,
            location_id INTEGER,
            day_of_week TEXT,
            start_time TEXT,
            end_time TEXT,
            FOREIGN KEY (akademisyen_id) REFERENCES users(id),
            FOREIGN KEY (location_id) REFERENCES locations(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS course_students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER,
            student_id INTEGER,
            FOREIGN KEY (course_id) REFERENCES courses(id),
            FOREIGN KEY (student_id) REFERENCES users(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            location_id INTEGER,
            course_id INTEGER,
            check_in_time TIMESTAMP,
            check_out_time TIMESTAMP,
            date DATE DEFAULT (DATE('now', 'localtime')),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (location_id) REFERENCES locations(id),
            FOREIGN KEY (course_id) REFERENCES courses(id)
        )
    ''')

    # Sınıf koltuk düzeni: hangi öğrenci hangi koltukta oturuyor?
    # seat_id formatı: "R{row}_S{side}_{col}"  (örn: "R1_L_3" = 1. sıra, sol blok, 3. sütun)
    # UNIQUE(location_id, seat_id): bir koltuk aynı anda bir kişiye ait olsun
    # UNIQUE(location_id, student_id): bir öğrenci aynı sınıfta iki koltuğa oturamaz
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS classroom_seats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            location_id INTEGER NOT NULL,
            seat_id TEXT NOT NULL,
            student_id INTEGER NOT NULL,
            assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(location_id, seat_id),
            UNIQUE(location_id, student_id),
            FOREIGN KEY (location_id) REFERENCES locations(id),
            FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')

    # KVKK uyumlu biyometrik erişim denetim günlüğü
    # user_id_hash: gerçek user_id yerine HMAC-SHA256 saklanır
    # → log sızarsa hangi kullanıcının işlemi olduğu doğrudan görünmez,
    # ama aynı kullanıcının işlemleri yine birbirine bağlanabilir.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS biometric_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id_hash TEXT NOT NULL,
            operation TEXT NOT NULL,
            success INTEGER NOT NULL DEFAULT 1,
            detail TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.commit()
    conn.close()

    # Veri seviyesinde migration
    _migrate_plaintext_encodings_if_any()


def _migrate_plaintext_encodings_if_any():
    """Eski sürümden kalma plaintext JSON face_encoding değerlerini
    otomatik olarak AES-GCM ile şifrele ve aynı sütunda base64 olarak geri yaz.

    Döngü idempotenttir: zaten şifreli verilere dokunmaz."""
    if not security.is_available():
        return

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, face_encoding FROM users WHERE face_encoding IS NOT NULL")
    rows = cursor.fetchall()

    migrated = 0
    for row in rows:
        value = row['face_encoding']
        if not security.looks_like_plaintext_json_array(value):
            continue

        try:
            arr = np.array(json.loads(value))
            encrypted_b64 = _encrypt_encoding_array(arr, row['id'])
            cursor.execute(
                "UPDATE users SET face_encoding = ? WHERE id = ?",
                (encrypted_b64, row['id'])
            )
            _log_biometric_operation(
                cursor, row['id'], 'migrate_encrypt', True,
                'Plaintext JSON -> AES-GCM migration'
            )
            migrated += 1
        except Exception as e:
            print(f"⚠ Migration hatası (user_id={row['id']}): {e}")

    if migrated:
        conn.commit()
        print(f"✓ {migrated} kullanıcının biyometrik şablonu şifrelendi (migration).")
    conn.close()


def init_default_data():
    """Varsayılan verileri ekle."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] > 0:
        conn.close()
        return

    cursor.execute("INSERT INTO locations (name, parent_id, location_type) VALUES (?, ?, ?)",
                   ("Mühendislik Fakültesi", None, "fakulte"))
    fakulte_id = cursor.lastrowid

    siniflar = ["Z-17", "Z-18", "Z-20", "Z-23", "Computer Lab", "118 Amfi", "102 Amfi"]
    sinif_ids = {}
    for sinif in siniflar:
        cursor.execute("INSERT INTO locations (name, parent_id, location_type) VALUES (?, ?, ?)",
                       (sinif, fakulte_id, "sinif"))
        sinif_ids[sinif] = cursor.lastrowid

    users = [
        ("Selma Toker", "ogrenci", None),
        ("Selma Toker", "ogrenci", None),   # Aynı ad-soyada sahip ikinci öğrenci:
                                            # ID ile ayrışır (ID tabanlı ayrım testi)
        ("Emir Koray Çoban", "personel", "Tesisatçı"),
        ("Ziya Karakaya", "admin", "Bölüm Başkanı"),
        ("Rahmi Er", "admin", "Rektör"),
        ("Güven Orkun Tanık", "akademisyen", "Yapay Zeka Hocası"),
    ]

    user_ids = {}
    selma_ids = []  # Aynı isimli "Selma Toker" öğrencilerinin benzersiz ID'leri
    for name, role, sub_role in users:
        cursor.execute("INSERT INTO users (name, role, sub_role) VALUES (?, ?, ?)",
                       (name, role, sub_role))
        uid = cursor.lastrowid
        user_ids[name] = uid  # son eklenen ID (benzersiz isimler için yeterli)
        if name == "Selma Toker":
            selma_ids.append(uid)

    cursor.execute('''
        INSERT INTO courses (name, akademisyen_id, location_id, day_of_week, start_time, end_time)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', ("Yapay Zeka", user_ids["Güven Orkun Tanık"], sinif_ids["Z-17"],
          "Pazartesi", "09:00", "12:00"))
    course_id = cursor.lastrowid

    # Her iki Selma Toker'i de derse kaydet → yoklamada/listede ID ile ayırt edilir
    for sid in selma_ids:
        cursor.execute("INSERT INTO course_students (course_id, student_id) VALUES (?, ?)",
                       (course_id, sid))

    conn.commit()
    conn.close()
    print("Varsayılan veriler eklendi.")


# ============================================================================
# Biyometrik Şifreleme Yardımcıları
# ============================================================================
#
# Format: [4 bayt header_len (LE uint32)] [header JSON (shape+dtype)] [raw array bayt'ları]
# Hepsi AES-GCM ile şifrelenir, associated_data = "user:<id>"
# → Bir kullanıcının encoding'i başka user_id ile çözülemez (AAD uyuşmaz → InvalidTag).

def _encrypt_encoding_array(encoding: np.ndarray, user_id: int) -> str:
    arr = np.asarray(encoding, dtype=np.float32)
    raw = arr.tobytes()
    header = json.dumps({'shape': list(arr.shape), 'dtype': 'float32'}).encode('utf-8')
    blob = struct.pack('<I', len(header)) + header + raw
    aad = f"user:{user_id}".encode('utf-8')
    return base64.b64encode(security.encrypt_bytes(blob, associated_data=aad)).decode('ascii')


def _decrypt_encoding_array(b64_text: str, user_id: int) -> np.ndarray:
    aad = f"user:{user_id}".encode('utf-8')
    blob = security.decrypt_bytes(base64.b64decode(b64_text), associated_data=aad)
    (hdr_len,) = struct.unpack('<I', blob[:4])
    header = json.loads(blob[4:4 + hdr_len].decode('utf-8'))
    raw = blob[4 + hdr_len:]
    arr = np.frombuffer(raw, dtype=np.dtype(header['dtype'])).reshape(header['shape'])
    return np.array(arr)  # frombuffer read-only; kopya döndür


# ============================================================================
# Audit Log
# ============================================================================

def _log_biometric_operation(cursor, user_id: Optional[int], operation: str,
                             success: bool, detail: str = "") -> None:
    try:
        user_hash = security.hash_identifier(str(user_id)) if user_id is not None else "-"
        cursor.execute(
            "INSERT INTO biometric_audit_log (user_id_hash, operation, success, detail) "
            "VALUES (?, ?, ?, ?)",
            (user_hash, operation, 1 if success else 0, (detail or "")[:500])
        )
    except Exception as e:
        print(f"⚠ Audit log yazılamadı: {e}")


def audit_biometric(user_id: Optional[int], operation: str, success: bool = True,
                    detail: str = "") -> None:
    """Dışarıdan çağrılabilen audit log yazıcısı."""
    conn = get_connection()
    cursor = conn.cursor()
    _log_biometric_operation(cursor, user_id, operation, success, detail)
    conn.commit()
    conn.close()


def get_audit_log(limit: int = 200):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM biometric_audit_log ORDER BY timestamp DESC LIMIT ?", (limit,)
    )
    rows = cursor.fetchall()
    conn.close()
    return rows


# ============================================================================
# KULLANICI İŞLEMLERİ
# ============================================================================

def get_all_users():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE is_active = 1 ORDER BY role, name")
    users = cursor.fetchall()
    conn.close()
    return users


def get_user_by_id(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user


def get_users_by_role(role):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE role = ? AND is_active = 1", (role,))
    users = cursor.fetchall()
    conn.close()
    return users


def add_user(name, role, sub_role=None, face_encoding=None):
    """Yeni kullanıcı ekle. face_encoding verilirse şifreli olarak saklanır."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO users (name, role, sub_role) VALUES (?, ?, ?)",
        (name, role, sub_role)
    )
    user_id = cursor.lastrowid

    if face_encoding is not None:
        encoding_enc = _encrypt_encoding_array(face_encoding, user_id)
        cursor.execute(
            "UPDATE users SET face_encoding = ? WHERE id = ?",
            (encoding_enc, user_id)
        )
        _log_biometric_operation(cursor, user_id, 'register', True,
                                 'Yeni kayıt sırasında encoding şifrelendi')

    conn.commit()
    conn.close()
    return user_id


def update_user(user_id, name=None, role=None, sub_role=None):
    conn = get_connection()
    cursor = conn.cursor()

    updates = []
    params = []

    if name:
        updates.append("name = ?")
        params.append(name)
    if role:
        updates.append("role = ?")
        params.append(role)
    if sub_role is not None:
        updates.append("sub_role = ?")
        params.append(sub_role)

    if updates:
        params.append(user_id)
        query = f"UPDATE users SET {', '.join(updates)} WHERE id = ?"
        cursor.execute(query, params)
        conn.commit()

    conn.close()


def update_user_face(user_id, face_encoding):
    """Kullanıcının yüz şablonunu güncelle (AES-GCM şifreli)."""
    conn = get_connection()
    cursor = conn.cursor()
    if face_encoding is None:
        cursor.execute("UPDATE users SET face_encoding = NULL WHERE id = ?", (user_id,))
        _log_biometric_operation(cursor, user_id, 'clear_encoding', True)
    else:
        encoding_enc = _encrypt_encoding_array(face_encoding, user_id)
        cursor.execute(
            "UPDATE users SET face_encoding = ? WHERE id = ?",
            (encoding_enc, user_id)
        )
        _log_biometric_operation(cursor, user_id, 'update_encoding', True)
    conn.commit()
    conn.close()


def update_user_face_ref(user_id: int, file_ref: Optional[str]):
    """Kullanıcının şifreli yüz fotoğrafı referansını güncelle (UUID)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET face_image_ref = ? WHERE id = ?",
        (file_ref, user_id)
    )
    _log_biometric_operation(
        cursor, user_id,
        'set_image_ref' if file_ref else 'clear_image_ref', True
    )
    conn.commit()
    conn.close()


def get_user_face_ref(user_id: int) -> Optional[str]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT face_image_ref FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row['face_image_ref'] if row else None


def delete_user(user_id):
    """Soft delete (is_active = 0). Biyometrik veri için delete_user_biometrics kullanın."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_active = 0 WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()


def delete_user_biometrics(user_id: int) -> Optional[str]:
    """KVKK 'unutulma hakkı': biyometrik verileri tamamen sil.
    Eski dosya referansını döndürür (face_module onu diskten silebilsin)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT face_image_ref FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    old_ref = row['face_image_ref'] if row else None

    cursor.execute(
        "UPDATE users SET face_encoding = NULL, face_image_ref = NULL WHERE id = ?",
        (user_id,)
    )
    _log_biometric_operation(cursor, user_id, 'delete_biometrics', True,
                             'KVKK unutulma hakkı')
    conn.commit()
    conn.close()
    return old_ref


def get_user_face_encoding(user_id):
    """Kullanıcının yüz şablonunu (şifreden çözülmüş numpy) getir."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT face_encoding FROM users WHERE id = ?", (user_id,))
    result = cursor.fetchone()

    if result and result['face_encoding']:
        try:
            arr = _decrypt_encoding_array(result['face_encoding'], user_id)
            _log_biometric_operation(cursor, user_id, 'read_encoding', True)
            conn.commit()
            conn.close()
            return arr
        except Exception as e:
            _log_biometric_operation(cursor, user_id, 'read_encoding', False, str(e)[:200])
            conn.commit()
            conn.close()
            print(f"⚠ user_id={user_id} encoding çözülemedi: {e}")
            return None
    conn.close()
    return None


def get_all_face_encodings():
    """Tüm aktif kullanıcıların yüz şablonlarını çöz ve döndür."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, name, face_encoding FROM users "
        "WHERE face_encoding IS NOT NULL AND is_active = 1"
    )
    results = cursor.fetchall()

    encodings = []
    for row in results:
        try:
            arr = _decrypt_encoding_array(row['face_encoding'], row['id'])
            encodings.append({'id': row['id'], 'name': row['name'], 'encoding': arr})
            _log_biometric_operation(cursor, row['id'], 'read_encoding_bulk', True)
        except Exception as e:
            _log_biometric_operation(cursor, row['id'], 'read_encoding_bulk', False, str(e)[:200])
            print(f"⚠ user_id={row['id']} encoding çözülemedi, atlandı: {e}")

    conn.commit()
    conn.close()
    return encodings


# ============================================================================
# MEKAN İŞLEMLERİ
# ============================================================================

def get_all_locations():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM locations")
    locations = cursor.fetchall()
    conn.close()
    return locations


def get_classrooms():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM locations WHERE location_type = 'sinif'")
    classrooms = cursor.fetchall()
    conn.close()
    return classrooms


def get_location_by_id(location_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM locations WHERE id = ?", (location_id,))
    location = cursor.fetchone()
    conn.close()
    return location


# ============================================================================
# SINIF KOLTUK İŞLEMLERİ
# ============================================================================

def get_classroom_seats(location_id):
    """Bir sınıftaki dolu koltukları (seat_id -> student dict) şeklinde döndür.

    Dönen dict:
        {
          "R1_L_3": {"student_id": 5, "student_name": "Selma Toker"},
          ...
        }
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT cs.seat_id, cs.student_id, u.name as student_name
        FROM classroom_seats cs
        JOIN users u ON cs.student_id = u.id
        WHERE cs.location_id = ? AND u.is_active = 1
    ''', (location_id,))
    rows = cursor.fetchall()
    conn.close()
    return {
        row['seat_id']: {
            'student_id': row['student_id'],
            'student_name': row['student_name'],
        }
        for row in rows
    }


def get_student_seat(location_id, student_id):
    """Öğrencinin bu sınıftaki koltuk ID'sini döndür (yoksa None)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT seat_id FROM classroom_seats WHERE location_id = ? AND student_id = ?",
        (location_id, student_id),
    )
    row = cursor.fetchone()
    conn.close()
    return row['seat_id'] if row else None


def assign_seat(location_id, seat_id, student_id):
    """Öğrenciye koltuk ata.

    Returns: (success: bool, message: str)

    Hata durumları:
      - Koltuk zaten başka bir öğrenciye ait
      - Öğrenci aynı sınıfta başka bir koltuğa zaten oturmuş
    """
    conn = get_connection()
    cursor = conn.cursor()
    try:
        # Önce koltuk dolu mu?
        cursor.execute(
            "SELECT student_id FROM classroom_seats WHERE location_id = ? AND seat_id = ?",
            (location_id, seat_id),
        )
        existing = cursor.fetchone()
        if existing:
            conn.close()
            if existing['student_id'] == student_id:
                return True, "Zaten bu koltukta oturuyorsunuz."
            return False, "Bu koltuk başka bir öğrenci tarafından kullanılıyor."

        # Öğrenci aynı sınıfta başka bir koltukta mı?
        cursor.execute(
            "SELECT seat_id FROM classroom_seats WHERE location_id = ? AND student_id = ?",
            (location_id, student_id),
        )
        own = cursor.fetchone()
        if own:
            conn.close()
            return False, f"Zaten başka bir koltukta oturuyorsunuz ({own['seat_id']}). Önce kalkın."

        cursor.execute(
            "INSERT INTO classroom_seats (location_id, seat_id, student_id) VALUES (?, ?, ?)",
            (location_id, seat_id, student_id),
        )
        conn.commit()
        conn.close()
        return True, "Koltuğa oturuldu."
    except sqlite3.IntegrityError as e:
        conn.close()
        return False, f"Koltuk atanamadı: {e}"


def release_seat(location_id, student_id):
    """Öğrenciyi oturduğu koltuktan kaldır.

    Returns: (success: bool, message: str)
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM classroom_seats WHERE location_id = ? AND student_id = ?",
        (location_id, student_id),
    )
    removed = cursor.rowcount
    conn.commit()
    conn.close()
    if removed > 0:
        return True, "Koltuktan kalkıldı."
    return False, "Zaten bir koltukta oturmuyorsunuz."


def release_seat_by_seat_id(location_id, seat_id):
    """Koltuk ID'si ile boşalt (akademisyen/admin için — belirli koltuğu boşaltma).

    Returns: (success: bool, message: str, released_student_id: Optional[int])
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT student_id FROM classroom_seats WHERE location_id = ? AND seat_id = ?",
        (location_id, seat_id),
    )
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False, "Bu koltukta oturan biri yok.", None
    student_id = row['student_id']
    cursor.execute(
        "DELETE FROM classroom_seats WHERE location_id = ? AND seat_id = ?",
        (location_id, seat_id),
    )
    conn.commit()
    conn.close()
    return True, "Öğrenci koltuktan kaldırıldı.", student_id


# ============================================================================
# DERS İŞLEMLERİ
# ============================================================================

def get_all_courses():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT c.*, u.name as akademisyen_name, l.name as location_name
        FROM courses c
        LEFT JOIN users u ON c.akademisyen_id = u.id
        LEFT JOIN locations l ON c.location_id = l.id
    ''')
    courses = cursor.fetchall()
    conn.close()
    return courses


def get_courses_by_akademisyen(akademisyen_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT c.*, l.name as location_name
        FROM courses c
        LEFT JOIN locations l ON c.location_id = l.id
        WHERE c.akademisyen_id = ?
    ''', (akademisyen_id,))
    courses = cursor.fetchall()
    conn.close()
    return courses


def get_courses_by_location(location_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT c.*, u.name as akademisyen_name
        FROM courses c
        LEFT JOIN users u ON c.akademisyen_id = u.id
        WHERE c.location_id = ?
    ''', (location_id,))
    courses = cursor.fetchall()
    conn.close()
    return courses


def get_student_courses(student_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT c.*, u.name as akademisyen_name, l.name as location_name
        FROM courses c
        JOIN course_students cs ON c.id = cs.course_id
        LEFT JOIN users u ON c.akademisyen_id = u.id
        LEFT JOIN locations l ON c.location_id = l.id
        WHERE cs.student_id = ?
    ''', (student_id,))
    courses = cursor.fetchall()
    conn.close()
    return courses


def add_course(name, akademisyen_id, location_id, day_of_week, start_time, end_time):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO courses (name, akademisyen_id, location_id, day_of_week, start_time, end_time)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (name, akademisyen_id, location_id, day_of_week, start_time, end_time))
    course_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return course_id


def assign_student_to_course(course_id, student_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO course_students (course_id, student_id) VALUES (?, ?)",
                   (course_id, student_id))
    conn.commit()
    conn.close()


def remove_student_from_course(course_id, student_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM course_students WHERE course_id = ? AND student_id = ?",
                   (course_id, student_id))
    conn.commit()
    conn.close()


def get_course_students(course_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT u.* FROM users u
        JOIN course_students cs ON u.id = cs.student_id
        WHERE cs.course_id = ? AND u.is_active = 1
    ''', (course_id,))
    students = cursor.fetchall()
    conn.close()
    return students


# ============================================================================
# YOKLAMA İŞLEMLERİ
# ============================================================================

def check_in(user_id, location_id, course_id=None):
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now()

    cursor.execute('''
        SELECT id FROM attendance
        WHERE user_id = ? AND location_id = ? AND date = DATE('now', 'localtime')
        AND check_out_time IS NULL
    ''', (user_id, location_id))

    existing = cursor.fetchone()
    if existing:
        conn.close()
        return None, "Zaten giriş yapılmış!"

    cursor.execute('''
        INSERT INTO attendance (user_id, location_id, course_id, check_in_time)
        VALUES (?, ?, ?, ?)
    ''', (user_id, location_id, course_id, now))

    attendance_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return attendance_id, "Giriş başarılı!"


def check_out(user_id, location_id):
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now()

    cursor.execute('''
        SELECT id FROM attendance
        WHERE user_id = ? AND location_id = ? AND date = DATE('now', 'localtime')
        AND check_out_time IS NULL
        ORDER BY check_in_time DESC LIMIT 1
    ''', (user_id, location_id))

    record = cursor.fetchone()
    if not record:
        conn.close()
        return False, "Giriş kaydı bulunamadı!"

    cursor.execute("UPDATE attendance SET check_out_time = ? WHERE id = ?", (now, record['id']))
    conn.commit()
    conn.close()
    return True, "Çıkış başarılı!"


def get_user_attendance(user_id, start_date=None, end_date=None):
    conn = get_connection()
    cursor = conn.cursor()

    query = '''
        SELECT a.*, l.name as location_name, c.name as course_name
        FROM attendance a
        LEFT JOIN locations l ON a.location_id = l.id
        LEFT JOIN courses c ON a.course_id = c.id
        WHERE a.user_id = ?
    '''
    params = [user_id]

    if start_date:
        query += " AND a.date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND a.date <= ?"
        params.append(end_date)

    query += " ORDER BY a.date DESC, a.check_in_time DESC"

    cursor.execute(query, params)
    records = cursor.fetchall()
    conn.close()
    return records


def get_location_attendance(location_id, date=None):
    conn = get_connection()
    cursor = conn.cursor()

    if date is None:
        date = datetime.now().strftime('%Y-%m-%d')

    cursor.execute('''
        SELECT a.*, u.name as user_name, u.role, c.name as course_name
        FROM attendance a
        JOIN users u ON a.user_id = u.id
        LEFT JOIN courses c ON a.course_id = c.id
        WHERE a.location_id = ? AND a.date = ?
        ORDER BY a.check_in_time DESC
    ''', (location_id, date))

    records = cursor.fetchall()
    conn.close()
    return records


def get_all_attendance(start_date=None, end_date=None):
    conn = get_connection()
    cursor = conn.cursor()

    query = '''
        SELECT a.*, u.name as user_name, u.role, l.name as location_name, c.name as course_name
        FROM attendance a
        JOIN users u ON a.user_id = u.id
        LEFT JOIN locations l ON a.location_id = l.id
        LEFT JOIN courses c ON a.course_id = c.id
        WHERE 1=1
    '''
    params = []

    if start_date:
        query += " AND a.date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND a.date <= ?"
        params.append(end_date)

    query += " ORDER BY a.date DESC, a.check_in_time DESC"

    cursor.execute(query, params)
    records = cursor.fetchall()
    conn.close()
    return records


# ============================================================================
# DEVAMSIZLIK / KRİTİK DEVAMSIZLIK UYARI HESAPLAMA
# ============================================================================
# Devamsızlık, attendance tablosundaki check_in kayıtlarından türetilir:
#   - Bir dersin "işlenen ders/oturum sayısı" = o derste check_in yapılmış
#     FARKLI tarih (gün) sayısıdır.
#   - Bir öğrencinin "katılımı"  = o derste check_in yaptığı farklı gün sayısı.
#   - Devamsızlık oranı = (toplam_oturum - katılım) / toplam_oturum
# Devamsızlık oranı kritik eşiği AŞAN öğrenci "Kritik Sırada" kabul edilir
# (varsayılan %30 → katılımı %70 sınırının altına düşmüş demektir).

ATTENDANCE_CRITICAL_THRESHOLD = 0.30  # devamsızlık oranı bu değeri AŞAN = kritik


def get_course_total_sessions(course_id) -> int:
    """Bir derste işlenen toplam oturum (farklı gün) sayısı.
    check_in kaydı bulunan benzersiz tarih sayısı baz alınır."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT COUNT(DISTINCT date) AS total
        FROM attendance
        WHERE course_id = ? AND check_in_time IS NOT NULL
    ''', (course_id,))
    row = cursor.fetchone()
    conn.close()
    return int(row['total']) if row and row['total'] is not None else 0


def get_student_attendance_count(course_id, student_id) -> int:
    """Bir öğrencinin bir derse katıldığı farklı gün (oturum) sayısı."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT COUNT(DISTINCT date) AS attended
        FROM attendance
        WHERE course_id = ? AND user_id = ? AND check_in_time IS NOT NULL
    ''', (course_id, student_id))
    row = cursor.fetchone()
    conn.close()
    return int(row['attended']) if row and row['attended'] is not None else 0


def get_course_absence_stats(course_id, threshold: float = ATTENDANCE_CRITICAL_THRESHOLD):
    """Bir derse kayıtlı tüm öğrenciler için devamsızlık istatistiği döndür.

    Her öğe (dict):
        student_id, student_name, course_id, course_name,
        total_sessions, attended, absent, absence_rate (0..1), is_critical (bool)
    """
    total_sessions = get_course_total_sessions(course_id)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM courses WHERE id = ?", (course_id,))
    crow = cursor.fetchone()
    course_name = crow['name'] if crow else f"#{course_id}"

    # Derse kayıtlı öğrenciler + her birinin katıldığı farklı gün sayısı (tek sorgu)
    cursor.execute('''
        SELECT u.id AS student_id, u.name AS student_name,
               COUNT(DISTINCT a.date) AS attended
        FROM course_students cs
        JOIN users u ON u.id = cs.student_id AND u.is_active = 1
        LEFT JOIN attendance a
               ON a.course_id = cs.course_id
              AND a.user_id   = cs.student_id
              AND a.check_in_time IS NOT NULL
        WHERE cs.course_id = ?
        GROUP BY u.id, u.name
        ORDER BY u.name
    ''', (course_id,))
    rows = cursor.fetchall()
    conn.close()

    stats = []
    for r in rows:
        attended = int(r['attended'] or 0)
        absent = max(0, total_sessions - attended)
        rate = (absent / total_sessions) if total_sessions > 0 else 0.0
        stats.append({
            'student_id': r['student_id'],
            'student_name': r['student_name'],
            'course_id': course_id,
            'course_name': course_name,
            'total_sessions': total_sessions,
            'attended': attended,
            'absent': absent,
            'absence_rate': rate,
            'is_critical': total_sessions > 0 and rate > threshold,
        })
    return stats


def get_critical_absentees(akademisyen_id=None,
                           threshold: float = ATTENDANCE_CRITICAL_THRESHOLD):
    """Devamsızlık sınırını AŞAN (kritik) öğrencileri döndür.

    akademisyen_id verilirse yalnızca o akademisyenin dersleri taranır
    (Akademisyen paneli); None ise tüm dersler taranır (Admin paneli).
    En yüksek devamsızlık oranından düşüğe doğru sıralı döner.
    """
    if akademisyen_id is not None:
        courses = get_courses_by_akademisyen(akademisyen_id)
    else:
        courses = get_all_courses()

    critical = []
    for course in courses:
        for s in get_course_absence_stats(course['id'], threshold):
            if s['is_critical']:
                critical.append(s)

    critical.sort(key=lambda x: x['absence_rate'], reverse=True)
    return critical


def get_course_schedule():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT c.*, u.name as akademisyen_name, l.name as location_name
        FROM courses c
        LEFT JOIN users u ON c.akademisyen_id = u.id
        LEFT JOIN locations l ON c.location_id = l.id
        ORDER BY c.day_of_week, c.start_time
    ''')
    schedule = cursor.fetchall()
    conn.close()
    return schedule
    init_database()
    init_default_data()
    print("Veritabanı başlatıldı!")
