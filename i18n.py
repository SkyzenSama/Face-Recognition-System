"""
i18n (Internationalization) Modülü
====================================

Arayüz metinleri için Türkçe / İngilizce çeviri yönetimi.

Kullanım:
    import i18n
    print(i18n.t('login.welcome'))   # mevcut dilde metin
    i18n.set_lang('en')               # diliği değiştir (disk'e de yazar)
    lang = i18n.get_lang()            # mevcut dil kodu ('tr' veya 'en')

Tasarım notları:
    - Dil seçimi `user_settings/language.txt`'de kalıcı olarak saklanır
      (kullanıcı uygulamayı kapatıp açtığında aynı dil korunur).
    - Bilinmeyen bir anahtar verilirse anahtarın kendisi döner (placeholder
      gibi davranır — kullanıcı çevirilmemiş bir yer görürse hangi anahtar
      olduğunu anlar, sessizce kaybolmaz).
    - DEFAULT_LANG ile setting dosyası yoksa veya bozuksa fallback davranır.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


DEFAULT_LANG = 'tr'
SUPPORTED_LANGS = ('tr', 'en')

_SETTINGS_DIR = "user_settings"
_LANG_FILE = "language.txt"

# Mevcut dil (modül seviyesinde cache)
_current_lang: Optional[str] = None


# ---------------------------------------------------------------------------
# Disk persistans
# ---------------------------------------------------------------------------

def _settings_path() -> Path:
    return Path(_SETTINGS_DIR) / _LANG_FILE


def _load_from_disk() -> str:
    """Disk'ten dil oku. Yoksa veya bozuksa DEFAULT_LANG döndür."""
    path = _settings_path()
    if not path.exists():
        return DEFAULT_LANG
    try:
        content = path.read_text(encoding='utf-8').strip().lower()
        if content in SUPPORTED_LANGS:
            return content
    except OSError:
        pass
    return DEFAULT_LANG


def _save_to_disk(lang: str) -> None:
    """Dil seçimini disk'e yaz (atomik olarak)."""
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(lang, encoding='utf-8')
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_lang() -> str:
    """Mevcut dil kodunu döndür ('tr' veya 'en')."""
    global _current_lang
    if _current_lang is None:
        _current_lang = _load_from_disk()
    return _current_lang


def set_lang(lang: str) -> None:
    """Dili değiştir ve disk'e kaydet. Geçersiz kodlar yok sayılır."""
    global _current_lang
    if lang not in SUPPORTED_LANGS:
        return
    _current_lang = lang
    try:
        _save_to_disk(lang)
    except OSError as e:
        print(f"⚠ Dil tercihi kaydedilemedi: {e}")


def t(key: str, **fmt) -> str:
    """Mevcut dilde anahtarın karşılığını döndür.

    Eksik anahtar → key'in kendisi (debug için görünür placeholder).
    Format argümanları → str.format() ile yerleştirilir.
    """
    lang = get_lang()
    text = TRANSLATIONS.get(lang, {}).get(key)
    if text is None:
        # Türkçe'ye düş; yine yoksa anahtarı göster
        text = TRANSLATIONS.get(DEFAULT_LANG, {}).get(key, key)
    if fmt:
        try:
            return text.format(**fmt)
        except (KeyError, IndexError):
            return text
    return text


# ---------------------------------------------------------------------------
# Çeviri tablosu
# ---------------------------------------------------------------------------
# Anahtarlar nokta ile gruplandırılmış (alan.alt_alan). Yalnız UI metinleri
# burada — kullanıcı isimleri, sınıf isimleri, kullanıcı rolleri vb. DB'den
# geliyor ve çevrilmiyor (bunlar veri, UI değil).

