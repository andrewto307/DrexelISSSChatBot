from typing import Protocol

from isss_bot import config

SIGN_OFF = "\n\nIf you didn't ask for this, you can ignore this email.\n\nISSS Assistant (unofficial)"


def compose(purpose: str, code: str | None) -> tuple[str, str]:
    if purpose == "verify":
        return (
            f"{code} is your ISSS Assistant code",
            f"Your code to finish signing up is {code}. It expires in 15 minutes.{SIGN_OFF}",
        )
    if purpose == "reset":
        return (
            f"{code} is your ISSS Assistant password reset code",
            f"Your code to set a new password is {code}. It expires in 15 minutes.{SIGN_OFF}",
        )
    if purpose == "exists":
        return (
            "You already have an ISSS Assistant account",
            "Someone tried to sign up with this email, but it already has an account. "
            f'Log in instead, or use "Forgot password" to set a new password.{SIGN_OFF}',
        )
    raise ValueError(f"Unknown email purpose: {purpose}")


class Mailer(Protocol):
    def send(self, email: str, purpose: str, code: str | None = None) -> None: ...


class ConsoleMailer:
    def send(self, email: str, purpose: str, code: str | None = None) -> None:
        subject, body = compose(purpose, code)
        print(f"\n--- Email to {email} (printed instead of sent) ---\nSubject: {subject}\n\n{body}\n", flush=True)


def create_mailer(kind: str = config.MAILER) -> Mailer:
    if kind == "console":
        return ConsoleMailer()
    raise ValueError(f"Unknown MAILER {kind!r}. Only 'console' is available for now.")
