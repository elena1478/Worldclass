# Worldclass Booking Automation

Rezerva automat clasele de **pilates** si **stretching** la **World Class Lujerului**, imediat ce fereastra de rezervare se deschide (26 de ore inainte de clasa).

Worldclass trimite automat email de confirmare dupa fiecare rezervare.

---

## Instalare

```bash
python -m venv venv
source venv/bin/activate        # Linux/Mac
pip install -r requirements.txt
playwright install chromium
```

---

## Configurare

```bash
cp .env.example .env
# Editeaza .env cu credentialele contului tau Worldclass
```

| Variabila | Descriere |
|-----------|-----------|
| `WC_EMAIL` | Emailul contului Worldclass |
| `WC_PASSWORD` | Parola contului Worldclass |
| `CHECK_INTERVAL_MINUTES` | Cat de des verifica (default: 30 min) |

---

## Utilizare

```bash
python main.py --dry-run --once   # test: vede clasele fara sa rezerve
python main.py --once             # o singura verificare
python main.py                    # serviciu continuu (recomandat)
```

### Pornire automata la sistem (Linux)

```bash
sudo nano /etc/systemd/system/worldclass-booking.service
```

```ini
[Unit]
Description=Worldclass Booking Automation
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/user/Worldclass
ExecStart=/home/user/Worldclass/venv/bin/python main.py
Restart=always
RestartSec=60

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable worldclass-booking
sudo systemctl start worldclass-booking
```

---

## Cum functioneaza

1. **Politica Worldclass**: rezervarile se deschid cu **26 de ore inainte**.
2. Scriptul verifica periodic (default: 30 min).
3. La fiecare verificare: se autentifica, incarca programul Lujerului, rezerva orice clasa de pilates/stretching disponibila.
4. Clasele deja rezervate sunt sarite automat.
5. Worldclass trimite email de confirmare automat dupa fiecare rezervare.

---

## Note

- Max **2 clase pe zi** la acelasi club (limita Worldclass).
- Anulare posibila cu cel putin **2 ore inainte** (altfel penalizare).
- Seteaza `HEADLESS=false` in `.env` ca sa vezi browserul in actiune (debug).
- Log-uri complete in `worldclass_booking.log`.
