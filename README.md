# Worldclass Booking Automation

Rezerva automat clasele de **pilates** si **stretching** la **World Class Lujerului**, imediat ce fereastra de rezervare se deschide (26 de ore inainte de clasa).

Dupa fiecare rezervare reusita trimite un **email de confirmare** cu toate detaliile.

---

## Instalare

```bash
# 1. Creeaza si activeaza un virtual environment
python -m venv venv
source venv/bin/activate        # Linux/Mac
# sau: venv\Scripts\activate    # Windows

# 2. Instaleaza dependentele
pip install -r requirements.txt

# 3. Instaleaza browser-ul Chromium pentru Playwright
playwright install chromium
```

---

## Configurare

```bash
cp .env.example .env
```

Editeaza `.env` si completeaza:

| Variabila | Descriere |
|-----------|-----------|
| `WC_EMAIL` | Emailul contului tau Worldclass |
| `WC_PASSWORD` | Parola contului Worldclass |
| `NOTIFY_EMAIL` | Emailul la care vrei sa primesti confirmari |
| `SMTP_USER` | Emailul Gmail de pe care se trimit notificarile |
| `SMTP_PASSWORD` | [Parola de aplicatie Gmail](https://myaccount.google.com/apppasswords) (nu parola contului!) |
| `SMTP_HOST` | `smtp.gmail.com` (default) |
| `SMTP_PORT` | `587` (default) |
| `CHECK_INTERVAL_MINUTES` | Cat de des verifica (default: 30 minute) |

---

## Utilizare

```bash
# Ruleaza continuu (recomandat — verifica la fiecare 30 min)
python main.py

# Verifica o singura data si iese
python main.py --once

# Test fara rezervari reale
python main.py --dry-run --once
```

### Pornire automata la sistem (Linux)

```bash
# Creeaza un serviciu systemd
sudo nano /etc/systemd/system/worldclass-booking.service
```

```ini
[Unit]
Description=Worldclass Booking Automation
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
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
sudo systemctl status worldclass-booking
```

---

## Cum functioneaza

1. **Politica Worldclass**: rezervarile se deschid cu **26 de ore inainte** de ora clasei.
2. Scriptul ruleaza periodic (default: la 30 de minute).
3. La fiecare verificare:
   - Se autentifica in contul tau
   - Incarca programul de la World Class Lujerului
   - Filtreaza clasele de pilates si stretching
   - Rezerva orice clasa disponibila (butonul "Rezerva" activ)
   - Trimite email de confirmare dupa fiecare rezervare
4. Clasele deja rezervate sunt sarite automat.

---

## Depanare

- **Screenshot-uri de debug** sunt salvate automat in folderul proiectului cand apar erori.
- **Log-uri complete** in `worldclass_booking.log`.
- Seteaza `HEADLESS=false` in `.env` pentru a vedea browserul in actiune.

---

## Note importante

- Maximum **2 clase** pot fi rezervate pe zi la acelasi club (limita Worldclass).
- Rezervarile pot fi anulate **cu cel putin 2 ore inainte**; altfel se aplica penalizare.
- Foloseste o **parola de aplicatie** Google, nu parola contului Gmail.
