import re
import tomllib
import sys
from pathlib import Path
from .config import debug


# 11 m-es hívójelek: szám + betű(k) + szám (pl. 109HA9731).
# Az amatőr hívójelek, perjeles és egyéb formátumok nem maradnak meg.
CB_CALL_RE = re.compile(r"^[0-9]+[A-Z]+[0-9]+$", re.IGNORECASE)


def clean_user_locators(path):
    """Csak NEW_locators frissítéskor tisztítja a személyes locators.tom fájlt.
    Megőrzi a többi szekciót, kommentet és a 11 m-es bejegyzések sorait.
    """
    if not path.exists():
        return 0
    content = path.read_text(encoding="utf-8-sig")
    lines = content.splitlines(keepends=True)
    in_locators = False
    removed = 0
    output = []
    for line in lines:
        section = re.match(r"^\s*\[([^]\r\n]+)\]\s*(?:#.*)?$", line)
        if section:
            in_locators = section.group(1).strip() == "locators"
        if in_locators:
            entry = re.match(r'^\s*(?:"([^"]+)"|\'([^\']+)\'|([A-Za-z0-9_/-]+))\s*=', line)
            if entry:
                callsign = next(v for v in entry.groups() if v is not None).strip()
                if not CB_CALL_RE.fullmatch(callsign):
                    removed += 1
                    continue
        output.append(line)
    if removed:
        tmp = path.with_suffix(".tmp")
        tmp.write_text("".join(output), encoding="utf-8")
        tmp.replace(path)
    return removed


def check_locators_update(callback=None):
    
    app_dir = (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parent.parent
    )

    base_path = app_dir / "Locator" / "locators_base.tom"
    user_path = app_dir / "Locator" / "locators.tom"
    
    with base_path.open("r", encoding="utf-8-sig") as file:
        header = file.readline().strip()

    if header == "[NEW_locators]":
        
        with base_path.open("rb") as file: #Beolvassa a base-t
            base = tomllib.load(file)
            
        if user_path.exists():#Ha létezik az user_path fájl akkor beolvassuk az user dict szótárba
            with user_path.open("rb") as file:
                user = tomllib.load(file)
        else:
            user = {"locators": {}}#Ha nincs beolvasható adat, akkor egy üres szótárat adunk neki
            debug("Nincs felhasználói adatbázis, üres szótár használata.")
        
    
        # A régi, teljes amatőrsávos gyűjtésből származó hívójeleket
        # kizárólag az új bázis érkezésekor távolítjuk el.
        removed_user = clean_user_locators(user_path)
        user_locators = {
            call: locator for call, locator in user.get("locators", {}).items()
            if CB_CALL_RE.fullmatch(str(call).strip())
        }
        debug(f"Felhasználói amatőr/nem CB hívójelek törölve: {removed_user}")

        debug("Frissített bázis, összehasonlítás szükséges")
        
        base_locators = {
            call: locator for call, locator in base["NEW_locators"].items()
            if CB_CALL_RE.fullmatch(str(call).strip())
        }
        
        debug(len(base_locators))
        debug(len(user_locators))
        
        duplicates = []

        for callsign in user_locators:
            if callsign in base_locators:
                duplicates.append(callsign) #Hozzáadjuk a listához azokat a hívójeleket amik duplikáltak, kétszer vannak

        debug(f"Duplikált hívójelek száma: {len(duplicates)}")
        
        for callsign in duplicates:
            del base_locators[callsign] #A duplikáltakat töröljük a base-ből de még csak a memóriából

        debug(f"Törölt duplikációk: {len(duplicates)}")
        debug(f"Base megmaradt hívójelei: {len(base_locators)}")
        
        lines = ["[locators]\n"] #Új lista fix fejléc névvel

        for callsign, locator in base_locators.items():
            lines.append(f'"{callsign}" = "{locator}"\n') #A listához hozzá adjuk a hívójel = lokátor kombinációt
            
        debug(f"Mentésre előkészített sorok: {len(lines)}")
        
        temp_path = base_path.with_suffix(".tmp") #Csinálunk egy tmp fájlt

        with temp_path.open("w", encoding="utf-8") as file:
            file.writelines(lines)#Soronként bele írjuk a tmp fájlba

        debug("Ideiglenes adatbázis sikeresen létrehozva")       

        temp_path.replace(base_path)

        debug("Lokátoradatbázis sikeresen frissítve!")        
    else:
        debug("Lokátor adatok már frissítésre kerültek egyszer.")   

    if callback:
        callback()        
