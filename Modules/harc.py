"""HARC HTTP kliens – Playwright/Chromium nélkül.

A HARC szerver űrlapjának tényleges POST célpontját és visszajelzését
éles teszttel kell megerősíteni. Bizonytalan beküldésnél nincs automatikus újrapróba.
"""
import queue
import time
from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlparse
from datetime import datetime
import requests
from .config import HARC_URL, LOGIN_URL, SPOT_URL, LOG_URL, LOGOUT_URL, HARC_FREQ, HARC_MODE, HARC_WORKED, ENABLE_LOCATORS, debug
from .adif import make_comment

class Forms(HTMLParser):
    def __init__(self):
        super().__init__(); self.forms=[]; self.current=None; self.select=None
    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if tag=='form':
            self.current={'action':a.get('action',''),'method':a.get('method','get').lower(),'fields':{},'names':set()}; self.forms.append(self.current)
        elif self.current is not None:
            if tag in ('input','button','textarea','select') and a.get('name'):
                name=a['name']; self.current['names'].add(name)
                if tag=='input' and a.get('type','').lower() in ('checkbox','radio') and 'checked' not in a: return
                if tag=='input' and a.get('type','').lower()=='file': return
                self.current['fields'][name]=a.get('value','')
            if tag=='select': self.select=a.get('name')
            if tag=='option' and self.select and 'selected' in a:
                self.current['fields'][self.select]=a.get('value','')
    def handle_endtag(self,tag):
        if tag=='form': self.current=None; self.select=None
        if tag=='select': self.select=None

class LogbookParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sorok = []
        self.sor = None
        self.cella = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.sor = []

        elif tag in ("td", "th") and self.sor is not None:
            self.cella = []

    def handle_data(self, data):
        if self.cella is not None:
            self.cella.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cella is not None:
            self.sor.append(" ".join("".join(self.cella).split()))
            self.cella = None

        elif tag == "tr" and self.sor is not None:
            self.sorok.append(self.sor)
            self.sor = None

def get_form(html, required):
    parser=Forms(); parser.feed(html)
    for form in parser.forms:
        if set(required).issubset(form['names']): return form
    raise RuntimeError('A várt HARC űrlap nem található; lehet, hogy változott a weboldal')

def same_host(url):
    return urlparse(url).hostname == urlparse(LOGIN_URL).hostname and urlparse(url).scheme=='https'

def submit_form(session, base, form, values, timeout=30):
    url=urljoin(base,form['action'] or base)
    if not same_host(url): raise RuntimeError('Váratlan űrlap-célpont; a beküldés megszakítva')
    payload=dict(form['fields']); payload.update(values)
    if form['method']=='post': return session.post(url,data=payload,timeout=timeout)
    return session.get(url,params=payload,timeout=timeout)

