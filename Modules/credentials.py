import keyring
from tkinter import messagebox
from .config import SERVICE, ACCOUNT_KEY

class CredentialsMixin:
    def save_credentials(self):
        """A HARC belépési adatokat a Windows hitelesítőadat-tárolójába menti."""

        call = self.callsign.get().strip().upper()
        password = self.password.get()

        if not call or not password:
            messagebox.showwarning("Hiányzó adatok", "Add meg a hívójelet és a jelszót!")
            return

        try:
            old_call = keyring.get_password(SERVICE, ACCOUNT_KEY)

            # A jelszó a hívójelhez tartozik.
            keyring.set_password(SERVICE, call, password)
            keyring.set_password(SERVICE, ACCOUNT_KEY, call)

            # Ha megváltozott a hívójel, a régi bejegyzést töröljük.
            if old_call and old_call != call:
                try:
                    keyring.delete_password(SERVICE, old_call)
                except Exception:
                    pass

            self.callsign.set(call)
            self.log("HARC belépési adatok mentve.")
            messagebox.showinfo("Mentés", "Adatok sikeresen mentve.")

        except Exception as e:
            messagebox.showerror("Mentési hiba", str(e))


    def load_credentials(self):
        """Indításkor betölti a korábban mentett hívójelet és jelszót."""

        try:
            call = keyring.get_password(SERVICE, ACCOUNT_KEY)

            if call:
                self.callsign.set(call)
                self.password.set(keyring.get_password(SERVICE, call) or "")

        except Exception as e:
            self.log(f"Mentett adatok olvasási hibája: {e}")


