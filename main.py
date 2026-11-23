import tkinter as tk
from pathlib import Path
import sys

def set_window_icon(root):
    # Az ablak/tálca ikonja az EXE melletti HARCBridge.ico fájlból.
    base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    icon = base / "HARCBridge.ico"
    if icon.is_file():
        try:
            root.iconbitmap(default=str(icon))
        except tk.TclError as exc:
            print(f"[IKON] Nem sikerült beállítani: {exc}")

from Modules.gui import HARCBridge
from Modules.locator_updater import check_locators_update
from Modules.time_sync import check_time

if __name__ == "__main__":
    root = tk.Tk()
    set_window_icon(root)
    app = HARCBridge(root)
    #root.after(100, check_locators_update)#Lokátor frissítés nézet, még a program indulás elején (locator_updater.py)
    #root.after(200, app.start_time_check)
    root.mainloop()
