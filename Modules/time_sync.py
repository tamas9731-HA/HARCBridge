"""NTP-alapú órapontosság-ellenőrzés, rendszeróra módosítása nélkül."""
from datetime import datetime, timezone
import ntplib
from .config import debug


def check_time():
    try:
        response = ntplib.NTPClient().request("pool.ntp.org", version=3, timeout=3)
        debug(f"Időeltérés: {response.offset:+.3f} másodperc")
        debug(f"NTP idő: {datetime.fromtimestamp(response.tx_time, timezone.utc)}")
        return response.offset
    except Exception as error:
        debug(f"Nem sikerült lekérni a pontos időt: {error}")
        return None

