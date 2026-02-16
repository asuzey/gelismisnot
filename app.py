# -*- coding: utf-8 -*-
import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import json
import re
from datetime import datetime
import traceback
from typing import List, Optional
import logging
import os
import sys
from pathlib import Path
import threading
import time
import webbrowser

APP_VERSION = "v1.1.0"
GITHUB_URL = "https://github.com/asuzey"


# ============= LOGGING SETUP =============
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app_errors.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ============= CUSTOM EXCEPTIONS =============
class NoteHelperException(Exception):
    """Base exception for the application."""
    pass

class DataException(NoteHelperException):
    """Exception for data-related errors."""
    pass

class FileOperationException(NoteHelperException):
    """Exception for file operation errors."""
    pass

class ValidationException(NoteHelperException):
    """Exception for validation errors."""
    pass

class UIException(NoteHelperException):
    """Exception for UI-related errors."""
    pass

# ============= CONFIG & APPEARANCE =============
def init_appearance():
    """Initialize app appearance with error handling."""
    try:
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        try:
            ctk.CTk._deactivate_windows_window_header_manipulation = True
            ctk.CTk._deactivate_macos_window_header_manipulation = True
        except Exception as e:
            logger.debug(f"Window header manipulation not available: {e}")
    except Exception as e:
        logger.error(f"Failed to initialize appearance: {e}")
        raise

init_appearance()

APP_NAME = "Note Helper"
DATA_FILE = "data.json"
MAX_RETRIES = 3
RETRY_DELAY = 0.5
FILE_OPERATION_TIMEOUT = 5

# ============= DATA MODEL =============
class Record:
    """Record with validation."""
    MAX_CODE_LENGTH = 100
    MAX_TEXT_LENGTH = 10000
    
    def __init__(self, code: str, text: str):
        self.code = self._validate_code(code)
        self.text = self._validate_text(text)
        self.favorite = False
        self.last_used: Optional[str] = None

    @staticmethod
    def _validate_code(code: str) -> str:
        """Validate and sanitize code."""
        if not isinstance(code, str):
            raise ValidationException(f"Code must be string, got {type(code)}")
        code = str(code).strip()
        if not code:
            raise ValidationException("Code cannot be empty")
        if len(code) > Record.MAX_CODE_LENGTH:
            raise ValidationException(f"Code exceeds max length of {Record.MAX_CODE_LENGTH}")
        return code

    @staticmethod
    def _validate_text(text: str) -> str:
        """Validate and sanitize text."""
        if not isinstance(text, str):
            raise ValidationException(f"Text must be string, got {type(text)}")
        text = str(text).strip()
        if not text:
            raise ValidationException("Text cannot be empty")
        if len(text) > Record.MAX_TEXT_LENGTH:
            raise ValidationException(f"Text exceeds max length of {Record.MAX_TEXT_LENGTH}")
        return text

    def to_dict(self):
        """Convert to dictionary with validation."""
        try:
            return {
                "code": self.code,
                "text": self.text,
                "favorite": bool(self.favorite),
                "last_used": self.last_used,
            }
        except Exception as e:
            logger.error(f"Error converting Record to dict: {e}")
            raise DataException(f"Failed to serialize record: {e}")

    @classmethod
    def from_dict(cls, d):
        """Create from dictionary with validation."""
        try:
            if not isinstance(d, dict):
                raise ValidationException(f"Expected dict, got {type(d)}")
            
            code = d.get("code")
            text = d.get("text")
            
            if not code or not text:
                raise ValidationException("Missing required fields: code, text")
            
            rec = cls(code, text)
            rec.favorite = bool(d.get("favorite", False))
            
            last_used = d.get("last_used")
            if last_used and isinstance(last_used, str):
                rec.last_used = last_used
            
            return rec
        except ValidationException:
            raise
        except Exception as e:
            logger.error(f"Error deserializing record: {e}")
            raise DataException(f"Failed to deserialize record: {e}")


