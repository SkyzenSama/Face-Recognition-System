"""
Güvenlik Modülü - Yüz Tanıma Yoklama Sistemi
=============================================

Bu modül, KVKK (Kişisel Verilerin Korunması Kanunu) uyumlu biyometrik
veri koruması sağlar. Açıklık için tüm kritik noktalar yorumlandı.

Sağladıkları:
    - AES-256-GCM kimlik doğrulamalı şifreleme (confidentiality + integrity)
    - Master key yönetimi: anahtar PROJE DİZİNİ DIŞINDA (kullanıcı ana
      dizininde), OS-level dosya izinleriyle (chmod 600) saklanır. Böylece
      veritabanı veya proje klasörü sızdırılsa bile şifreli veri kırılamaz.
    - Tahmin edilemez UUID4 tabanlı dosya adları (user_1.jpg gibi örüntüler
      yok)
    - HMAC-SHA256 tuzlu hashleme: audit loglarında gerçek user_id yerine
      sabit hash kullanılır → log sızarsa kullanıcı kimliği ifşa olmaz
    - Biyometrik verilere her erişim audit tablosuna yazılır (KVKK m.12)

Önemli: Master key silinirse/kaybolursa mevcut şifreli verilere erişim
tamamen kaybolur. Bu bir hata değil, tasarımın parçasıdır.
"""

from __future__ import annotations

import os
import base64
import uuid
import hashlib
import hmac
import secrets
import platform
from pathlib import Path
from typing import Optional

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False


# ---------------------------------------------------------------------------
# Anahtar Saklama Konumu
# ---------------------------------------------------------------------------
# Anahtar dosyasını PROJE DİZİNİNDE saklamak BÜYÜK bir hata olurdu; çünkü
# proje GitHub'a push'landığında, ZIP'lenip paylaşıldığında veya yedeklendiğinde
# anahtar da beraber kopyalanır. Anahtarı, şifrelediği veriyle birlikte
# taşımak = şifrelemeyi hiç yapmamış olmak.
#
# Bu yüzden anahtar kullanıcı ana dizini altında, gizli bir alt klasörde tutulur.
# Unix'te chmod 600 ile yalnızca dosya sahibi okuyabilir.
_APP_DIR_NAME = ".thk_face_attendance"
KEY_FILE_NAME = "master.key"
SALT_FILE_NAME = "hmac_salt.bin"


def _get_key_dir() -> Path:
    """Master key'in saklanacağı dizini döndür ve yoksa oluştur."""
    key_dir = Path.home() / _APP_DIR_NAME
    key_dir.mkdir(parents=True, exist_ok=True)
    # Unix'te dizin izinlerini kısıtla: sadece sahibi okuyup açabilsin.
    if platform.system() != "Windows":
        try:
            os.chmod(key_dir, 0o700)
        except OSError:
            pass  # bazı dosya sistemlerinde chmod desteklenmez
    return key_dir


def _restrict_file_permissions(filepath: Path) -> None:
    """Dosya sadece sahibi tarafından okunup yazılabilsin (0600)."""
    if platform.system() != "Windows":
        try:
            os.chmod(filepath, 0o600)
        except OSError:
            pass


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Güç kesintisi/çökme durumunda yarı yazılmış anahtar dosyası
    oluşmaması için önce geçici dosyaya yazıp sonra taşı."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _load_or_create_master_key() -> bytes:
    """Master key'i yükle; yoksa kriptografik güvenli rastgele oluştur."""
    key_path = _get_key_dir() / KEY_FILE_NAME
    if key_path.exists():
        with open(key_path, "rb") as f:
            key = f.read()
        if len(key) != 32:
            raise ValueError(
                f"Master key dosyası bozuk (beklenen 32 bayt, bulunan {len(key)}). "
                f"Manuel kontrol gerekli: {key_path}"
            )
        return key

    # secrets modülü, os.urandom üzerine kurulu kriptografik güvenli PRNG kullanır.
    # random.randbytes KULLANMAYIN; o kriptografik değildir.
    key = secrets.token_bytes(32)  # AES-256 için 256 bit
    _atomic_write_bytes(key_path, key)
    _restrict_file_permissions(key_path)
    return key


def _load_or_create_hmac_salt() -> bytes:
    """Audit hash'leri için tuz (salt) değeri. Sabit olmak zorunda çünkü
    aynı user_id her zaman aynı hash'i üretmeli (sorgulanabilir olsun diye),
    ama projeden projeye farklı olmalı."""
    salt_path = _get_key_dir() / SALT_FILE_NAME
    if salt_path.exists():
        with open(salt_path, "rb") as f:
            return f.read()
    salt = secrets.token_bytes(16)
    _atomic_write_bytes(salt_path, salt)
    _restrict_file_permissions(salt_path)
    return salt


# Tembel yükleme: modül import edilir edilmez anahtar dosyası oluşturma.
# Testlerde ve ilk kurulumda daha temiz davranır.
_MASTER_KEY: Optional[bytes] = None
_HMAC_SALT: Optional[bytes] = None


def _ensure_ready() -> None:
    """İlk çağrıda anahtarları yükle/oluştur."""
    global _MASTER_KEY, _HMAC_SALT
    if not CRYPTO_AVAILABLE:
        raise RuntimeError(
            "cryptography kütüphanesi bulunamadı. "
            "Şifreleme için gereklidir. Yükleme: pip install cryptography"
        )
    if _MASTER_KEY is None:
        _MASTER_KEY = _load_or_create_master_key()
    if _HMAC_SALT is None:
        _HMAC_SALT = _load_or_create_hmac_salt()


