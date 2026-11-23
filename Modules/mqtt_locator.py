"""Folyamatos 11m MQTT figyelés; a HARC START/STOP-tól függetlenül fut."""
import json
import re
import ssl
import threading
import time

import paho.mqtt.client as mqtt

from . import config

try:
    import certifi
except ImportError:
    certifi = None

HOST = 'mqtt.pskreporter.info'
PORT = 1884
TOPIC = 'pskr/filter/v2/11m/#'
CB_CALL_RE = re.compile(r'^[0-9]+[A-Z]+[0-9]+$', re.I)
GRID_RE = re.compile(r'^[A-R]{2}[0-9]{2}(?:[A-X]{2})?$', re.I)


def reports(data):
    if isinstance(data, list):
        for item in data:
            yield from reports(item)
    elif isinstance(data, dict):
        if any(k in data for k in ('sc', 'rc', 'senderCallsign', 'receiverCallsign')):
            yield data
        for key in ('reports', 'spots', 'data'):
            if key in data and isinstance(data[key], (dict, list)):
                yield from reports(data[key])


class MQTTLocator:
    def __init__(self, database, log):
        self.database = database
        self.log = log
        self.stop_event = threading.Event()
        self.thread = None
        self.client = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._run, name='BridgeMQTT', daemon=True)
        self.thread.start()

    def _run(self):
        delay = 60
        while not self.stop_event.is_set():
            client = None
            try:
                client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
                self.client = client

                def on_connect(c, userdata, flags, reason_code, properties):
                    if reason_code == 0 and not self.stop_event.is_set():
                        result, mid = c.subscribe(TOPIC)
                        self.log(f'MQTT kapcsolódva (TLS, {PORT}), feliratkozás: {TOPIC} (eredmény={result}, mid={mid})')
                    else:
                        self.log(f'MQTT kapcsolódási válasz: {reason_code}')

                def on_subscribe(c, userdata, mid, reason_codes, properties):
                    self.log(f'MQTT feliratkozás visszaigazolva: mid={mid}, válasz={reason_codes}')

                def on_message(c, userdata, msg):
                    if self.stop_event.is_set():
                        return
                    try:
                        payload = json.loads(msg.payload.decode('utf-8'))
                        if config.DEBUGMODE:
                            self.log(f'MQTT DEBUG üzenet: topic={msg.topic}, payload={payload!r}')
                        for record in reports(payload):
                            if config.DEBUGMODE:
                                self.log(f'MQTT DEBUG riport: {record!r}')
                            for call, grid in ((record.get('sc') or record.get('senderCallsign'), record.get('sl') or record.get('senderLocator') or record.get('senderGrid')),
                                               (record.get('rc') or record.get('receiverCallsign'), record.get('rl') or record.get('receiverLocator') or record.get('receiverGrid'))):
                                if not call or not grid:
                                    continue
                                if not CB_CALL_RE.fullmatch(str(call).strip()) or not GRID_RE.fullmatch(str(grid).strip()):
                                    continue
                                # A helyi adatbázis jelenleg 6 karakteres Maidenhead-lokátort tárol.
                                if len(str(grid).strip()) != 6:
                                    continue
                                # Az alapadatbázisban már szereplő hívójeleket
                                # ne tekintsük új MQTT találatnak a naplóban.
                                normalized_call = str(call).strip().upper()
                                with self.database.lock:
                                    already_in_base = normalized_call in self.database.base
                                result = self.database.observe(call, grid)
                                # Csak az új, sikeresen locators.tom-ba mentett QRA-t naplózzuk.
                                # A konfliktusokat és a meglévő adatok módosítását nem.
                                if result == 'new' and not already_in_base:
                                    self.log(f'MQTT új QRA mentve: {call} -> {grid}')
                                elif result == 'conflict':
                                    self.log(f'MQTT lokátoreltérés (ellenőrzés alatt): {call} -> {grid}')
                                elif result == 'replaced':
                                    self.log(f'MQTT lokátor frissítve: {call} -> {grid}')
                    except Exception as exc:
                        self.log(f'MQTT üzenet feldolgozási hiba: {exc}')

                client.on_connect = on_connect
                client.on_message = on_message
                client.on_subscribe = on_subscribe
                if certifi is not None:
                    client.tls_set(ca_certs=certifi.where(), cert_reqs=ssl.CERT_REQUIRED)
                else:
                    client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
                self.log(f'MQTT kapcsolódás indítása: {HOST}:{PORT}, TLS bekapcsolva')
                client.connect(HOST, PORT, keepalive=60)
                delay = 60
                # A loop_forever visszatér hibánál; saját késleltetett újrapróbálkozás.
                client.loop_forever(retry_first_connection=False)
            except Exception as exc:
                if not self.stop_event.is_set():
                    self.log(f'MQTT kapcsolat hiba: {exc}')
            finally:
                if client is not None:
                    try:
                        client.disconnect()
                    except Exception:
                        pass
                self.client = None
            if not self.stop_event.is_set():
                self.log(f'MQTT újracsatlakozás {delay} másodperc múlva.')
                self.stop_event.wait(delay)
                delay = min(delay * 2, 1800)

    def stop(self):
        self.stop_event.set()
        client = self.client
        if client is not None:
            try:
                client.disconnect()  # MQTT DISCONNECT csomag
            except Exception:
                pass
        if self.thread is not None:
            self.thread.join(timeout=5)
        self.database.save()