TRANSLATIONS: dict[str, dict[str, str]] = {
    'tr': {
        # ----- Login ekranı -----
        'login.subtitle': "Yüz Tanıma Yoklama Sistemi",
        'login.faculty': "Mühendislik Fakültesi",
        'login.face_login': "📷  Yüz ile Giriş Yap",
        'login.manual_login': "👤  Manuel Giriş (Test)",
        'login.face_register': "➕  Yeni Yüz Kaydı",
        'login.footer': "© 2026 THK Üniversitesi - Yüz Tanıma Yoklama Sistemi - Bitirme Projesi",

        # ----- Roller (Liste / başlıklar için) -----
        'role.admin': "Admin",
        'role.akademisyen': "Akademisyen",
        'role.personel': "Personel",
        'role.ogrenci': "Öğrenci",

        # ----- Ana panel butonları -----
        'panel.user_management': "👥 Kullanıcı Yönetimi",
        'panel.all_attendance': "📊 Tüm Yoklamalar",
        'panel.course_management': "📚 Ders Yönetimi",
        'panel.permission_management': "🔐 Yetki Yönetimi",
        'panel.schedule': "📅 Ders Programı",
        'panel.my_courses': "📚 Derslerim",
        'panel.student_attendance': "📊 Öğrenci Yoklamaları",
        'panel.student_management': "👥 Öğrenci Yönetimi",
        'panel.my_attendance': "📊 Yoklamalarım",
        'panel.locations_hint': "\n📍 Yoklama almak için\nsol panelden bir sınıf seçin.",
        'panel.welcome_user': "Hoş Geldiniz, {name}",
        'panel.role_label': "Rol: {role}",
        'panel.critical_absence': "🚨 Kritik Devamsızlık Uyarıları",

        # ----- Yoklama -----
        'attendance.scan_hint': "Yoklama almak için yüzünüzü okutun:",
        'attendance.check_in': "📷 GİRİŞ YAP",
        'attendance.check_out': "📷 ÇIKIŞ YAP",
        'attendance.welcome_in': "Sayın {name}, Hoş Geldiniz!\n\nGiriş saati kaydedildi.",
        'attendance.face_mismatch': "Yüz doğrulanamadı! Lütfen kendi hesabınızla giriş yapın.",
        'attendance.title_records': "{name} - Yoklama Kayıtları",
        'attendance.col_user': "Kullanıcı",
        'attendance.col_role': "Rol",
        'attendance.col_course': "Ders",
        'attendance.col_in': "Giriş",
        'attendance.col_out': "Çıkış",
        'attendance.col_location': "Mekan",
        'attendance.col_date': "Tarih",
        'attendance.col_user_id': "Öğrenci ID",

        # ----- Canlılık (Liveness / Göz Kırpma) Kontrolü -----
        'attendance.liveness_prompt': "Canlılık Kontrolü: Lütfen kafanızı hafifçe hareket ettirin",
        'attendance.liveness_success': "Canlılık Doğrulandı ✅",
        'attendance.liveness_failed': "Canlılık Doğrulanamadı!",
        'attendance.liveness_progress': "Hareket: %{percent}",
        'attendance.liveness_cancelled': "Canlılık kontrolü iptal edildi.",

        # ----- Kritik Devamsızlık Uyarıları -----
        'absence.title': "🚨 Kritik Devamsızlık Uyarıları",
        'absence.info': "Devamsızlık oranı %{limit} kritik sınırını aşan öğrenciler "
                        "aşağıda listelenmiştir.\nUyarı göndermek için öğrencileri "
                        "seçip alttaki butona basın.",
        'absence.col_student_id': "Öğrenci ID",
        'absence.col_student_name': "Öğrenci Adı",
        'absence.col_course': "Ders Adı",
        'absence.col_rate': "Mevcut Devamsızlık Oranı",
        'absence.col_status': "Durum",
        'absence.status_critical': "Kritik Sınırda",
        'absence.send_email_btn': "📧 Seçilenlere Uyarı E-Postası Gönder (Simülasyon)",
        'absence.no_selection': "Lütfen en az bir öğrenci seçin!",
        'absence.none_critical': "Şu anda kritik devamsızlık sınırını aşan öğrenci bulunmuyor. ✅",
        'absence.sending': "Uyarı e-postaları gönderiliyor...",
        'absence.email_success_title': "Simülasyon Başarılı",
        'absence.email_success_one': "Simülasyon Başarılı: {name} kişisine uyarı "
                                     "e-postası ve sistem bildirimi başarıyla gönderildi!",
        'absence.summary': "{count} öğrenci kritik devamsızlık sınırında.",

        # ----- Sınıf krokisi -----
        'classroom.title': "🪑 Sınıf Krokisi",
        'classroom.door': "🚪 KAPI",
        'classroom.desk': "📚 AKADEMİSYEN MASASI",
        'classroom.hint_student': "Boş bir koltuğa tıklayarak oturabilirsin. "
                                   "Kendi koltuğundan kalkmak için üstüne gelip sağ üstteki ✕ işaretine bas.",
        'classroom.hint_teacher': "Oturan bir öğrenciyi kaldırmak için koltuğun üstüne gel ve "
                                   "sağ üstte çıkan ✕ işaretine bas.",
        'classroom.hint_readonly': "Sınıfın anlık koltuk dağılımı (salt-okunur).",
        'classroom.cannot_sit': "Oturulamadı",
        'classroom.cannot_leave': "Kalkılamadı",
        'classroom.cannot_remove': "Kaldırılamadı",
        'classroom.remove_confirm': "{name} adlı öğrenciyi {seat} koltuğundan kaldırmak istediğinize emin misiniz?",

        # ----- Sınıf detay -----
        'class.courses_here': "📚 Bu Sınıftaki Dersler:",
        'class.locations_header': "📍 Mekanlar",

        # ----- Ortak -----
        'common.back': "← Geri",
        'common.cancel': "İptal",
        'common.save': "Kaydet",
        'common.confirm': "Onay",
        'common.error': "Hata",
        'common.warning': "Uyarı",
        'common.info': "Bilgi",
        'common.success': "Başarılı",
        'common.close': "Kapat",
        'common.show': "Göster",
        'common.date': "Tarih",

        # ----- Çıkış -----
        'logout.button': "Çıkış",
        'logout.confirm_title': "Çıkış",
        'logout.confirm_msg': "Çıkış yapmak istediğinizden emin misiniz?",
        'logout.success_title': "Çıkış",
        'logout.success_msg': "Başarıyla Çıkış yapıldı.",

        # ----- Dil ayarları -----
        'settings.button_tooltip': "Ayarlar",
        'settings.lang_title': "Dil Seçimi",
        'settings.lang_prompt': "Lütfen arayüz dilini seçin:",
        'settings.lang_changed_title': "Dil",
        'settings.lang_changed_msg': "Arayüz dili Türkçe olarak ayarlandı.",
    },

    'en': {
        # ----- Login -----
        'login.subtitle': "Face Recognition Attendance System",
        'login.faculty': "Faculty of Engineering",
        'login.face_login': "📷  Login with Face",
        'login.manual_login': "👤  Manual Login (Test)",
        'login.face_register': "➕  New Face Registration",
        'login.footer': "© 2026 THK University - Face Recognition Attendance System - Capstone Project",

        # ----- Roles -----
        'role.admin': "Admin",
        'role.akademisyen': "Academician",
        'role.personel': "Staff",
        'role.ogrenci': "Student",

        # ----- Panel buttons -----
        'panel.user_management': "👥 User Management",
        'panel.all_attendance': "📊 All Attendance",
        'panel.course_management': "📚 Course Management",
        'panel.permission_management': "🔐 Permission Management",
        'panel.schedule': "📅 Course Schedule",
        'panel.my_courses': "📚 My Courses",
        'panel.student_attendance': "📊 Student Attendance",
        'panel.student_management': "👥 Student Management",
        'panel.my_attendance': "📊 My Attendance",
        'panel.locations_hint': "\n📍 To record attendance,\nselect a classroom from the left panel.",
        'panel.welcome_user': "Welcome, {name}",
        'panel.role_label': "Role: {role}",
        'panel.critical_absence': "🚨 Critical Absence Alerts",

        # ----- Attendance -----
        'attendance.scan_hint': "Scan your face to record attendance:",
        'attendance.check_in': "📷 CHECK IN",
        'attendance.check_out': "📷 CHECK OUT",
        'attendance.welcome_in': "Dear {name}, Welcome!\n\nCheck-in time recorded.",
        'attendance.face_mismatch': "Face not verified! Please log in with your own account.",
        'attendance.title_records': "{name} - Attendance Records",
        'attendance.col_user': "User",
        'attendance.col_role': "Role",
        'attendance.col_course': "Course",
        'attendance.col_in': "Check-in",
        'attendance.col_out': "Check-out",
        'attendance.col_location': "Location",
        'attendance.col_date': "Date",
        'attendance.col_user_id': "Student ID",

        # ----- Liveness / Blink Detection -----
        'attendance.liveness_prompt': "Liveness Check: Please move your head slightly",
        'attendance.liveness_success': "Liveness Verified ✅",
        'attendance.liveness_failed': "Liveness Verification Failed!",
        'attendance.liveness_progress': "Movement: {percent}%",
        'attendance.liveness_cancelled': "Liveness check cancelled.",

        # ----- Critical Absence Alerts -----
        'absence.title': "🚨 Critical Absence Alerts",
        'absence.info': "Students whose absence rate exceeds the {limit}% critical "
                        "threshold are listed below.\nSelect students and click the "
                        "button to send a warning.",
        'absence.col_student_id': "Student ID",
        'absence.col_student_name': "Student Name",
        'absence.col_course': "Course Name",
        'absence.col_rate': "Current Absence Rate",
        'absence.col_status': "Status",
        'absence.status_critical': "Critical",
        'absence.send_email_btn': "📧 Send Warning Email to Selected (Simulation)",
        'absence.no_selection': "Please select at least one student!",
        'absence.none_critical': "No students currently exceed the critical absence threshold. ✅",
        'absence.sending': "Sending warning emails...",
        'absence.email_success_title': "Simulation Successful",
        'absence.email_success_one': "Simulation Successful: a warning email and system "
                                     "notification were successfully sent to {name}!",
        'absence.summary': "{count} student(s) at the critical absence threshold.",

        # ----- Classroom -----
        'classroom.title': "🪑 Classroom Layout",
        'classroom.door': "🚪 DOOR",
        'classroom.desk': "📚 TEACHER'S DESK",
        'classroom.hint_student': "Click an empty seat to sit. To leave your seat, "
                                   "hover over it and click the ✕ in the top-right.",
        'classroom.hint_teacher': "To remove a student from their seat, hover over it "
                                   "and click the ✕ in the top-right.",
        'classroom.hint_readonly': "Current seat assignments (read-only).",
        'classroom.cannot_sit': "Cannot sit",
        'classroom.cannot_leave': "Cannot leave",
        'classroom.cannot_remove': "Cannot remove",
        'classroom.remove_confirm': "Are you sure you want to remove {name} from seat {seat}?",

        # ----- Class detail -----
        'class.courses_here': "📚 Courses in this classroom:",
        'class.locations_header': "📍 Locations",

        # ----- Common -----
        'common.back': "← Back",
        'common.cancel': "Cancel",
        'common.save': "Save",
        'common.confirm': "Confirm",
        'common.error': "Error",
        'common.warning': "Warning",
        'common.info': "Info",
        'common.success': "Success",
        'common.close': "Close",
        'common.show': "Show",
        'common.date': "Date",

        # ----- Logout -----
        'logout.button': "Logout",
        'logout.confirm_title': "Logout",
        'logout.confirm_msg': "Are you sure you want to log out?",
        'logout.success_title': "Logout",
        'logout.success_msg': "Logged out successfully.",

        # ----- Language settings -----
        'settings.button_tooltip': "Settings",
        'settings.lang_title': "Language",
        'settings.lang_prompt': "Please select the interface language:",
        'settings.lang_changed_title': "Language",
        'settings.lang_changed_msg': "Interface language set to English.",
    },
}


if __name__ == "__main__":
    # Smoke test
    print(f"Default lang: {get_lang()}")
    print(f"TR login: {t('login.face_login')}")
    set_lang('en')
    print(f"After set_lang('en'): {get_lang()}")
    print(f"EN login: {t('login.face_login')}")
    print(f"Format: {t('attendance.welcome_in', name='Ahmet')}")
    print(f"Unknown key: {t('does.not.exist')}")
    set_lang('tr')  # reset
