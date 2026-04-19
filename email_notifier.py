import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from loguru import logger

from config import Config


def send_booking_confirmation(booking: dict) -> bool:
    """Send email confirmation after a successful class booking."""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = (
            f"Rezervare confirmata: {booking.get('name', 'Clasa')} "
            f"- {booking.get('date', '')} {booking.get('time', '')}"
        )
        msg["From"] = Config.SMTP_USER
        msg["To"] = Config.NOTIFY_EMAIL

        plain = _build_plain(booking)
        html = _build_html(booking)

        msg.attach(MIMEText(plain, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))

        with smtplib.SMTP(Config.SMTP_HOST, Config.SMTP_PORT, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.login(Config.SMTP_USER, Config.SMTP_PASSWORD)
            server.sendmail(Config.SMTP_USER, Config.NOTIFY_EMAIL, msg.as_string())

        logger.success(f"Email trimis pentru {booking.get('name')} la {Config.NOTIFY_EMAIL}")
        return True

    except Exception as e:
        logger.error(f"Nu s-a putut trimite emailul de confirmare: {e}")
        return False


def _build_plain(b: dict) -> str:
    return f"""
Rezervare confirmata la World Class Lujerului!

Clasa:      {b.get('name', 'N/A')}
Data:       {b.get('date', 'N/A')}
Ora:        {b.get('time', 'N/A')}
Durata:     {b.get('duration', 'N/A')}
Instructor: {b.get('instructor', 'N/A')}
Club:       World Class Lujerului

Rezervare efectuata automat la: {b.get('booked_at', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}

IMPORTANT: Poti anula rezervarea cu cel putin 2 ore inainte de clasa, altfel primesti penalizare.
"""


def _build_html(b: dict) -> str:
    booked_at = b.get("booked_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;font-family:Arial,sans-serif;background:#f4f4f4;">
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td align="center" style="padding:30px 0;">
        <table width="600" cellpadding="0" cellspacing="0"
               style="background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.12);">

          <!-- Header -->
          <tr>
            <td style="background:#1a1a2e;padding:24px 32px;text-align:center;">
              <h1 style="color:#e94560;margin:0;font-size:28px;letter-spacing:2px;">WORLD CLASS</h1>
              <p style="color:#aaa;margin:4px 0 0;font-size:13px;">Rezervare Confirmata Automat</p>
            </td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="padding:32px;">
              <h2 style="color:#1a1a2e;margin:0 0 20px;">
                &#10003;&nbsp;{b.get('name', 'Clasa')}
              </h2>

              <table width="100%" cellpadding="0" cellspacing="0"
                     style="border-collapse:collapse;font-size:15px;">
                {_row('&#128197; Data', b.get('date', 'N/A'))}
                {_row('&#9200; Ora', b.get('time', 'N/A'))}
                {_row('&#9201; Durata', b.get('duration', 'N/A'))}
                {_row('&#128100; Instructor', b.get('instructor', 'N/A'))}
                {_row('&#128205; Club', 'World Class Lujerului')}
              </table>

              <p style="margin:24px 0 8px;padding:16px;background:#fff8e1;border-left:4px solid #f59e0b;
                         font-size:13px;color:#555;border-radius:0 4px 4px 0;">
                <strong>Important:</strong> Poti anula rezervarea cu cel putin
                <strong>2 ore inainte</strong> de inceperea clasei, altfel primesti penalizare.
              </p>

              <p style="font-size:11px;color:#aaa;margin:20px 0 0;text-align:right;">
                Rezervare efectuata automat la {booked_at}
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""


def _row(label: str, value: str) -> str:
    return f"""
<tr style="border-bottom:1px solid #f0f0f0;">
  <td style="padding:10px 8px;color:#888;width:40%;">{label}</td>
  <td style="padding:10px 8px;font-weight:bold;color:#1a1a2e;">{value}</td>
</tr>
"""
