#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Expense Tracker Desktop App

Technologies:
- Tkinter (UI)
- SQLite (storage)
- Pillow/PIL (image handling and previews)
- ReportLab + arabic_reshaper + python-bidi (Persian PDF export)

Single-file implementation with clear functions and a simple, user-friendly UI.

Features:
- Auto-create SQLite DB and image folder
- Full CRUD with Treeview listing
- Date picker (tkcalendar.DateEntry if available, otherwise Entry)
- Attach receipt image from file or paste from clipboard
- Image preview
- Filter by date range and/or mission
- Persian PDF export for a selected mission; embeds images

Run:
  python3 expense_tracker.py

Dependencies (install in a venv recommended):
  pip install pillow reportlab tkcalendar arabic-reshaper python-bidi
"""

from __future__ import annotations

import os
import sys
import sqlite3
from datetime import datetime, date
from typing import Optional, Tuple, List

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

try:
    from tkcalendar import DateEntry  # type: ignore
    HAS_TKCALENDAR = True
except Exception:
    DateEntry = None  # type: ignore
    HAS_TKCALENDAR = False

try:
    from PIL import Image, ImageTk, ImageGrab
    HAS_PIL = True
except Exception:
    HAS_PIL = False
    Image = None  # type: ignore
    ImageTk = None  # type: ignore
    ImageGrab = None  # type: ignore

try:
    # Persian shaping and bidi reordering
    import arabic_reshaper  # type: ignore
    from bidi.algorithm import get_display  # type: ignore
    HAS_PERSIAN = True
except Exception:
    HAS_PERSIAN = False

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.utils import ImageReader
    from reportlab.lib import colors
    HAS_REPORTLAB = True
except Exception:
    HAS_REPORTLAB = False


APP_TITLE = "Expense Tracker"
DB_FILENAME = "expenses.db"
IMAGES_DIR = "receipts"
FONTS_DIR = "fonts"

# Categories
CATEGORIES = ["Snapp", "Food", "Miscellaneous"]


def app_dir() -> str:
    return os.path.abspath(os.path.dirname(__file__))


def db_path() -> str:
    return os.path.join(app_dir(), DB_FILENAME)


def receipts_dir() -> str:
    return os.path.join(app_dir(), IMAGES_DIR)


def fonts_dir() -> str:
    return os.path.join(app_dir(), FONTS_DIR)


def ensure_environment() -> None:
    os.makedirs(receipts_dir(), exist_ok=True)
    os.makedirs(fonts_dir(), exist_ok=True)


def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    ensure_environment()
    conn = connect_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                category TEXT NOT NULL,
                amount REAL NOT NULL,
                description TEXT,
                mission TEXT,
                image_path TEXT
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def parse_date_str(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def format_date(d: date) -> str:
    return d.strftime("%Y-%m-%d")


class ExpenseTrackerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1080x720")
        self.root.minsize(980, 640)

        # Form state
        self.selected_expense_id: Optional[int] = None
        self.current_image_path: Optional[str] = None
        self.preview_image_tk: Optional[ImageTk.PhotoImage] = None if HAS_PIL else None

        # Build UI
        self._build_ui()
        # Load initial data
        self.load_expenses()

    # -------------------- UI Construction --------------------
    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=10)
        container.pack(fill=tk.BOTH, expand=True)

        # Top form
        form_frame = ttk.LabelFrame(container, text="Expense Details", padding=10)
        form_frame.pack(fill=tk.X, expand=False, pady=(0, 10))

        # Row 1: Date, Category, Amount
        row1 = ttk.Frame(form_frame)
        row1.pack(fill=tk.X, pady=4)

        ttk.Label(row1, text="Date (YYYY-MM-DD)").grid(row=0, column=0, sticky=tk.W, padx=(0, 6))
        if HAS_TKCALENDAR and DateEntry is not None:
            self.date_input = DateEntry(row1, date_pattern="yyyy-mm-dd")  # type: ignore
            self.date_input.set_date(date.today())
        else:
            self.date_input = ttk.Entry(row1)
            self.date_input.insert(0, format_date(date.today()))
        self.date_input.grid(row=1, column=0, sticky=tk.W+tk.E, padx=(0, 12))

        ttk.Label(row1, text="Category").grid(row=0, column=1, sticky=tk.W)
        self.category_var = tk.StringVar(value=CATEGORIES[0])
        self.category_combo = ttk.Combobox(row1, textvariable=self.category_var, values=CATEGORIES, state="readonly")
        self.category_combo.grid(row=1, column=1, sticky=tk.W+tk.E, padx=(0, 12))

        ttk.Label(row1, text="Amount").grid(row=0, column=2, sticky=tk.W)
        self.amount_var = tk.StringVar()
        self.amount_entry = ttk.Entry(row1, textvariable=self.amount_var)
        self.amount_entry.grid(row=1, column=2, sticky=tk.W+tk.E)
        row1.grid_columnconfigure(0, weight=1)
        row1.grid_columnconfigure(1, weight=1)
        row1.grid_columnconfigure(2, weight=1)

        # Row 2: Description, Mission
        row2 = ttk.Frame(form_frame)
        row2.pack(fill=tk.X, pady=4)

        ttk.Label(row2, text="Description").grid(row=0, column=0, sticky=tk.W)
        self.description_entry = ttk.Entry(row2)
        self.description_entry.grid(row=1, column=0, sticky=tk.W+tk.E, padx=(0, 12))

        ttk.Label(row2, text="Mission").grid(row=0, column=1, sticky=tk.W)
        self.mission_entry = ttk.Entry(row2)
        self.mission_entry.grid(row=1, column=1, sticky=tk.W+tk.E)
        row2.grid_columnconfigure(0, weight=2)
        row2.grid_columnconfigure(1, weight=1)

        # Row 3: Image controls and preview
        row3 = ttk.Frame(form_frame)
        row3.pack(fill=tk.X, pady=4)

        img_controls = ttk.Frame(row3)
        img_controls.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.image_path_var = tk.StringVar()
        ttk.Label(img_controls, text="Image").grid(row=0, column=0, sticky=tk.W)
        self.image_path_entry = ttk.Entry(img_controls, textvariable=self.image_path_var)
        self.image_path_entry.grid(row=1, column=0, sticky=tk.W+tk.E, padx=(0, 8))

        select_btn = ttk.Button(img_controls, text="Browse…", command=self.select_image_file)
        select_btn.grid(row=1, column=1, padx=(0, 8))
        paste_btn = ttk.Button(img_controls, text="Paste from Clipboard", command=self.paste_image_from_clipboard)
        paste_btn.grid(row=1, column=2)
        img_controls.grid_columnconfigure(0, weight=1)

        preview_frame = ttk.Frame(row3)
        preview_frame.pack(side=tk.RIGHT)
        ttk.Label(preview_frame, text="Preview").pack(anchor=tk.W)
        self.preview_label = ttk.Label(preview_frame)
        self.preview_label.pack(padx=4, pady=2)

        # Actions
        actions = ttk.Frame(form_frame)
        actions.pack(fill=tk.X, pady=(6, 0))
        self.add_btn = ttk.Button(actions, text="Add", command=self.add_expense)
        self.add_btn.pack(side=tk.LEFT)
        self.update_btn = ttk.Button(actions, text="Update", command=self.edit_expense)
        self.update_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.delete_btn = ttk.Button(actions, text="Delete", command=self.delete_expense)
        self.delete_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.clear_btn = ttk.Button(actions, text="Clear", command=self.clear_form)
        self.clear_btn.pack(side=tk.LEFT, padx=(8, 0))

        # Filter section
        filter_frame = ttk.LabelFrame(container, text="Filter", padding=10)
        filter_frame.pack(fill=tk.X, expand=False, pady=(0, 10))

        ttk.Label(filter_frame, text="From Date").grid(row=0, column=0, sticky=tk.W)
        if HAS_TKCALENDAR and DateEntry is not None:
            self.filter_from_input = DateEntry(filter_frame, date_pattern="yyyy-mm-dd")  # type: ignore
        else:
            self.filter_from_input = ttk.Entry(filter_frame)
        self.filter_from_input.grid(row=1, column=0, sticky=tk.W+tk.E, padx=(0, 12))

        ttk.Label(filter_frame, text="To Date").grid(row=0, column=1, sticky=tk.W)
        if HAS_TKCALENDAR and DateEntry is not None:
            self.filter_to_input = DateEntry(filter_frame, date_pattern="yyyy-mm-dd")  # type: ignore
        else:
            self.filter_to_input = ttk.Entry(filter_frame)
        self.filter_to_input.grid(row=1, column=1, sticky=tk.W+tk.E, padx=(0, 12))

        ttk.Label(filter_frame, text="Mission").grid(row=0, column=2, sticky=tk.W)
        self.filter_mission_entry = ttk.Entry(filter_frame)
        self.filter_mission_entry.grid(row=1, column=2, sticky=tk.W+tk.E, padx=(0, 12))

        filter_btn = ttk.Button(filter_frame, text="Filter", command=self.filter_expenses)
        filter_btn.grid(row=1, column=3, padx=(0, 8))
        show_all_btn = ttk.Button(filter_frame, text="Show All", command=self.load_expenses)
        show_all_btn.grid(row=1, column=4)

        export_btn = ttk.Button(filter_frame, text="Export PDF (Mission)", command=self.export_pdf)
        export_btn.grid(row=1, column=5, padx=(16, 0))

        filter_frame.grid_columnconfigure(0, weight=1)
        filter_frame.grid_columnconfigure(1, weight=1)
        filter_frame.grid_columnconfigure(2, weight=1)

        # Treeview
        list_frame = ttk.Frame(container)
        list_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("id", "date", "category", "amount", "description", "mission", "image_path")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=12)
        self.tree.heading("id", text="ID")
        self.tree.heading("date", text="Date")
        self.tree.heading("category", text="Category")
        self.tree.heading("amount", text="Amount")
        self.tree.heading("description", text="Description")
        self.tree.heading("mission", text="Mission")
        self.tree.heading("image_path", text="Image Path")

        self.tree.column("id", width=60, anchor=tk.CENTER)
        self.tree.column("date", width=110, anchor=tk.CENTER)
        self.tree.column("category", width=120)
        self.tree.column("amount", width=100, anchor=tk.E)
        self.tree.column("description", width=260)
        self.tree.column("mission", width=160)
        self.tree.column("image_path", width=260)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree.bind("<Double-1>", self.on_tree_double_click)

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    # -------------------- DB Helpers --------------------
    def _validate_form(self) -> Tuple[bool, Optional[str]]:
        # Date
        if HAS_TKCALENDAR and isinstance(self.date_input, DateEntry):  # type: ignore
            d = self.date_input.get_date()  # type: ignore
            date_str = format_date(d)
        else:
            date_str = self.date_input.get().strip()
        try:
            parse_date_str(date_str)
        except Exception:
            return False, "Invalid date. Use YYYY-MM-DD."

        # Category
        category = self.category_var.get().strip()
        if not category:
            return False, "Category is required."

        # Amount
        amount_str = self.amount_var.get().strip().replace(",", "")
        try:
            amount_val = float(amount_str)
        except Exception:
            return False, "Amount must be a number."
        if amount_val < 0:
            return False, "Amount cannot be negative."

        # Image path is optional
        return True, None

    def _get_form_values(self) -> Tuple[str, str, float, str, str, Optional[str]]:
        # Date string
        if HAS_TKCALENDAR and isinstance(self.date_input, DateEntry):  # type: ignore
            d = self.date_input.get_date()  # type: ignore
            date_str = format_date(d)
        else:
            date_str = self.date_input.get().strip()

        category = self.category_var.get().strip()
        amount_val = float(self.amount_var.get().strip().replace(",", ""))
        description = self.description_entry.get().strip()
        mission = self.mission_entry.get().strip()
        image_path = self.current_image_path or self.image_path_var.get().strip() or None
        if image_path == "":
            image_path = None
        return date_str, category, amount_val, description, mission, image_path

    def add_expense(self) -> None:
        ok, err = self._validate_form()
        if not ok:
            messagebox.showerror("Validation Error", err or "Invalid input")
            return
        date_str, category, amount_val, description, mission, image_path = self._get_form_values()

        conn = connect_db()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO expenses(date, category, amount, description, mission, image_path) VALUES (?, ?, ?, ?, ?, ?)",
                (date_str, category, amount_val, description, mission, image_path),
            )
            conn.commit()
        finally:
            conn.close()
        self.clear_form()
        self.load_expenses()

    def edit_expense(self) -> None:
        if self.selected_expense_id is None:
            messagebox.showinfo("No selection", "Double-click an item to load for editing.")
            return
        ok, err = self._validate_form()
        if not ok:
            messagebox.showerror("Validation Error", err or "Invalid input")
            return
        date_str, category, amount_val, description, mission, image_path = self._get_form_values()

        conn = connect_db()
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE expenses SET date=?, category=?, amount=?, description=?, mission=?, image_path=? WHERE id=?",
                (date_str, category, amount_val, description, mission, image_path, self.selected_expense_id),
            )
            conn.commit()
        finally:
            conn.close()
        self.clear_form()
        self.load_expenses()

    def delete_expense(self) -> None:
        if self.selected_expense_id is None:
            messagebox.showinfo("No selection", "Select a row to delete.")
            return
        if not messagebox.askyesno("Confirm Delete", "Are you sure you want to delete this expense?"):
            return
        conn = connect_db()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM expenses WHERE id=?", (self.selected_expense_id,))
            conn.commit()
        finally:
            conn.close()
        self.clear_form()
        self.load_expenses()

    def load_expenses(self) -> None:
        # Clear filters
        if HAS_TKCALENDAR and isinstance(self.filter_from_input, DateEntry):  # type: ignore
            try:
                self.filter_from_input.set_date(date.today())  # type: ignore
                self.filter_from_input.delete(0, tk.END)  # type: ignore
            except Exception:
                pass
        else:
            self.filter_from_input.delete(0, tk.END)
        if HAS_TKCALENDAR and isinstance(self.filter_to_input, DateEntry):  # type: ignore
            try:
                self.filter_to_input.set_date(date.today())  # type: ignore
                self.filter_to_input.delete(0, tk.END)  # type: ignore
            except Exception:
                pass
        else:
            self.filter_to_input.delete(0, tk.END)
        self.filter_mission_entry.delete(0, tk.END)

        conn = connect_db()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM expenses ORDER BY date DESC, id DESC")
            rows = cur.fetchall()
        finally:
            conn.close()
        self._populate_tree(rows)

    def filter_expenses(self) -> None:
        from_str = self._get_filter_date_value(self.filter_from_input)
        to_str = self._get_filter_date_value(self.filter_to_input)
        mission = self.filter_mission_entry.get().strip()

        query = "SELECT * FROM expenses WHERE 1=1"
        params: List[object] = []
        if from_str:
            query += " AND date >= ?"
            params.append(from_str)
        if to_str:
            query += " AND date <= ?"
            params.append(to_str)
        if mission:
            query += " AND mission LIKE ?"
            params.append(f"%{mission}%")
        query += " ORDER BY date DESC, id DESC"

        conn = connect_db()
        try:
            cur = conn.cursor()
            cur.execute(query, params)
            rows = cur.fetchall()
        finally:
            conn.close()
        self._populate_tree(rows)

    def _get_filter_date_value(self, widget: tk.Widget) -> Optional[str]:
        try:
            if HAS_TKCALENDAR and isinstance(widget, DateEntry):  # type: ignore
                # If user left empty, treat as None
                v = widget.get()  # type: ignore
                v = v.strip()
                if not v:
                    return None
                # tkcalendar returns formatted string too
                if len(v) == 10:
                    parse_date_str(v)
                    return v
                d = widget.get_date()  # type: ignore
                return format_date(d)
        except Exception:
            pass
        if isinstance(widget, ttk.Entry) or isinstance(widget, tk.Entry):
            v2 = widget.get().strip()
            if v2:
                parse_date_str(v2)
                return v2
        return None

    def _populate_tree(self, rows: List[sqlite3.Row]) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        for r in rows:
            self.tree.insert("", tk.END, values=(
                r["id"], r["date"], r["category"], f"{r['amount']:.2f}", r["description"], r["mission"], r["image_path"] or ""
            ))

    # -------------------- Image Handling --------------------
    def select_image_file(self) -> None:
        filename = filedialog.askopenfilename(
            title="Select Image",
            filetypes=[
                ("Image files", "*.png;*.jpg;*.jpeg;*.bmp;*.gif"),
                ("All files", "*.*"),
            ],
        )
        if not filename:
            return
        if not HAS_PIL:
            messagebox.showerror("Missing Dependency", "Pillow is required for image handling.")
            return
        try:
            saved_path = self._save_image_to_receipts(Image.open(filename))
            self.current_image_path = saved_path
            self.image_path_var.set(saved_path)
            self._update_preview(saved_path)
        except Exception as e:
            messagebox.showerror("Image Error", f"Failed to process image: {e}")

    def paste_image_from_clipboard(self) -> None:
        if not HAS_PIL or ImageGrab is None:
            messagebox.showerror("Missing Dependency", "Pillow is required for clipboard paste.")
            return
        try:
            data = ImageGrab.grabclipboard()
            if isinstance(data, Image.Image):
                saved_path = self._save_image_to_receipts(data)
                self.current_image_path = saved_path
                self.image_path_var.set(saved_path)
                self._update_preview(saved_path)
                return
            elif isinstance(data, list) and data and isinstance(data[0], str) and os.path.isfile(data[0]):
                # Clipboard has file path(s)
                img = Image.open(data[0])
                saved_path = self._save_image_to_receipts(img)
                self.current_image_path = saved_path
                self.image_path_var.set(saved_path)
                self._update_preview(saved_path)
                return
            else:
                messagebox.showinfo("Clipboard", "No image found in clipboard.")
        except Exception as e:
            messagebox.showerror("Clipboard Error", f"Failed to paste image: {e}")

    def _save_image_to_receipts(self, image: "Image.Image") -> str:
        # Ensure RGB for JPEG saving if needed
        try:
            base = datetime.now().strftime("%Y%m%d_%H%M%S")
            target = os.path.join(receipts_dir(), f"receipt_{base}.jpg")
            img = image
            if image.mode not in ("RGB", "L"):
                img = image.convert("RGB")
            img.save(target, format="JPEG", quality=85)
            return target
        finally:
            try:
                image.close()
            except Exception:
                pass

    def _update_preview(self, path: str) -> None:
        if not HAS_PIL:
            return
        try:
            with Image.open(path) as im:
                preview = im.copy()
            preview.thumbnail((160, 160))
            self.preview_image_tk = ImageTk.PhotoImage(preview)
            self.preview_label.configure(image=self.preview_image_tk)
        except Exception as e:
            messagebox.showerror("Preview Error", f"Failed to show preview: {e}")

    # -------------------- Selection & Form --------------------
    def on_tree_double_click(self, event: tk.Event) -> None:  # noqa: ARG002
        item_id = self.tree.focus()
        if not item_id:
            return
        values = self.tree.item(item_id, "values")
        if not values:
            return
        try:
            self.selected_expense_id = int(values[0])
        except Exception:
            self.selected_expense_id = None

        # Populate form
        date_str = values[1]
        if HAS_TKCALENDAR and isinstance(self.date_input, DateEntry):  # type: ignore
            try:
                self.date_input.set_date(parse_date_str(date_str))  # type: ignore
            except Exception:
                self.date_input.set_date(date.today())  # type: ignore
        else:
            self.date_input.delete(0, tk.END)
            self.date_input.insert(0, date_str)

        self.category_var.set(values[2])
        self.amount_var.set(values[3])

        self.description_entry.delete(0, tk.END)
        self.description_entry.insert(0, values[4])

        self.mission_entry.delete(0, tk.END)
        self.mission_entry.insert(0, values[5])

        path = values[6]
        self.image_path_var.set(path)
        self.current_image_path = path if path else None
        if path:
            self._update_preview(path)
        else:
            self.preview_label.configure(image="")
            self.preview_image_tk = None

    def clear_form(self) -> None:
        self.selected_expense_id = None

        if HAS_TKCALENDAR and isinstance(self.date_input, DateEntry):  # type: ignore
            try:
                self.date_input.set_date(date.today())  # type: ignore
            except Exception:
                pass
        else:
            self.date_input.delete(0, tk.END)
            self.date_input.insert(0, format_date(date.today()))

        self.category_var.set(CATEGORIES[0])
        self.amount_var.set("")
        self.description_entry.delete(0, tk.END)
        self.mission_entry.delete(0, tk.END)
        self.image_path_var.set("")
        self.current_image_path = None
        self.preview_label.configure(image="")
        self.preview_image_tk = None

    # -------------------- PDF Export --------------------
    def export_pdf(self) -> None:
        if not HAS_REPORTLAB:
            messagebox.showerror("Missing Dependency", "ReportLab is required for PDF export.")
            return

        mission = self.filter_mission_entry.get().strip() or self.mission_entry.get().strip()
        if not mission:
            # Let user choose mission from a dialog input
            mission = self._prompt_text("Mission required", "Enter mission to export:")
            if not mission:
                return

        # Filter by mission
        conn = connect_db()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM expenses WHERE mission = ? ORDER BY date ASC, id ASC",
                (mission,),
            )
            rows = cur.fetchall()
        finally:
            conn.close()

        if not rows:
            messagebox.showinfo("No Data", "No expenses found for the given mission.")
            return

        # Output filename
        safe_mission = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in mission)
        today_str = format_date(date.today())
        default_name = f"{safe_mission}_mission_{today_str}.pdf"
        save_path = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            initialfile=default_name,
            filetypes=[("PDF", "*.pdf")],
            title="Save PDF Report",
        )
        if not save_path:
            return

        # Prepare font for Persian
        font_name = self._register_persian_font()

        # Create PDF
        page_width, page_height = A4
        c = canvas.Canvas(save_path, pagesize=A4)

        # Header
        c.setFont(font_name, 16)
        title_text = f"گزارش هزینه ماموریت: {mission}"
        title_text = self._persian_text(title_text)
        c.drawString(40, page_height - 50, title_text)

        c.setFont(font_name, 11)
        sub_text = self._persian_text(f"تاریخ تهیه گزارش: {today_str}")
        c.drawString(40, page_height - 70, sub_text)

        y = page_height - 100
        line_height = 16
        image_max_width = page_width - 80

        # Table header
        headers = ["#", "تاریخ", "دسته", "مبلغ", "توضیحات", "ماموریت"]
        header_positions = [40, 70, 150, 250, 330, 520]
        c.setFillColor(colors.black)
        c.setFont(font_name, 12)
        for text, x in zip(headers, header_positions):
            c.drawString(x, y, self._persian_text(text))
        y -= line_height
        c.line(40, y + 4, page_width - 40, y + 4)
        y -= 6

        index = 1
        for r in rows:
            values = [
                str(index),
                r["date"],
                r["category"],
                f"{r['amount']:.2f}",
                r["description"] or "",
                r["mission"] or "",
            ]

            # Render row text
            c.setFont(font_name, 10)
            for value, x in zip(values, header_positions):
                c.drawString(x, y, self._persian_text(value))
            y -= line_height

            # Render image if exists
            img_path = r["image_path"]
            if img_path and os.path.isfile(img_path):
                try:
                    img_reader = ImageReader(img_path)
                    if HAS_PIL:
                        with Image.open(img_path) as im:
                            width, height = im.size
                    else:
                        # Fallback: assume rectangle
                        width, height = (1024, 768)
                    scale = min(image_max_width / float(width), 300.0 / float(height))
                    new_w = float(width) * scale
                    new_h = float(height) * scale
                    if y - new_h < 60:
                        c.showPage()
                        c.setFont(font_name, 16)
                        c.drawString(40, page_height - 50, title_text)
                        c.setFont(font_name, 11)
                        c.drawString(40, page_height - 70, sub_text)
                        y = page_height - 100
                        c.setFont(font_name, 10)
                    c.drawImage(img_reader, 40, y - new_h, width=new_w, height=new_h, preserveAspectRatio=True, mask='auto')
                    y -= new_h + 8
                except Exception:
                    # Skip image if unreadable
                    pass

            # Page break if needed
            if y < 60:
                c.showPage()
                c.setFont(font_name, 16)
                c.drawString(40, page_height - 50, title_text)
                c.setFont(font_name, 11)
                c.drawString(40, page_height - 70, sub_text)
                y = page_height - 100

            index += 1

        c.save()
        messagebox.showinfo("Export Complete", f"PDF saved to:\n{save_path}")

    def _persian_text(self, text: str) -> str:
        # Apply reshaping and bidi if available, otherwise return as-is
        if not HAS_PERSIAN:
            return text
        try:
            reshaped = arabic_reshaper.reshape(text)
            bidi_text = get_display(reshaped)
            return bidi_text
        except Exception:
            return text

    def _register_persian_font(self) -> str:
        # Try to register Vazirmatn if present or downloadable; otherwise fallback to DejaVuSans
        font_candidates = [
            os.path.join(fonts_dir(), "Vazirmatn-Regular.ttf"),
            os.path.join(fonts_dir(), "Vazir.ttf"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        ]

        for path in font_candidates:
            if os.path.isfile(path):
                try:
                    pdfmetrics.registerFont(TTFont("PersianFont", path))
                    return "PersianFont"
                except Exception:
                    continue

        # Last resort: try to download Vazirmatn
        try:
            import urllib.request  # lazy import
            url = "https://github.com/rastikerdar/vazirmatn/releases/download/v33.003/Vazirmatn-Fonts-TTF-3.003.zip"
            zip_path = os.path.join(fonts_dir(), "vazirmatn.zip")
            urllib.request.urlretrieve(url, zip_path)
            import zipfile
            with zipfile.ZipFile(zip_path, 'r') as zf:
                for name in zf.namelist():
                    if name.lower().endswith("vazirmatn-regular.ttf"):
                        zf.extract(name, fonts_dir())
                        extracted_path = os.path.join(fonts_dir(), name)
                        pdfmetrics.registerFont(TTFont("PersianFont", extracted_path))
                        return "PersianFont"
        except Exception:
            pass

        # Fallback: built-in Helvetica (won't render Persian properly without shaping)
        return "Helvetica"

    # -------------------- Utilities --------------------
    def _prompt_text(self, title: str, prompt: str) -> Optional[str]:
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.grab_set()

        ttk.Label(dialog, text=prompt).pack(padx=12, pady=(12, 6), anchor=tk.W)
        entry = ttk.Entry(dialog, width=40)
        entry.pack(padx=12, pady=(0, 12))
        entry.focus_set()

        result: List[str] = []

        def on_ok() -> None:
            result.clear()
            result.append(entry.get().strip())
            dialog.destroy()

        def on_cancel() -> None:
            dialog.destroy()

        btns = ttk.Frame(dialog)
        btns.pack(padx=12, pady=(0, 12))
        ttk.Button(btns, text="OK", command=on_ok).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btns, text="Cancel", command=on_cancel).pack(side=tk.LEFT)

        dialog.wait_window(dialog)
        return result[0] if result else None


def main() -> None:
    init_db()
    root = tk.Tk()
    # Use ttk themes if available
    try:
        style = ttk.Style(root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
    except Exception:
        pass
    app = ExpenseTrackerApp(root)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        messagebox.showerror(APP_TITLE, f"Unexpected error: {e}")

