import smtplib
import logging
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from config import Config

logger = logging.getLogger(__name__)

_EMAIL_CFG = Config.settings["email"]
_SMS_CFG   = Config.settings.get("sms", {})

_last_email_time: dict[str, float] = {}
_last_sms_time:   dict[str, float] = {}


def _email_cooldown_ok(parameter: str) -> bool:
    secs = _EMAIL_CFG.get("cooldown_minutes", 15) * 60
    return (time.time() - _last_email_time.get(parameter, 0)) >= secs


def _sms_cooldown_ok(parameter: str) -> bool:
    secs = _SMS_CFG.get("cooldown_minutes", 15) * 60
    return (time.time() - _last_sms_time.get(parameter, 0)) >= secs


def _direction_word(direction: str) -> str:
    return "exceeded" if direction == "high" else "fallen below"


def send_email(parameter: str, value: float,
               threshold: float, direction: str) -> bool:
    if not _EMAIL_CFG.get("enabled", False):
        return False
    if not _email_cooldown_ok(parameter):
        logger.debug("Email cooldown active for %s", parameter)
        return False

    dw = _direction_word(direction)
    subject = f"[MUSEUM ALERT] {parameter.capitalize()} {dw} safe range"
    body = (
        f"MUSEUM CLIMATE ALERT\n{'=' * 40}\n\n"
        f"Parameter : {parameter.capitalize()}\n"
        f"Reading   : {value}\n"
        f"Threshold : {threshold} ({direction})\n"
        f"Status    : Reading has {dw} the safe range.\n\n"
        f"Automatic actuator response has been triggered.\n"
        f"Please inspect the affected gallery.\n\n"
        f"— Smart Museum Preservation System"
    )

    msg = MIMEMultipart()
    msg["From"]    = _EMAIL_CFG["sender"]
    msg["To"]      = ", ".join(_EMAIL_CFG["recipients"])
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(_EMAIL_CFG["smtp_host"], _EMAIL_CFG["smtp_port"]) as srv:
            srv.starttls()
            srv.login(_EMAIL_CFG["sender"], _EMAIL_CFG["password"])
            srv.sendmail(_EMAIL_CFG["sender"], _EMAIL_CFG["recipients"], msg.as_string())
        _last_email_time[parameter] = time.time()
        logger.info("Email alert sent for %s (value=%.2f)", parameter, value)
        return True
    except Exception as exc:
        logger.error("Failed to send email alert: %s", exc)
        return False


def send_sms(parameter: str, value: float,
             threshold: float, direction: str) -> bool:
    if not _SMS_CFG.get("enabled", False):
        return False
    if not _sms_cooldown_ok(parameter):
        logger.debug("SMS cooldown active for %s", parameter)
        return False

    dw = _direction_word(direction)
    body = (
        f"MUSEUM ALERT: {parameter.capitalize()} {dw} safe range. "
        f"Reading={value}, Threshold={threshold}. "
        f"Automatic response triggered."
    )

    try:
        from twilio.rest import Client
        client = Client(_SMS_CFG["account_sid"], _SMS_CFG["auth_token"])
        client.messages.create(
            body=body,
            from_=_SMS_CFG["from_number"],
            to=_SMS_CFG["to_number"],
        )
        _last_sms_time[parameter] = time.time()
        logger.info("SMS alert sent for %s", parameter)
        return True
    except ImportError:
        logger.warning("twilio package not installed — SMS disabled")
        return False
    except Exception as exc:
        logger.error("Failed to send SMS: %s", exc)
        return False


def send_alert(parameter: str, value: float,
               threshold: float, direction: str) -> None:
    if _EMAIL_CFG.get("enabled", False):
        send_email(parameter, value, threshold, direction)
    if _SMS_CFG.get("enabled", False):
        send_sms(parameter, value, threshold, direction)
