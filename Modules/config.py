# ============================================================
# ÁLLANDÓK ÉS BEÁLLÍTÁSOK
# ============================================================

# HARC weboldalak
HARC_URL = "https://hotelalfa.hu"
LOGIN_URL = "https://hotelalfa.hu/cluster/index.php"
SPOT_URL = "https://hotelalfa.hu/cluster/log_sendspot.php"
LOG_URL = "https://hotelalfa.hu/cluster/log_sendspot_any.php"
LOGOUT_URL = "https://hotelalfa.hu/cluster/logout.php"

# WSJT-CB UDP kapcsolat
UDP_IP = "127.0.0.1"
UDP_PORT = 2237

FORWARD_IP = "127.0.0.1"
FORWARD_PORT = 2238

# Windows hitelesítőadat-tároló azonosítói
SERVICE = "HARC_Log_Bridge"
ACCOUNT_KEY = "saved_callsign"

# A HARC spotban használt fix adatok
HARC_FREQ = "27265"
HARC_MODE = "FT8"
HARC_WORKED = "WKD"

# Grafikus felület színei
BG = "#101B2B"             # Fő háttér
PANEL = "#1B2C40"          # Panelek
INPUT_BG = "#263A50"       # Mezők, táblázatfejléc
FG = "#F2F7FC"             # Világos szöveg
MUTED = "#A4B7CC"          # Halvány szöveg
GREEN = "#16865B"          # START gomb
RED = "#B83C46"            # STOP gomb
BLUE = "#267DB3"           # Kiemelés
LIGHT_GREEN = "#65E6B0"    # Sikeres állapot
LIGHT_RED = "#FF8D88"      # Hibaállapot

# QRA lokátorok: csak megfelelő adatfelhasználási engedéllyel kapcsold be.
ENABLE_LOCATORS = True

#DEBUG mód
DEBUGMODE = False

def debug(message):
    if DEBUGMODE:
        print(f"[DEBUG] {message}")
