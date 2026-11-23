import socket
from .config import UDP_IP, UDP_PORT, FORWARD_IP, FORWARD_PORT
from .adif import extract_qso

class UDPListenerMixin:
    def listen_udp(self):
        """WSJT-CB UDP fogadás és továbbítás a LOG11DX felé."""

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(1)

        # Külön socket az UDP-csomagok továbbításához.
        forward_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        forwarded_qsos = set()  # LOG11DX: ugyanazt a naplózott QSO-t csak egyszer küldjük.

        try:
            sock.bind((UDP_IP, UDP_PORT))
            self.messages.put(("udp_status", f"● UDP aktív: {UDP_IP}:{UDP_PORT}"))
            self.log(f"WSJT-CB UDP figyelés: {UDP_PORT}")
            self.log(f"LOG11DX UDP továbbítás: {FORWARD_IP}:{FORWARD_PORT}")

            while self.running:
                try:
                    packet, _ = sock.recvfrom(65535)
                except socket.timeout:
                    continue

                qso = extract_qso(packet)
                # A nem QSO típusú WSJT-X csomagokat változatlanul továbbítjuk.
                # QSO esetén az ismételt UDP logcsomagokat kiszűrjük.
                should_forward = True
                qso_key = None
                if qso and qso.get("CALL"):
                    qso_key = (
                        qso.get("CALL", ""), qso.get("QSO_DATE", ""),
                        qso.get("TIME_ON", ""), qso.get("MODE", "")
                    )
                    should_forward = qso_key not in forwarded_qsos

                if self.forward_log11dx_enabled.is_set() and should_forward:
                    try:
                        forward_sock.sendto(packet, (FORWARD_IP, FORWARD_PORT))
                        if qso_key is not None:
                            forwarded_qsos.add(qso_key)
                    except OSError as e:
                        self.log(f"LOG11DX továbbítási hiba: {e}")
                if qso and qso.get("CALL"):
                    self.messages.put(("qso", qso))

        except OSError as e:
            self.log(f"UDP hiba: {e}")
            self.messages.put(("udp_status", f"● UDP hiba: {e}"))

        finally:
            sock.close()
            forward_sock.close()


