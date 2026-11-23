"""BaseMaker alapadatbázis + helyi QRA gyorsítótár (TOML, szálbiztos)."""
import os
import re
import sys
import threading
import tomllib
from pathlib import Path

GRID_RE = re.compile(r'^[A-R]{2}[0-9]{2}[A-X]{2}$', re.I)
CALL_RE = re.compile(r'^[A-Z0-9/]{2,24}$', re.I)

class LocatorDatabase:
    def __init__(self, directory=None):
        # Telepített EXE-nél a PyInstaller a modulokat az _internal mappába teszi.
        # Az adatfájlok viszont az EXE mellett, a Locator mappában vannak.
        app_dir = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent.parent
        self.directory = Path(directory) if directory else app_dir / 'Locator'
        self.lock = threading.RLock()
        self.base = {}
        self.local = {}
        self.conflicts = {}

    @staticmethod
    def _read(path, section):
        if not path.exists():
            return {}
        with path.open('rb') as f:
            data = tomllib.load(f).get(section, {})
        if not isinstance(data, dict):
            raise ValueError(f'Hibás [{section}] szakasz: {path.name}')
        return data

    def load(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        base = self._read(self.directory / 'locators_base.tom', 'locators')
        local = self._read(self.directory / 'locators.tom', 'locators')
        conflicts = self._read(self.directory / 'locators_conflicts.tom', 'conflicts')
        def clean(d):
            return {str(k).upper(): str(v).upper() for k,v in d.items()
                    if CALL_RE.fullmatch(str(k).upper()) and GRID_RE.fullmatch(str(v).upper())}
        with self.lock:
            self.base = clean(base)
            self.local = clean(local)
            self.conflicts = {}
            for key, value in conflicts.items():
                call = str(key).upper()
                if not CALL_RE.fullmatch(call):
                    continue
                # Régi, listás konfliktusok migrálása (az első eltérés 1 alkalom).
                if isinstance(value, list):
                    grids = [str(v).upper() for v in value if GRID_RE.fullmatch(str(v))]
                    if grids:
                        self.conflicts[call] = {'locator': grids[-1], 'occurrences': 1}
                elif isinstance(value, dict):
                    grid = str(value.get('locator', '')).upper()
                    count = value.get('occurrences', 0)
                    if GRID_RE.fullmatch(grid) and type(count) is int and 1 <= count <= 3:
                        self.conflicts[call] = {'locator': grid, 'occurrences': count}
        return len(self.base) + len(set(self.local) - set(self.base))

    def find(self, callsign):
        key = callsign.strip().upper()
        with self.lock:
            return self.local.get(key) or self.base.get(key) or ''

    def _save(self, filename, section, values):
        path = self.directory / filename
        tmp = path.with_suffix('.tmp')
        with tmp.open('w', encoding='utf-8', newline='\n') as f:
            f.write(f'[{section}]\n')
            for call, value in sorted(values.items()):
                if isinstance(value, set):
                    formatted = '[' + ', '.join('"' + v + '"' for v in sorted(value)) + ']'
                else:
                    formatted = '"' + value + '"'
                f.write(f'"{call}" = {formatted}\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    def _save_conflicts(self):
        """Konfliktusok új TOML szerkezetben, atomikus fájlcserével."""
        path = self.directory / 'locators_conflicts.tom'
        tmp = path.with_suffix('.tmp')
        with tmp.open('w', encoding='utf-8', newline='\n') as f:
            for call, entry in sorted(self.conflicts.items()):
                f.write(f'["conflicts"."{call}"]\n')
                f.write(f'locator = "{entry["locator"]}"\n')
                f.write(f'occurrences = {entry["occurrences"]}\n\n')
            if not self.conflicts:
                f.write('[conflicts]\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    def _replace_base_grid(self, call, old, new):
        """Csak a konkrét értéket írja át, a teljes base fájlt nem formázza újra."""
        path = self.directory / 'locators_base.tom'
        original = path.read_bytes()
        # Megőrizzük a BOM-ot, sorvégeket, sorrendet, kommenteket.
        pattern = re.compile(
            rb'(?m)^(\s*"' + re.escape(call.encode('ascii')) +
            rb'"\s*=\s*")' + re.escape(old.encode('ascii')) + rb'("(?=\s*(?:#.*)?$))'
        )
        updated, count = pattern.subn(lambda m: m.group(1) + new.encode('ascii') + m.group(2), original)
        if count != 1:
            raise ValueError(f'Nem található egyértelmű base rekord: {call}')
        tmp = path.with_suffix('.tmp')
        tmp.write_bytes(updated)
        os.replace(tmp, path)

    def observe(self, callsign, grid):
        call, grid = str(callsign).strip().upper(), str(grid).strip().upper()
        if not CALL_RE.fullmatch(call) or not GRID_RE.fullmatch(grid):
            return None
        with self.lock:
            # A helyi bejegyzés elsőbbséget élvez; így a Bridge csak
            # a saját lokátorát módosítja, ha mindkét helyen szerepel.
            current = self.local.get(call) or self.base.get(call)
            if current is None:
                self.local[call] = grid
                self._save('locators.tom', 'locators', self.local)
                return 'new'
            if current == grid:
                if call in self.conflicts:
                    del self.conflicts[call]
                    self._save_conflicts()
                return None

            entry = self.conflicts.get(call)
            if entry is not None and entry['locator'] == grid:
                count = entry['occurrences'] + 1
            else:
                count = 1
            if count < 3:
                self.conflicts[call] = {'locator': grid, 'occurrences': count}
                self._save_conflicts()
                return 'conflict'

            # Csak a sikeres adatbázis-módosítás után töröljük a konfliktust.
            if call in self.local:
                self.local[call] = grid
                try:
                    self._save('locators.tom', 'locators', self.local)
                except Exception:
                    self.local[call] = current
                    raise
            else:
                self._replace_base_grid(call, current, grid)
                self.base[call] = grid
            del self.conflicts[call]
            self._save_conflicts()
            return 'replaced'

    def save(self):
        with self.lock:
            self._save('locators.tom', 'locators', self.local)
            self._save_conflicts()