class DataManager:
    """Manages data loading/saving with comprehensive error handling and retry logic."""

    def __init__(self, filename: str):
        if not filename:
            raise ValidationException("Filename cannot be empty")
        self.filename = filename
        self.records: List[Record] = []
        self.lock = threading.Lock()
        self.backup_suffix = ".backup"
        self.load()

    def _read_file_with_retry(self) -> str:
        """Read file with retry logic."""
        for attempt in range(MAX_RETRIES):
            try:
                with open(self.filename, "r", encoding="utf-8") as f:
                    return f.read()
            except FileNotFoundError:
                logger.debug(f"Data file not found: {self.filename}")
                return "[]"
            except json.JSONDecodeError as e:
                logger.warning(f"Invalid JSON in data file (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY)
                    continue
                raise FileOperationException(f"Data file is corrupted: {e}")
            except IOError as e:
                logger.warning(f"IO error reading file (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY)
                    continue
                raise FileOperationException(f"Failed to read data file: {e}")
            except Exception as e:
                logger.error(f"Unexpected error reading file: {e}")
                raise FileOperationException(f"Unexpected error reading file: {e}")

    def _write_file_with_retry(self, content: str) -> None:
        """Write file with retry logic and backup."""
        for attempt in range(MAX_RETRIES):
            try:
                # Create backup if file exists
                if os.path.exists(self.filename):
                    backup_path = self.filename + self.backup_suffix
                    try:
                        with open(self.filename, "r", encoding="utf-8") as f:
                            backup_content = f.read()
                        with open(backup_path, "w", encoding="utf-8") as f:
                            f.write(backup_content)
                    except Exception as e:
                        logger.warning(f"Failed to create backup: {e}")

                # Write new file
                with open(self.filename, "w", encoding="utf-8") as f:
                    f.write(content)
                
                logger.debug(f"Data saved successfully to {self.filename}")
                return
            except PermissionError as e:
                logger.error(f"Permission denied writing to {self.filename}: {e}")
                raise FileOperationException(f"Permission denied: Cannot write to file")
            except IOError as e:
                logger.warning(f"IO error writing file (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY)
                    continue
                raise FileOperationException(f"Failed to write data file after {MAX_RETRIES} attempts: {e}")
            except Exception as e:
                logger.error(f"Unexpected error writing file: {e}")
                raise FileOperationException(f"Unexpected error writing file: {e}")

    def load(self) -> None:
        """Load records with comprehensive error handling."""
        try:
            with self.lock:
                content = self._read_file_with_retry()
                raw = json.loads(content)
                
                if not isinstance(raw, list):
                    raise ValidationException("Data file must contain a JSON array")
                
                self.records = []
                failed_count = 0
                
                for idx, r in enumerate(raw):
                    try:
                        record = Record.from_dict(r)
                        self.records.append(record)
                    except (ValidationException, DataException) as e:
                        logger.warning(f"Skipping invalid record #{idx}: {e}")
                        failed_count += 1
                    except Exception as e:
                        logger.warning(f"Error loading record #{idx}: {e}")
                        failed_count += 1
                
                if failed_count > 0:
                    logger.info(f"Loaded {len(self.records)} records ({failed_count} failed)")
                
        except (FileOperationException, ValidationException) as e:
            logger.error(f"Data loading error: {e}")
            self.records = []
        except Exception as e:
            logger.error(f"Unexpected error loading data: {e}")
            self.records = []

    def save(self) -> None:
        """Save records with comprehensive error handling."""
        try:
            with self.lock:
                data = []
                for r in self.records:
                    try:
                        data.append(r.to_dict())
                    except DataException as e:
                        logger.warning(f"Skipping record during save: {e}")
                        continue
                
                content = json.dumps(data, ensure_ascii=False, indent=2)
                self._write_file_with_retry(content)
                logger.info(f"Saved {len(data)} records")
                
        except FileOperationException as e:
            logger.error(f"Save failed: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error saving data: {e}")
            raise

    def auto_code(self) -> str:
        """Generate automatic code with safety checks."""
        try:
            i = 1
            existing = {r.code for r in self.records}
            max_iterations = 10000
            
            while i <= max_iterations:
                code = f"AUTO-{i:04d}"
                if code not in existing:
                    return code
                i += 1
            
            raise DataException(f"Could not generate unique code after {max_iterations} attempts")
        except Exception as e:
            logger.error(f"Error generating auto code: {e}")
            raise


# ============= MAIN APP =============
class NoteHelperApp:
    def __init__(self):
        try:
            self.data = DataManager(DATA_FILE)
            self.filtered_records: List[Record] = self.data.records.copy()
            self.current_filter_mode = "all"  # 'all', 'favorites', 'recent'

            # Setup root window
            self.root = ctk.CTk()
            self.root.title(APP_NAME)
            self.root.geometry("900x600")
            self.root.minsize(700, 500)

            # UI State
            self.search_var = tk.StringVar()
            self.search_timer = None
            self.selected_card_widget = None
            
            # ===== SEARCHER MODE (NEW) =====
            self.searcher_mode_active = False
            self.last_clipboard_text = ""

            # Build UI
            self._build_ui()

            # ===== KEYBOARD SHORTCUTS (NEW) =====
            self.root.bind("<Control-c>", self._on_search_hotkey)
            self.root.bind("<Delete>", self._on_delete_key)
            self.root.bind("<Control-e>", self._on_edit_key)

            # Initial display
            self._refresh_list()
            logger.info("Application initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize application: {e}")
            traceback.print_exc()
            messagebox.showerror("İnisiyasyon Hatası", f"Uygulama başlatılamadı: {e}")
            raise

    def _build_ui(self):
        """Build main UI - no dynamic resizing, static layout with error handling."""
        try:
            # ===== TOP BAR =====
            topbar = ctk.CTkFrame(self.root, height=60, fg_color="#2a2a2a")
            topbar.pack(side="top", fill="x", padx=6, pady=(6, 4))
            topbar.pack_propagate(False)

            # Left buttons
            left_frame = ctk.CTkFrame(topbar, fg_color="transparent")
            left_frame.pack(side="left", padx=4)

            self.btn_new = ctk.CTkButton(left_frame, text="➕ Yeni", width=100, height=40, command=self._safe_add_record)
            self.btn_new.pack(side="left", padx=2)

            self.btn_fav = ctk.CTkButton(left_frame, text="⭐ Favori", width=100, height=40, command=self._safe_show_favorites)
            self.btn_fav.pack(side="left", padx=2)

            self.btn_recent = ctk.CTkButton(left_frame, text="🕘 Son", width=100, height=40, command=self._safe_show_recent)
            self.btn_recent.pack(side="left", padx=2)

            # Center search
            center_frame = ctk.CTkFrame(topbar, fg_color="transparent")
            center_frame.pack(side="left", fill="x", expand=True, padx=6)

            search_entry = ctk.CTkEntry(
                center_frame,
                textvariable=self.search_var,
                placeholder_text="Ara (kod / açıklama)",
                height=40,
            )
            search_entry.pack(fill="x")

            # Right buttons
            right_frame = ctk.CTkFrame(topbar, fg_color="transparent")
            right_frame.pack(side="right", padx=4)

            self.btn_import = ctk.CTkButton(right_frame, text="📥 İçe", width=80, height=40, command=self._safe_import_txt)
            self.btn_import.pack(side="left", padx=2)

            self.btn_export = ctk.CTkButton(right_frame, text="📤 Dışa", width=80, height=40, command=self._safe_export_txt)
            self.btn_export.pack(side="left", padx=2)

            self.btn_theme = ctk.CTkButton(right_frame, text="🌗", width=40, height=40, command=self._safe_toggle_theme)
            self.btn_theme.pack(side="left", padx=2)

            # ===== SEARCHER BUTTON (NEW) =====
            self.btn_searcher = ctk.CTkButton(
                right_frame, text="[SEARCHER] OFF", width=140, height=40,
                command=self._toggle_searcher_mode,
                fg_color="#666666"
            )
            self.btn_searcher.pack(side="left", padx=2)

            # Help button
            self.btn_help = ctk.CTkButton(right_frame, text="❓", width=40, height=40, command=self._show_shortcuts_help)
            self.btn_help.pack(side="left", padx=2)

            # Bind search with debounce
            self.search_var.trace("w", self._on_search_input)

            # ===== LIST AREA =====
            self.container = ctk.CTkScrollableFrame(self.root, fg_color="transparent")
            self.container.pack(side="top", fill="both", expand=True, padx=6, pady=6)

            # ===== FOOTER FRAME =====
            footer_frame = ctk.CTkFrame(self.root, fg_color="#1f1f1f", height=28)
            footer_frame.pack(side="bottom", fill="x")

            # Sol - Kayıt sayısı
            self.record_label = ctk.CTkLabel(
                footer_frame,
                text=f"Toplam Kayıt: {len(self.data.records)}",
                text_color="#888888",
                fg_color="transparent",
                font=("Segoe UI", 11)
            )
            self.record_label.pack(side="left", padx=10)

            # Orta/Sağ - Developed by asu (tıklanabilir)
            dev_label = ctk.CTkLabel(
                footer_frame,
                text="developed by asu",
                text_color="#666666",
                fg_color="transparent",
                font=("Segoe UI", 11, "italic"),
                cursor="hand2"
            )
            dev_label.pack(side="right", padx=80)

            dev_label.bind("<Button-1>", lambda e: webbrowser.open(GITHUB_URL))

            # Sağ en köşe - Versiyon
            version_label = ctk.CTkLabel(
                footer_frame,
                text=APP_VERSION,
                text_color="#555555",
                fg_color="transparent",
                font=("Segoe UI", 10)
            )
            version_label.pack(side="right", padx=10)
            
        except Exception as e:
            logger.error(f"Error building UI: {e}")
            traceback.print_exc()
            raise UIException(f"Failed to build user interface: {e}")

    def _update_footer(self):
        """Update footer text safely."""
        try:
            if not self.record_label or not self.root.winfo_exists():
                return
            footer_text = f"Toplam Kayıt: {len(self.data.records)}"
            self.record_label.configure(text=footer_text)
        except tk.TclError:
            logger.debug("Widget destroyed, skipping footer update")
        except Exception as e:
            logger.error(f"Footer update error: {e}")

    def _safe_wrapper(self, func, *args, **kwargs):
        """Safely execute a function with error handling."""
        try:
            return func(*args, **kwargs)
        except ValidationException as e:
            logger.warning(f"Validation error: {e}")
            messagebox.showwarning("Doğrulama Hatası", str(e))
        except DataException as e:
            logger.error(f"Data error: {e}")
            messagebox.showerror("Veri Hatası", str(e))
        except FileOperationException as e:
            logger.error(f"File operation error: {e}")
            messagebox.showerror("Dosya Hatası", str(e))
        except Exception as e:
            logger.error(f"Unexpected error in {func.__name__}: {e}")
            traceback.print_exc()
            messagebox.showerror("Hata", f"Beklenmeyen hata: {str(e)[:100]}")

    def _on_search_input(self, *args):
        """Debounced search input handler."""
        try:
            if self.search_timer is not None:
                self.root.after_cancel(self.search_timer)
            self.search_timer = self.root.after(400, self._perform_search)
        except Exception as e:
            logger.error(f"Search input error: {e}")

    def _perform_search(self):
        """Actually perform the search."""
        try:
            q = self.search_var.get().strip().lower()
            if not isinstance(q, str):
                q = ""
            
            if q:
                self.current_filter_mode = "search"
                self.filtered_records = [
                    r for r in self.data.records
                    if q in r.code.lower() or q in r.text.lower()
                ]
            else:
                self.current_filter_mode = "all"
                self.filtered_records = self.data.records.copy()
            self._refresh_list()
        except Exception as e:
            logger.error(f"Search error: {e}")
            self.current_filter_mode = "all"
            self.filtered_records = self.data.records.copy()
            self._refresh_list()

    def _safe_show_favorites(self):
        """Show only favorite records (safe wrapper)."""
        self._safe_wrapper(self._show_favorites)

    def _show_favorites(self):
        """Show only favorite records."""
        self.search_var.set("")
        if self.search_timer is not None:
            self.root.after_cancel(self.search_timer)
            self.search_timer = None
        self.current_filter_mode = "favorites"
        self.filtered_records = [r for r in self.data.records if r.favorite]
        self._refresh_list()

    def _safe_show_recent(self):
        """Show recently used records (safe wrapper)."""
        self._safe_wrapper(self._show_recent)

    def _show_recent(self):
        """Show recently used records, newest first."""
        self.search_var.set("")
        if self.search_timer is not None:
            self.root.after_cancel(self.search_timer)
            self.search_timer = None
        self.current_filter_mode = "recent"

        # Split by last_used status
        with_used = [r for r in self.data.records if r.last_used]
        without_used = [r for r in self.data.records if not r.last_used]

        try:
            with_used.sort(
                key=lambda r: datetime.fromisoformat(r.last_used) if r.last_used else datetime.min,
                reverse=True
            )
        except Exception:
            logger.warning("Failed to sort by datetime, using string sort")
            with_used.sort(key=lambda r: r.last_used or "", reverse=True)

        self.filtered_records = with_used + without_used
        self._refresh_list()

    def _safe_add_record(self):
        """Add record (safe wrapper)."""
        self._safe_wrapper(self._add_record)

    def _add_record(self):
        """Open dialog to add new record."""
        try:
            top = ctk.CTkToplevel(self.root)
            top.title("Yeni Kayıt")
            top.geometry("450x400")
            top.resizable(False, False)

            # Code
            ctk.CTkLabel(top, text="Kod (isteğe bağlı):").pack(anchor="w", padx=15, pady=(15, 5))
            code_entry = ctk.CTkEntry(top)
            code_entry.pack(fill="x", padx=15, pady=(0, 10))

            # Text
            ctk.CTkLabel(top, text="İçerik:").pack(anchor="w", padx=15, pady=(5, 5))
            txt = ctk.CTkTextbox(top)
            txt.pack(fill="both", expand=True, padx=15, pady=(0, 15))

            def save():
                try:
                    text = txt.get("1.0", "end").strip()
                    code = code_entry.get().strip()
                    
                    if not text:
                        messagebox.showwarning("Uyarı", "İçerik boş olamaz!")
                        return
                    
                    if not code:
                        code = self.data.auto_code()
                    
                    # Validate before adding
                    record = Record(code, text)
                    self.data.records.append(record)
                    self.data.save()
                    self._perform_search()
                    self._update_footer()
                    top.destroy()
                    logger.info(f"Record added: {code}")
                    
                except ValidationException as e:
                    logger.warning(f"Validation error adding record: {e}")
                    messagebox.showwarning("Uyarı", str(e))
                except DataException as e:
                    logger.error(f"Data error adding record: {e}")
                    messagebox.showerror("Veri Hatası", str(e))
                except Exception as e:
                    logger.error(f"Error saving record: {e}")
                    messagebox.showerror("Hata", f"Kayıt kaydedilemedi: {e}")

            ctk.CTkButton(top, text="Kaydet", command=save).pack(pady=10)
            
        except Exception as e:
            logger.error(f"Error opening add record dialog: {e}")
            messagebox.showerror("Hata", f"Kayıt ekleme penceresi açılamadı: {e}")

    def _safe_edit_record(self, record: Record):
        """Edit record (safe wrapper)."""
        try:
            if not record:
                raise ValidationException("Record cannot be None")
            self._safe_wrapper(self._edit_record, record)
        except Exception as e:
            logger.error(f"Safe edit record error: {e}")

    def _edit_record(self, record: Record):
        """Open dialog to edit record."""
        try:
            if not record or not isinstance(record, Record):
                raise ValidationException("Invalid record")
            
            top = ctk.CTkToplevel(self.root)
            top.title("Düzenleme")
            top.geometry("450x400")
            top.resizable(False, False)
            top.grab_set()

            # Code
            ctk.CTkLabel(top, text="Kod:").pack(anchor="w", padx=15, pady=(15, 5))
            code_entry = ctk.CTkEntry(top)
            code_entry.insert(0, record.code)
            code_entry.pack(fill="x", padx=15, pady=(0, 10))

            # Text
            ctk.CTkLabel(top, text="İçerik:").pack(anchor="w", padx=15, pady=(5, 5))
            txt = ctk.CTkTextbox(top)
            txt.insert("1.0", record.text)
            txt.pack(fill="both", expand=True, padx=15, pady=(0, 15))

            def save():
                try:
                    new_text = txt.get("1.0", "end").strip()
                    new_code = code_entry.get().strip()
                    
                    if not new_text or not new_code:
                        messagebox.showwarning("Uyarı", "Kod ve içerik boş olamaz!")
                        return
                    
                    record.code = new_code
                    record.text = new_text
                    self.data.save()
                    self._perform_search()
                    top.destroy()
                    logger.info(f"Record updated: {new_code}")
                    
                except ValidationException as e:
                    messagebox.showwarning("Uyarı", str(e))
                except DataException as e:
                    messagebox.showerror("Veri Hatası", str(e))
                except Exception as e:
                    logger.error(f"Error updating record: {e}")
                    messagebox.showerror("Hata", f"Kayıt kaydedilemedi: {e}")

            def delete():
                try:
                    if messagebox.askyesno("Sil", "Bu kaydı silmek istediğinizden emin misiniz?"):
                        if record in self.data.records:
                            self.data.records.remove(record)
                            self.data.save()
                            self._perform_search()
                            self._update_footer()
                            top.destroy()
                            logger.info(f"Record deleted: {record.code}")
                        else:
                            messagebox.showwarning("Uyarı", "Kayıt bulunamadı")
                except Exception as e:
                    logger.error(f"Error deleting record: {e}")
                    messagebox.showerror("Hata", f"Kayıt silinirken hata: {e}")

            btn_frame = ctk.CTkFrame(top)
            btn_frame.pack(fill="x", padx=15, pady=10)
            ctk.CTkButton(btn_frame, text="Kaydet", command=save).pack(side="left", padx=5)
            ctk.CTkButton(btn_frame, text="Sil", command=delete, fg_color="red").pack(side="left", padx=5)
            
        except ValidationException as e:
            messagebox.showwarning("Uyarı", str(e))
        except Exception as e:
            logger.error(f"Error opening edit dialog: {e}")
            messagebox.showerror("Hata", f"Düzenleme penceresi açılamadı: {e}")

    def _safe_import_txt(self):
        """Import (safe wrapper)."""
        self._safe_wrapper(self._import_txt)

    def _import_txt(self):
        """Import records from text file."""
        try:
            path = filedialog.askopenfilename(
                filetypes=[("Text", "*.txt")],
                title="Kayıtları İçe Aktar"
            )
            if not path:
                return

            if not os.path.exists(path):
                raise FileOperationException(f"File not found: {path}")

            if not os.access(path, os.R_OK):
                raise FileOperationException(f"Cannot read file: {path}")

            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
                if not content:
                    messagebox.showwarning("Uyarı", "Dosya boş")
                    return
                
                blocks = re.split(r"\n\s*\n", content.strip())

            count = 0
            failed_count = 0
            
            for idx, b in enumerate(blocks):
                try:
                    lines = b.strip().splitlines()
                    if not lines:
                        continue

                    first = lines[0]
                    if re.match(r"^[A-ZÇĞİÖŞÜa-zçğıöşü].*🔎\d+", first):
                        code = first.strip()
                        text = "\n".join(lines[1:]).strip()
                    elif re.match(r"^\d{3,}", first):
                        code = first.strip()
                        text = "\n".join(lines[1:]).strip()
                    else:
                        code = self.data.auto_code()
                        text = b.strip()

                    if text:
                        try:
                            record = Record(code, text)
                            self.data.records.append(record)
                            count += 1
                        except (ValidationException, DataException) as e:
                            logger.warning(f"Skipping invalid record #{idx}: {e}")
                            failed_count += 1
                            
                except Exception as e:
                    logger.warning(f"Error processing block #{idx}: {e}")
                    failed_count += 1
                    continue

            self.data.save()
            self._perform_search()
            self._update_footer()
            
            msg = f"{count} kayıt içe aktarıldı!"
            if failed_count > 0:
                msg += f"\n({failed_count} kayıt atlandı)"
            
            messagebox.showinfo("Başarı", msg)
            logger.info(f"Import completed: {count} records, {failed_count} failed")
            
        except FileOperationException as e:
            logger.error(f"File operation error: {e}")
            messagebox.showerror("Dosya Hatası", str(e))
        except Exception as e:
            logger.error(f"Import error: {e}")
            traceback.print_exc()
            messagebox.showerror("Hata", f"İçe aktarma başarısız: {e}")

    def _safe_export_txt(self):
        """Export (safe wrapper)."""
        self._safe_wrapper(self._export_txt)

    def _export_txt(self):
        """Export records to text file."""
        try:
            if not self.data.records:
                messagebox.showwarning("Uyarı", "Dışa aktar için kayıt yok")
                return
            
            path = filedialog.asksaveasfilename(
                defaultextension=".txt",
                filetypes=[("Text", "*.txt")],
                title="Kayıtları Dışa Aktar"
            )
            if not path:
                return

            with open(path, "w", encoding="utf-8") as f:
                for idx, r in enumerate(self.data.records):
                    try:
                        f.write(f"{r.code}\n{r.text}\n\n")
                    except Exception as e:
                        logger.warning(f"Error writing record #{idx}: {e}")
                        continue

            messagebox.showinfo("Başarı", f"{len(self.data.records)} kayıt dışa aktarıldı!")
            logger.info(f"Export completed: {len(self.data.records)} records")
            
        except PermissionError:
            logger.error("Permission denied writing export file")
            messagebox.showerror("Hata", "Dosyaya yazama izni yok")
        except Exception as e:
            logger.error(f"Export error: {e}")
            messagebox.showerror("Hata", f"Dışa aktarma başarısız: {e}")

    def _safe_toggle_theme(self):
        """Toggle theme (safe wrapper)."""
        self._safe_wrapper(self._toggle_theme)

    def _toggle_theme(self):
        """Toggle between light and dark theme."""
        try:
            current = ctk.get_appearance_mode()
            new_mode = "Light" if current == "Dark" else "Dark"
            ctk.set_appearance_mode(new_mode)
            logger.info(f"Theme changed to: {new_mode}")
        except Exception as e:
            logger.error(f"Theme toggle error: {e}")
            raise

    # ===== SEARCHER MODE METHODS (NEW) =====
    def _toggle_searcher_mode(self):
        """Toggle searcher mode."""
        try:
            self.searcher_mode_active = not self.searcher_mode_active
            if self.searcher_mode_active:
                self.btn_searcher.configure(fg_color="#2ecc71", text="[SEARCHER] ON - Ctrl+C")
                self._show_toast("Searcher Mode: ON (Ctrl+C ile arama)", duration=1500)
                logger.info("Searcher Mode: ON")
            else:
                self.btn_searcher.configure(fg_color="#666666", text="[SEARCHER] OFF")
                self._show_toast("Searcher Mode: OFF", duration=1200)
                logger.info("Searcher Mode: OFF")
        except Exception as e:
            logger.error(f"[ERROR] Searcher mode toggle: {e}")

    def _on_search_hotkey(self, event=None):
        """Handle Ctrl+C hotkey for Searcher Mode."""
        if not self.searcher_mode_active:
            return
        try:
            clipboard_text = self.root.clipboard_get().strip()
            if clipboard_text and len(clipboard_text) > 1:
                # Don't search if it's the same text
                if clipboard_text != self.last_clipboard_text:
                    self.last_clipboard_text = clipboard_text
                    self.search_var.set(clipboard_text)
                    self._perform_search()
                    logger.debug(f"Searcher: Searched '{clipboard_text[:30]}...'")
        except tk.TclError:
            pass
        except Exception as e:
            logger.error(f"[ERROR] Search hotkey: {e}")

    def _on_delete_key(self, event=None):
        """Handle Delete key to delete selected record."""
        try:
            if hasattr(self, 'last_selected_record_code') and self.last_selected_record_code:
                record = next((r for r in self.data.records if r.code == self.last_selected_record_code), None)
                if record:
                    self._safe_edit_record(record)
                    return
            self._show_toast("Silmek için önce bir kayıt seçiniz", duration=1500)
        except Exception as e:
            logger.error(f"[ERROR] Delete key: {e}")

    def _on_edit_key(self, event=None):
        """Handle Ctrl+E to edit selected record."""
        try:
            if hasattr(self, 'last_selected_record_code') and self.last_selected_record_code:
                record = next((r for r in self.data.records if r.code == self.last_selected_record_code), None)
                if record:
                    self._safe_edit_record(record)
                    return
            self._show_toast("Düzenlemek için önce bir kayıt seçiniz", duration=1500)
        except Exception as e:
            logger.error(f"[ERROR] Edit key: {e}")

    def _show_shortcuts_help(self):
        """Show keyboard shortcuts help dialog."""
        try:
            help_dialog = ctk.CTkToplevel(self.root)
            help_dialog.title("⌨️ Keyboard Shortcuts")
            help_dialog.geometry("500x450")
            help_dialog.resizable(False, False)
            
            # Header
            header = ctk.CTkLabel(
                help_dialog, 
                text="⌨️ KEYBOARD SHORTCUTS",
                font=("Courier", 12, "bold"),
                text_color="#ffffff",
                fg_color="#333333",
                pady=10
            )
            header.pack(fill="x")
            
            # Content frame with scrollable text
            content_frame = ctk.CTkFrame(help_dialog, fg_color="transparent")
            content_frame.pack(fill="both", expand=True, padx=10, pady=10)
            
            shortcuts_text = """SEARCH & VIEW
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Ctrl + C        Toggle Searcher Mode
                  (auto-search clipboard)
  Type in search  Find by code/description
  ⭐ Favori       Show favorite records
  🕘 Son          Show recently used
  
RECORD MANAGEMENT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Delete          Delete selected record
  Ctrl + E        Edit selected record
  Click on card   Mark as recently used
  Copy button     Copy text to clipboard
  
IMPORT / EXPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  📥 İçe          Import from .txt file
  📤 Dışa         Export to .txt file
  
THEME
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  🌗              Toggle Dark/Light theme"""
            
            text_widget = ctk.CTkTextbox(
                content_frame,
                height=18, width=55,
                font=("Courier", 10),
                text_color="#ffffff"
            )
            text_widget.pack(fill="both", expand=True)
            text_widget.insert("1.0", shortcuts_text)
            text_widget.configure(state="disabled")
            
            # Close button
            close_btn = ctk.CTkButton(
                help_dialog,
                text="Kapat",
                command=help_dialog.destroy,
                fg_color="#0d47a1",
                hover_color="#1565c0"
            )
            close_btn.pack(pady=10)
            
        except Exception as e:
            logger.error(f"Error showing help dialog: {e}")
            messagebox.showerror("Hata", f"Yardım penceresi açılamadı: {e}")

    def _copy_text(self, text: str):
        """Copy text to clipboard."""
        try:
            if not text or not isinstance(text, str):
                raise ValidationException("Text must be a non-empty string")
            
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self._show_toast("Kopyalandı ✓")
            logger.debug("Text copied to clipboard")
        except tk.TclError as e:
            logger.error(f"Clipboard error: {e}")
            messagebox.showwarning("Uyarı", "Clipboard'a kopyalanamadı")
        except ValidationException as e:
            logger.warning(f"Copy text validation error: {e}")
        except Exception as e:
            logger.error(f"Copy error: {e}")

    def _show_toast(self, msg: str, duration: int = 2000):
        """Show temporary notification."""
        try:
            if not msg or not isinstance(msg, str):
                return
            
            if not self.root.winfo_exists():
                return
            
            t = ctk.CTkLabel(self.root, text=msg, bg_color="transparent", text_color="#4CAF50")
            t.place(relx=0.5, rely=0.92, anchor="center")
            self.root.after(duration, lambda: self._safe_destroy_widget(t))
        except tk.TclError:
            logger.debug("Widget creation failed (window might be destroyed)")
        except Exception as e:
            logger.debug(f"Toast error: {e}")

    def _safe_destroy_widget(self, widget):
        """Safely destroy a widget."""
        try:
            if widget and widget.winfo_exists():
                widget.destroy()
        except Exception:
            pass

    def _highlight_text(self, text: str, query: str) -> str:
        """Highlight search query in text."""
        try:
            if not query or not isinstance(query, str) or not isinstance(text, str):
                return text
            
            pattern = re.compile(re.escape(query), re.IGNORECASE)
            result = pattern.sub(lambda m: f"⭐{m.group(0)}⭐", text)
            return result[:500]  # Limit highlighted text to 500 chars
        except Exception as e:
            logger.debug(f"Highlight error: {e}")
            return text

    def _refresh_list(self):
        """Refresh the record list display."""
        try:
            # Clear old widgets
            try:
                for widget in self.container.winfo_children():
                    widget.destroy()
            except tk.TclError:
                logger.debug("Container widget destroyed")
                return

            # Get search query
            q = self.search_var.get().strip() if isinstance(self.search_var.get(), str) else ""

            # Empty state
            if not self.filtered_records:
                msg = "Burası şimdilik boş."
                if self.current_filter_mode == "recent" or self.current_filter_mode == "favorites":
                    msg += "\nHenüz " + ("son kullanılan" if self.current_filter_mode == "recent" else "favori") + " kayıt yok."
                else:
                    msg += "\nÜstten ➕ Yeni veya 📥 İçe Aktar kullanabilirsin."

                try:
                    empty_label = ctk.CTkLabel(
                        self.container,
                        text=msg,
                        justify="center",
                        text_color="#666666"
                    )
                    empty_label.pack(pady=40)
                except Exception as e:
                    logger.error(f"Error creating empty label: {e}")
                return

            # Display records
            displayed = 0
            for record in self.filtered_records:
                try:
                    self._create_card(record, q)
                    displayed += 1
                except Exception as e:
                    logger.warning(f"Error creating card for record: {e}")
                    continue

            logger.debug(f"Displayed {displayed} records")

        except Exception as e:
            logger.error(f"Refresh list error: {e}")
            traceback.print_exc()

    def _create_card(self, record: Record, query: str = ""):
        """Create and display a single record card."""
        try:
            if not record or not isinstance(record, Record):
                raise ValidationException("Invalid record")
            
            card = ctk.CTkFrame(self.container, corner_radius=12, border_width=2, border_color="#333333")
            card.pack(fill="x", pady=10, padx=6)

            # Select on click
            def on_select():
                try:
                    try:
                        if self.selected_card_widget and self.selected_card_widget.winfo_exists():
                            self.selected_card_widget.configure(border_width=2, border_color="#333333")
                    except tk.TclError:
                        pass
                    
                    if card.winfo_exists():
                        card.configure(border_width=3, border_color="#555555")
                        self.selected_card_widget = card
                        # Store record code for keyboard shortcuts
                        self.last_selected_record_code = record.code
                    
                    record.last_used = datetime.now().isoformat()
                    self.data.save()
                except tk.TclError:
                    logger.debug("Widget destroyed, skipping select callback")
                except Exception as e:
                    logger.error(f"Select card error: {e}")

            card.bind("<Button-1>", lambda e: on_select())
            card.bind("<Double-Button-1>", lambda e: self._safe_edit_record(record))

            # Code label
            try:
                code_text = self._highlight_text(record.code, query)
                code_lbl = ctk.CTkLabel(
                    card,
                    text=code_text,
                    font=("Arial", 14, "bold"),
                    text_color="#ffffff"
                )
                code_lbl.pack(anchor="w", padx=10, pady=(10, 2))
                code_lbl.bind("<Button-1>", lambda e: on_select())
                code_lbl.bind("<Double-Button-1>", lambda e: self._safe_edit_record(record))
            except Exception as e:
                logger.error(f"Error creating code label: {e}")

            # Text label
            try:
                text_display = record.text.replace('\n', ' | ')[:200] if record.text else ""
                text_display = self._highlight_text(text_display, query)
                txt_lbl = ctk.CTkLabel(
                    card,
                    text=text_display,
                    wraplength=680,
                    justify="left",
                    font=("Arial", 12),
                    text_color="#e0e0e0"
                )
                txt_lbl.pack(anchor="w", padx=10, pady=(2, 10))
                txt_lbl.bind("<Button-1>", lambda e: on_select())
                txt_lbl.bind("<Double-Button-1>", lambda e: self._safe_edit_record(record))
            except Exception as e:
                logger.error(f"Error creating text label: {e}")

            # Buttons frame
            try:
                btns = ctk.CTkFrame(card, fg_color="transparent")
                btns.pack(anchor="e", padx=10, pady=(0, 10))

                # Copy button
                try:
                    ctk.CTkButton(
                        btns,
                        text="📋",
                        width=40,
                        height=32,
                        command=lambda: self._copy_text(record.text),
                    ).pack(side="left", padx=4)
                except Exception as e:
                    logger.warning(f"Could not create copy button: {e}")

                # Favorite button
                def toggle_fav():
                    try:
                        record.favorite = not record.favorite
                        self.data.save()
                        self._refresh_list()
                    except Exception as e:
                        logger.error(f"Toggle favorite error: {e}")
                        messagebox.showerror("Hata", f"Favori ayarı değiştirilemedi: {e}")

                try:
                    ctk.CTkButton(
                        btns,
                        text="⭐" if record.favorite else "☆",
                        width=40,
                        height=32,
                        command=toggle_fav,
                    ).pack(side="left", padx=4)
                except Exception as e:
                    logger.warning(f"Could not create favorite button: {e}")
            except Exception as e:
                logger.error(f"Error creating button frame: {e}")

        except Exception as e:
            logger.error(f"Create card error: {e}")

    def run(self):
        """Start the application."""
        try:
            self.root.mainloop()
        except Exception as e:
            logger.error(f"Unhandled exception in mainloop: {e}")
            traceback.print_exc()


# ============= ENTRY POINT =============
if __name__ == "__main__":
    try:
        logger.info("Starting application...")
        app = NoteHelperApp()
        app.run()
    except Exception as e:
        logger.critical(f"Fatal error: {e}")
        traceback.print_exc()
        messagebox.showerror("Kritik Hata", f"Uygulamayı başlatamıyorum: {e}")
        sys.exit(1)
