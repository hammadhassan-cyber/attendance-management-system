import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import sqlite3
import csv
import os
import shutil
import smtplib
import threading
import random
import calendar
from datetime import datetime, date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

try:
    import matplotlib
    matplotlib.use("TkAgg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

# ─────────────────────────────────────────────
#  PALETTE & THEME
# ─────────────────────────────────────────────
C = {
    "bg":        "#0D1117",
    "surface":   "#161B22",
    "card":      "#1C2333",
    "border":    "#30363D",
    "accent":    "#58A6FF",
    "accent2":   "#3FB950",
    "accent3":   "#F78166",
    "accent4":   "#D29922",
    "text":      "#E6EDF3",
    "text_dim":  "#8B949E",
    "present":   "#3FB950",
    "absent":    "#F78166",
    "late":      "#D29922",
    "hover":     "#1F2937",
    "btn":       "#21262D",
    "btn_hover": "#30363D",
    "selection": "#1F3A5F",
    "white":     "#FFFFFF",
}

FONTS = {
    "title":   ("Segoe UI", 22, "bold"),
    "header":  ("Segoe UI", 13, "bold"),
    "label":   ("Segoe UI", 10),
    "label_b": ("Segoe UI", 10, "bold"),
    "small":   ("Segoe UI", 9),
    "mono":    ("Consolas", 10),
    "big":     ("Segoe UI", 28, "bold"),
    "medium":  ("Segoe UI", 14, "bold"),
}

DB_FILE  = "attendance.db"
CSV_FILE = "attendance.csv"
BACKUP_DIR = "backups"

# ─────────────────────────────────────────────
#  DATABASE LAYER
# ─────────────────────────────────────────────
class Database:
    def __init__(self):
        self.conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        cur = self.conn.cursor()
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS members (
                id   TEXT PRIMARY KEY,
                name TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS attendance (
                rowid     INTEGER PRIMARY KEY AUTOINCREMENT,
                member_id TEXT NOT NULL,
                name      TEXT NOT NULL,
                date      TEXT NOT NULL,
                status    TEXT NOT NULL CHECK(status IN ('Present','Absent','Late')),
                timestamp TEXT NOT NULL,
                UNIQUE(member_id, date)
            );
        """)
        self.conn.commit()

    # ── Members ──────────────────────────────
    def add_member(self, mid, name):
        try:
            self.conn.execute("INSERT OR IGNORE INTO members VALUES (?,?)", (mid.strip(), name.strip().title()))
            self.conn.commit()
        except Exception as e:
            raise e

    def get_members(self):
        return self.conn.execute("SELECT * FROM members ORDER BY name").fetchall()

    def member_exists(self, mid):
        r = self.conn.execute("SELECT 1 FROM members WHERE LOWER(id)=LOWER(?)", (mid,)).fetchone()
        return r is not None

    # ── Attendance ────────────────────────────
    def mark(self, mid, name, dt, status):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            self.conn.execute(
                "INSERT INTO attendance (member_id,name,date,status,timestamp) VALUES (?,?,?,?,?)",
                (mid.strip(), name.strip().title(), dt, status, ts)
            )
            self.conn.commit()
            return True, "Marked successfully"
        except sqlite3.IntegrityError:
            return False, f"Attendance for {mid} on {dt} already exists."

    def update(self, mid, dt, new_status):
        cur = self.conn.execute(
            "UPDATE attendance SET status=? WHERE LOWER(member_id)=LOWER(?) AND date=?",
            (new_status, mid, dt)
        )
        self.conn.commit()
        return cur.rowcount > 0

    def delete(self, mid, dt):
        cur = self.conn.execute(
            "DELETE FROM attendance WHERE LOWER(member_id)=LOWER(?) AND date=?",
            (mid, dt)
        )
        self.conn.commit()
        return cur.rowcount > 0

    def get_all(self, order="date DESC"):
        return self.conn.execute(f"SELECT * FROM attendance ORDER BY {order}").fetchall()

    def get_by_date(self, dt):
        return self.conn.execute(
            "SELECT * FROM attendance WHERE date=? ORDER BY name", (dt,)
        ).fetchall()

    def get_by_id(self, mid):
        return self.conn.execute(
            "SELECT * FROM attendance WHERE LOWER(member_id)=LOWER(?) ORDER BY date DESC", (mid,)
        ).fetchall()

    def search(self, query):
        q = f"%{query.lower()}%"
        return self.conn.execute(
            "SELECT * FROM attendance WHERE LOWER(member_id) LIKE ? OR LOWER(name) LIKE ? ORDER BY date DESC",
            (q, q)
        ).fetchall()

    def summary(self, mid):
        rows = self.get_by_id(mid)
        total  = len(rows)
        present = sum(1 for r in rows if r["status"] == "Present")
        absent  = sum(1 for r in rows if r["status"] == "Absent")
        late    = sum(1 for r in rows if r["status"] == "Late")
        pct     = round((present + late * 0.5) / total * 100, 1) if total else 0
        return {"total": total, "present": present, "absent": absent, "late": late, "pct": pct}

    def monthly_report(self, year, month):
        pattern = f"{year}-{month:02d}-%"
        return self.conn.execute(
            "SELECT member_id, name, status FROM attendance WHERE date LIKE ? ORDER BY name",
            (pattern,)
        ).fetchall()

    def close(self):
        self.conn.close()

# ─────────────────────────────────────────────
#  CSV LAYER
# ─────────────────────────────────────────────
class CSVHandler:
    HEADERS = ["ID", "Name", "Date", "Status", "Timestamp"]

    def __init__(self, path=CSV_FILE):
        self.path = path
        if not os.path.exists(path):
            self._write_header()

    def _write_header(self):
        with open(self.path, "w", newline="") as f:
            csv.writer(f).writerow(self.HEADERS)

    def append(self, mid, name, dt, status):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self.path, "a", newline="") as f:
            csv.writer(f).writerow([mid, name, dt, status, ts])

    def sync_from_db(self, db: Database):
        rows = db.get_all("date ASC")
        with open(self.path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(self.HEADERS)
            for r in rows:
                w.writerow([r["member_id"], r["name"], r["date"], r["status"], r["timestamp"]])

    def export_report(self, path, rows, headers):
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(headers)
            w.writerows(rows)

# ─────────────────────────────────────────────
#  BACKUP
# ─────────────────────────────────────────────
def auto_backup(db: Database, csv_handler: CSVHandler):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_handler.sync_from_db(db)
    for src, dst in [(DB_FILE, f"{BACKUP_DIR}/attendance_{stamp}.db"),
                     (CSV_FILE, f"{BACKUP_DIR}/attendance_{stamp}.csv")]:
        if os.path.exists(src):
            shutil.copy2(src, dst)
    # keep only latest 10 backups
    for ext in ("db", "csv"):
        files = sorted([f for f in os.listdir(BACKUP_DIR) if f.endswith(f".{ext}")])
        for old in files[:-10]:
            os.remove(os.path.join(BACKUP_DIR, old))

# ─────────────────────────────────────────────
#  EMAIL
# ─────────────────────────────────────────────
def send_email(to_addr, subject, body, attachment_path=None,
               smtp_host="smtp.gmail.com", smtp_port=587,
               from_addr="", password=""):
    msg = MIMEMultipart()
    msg["From"]    = from_addr
    msg["To"]      = to_addr
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))
    if attachment_path and os.path.exists(attachment_path):
        with open(attachment_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{os.path.basename(attachment_path)}"')
        msg.attach(part)
    with smtplib.SMTP(smtp_host, smtp_port) as s:
        s.starttls()
        s.login(from_addr, password)
        s.sendmail(from_addr, to_addr, msg.as_string())

# ─────────────────────────────────────────────
#  REUSABLE WIDGETS
# ─────────────────────────────────────────────
class StyledEntry(tk.Entry):
    def __init__(self, parent, placeholder="", **kw):
        kw.setdefault("bg", C["surface"])
        kw.setdefault("fg", C["text"])
        kw.setdefault("insertbackground", C["accent"])
        kw.setdefault("relief", "flat")
        kw.setdefault("bd", 0)
        kw.setdefault("font", FONTS["label"])
        kw.setdefault("highlightthickness", 1)
        kw.setdefault("highlightbackground", C["border"])
        kw.setdefault("highlightcolor", C["accent"])
        super().__init__(parent, **kw)
        self.placeholder = placeholder
        self._placeholder_on()
        self.bind("<FocusIn>",  self._clear_ph)
        self.bind("<FocusOut>", self._set_ph)

    def _placeholder_on(self):
        if not self.get():
            self.insert(0, self.placeholder)
            self.config(fg=C["text_dim"])

    def _clear_ph(self, _=None):
        if self.get() == self.placeholder:
            self.delete(0, "end")
            self.config(fg=C["text"])

    def _set_ph(self, _=None):
        if not self.get():
            self._placeholder_on()

    def value(self):
        v = self.get()
        return "" if v == self.placeholder else v.strip()


class GlowButton(tk.Button):
    def __init__(self, parent, text, command=None, color=None, **kw):
        self._color = color or C["accent"]
        kw.setdefault("bg", self._color)
        kw.setdefault("fg", C["bg"])
        kw.setdefault("activebackground", self._color)
        kw.setdefault("activeforeground", C["bg"])
        kw.setdefault("relief", "flat")
        kw.setdefault("bd", 0)
        kw.setdefault("cursor", "hand2")
        kw.setdefault("font", FONTS["label_b"])
        kw.setdefault("padx", 18)
        kw.setdefault("pady", 8)
        super().__init__(parent, text=text, command=command, **kw)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def _on_enter(self, _):
        self.config(bg=self._lighten(self._color))

    def _on_leave(self, _):
        self.config(bg=self._color)

    @staticmethod
    def _lighten(hex_color):
        hex_color = hex_color.lstrip("#")
        r, g, b = (int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        return "#{:02X}{:02X}{:02X}".format(min(r+30,255), min(g+30,255), min(b+30,255))


class Card(tk.Frame):
    def __init__(self, parent, **kw):
        kw.setdefault("bg", C["card"])
        kw.setdefault("relief", "flat")
        kw.setdefault("bd", 0)
        kw.setdefault("highlightthickness", 1)
        kw.setdefault("highlightbackground", C["border"])
        super().__init__(parent, **kw)


class SectionLabel(tk.Label):
    def __init__(self, parent, text, **kw):
        kw.setdefault("bg", C["bg"] if "bg" not in kw else kw["bg"])
        kw.setdefault("fg", C["text_dim"])
        kw.setdefault("font", FONTS["small"])
        super().__init__(parent, text=text.upper(), **kw)


class StyledTree(ttk.Treeview):
    def __init__(self, parent, columns, headings, **kw):
        kw.setdefault("show", "headings")
        kw.setdefault("selectmode", "browse")
        super().__init__(parent, columns=columns, **kw)
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Custom.Treeview",
            background=C["surface"], foreground=C["text"],
            fieldbackground=C["surface"], rowheight=30,
            font=FONTS["label"], borderwidth=0)
        style.configure("Custom.Treeview.Heading",
            background=C["card"], foreground=C["text_dim"],
            font=FONTS["label_b"], relief="flat", borderwidth=0)
        style.map("Custom.Treeview",
            background=[("selected", C["selection"])],
            foreground=[("selected", C["white"])])
        self.configure(style="Custom.Treeview")
        for col, heading in zip(columns, headings):
            self.heading(col, text=heading, anchor="w")
            self.column(col, anchor="w", width=120)
        self.tag_configure("present", foreground=C["present"])
        self.tag_configure("absent",  foreground=C["absent"])
        self.tag_configure("late",    foreground=C["late"])
        self.tag_configure("even",    background=C["surface"])
        self.tag_configure("odd",     background=C["card"])

    def load_rows(self, rows, key_index=3):
        self.delete(*self.get_children())
        for i, row in enumerate(rows):
            tag = ("even" if i%2==0 else "odd",)
            if len(row) > key_index:
                status = str(row[key_index]).lower()
                if status in ("present","absent","late"):
                    tag = (status,)
            self.insert("", "end", values=row, tags=tag)

# ─────────────────────────────────────────────
#  TOAST NOTIFICATION
# ─────────────────────────────────────────────
class Toast:
    def __init__(self, root, message, kind="info"):
        colors = {"info": C["accent"], "success": C["present"], "error": C["absent"], "warn": C["late"]}
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=colors.get(kind, C["accent"]))
        tk.Label(self.win, text=message, bg=colors.get(kind, C["accent"]),
                 fg=C["white"], font=FONTS["label_b"], padx=16, pady=10).pack()
        rw, rh = root.winfo_width(), root.winfo_height()
        rx, ry = root.winfo_rootx(), root.winfo_rooty()
        self.win.update_idletasks()
        w, h = self.win.winfo_width(), self.win.winfo_height()
        x = rx + (rw - w) // 2
        y = ry + rh - h - 40
        self.win.geometry(f"+{x}+{y}")
        self.win.after(2500, self.win.destroy)

# ─────────────────────────────────────────────
#  STAT CARD
# ─────────────────────────────────────────────
def make_stat_card(parent, label, value, color, bg=None):
    bg = bg or C["card"]
    f = Card(parent, bg=bg, padx=20, pady=16)
    tk.Label(f, text=label, bg=bg, fg=C["text_dim"], font=FONTS["small"]).pack(anchor="w")
    tk.Label(f, text=str(value), bg=bg, fg=color, font=FONTS["big"]).pack(anchor="w")
    return f

# ─────────────────────────────────────────────
#  MAIN APPLICATION
# ─────────────────────────────────────────────
class AttendanceApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.db  = Database()
        self.csv = CSVHandler()
        self.title("Attendance Management System")
        self.geometry("1280x780")
        self.minsize(1024, 680)
        self.configure(bg=C["bg"])
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._seed_demo_data()
        self._build_ui()
        self._schedule_backup()

    # ── Demo Data ─────────────────────────────
    def _seed_demo_data(self):
        members = [
            ("EMP001","Alice Johnson"),("EMP002","Bob Smith"),("EMP003","Carol White"),
            ("EMP004","David Brown"),("EMP005","Eva Martinez"),("EMP006","Frank Wilson"),
        ]
        for mid, name in members:
            self.db.add_member(mid, name)
        statuses = ["Present","Present","Present","Absent","Late"]
        today = date.today()
        for i in range(14):
            d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
            for mid, name in members:
                st = random.choice(statuses)
                ok, _ = self.db.mark(mid, name, d, st)
                if ok:
                    self.csv.append(mid, name, d, st)

    # ── Layout ────────────────────────────────
    def _build_ui(self):
        # ── Sidebar ──────────────────────────
        self.sidebar = tk.Frame(self, bg=C["surface"], width=220)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        # Logo area
        logo_f = tk.Frame(self.sidebar, bg=C["surface"], pady=24)
        logo_f.pack(fill="x")
        tk.Label(logo_f, text="◉", bg=C["surface"], fg=C["accent"], font=("Segoe UI",28)).pack()
        tk.Label(logo_f, text="AttendTrack", bg=C["surface"], fg=C["text"],
                 font=("Segoe UI", 13, "bold")).pack()
        tk.Label(logo_f, text="Management System", bg=C["surface"],
                 fg=C["text_dim"], font=FONTS["small"]).pack()

        ttk.Separator(self.sidebar, orient="horizontal").pack(fill="x", padx=16, pady=4)

        # Nav buttons
        nav_items = [
            ("🏠  Dashboard",   self._show_dashboard),
            ("✏️  Mark Attendance", self._show_mark),
            ("📋  View Records",   self._show_view),
            ("🔄  Update Records", self._show_update),
            ("📊  Reports",        self._show_reports),
            ("👥  Manage Members", self._show_members),
            ("📧  Email Report",   self._show_email),
            ("💾  Backup",         self._do_backup),
        ]
        self._nav_btns = []
        for label, cmd in nav_items:
            b = tk.Button(self.sidebar, text=label, command=cmd,
                          bg=C["surface"], fg=C["text"], font=FONTS["label"],
                          relief="flat", bd=0, anchor="w", padx=20, pady=10,
                          cursor="hand2", activebackground=C["hover"],
                          activeforeground=C["text"])
            b.pack(fill="x")
            b.bind("<Enter>", lambda e, w=b: w.config(bg=C["hover"]))
            b.bind("<Leave>", lambda e, w=b: w.config(bg=C["surface"]))
            self._nav_btns.append(b)

        # Clock at bottom of sidebar
        self._clock_lbl = tk.Label(self.sidebar, text="", bg=C["surface"],
                                   fg=C["text_dim"], font=FONTS["small"])
        self._clock_lbl.pack(side="bottom", pady=10)
        self._update_clock()

        # ── Content area ─────────────────────
        self.content = tk.Frame(self, bg=C["bg"])
        self.content.pack(side="left", fill="both", expand=True)

        self._show_dashboard()

    def _update_clock(self):
        self._clock_lbl.config(text=datetime.now().strftime("⏰  %H:%M:%S\n📅  %d %b %Y"))
        self.after(1000, self._update_clock)

    def _clear_content(self):
        for w in self.content.winfo_children():
            w.destroy()

    def _page_header(self, title, subtitle=""):
        f = tk.Frame(self.content, bg=C["bg"], pady=20, padx=28)
        f.pack(fill="x")
        tk.Label(f, text=title, bg=C["bg"], fg=C["text"], font=FONTS["title"]).pack(anchor="w")
        if subtitle:
            tk.Label(f, text=subtitle, bg=C["bg"], fg=C["text_dim"], font=FONTS["label"]).pack(anchor="w")
        ttk.Separator(self.content, orient="horizontal").pack(fill="x", padx=28, pady=(0,12))

    # ── DASHBOARD ─────────────────────────────
    def _show_dashboard(self):
        self._clear_content()
        self._page_header("Dashboard", f"Welcome back! Today is {date.today().strftime('%A, %d %B %Y')}")

        outer = tk.Frame(self.content, bg=C["bg"])
        outer.pack(fill="both", expand=True, padx=28)

        # Stats row
        rows = self.db.get_all()
        today_str = date.today().strftime("%Y-%m-%d")
        today_rows = self.db.get_by_date(today_str)
        n_present = sum(1 for r in today_rows if r["status"]=="Present")
        n_absent  = sum(1 for r in today_rows if r["status"]=="Absent")
        n_late    = sum(1 for r in today_rows if r["status"]=="Late")

        stats_f = tk.Frame(outer, bg=C["bg"])
        stats_f.pack(fill="x", pady=(0,16))
        for label, val, color in [
            ("Today's Present", n_present, C["present"]),
            ("Today's Absent",  n_absent,  C["absent"]),
            ("Today's Late",    n_late,    C["late"]),
            ("Total Records",   len(rows), C["accent"]),
        ]:
            c = make_stat_card(stats_f, label, val, color)
            c.pack(side="left", padx=(0,12), pady=4, fill="y")

        # Recent records
        bottom = tk.Frame(outer, bg=C["bg"])
        bottom.pack(fill="both", expand=True, pady=(0,20))

        recent_f = Card(bottom, padx=16, pady=12)
        recent_f.pack(side="left", fill="both", expand=True, padx=(0,12))
        tk.Label(recent_f, text="Recent Attendance", bg=C["card"],
                 fg=C["text"], font=FONTS["header"]).pack(anchor="w", pady=(0,8))

        cols = ("id","name","date","status")
        heads = ("ID","Name","Date","Status")
        tree = StyledTree(recent_f, cols, heads, height=12)
        tree.pack(fill="both", expand=True)
        tree.column("id",   width=80)
        tree.column("name", width=140)
        tree.column("date", width=100)
        tree.column("status", width=80)
        data = [(r["member_id"], r["name"], r["date"], r["status"]) for r in rows[:20]]
        tree.load_rows(data)

        # Mini chart (if matplotlib)
        if MATPLOTLIB_AVAILABLE:
            chart_f = Card(bottom, padx=16, pady=12, width=300)
            chart_f.pack(side="left", fill="y")
            chart_f.pack_propagate(False)
            tk.Label(chart_f, text="Today's Overview", bg=C["card"],
                     fg=C["text"], font=FONTS["header"]).pack(anchor="w", pady=(0,8))
            fig = Figure(figsize=(2.8, 2.8), dpi=90, facecolor=C["card"])
            ax = fig.add_subplot(111)
            ax.set_facecolor(C["card"])
            vals = [n_present, n_absent, n_late]
            if sum(vals) > 0:
                colors_pie = [C["present"], C["absent"], C["late"]]
                wedges, _ = ax.pie(vals, colors=colors_pie, startangle=90,
                                   wedgeprops=dict(width=0.55, edgecolor=C["card"]))
                ax.text(0,0, f"{sum(vals)}\nTotal", ha="center", va="center",
                        color=C["text"], fontsize=11, fontweight="bold")
                patches = [mpatches.Patch(color=c, label=l)
                           for c,l,v in zip(colors_pie,["Present","Absent","Late"], vals) if v>0]
                ax.legend(handles=patches,
                          loc="lower center", frameon=False,
                          labelcolor=C["text"], fontsize=8)
            else:
                ax.text(0,0, "No Data\nToday", ha="center", va="center",
                        color=C["text_dim"], fontsize=12)
                ax.set_xlim(-1,1); ax.set_ylim(-1,1)
            ax.axis("off")
            fig.tight_layout()
            canvas = FigureCanvasTkAgg(fig, chart_f)
            canvas.draw()
            canvas.get_tk_widget().pack(fill="both", expand=True)

    # ── MARK ATTENDANCE ───────────────────────
    def _show_mark(self):
        self._clear_content()
        self._page_header("Mark Attendance", "Record daily attendance for students/employees")

        wrap = tk.Frame(self.content, bg=C["bg"], padx=28)
        wrap.pack(fill="both", expand=True)

        left = Card(wrap, padx=24, pady=20)
        left.pack(side="left", fill="y", padx=(0,16))

        tk.Label(left, text="Single Entry", bg=C["card"], fg=C["text"],
                 font=FONTS["header"]).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0,16))

        fields = [
            ("Member ID",  "e.g. EMP001"),
            ("Full Name",  "e.g. John Doe"),
            ("Date",       "YYYY-MM-DD"),
        ]
        entries = {}
        for i, (lbl, ph) in enumerate(fields, 1):
            SectionLabel(left, lbl, bg=C["card"]).grid(row=i*2-1, column=0, columnspan=2, sticky="w", pady=(8,2))
            e = StyledEntry(left, placeholder=ph, width=28)
            e.grid(row=i*2, column=0, columnspan=2, sticky="ew", ipady=6)
            entries[lbl] = e
            if lbl == "Date":
                e.delete(0,"end")
                e.insert(0, date.today().strftime("%Y-%m-%d"))
                e.config(fg=C["text"])

        SectionLabel(left, "Status", bg=C["card"]).grid(row=7, column=0, columnspan=2, sticky="w", pady=(8,2))
        status_var = tk.StringVar(value="Present")
        sf = tk.Frame(left, bg=C["card"])
        sf.grid(row=8, column=0, columnspan=2, sticky="w")
        for s, color in [("Present", C["present"]), ("Absent", C["absent"]), ("Late", C["late"])]:
            tk.Radiobutton(sf, text=s, variable=status_var, value=s,
                           bg=C["card"], fg=color, selectcolor=C["card"],
                           activebackground=C["card"], activeforeground=color,
                           font=FONTS["label_b"]).pack(side="left", padx=6)

        def do_mark():
            mid  = entries["Member ID"].value()
            name = entries["Full Name"].value()
            dt   = entries["Date"].value()
            st   = status_var.get()
            if not mid or mid == "e.g. EMP001":
                Toast(self, "Member ID required", "error"); return
            if not name or name == "e.g. John Doe":
                Toast(self, "Name required", "error"); return
            try:
                datetime.strptime(dt, "%Y-%m-%d")
            except ValueError:
                Toast(self, "Invalid date format (YYYY-MM-DD)", "error"); return
            self.db.add_member(mid, name)
            ok, msg = self.db.mark(mid, name, dt, st)
            if ok:
                self.csv.append(mid, name, dt, st)
                Toast(self, f"✓ Attendance marked: {st}", "success")
                bulk_tree.load_rows([(r["member_id"], r["name"], r["date"], r["status"])
                                     for r in self.db.get_by_date(dt)])
            else:
                Toast(self, msg, "warn")

        GlowButton(left, "✓  Mark Attendance", do_mark, color=C["accent2"]).grid(
            row=9, column=0, columnspan=2, sticky="ew", pady=16)

        # Bulk panel
        right = Card(wrap, padx=24, pady=20)
        right.pack(side="left", fill="both", expand=True)

        tk.Label(right, text="Today's Attendance", bg=C["card"],
                 fg=C["text"], font=FONTS["header"]).pack(anchor="w", pady=(0,10))

        date_f = tk.Frame(right, bg=C["card"])
        date_f.pack(fill="x", pady=(0,8))
        tk.Label(date_f, text="View Date:", bg=C["card"], fg=C["text_dim"],
                 font=FONTS["label"]).pack(side="left")
        view_date = StyledEntry(date_f, placeholder=date.today().strftime("%Y-%m-%d"), width=14)
        view_date.pack(side="left", padx=8, ipady=4)
        view_date.delete(0,"end"); view_date.insert(0, date.today().strftime("%Y-%m-%d")); view_date.config(fg=C["text"])

        cols = ("id","name","date","status")
        bulk_tree = StyledTree(right, cols, ("ID","Name","Date","Status"), height=16)
        bulk_tree.pack(fill="both", expand=True)
        bulk_tree.column("id",    width=80)
        bulk_tree.column("name",  width=160)
        bulk_tree.column("date",  width=100)
        bulk_tree.column("status",width=80)

        def load_date_view():
            dt = view_date.value()
            rows = self.db.get_by_date(dt)
            bulk_tree.load_rows([(r["member_id"],r["name"],r["date"],r["status"]) for r in rows])

        GlowButton(date_f, "Load", load_date_view, color=C["accent"]).pack(side="left")
        load_date_view()

    # ── VIEW RECORDS ──────────────────────────
    def _show_view(self):
        self._clear_content()
        self._page_header("View Records", "Browse, filter and search attendance records")

        wrap = tk.Frame(self.content, bg=C["bg"], padx=28)
        wrap.pack(fill="both", expand=True)

        # Filters bar
        fbar = Card(wrap, padx=16, pady=12)
        fbar.pack(fill="x", pady=(0,12))
        tk.Label(fbar, text="Search:", bg=C["card"], fg=C["text_dim"], font=FONTS["label"]).pack(side="left")
        search_e = StyledEntry(fbar, placeholder="ID or Name…", width=22)
        search_e.pack(side="left", padx=8, ipady=5)
        tk.Label(fbar, text="Filter Date:", bg=C["card"], fg=C["text_dim"], font=FONTS["label"]).pack(side="left", padx=(12,0))
        date_e = StyledEntry(fbar, placeholder="YYYY-MM-DD", width=14)
        date_e.pack(side="left", padx=8, ipady=5)

        cols = ("id","name","date","status","timestamp")
        tree = StyledTree(wrap, cols, ("ID","Name","Date","Status","Timestamp"), height=20)
        tree.pack(fill="both", expand=True)
        tree.column("id",        width=90)
        tree.column("name",      width=160)
        tree.column("date",      width=100)
        tree.column("status",    width=90)
        tree.column("timestamp", width=160)

        sb = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
        tree.configure(yscroll=sb.set)
        sb.pack(side="right", fill="y")

        def load_all():
            rows = self.db.get_all()
            tree.load_rows([(r["member_id"],r["name"],r["date"],r["status"],r["timestamp"]) for r in rows])

        def do_search():
            q = search_e.value()
            d = date_e.value()
            if q:
                rows = self.db.search(q)
            elif d:
                rows = self.db.get_by_date(d)
            else:
                rows = self.db.get_all()
            tree.load_rows([(r["member_id"],r["name"],r["date"],r["status"],r["timestamp"]) for r in rows])

        GlowButton(fbar, "🔍 Search", do_search).pack(side="left", padx=4)
        GlowButton(fbar, "↺ Reset",   load_all, color=C["btn"]).pack(side="left", padx=4)

        def export_visible():
            rows = [(tree.item(i)["values"]) for i in tree.get_children()]
            path = filedialog.asksaveasfilename(defaultextension=".csv",
                filetypes=[("CSV","*.csv")], initialfile="records_export.csv")
            if path:
                self.csv.export_report(path, rows, ["ID","Name","Date","Status","Timestamp"])
                Toast(self, "✓ Exported to CSV", "success")

        GlowButton(fbar, "⬇ Export CSV", export_visible, color=C["accent4"]).pack(side="right", padx=4)
        load_all()

    # ── UPDATE RECORDS ────────────────────────
    def _show_update(self):
        self._clear_content()
        self._page_header("Update Records", "Correct or remove attendance entries")

        wrap = tk.Frame(self.content, bg=C["bg"], padx=28)
        wrap.pack(fill="both", expand=True)

        left = Card(wrap, padx=24, pady=20, width=360)
        left.pack(side="left", fill="y", padx=(0,16))
        left.pack_propagate(False)

        tk.Label(left, text="Update Entry", bg=C["card"], fg=C["text"],
                 font=FONTS["header"]).pack(anchor="w", pady=(0,16))

        SectionLabel(left, "Member ID", bg=C["card"]).pack(anchor="w", pady=(6,2))
        uid_e = StyledEntry(left, placeholder="e.g. EMP001", width=26)
        uid_e.pack(fill="x", ipady=6)
        SectionLabel(left, "Date", bg=C["card"]).pack(anchor="w", pady=(10,2))
        udt_e = StyledEntry(left, placeholder="YYYY-MM-DD", width=26)
        udt_e.pack(fill="x", ipady=6)
        SectionLabel(left, "New Status", bg=C["card"]).pack(anchor="w", pady=(10,2))
        new_status = tk.StringVar(value="Present")
        sf = tk.Frame(left, bg=C["card"])
        sf.pack(anchor="w")
        for s, col in [("Present",C["present"]),("Absent",C["absent"]),("Late",C["late"])]:
            tk.Radiobutton(sf, text=s, variable=new_status, value=s,
                           bg=C["card"], fg=col, selectcolor=C["card"],
                           activebackground=C["card"], activeforeground=col,
                           font=FONTS["label_b"]).pack(side="left", padx=6)

        def do_update():
            mid = uid_e.value(); dt = udt_e.value()
            if not mid or not dt:
                Toast(self, "ID and Date required", "error"); return
            if self.db.update(mid, dt, new_status.get()):
                self.csv.sync_from_db(self.db)
                Toast(self, "✓ Record updated", "success")
                load_tree()
            else:
                Toast(self, "No matching record found", "warn")

        def do_delete():
            mid = uid_e.value(); dt = udt_e.value()
            if not mid or not dt:
                Toast(self, "ID and Date required", "error"); return
            if not messagebox.askyesno("Confirm", f"Delete {mid} on {dt}?"):
                return
            if self.db.delete(mid, dt):
                self.csv.sync_from_db(self.db)
                Toast(self, "✓ Record deleted", "success")
                load_tree()
            else:
                Toast(self, "No matching record found", "warn")

        GlowButton(left, "✓  Update Status", do_update, color=C["accent2"]).pack(fill="x", pady=(14,6))
        GlowButton(left, "🗑  Delete Record", do_delete, color=C["absent"]).pack(fill="x")

        # Right — table with click-to-fill
        right = Card(wrap, padx=16, pady=12)
        right.pack(side="left", fill="both", expand=True)
        tk.Label(right, text="All Records (click to select)", bg=C["card"],
                 fg=C["text"], font=FONTS["header"]).pack(anchor="w", pady=(0,8))

        cols = ("id","name","date","status")
        tree = StyledTree(right, cols, ("ID","Name","Date","Status"), height=20)
        tree.pack(fill="both", expand=True)
        tree.column("id",     width=90)
        tree.column("name",   width=160)
        tree.column("date",   width=100)
        tree.column("status", width=90)

        def load_tree():
            rows = self.db.get_all()
            tree.load_rows([(r["member_id"],r["name"],r["date"],r["status"]) for r in rows])

        def on_select(e):
            sel = tree.selection()
            if sel:
                vals = tree.item(sel[0])["values"]
                uid_e.delete(0,"end"); uid_e.insert(0, vals[0]); uid_e.config(fg=C["text"])
                udt_e.delete(0,"end"); udt_e.insert(0, vals[2]); udt_e.config(fg=C["text"])
                new_status.set(vals[3])

        tree.bind("<<TreeviewSelect>>", on_select)
        load_tree()

    # ── REPORTS ───────────────────────────────
    def _show_reports(self):
        self._clear_content()
        self._page_header("Reports & Analytics", "Generate summaries and visualize trends")

        wrap = tk.Frame(self.content, bg=C["bg"], padx=28)
        wrap.pack(fill="both", expand=True)

        # Controls
        ctrl = Card(wrap, padx=16, pady=12)
        ctrl.pack(fill="x", pady=(0,12))

        tk.Label(ctrl, text="Member ID:", bg=C["card"], fg=C["text_dim"], font=FONTS["label"]).pack(side="left")
        mid_e = StyledEntry(ctrl, placeholder="Leave blank for all", width=18)
        mid_e.pack(side="left", padx=8, ipady=5)

        tk.Label(ctrl, text="Month:", bg=C["card"], fg=C["text_dim"], font=FONTS["label"]).pack(side="left", padx=(12,0))
        months = [f"{i:02d} - {calendar.month_name[i]}" for i in range(1,13)]
        month_var = tk.StringVar(value=f"{date.today().month:02d} - {calendar.month_name[date.today().month]}")
        mo = ttk.Combobox(ctrl, values=months, textvariable=month_var, width=16, state="readonly")
        mo.pack(side="left", padx=8)

        tk.Label(ctrl, text="Year:", bg=C["card"], fg=C["text_dim"], font=FONTS["label"]).pack(side="left")
        yr_var = tk.StringVar(value=str(date.today().year))
        years = [str(y) for y in range(date.today().year-3, date.today().year+2)]
        ttk.Combobox(ctrl, values=years, textvariable=yr_var, width=7, state="readonly").pack(side="left", padx=8)

        body = tk.Frame(wrap, bg=C["bg"])
        body.pack(fill="both", expand=True)

        left = tk.Frame(body, bg=C["bg"])
        left.pack(side="left", fill="both", expand=True, padx=(0,12))

        # Summary table
        summary_card = Card(left, padx=16, pady=12)
        summary_card.pack(fill="both", expand=True)
        tk.Label(summary_card, text="Attendance Summary", bg=C["card"],
                 fg=C["text"], font=FONTS["header"]).pack(anchor="w", pady=(0,8))
        scols = ("id","name","present","absent","late","total","pct")
        sheads = ("ID","Name","Present","Absent","Late","Total","Pct %")
        stree = StyledTree(summary_card, scols, sheads, height=14)
        stree.pack(fill="both", expand=True)
        for c, w in zip(scols, [80,140,70,70,60,60,70]):
            stree.column(c, width=w)

        right_panel = tk.Frame(body, bg=C["bg"], width=340)
        right_panel.pack(side="left", fill="y")
        right_panel.pack_propagate(False)

        chart_card = Card(right_panel, padx=12, pady=12)
        chart_card.pack(fill="both", expand=True)
        tk.Label(chart_card, text="Visual Analysis", bg=C["card"],
                 fg=C["text"], font=FONTS["header"]).pack(anchor="w", pady=(0,8))

        def load_report():
            year  = int(yr_var.get())
            month = int(month_var.get().split(" ")[0])
            mid   = mid_e.value()
            rows = self.db.monthly_report(year, month)

            # aggregate
            agg = {}
            for r in rows:
                key = (r["member_id"], r["name"])
                if key not in agg:
                    agg[key] = {"present":0,"absent":0,"late":0}
                agg[key][r["status"].lower()] += 1

            if mid and mid != "Leave blank for all":
                agg = {k:v for k,v in agg.items() if k[0].lower() == mid.lower()}

            stree.delete(*stree.get_children())
            for i, ((mid_, name), d) in enumerate(agg.items()):
                total = d["present"]+d["absent"]+d["late"]
                pct   = round((d["present"]+d["late"]*0.5)/total*100,1) if total else 0
                tag   = "even" if i%2==0 else "odd"
                stree.insert("", "end", values=(mid_,name,d["present"],d["absent"],d["late"],total,f"{pct}%"), tags=(tag,))

            if MATPLOTLIB_AVAILABLE and agg:
                for w in chart_card.winfo_children():
                    if not isinstance(w, tk.Label):
                        w.destroy()
                names  = [k[1].split()[0] for k in agg][:8]
                pres   = [v["present"] for v in list(agg.values())[:8]]
                abss   = [v["absent"]  for v in list(agg.values())[:8]]
                lates  = [v["late"]    for v in list(agg.values())[:8]]

                fig = Figure(figsize=(3.2,4.5), dpi=90, facecolor=C["card"])
                ax  = fig.add_subplot(111)
                ax.set_facecolor(C["surface"])
                x = range(len(names))
                ax.bar(x, pres,  color=C["present"], label="Present", alpha=0.9)
                ax.bar(x, abss,  bottom=pres, color=C["absent"], label="Absent", alpha=0.9)
                ax.bar(x, lates, bottom=[p+a for p,a in zip(pres,abss)],
                       color=C["late"], label="Late", alpha=0.9)
                ax.set_xticks(list(x))
                ax.set_xticklabels(names, rotation=45, ha="right", fontsize=8, color=C["text_dim"])
                ax.tick_params(colors=C["text_dim"], labelsize=8)
                ax.spines["bottom"].set_color(C["border"])
                ax.spines["left"].set_color(C["border"])
                ax.spines["top"].set_visible(False)
                ax.spines["right"].set_visible(False)
                ax.legend(frameon=False, labelcolor=C["text"], fontsize=8, loc="upper right")
                ax.set_title(f"{calendar.month_name[month]} {year}",
                             color=C["text_dim"], fontsize=9, pad=8)
                fig.tight_layout()
                canvas = FigureCanvasTkAgg(fig, chart_card)
                canvas.draw()
                canvas.get_tk_widget().pack(fill="both", expand=True)

        def export_report():
            year  = int(yr_var.get())
            month = int(month_var.get().split(" ")[0])
            rows_data = [stree.item(i)["values"] for i in stree.get_children()]
            if not rows_data:
                Toast(self, "No data to export", "warn"); return
            path = filedialog.asksaveasfilename(
                defaultextension=".csv",
                filetypes=[("CSV","*.csv")],
                initialfile=f"report_{year}_{month:02d}.csv"
            )
            if path:
                self.csv.export_report(path, rows_data, ["ID","Name","Present","Absent","Late","Total","Pct%"])
                Toast(self, "✓ Report exported", "success")

        GlowButton(ctrl, "📊 Generate", load_report, color=C["accent"]).pack(side="left", padx=4)
        GlowButton(ctrl, "⬇ Export CSV", export_report, color=C["accent4"]).pack(side="left", padx=4)
        load_report()

    # ── MEMBERS ───────────────────────────────
    def _show_members(self):
        self._clear_content()
        self._page_header("Manage Members", "Add and view registered students/employees")

        wrap = tk.Frame(self.content, bg=C["bg"], padx=28)
        wrap.pack(fill="both", expand=True)

        left = Card(wrap, padx=24, pady=20, width=340)
        left.pack(side="left", fill="y", padx=(0,16))
        left.pack_propagate(False)

        tk.Label(left, text="Add Member", bg=C["card"], fg=C["text"],
                 font=FONTS["header"]).pack(anchor="w", pady=(0,16))

        SectionLabel(left, "Member ID", bg=C["card"]).pack(anchor="w", pady=(6,2))
        id_e = StyledEntry(left, placeholder="e.g. EMP007", width=26)
        id_e.pack(fill="x", ipady=6)
        SectionLabel(left, "Full Name", bg=C["card"]).pack(anchor="w", pady=(10,2))
        nm_e = StyledEntry(left, placeholder="e.g. Jane Doe", width=26)
        nm_e.pack(fill="x", ipady=6)

        def add_member():
            mid = id_e.value(); name = nm_e.value()
            if not mid or not name:
                Toast(self, "Both fields required", "error"); return
            self.db.add_member(mid, name)
            Toast(self, f"✓ Member {name} added", "success")
            load_members()
            id_e.delete(0,"end"); nm_e.delete(0,"end")
            id_e._placeholder_on(); nm_e._placeholder_on()

        GlowButton(left, "➕  Add Member", add_member, color=C["accent2"]).pack(fill="x", pady=(16,0))

        right = Card(wrap, padx=16, pady=12)
        right.pack(side="left", fill="both", expand=True)
        tk.Label(right, text="Registered Members", bg=C["card"],
                 fg=C["text"], font=FONTS["header"]).pack(anchor="w", pady=(0,8))

        mcols = ("id","name")
        mtree = StyledTree(right, mcols, ("ID","Name"), height=20)
        mtree.pack(fill="both", expand=True)
        mtree.column("id",   width=120)
        mtree.column("name", width=220)

        def load_members():
            mtree.delete(*mtree.get_children())
            for i, r in enumerate(self.db.get_members()):
                tag = "even" if i%2==0 else "odd"
                mtree.insert("", "end", values=(r["id"], r["name"]), tags=(tag,))

        load_members()

    # ── EMAIL ─────────────────────────────────
    def _show_email(self):
        self._clear_content()
        self._page_header("Send Email Report", "Email attendance reports directly")

        wrap = tk.Frame(self.content, bg=C["bg"], padx=28)
        wrap.pack(fill="both", expand=True)

        card = Card(wrap, padx=28, pady=24)
        card.pack(fill="x")

        def lbl(text): return SectionLabel(card, text, bg=C["card"])
        def ent(ph, show=None): 
            e = StyledEntry(card, placeholder=ph, width=42, show=show or "")
            return e

        lbl("From Email Address").pack(anchor="w", pady=(8,2))
        from_e = ent("your.email@gmail.com"); from_e.pack(fill="x", ipady=6)
        lbl("App Password (Gmail App Password)").pack(anchor="w", pady=(10,2))
        pass_e = StyledEntry(card, placeholder="xxxx xxxx xxxx xxxx", show="●", width=42)
        pass_e.pack(fill="x", ipady=6)
        lbl("To Email Address").pack(anchor="w", pady=(10,2))
        to_e = ent("recipient@example.com"); to_e.pack(fill="x", ipady=6)
        lbl("Subject").pack(anchor="w", pady=(10,2))
        subj_e = StyledEntry(card, placeholder="Monthly Attendance Report", width=42)
        subj_e.pack(fill="x", ipady=6)
        subj_e.delete(0,"end"); subj_e.insert(0,"Monthly Attendance Report"); subj_e.config(fg=C["text"])
        lbl("Body").pack(anchor="w", pady=(10,2))
        body_t = tk.Text(card, bg=C["surface"], fg=C["text"], insertbackground=C["accent"],
                         relief="flat", bd=0, highlightthickness=1,
                         highlightbackground=C["border"], font=FONTS["label"],
                         height=5, width=42)
        body_t.pack(fill="x")
        body_t.insert("end", "Please find the attached attendance report.")

        attach_var = tk.StringVar(value="")
        attach_lbl = tk.Label(card, text="No file selected", bg=C["card"],
                              fg=C["text_dim"], font=FONTS["small"])

        def pick_file():
            path = filedialog.askopenfilename(filetypes=[("CSV","*.csv"),("All","*.*")])
            if path:
                attach_var.set(path)
                attach_lbl.config(text=os.path.basename(path), fg=C["accent"])

        bf = tk.Frame(card, bg=C["card"])
        bf.pack(fill="x", pady=12)
        GlowButton(bf, "📎 Attach File", pick_file, color=C["btn"]).pack(side="left", padx=(0,8))
        attach_lbl.pack(side="left")

        status_lbl = tk.Label(card, text="", bg=C["card"], fg=C["text_dim"], font=FONTS["label"])
        status_lbl.pack(anchor="w")

        def do_send():
            fr = from_e.value(); pw = pass_e.value()
            to = to_e.value(); sub = subj_e.value()
            bd = body_t.get("1.0","end").strip()
            att = attach_var.get()
            if not all([fr, pw, to, sub]):
                Toast(self, "Fill all required fields", "error"); return
            status_lbl.config(text="⏳ Sending…", fg=C["accent"])
            self.update()
            def _send():
                try:
                    send_email(to, sub, bd, att or None, from_addr=fr, password=pw)
                    status_lbl.config(text="✓ Email sent successfully!", fg=C["present"])
                    Toast(self, "✓ Email sent!", "success")
                except Exception as ex:
                    status_lbl.config(text=f"✗ {ex}", fg=C["absent"])
                    Toast(self, f"Error: {ex}", "error")
            threading.Thread(target=_send, daemon=True).start()

        GlowButton(card, "📧  Send Email", do_send, color=C["accent"]).pack(anchor="w", pady=(8,0))

        info = Card(wrap, padx=20, pady=14)
        info.pack(fill="x", pady=(16,0))
        tk.Label(info, text="ℹ  Gmail Setup", bg=C["card"], fg=C["accent"],
                 font=FONTS["label_b"]).pack(anchor="w")
        note = ("Use a Gmail App Password (not your login password).\n"
                "Go to: Google Account → Security → 2-Step Verification → App Passwords.\n"
                "Ensure 'Less secure app access' or App Passwords are enabled.")
        tk.Label(info, text=note, bg=C["card"], fg=C["text_dim"],
                 font=FONTS["small"], justify="left").pack(anchor="w", pady=(4,0))

    # ── BACKUP ────────────────────────────────
    def _do_backup(self):
        try:
            auto_backup(self.db, self.csv)
            Toast(self, "✓ Backup created successfully", "success")
        except Exception as e:
            Toast(self, f"Backup failed: {e}", "error")

    def _schedule_backup(self):
        # Auto-backup every 30 minutes
        def _run():
            auto_backup(self.db, self.csv)
            self.after(30*60*1000, _schedule_backup_inner)
        def _schedule_backup_inner():
            threading.Thread(target=_run, daemon=True).start()
        self.after(30*60*1000, _schedule_backup_inner)

    def _on_close(self):
        try:
            self.csv.sync_from_db(self.db)
            auto_backup(self.db, self.csv)
        except Exception:
            pass
        finally:
            self.db.close()
            self.destroy()

# ─────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────
if __name__ == "__main__":
    app = AttendanceApp()
    app.mainloop()
