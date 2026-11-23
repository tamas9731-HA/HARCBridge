import tkinter as tk
import sys
from pathlib import Path

class Betoltes:
    def __init__(self, root, kesz_callback):
        self.root = root
        self.kesz_callback = kesz_callback
   
        self.keret = tk.Frame(self.root, bg="#000000")
        self.keret.pack(fill="both", expand=True)
        
        self.feladatok = {
            "lokator": False,
            "lokator_frissites": False,
            "hotelalfa": False,
            "log11dx": False,
            "ido": False,
            "updater": False
        }        
        self.betoltes_kesz = False
        self.minimum_ido_letelt = False
        self.root.after(2000, self.minimum_ido_vege)

        self.tartalom = tk.Frame(self.keret, bg="#000000")
        self.tartalom.pack(expand=True)

        app_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
        logo_path = app_dir / "Images" / "logo.png"
        self.logo_kep = tk.PhotoImage(file=str(logo_path)).subsample(5, 5)

        self.felirat = tk.Label(self.tartalom, text="HARC BRIDGE V0.2\nAdatok betöltése...", bg="#000000", fg="white",font=("Segoe UI", 18, "bold"))
        self.felirat.pack(expand=True)

        self.vaszon = tk.Canvas(self.tartalom, width=50, height=50, bg="#000000", highlightthickness=0)
        self.vaszon.pack(pady=(15, 0))
        
        self.karika = self.vaszon.create_arc(5, 5, 45, 45,start=0,extent=270,style="arc",outline="#00BFFF",width=4)
        self.forgatas()
                
        self.logo = tk.Label(self.tartalom, image=self.logo_kep, bg="#000000")
        self.logo.pack(side="top", pady=(0, 5), before=self.felirat)

        self.frissites_allapot = tk.Label(self.tartalom, text="Frissítések ellenőrzése...", bg="#000000", fg="#00BFFF", font=("Segoe UI", 10))
        self.frissites_allapot.pack(before=self.felirat, pady=(0, 8))

    def feladat_kesz(self, nev):
        self.feladatok[nev] = True
        #print(f"\033[92m[BETÖLTÉS] {nev} kész\033[0m")
        #print(f"\033[96m[BETÖLTÉS] Állapotok: {self.feladatok}\033[0m")
        self.ellenorzes()

    def forgatas(self):
        if self.betoltes_kesz:
            return

        szog = float(self.vaszon.itemcget(self.karika, "start"))
        self.vaszon.itemconfigure(self.karika, start=(szog - 10) % 360)
        self.root.after(30, self.forgatas)

    def minimum_ido_vege(self):
        self.minimum_ido_letelt = True
        self.ellenorzes()

    def ellenorzes(self):
        if all(self.feladatok.values()) and self.minimum_ido_letelt:
            if not self.betoltes_kesz:
                self.betoltes_kesz = True
                self.keret.destroy()
                self.kesz_callback()
    
if __name__ == "__main__":
    ablak = tk.Tk()
    ablak.geometry("850x650")
    betoltes = Betoltes(ablak)
    ablak.mainloop()
