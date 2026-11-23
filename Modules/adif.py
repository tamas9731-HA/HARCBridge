import re

# ============================================================
# ADIF FELDOLGOZÁS
# ============================================================

def parse_adif(data):
    """Az ADIF bájtsorozatot Python szótárrá alakítja."""

    result = {}

    # Ha van ADIF fejléc, átugorjuk.
    header = re.search(rb"<EOH\s*>", data, re.I)
    if header:
        data = data[header.end():]

    # ADIF mező például: <CALL:6>EA5IKP
    # A 6 a mező értékének bájthossza.
    pattern = re.compile(rb"<([^<>:]+):(\d+)(?::[^<>]*)?>", re.I)
    pos = 0

    while True:
        match = pattern.search(data, pos)
        if not match:
            break

        name = match.group(1).decode("ascii", errors="replace").upper()
        length = int(match.group(2))
        start = match.end()
        end = start + length

        # Hiányos mező esetén nem próbálunk tovább olvasni.
        if end > len(data):
            break

        result[name] = data[start:end].decode("utf-8", errors="replace").strip()
        pos = end

    return result


def extract_qso(packet):
    """A WSJT-CB 12-es típusú UDP üzenetéből kiolvassa az ADIF logot."""

    if len(packet) < 20:
        return None

    # WSJT protokollazonosító (magic number)
    if int.from_bytes(packet[:4], "big") != 0xADBCCBDA:
        return None

    # Csak a Logged ADIF üzenettípus érdekel.
    if int.from_bytes(packet[8:12], "big") != 12:
        return None

    pos = 12

    # Az alkalmazás azonosítójának hossza.
    sender_len = int.from_bytes(packet[pos:pos + 4], "big")
    pos += 4

    # A Qt 0xFFFFFFFF értéke null adatot jelent.
    if sender_len == 0xFFFFFFFF or pos + sender_len + 4 > len(packet):
        return None

    # Átugorjuk az alkalmazás azonosítóját.
    pos += sender_len

    # A következő mező maga az ADIF bájtsorozat.
    data_len = int.from_bytes(packet[pos:pos + 4], "big")
    pos += 4

    if data_len == 0xFFFFFFFF or pos + data_len > len(packet):
        return None

    adif_data = packet[pos:pos + data_len]

    #print("NYERS UDP ADIF:", repr(adif_data))

    return parse_adif(adif_data)


def make_comment(qso):
    """A HARC megjegyzés összeállítása: RX + TX + WSJT-CB COMMENT."""

    rx = qso.get("RST_RCVD", "").strip()
    tx = qso.get("RST_SENT", "").strip()
    comment = qso.get("COMMENT", "").strip()

    parts = []
    if rx:
        parts.append(f"Rcvd: {rx}")
    if tx:
        parts.append(f"Sent: {tx}")

    result = "AutoLog |  " + " ".join(parts)

    # A felhasználói megjegyzést csak akkor adjuk hozzá, ha nem üres.
    if comment:
        result = f"{result} | {comment}" if result else comment

    return result