class HarcMixin:
    
    def check_hotelalfa_site(self):
        try:
            response = requests.get(HARC_URL, timeout = 5)

            if response.status_code >= 200 and response.status_code < 300:
                debug("HARC LOG CLUSTER: Elérhető")
                return True
            else:
                debug("HARC LOG CLUSTER: Nem elérhető")
                return False
        except:
            debug("Hiba a hotelalfa.hu check közben")
            return False
            
    def web_queue_worker(self):
        while self.running:
            try: job=self.jobs.get(timeout=1)
            except queue.Empty: continue
            try:
                record_id=job[0]
                if not self.upload_enabled.is_set(): self.set_status_async(record_id,'Kihagyva (STOP)')
                else: self.web_worker(*job)
            finally: self.jobs.task_done()

    def web_worker(self, record_id, qso, call, password, visible=False, retry=False):
        submitted=False; stage='kapcsolódás'; session=requests.Session()
        session.headers.update({'User-Agent':'HARCBridge/0.1 (HTTP)','Accept':'text/html,application/xhtml+xml'})
        try:
            self.set_status_async(record_id,'Kapcsolódás...')
            r=session.get(LOGIN_URL,timeout=30); 
            r.raise_for_status()
            stage='bejelentkezés'
            login=get_form(r.text,('myusername','mypassword'))
            r=submit_form(session,r.url,login,{'myusername':call,'mypassword':password})
            r.raise_for_status()
            stage='beküldő felület'

            r = session.get(LOG_URL, timeout=30)
            r.raise_for_status()

            if not same_host(r.url):
                raise RuntimeError("Váratlan átirányítás")

            log_form = get_form(
                r.text,
                (
                    "ev_be", "ho_be", "nap_be",
                    "ora_be", "perc_be",
                    "dx", "qrg", "mode", "wkd",
                    "txloc", "rxloc", "comment"
                )
            )

            dx = qso["CALL"].strip().upper()
            comment = make_comment(qso)
            rxloc = self.locator_db.find(dx) if ENABLE_LOCATORS else ""

            # A HARC profilból kiolvasott TX-lokátor
            txloc = log_form["fields"].get("txloc", "")

            # A QSO első feldolgozásakor eltett helyi idő; újrapróbáláskor változatlan.
            helyi_ido = qso.get("_LOG_LOCAL_TIME")
            if not helyi_ido:
                helyi_ido = datetime.now().strftime("%Y-%m-%d %H:%M")
                qso["_LOG_LOCAL_TIME"] = helyi_ido
            most = datetime.strptime(helyi_ido, "%Y-%m-%d %H:%M")

            values = {
                "ev_be": most.strftime("%Y"),
                "ho_be": most.strftime("%m"),
                "nap_be": most.strftime("%d"),
                "ora_be": most.strftime("%H"),
                "perc_be": most.strftime("%M"),
                "dx": dx,
                "qrg": HARC_FREQ,
                "mode": HARC_MODE,
                "wkd": HARC_WORKED,
                "txloc": txloc,
                "rxloc": rxloc,
                "comment": comment
            }

            debug(f"LOG adatok: {values}")

            if not self.upload_enabled.is_set():
                self.set_status_async(record_id, "Kihagyva (STOP)")
                return


            # Ismételt küldés előtt előbb megnézzük, nem került-e már be.
            if retry:
                stage = "újraküldés előtti LOGBOOK-ellenőrzés"
                self.set_status_async(record_id, "LOGBOOK ellenőrzése...")
                check = session.get("https://hotelalfa.hu/cluster/log_logbook.php", timeout=30)
                check.raise_for_status()
                if urlparse(check.url).path != "/cluster/log_logbook.php":
                    raise RuntimeError("Nem érhető el a bejelentkezett LOGBOOK")
                old_parser = LogbookParser()
                old_parser.feed(check.text)
                stamp = most.strftime("%Y-%m-%d %H:%M")
                if any(len(row) >= 2 and row[0] == stamp and row[1].upper() == dx
                       for row in old_parser.sorok):
                    self.set_status_async(record_id, "Elküldve")
                    self.messages.put(("harc_success", record_id))
                    self.messages.put(("sent_count", None))
                    self.log(f"LOG már megtalálható, újraküldés nélkül: {dx}")
                    return

            stage = "beküldés"
            submitted = True
            self.set_status_async(record_id,'Küldés...')
            r = submit_form(session, r.url, log_form, values, timeout=30)
            r.raise_for_status()
            
            logbook_url = "https://hotelalfa.hu/cluster/log_logbook.php"
            
            time.sleep(1)
            logbook = session.get(logbook_url, timeout=30)
            logbook.raise_for_status()
            if urlparse(logbook.url).path != "/cluster/log_logbook.php":
                raise RuntimeError("Nem érhető el a bejelentkezett LOGBOOK")
            
            parser = LogbookParser()
            parser.feed(logbook.text)

            debug(f"LOGBOOK sorok száma: {len(parser.sorok)}")
            
            keresett_dx = dx.upper()

            keresett_datum = (
                f"{values['ev_be']}-{values['ho_be']}-{values['nap_be']} "
                f"{values['ora_be']}:{values['perc_be']}"
            )

            talalat = False #talalat változó hogy van-e ilyen qso a logbookban

            for sor in parser.sorok:
                if len(sor) >= 2:
                    if sor[0] == keresett_datum and sor[1].upper() == keresett_dx:
                        talalat = True
                        break

            debug(f"\033[92mKeresett QSO: {keresett_dx} | {keresett_datum}")
            debug(f"LOGBOOK találat: {talalat}")

            debug(f"LOGBOOK HTTP: {logbook.status_code}")
            debug(f"LOGBOOK URL: {logbook.url}")
            
            
            debug(f"LOG válasz HTTP: {r.status_code}")
            debug(f"LOG végső URL: {r.url} \033[0m")

            for item in r.history:
                debug(f"LOG átirányítás: {item.status_code} -> {item.url}")
          
            
            if talalat:
                self.set_status_async(record_id, 'Elküldve')
                self.messages.put(('harc_success', record_id))
                self.messages.put(('sent_count', None))
                self.log(f'HARC feltöltés sikeres: {dx}')
            else:
                self.set_status_async(record_id, 'Ellenőrizendő – HARC')
                self.messages.put(('harc_failed', (
                    record_id,
                    'A QSO nem található a HARC LOGBOOK-ban; ellenőrizni kell.',
                    True,
                )))
                self.log('A beküldés eredménye ellenőrizendő a HARC-on; automatikus újrapróba nincs.')
        except Exception as e:
            detail=str(e).splitlines()[0][:220]
            status=('Ellenőrizendő – HARC' if submitted else 'Hiba – '+ ('kapcsolat' if stage=='kapcsolódás' else 'belépés' if stage=='bejelentkezés' else 'űrlap'))
            reason=f'HARC HTTP hiba ({stage}): {detail}'
            self.log(reason); self.set_status_async(record_id,status)
            self.messages.put(('harc_failed',(record_id,reason,submitted)))
            self.messages.put(('error_count',None))
        finally:
            try: session.get(LOGOUT_URL,timeout=10)
            except requests.RequestException: pass
            session.close()
