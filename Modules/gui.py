import tkinter as tk
from tkinter import ttk, messagebox
import threading
import queue
import tomllib
import json
import urllib.request
import sys
from pathlib import Path

def app_directory():
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent

from datetime import datetime
from .config import BG, PANEL, INPUT_BG, FG, MUTED, GREEN, RED, BLUE, LIGHT_GREEN, LIGHT_RED
from .udp_listener import UDPListenerMixin
from .harc import HarcMixin
from .credentials import CredentialsMixin
from .config import ENABLE_LOCATORS, debug
from .qth_locator import LocatorDatabase
from .mqtt_locator import MQTTLocator
from .time_sync import check_time
from .betoltes import Betoltes
from .locator_updater import check_locators_update
from .updater import check_update, download_installer, start_installer

class HARCBridge(UDPListenerMixin, HarcMixin, CredentialsMixin):
    def __init__(self, root):
        self.root = root
        self.betoltes = Betoltes(self.root, self.fokepernyo_inditas)#betöltési képernyőt behozzuk self.betoltes
        self.root.title("HARC Log Bridge v0.2")
        self.root.geometry("850x650")
        self.root.minsize(720, 480)
        self.root.configure(bg=BG)
        
        #Időellenőrzés eredménye a főképernyő megjelenéséig, betöltés alatt
        self.time_difference = None
        
        # A háttérszálak ezen keresztül üzennek a Tkinternek.
        self.messages = queue.Queue()
        self.betoltes_messages = queue.Queue()

        # A QSO-k sorban kerülnek feltöltésre.
        self.jobs = queue.Queue()

        self.running = True
        self.betoltes_aktiv = True
        self.hotelalfa_eredmeny_mentett = None

        # START/STOP kapcsoló, kezdetben STOP.
        self.upload_enabled = threading.Event()

        # HARC belépési adatok és böngészőbeállítás.
        self.callsign = tk.StringVar()
        self.password = tk.StringVar()
        self.show_browser = tk.BooleanVar(value=False)  # Mindig rejtett Chromium
        
        # Elsőként KIZÁRÓLAG a verzióellenőrzés indul el.
        # A többi inicializálás csak annak befejezése (vagy kihagyása) után következik.
        self._tovabbi_betoltes_elindult = False
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(100, self.betoltes_uzenetek)
        self.root.after(0, self.frissites_ellenorzes_inditas)

    def tovabbi_betoltes_inditas(self):
        if self._tovabbi_betoltes_elindult:
            return
        self._tovabbi_betoltes_elindult = True
        # LOG11DX UDP továbbítás kapcsolója (alapból kikapcsolva).
        self.forward_log11dx_enabled = threading.Event()
        self.settings_path = app_directory() / 'Settings' / 'settings.tom'
        self.log11dx_warning_disabled = self.load_warning_setting()
        self.forward_log11dx = tk.BooleanVar(value=self.load_forward_setting())
        if self.forward_log11dx.get():
            self.forward_log11dx_enabled.set()
        # A beállítás beolvasása kész akkor is, ha nincs settings.tom,
        # vagy a LOG11DX továbbítás alapértelmezetten ki van kapcsolva.
        self.betoltes.feladat_kesz("log11dx")

        # Az aktuális programindítás számlálói.
        self.received_count = 0
        self.sent_count = 0
        self.error_count = 0

        # UDP duplikációk kiszűrése.
        self.seen_qsos = set()
        self.record_counter = 0
        self.failed_uploads = {}  # record_id -> (qso, reason, uncertain)
        self.failed_logs_path = app_directory() / "Settings" / "failed_logs.json"
        self.pending_uploads = {}  # record_id -> qso, until result

        # A lokátoradatbázist csak egyszer töltjük a memóriába.
        # Hiányzó vagy sérült adatbázis nem akadályozza a spotküldést.
        self.locator_db = LocatorDatabase()
        self.locator_info = "QRA adatbázis: kikapcsolva"
        if ENABLE_LOCATORS:
            try:
                count = self.locator_db.load()
                self.locator_info = f"QRA adatbázis betöltve: {count} hívójel"
                debug("Adatbázis feldolgozva sikeres")
            except Exception as exc:
                self.locator_info = f"QRA adatbázis nem elérhető: {exc}"
                debug("Adatbázis feldolgozva sikertelen")
            

        self.betoltes.feladat_kesz("lokator")

        self.mqtt_locator = MQTTLocator(self.locator_db, self.log) if ENABLE_LOCATORS else None
        # A főképernyőt a betöltés befejezése után indítjuk.

        # Külön szálon figyeljük az UDP-t és dolgozzuk fel a webes feladatokat.
        threading.Thread(target=self.listen_udp, daemon=True).start()
        threading.Thread(target=self.web_queue_worker, daemon=True).start()

        # A grafikus felület 100 ms-onként feldolgozza a beérkező üzeneteket.
        self.root.after(200, self.lokator_frissites_inditas)#ellenőrzi hogy kell-e frissíteni a locator és locator_base-t (frissítés után kell)
        self.root.after(200, self.start_time_check)#idő ellenőrzés
        self.root.after(300, self.hotelalfa_ellenorzes_inditas)#hotelalfa honlap elérhetőségének vizsgálata
        # Első indítási ellenőrzés: a főképernyő csak ennek lezárulta után nyílik meg.


    def frissites_ellenorzes_inditas(self):
        threading.Thread(target=self.frissites_ellenorzes_worker, daemon=True).start()

    def frissites_ellenorzes_worker(self):
        version, error = check_update()
        self.betoltes_messages.put(("updater_eredmeny", (version, error)))

    def frissites_folytatas(self, status):
        self.betoltes.frissites_allapot.configure(text=status)
        self.betoltes.feladat_kesz("updater")
        self.tovabbi_betoltes_inditas()

    def frissites_kerdes(self, version):
        self.betoltes.frissites_allapot.configure(text=f"Új verzió érhető el: {version}")
        if not messagebox.askyesno("HARC Bridge frissítés", f"Elérhető a {version} verzió.\nSzeretnéd most frissíteni?", parent=self.root):
            self.frissites_folytatas("Frissítés kihagyva.")
            return
        if sys.platform != "win32":
            messagebox.showinfo("Frissítés", "Az automatikus telepítés jelenleg csak Windows alatt érhető el.", parent=self.root)
            self.frissites_folytatas("Frissítés kihagyva (Linux).")
            return
        self.betoltes.frissites_allapot.configure(text="Frissítés letöltése...")
        threading.Thread(target=self.frissites_letoltes_worker, daemon=True).start()

    def frissites_letoltes_worker(self):
        try:
            path = download_installer()
            self.betoltes_messages.put(("updater_telepites", path))
        except Exception as exc:
            self.betoltes_messages.put(("updater_hiba", str(exc)))

    def frissites_telepites(self, path):
        try:
            start_installer(path)
        except Exception as exc:
            messagebox.showerror("Frissítés", f"Nem sikerült elindítani a telepítőt:\n{exc}", parent=self.root)
            self.frissites_folytatas("Frissítés sikertelen, program indítása.")
            return
        # A telepítőnek a régi EXE-k cseréje előtt le kell zárnia a Bridge-et.
        self.root.destroy()


    def fokepernyo_inditas(self):
        self.betoltes_aktiv = False

        self.create_ui()
        self.load_failed_logs()
        self.draw_harc_badge(self.hotelalfa_eredmeny_mentett)
        self.load_credentials()

        if self.mqtt_locator:
            self.mqtt_locator.start()

        self.root.after(100, self.process_messages)
        self.root.after(100, self.show_time_status, self.time_difference)
        
    def lokator_frissites_inditas(self):
        threading.Thread(target=self.lokator_frissites_worker,daemon=True).start()#külön szálon elindítjuk a lokátor frissítést   
        
    def lokator_frissites_worker(self):
        try:
            check_locators_update()
        except Exception as exc:
            debug(f"Lokátorfrissítési hiba: {exc}")
        finally:
            self.betoltes_messages.put(("lokator_frissites_kesz", None))
            
    def hotelalfa_ellenorzes_inditas(self):
        threading.Thread(target=self.hotelalfa_site_check,daemon=True).start()               

    def create_ui(self):
        """Az ablak, a fülek, a táblázat és a vezérlők létrehozása."""

        style = ttk.Style()
        style.theme_use("clam")

        # Sötét Tkinter téma
        style.configure("Dark.TNotebook", background=BG, borderwidth=0)
        style.configure("Dark.TNotebook.Tab", background=PANEL, foreground=MUTED, padding=(14, 7))
        style.map("Dark.TNotebook.Tab", background=[("selected", BLUE)], foreground=[("selected", FG)])

        style.configure("Dark.Treeview", background=PANEL, fieldbackground=PANEL, foreground=FG, rowheight=29, borderwidth=0)
        style.configure("Dark.Treeview.Heading", background=INPUT_BG, foreground=FG, relief="flat", font=("Segoe UI", 9, "bold"))
        style.map("Dark.Treeview", background=[("selected", BLUE)], foreground=[("selected", FG)])

        style.configure("Dark.TEntry", fieldbackground=INPUT_BG, foreground=FG, insertcolor=FG, padding=6)
        style.configure("Dark.TCheckbutton", background=BG, foreground=FG)

        # ---------------- KOMPAKT FEJLÉC ÉS VEZÉRLŐSOR ----------------

        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=14, pady=(10, 5))

        tk.Label(header, text="◉ HARC Log Bridge", bg=BG, fg=FG,
                 font=("Segoe UI", 16, "bold")).pack(side="left")
        tk.Label(header, text="v0.2", bg=BG, fg=MUTED,
                 font=("Segoe UI", 9)).pack(side="left", padx=8)
        tk.Label(header,
                 text="Fejlesztők: Németh Tamás 109HA9731  |  Varga Tamás 109HA2247",
                 bg=BG, fg=MUTED, font=("Segoe UI", 8)).pack(side="right")

        control = tk.Frame(self.root, bg=PANEL, padx=12, pady=8)
        control.pack(fill="x", padx=14, pady=(0, 5))

        self.toggle_button = tk.Button(
            control, text="▶ START", command=self.toggle_upload,
            bg=GREEN, fg="white", activebackground="#20A574",
            activeforeground="white", relief="flat",
            font=("Segoe UI", 11, "bold"), width=13, cursor="hand2"
        )
        self.toggle_button.pack(side="right")

        self.state_label = tk.Label(control, text="● LEÁLLÍTVA", bg=PANEL,
                                    fg=LIGHT_RED, font=("Segoe UI", 11, "bold"))
        self.state_label.pack(side="left", padx=(0, 18))

        # Az óraállapot ugyanebben a sávban, a gomb mellett jelenik meg.
        # A hosszabb figyelmeztetés a rendelkezésre álló helyen sort törhet.
        self.time_label = tk.Label(
            control, text="Óra szinkron: Ellenőrzés...", bg=PANEL, fg=MUTED,
            font=("Segoe UI", 9, "bold"), anchor="e", justify="right",
            wraplength=430
        )
        self.time_label.pack(side="right", padx=(6, 12))


        # ---------------- SZÁMLÁLÓK ----------------

        stats = tk.Frame(self.root, bg=BG)
        stats.pack(fill="x", padx=11, pady=(0, 6))

        self.received_label = self.stat_card(stats, "Fogadott QSO", FG)
        self.sent_label = self.stat_card(stats, "Elküldött", LIGHT_GREEN)
        self.error_label = self.stat_card(stats, "Hiba", LIGHT_RED)

        # ---------------- FÜLEK ----------------

        tabs_container = tk.Frame(self.root, bg=BG)#Létrehoztunk egy konténert a fülek számára hogy más is kerülhessen melléjük
        tabs_container.pack(fill="both", expand=True, padx=14, pady=(0, 6))
    
        notebook = ttk.Notebook(tabs_container, style="Dark.TNotebook")#a notebook most már a konténeren belül fog elhelyezkedni
        notebook.pack(fill="both", expand=True, padx=14, pady=(0, 6))

        log_tab = tk.Frame(notebook, bg=BG)
        settings_tab = tk.Frame(notebook, bg=BG)
        events_tab = tk.Frame(notebook, bg=BG)

        notebook.add(log_tab, text="Élő napló")
        notebook.add(settings_tab, text="Beállítások")
        notebook.add(events_tab, text="Események")
        
        # ------------ HOTELALFA oldal ellenőrzés és kiírás metódusa ----------------------------        
        self.hotelalfa_site_available = queue.Queue()

        # A Canvas-szal valódi lekerekített hátteret kapunk, külön csomag nélkül.
        self.harc_badge = tk.Canvas(
            tabs_container, width=260, height=31, bg=BG,
            highlightthickness=0, bd=0
        )
        self.harc_badge.place(relx=1.0, x=-10, y=0, anchor="ne")
        tk.Misc.lift(self.harc_badge)  # A teljes Canvas widget előtérbe hozása
        self.draw_harc_badge(None)  # Induláskor: ellenőrzés folyamatban

        site_visit = threading.Thread(target=self.hotelalfa_site_check, daemon=True)#külön szálon megnézzük elérhető-e a hotelalfa.hu
        site_visit.start()

        # ---------------- ÉLŐ NAPLÓ ----------------

        columns = ("call", "time", "reports", "status", "action")
        self.table = ttk.Treeview(log_tab, columns=columns, show="headings", style="Dark.Treeview")

        headings = {"call": "DX hívójel", "time": "UTC", "reports": "RX / TX", "status": "HARC", "action": "Művelet"}
        widths = {"call": 150, "time": 85, "reports": 160, "status": 180, "action": 130}

        for col in columns:
            self.table.heading(col, text=headings[col])
            self.table.column(col, width=widths[col], anchor="center")

        # Az egész sor színe a HARC állapotát jelzi.
        self.table.tag_configure("sent", foreground=LIGHT_GREEN)
        self.table.tag_configure("error", foreground=LIGHT_RED)
        self.table.tag_configure("skipped", foreground=MUTED)
        self.table.pack(fill="both", expand=True)
        # Treeview-ben nincs valódi cellagomb; a Művelet cella kattintható.
        self.table.bind("<ButtonRelease-1>", self.on_table_click)

        # ---------------- BEÁLLÍTÁSOK ----------------

        self.setting_label(settings_tab, "HARC hívójel")
        ttk.Entry(settings_tab, textvariable=self.callsign, width=35, style="Dark.TEntry").pack(anchor="w", padx=12, pady=(0, 10))

        self.setting_label(settings_tab, "HARC jelszó")
        ttk.Entry(settings_tab, textvariable=self.password, show="*", width=35, style="Dark.TEntry").pack(anchor="w", padx=12, pady=(0, 10))

        # A böngésző megjelenítése nem állítható a felületen.

        ttk.Checkbutton(
            settings_tab, 
            text="UDP továbbítás a LOG11DX felé (2238)",
            variable=self.forward_log11dx,
            command=self.toggle_log11dx_forward,
            style="Dark.TCheckbutton"
        ).pack(anchor="w", padx=12, pady=8)

        tk.Button(
            settings_tab, text="Bejelentkezési adatok mentése",
            command=self.save_credentials, bg=BLUE, fg="white",
            relief="flat", padx=12, pady=7
        ).pack(anchor="w", padx=12, pady=8)

        tk.Label(
            settings_tab,
            text="27265 kHz  •  FT8  •  WKD\nMegjegyzés: RX / TX + WSJT-CB COMMENT",
            bg=BG, fg=MUTED, justify="left"
        ).pack(anchor="w", padx=12, pady=10)

        # ---------------- ESEMÉNYNAPLÓ ----------------

        self.output = tk.Text(
            events_tab, bg=PANEL, fg=FG, insertbackground=FG,
            font=("Consolas", 9), relief="flat", state="disabled", wrap="word"
        )
        self.output.pack(fill="both", expand=True)

        # ---------------- ALSÓ ÁLLAPOTSOR ----------------

        self.bottom_status = tk.Label(
            self.root, text="UDP kapcsolat indítása...", bg=BG,
            fg=MUTED, anchor="w", font=("Segoe UI", 9)
        )
        self.bottom_status.pack(fill="x", padx=14, pady=(0, 6))
        
    def draw_harc_badge(self, available):
        """A HARC weboldal státuszát lekerekített jelzőn jeleníti meg."""
        if available is True:
            background, border, color = "#173A30", "#276B50", "#74E0AB"
            status = "Elérhető"
        elif available is False:
            background, border, color = "#40252A", "#85434A", "#FF929C"
            status = "Nem elérhető"
        else:
            background, border, color = "#29313F", "#495366", "#AAB6CA"
            status = "Ellenőrzés..."

        canvas = self.harc_badge
        canvas.delete("all")
        # Lekerekített téglalap: a végeken félkörök, középen téglalap.
        for fill, inset in ((border, 0), (background, 1)):
            x0, y0, x1, y1 = 1 + inset, 1 + inset, 259 - inset, 30 - inset
            radius = (y1 - y0) / 2
            canvas.create_oval(x0, y0, x0 + 2 * radius, y1, fill=fill, outline=fill)
            canvas.create_oval(x1 - 2 * radius, y0, x1, y1, fill=fill, outline=fill)
            canvas.create_rectangle(x0 + radius, y0, x1 - radius, y1,
                                    fill=fill, outline=fill)
        canvas.create_oval(13, 11, 22, 20, fill=color, outline=color)
        canvas.create_text(31, 15, anchor="w", text="HARC LOG CLUSTER",
                           fill="#E6EAF1", font=("Segoe UI", 9, "bold"))
        canvas.create_text(248, 15, anchor="e", text=status,
                           fill=color, font=("Segoe UI", 9, "bold"))

    def hotelalfa_site_check(self):
        # Csak a háttérszál végez hálózati kérést, Tkinter elemet nem módosít.
        try:
            valasz = self.check_hotelalfa_site()#a valasz a check_hotelalfa_site függvény válasza
        except Exception as exc:
            print(f"HARC elérhetőség-ellenőrzési hiba: {exc}")
            valasz = False
        self.betoltes_messages.put(("hotelalfa_kesz", valasz))
        debug("Hotel Alfa eredménye elküldve a betöltőnek")

    def hotelalfa_eredmeny(self):#késleltetett meghívással megnézzük hogy van-e eredménye az oldal ellenőrzés szálnak
        # A Canvas frissítése kizárólag a Tkinter főszálán történik.
        try:
            eredmeny = self.hotelalfa_site_available.get_nowait()
        except queue.Empty:
            if self.running:
                self.root.after(100, self.hotelalfa_eredmeny)
            return
        self.draw_harc_badge(eredmeny)
        self.betoltes.feladat_kesz("hotelalfa")#oldal ellenőrzés késznek nyilvánítása betöltéshez

    def start_time_check(self):#Megnézzük az idő eltérés mértékét
        def worker():
            difference = check_time()
            self.root.after(0, self.time_check_finished, difference)

        threading.Thread(target=worker, daemon=True).start()
        
    def time_check_finished(self, difference):
        self.time_difference = difference
        self.betoltes.feladat_kesz("ido")

    def show_time_status(self, difference):#time_check óra állapot kiírás        
        
        if not hasattr(self, "time_label"):#ellenőrzi létre jött-e már a felirat a betöltés során
            debug("Nincs time_label")
            return
            
        if difference is None:
            self.time_label.config(
                text="Óra szinkron: Nem ellenőrizhető",
                fg=MUTED
            )

        elif abs(difference) < 1:
            self.time_label.config(
                text="Óra szinkron: Pontos",
                fg=LIGHT_GREEN
            )

        else:
            self.time_label.config(
                text=f"Pontatlan óra! ({difference:+.2f} mp eltérés) – állítsd be a pontos időt.",
                fg=LIGHT_RED
            )

    def stat_card(self, parent, title, color):
        """Egy számlálókártya létrehozása a főablak tetején."""

        frame = tk.Frame(parent, bg=PANEL, padx=12, pady=5)
        frame.pack(side="left", fill="x", expand=True, padx=3)

        tk.Label(frame, text=title, bg=PANEL, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w")

        value = tk.Label(frame, text="0", bg=PANEL, fg=color, font=("Segoe UI", 17, "bold"))
        value.pack(anchor="w")
        return value

    def setting_label(self, parent, text):
        """Egységes felirat a Beállítások fülön."""
        tk.Label(parent, text=text, bg=BG, fg=FG, font=("Segoe UI", 10)).pack(anchor="w", padx=12, pady=(10, 4))

    def load_forward_setting(self):
        try:
            with self.settings_path.open('rb') as f:
                value = tomllib.load(f).get('settings', {}).get('forward_log11dx', False)
            return value if isinstance(value, bool) else False
        except (OSError, ValueError, tomllib.TOMLDecodeError):
            return False
            
    def load_warning_setting(self):
        try:
            with self.settings_path.open('rb') as f:
                value = tomllib.load(f).get('settings', {}).get('log_warning_disabled', False)
            debug(f"log11dx_warning_disabled : {value}")
            return value if isinstance(value, bool) else False

        except (OSError, ValueError, tomllib.TOMLDecodeError):
            return False

    def save_forward_setting(self):
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.settings_path.with_suffix('.tmp')
        tmp.write_text(
        '[settings]\nforward_log11dx = ' + ('true' if self.forward_log11dx.get() else 'false') + '\nlog_warning_disabled = ' + 
        ('true' if self.log11dx_warning_disabled else 'false') + '\n', encoding='utf-8')
        tmp.replace(self.settings_path)

    def toggle_log11dx_forward(self):
        """A LOG11DX UDP-továbbításának be- és kikapcsolása."""

        if self.forward_log11dx.get():
            self.forward_log11dx_enabled.set()
            self.log("LOG11DX UDP továbbítás bekapcsolva.")
            
            if not self.log11dx_warning_disabled:
                self.show_log11dx_warning()
        else:
            self.forward_log11dx_enabled.clear()
            self.log("LOG11DX UDP továbbítás kikapcsolva.")
        try:
            self.save_forward_setting()
        except OSError as exc:
            self.log(f"LOG11DX beállítás mentési hiba: {exc}")

    def show_log11dx_warning(self):
        window = tk.Toplevel(self.root)
        window.title("HARC Bridge - LOG11DX")
        window.configure(bg="#1C2029")
        window.resizable(False, False)

        width = 460
        height = 330

        # A főablak aktuális helyének és méretének lekérése.
        self.root.update_idletasks()

        x = self.root.winfo_rootx() + (self.root.winfo_width() - width) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - height) // 2

        window.geometry(f"{width}x{height}+{x}+{y}")
        window.transient(self.root)

        bg = "#1C2029"
        fg = "#E6EAF1"
        muted = "#AAB3C3"
        panel = "#292F3B"

        # Fejléc
        tk.Label(
            window,
            text="⚠  LOG11DX továbbítás",
            font=("Segoe UI", 15, "bold"),
            fg="#FFBF61",
            bg=bg
        ).pack(anchor="w", padx=25, pady=(22, 5))

        tk.Label(
            window,
            text="Ellenőrizd az UDP-portok beállítását!",
            font=("Segoe UI", 10),
            fg=muted,
            bg=bg
        ).pack(anchor="w", padx=25, pady=(0, 16))

        # Portok
        ports = tk.Frame(window, bg=panel)
        ports.pack(fill="x", padx=25, pady=(0, 15))

        tk.Label(
            ports, text="WSJT-CB     2237",
            font=("Consolas", 12, "bold"),
            fg=fg, bg=panel
        ).pack(pady=(12, 5))

        tk.Label(
            ports, text="LOG11DX     2238",
            font=("Consolas", 12, "bold"),
            fg=fg, bg=panel
        ).pack(pady=(5, 12))

        # Tájékoztató
        tk.Label(
            window,
            text="Portmódosítás után indítsd újra\n"
                 "a LOG11DX programot!",
            font=("Segoe UI", 10),
            fg=muted,
            bg=bg,
            justify="left"
        ).pack(anchor="w", padx=25)

        dont_show = tk.BooleanVar(value=False)

        # Alsó vezérlők
        bottom = tk.Frame(window, bg=bg)
        bottom.pack(fill="x", padx=25, pady=(20, 0))

        tk.Checkbutton(
            bottom,
            text="Ne jelenjen meg újra",
            variable=dont_show,
            font=("Segoe UI", 10),
            fg=fg,
            bg=bg,
            activeforeground=fg,
            activebackground=bg,
            selectcolor=panel,
            bd=0,
            highlightthickness=0
        ).pack(side="left")

        def confirm():
            if dont_show.get():
                self.log11dx_warning_disabled = True
                try:
                    self.save_forward_setting()
                except OSError as exc:
                    self.log(f"Figyelmeztetés mentési hiba: {exc}")

            window.destroy()

        ok_button = tk.Button(
            bottom,
            text="Rendben",
            command=confirm,
            font=("Segoe UI", 10, "bold"),
            fg="white",
            bg="#3379E5",
            activeforeground="white",
            activebackground="#2563C4",
            relief="flat",
            cursor="hand2",
            padx=20,
            pady=8
        )
        ok_button.pack(side="right")

        window.protocol("WM_DELETE_WINDOW", confirm)
        window.bind("<Return>", lambda event: confirm())
        window.grab_set()
        ok_button.focus_set()

    def toggle_upload(self):
        """Engedélyezi vagy letiltja az automatikus HARC feltöltést."""

        if self.upload_enabled.is_set():
            # START -> STOP
            self.upload_enabled.clear()
            self.state_label.config(text="● LEÁLLÍTVA", fg=LIGHT_RED)
            self.toggle_button.config(text="▶ START", bg=GREEN)
            self.log("Automatikus HARC feltöltés leállítva.")

        else:
            # HARC belépési adatok nélkül nem indítunk feltöltést.
            if not self.callsign.get().strip() or not self.password.get():
                messagebox.showwarning("Hiányzó adatok", "Először add meg a HARC bejelentkezési adatokat!")
                return

            # STOP -> START
            self.upload_enabled.set()
            self.state_label.config(text="● FUT", fg=LIGHT_GREEN)
            self.toggle_button.config(text="■ STOP", bg=RED)
            self.log("Automatikus HARC feltöltés elindítva.")

    def add_qso(self, qso):
        """Megjeleníti a QSO-t, START esetén pedig feltöltési sorba helyezi."""

        # Egy összeköttetést hívójel + dátum + idő + mód alapján azonosítunk.
        key = (
            qso.get("CALL", ""),
            qso.get("QSO_DATE", ""),
            qso.get("TIME_ON", ""),
            qso.get("MODE", "")
        )

        # A pontos azonosító megmutatja, melyik mező változott két küldés között.

        # Ugyanazt az UDP logot nem dolgozzuk fel többször.
        if key in self.seen_qsos:
            self.log(f"Duplikált QSO kihagyva: {key[0]} (azonos dátum, idő és mód)")
            return

        # Ugyanaz a hívójel eltérő azonosítóval nem feltétlenül duplikáció.
        previous = [old for old in self.seen_qsos if old[0] == key[0]]
        if previous:
            self.log(f"FIGYELEM: {key[0]} már szerepelt, de eltér a QSO azonosítója!")
            for old in previous[-3:]:
                changes = [f"{name}: {before!r} -> {after!r}"
                           for name, before, after in zip(("CALL", "DÁTUM", "UTC", "MÓD"), old, key)
                           if before != after]
                self.log("Eltérés a korábbi QSO-hoz képest: " + ", ".join(changes))

        self.seen_qsos.add(key)
        self.record_counter += 1
        record_id = str(self.record_counter)

        self.received_count += 1
        self.received_label.config(text=str(self.received_count))

        # A táblázatban rövidített UTC időt jelenítünk meg.
        utc = qso.get("TIME_ON", "")
        if len(utc) >= 4:
            utc = f"{utc[:2]}:{utc[2:4]}"

        rx = qso.get("RST_RCVD", "")
        tx = qso.get("RST_SENT", "")
        enabled = self.upload_enabled.is_set()

        status = "Várakozik" if enabled else "Kihagyva (STOP)"

        self.table.insert(
            "", 0, iid=record_id,
            values=(qso.get("CALL", ""), utc, f"{rx} / {tx}", status),
            tags=() if enabled else ("skipped",)
        )

        self.log(f"Új QSO: {qso['CALL']}")

        # STOP esetén csak a helyi táblázatba kerül az összeköttetés.
        if not enabled:
            self.log("STOP állapot: feltöltés kihagyva.")
            return

        # A feladatot a háttérben futó webes feldolgozó kapja meg.
        # A LOG helyi időbélyegét egyszer rögzítjük, hogy újraküldéskor ne változzon.
        qso = qso.copy()
        qso["_LOG_LOCAL_TIME"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.pending_uploads[record_id] = qso.copy()
        self.jobs.put((
            record_id, qso.copy(),
            self.callsign.get().strip().upper(),
            self.password.get(),
            self.show_browser.get()
        ))

    def save_failed_logs(self):
        """Csak a sikertelen LOG-ok; jelszó nem kerül a fájlba."""
        records = [
            {"qso": qso, "reason": reason, "uncertain": uncertain}
            for qso, reason, uncertain in self.failed_uploads.values()
        ]
        self.failed_logs_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.failed_logs_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.failed_logs_path)

    def load_failed_logs(self):
        if not self.failed_logs_path.exists():
            return
        try:
            records = json.loads(self.failed_logs_path.read_text(encoding="utf-8"))
            if not isinstance(records, list):
                raise ValueError("Érvénytelen mentett LOG-lista")
            for item in records:
                qso = item["qso"]
                if not isinstance(qso, dict) or not qso.get("CALL"):
                    continue
                self.record_counter += 1
                rid = str(self.record_counter)
                self.failed_uploads[rid] = (qso, item.get("reason", "Korábbi hiba"), bool(item.get("uncertain", True)))
                utc = qso.get("TIME_ON", "")
                if len(utc) >= 4:
                    utc = f"{utc[:2]}:{utc[2:4]}"
                self.table.insert("", 0, iid=rid, values=(
                    qso.get("CALL", ""), utc,
                    f"{qso.get('RST_RCVD', '')} / {qso.get('RST_SENT', '')}",
                    "Ellenőrizendő – HARC" if item.get("uncertain", True) else "Hiba – HARC",
                    "↻ Újraküldés"), tags=("error",))
            self.log(f"Mentett sikertelen LOG-ok betöltve: {len(self.failed_uploads)}")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.log(f"Sikertelen LOG-ok betöltési hibája: {exc}")

    def on_table_click(self, event):
        if self.table.identify_region(event.x, event.y) != "cell":
            return
        if self.table.identify_column(event.x) != "#5":
            return
        rid = self.table.identify_row(event.y)
        if rid and rid in self.failed_uploads and self.table.set(rid, "action") == "↻ Újraküldés":
            self.retry_failed(rid)

    def retry_failed(self, record_id):
        failed = self.failed_uploads.get(record_id)
        if failed is None:
            return
        qso, reason, uncertain = failed
        if not self.callsign.get().strip() or not self.password.get():
            messagebox.showwarning("Hiányzó adatok", "Add meg a HARC belépési adatokat!")
            return
        if not self.upload_enabled.is_set():
            messagebox.showwarning("HARC leállítva", "Az újrapróbáláshoz előbb nyomd meg a START gombot.")
            return
        # A háttérben előbb LOGBOOK-ellenőrzés történik; nem küldünk vakon újra.
        self.pending_uploads[record_id] = qso.copy()
        self.table.set(record_id, "status", "Újrapróbálásra vár")
        self.table.set(record_id, "action", "")
        self.table.item(record_id, tags=())
        # A lemezen megőrizzük a bejegyzést a sikeres LOGBOOK-igazolásig.
        self.jobs.put((record_id, qso.copy(), self.callsign.get().strip().upper(),
                       self.password.get(), self.show_browser.get(), True))
        self.log(f"LOG ellenőrzése és szükség esetén újraküldése: {qso.get('CALL', '')}")

    def set_status_async(self, record_id, status):
        """A háttérszál állapotfrissítést kér a Tkinter főszálától."""
        self.messages.put(("harc_status", (record_id, status)))

    def log(self, message):
        """Időbélyeges eseményt helyez a naplózási sorba."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.messages.put(("log", f"[{timestamp}] {message}"))

    def betoltes_uzenetek(self):
        if not self.running or not self.betoltes_aktiv:
            return

        try:
            while True:
                kind, value = self.betoltes_messages.get_nowait()
                debug(f"Betöltő üzenetet fogadott: {kind}, érték: {value}")

                if kind == "updater_eredmeny":
                    version, error = value
                    if version:
                        self.frissites_kerdes(version)
                    elif error:
                        self.frissites_folytatas("Frissítés nem ellenőrizhető, program indítása.")
                    else:
                        self.frissites_folytatas("A program naprakész.")
                elif kind == "updater_telepites":
                    self.frissites_telepites(value)
                    return
                elif kind == "updater_hiba":
                    messagebox.showwarning("Frissítés", f"Nem sikerült letölteni a frissítést:\n{value}", parent=self.root)
                    self.frissites_folytatas("Frissítés sikertelen, program indítása.")
                elif kind == "lokator_frissites_kesz":
                    self.betoltes.feladat_kesz("lokator_frissites")

                elif kind == "hotelalfa_kesz":
                    self.hotelalfa_eredmeny_mentett = value
                    self.betoltes.feladat_kesz("hotelalfa")

        except queue.Empty:
            pass

        if self.betoltes_aktiv:
            self.root.after(100, self.betoltes_uzenetek)

    def process_messages(self):
        """A háttérszálak üzeneteinek feldolgozása a Tkinter főszálán."""

        while True:
            try:
                kind, value = self.messages.get_nowait()
            except queue.Empty:
                break
                
            if kind == "time_check":
                self.show_time_status(value)
                continue

            if kind == "qso":
                self.add_qso(value)

            elif kind == "udp_status":
                color = LIGHT_GREEN if "aktív" in value else LIGHT_RED
                self.bottom_status.config(text=value, fg=color)

            elif kind == "harc_status":
                record_id, status = value

                if self.table.exists(record_id):
                    self.table.set(record_id, "status", status)

                    # A táblázatsor színét a feltöltési állapot határozza meg.
                    if status == "Elküldve":
                        tags = ("sent",)
                    elif "Hiba" in status or "Ellenőrizendő" in status:
                        tags = ("error",)
                    elif "Kihagyva" in status:
                        tags = ("skipped",)
                    else:
                        tags = ()

                    self.table.item(record_id, tags=tags)

            elif kind == "harc_failed":
                record_id, reason, uncertain = value
                qso = self.pending_uploads.pop(record_id, None)
                if qso is not None:
                    self.failed_uploads[record_id] = (qso, reason, uncertain)
                self.log(f"HARC hiba ({record_id}): {reason}")
                if self.table.exists(record_id):
                    self.table.set(record_id, "action", "↻ Újraküldés")
                try:
                    self.save_failed_logs()
                except OSError as exc:
                    self.log(f"Sikertelen LOG mentési hiba: {exc}")

            elif kind == "harc_success":
                self.pending_uploads.pop(value, None)
                self.failed_uploads.pop(value, None)
                if self.table.exists(value):
                    self.table.set(value, "action", "")
                try:
                    self.save_failed_logs()
                except OSError as exc:
                    self.log(f"Sikertelen LOG mentési hiba: {exc}")

            elif kind == "sent_count":
                self.sent_count += 1
                self.sent_label.config(text=str(self.sent_count))

            elif kind == "error_count":
                self.error_count += 1
                self.error_label.config(text=str(self.error_count))

            elif kind == "log":
                # A szövegdobozt csak az új üzenet beszúrására nyitjuk meg.
                self.output.config(state="normal")
                self.output.insert("end", value + "\n")
                self.output.see("end")
                self.output.config(state="disabled")

        # A Tkinter 100 ms múlva ismét ellenőrzi az üzenetsort.
        if self.running:
            self.root.after(100, self.process_messages)

    def close(self):
        """Leállítja az új feltöltéseket és bezárja az alkalmazást."""

        self.upload_enabled.clear()
        self.running = False
        if getattr(self, "mqtt_locator", None):
            try:
                self.mqtt_locator.stop()
            except Exception as exc:
                print(f'MQTT leállítási hiba: {exc}')
        self.root.destroy()


