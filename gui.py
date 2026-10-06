"""
Ana GUI Modülü - Yüz Tanıma Yoklama Sistemi
Türk Hava Kurumu Üniversitesi
Tkinter ile kullanıcı arayüzü
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from datetime import datetime
import os
import threading
import time

# PIL for logo
try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# Modülleri import et
import database as db
import face_module as fm
import i18n
_ = i18n.t  # kısa kısayol: _("login.face_login") gibi kullanılabilir

# THK Üniversitesi Kurumsal Renkleri
THK_LACIVERT = "#1a3a6e"      # Ana lacivert
THK_LACIVERT_DARK = "#0f2345"  # Koyu lacivert
THK_KIRMIZI = "#c8102e"        # Kırmızı
THK_BEYAZ = "#ffffff"          # Beyaz
THK_GRI = "#f5f5f5"            # Açık gri (arka plan)


# ============================================================================
# Yardımcı: "ID - Ad Soyad" biçiminden güvenli ID ayıklama (PROBLEM 1)
# ============================================================================
# Combobox/Listbox öğeleri "12 - Selma Toker" biçimindedir. İsim içinde " - "
# geçse bile ID daima ilk parçadır; maxsplit=1 + [0] bunu garanti eder. int()
# dönüşümü hatalı/boş seçimlerde sessizce None döndürür (çökme yerine uyarı).
# Aynı ad-soyada sahip iki kullanıcı bu sayede benzersiz ID'leriyle ayrışır.

def parse_leading_id(text):
    """ "12 - Ad Soyad" → 12. Geçersiz/boş girişte None döndürür."""
    if not text:
        return None
    head = str(text).split(' - ', 1)[0].strip()
    try:
        return int(head)
    except (ValueError, TypeError):
        return None


def format_user_option(user):
    """Kullanıcıyı seçim listeleri için "ID - Ad Soyad" biçiminde döndürür.
    Aynı isimli kullanıcıların benzersiz ID ile ayırt edilmesini sağlar."""
    return f"{user['id']} - {user['name']}"


class CustomLogoWidget(tk.Frame):
    """64×64 piksel opsiyonel logo slotu.

    - Boşken: merkezde büyük bir '+' gösterir; tıklanınca filedialog açılır
    - Doluyken: resim gösterilir; mouse üzerine gelince sağ altta küçük '+'
      belirir → tıklanınca resim değiştirilir
    - Seçilen resim `assets/custom_logo.png` altına kalıcı olarak kaydedilir
      → uygulama kapatılıp açıldığında aynı resim görünür
    """

    IMAGE_PATH = os.path.join("assets", "custom_logo.png")
    SIZE = 64

    def __init__(self, master, bg: str, **kwargs):
        super().__init__(master, bg=bg, width=self.SIZE, height=self.SIZE, **kwargs)
        # Çerçeveyi sabit 64×64 boyutunda tut
        self.pack_propagate(False)
        self.grid_propagate(False)

        self.bg_color = bg
        self.photo = None  # PhotoImage referansı (garbage collect olmasın diye saklanır)

        # Canvas kullanıyoruz çünkü hover overlay için çizim lazım
        self.canvas = tk.Canvas(
            self, width=self.SIZE, height=self.SIZE,
            bg=bg, highlightthickness=1,
            highlightbackground="#ffffff",  # hafif kenar çizgisi
            cursor="hand2",
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Enter>", self._on_enter)
        self.canvas.bind("<Leave>", self._on_leave)

        self.has_image = False
        self._hover = False

        # Disk'te kaydedilmiş resim varsa yükle
        self._load_existing()
        self._redraw()

    # ----- dahili yardımcılar -----

    @staticmethod
    def _ensure_assets_dir():
        d = os.path.dirname(CustomLogoWidget.IMAGE_PATH)
        if d and not os.path.exists(d):
            os.makedirs(d, exist_ok=True)

    def _load_existing(self):
        """Önceden kaydedilmiş logoyu yükle (varsa)."""
        if not PIL_AVAILABLE:
            return
        if not os.path.exists(self.IMAGE_PATH):
            return
        try:
            img = Image.open(self.IMAGE_PATH).convert("RGBA")
            img = img.resize((self.SIZE, self.SIZE), Image.Resampling.LANCZOS)
            self.photo = ImageTk.PhotoImage(img)
            self.has_image = True
        except Exception as e:
            print(f"○ Özel logo yüklenemedi: {e}")
            self.has_image = False

    def _redraw(self):
        """Canvas'ı duruma göre yeniden çiz."""
        self.canvas.delete("all")
        if self.has_image and self.photo is not None:
            # Resmi yerleştir
            self.canvas.create_image(
                self.SIZE // 2, self.SIZE // 2, image=self.photo
            )
            # Hover durumunda sağ altta küçük '+' rozeti
            if self._hover:
                x = self.SIZE - 10
                y = self.SIZE - 10
                r = 8
                self.canvas.create_oval(
                    x - r, y - r, x + r, y + r,
                    fill=THK_KIRMIZI, outline="white", width=1
                )
                self.canvas.create_text(
                    x, y, text="+", fill="white",
                    font=("Helvetica", 10, "bold"),
                )
        else:
            # Boş durum: merkezde büyük '+'
            self.canvas.create_text(
                self.SIZE // 2, self.SIZE // 2,
                text="+", fill=THK_BEYAZ,
                font=("Helvetica", 24, "bold"),
            )

    # ----- event handler'lar -----

    def _on_enter(self, _event):
        self._hover = True
        self._redraw()

    def _on_leave(self, _event):
        self._hover = False
        self._redraw()

    def _on_click(self, _event):
        """Dosya seçtir, seç, boyutla, kaydet, göster."""
        if not PIL_AVAILABLE:
            messagebox.showerror(
                "Eksik kütüphane",
                "Pillow kütüphanesi kurulu değil.\npip install Pillow"
            )
            return

        path = filedialog.askopenfilename(
            title="Logo Resmi Seçin",
            filetypes=[
                ("Resim dosyaları", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"),
                ("Tüm dosyalar", "*.*"),
            ],
        )
        if not path:
            return  # kullanıcı iptal etti

        try:
            self._ensure_assets_dir()
            img = Image.open(path).convert("RGBA")
            img = img.resize((self.SIZE, self.SIZE), Image.Resampling.LANCZOS)
            # Kalıcı saklama: her zaman PNG olarak (şeffaflık koruması için)
            img.save(self.IMAGE_PATH, "PNG")
            self.photo = ImageTk.PhotoImage(img)
            self.has_image = True
            self._redraw()
        except Exception as e:
            messagebox.showerror("Hata", f"Resim yüklenemedi:\n{e}")


class RoundedButton(tk.Canvas):
    """Kenarları yuvarlatılmış, modern görünümlü canvas tabanlı buton.

    Standart ttk.Button `border-radius` desteklemediği için canvas üzerinde
    manuel olarak yuvarlatılmış dikdörtgen çiziyoruz. Hover ve pressed
    durumlarında renk değişir → daha kullanıcı dostu.
    """

    def __init__(self, master, text, command=None,
                 bg=None, fg="white", hover_bg=None, pressed_bg=None,
                 font=("Helvetica", 11, "bold"),
                 width=180, height=44, radius=14,
                 parent_bg=None):
        """Canvas tabanlı yuvarlatılmış buton.

        Not: tk.Canvas'ın kendi 'width'/'height' argümanları ile karışmayı
        önlemek için hiç **kwargs almıyoruz. Tüm parametreler explicit.
        """
        # Arka plan rengini parent'tan al (Canvas'ın "bg"i dışarı taşmasın)
        if parent_bg is None:
            try:
                parent_bg = master.cget("bg")
            except (tk.TclError, AttributeError):
                parent_bg = "#f5f5f5"
            # ttk widget'larından dönen değer bazen boş string olabilir
            if not parent_bg:
                parent_bg = "#f5f5f5"

        # Önce Canvas'ı minimum argümanla initialize et
        tk.Canvas.__init__(
            self, master,
            width=int(width), height=int(height),
            bg=parent_bg,
            highlightthickness=0,
            bd=0,
        )
        self.configure(cursor="hand2")

        self._text = text
        self._command = command
        self._w_px = int(width)
        self._h_px = int(height)
        self._r = int(radius)
        self._font = font
        self._fg = fg
        self._bg = bg if bg is not None else THK_KIRMIZI
        self._hover_bg = hover_bg if hover_bg is not None else self._shift(self._bg, -20)
        self._pressed_bg = pressed_bg if pressed_bg is not None else self._shift(self._bg, -40)
        self._current_bg = self._bg
        self._disabled = False

        self._shape_id = None
        self._text_id = None
        self._draw()

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

    # ---- çizim ----

    @staticmethod
    def _shift(hex_color: str, delta: int) -> str:
        """Hex rengi delta kadar aydınlat/karart (-255..+255)."""
        h = hex_color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        r = max(0, min(255, r + delta))
        g = max(0, min(255, g + delta))
        b = max(0, min(255, b + delta))
        return f"#{r:02x}{g:02x}{b:02x}"

    def _rounded_rect_points(self, x1, y1, x2, y2, r):
        """Yuvarlatılmış dikdörtgen için bir polygon nokta dizisi üret."""
        return [
            x1 + r, y1,
            x2 - r, y1,
            x2, y1,
            x2, y1 + r,
            x2, y2 - r,
            x2, y2,
            x2 - r, y2,
            x1 + r, y2,
            x1, y2,
            x1, y2 - r,
            x1, y1 + r,
            x1, y1,
        ]

    def _draw(self):
        self.delete("all")
        pts = self._rounded_rect_points(1, 1, self._w_px - 1, self._h_px - 1, self._r)
        self._shape_id = self.create_polygon(
            pts, smooth=True, splinesteps=36,
            fill=self._current_bg, outline="",
        )
        self._text_id = self.create_text(
            self._w_px // 2, self._h_px // 2,
            text=self._text, fill=self._fg, font=self._font,
        )

    # ---- events ----

    def _on_enter(self, _e):
        if self._disabled:
            return
        self._current_bg = self._hover_bg
        self.itemconfig(self._shape_id, fill=self._current_bg)

    def _on_leave(self, _e):
        if self._disabled:
            return
        self._current_bg = self._bg
        self.itemconfig(self._shape_id, fill=self._current_bg)

    def _on_press(self, _e):
        if self._disabled:
            return
        self._current_bg = self._pressed_bg
        self.itemconfig(self._shape_id, fill=self._current_bg)

    def _on_release(self, event):
        if self._disabled:
            return
        # Tıklama bırakıldığında hover durumuna geri dön ve komutu çalıştır
        # Ama kullanıcı mouse'u buton dışına kaydırıp bıraktıysa tetikleme
        x, y = event.x, event.y
        if 0 <= x <= self._w_px and 0 <= y <= self._h_px:
            self._current_bg = self._hover_bg
            self.itemconfig(self._shape_id, fill=self._current_bg)
            if self._command is not None:
                try:
                    self._command()
                except Exception as exc:
                    print(f"RoundedButton komutu hata verdi: {exc}")
                    raise
        else:
            self._current_bg = self._bg
            self.itemconfig(self._shape_id, fill=self._current_bg)

    # ---- API ----

    def config_text(self, text: str):
        self._text = text
        self.itemconfig(self._text_id, text=text)

    def set_disabled(self, disabled: bool):
        self._disabled = disabled
        self.configure(cursor="" if disabled else "hand2")
        self.itemconfig(
            self._shape_id,
            fill=self._shift(self._bg, 60) if disabled else self._bg,
        )


class SettingsGearWidget(tk.Canvas):
    """Login ekranının sol-altına yerleştirilen küçük dişli ikon.

    Tıklayınca dil seçim popup'ını açar. Canvas üzerinde el ile çizilmiş
    bir dişli ikon — image asset bağımlılığı yok.
    """

    SIZE = 36
    DEFAULT_COLOR = "#cfd6e2"
    HOVER_COLOR = "#ffffff"

    def __init__(self, master, command=None, bg=None, **kwargs):
        # Parent background'ını çıkarsa (Canvas'ın çevresi belli olmasın)
        if bg is None:
            try:
                bg = master.cget("bg")
            except (tk.TclError, AttributeError):
                bg = "#1a3a6e"
            if not bg:
                bg = "#1a3a6e"

        tk.Canvas.__init__(
            self, master,
            width=self.SIZE, height=self.SIZE,
            bg=bg, highlightthickness=0, bd=0,
        )
        self.configure(cursor="hand2")
        self._command = command
        self._bg = bg
        self._color = self.DEFAULT_COLOR
        self._draw()

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)

    def _draw(self):
        self.delete("all")
        cx = cy = self.SIZE // 2
        # Dış dişler — bir polygon ile 8 dişli yıldız benzeri şekil
        # Açıların radyal koordinatlarını hesaplayıp aralıklı dış/iç noktalarla
        # tipik bir dişli silüeti elde ediyoruz.
        import math
        teeth = 8
        outer_r = self.SIZE / 2 - 2
        inner_r = outer_r * 0.78
        pts = []
        # Her diş için 4 nokta: iki dış köşe + iki iç köşe
        for i in range(teeth):
            a0 = (i / teeth) * 2 * math.pi
            a1 = ((i + 0.4) / teeth) * 2 * math.pi
            a2 = ((i + 0.6) / teeth) * 2 * math.pi
            a3 = ((i + 1.0) / teeth) * 2 * math.pi
            for a, r in ((a0, outer_r), (a1, outer_r),
                         (a2, inner_r), (a3, inner_r)):
                pts.append(cx + r * math.cos(a))
                pts.append(cy + r * math.sin(a))
        self._gear_id = self.create_polygon(
            pts, fill=self._color, outline="", smooth=False,
        )
        # Merkez delik
        hole_r = outer_r * 0.32
        self.create_oval(
            cx - hole_r, cy - hole_r, cx + hole_r, cy + hole_r,
            fill=self._bg, outline="",
        )

    def _on_enter(self, _e):
        self._color = self.HOVER_COLOR
        self._draw()

    def _on_leave(self, _e):
        self._color = self.DEFAULT_COLOR
        self._draw()

    def _on_click(self, _e):
        if self._command is not None:
            self._command()