def is_available() -> bool:
    """cryptography yüklü mü?"""
    return CRYPTO_AVAILABLE


def get_key_location() -> str:
    """Hata mesajlarında/loglarda göstermek için anahtar dosyası yolu."""
    return str(_get_key_dir() / KEY_FILE_NAME)


# ---------------------------------------------------------------------------
# AES-256-GCM Şifreleme
# ---------------------------------------------------------------------------
# GCM modunu özellikle seçtik: "authenticated encryption with associated data"
# sağlar. Yani şifreli metin değiştirilirse decrypt InvalidTag hatası verir;
# dolayısıyla saldırgan sessizce veriyi bozamaz. CBC veya ECB bunu yapmaz.
#
# Format: [12 bayt nonce] [ciphertext] [16 bayt auth tag]
# Nonce her şifrelemede rastgele üretilir → aynı veri iki kez şifrelense bile
# çıktı farklı olur (deterministik değil, daha güvenli).

_NONCE_SIZE = 12  # GCM için önerilen boyut


def encrypt_bytes(plaintext: bytes, associated_data: Optional[bytes] = None) -> bytes:
    """Bayt dizisini AES-256-GCM ile şifrele.

    associated_data şifrelenmez ama kimlik doğrulamaya dahildir. Mesela
    user_id'yi buraya verirsek, kötü niyetli bir aktör şifreli bir kullanıcının
    face_encoding'ini başka bir kullanıcıya kopyalayamaz.
    """
    _ensure_ready()
    aesgcm = AESGCM(_MASTER_KEY)
    nonce = secrets.token_bytes(_NONCE_SIZE)
    ciphertext = aesgcm.encrypt(nonce, plaintext, associated_data)
    return nonce + ciphertext


def decrypt_bytes(blob: bytes, associated_data: Optional[bytes] = None) -> bytes:
    """Şifreli veriyi çöz. Veri bozulmuş/değiştirilmişse cryptography
    kütüphanesi InvalidTag istisnası fırlatır."""
    _ensure_ready()
    if len(blob) < _NONCE_SIZE + 16:
        raise ValueError("Şifreli blok çok kısa (bozuk veya eksik).")
    aesgcm = AESGCM(_MASTER_KEY)
    nonce = blob[:_NONCE_SIZE]
    ciphertext = blob[_NONCE_SIZE:]
    return aesgcm.decrypt(nonce, ciphertext, associated_data)


def encrypt_text(text: str, associated_data: Optional[bytes] = None) -> str:
    """Metni şifrele ve base64 döndür (SQLite TEXT sütununda saklanabilir)."""
    return base64.b64encode(
        encrypt_bytes(text.encode("utf-8"), associated_data)
    ).decode("ascii")


def decrypt_text(b64: str, associated_data: Optional[bytes] = None) -> str:
    """base64 metni çöz."""
    return decrypt_bytes(base64.b64decode(b64), associated_data).decode("utf-8")


# ---------------------------------------------------------------------------
# HMAC-SHA256 Hash (Audit Log için)
# ---------------------------------------------------------------------------
# Audit loglarında "user_id=5" yazmak yerine HMAC(salt, "5") yazarız.
# Böylece log dosyaları sızdırıldığında kullanıcı kimlikleri ifşa olmaz,
# ama yine de aynı kullanıcının tüm işlemleri ilişkilendirilebilir.

def hash_identifier(value: str) -> str:
    """Kimlik değerini HMAC-SHA256 ile hash'le (hex döndürür)."""
    _ensure_ready()
    return hmac.new(_HMAC_SALT, str(value).encode("utf-8"), hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# Dosya Adı Üretimi
# ---------------------------------------------------------------------------
# user_1.jpg → 7b2e1f9a3c4d5e6f.enc  gibi tahmin edilemez adlara geçiyoruz.
# Dosya içeriği zaten şifreli olduğu için UUID'nin kriptografik güvenli
# olması mecburi değil; yalnız enumerate edilememesi yeter.

def generate_file_reference() -> str:
    """Yeni bir tahmin edilemez dosya referansı üret."""
    return uuid.uuid4().hex


# ---------------------------------------------------------------------------
# Yardımcı: şifreli metnin format sezgisi
# ---------------------------------------------------------------------------
# Migration sırasında "bu metin zaten şifreli mi yoksa eski plaintext JSON mu?"
# ayrımını yapabilmek için kullanılır.

def looks_like_plaintext_json_array(value: str) -> bool:
    """Eski format: '[0.123, -0.45, ...]' gibi JSON float listesi."""
    v = value.strip()
    if not (v.startswith("[") and v.endswith("]")):
        return False
    try:
        import json
        data = json.loads(v)
        return isinstance(data, list) and all(
            isinstance(x, (int, float)) for x in data
        )
    except (ValueError, TypeError):
        return False


if __name__ == "__main__":
    # Hızlı smoke test
    print(f"cryptography mevcut: {is_available()}")
    if is_available():
        _ensure_ready()
        print(f"Anahtar konumu: {get_key_location()}")
        sample = b"Merhaba, gizli dunya!"
        ct = encrypt_bytes(sample, associated_data=b"user:1")
        pt = decrypt_bytes(ct, associated_data=b"user:1")
        assert pt == sample
        print("✓ AES-GCM şifrele/çöz çalışıyor")
        print(f"✓ hash_identifier('1') = {hash_identifier('1')[:16]}...")
        print(f"✓ generate_file_reference() = {generate_file_reference()}")