def open_language_popup(parent, on_select=None):
    """Dil seçim popup'ını aç.

    on_select: callable(lang_code: str). Kullanıcı bir dil seçtiğinde
    çağrılır. Genelde GUI'nin mevcut ekranı yeniden çizmesi için kullanılır.
    """
    popup = tk.Toplevel(parent)
    popup.title(_('settings.lang_title'))
    popup.transient(parent)
    popup.grab_set()
    popup.resizable(False, False)
    popup.configure(bg=THK_LACIVERT)

    # Boyut + ortala
    w, h = 360, 280
    parent.update_idletasks()
    px = parent.winfo_rootx() + (parent.winfo_width() // 2) - (w // 2)
    py = parent.winfo_rooty() + (parent.winfo_height() // 2) - (h // 2)
    popup.geometry(f"{w}x{h}+{max(px, 0)}+{max(py, 0)}")

    # Başlık
    tk.Label(
        popup, text=_('settings.lang_title'),
        font=('Helvetica', 18, 'bold'),
        fg=THK_BEYAZ, bg=THK_LACIVERT,
    ).pack(pady=(20, 5))

    tk.Label(
        popup, text=_('settings.lang_prompt'),
        font=('Helvetica', 10),
        fg="#cfd6e2", bg=THK_LACIVERT,
        wraplength=300, justify='center',
    ).pack(pady=(0, 18))

    current = i18n.get_lang()

    def _choose(lang_code: str):
        i18n.set_lang(lang_code)
        popup.destroy()
        if on_select is not None:
            on_select(lang_code)

    # Bayrak emojileri + dil adı (her satır bir buton)
    # Eğer Windows'ta emoji görünmezse, kullanıcı yine de yazıyı görür.
    options = [
        ('tr', "🇹🇷  Türkçe"),
        ('en', "🇺🇸  English"),
    ]

    for code, label in options:
        # Mevcut dil yeşil tonda highlight olsun
        bg_color = "#22c55e" if code == current else THK_LACIVERT_DARK
        RoundedButton(
            popup, text=label,
            command=lambda c=code: _choose(c),
            bg=bg_color, fg=THK_BEYAZ,
            width=240, height=44, radius=14,
            font=('Helvetica', 13, 'bold'),
            parent_bg=THK_LACIVERT,
        ).pack(pady=6)

    # İptal butonu
    def _cancel():
        popup.destroy()

    RoundedButton(
        popup, text=_('common.cancel'), command=_cancel,
        bg="#6b7280", fg=THK_BEYAZ,
        width=120, height=36, radius=12,
        font=('Helvetica', 10),
        parent_bg=THK_LACIVERT,
    ).pack(pady=(15, 10))


class ClassroomLayoutWidget(tk.Frame):
    """Sınıf yerleşim krokisi (6 sıra × 2 blok × 5 koltuk + koridor + kapı + masa).

    Rol tabanlı etkileşim:
      - ogrenci: boş koltuklara tıklayıp oturabilir. Kendi koltuğunun
        üstüne mouse gelince sağ üstte bir "×" belirir, tıklanınca kalkar.
      - akademisyen / admin: koltuk seçemez. Dolu koltuklara mouse gelince
        "×" belirir, tıklanınca oturan öğrenciyi kaldırır.
      - personel: salt-okunur, hiçbir etkileşim yok.

    Seat ID formatı: "R{row}_{side}_{col}"
      row ∈ 1..6, side ∈ {'L','R'}, col ∈ 1..5
    """

    # Varsayılan sabitler — instance bazında __init__ ile override edilebilir
    DEFAULT_ROWS = 6
    COLS_PER_SIDE = 5
    SEAT_W = 40
    SEAT_H = 30
    GAP = 6
    AISLE_W = 24  # orta koridor genişliği
    PAD = 16

    # Renkler (classroom krokisi temalı, fakat THK paleti ile uyumlu)
    BG = "#2d2d2d"
    SEAT_EMPTY = "#404040"
    SEAT_EMPTY_HOVER = "#5a7db8"          # boş koltuğa hover (öğrenci)
    SEAT_MINE = "#4ade80"                  # kendi oturduğum koltuk
    SEAT_OTHER = "#c8102e"                 # başka öğrencinin koltuğu
    SEAT_TEXT_EMPTY = "#a0a0a0"
    SEAT_TEXT_FILLED = "#ffffff"
    DOOR_COLOR = "#4ade80"
    DESK_COLOR = "#2563eb"
    GRID_BORDER = "#404040"

    def __init__(self, master, location_id, current_user,
                 on_change=None, rows=None, **kwargs):
        """
        master: parent widget
        location_id: int — hangi sınıf
        current_user: sqlite Row — kullanıcı bilgisi (id, role, name)
        on_change: callable, her değişiklikten sonra çağrılır
        rows: int — sıra sayısı (verilmezse DEFAULT_ROWS kullanılır).
              Farklı sınıflar (Z-17=6, 102 Amfi=9) için özelleştirilebilir.
        """
        self.rows = rows if rows is not None else self.DEFAULT_ROWS
        # Boyutları önceden hesapla
        grid_w = (self.COLS_PER_SIDE * self.SEAT_W
                  + (self.COLS_PER_SIDE - 1) * self.GAP) * 2 + self.AISLE_W
        grid_h = self.rows * self.SEAT_H + (self.rows - 1) * self.GAP
        # Alt bölüm (kapı + masa için ek yükseklik): 20px boşluk + 44px kapı/masa satırı
        total_w = grid_w + 2 * self.PAD
        total_h = grid_h + 2 * self.PAD + 64

        super().__init__(master, bg=self.BG, **kwargs)
        self.location_id = location_id
        self.current_user = current_user
        self.on_change = on_change

        self.canvas = tk.Canvas(
            self, width=total_w, height=total_h,
            bg=self.BG, highlightthickness=1,
            highlightbackground=self.GRID_BORDER,
        )
        self.canvas.pack()

        # {seat_id: (rect_id, text_id, x1, y1, x2, y2)}
        self._seat_items = {}
        # {canvas_item_id: seat_id}  — hangi canvas item hangi koltuk
        self._item_to_seat = {}
        # Hover durumunda üstte çizilen "×" item id'leri
        self._hover_x_items = []
        self._hovered_seat = None

        # Canvas'ta kroki çizimi
        self._total_w = total_w
        self._total_h = total_h
        self._grid_h = grid_h
        self._grid_w = grid_w

        self._draw_static()
        self.refresh()

        # Mouse olayları
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Leave>", self._on_leave_canvas)
        self.canvas.bind("<Button-1>", self._on_click)

    # ------------------------------------------------------------------
    # Çizim
    # ------------------------------------------------------------------

    def _seat_bbox(self, row, side, col):
        """Verilen koltuğun sol-üst/sağ-alt piksel koordinatları."""
        x0 = self.PAD
        # Sol bloktaki sütun genişliği + aralıkları; sağ bloğa geçiş için aisle ekle
        col_offset = col * (self.SEAT_W + self.GAP) - self.GAP  # col 1-based: col=1 → 0..SEAT_W
        # Aslında col 1 → offset 0; col 2 → SEAT_W + GAP; genel: (col-1)*(SEAT_W+GAP)
        col_offset = (col - 1) * (self.SEAT_W + self.GAP)
        if side == 'L':
            x = x0 + col_offset
        else:
            left_block_w = self.COLS_PER_SIDE * self.SEAT_W + (self.COLS_PER_SIDE - 1) * self.GAP
            x = x0 + left_block_w + self.AISLE_W + col_offset

        y = self.PAD + (row - 1) * (self.SEAT_H + self.GAP)
        return (x, y, x + self.SEAT_W, y + self.SEAT_H)

    def _draw_static(self):
        """Sabit elemanları çiz (kapı, masa, koltuk dikdörtgen karkasları)."""
        # Her koltuk için rect + text oluştur; içeriği refresh() dolduracak
        for row in range(1, self.rows + 1):
            for side in ('L', 'R'):
                for col in range(1, self.COLS_PER_SIDE + 1):
                    seat_id = f"R{row}_{side}_{col}"
                    x1, y1, x2, y2 = self._seat_bbox(row, side, col)
                    rect = self.canvas.create_rectangle(
                        x1, y1, x2, y2,
                        fill=self.SEAT_EMPTY, outline="",
                        width=0,
                    )
                    # Alt çizgi (koltuk efekti)
                    shadow = self.canvas.create_line(
                        x1, y2, x2, y2, fill="#1a1a1a", width=3,
                    )
                    text = self.canvas.create_text(
                        (x1 + x2) // 2, (y1 + y2) // 2,
                        text="-", fill=self.SEAT_TEXT_EMPTY,
                        font=("Helvetica", 10, "bold"),
                    )
                    self._seat_items[seat_id] = {
                        'rect': rect,
                        'shadow': shadow,
                        'text': text,
                        'bbox': (x1, y1, x2, y2),
                    }
                    self._item_to_seat[rect] = seat_id
                    self._item_to_seat[text] = seat_id

        # Alt bölüm: kapı (sol) ve masa (sağ)
        bottom_y = self.PAD + self._grid_h + 20
        # Kapı
        door_x1 = self.PAD
        door_x2 = self.PAD + 120
        door_y1 = bottom_y
        door_y2 = bottom_y + 40
        self.canvas.create_rectangle(
            door_x1, door_y1, door_x2, door_y2,
            outline=self.DOOR_COLOR, width=2,
            fill="#16331f",
        )
        self.canvas.create_text(
            (door_x1 + door_x2) // 2, (door_y1 + door_y2) // 2,
            text=_('classroom.door'), fill=self.DOOR_COLOR,
            font=("Helvetica", 10, "bold"),
        )
        # Masa
        desk_x2 = self.PAD + self._grid_w
        desk_x1 = desk_x2 - 160
        desk_y1 = bottom_y
        desk_y2 = bottom_y + 40
        self.canvas.create_rectangle(
            desk_x1, desk_y1, desk_x2, desk_y2,
            fill=self.DESK_COLOR, outline="",
        )
        self.canvas.create_text(
            (desk_x1 + desk_x2) // 2, (desk_y1 + desk_y2) // 2,
            text=_('classroom.desk'), fill="white",
            font=("Helvetica", 9, "bold"),
        )

    def refresh(self):
        """DB'den koltuk durumunu oku ve krokiyi güncelle."""
        seats = db.get_classroom_seats(self.location_id)
        my_id = self.current_user['id']

        for seat_id, items in self._seat_items.items():
            info = seats.get(seat_id)
            if info is None:
                # Boş koltuk
                self.canvas.itemconfig(items['rect'], fill=self.SEAT_EMPTY)
                self.canvas.itemconfig(items['text'], text="-", fill=self.SEAT_TEXT_EMPTY)
            elif info['student_id'] == my_id:
                # Kendi koltuğum
                self.canvas.itemconfig(items['rect'], fill=self.SEAT_MINE)
                # İsmin ilk harfleri (baş harf soyadın baş harfi gibi)
                initials = self._initials(info['student_name'])
                self.canvas.itemconfig(items['text'], text=initials, fill=self.SEAT_TEXT_FILLED)
            else:
                # Başka öğrencinin koltuğu
                self.canvas.itemconfig(items['rect'], fill=self.SEAT_OTHER)
                initials = self._initials(info['student_name'])
                self.canvas.itemconfig(items['text'], text=initials, fill=self.SEAT_TEXT_FILLED)

        # Hover artifact'larını temizle — refresh sonrası kaybolsun
        self._clear_hover_overlay()
        self._hovered_seat = None
        self._seats_cache = seats  # _on_motion içinde tekrar DB sorgusu yapmamak için

    @staticmethod
    def _initials(name: str) -> str:
        parts = [p for p in name.strip().split() if p]
        if not parts:
            return "-"
        if len(parts) == 1:
            return parts[0][:2].upper()
        return (parts[0][0] + parts[-1][0]).upper()

    # ------------------------------------------------------------------
    # Hover & X overlay
    # ------------------------------------------------------------------

    def _clear_hover_overlay(self):
        for item in self._hover_x_items:
            try:
                self.canvas.delete(item)
            except tk.TclError:
                pass
        self._hover_x_items = []

    def _should_show_x(self, seat_id):
        """Bu koltuğun üstüne gelince X gösterilmeli mi?"""
        info = getattr(self, '_seats_cache', {}).get(seat_id)
        role = self.current_user['role']
        if role == 'ogrenci':
            # Sadece kendi koltuğunda X göster (kalk demek için)
            return info is not None and info['student_id'] == self.current_user['id']
        if role in ('akademisyen', 'admin'):
            # Dolu her koltukta X göster (oturanı kaldırmak için)
            return info is not None
        # personel
        return False

    def _draw_x_overlay(self, seat_id):
        items = self._seat_items[seat_id]
        x1, y1, x2, y2 = items['bbox']
        # Sağ üst köşede küçük kırmızı rozet
        bx2 = x2 - 2
        by1 = y1 + 2
        bx1 = bx2 - 16
        by2 = by1 + 16
        badge = self.canvas.create_oval(
            bx1, by1, bx2, by2,
            fill="#c8102e", outline="white", width=1,
        )
        xtxt = self.canvas.create_text(
            (bx1 + bx2) // 2, (by1 + by2) // 2,
            text="✕", fill="white",
            font=("Helvetica", 9, "bold"),
        )
        self._hover_x_items = [badge, xtxt]
        # Item → seat mapping (X'e de tıklanabilir olsun)
        self._item_to_seat[badge] = seat_id
        self._item_to_seat[xtxt] = seat_id

    def _on_motion(self, event):
        item = self.canvas.find_closest(event.x, event.y)
        seat_id = self._item_to_seat.get(item[0] if item else None) if item else None

        # Bbox dışında mı?
        if seat_id is not None:
            x1, y1, x2, y2 = self._seat_items[seat_id]['bbox']
            if not (x1 <= event.x <= x2 and y1 <= event.y <= y2):
                # Aslında koltuk dışında → seat_id'yi iptal et
                # AMA: X rozeti bbox dışına taşabilir. Kontrol edelim.
                if self._hovered_seat != seat_id:
                    seat_id = None
                # else: zaten X'in üzerindeyiz, mevcut hover devam etsin
        if seat_id != self._hovered_seat:
            self._clear_hover_overlay()
            self._hovered_seat = seat_id
            if seat_id and self._should_show_x(seat_id):
                self._draw_x_overlay(seat_id)
            # Öğrenci için: boş koltuk üstüne gelince hafif vurgu
            self._update_empty_hover(seat_id)

    def _update_empty_hover(self, seat_id):
        """Öğrenci boş bir koltuğun üstündeyse hafif renk değişimi."""
        # Önce tüm boş koltukları başa döndür
        seats = getattr(self, '_seats_cache', {})
        for sid, items in self._seat_items.items():
            if sid in seats:
                continue  # dolu — zaten kendi rengi var
            if sid == seat_id and self.current_user['role'] == 'ogrenci':
                self.canvas.itemconfig(items['rect'], fill=self.SEAT_EMPTY_HOVER)
            else:
                self.canvas.itemconfig(items['rect'], fill=self.SEAT_EMPTY)

    def _on_leave_canvas(self, _event):
        self._clear_hover_overlay()
        self._hovered_seat = None
        # Boş koltukları normal renge döndür
        seats = getattr(self, '_seats_cache', {})
        for sid, items in self._seat_items.items():
            if sid not in seats:
                self.canvas.itemconfig(items['rect'], fill=self.SEAT_EMPTY)

    # ------------------------------------------------------------------
    # Tıklama
    # ------------------------------------------------------------------

    def _on_click(self, event):
        item = self.canvas.find_closest(event.x, event.y)
        if not item:
            return
        seat_id = self._item_to_seat.get(item[0])
        if not seat_id:
            return

        # Tıklama gerçekten bbox içinde mi? (rozet koltuk bbox'ı dışına 2px taşabilir,
        # biz yine koltuk tıklaması sayarız)
        x1, y1, x2, y2 = self._seat_items[seat_id]['bbox']
        in_bbox = x1 - 4 <= event.x <= x2 + 4 and y1 - 4 <= event.y <= y2 + 4
        if not in_bbox:
            return

        # X rozeti mi tıklandı? (sağ-üst köşede 16x16)
        bx2 = x2 - 2
        by1 = y1 + 2
        bx1 = bx2 - 16
        by2 = by1 + 16
        on_x_badge = (bx1 <= event.x <= bx2 and by1 <= event.y <= by2)

        role = self.current_user['role']
        seats = getattr(self, '_seats_cache', {})
        info = seats.get(seat_id)

        if role == 'ogrenci':
            if info is None:
                # Boş koltuk → otur
                ok, msg = db.assign_seat(self.location_id, seat_id, self.current_user['id'])
                if not ok:
                    messagebox.showwarning(_('classroom.cannot_sit'), msg)
            elif info['student_id'] == self.current_user['id']:
                # Kendi koltuğuma tıkladım:
                # - X rozetine bastıysam → kalk
                # - koltuğun gövdesine bastıysam hiçbir şey yapma
                if on_x_badge:
                    ok, msg = db.release_seat(self.location_id, self.current_user['id'])
                    if not ok:
                        messagebox.showwarning(_('classroom.cannot_leave'), msg)
                # else: yok say — yanlışlıkla kalkmayı önle
            else:
                # Başkasının koltuğu — hiçbir şey yapma
                pass
            self.refresh()
            if self.on_change:
                self.on_change()
            return

        if role in ('akademisyen', 'admin'):
            if info is not None and on_x_badge:
                # Akademisyen/admin öğrenciyi kaldırıyor
                if messagebox.askyesno(
                    _('common.confirm'),
                    _('classroom.remove_confirm',
                      name=info['student_name'], seat=seat_id),
                ):
                    ok, msg, sid = db.release_seat_by_seat_id(self.location_id, seat_id)
                    if not ok:
                        messagebox.showwarning(_('classroom.cannot_remove'), msg)
                    self.refresh()
                    if self.on_change:
                        self.on_change()
            # Boş koltuğa tıklamak akademisyen/admin için no-op
            return

        # Personel: hiçbir şey yapma (salt-okunur)


class AttendanceSystem:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("THK Üniversitesi - Yüz Tanıma Yoklama Sistemi")
        self.root.geometry("1200x800")
        self.root.configure(bg=THK_LACIVERT)
        
        # Logo
        self.logo_image = None
        self.load_logo()
        
        # Termometre
        self.thermometer_image = None
        self.load_thermometer()
        
        # Sıcaklık widget durumu
        self.temp_widget_frame = None
        self.temp_label = None
        self.temp_animation_id = None
        
        # Stil ayarları
        self.style = ttk.Style()
        self.style.theme_use('clam')
        self.configure_styles()
        
        # Mevcut kullanıcı
        self.current_user = None
        self.current_location = None
        
        # Veritabanını başlat
        db.init_database()
        db.init_default_data()
        
        # Ana frame
        self.main_frame = ttk.Frame(self.root, style='Main.TFrame')
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Giriş ekranını göster
        self.show_login_screen()
    
    def load_logo(self):
        """THK logosunu yükle"""
        logo_paths = ["logo.png", "thk_logo.png", "assets/logo.png"]
        
        if PIL_AVAILABLE:
            for path in logo_paths:
                if os.path.exists(path):
                    try:
                        img = Image.open(path)
                        # Logo boyutunu ayarla
                        img = img.resize((200, 200), Image.Resampling.LANCZOS)
                        self.logo_image = ImageTk.PhotoImage(img)
                        print(f"✓ Logo yüklendi: {path}")
                        return
                    except Exception as e:
                        print(f"Logo yüklenemedi: {e}")
        
        print("○ Logo bulunamadı (logo.png dosyasını klasöre ekleyin)")
    
    def load_thermometer(self):
        """Termometre ikonunu yükle"""
        if PIL_AVAILABLE:
            thermo_paths = ["termometre.png", "assets/termometre.png"]
            for path in thermo_paths:
                if os.path.exists(path):
                    try:
                        img = Image.open(path)
                        img = img.resize((48, 48), Image.Resampling.LANCZOS)
                        self.thermometer_image = ImageTk.PhotoImage(img)
                        print(f"✓ Termometre ikonu yüklendi: {path}")
                        return
                    except Exception as e:
                        print(f"Termometre yüklenemedi: {e}")
        print("○ Termometre ikonu bulunamadı")
        
    def configure_styles(self):
        """THK temalı stil ayarları"""
        # Frame stilleri
        self.style.configure('Main.TFrame', background=THK_GRI)
        self.style.configure('Login.TFrame', background=THK_LACIVERT)
        self.style.configure('Card.TFrame', background=THK_BEYAZ)
        
        # Label stilleri - Giriş ekranı için
        self.style.configure('Title.TLabel', 
                            font=('Helvetica', 28, 'bold'), 
                            foreground=THK_BEYAZ,
                            background=THK_LACIVERT)
        self.style.configure('Subtitle.TLabel', 
                            font=('Helvetica', 16), 
                            foreground=THK_BEYAZ,
                            background=THK_LACIVERT)
        self.style.configure('LoginInfo.TLabel', 
                            font=('Helvetica', 10), 
                            foreground=THK_BEYAZ,
                            background=THK_LACIVERT)
        
        # Label stilleri - Normal ekranlar için
        self.style.configure('Header.TLabel', 
                            font=('Helvetica', 18, 'bold'), 
                            foreground=THK_LACIVERT,
                            background=THK_GRI)
        self.style.configure('Normal.TLabel', 
                            font=('Helvetica', 11), 
                            background=THK_GRI)
        
        # Buton stilleri
        self.style.configure('Big.TButton', 
                            font=('Helvetica', 14, 'bold'), 
                            padding=15,
                            background=THK_KIRMIZI,
                            foreground=THK_BEYAZ)
        self.style.map('Big.TButton',
                      background=[('active', THK_LACIVERT_DARK)])
        
        self.style.configure('Action.TButton', 
                            font=('Helvetica', 12), 
                            padding=10)
        self.style.configure('Location.TButton', 
                            font=('Helvetica', 11), 
                            padding=8)
        
        # Kırmızı buton stili
        self.style.configure('Red.TButton',
                            font=('Helvetica', 14, 'bold'),
                            padding=15)
        
    def clear_frame(self):
        """Frame'i temizle"""
        # Sıcaklık widget'ını temizle
        if self.temp_animation_id:
            self.root.after_cancel(self.temp_animation_id)
            self.temp_animation_id = None
        self.temp_widget_frame = None
        self.temp_label = None
        
        for widget in self.main_frame.winfo_children():
            widget.destroy()
    
    # ==================== GİRİŞ EKRANI ====================
    
    def show_login_screen(self):
        """THK temalı giriş ekranını göster"""
        self.clear_frame()
        self.current_user = None
        
        # Ana frame'i lacivert yap
        self.main_frame.configure(style='Login.TFrame')
        self.root.configure(bg=THK_LACIVERT)
        
        # Üst boşluk
        spacer_top = tk.Frame(self.main_frame, bg=THK_LACIVERT, height=30)
        spacer_top.pack(fill=tk.X)
        
        # Logo satırı: [✈️] [64×64 özel slot] [THK]
        # Eğer logo.png varsa onu tek başına göstermeye devam ediyoruz;
        # yoksa metin tabanlı yatay düzen + opsiyonel özel slot kullanıyoruz.
        if self.logo_image:
            logo_label = tk.Label(self.main_frame, image=self.logo_image, bg=THK_LACIVERT)
            logo_label.pack(pady=20)
        else:
            logo_row = tk.Frame(self.main_frame, bg=THK_LACIVERT)
            logo_row.pack(pady=20)

            # Sol: uçak simgesi
            plane_lbl = tk.Label(
                logo_row, text="✈️",
                font=('Helvetica', 48, 'bold'),
                fg=THK_BEYAZ, bg=THK_LACIVERT,
            )
            plane_lbl.pack(side=tk.LEFT, padx=12)

            # Orta: 64×64 opsiyonel özel logo slotu
            custom_slot = CustomLogoWidget(logo_row, bg=THK_LACIVERT)
            custom_slot.pack(side=tk.LEFT, padx=12, pady=6)
            # Referansı garbage collect olmasın diye sakla
            self._custom_logo_widget = custom_slot

            # Sağ: THK yazısı
            thk_lbl = tk.Label(
                logo_row, text="THK",
                font=('Helvetica', 48, 'bold'),
                fg=THK_BEYAZ, bg=THK_LACIVERT,
            )
            thk_lbl.pack(side=tk.LEFT, padx=12)
        
        # Üniversite adı
        uni_name = tk.Label(self.main_frame, 
                           text="TÜRK HAVA KURUMU ÜNİVERSİTESİ",
                           font=('Helvetica', 24, 'bold'),
                           fg=THK_BEYAZ, bg=THK_LACIVERT)
        uni_name.pack(pady=5)
        
        # Alt başlık
        subtitle = tk.Label(self.main_frame, 
                           text=_('login.subtitle'),
                           font=('Helvetica', 16),
                           fg=THK_KIRMIZI, bg=THK_LACIVERT)
        subtitle.pack(pady=5)
        
        faculty = tk.Label(self.main_frame, 
                          text=_('login.faculty'),
                          font=('Helvetica', 14),
                          fg=THK_BEYAZ, bg=THK_LACIVERT)
        faculty.pack(pady=5)
        
        # Butonlar için çerçeve
        btn_frame = tk.Frame(self.main_frame, bg=THK_LACIVERT)
        btn_frame.pack(pady=40)

        # Yüz ile giriş butonu (Kırmızı, yuvarlatılmış)
        face_btn = RoundedButton(
            btn_frame, text=_('login.face_login'),
            command=self.face_login,
            bg=THK_KIRMIZI, fg=THK_BEYAZ,
            width=280, height=52, radius=16,
            font=('Helvetica', 14, 'bold'),
        )
        face_btn.pack(pady=10)

        # Manuel giriş butonu (Lacivert koyu)
        manual_btn = RoundedButton(
            btn_frame, text=_('login.manual_login'),
            command=self.show_manual_login,
            bg=THK_LACIVERT_DARK, fg=THK_BEYAZ,
            width=280, height=52, radius=16,
            font=('Helvetica', 14),
        )
        manual_btn.pack(pady=10)

        # Yeni yüz kaydı butonu
        register_btn = RoundedButton(
            btn_frame, text=_('login.face_register'),
            command=self.show_face_register,
            bg=THK_LACIVERT_DARK, fg=THK_BEYAZ,
            width=280, height=52, radius=16,
            font=('Helvetica', 14),
        )
        register_btn.pack(pady=10)
        
        # Alt bilgi
        info_frame = tk.Frame(self.main_frame, bg=THK_LACIVERT)
        info_frame.pack(side=tk.BOTTOM, pady=20)
        
        # Kırmızı çizgi
        line = tk.Frame(info_frame, bg=THK_KIRMIZI, height=2, width=400)
        line.pack(pady=10)
        
        info = tk.Label(info_frame, 
                       text=_('login.footer'),
                       font=('Helvetica', 10),
                       fg=THK_BEYAZ, bg=THK_LACIVERT)
        info.pack()

        # Sol alt: Ayarlar (Dil) dişli ikonu
        gear = SettingsGearWidget(
            self.main_frame,
            command=lambda: open_language_popup(
                self.root,
                on_select=lambda code: self.show_login_screen(),
            ),
            bg=THK_LACIVERT,
        )
        gear.place(relx=0.0, rely=1.0, anchor='sw', x=15, y=-15)

        # Sistem Sıcaklığı butonu - sağ alt köşe
        temp_btn = tk.Button(self.main_frame,
                             text="🌡  Sistem Sıcaklığı",
                             font=('Helvetica', 10, 'bold'),
                             fg=THK_BEYAZ, bg=THK_LACIVERT_DARK,
                             activebackground=THK_KIRMIZI,
                             activeforeground=THK_BEYAZ,
                             bd=1, relief='solid',
                             cursor='hand2',
                             padx=12, pady=6,
                             command=self.toggle_temp_widget)
        temp_btn.place(relx=1.0, rely=1.0, anchor='se', x=-15, y=-15)
        
    def toggle_temp_widget(self):
        """Sıcaklık widget'ını aç/kapa"""
        if self.temp_widget_frame and self.temp_widget_frame.winfo_exists():
            self.close_temp_widget()
        else:
            self.open_temp_widget()
    
    def open_temp_widget(self):
        """Sıcaklık widget'ını aç"""
        # Önceki animasyonu iptal et
        if self.temp_animation_id:
            self.root.after_cancel(self.temp_animation_id)
            self.temp_animation_id = None
        
        # Widget çerçevesi - sağ alt köşede, butonun üstünde
        self.temp_widget_frame = tk.Frame(self.main_frame,
                                          bg='#152d5a',
                                          bd=2,
                                          relief='solid',
                                          highlightbackground=THK_KIRMIZI,
                                          highlightthickness=1)
        self.temp_widget_frame.place(relx=1.0, rely=1.0, anchor='se', x=-15, y=-55,
                                      width=220, height=120)
        
        # Üst bar - başlık ve çarpı butonu
        top_bar = tk.Frame(self.temp_widget_frame, bg=THK_LACIVERT_DARK)
        top_bar.pack(fill=tk.X)
        
        title_lbl = tk.Label(top_bar, text="Sistem Sıcaklığı",
                             font=('Helvetica', 9, 'bold'),
                             fg=THK_BEYAZ, bg=THK_LACIVERT_DARK,
                             padx=8, pady=4)
        title_lbl.pack(side=tk.LEFT)
        
        close_btn = tk.Button(top_bar, text="✕",
                              font=('Helvetica', 10, 'bold'),
                              fg=THK_KIRMIZI, bg=THK_LACIVERT_DARK,
                              activebackground=THK_KIRMIZI,
                              activeforeground=THK_BEYAZ,
                              bd=0, cursor='hand2',
                              padx=6, pady=2,
                              command=self.close_temp_widget)
        close_btn.pack(side=tk.RIGHT)
        
        # İçerik alanı
        content = tk.Frame(self.temp_widget_frame, bg='#152d5a')
        content.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)
        
        # Termometre ikonu
        if self.thermometer_image:
            thermo_lbl = tk.Label(content, image=self.thermometer_image, bg='#152d5a')
            thermo_lbl.pack(side=tk.LEFT, padx=(0, 10))
        else:
            # Fallback: emoji termometre
            thermo_lbl = tk.Label(content, text="🌡",
                                  font=('Helvetica', 32),
                                  bg='#152d5a')
            thermo_lbl.pack(side=tk.LEFT, padx=(0, 10))
        
        # Sıcaklık değeri
        self.temp_label = tk.Label(content, text="--°C",
                                   font=('Helvetica', 28, 'bold'),
                                   fg='#4fc3f7', bg='#152d5a')
        self.temp_label.pack(side=tk.LEFT)
        
        # Animasyonu başlat
        self.start_temp_animation()
    
    def close_temp_widget(self):
        """Sıcaklık widget'ını kapat"""
        if self.temp_animation_id:
            self.root.after_cancel(self.temp_animation_id)
            self.temp_animation_id = None
        if self.temp_widget_frame and self.temp_widget_frame.winfo_exists():
            self.temp_widget_frame.destroy()
        self.temp_widget_frame = None
        self.temp_label = None
    
    def start_temp_animation(self):
        """Sıcaklık animasyonunu başlat"""
        # Sıcaklık adımları: (değer, süre_ms)
        steps = [
            ("1°C", 2000),     # 2 saniye
            ("71°C", 1000),    # 1 saniye
            ("68°C", 1000),    # 1 saniye
            ("69°C", 1000),    # 1 saniye
            ("65°C", 1000),    # 1 saniye
            ("64°C", 2000),    # 2 saniye
            ("63°C", 2000),    # 2 saniye
            ("64°C", None),    # Kalıcı
        ]
        
        def animate(step_index):
            if not self.temp_label or not self.temp_label.winfo_exists():
                return
            
            text, duration = steps[step_index]
            self.temp_label.config(text=text)
            
            # Renk ayarla - sıcaklığa göre
            temp_val = int(text.replace("°C", ""))
            if temp_val <= 30:
                self.temp_label.config(fg='#4fc3f7')   # Mavi - soğuk
            elif temp_val <= 60:
                self.temp_label.config(fg='#ffb74d')   # Turuncu - ılık
            elif temp_val <= 70:
                self.temp_label.config(fg='#ff7043')   # Kırmızımsı - sıcak
            else:
                self.temp_label.config(fg='#ef5350')   # Kırmızı - çok sıcak
            
            if duration is not None and step_index < len(steps) - 1:
                self.temp_animation_id = self.root.after(duration, animate, step_index + 1)
        
        animate(0)
    
    def face_login(self):
        """Yüz ile giriş yap"""
        user_id, user_name, message = fm.recognize_face_from_camera(timeout=15)
        
        if user_id:
            self.current_user = db.get_user_by_id(user_id)
            # ID'yi de göster → aynı isimli kullanıcılarda (örn. iki "Selma Toker")
            # tam olarak kimin giriş yaptığı net olur
            messagebox.showinfo("Hoş Geldiniz!",
                                f"Sayın {user_name} (ID: {user_id}), Hoş Geldiniz!")
            self.show_main_menu()
        else:
            messagebox.showerror("Hata", f"Giriş başarısız: {message}")
    
    def show_manual_login(self):
        """Manuel giriş ekranı (test için)"""
        self.clear_frame()
        
        # Arka planı griye döndür
        self.main_frame.configure(style='Main.TFrame')
        self.root.configure(bg=THK_GRI)
        
        ttk.Label(self.main_frame, text="Manuel Giriş", style='Header.TLabel').pack(pady=20)
        
        # Kullanıcı listesi
        users = db.get_all_users()
        
        list_frame = ttk.Frame(self.main_frame)
        list_frame.pack(pady=20, fill=tk.BOTH, expand=True)
        
        # Treeview
        columns = ('ID', 'Ad Soyad', 'Rol', 'Alt Rol')
        tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=15)
        
        for col in columns:
            tree.heading(col, text=col)
            if col == 'ID':
                # ID sütununu ortalanmış ve net görünür yap (aynı isimli
                # kullanıcıları benzersiz ID ile ayırt etmek için - PROBLEM 1)
                tree.column(col, width=60, minwidth=50, anchor='center', stretch=False)
            else:
                tree.column(col, width=150)
        
        for user in users:
            role_tr = {'admin': 'Admin', 'akademisyen': 'Akademisyen', 
                      'personel': 'Personel', 'ogrenci': 'Öğrenci'}
            tree.insert('', tk.END, values=(
                user['id'], user['name'], 
                role_tr.get(user['role'], user['role']),
                user['sub_role'] or '-'
            ))
        
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        def login_selected():
            selected = tree.selection()
            if not selected:
                messagebox.showwarning("Uyarı", "Lütfen bir kullanıcı seçin!")
                return
            
            user_id = parse_leading_id(tree.item(selected[0])['values'][0])
            if user_id is None:
                messagebox.showwarning("Uyarı", "Lütfen bir kullanıcı seçin!")
                return
            self.current_user = db.get_user_by_id(user_id)
            messagebox.showinfo("Hoş Geldiniz!", f"Sayın {self.current_user['name']}, Hoş Geldiniz!")
            self.show_main_menu()
        
        btn_frame = ttk.Frame(self.main_frame)
        btn_frame.pack(pady=20)
        
        ttk.Button(btn_frame, text="Giriş Yap", style='Action.TButton',
                  command=login_selected).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="Geri", style='Action.TButton',
                  command=self.show_login_screen).pack(side=tk.LEFT, padx=10)
    
    def show_face_register(self):
        """Yüz kayıt ekranı"""
        self.clear_frame()
        
        # Arka planı griye döndür
        self.main_frame.configure(style='Main.TFrame')
        self.root.configure(bg=THK_GRI)
        
        ttk.Label(self.main_frame, text="Yüz Kaydı", style='Header.TLabel').pack(pady=20)
        
        # Kullanıcı seçimi
        users = db.get_all_users()
        
        select_frame = ttk.Frame(self.main_frame)
        select_frame.pack(pady=20)
        
        ttk.Label(select_frame, text="Kullanıcı Seçin:").pack()
        
        user_var = tk.StringVar()
        user_combo = ttk.Combobox(select_frame, textvariable=user_var, state='readonly', width=40)
        # "ID - Ad Soyad" biçimi: aynı isimli kullanıcılar benzersiz ID ile ayrışır
        user_combo['values'] = [format_user_option(u) for u in users]
        user_combo.pack(pady=10)
        
        def register_face():
            user_id = parse_leading_id(user_var.get())
            if user_id is None:
                messagebox.showwarning("Uyarı", "Lütfen bir kullanıcı seçin!")
                return
            
            success, encoding, message = fm.capture_face_from_camera(user_id, "Yüz Kaydı")
            
            if success:
                messagebox.showinfo("Başarılı", message)
            else:
                messagebox.showerror("Hata", message)
        
        def register_from_file():
            user_id = parse_leading_id(user_var.get())
            if user_id is None:
                messagebox.showwarning("Uyarı", "Lütfen bir kullanıcı seçin!")
                return
            
            file_path = filedialog.askopenfilename(
                title="Fotoğraf Seçin",
                filetypes=[("Resim Dosyaları", "*.jpg *.jpeg *.png")]
            )
            
            if file_path:
                success, message = fm.register_face_from_file(user_id, file_path)
                if success:
                    messagebox.showinfo("Başarılı", message)
                else:
                    messagebox.showerror("Hata", message)
        
        btn_frame = ttk.Frame(self.main_frame)
        btn_frame.pack(pady=30)
        
        ttk.Button(btn_frame, text="📷 Kameradan Kaydet", style='Action.TButton',
                  command=register_face).pack(pady=10)
        ttk.Button(btn_frame, text="📁 Dosyadan Kaydet", style='Action.TButton',
                  command=register_from_file).pack(pady=10)
        ttk.Button(btn_frame, text="Geri", style='Action.TButton',
                  command=self.show_login_screen).pack(pady=10)
    
    # ==================== ANA MENÜ ====================
    
    def show_main_menu(self):
        """Ana menüyü göster"""
        self.clear_frame()
        
        # Arka planı griye döndür
        self.main_frame.configure(style='Main.TFrame')
        self.root.configure(bg=THK_GRI)
        
        if not self.current_user:
            self.show_login_screen()
            return
        
        role = self.current_user['role']
        
        # Başlık
        header_frame = ttk.Frame(self.main_frame)
        header_frame.pack(fill=tk.X, pady=10)
        
        role_tr = {'admin': 'Admin', 'akademisyen': 'Akademisyen', 
                  'personel': 'Personel', 'ogrenci': 'Öğrenci'}
        
        user_info = f"👤 {self.current_user['name']} ({role_tr.get(role, role)})"
        if self.current_user['sub_role']:
            user_info += f" - {self.current_user['sub_role']}"
        
        ttk.Label(header_frame, text=user_info, style='Header.TLabel').pack(side=tk.LEFT)
        
        ttk.Button(header_frame, text="🚪 Çıkış", command=self.logout).pack(side=tk.RIGHT)
        
        # Menü seçenekleri
        menu_frame = ttk.Frame(self.main_frame)
        menu_frame.pack(pady=30, fill=tk.BOTH, expand=True)
        
        # Sol panel - Mekanlar
        left_frame = ttk.LabelFrame(menu_frame, text="📍 Mekanlar", padding=10)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10)
        
        self.show_locations_panel(left_frame)
        
        # Sağ panel - İşlemler
        right_frame = ttk.LabelFrame(menu_frame, text="⚙️ İşlemler", padding=10)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=10)
        
        if role == 'admin':
            self.show_admin_panel(right_frame)
        elif role == 'akademisyen':
            self.show_akademisyen_panel(right_frame)
        elif role == 'personel':
            self.show_personel_panel(right_frame)
        else:  # ogrenci
            self.show_ogrenci_panel(right_frame)
    
    def show_locations_panel(self, parent):
        """Mekanlar panelini göster"""
        ttk.Label(parent, text="🏛️ Mühendislik Fakültesi", font=('Helvetica', 14, 'bold')).pack(pady=10)
        
        classrooms = db.get_classrooms()
        
        for classroom in classrooms:
            btn = ttk.Button(parent, text=f"🚪 {classroom['name']}", 
                           style='Location.TButton',
                           command=lambda c=classroom: self.select_location(c))
            btn.pack(pady=5, fill=tk.X)
    
    def select_location(self, location):
        """Mekan seçildiğinde"""
        self.current_location = location
        
        role = self.current_user['role']
        
        if role == 'ogrenci':
            self.show_student_attendance(location)
        elif role in ['admin', 'akademisyen']:
            self.show_location_attendance(location)
        else:  # personel
            self.show_location_schedule(location)
    
    # ==================== ADMIN PANELİ ====================
    
    def show_admin_panel(self, parent):
        """Admin panelini göster"""
        admin_buttons = [
            (_('panel.user_management'),       self.show_user_management,       THK_LACIVERT),
            (_('panel.all_attendance'),        self.show_all_attendance,        THK_LACIVERT),
            (_('panel.course_management'),     self.show_course_management,     THK_LACIVERT),
            (_('panel.permission_management'), self.show_permission_management, THK_KIRMIZI),
            (_('panel.critical_absence'),      self.show_critical_absence,      THK_KIRMIZI),
            (_('panel.schedule'),              self.show_schedule,              THK_LACIVERT),
        ]
        for text, cmd, color in admin_buttons:
            RoundedButton(
                parent, text=text, command=cmd,
                bg=color, fg=THK_BEYAZ,
                width=280, height=46, radius=14,
                font=('Helvetica', 12, 'bold'),
            ).pack(pady=8)
    
    def show_user_management(self):
        """Kullanıcı yönetimi ekranı"""
        self.clear_frame()
        
        # Başlık ve geri butonu
        header = ttk.Frame(self.main_frame)
        header.pack(fill=tk.X, pady=10)
        
        ttk.Label(header, text="👥 Kullanıcı Yönetimi", style='Header.TLabel').pack(side=tk.LEFT)
        ttk.Button(header, text="← Geri", command=self.show_main_menu).pack(side=tk.RIGHT)
        
        # Kullanıcı listesi
        list_frame = ttk.Frame(self.main_frame)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        columns = ('ID', 'Ad Soyad', 'Rol', 'Alt Rol', 'Yüz Kaydı')
        self.user_tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=15)
        
        for col in columns:
            self.user_tree.heading(col, text=col)
            if col == 'ID':
                self.user_tree.column(col, width=60, minwidth=50,
                                      anchor='center', stretch=False)
            else:
                self.user_tree.column(col, width=120)
        
        self.refresh_user_list()
        
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.user_tree.yview)
        self.user_tree.configure(yscrollcommand=scrollbar.set)
        
        self.user_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Butonlar
        btn_frame = ttk.Frame(self.main_frame)
        btn_frame.pack(pady=10)
        
        ttk.Button(btn_frame, text="➕ Yeni Kullanıcı", command=self.add_user_dialog).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="✏️ Düzenle", command=self.edit_user_dialog).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="🗑️ Sil", command=self.delete_user).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="📷 Yüz Kaydet", command=self.register_user_face).pack(side=tk.LEFT, padx=5)
    
    def refresh_user_list(self):
        """Kullanıcı listesini yenile"""
        for item in self.user_tree.get_children():
            self.user_tree.delete(item)
        
        users = db.get_all_users()
        role_tr = {'admin': 'Admin', 'akademisyen': 'Akademisyen', 
                  'personel': 'Personel', 'ogrenci': 'Öğrenci'}
        
        for user in users:
            has_face = "✅" if db.get_user_face_encoding(user['id']) is not None else "❌"
            self.user_tree.insert('', tk.END, values=(
                user['id'], user['name'],
                role_tr.get(user['role'], user['role']),
                user['sub_role'] or '-',
                has_face
            ))
    
    def add_user_dialog(self):
        """Yeni kullanıcı ekleme dialogu"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Yeni Kullanıcı Ekle")
        dialog.geometry("400x350")
        dialog.transient(self.root)
        dialog.grab_set()
        
        ttk.Label(dialog, text="Ad Soyad:").pack(pady=5)
        name_entry = ttk.Entry(dialog, width=40)
        name_entry.pack(pady=5)
        
        ttk.Label(dialog, text="Rol:").pack(pady=5)
        role_var = tk.StringVar()
        role_combo = ttk.Combobox(dialog, textvariable=role_var, state='readonly', width=37)
        role_combo['values'] = ['Admin', 'Akademisyen', 'Personel', 'Öğrenci']
        role_combo.pack(pady=5)
        
        ttk.Label(dialog, text="Alt Rol (Opsiyonel):").pack(pady=5)
        sub_role_entry = ttk.Entry(dialog, width=40)
        sub_role_entry.pack(pady=5)
        
        def save():
            name = name_entry.get().strip()
            role = role_var.get()
            sub_role = sub_role_entry.get().strip() or None
            
            if not name or not role:
                messagebox.showwarning("Uyarı", "Ad ve rol zorunludur!")
                return
            
            role_map = {'Admin': 'admin', 'Akademisyen': 'akademisyen',
                       'Personel': 'personel', 'Öğrenci': 'ogrenci'}
            
            db.add_user(name, role_map[role], sub_role)
            messagebox.showinfo("Başarılı", "Kullanıcı eklendi!")
            self.refresh_user_list()
            dialog.destroy()
        
        ttk.Button(dialog, text="Kaydet", command=save).pack(pady=20)
    
    def edit_user_dialog(self):
        """Kullanıcı düzenleme dialogu"""
        selected = self.user_tree.selection()
        if not selected:
            messagebox.showwarning("Uyarı", "Lütfen bir kullanıcı seçin!")
            return
        
        user_id = parse_leading_id(self.user_tree.item(selected[0])['values'][0])
        user = db.get_user_by_id(user_id)
        
        dialog = tk.Toplevel(self.root)
        dialog.title("Kullanıcı Düzenle")
        dialog.geometry("400x350")
        dialog.transient(self.root)
        dialog.grab_set()
        
        ttk.Label(dialog, text="Ad Soyad:").pack(pady=5)
        name_entry = ttk.Entry(dialog, width=40)
        name_entry.insert(0, user['name'])
        name_entry.pack(pady=5)
        
        ttk.Label(dialog, text="Rol:").pack(pady=5)
        role_var = tk.StringVar()
        role_combo = ttk.Combobox(dialog, textvariable=role_var, state='readonly', width=37)
        role_combo['values'] = ['Admin', 'Akademisyen', 'Personel', 'Öğrenci']
        
        role_map_rev = {'admin': 'Admin', 'akademisyen': 'Akademisyen',
                       'personel': 'Personel', 'ogrenci': 'Öğrenci'}
        role_var.set(role_map_rev.get(user['role'], ''))
        role_combo.pack(pady=5)
        
        ttk.Label(dialog, text="Alt Rol:").pack(pady=5)
        sub_role_entry = ttk.Entry(dialog, width=40)
        if user['sub_role']:
            sub_role_entry.insert(0, user['sub_role'])
        sub_role_entry.pack(pady=5)
        
        def save():
            name = name_entry.get().strip()
            role = role_var.get()
            sub_role = sub_role_entry.get().strip() or None
            
            if not name or not role:
                messagebox.showwarning("Uyarı", "Ad ve rol zorunludur!")
                return
            
            role_map = {'Admin': 'admin', 'Akademisyen': 'akademisyen',
                       'Personel': 'personel', 'Öğrenci': 'ogrenci'}
            
            db.update_user(user_id, name, role_map[role], sub_role)
            messagebox.showinfo("Başarılı", "Kullanıcı güncellendi!")
            self.refresh_user_list()
            dialog.destroy()
        
        ttk.Button(dialog, text="Kaydet", command=save).pack(pady=20)
    
    def delete_user(self):
        """Kullanıcı sil"""
        selected = self.user_tree.selection()
        if not selected:
            messagebox.showwarning("Uyarı", "Lütfen bir kullanıcı seçin!")
            return
        
        if messagebox.askyesno("Onay", "Bu kullanıcıyı silmek istediğinizden emin misiniz?"):
            user_id = parse_leading_id(self.user_tree.item(selected[0])['values'][0])
            db.delete_user(user_id)
            self.refresh_user_list()
            messagebox.showinfo("Başarılı", "Kullanıcı silindi!")
    
    def register_user_face(self):
        """Seçili kullanıcının yüzünü kaydet"""
        selected = self.user_tree.selection()
        if not selected:
            messagebox.showwarning("Uyarı", "Lütfen bir kullanıcı seçin!")
            return
        
        user_id = parse_leading_id(self.user_tree.item(selected[0])['values'][0])
        user_name = self.user_tree.item(selected[0])['values'][1]
        
        choice = messagebox.askquestion("Kayıt Yöntemi", 
                                        "Kameradan kayıt için 'Yes', dosyadan kayıt için 'No' tıklayın.")
        
        if choice == 'yes':
            success, encoding, message = fm.capture_face_from_camera(user_id, f"Yüz Kaydı - {user_name}")
        else:
            file_path = filedialog.askopenfilename(
                title="Fotoğraf Seçin",
                filetypes=[("Resim Dosyaları", "*.jpg *.jpeg *.png")]
            )
            if file_path:
                success, message = fm.register_face_from_file(user_id, file_path)
            else:
                return
        
        if success:
            messagebox.showinfo("Başarılı", message)
            self.refresh_user_list()
        else:
            messagebox.showerror("Hata", message)
    
    def show_all_attendance(self):
        """Tüm yoklamaları göster"""
        self.clear_frame()
        
        header = ttk.Frame(self.main_frame)
        header.pack(fill=tk.X, pady=10)
        
        ttk.Label(header, text="📊 Tüm Yoklamalar", style='Header.TLabel').pack(side=tk.LEFT)
        ttk.Button(header, text="← Geri", command=self.show_main_menu).pack(side=tk.RIGHT)
        
        # Filtre
        filter_frame = ttk.Frame(self.main_frame)
        filter_frame.pack(fill=tk.X, pady=10)
        
        ttk.Label(filter_frame, text="Tarih Aralığı:").pack(side=tk.LEFT, padx=5)
        
        start_date = ttk.Entry(filter_frame, width=12)
        start_date.insert(0, datetime.now().strftime('%Y-%m-%d'))
        start_date.pack(side=tk.LEFT, padx=5)
        
        ttk.Label(filter_frame, text="-").pack(side=tk.LEFT)
        
        end_date = ttk.Entry(filter_frame, width=12)
        end_date.insert(0, datetime.now().strftime('%Y-%m-%d'))
        end_date.pack(side=tk.LEFT, padx=5)
        
        def refresh():
            self.refresh_attendance_list(start_date.get(), end_date.get())
        
        ttk.Button(filter_frame, text="🔍 Filtrele", command=refresh).pack(side=tk.LEFT, padx=10)
        
        # Liste
        list_frame = ttk.Frame(self.main_frame)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        columns = ('ID', 'Tarih', 'Kullanıcı', 'Rol', 'Mekan', 'Ders', 'Giriş', 'Çıkış')
        self.attendance_tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=20)
        
        for col in columns:
            heading = _('attendance.col_user_id') if col == 'ID' else col
            self.attendance_tree.heading(col, text=heading)
            if col == 'ID':
                # Aynı isimli kullanıcıları (örn. iki "Selma Toker") ayırt etmek için
                self.attendance_tree.column(col, width=70, minwidth=60,
                                            anchor='center', stretch=False)
            else:
                self.attendance_tree.column(col, width=100)
        
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.attendance_tree.yview)
        self.attendance_tree.configure(yscrollcommand=scrollbar.set)
        
        self.attendance_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        refresh()
    
    def refresh_attendance_list(self, start_date=None, end_date=None):
        """Yoklama listesini yenile"""
        for item in self.attendance_tree.get_children():
            self.attendance_tree.delete(item)
        
        records = db.get_all_attendance(start_date, end_date)
        role_tr = {'admin': 'Admin', 'akademisyen': 'Akademisyen', 
                  'personel': 'Personel', 'ogrenci': 'Öğrenci'}
        
        for record in records:
            check_in = record['check_in_time'][:16] if record['check_in_time'] else '-'
            check_out = record['check_out_time'][:16] if record['check_out_time'] else '-'
            
            self.attendance_tree.insert('', tk.END, values=(
                record['user_id'],
                record['date'],
                record['user_name'],
                role_tr.get(record['role'], record['role']),
                record['location_name'] or '-',
                record['course_name'] or '-',
                check_in,
                check_out
            ))
    
    def show_permission_management(self):
        """Yetki yönetimi ekranı"""
        self.clear_frame()
        
        header = ttk.Frame(self.main_frame)
        header.pack(fill=tk.X, pady=10)
        
        ttk.Label(header, text="🔐 Yetki Yönetimi", style='Header.TLabel').pack(side=tk.LEFT)
        ttk.Button(header, text="← Geri", command=self.show_main_menu).pack(side=tk.RIGHT)
        
        info = ttk.Label(self.main_frame, 
                        text="Kullanıcının rolünü değiştirerek yetkilerini güncelleyebilirsiniz.\n"
                             "Admin: Tüm yetkiler\n"
                             "Akademisyen: Öğrenci yoklama görüntüleme, öğrenci ekleme/çıkarma\n"
                             "Personel: Kendi yoklaması ve ders programı görüntüleme\n"
                             "Öğrenci: Sadece kendi yoklaması",
                        font=('Helvetica', 11))
        info.pack(pady=20)
        
        # Kullanıcı listesi
        users = db.get_all_users()
        
        list_frame = ttk.Frame(self.main_frame)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        columns = ('ID', 'Ad Soyad', 'Mevcut Rol', 'Alt Rol')
        tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=12)
        
        role_tr = {'admin': 'Admin', 'akademisyen': 'Akademisyen', 
                  'personel': 'Personel', 'ogrenci': 'Öğrenci'}
        
        for col in columns:
            tree.heading(col, text=col)
            if col == 'ID':
                # Aynı isimli kişiler admin tarafından benzersiz ID ile ayırt
                # edilebilsin diye ID sütunu net ve ortalanmış (PROBLEM 1)
                tree.column(col, width=60, minwidth=50, anchor='center', stretch=False)
            else:
                tree.column(col, width=150)
        
        for user in users:
            tree.insert('', tk.END, values=(
                user['id'], user['name'],
                role_tr.get(user['role'], user['role']),
                user['sub_role'] or '-'
            ))
        
        tree.pack(fill=tk.BOTH, expand=True)
        
        # Rol değiştirme
        change_frame = ttk.Frame(self.main_frame)
        change_frame.pack(pady=20)
        
        ttk.Label(change_frame, text="Yeni Rol:").pack(side=tk.LEFT, padx=5)
        
        role_var = tk.StringVar()
        role_combo = ttk.Combobox(change_frame, textvariable=role_var, state='readonly', width=20)
        role_combo['values'] = ['Admin', 'Akademisyen', 'Personel', 'Öğrenci']
        role_combo.pack(side=tk.LEFT, padx=5)
        
        def change_role():
            selected = tree.selection()
            if not selected:
                messagebox.showwarning("Uyarı", "Lütfen bir kullanıcı seçin!")
                return
            
            if not role_var.get():
                messagebox.showwarning("Uyarı", "Lütfen bir rol seçin!")
                return
            
            user_id = parse_leading_id(tree.item(selected[0])['values'][0])
            role_map = {'Admin': 'admin', 'Akademisyen': 'akademisyen',
                       'Personel': 'personel', 'Öğrenci': 'ogrenci'}
            
            db.update_user(user_id, role=role_map[role_var.get()])
            messagebox.showinfo("Başarılı", "Yetki güncellendi!")
            self.show_permission_management()
        
        ttk.Button(change_frame, text="Yetkiyi Değiştir", command=change_role).pack(side=tk.LEFT, padx=10)
    
    def show_course_management(self):
        """Ders yönetimi ekranı"""
        self.clear_frame()
        
        header = ttk.Frame(self.main_frame)
        header.pack(fill=tk.X, pady=10)
        
        ttk.Label(header, text="📚 Ders Yönetimi", style='Header.TLabel').pack(side=tk.LEFT)
        ttk.Button(header, text="← Geri", command=self.show_main_menu).pack(side=tk.RIGHT)
        
        # Ders listesi
        list_frame = ttk.Frame(self.main_frame)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        columns = ('ID', 'Ders Adı', 'Akademisyen', 'Sınıf', 'Gün', 'Başlangıç', 'Bitiş')
        self.course_tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=12)
        
        for col in columns:
            self.course_tree.heading(col, text=col)
            self.course_tree.column(col, width=100 if col != 'ID' else 50)
        
        self.refresh_course_list()
        
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.course_tree.yview)
        self.course_tree.configure(yscrollcommand=scrollbar.set)
        
        self.course_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Butonlar
        btn_frame = ttk.Frame(self.main_frame)
        btn_frame.pack(pady=10)
        
        ttk.Button(btn_frame, text="➕ Yeni Ders", command=self.add_course_dialog).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="👥 Öğrenci Ata", command=self.assign_students_dialog).pack(side=tk.LEFT, padx=5)
    
    def refresh_course_list(self):
        """Ders listesini yenile"""
        for item in self.course_tree.get_children():
            self.course_tree.delete(item)
        
        courses = db.get_all_courses()
        
        for course in courses:
            self.course_tree.insert('', tk.END, values=(
                course['id'],
                course['name'],
                course['akademisyen_name'] or '-',
                course['location_name'] or '-',
                course['day_of_week'] or '-',
                course['start_time'] or '-',
                course['end_time'] or '-'
            ))
    
    def add_course_dialog(self):
        """Yeni ders ekleme dialogu"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Yeni Ders Ekle")
        dialog.geometry("450x450")
        dialog.transient(self.root)
        dialog.grab_set()
        
        ttk.Label(dialog, text="Ders Adı:").pack(pady=5)
        name_entry = ttk.Entry(dialog, width=40)
        name_entry.pack(pady=5)
        
        ttk.Label(dialog, text="Akademisyen:").pack(pady=5)
        akademisyenler = db.get_users_by_role('akademisyen')
        akademisyen_var = tk.StringVar()
        akademisyen_combo = ttk.Combobox(dialog, textvariable=akademisyen_var, state='readonly', width=37)
        akademisyen_combo['values'] = [format_user_option(a) for a in akademisyenler]
        akademisyen_combo.pack(pady=5)
        
        ttk.Label(dialog, text="Sınıf:").pack(pady=5)
        classrooms = db.get_classrooms()
        classroom_var = tk.StringVar()
        classroom_combo = ttk.Combobox(dialog, textvariable=classroom_var, state='readonly', width=37)
        classroom_combo['values'] = [format_user_option(c) for c in classrooms]
        classroom_combo.pack(pady=5)
        
        ttk.Label(dialog, text="Gün:").pack(pady=5)
        day_var = tk.StringVar()
        day_combo = ttk.Combobox(dialog, textvariable=day_var, state='readonly', width=37)
        day_combo['values'] = ['Pazartesi', 'Salı', 'Çarşamba', 'Perşembe', 'Cuma']
        day_combo.pack(pady=5)
        
        time_frame = ttk.Frame(dialog)
        time_frame.pack(pady=10)
        
        ttk.Label(time_frame, text="Başlangıç:").pack(side=tk.LEFT)
        start_entry = ttk.Entry(time_frame, width=10)
        start_entry.insert(0, "09:00")
        start_entry.pack(side=tk.LEFT, padx=5)
        
        ttk.Label(time_frame, text="Bitiş:").pack(side=tk.LEFT, padx=10)
        end_entry = ttk.Entry(time_frame, width=10)
        end_entry.insert(0, "12:00")
        end_entry.pack(side=tk.LEFT, padx=5)
        
        def save():
            name = name_entry.get().strip()
            if not name:
                messagebox.showwarning("Uyarı", "Ders adı zorunludur!")
                return
            
            akademisyen_id = parse_leading_id(akademisyen_var.get())
            location_id = parse_leading_id(classroom_var.get())
            
            db.add_course(name, akademisyen_id, location_id, 
                         day_var.get(), start_entry.get(), end_entry.get())
            
            messagebox.showinfo("Başarılı", "Ders eklendi!")
            self.refresh_course_list()
            dialog.destroy()
        
        ttk.Button(dialog, text="Kaydet", command=save).pack(pady=20)
    
    def assign_students_dialog(self):
        """Derse öğrenci atama dialogu"""
        selected = self.course_tree.selection()
        if not selected:
            messagebox.showwarning("Uyarı", "Lütfen bir ders seçin!")
            return
        
        course_id = parse_leading_id(self.course_tree.item(selected[0])['values'][0])
        course_name = self.course_tree.item(selected[0])['values'][1]
        
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Öğrenci Ata - {course_name}")
        dialog.geometry("500x500")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Mevcut öğrenciler
        ttk.Label(dialog, text="Dersin Öğrencileri:", font=('Helvetica', 11, 'bold')).pack(pady=5)
        
        enrolled_frame = ttk.Frame(dialog)
        enrolled_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        enrolled_list = tk.Listbox(enrolled_frame, height=8)
        enrolled_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        enrolled_students = db.get_course_students(course_id)
        for student in enrolled_students:
            enrolled_list.insert(tk.END, format_user_option(student))
        
        # Tüm öğrenciler
        ttk.Label(dialog, text="Tüm Öğrenciler:", font=('Helvetica', 11, 'bold')).pack(pady=5)
        
        all_frame = ttk.Frame(dialog)
        all_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        all_list = tk.Listbox(all_frame, height=8, selectmode=tk.MULTIPLE)
        all_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        all_students = db.get_users_by_role('ogrenci')
        enrolled_ids = [s['id'] for s in enrolled_students]
        
        for student in all_students:
            if student['id'] not in enrolled_ids:
                all_list.insert(tk.END, format_user_option(student))
        
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(pady=10)
        
        def add_students():
            selections = all_list.curselection()
            for idx in selections:
                student_text = all_list.get(idx)
                student_id = parse_leading_id(student_text)
                if student_id is not None:
                    db.assign_student_to_course(course_id, student_id)
            
            messagebox.showinfo("Başarılı", "Öğrenciler eklendi!")
            dialog.destroy()
            self.assign_students_dialog()
        
        def remove_student():
            selection = enrolled_list.curselection()
            if not selection:
                return
            
            student_text = enrolled_list.get(selection[0])
            student_id = parse_leading_id(student_text)
            if student_id is None:
                return
            db.remove_student_from_course(course_id, student_id)
            
            messagebox.showinfo("Başarılı", "Öğrenci çıkarıldı!")
            dialog.destroy()
            self.assign_students_dialog()
        
        ttk.Button(btn_frame, text="➕ Seçilenleri Ekle", command=add_students).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="➖ Seçileni Çıkar", command=remove_student).pack(side=tk.LEFT, padx=5)
    
    def show_schedule(self):
        """Ders programını göster"""
        self.clear_frame()
        
        header = ttk.Frame(self.main_frame)
        header.pack(fill=tk.X, pady=10)
        
        ttk.Label(header, text="📅 Ders Programı", style='Header.TLabel').pack(side=tk.LEFT)
        ttk.Button(header, text="← Geri", command=self.show_main_menu).pack(side=tk.RIGHT)
        
        # Program tablosu
        schedule = db.get_course_schedule()
        
        list_frame = ttk.Frame(self.main_frame)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        columns = ('Gün', 'Saat', 'Ders', 'Akademisyen', 'Sınıf')
        tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=20)
        
        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=150)
        
        for course in schedule:
            tree.insert('', tk.END, values=(
                course['day_of_week'] or '-',
                f"{course['start_time']} - {course['end_time']}" if course['start_time'] else '-',
                course['name'],
                course['akademisyen_name'] or '-',
                course['location_name'] or '-'
            ))
        
        tree.pack(fill=tk.BOTH, expand=True)
    
    # ==================== AKADEMİSYEN PANELİ ====================
    
    def show_akademisyen_panel(self, parent):
        """Akademisyen panelini göster"""
        buttons = [
            (_('panel.my_courses'),         self.show_my_courses,             THK_LACIVERT),
            (_('panel.student_attendance'), self.show_student_attendance_list, THK_LACIVERT),
            (_('panel.student_management'), self.show_student_management,     THK_LACIVERT),
            (_('panel.critical_absence'),   self.show_critical_absence,       THK_KIRMIZI),
            (_('panel.schedule'),           self.show_schedule,               THK_LACIVERT),
        ]
        for text, cmd, color in buttons:
            RoundedButton(
                parent, text=text, command=cmd,
                bg=color, fg=THK_BEYAZ,
                width=280, height=46, radius=14,
                font=('Helvetica', 12, 'bold'),
            ).pack(pady=8)
    
    # ==================== KRİTİK DEVAMSIZLIK UYARILARI ====================
    
    def show_critical_absence(self):
        """Devamsızlık sınırını aşan öğrencilerin listelendiği bildirim ekranı.
        Admin: tüm dersler | Akademisyen: yalnızca kendi dersleri."""
        self.clear_frame()
        
        # Arka planı griye döndür
        self.main_frame.configure(style='Main.TFrame')
        self.root.configure(bg=THK_GRI)
        
        header = ttk.Frame(self.main_frame)
        header.pack(fill=tk.X, pady=10)
        
        ttk.Label(header, text=_('absence.title'), style='Header.TLabel').pack(side=tk.LEFT)
        ttk.Button(header, text=_('common.back'),
                   command=self.show_main_menu).pack(side=tk.RIGHT)
        
        # Kapsam: admin tüm dersleri, akademisyen yalnızca kendi derslerini görür
        role = self.current_user['role'] if self.current_user else None
        akademisyen_id = None if role == 'admin' else self.current_user['id']
        
        limit_pct = int(db.ATTENDANCE_CRITICAL_THRESHOLD * 100)
        ttk.Label(self.main_frame, text=_('absence.info', limit=limit_pct),
                  font=('Helvetica', 11)).pack(pady=10)
        
        critical = db.get_critical_absentees(akademisyen_id)
        
        # Kritik öğrenci yoksa bilgilendir ve dur
        if not critical:
            ttk.Label(self.main_frame, text=_('absence.none_critical'),
                      font=('Helvetica', 13, 'bold'), foreground=THK_LACIVERT).pack(pady=40)
            return
        
        list_frame = ttk.Frame(self.main_frame)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        columns = ('student_id', 'student_name', 'course', 'rate', 'status')
        headings = {
            'student_id':   _('absence.col_student_id'),
            'student_name': _('absence.col_student_name'),
            'course':       _('absence.col_course'),
            'rate':         _('absence.col_rate'),
            'status':       _('absence.col_status'),
        }
        # selectmode='extended' → birden fazla öğrenci seçilebilir
        tree = ttk.Treeview(list_frame, columns=columns, show='headings',
                            height=15, selectmode='extended')
        for col in columns:
            tree.heading(col, text=headings[col])
            if col == 'student_id':
                tree.column(col, width=80, minwidth=70, anchor='center', stretch=False)
            elif col in ('rate', 'status'):
                tree.column(col, width=160, anchor='center')
            else:
                tree.column(col, width=200)
        
        # Kritik satırları kırmızı vurgula
        tree.tag_configure('critical', foreground=THK_KIRMIZI)
        
        # iid → öğrenci/ders verisi (seçim sonrası simülasyon için)
        row_data = {}
        for item in critical:
            rate_txt = f"%{item['absence_rate'] * 100:.1f}"
            iid = tree.insert('', tk.END, tags=('critical',), values=(
                item['student_id'],
                item['student_name'],
                item['course_name'],
                rate_txt,
                _('absence.status_critical'),
            ))
            row_data[iid] = item
        
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        ttk.Label(self.main_frame, text=_('absence.summary', count=len(critical)),
                  font=('Helvetica', 10)).pack(pady=4)
        
        # Uyarı e-postası gönder (simülasyon) butonu
        btn_frame = ttk.Frame(self.main_frame)
        btn_frame.pack(pady=12)
        RoundedButton(
            btn_frame, text=_('absence.send_email_btn'),
            command=lambda: self._send_warning_emails(tree, row_data),
            bg=THK_KIRMIZI, fg=THK_BEYAZ,
            width=420, height=46, radius=14,
            font=('Helvetica', 12, 'bold'),
        ).pack()
    
    def _send_warning_emails(self, tree, row_data):
        """Seçili öğrencilere uyarı e-postası gönderimini SİMÜLE eder.
        Arka planda (thread) 1 sn'lik SMTP gönderimi taklit edilir; ardından
        her öğrenci için denetim günlüğüne 'attendance_warning_email_sent'
        kaydı yazılır ve başarı popup'ı gösterilir."""
        selected = tree.selection()
        if not selected:
            messagebox.showwarning(_('common.warning'), _('absence.no_selection'))
            return
        
        targets = [row_data[iid] for iid in selected if iid in row_data]
        if not targets:
            messagebox.showwarning(_('common.warning'), _('absence.no_selection'))
            return
        
        # --- Yükleme (indeterminate progressbar) penceresi ---
        prog = tk.Toplevel(self.root)
        prog.title(_('absence.sending'))
        prog.geometry("380x120")
        prog.transient(self.root)
        prog.grab_set()
        prog.resizable(False, False)
        ttk.Label(prog, text=_('absence.sending'),
                  font=('Helvetica', 11)).pack(pady=16)
        pbar = ttk.Progressbar(prog, mode='indeterminate', length=320)
        pbar.pack(pady=6)
        pbar.start(12)
        
        def worker():
            # Gerçek SMTP yerine ~1 sn'lik gönderim simülasyonu
            time.sleep(1.0)
            # Her öğrenci için denetim günlüğüne kaydet (audit_biometric her
            # çağrıda kendi bağlantısını açtığı için thread'den çağrı güvenli)
            for t in targets:
                db.audit_biometric(
                    t['student_id'], 'attendance_warning_email_sent', True,
                    f"course={t['course_name']} absence_rate={t['absence_rate']*100:.1f}%"
                )
            # UI güncellemeleri yalnızca ana thread'de yapılmalı
            self.root.after(0, finish)
        
        def finish():
            pbar.stop()
            try:
                prog.grab_release()
                prog.destroy()
            except tk.TclError:
                pass
            # Her öğrenci için başarı mesajı (spec: "[Öğrenci Adı] kişisine ...")
            msg = "\n".join(
                _('absence.email_success_one', name=t['student_name']) for t in targets
            )
            messagebox.showinfo(_('absence.email_success_title'), msg)
        
        threading.Thread(target=worker, daemon=True).start()
    
    def show_my_courses(self):
        """Akademisyenin derslerini göster"""
        self.clear_frame()
        
        header = ttk.Frame(self.main_frame)
        header.pack(fill=tk.X, pady=10)
        
        ttk.Label(header, text="📚 Derslerim", style='Header.TLabel').pack(side=tk.LEFT)
        ttk.Button(header, text="← Geri", command=self.show_main_menu).pack(side=tk.RIGHT)
        
        courses = db.get_courses_by_akademisyen(self.current_user['id'])
        
        list_frame = ttk.Frame(self.main_frame)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        columns = ('ID', 'Ders Adı', 'Sınıf', 'Gün', 'Saat')
        tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=15)
        
        for col in columns:
            tree.heading(col, text=col)
        
        for course in courses:
            tree.insert('', tk.END, values=(
                course['id'],
                course['name'],
                course['location_name'] or '-',
                course['day_of_week'] or '-',
                f"{course['start_time']} - {course['end_time']}" if course['start_time'] else '-'
            ))
        
        tree.pack(fill=tk.BOTH, expand=True)
    
    def show_student_attendance_list(self):
        """Öğrenci yoklamalarını göster"""
        self.clear_frame()
        
        header = ttk.Frame(self.main_frame)
        header.pack(fill=tk.X, pady=10)
        
        ttk.Label(header, text="📊 Öğrenci Yoklamaları", style='Header.TLabel').pack(side=tk.LEFT)
        ttk.Button(header, text="← Geri", command=self.show_main_menu).pack(side=tk.RIGHT)
        
        # Akademisyenin derslerindeki öğrencilerin yoklamalarını göster
        courses = db.get_courses_by_akademisyen(self.current_user['id'])
        
        list_frame = ttk.Frame(self.main_frame)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        columns = ('Tarih', 'Öğrenci', 'Ders', 'Sınıf', 'Giriş', 'Çıkış')
        tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=20)
        
        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=120)
        
        for course in courses:
            students = db.get_course_students(course['id'])
            for student in students:
                records = db.get_user_attendance(student['id'])
                for record in records:
                    if record['course_id'] == course['id']:
                        check_in = record['check_in_time'][:16] if record['check_in_time'] else '-'
                        check_out = record['check_out_time'][:16] if record['check_out_time'] else '-'
                        
                        tree.insert('', tk.END, values=(
                            record['date'],
                            student['name'],
                            course['name'],
                            record['location_name'] or '-',
                            check_in,
                            check_out
                        ))
        
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    
    def show_student_management(self):
        """Öğrenci yönetimi (Akademisyen için)"""
        self.clear_frame()
        
        header = ttk.Frame(self.main_frame)
        header.pack(fill=tk.X, pady=10)
        
        ttk.Label(header, text="👥 Öğrenci Yönetimi", style='Header.TLabel').pack(side=tk.LEFT)
        ttk.Button(header, text="← Geri", command=self.show_main_menu).pack(side=tk.RIGHT)
        
        # Öğrenci listesi
        students = db.get_users_by_role('ogrenci')
        
        list_frame = ttk.Frame(self.main_frame)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        columns = ('ID', 'Ad Soyad', 'Yüz Kaydı')
        self.student_tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=15)
        
        for col in columns:
            self.student_tree.heading(col, text=col)
        
        for student in students:
            has_face = "✅" if db.get_user_face_encoding(student['id']) is not None else "❌"
            self.student_tree.insert('', tk.END, values=(
                student['id'], student['name'], has_face
            ))
        
        self.student_tree.pack(fill=tk.BOTH, expand=True)
        
        btn_frame = ttk.Frame(self.main_frame)
        btn_frame.pack(pady=10)
        
        ttk.Button(btn_frame, text="➕ Yeni Öğrenci", command=self.add_student_dialog).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="🗑️ Öğrenci Sil", command=self.delete_student).pack(side=tk.LEFT, padx=5)
    
    def add_student_dialog(self):
        """Yeni öğrenci ekleme dialogu"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Yeni Öğrenci Ekle")
        dialog.geometry("400x200")
        dialog.transient(self.root)
        dialog.grab_set()
        
        ttk.Label(dialog, text="Ad Soyad:").pack(pady=10)
        name_entry = ttk.Entry(dialog, width=40)
        name_entry.pack(pady=5)
        
        def save():
            name = name_entry.get().strip()
            if not name:
                messagebox.showwarning("Uyarı", "Ad soyad zorunludur!")
                return
            
            db.add_user(name, 'ogrenci')
            messagebox.showinfo("Başarılı", "Öğrenci eklendi!")
            dialog.destroy()
            self.show_student_management()
        
        ttk.Button(dialog, text="Kaydet", command=save).pack(pady=20)
    
    def delete_student(self):
        """Öğrenci sil"""
        selected = self.student_tree.selection()
        if not selected:
            messagebox.showwarning("Uyarı", "Lütfen bir öğrenci seçin!")
            return
        
        if messagebox.askyesno("Onay", "Bu öğrenciyi silmek istediğinizden emin misiniz?"):
            student_id = self.student_tree.item(selected[0])['values'][0]
            db.delete_user(student_id)
            self.show_student_management()
            messagebox.showinfo("Başarılı", "Öğrenci silindi!")
    
    # ==================== PERSONEL PANELİ ====================
    
    def show_personel_panel(self, parent):
        """Personel panelini göster"""
        buttons = [
            (_('panel.my_attendance'), self.show_my_attendance),
            (_('panel.schedule'),      self.show_schedule),
        ]
        for text, cmd in buttons:
            RoundedButton(
                parent, text=text, command=cmd,
                bg=THK_LACIVERT, fg=THK_BEYAZ,
                width=280, height=46, radius=14,
                font=('Helvetica', 12, 'bold'),
            ).pack(pady=8)
    
    def show_my_attendance(self):
        """Kendi yoklamalarımı göster"""
        self.clear_frame()
        
        header = ttk.Frame(self.main_frame)
        header.pack(fill=tk.X, pady=10)
        
        ttk.Label(header, text="📊 Yoklamalarım", style='Header.TLabel').pack(side=tk.LEFT)
        ttk.Button(header, text="← Geri", command=self.show_main_menu).pack(side=tk.RIGHT)
        
        records = db.get_user_attendance(self.current_user['id'])
        
        list_frame = ttk.Frame(self.main_frame)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        columns = ('Tarih', 'Mekan', 'Ders', 'Giriş', 'Çıkış')
        tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=20)
        
        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=130)
        
        for record in records:
            check_in = record['check_in_time'][:16] if record['check_in_time'] else '-'
            check_out = record['check_out_time'][:16] if record['check_out_time'] else '-'
            
            tree.insert('', tk.END, values=(
                record['date'],
                record['location_name'] or '-',
                record['course_name'] or '-',
                check_in,
                check_out
            ))
        
        tree.pack(fill=tk.BOTH, expand=True)
    
    # ==================== ÖĞRENCİ PANELİ ====================
    
    def show_ogrenci_panel(self, parent):
        """Öğrenci panelini göster"""
        RoundedButton(
            parent, text=_('panel.my_attendance'), command=self.show_my_attendance,
            bg=THK_LACIVERT, fg=THK_BEYAZ,
            width=280, height=46, radius=14,
            font=('Helvetica', 12, 'bold'),
        ).pack(pady=8)

        ttk.Label(parent, text=_('panel.locations_hint'),
                 font=('Helvetica', 11)).pack(pady=20)
    
    def show_student_attendance(self, location):
        """Öğrenci için yoklama ekranı"""
        self.clear_frame()
        
        header = ttk.Frame(self.main_frame)
        header.pack(fill=tk.X, pady=10)
        
        ttk.Label(header, text=f"📍 {location['name']} - Yoklama", style='Header.TLabel').pack(side=tk.LEFT)
        ttk.Button(header, text="← Geri", command=self.show_main_menu).pack(side=tk.RIGHT)
        
        # Bu sınıftaki dersler
        courses = db.get_courses_by_location(location['id'])
        
        info_frame = ttk.Frame(self.main_frame)
        info_frame.pack(pady=30)
        
        ttk.Label(info_frame, text=_('attendance.scan_hint'),
                 font=('Helvetica', 14)).pack(pady=10)
        
        # Giriş/Çıkış butonları
        btn_frame = ttk.Frame(self.main_frame)
        btn_frame.pack(pady=20)
        
        def do_check_in():
            # Yüz tanıma
            user_id, user_name, message = fm.recognize_face_from_camera(timeout=10)
            
            if user_id and user_id == self.current_user['id']:
                # Ders seçimi (varsa)
                course_id = None
                if courses:
                    course_id = courses[0]['id']  # İlk dersi seç
                
                result_id, result_msg = db.check_in(user_id, location['id'], course_id)
                
                if result_id:
                    messagebox.showinfo(
                        _('common.success'),
                        _('attendance.welcome_in',
                          name=f"{self.current_user['name']} (ID: {self.current_user['id']})"),
                    )
                else:
                    messagebox.showwarning(_('common.warning'), result_msg)
            elif user_id:
                messagebox.showerror(_('common.error'), _('attendance.face_mismatch'))
            else:
                messagebox.showerror(_('common.error'), message)
        
        def do_check_out():
            # Yüz tanıma
            user_id, user_name, message = fm.recognize_face_from_camera(timeout=10)
            
            if user_id and user_id == self.current_user['id']:
                success, result_msg = db.check_out(user_id, location['id'])
                
                if success:
                    messagebox.showinfo("Başarılı", "Başarıyla Çıkış yapıldı.")
                else:
                    messagebox.showwarning("Uyarı", result_msg)
            elif user_id:
                messagebox.showerror("Hata", "Yüz doğrulanamadı!")
            else:
                messagebox.showerror("Hata", message)
        
        RoundedButton(
            btn_frame, text=_('attendance.check_in'),
            command=do_check_in,
            bg=THK_KIRMIZI, fg=THK_BEYAZ,
            width=220, height=56, radius=16,
            font=('Helvetica', 14, 'bold'),
        ).pack(side=tk.LEFT, padx=20)

        RoundedButton(
            btn_frame, text=_('attendance.check_out'),
            command=do_check_out,
            bg=THK_LACIVERT, fg=THK_BEYAZ,
            width=220, height=56, radius=16,
            font=('Helvetica', 14, 'bold'),
        ).pack(side=tk.LEFT, padx=20)
        
        # Bu sınıftaki dersler
        if courses:
            ttk.Label(self.main_frame, text="\n" + _('class.courses_here'),
                     font=('Helvetica', 12, 'bold')).pack(pady=10)
            
            for course in courses:
                course_info = f"{course['name']} - {course['akademisyen_name'] or 'Atanmamış'}"
                ttk.Label(self.main_frame, text=course_info, font=('Helvetica', 11)).pack()

        # --- Sınıf Krokisi ---
        self._render_classroom_layout(location)
    
    def show_location_attendance(self, location):
        """Admin/Akademisyen için mekan yoklama ekranı"""
        self.clear_frame()
        
        header = ttk.Frame(self.main_frame)
        header.pack(fill=tk.X, pady=10)
        
        ttk.Label(header, text=f"📍 {location['name']} - Yoklama Kayıtları", 
                 style='Header.TLabel').pack(side=tk.LEFT)
        ttk.Button(header, text="← Geri", command=self.show_main_menu).pack(side=tk.RIGHT)
        
        # Tarih filtresi
        filter_frame = ttk.Frame(self.main_frame)
        filter_frame.pack(fill=tk.X, pady=10)
        
        ttk.Label(filter_frame, text="Tarih:").pack(side=tk.LEFT, padx=5)
        date_entry = ttk.Entry(filter_frame, width=12)
        date_entry.insert(0, datetime.now().strftime('%Y-%m-%d'))
        date_entry.pack(side=tk.LEFT, padx=5)
        
        def refresh():
            self.refresh_location_attendance(location['id'], date_entry.get())
        
        ttk.Button(filter_frame, text="🔍 Göster", command=refresh).pack(side=tk.LEFT, padx=10)
        
        # Bu sınıfta kroki gösterilecek mi? Öyleyse tablo yerden tasarruf etsin.
        has_layout = location['name'] in {"Z-17", "102 Amfi"}

        # Liste
        list_frame = ttk.Frame(self.main_frame)
        if has_layout:
            # Kroki de sığsın diye liste sabit boyutlu ve kompakt
            list_frame.pack(fill=tk.X, pady=10)
            tree_height = 6
        else:
            list_frame.pack(fill=tk.BOTH, expand=True, pady=10)
            tree_height = 15

        columns = ('ID', 'Kullanıcı', 'Rol', 'Ders', 'Giriş', 'Çıkış')
        self.loc_attendance_tree = ttk.Treeview(
            list_frame, columns=columns, show='headings', height=tree_height
        )

        for col in columns:
            heading = _('attendance.col_user_id') if col == 'ID' else col
            self.loc_attendance_tree.heading(col, text=heading)
            if col == 'ID':
                self.loc_attendance_tree.column(col, width=70, minwidth=60,
                                                anchor='center', stretch=False)
            else:
                self.loc_attendance_tree.column(col, width=130)

        if has_layout:
            self.loc_attendance_tree.pack(fill=tk.X)
        else:
            self.loc_attendance_tree.pack(fill=tk.BOTH, expand=True)
        
        refresh()
        
        # Bu sınıftaki dersler
        courses = db.get_courses_by_location(location['id'])
        if courses:
            ttk.Label(self.main_frame, text="\n📚 Bu Sınıftaki Dersler:", 
                     font=('Helvetica', 11, 'bold')).pack()
            
            for course in courses:
                course_info = f"{course['name']} - {course['akademisyen_name'] or 'Atanmamış'}"
                ttk.Label(self.main_frame, text=course_info).pack()

        # --- Sınıf Krokisi ---
        self._render_classroom_layout(location)
    
    def refresh_location_attendance(self, location_id, date):
        """Mekan yoklama listesini yenile"""
        for item in self.loc_attendance_tree.get_children():
            self.loc_attendance_tree.delete(item)
        
        records = db.get_location_attendance(location_id, date)
        role_tr = {'admin': 'Admin', 'akademisyen': 'Akademisyen', 
                  'personel': 'Personel', 'ogrenci': 'Öğrenci'}
        
        for record in records:
            check_in = record['check_in_time'][11:16] if record['check_in_time'] else '-'
            check_out = record['check_out_time'][11:16] if record['check_out_time'] else '-'
            
            self.loc_attendance_tree.insert('', tk.END, values=(
                record['user_id'],
                record['user_name'],
                role_tr.get(record['role'], record['role']),
                record['course_name'] or '-',
                check_in,
                check_out
            ))
    
    def show_location_schedule(self, location):
        """Personel için mekan ders programı"""
        self.clear_frame()
        
        header = ttk.Frame(self.main_frame)
        header.pack(fill=tk.X, pady=10)
        
        ttk.Label(header, text=f"📍 {location['name']} - Ders Programı", 
                 style='Header.TLabel').pack(side=tk.LEFT)
        ttk.Button(header, text="← Geri", command=self.show_main_menu).pack(side=tk.RIGHT)
        
        courses = db.get_courses_by_location(location['id'])
        
        if not courses:
            ttk.Label(self.main_frame, text="Bu sınıfta henüz ders tanımlanmamış.",
                     font=('Helvetica', 12)).pack(pady=50)
            return
        
        list_frame = ttk.Frame(self.main_frame)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=20)
        
        columns = ('Ders', 'Akademisyen', 'Gün', 'Saat')
        tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=15)
        
        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=150)
        
        for course in courses:
            tree.insert('', tk.END, values=(
                course['name'],
                course['akademisyen_name'] or '-',
                course['day_of_week'] or '-',
                f"{course['start_time']} - {course['end_time']}" if course['start_time'] else '-'
            ))
        
        tree.pack(fill=tk.BOTH, expand=True)

        # --- Sınıf Krokisi (salt-okunur) ---
        self._render_classroom_layout(location)

    # ==================== SINIF KROKİSİ ====================

    def _render_classroom_layout(self, location):
        """Mekan ekranlarının altına 'Sınıf Krokisi' bölümünü yerleştir.

        Her sınıfın kendi yerleşim konfigürasyonu `CLASSROOM_LAYOUTS`
        dict'inde tanımlı. Yeni bir sınıf eklemek için buraya bir girdi
        ekle:
            "Sınıf İsmi": {"rows": <sıra_sayısı>}
        """
        CLASSROOM_LAYOUTS = {
            "Z-17":     {"rows": 6},
            "102 Amfi": {"rows": 9},
        }
        layout_config = CLASSROOM_LAYOUTS.get(location['name'])
        if layout_config is None:
            return  # Bu sınıf için kroki tanımlı değil

        # Ayırıcı
        sep = tk.Frame(self.main_frame, bg=THK_KIRMIZI, height=2)
        sep.pack(fill=tk.X, pady=(20, 10), padx=20)

        # Başlık
        title_frame = tk.Frame(self.main_frame, bg=THK_GRI)
        title_frame.pack(fill=tk.X, pady=(0, 10))
        tk.Label(
            title_frame,
            text=_('classroom.title'),
            font=('Helvetica', 16, 'bold'),
            fg=THK_LACIVERT, bg=THK_GRI,
        ).pack()

        # Kullanım ipucu — role göre metin değişiyor
        role = self.current_user['role']
        if role == 'ogrenci':
            hint = _('classroom.hint_student')
        elif role in ('akademisyen', 'admin'):
            hint = _('classroom.hint_teacher')
        else:
            hint = _('classroom.hint_readonly')
        tk.Label(
            self.main_frame, text=hint,
            font=('Helvetica', 10, 'italic'),
            fg="#555", bg=THK_GRI, wraplength=900, justify='center',
        ).pack(pady=(0, 10))

        # Krokiyi ortala
        holder = tk.Frame(self.main_frame, bg=THK_GRI)
        holder.pack(pady=5)

        layout = ClassroomLayoutWidget(
            holder,
            location_id=location['id'],
            current_user=self.current_user,
            rows=layout_config['rows'],
        )
        layout.pack()
        # Referansı sakla (GC olmasın)
        self._classroom_widget = layout
    
    # ==================== ÇIKIŞ ====================
    
    def logout(self):
        """Çıkış yap"""
        if messagebox.askyesno(_('logout.confirm_title'), _('logout.confirm_msg')):
            messagebox.showinfo(_('logout.success_title'), _('logout.success_msg'))
            self.current_user = None
            self.current_location = None
            self.show_login_screen()
    
    def run(self):
        """Uygulamayı çalıştır"""
        self.root.mainloop()


if __name__ == "__main__":
    app = AttendanceSystem()
    app.run()
