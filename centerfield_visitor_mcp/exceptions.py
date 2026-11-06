class CenterfieldError(Exception):
    """Base error. ``status_code`` is the site's HTTP status when one was received."""

    def __init__(self, message: str = "", *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class SessionInitError(CenterfieldError):
    pass


class CSRFError(CenterfieldError):
    pass


class CompanyNotFoundError(CenterfieldError):
    pass


class PersonInChargeVerificationError(CenterfieldError):
    pass


class FloorListError(CenterfieldError):
    pass


class ReservationSubmissionError(CenterfieldError):
    """The reservation was definitely NOT created (explicit reject, unambiguous 4xx, or never sent)."""


class ReservationOutcomeUnknownError(CenterfieldError):
    """The reservation request may have reached the site, but its outcome could not be confirmed.

    Raised for read/write timeouts, read/write errors, protocol errors, 5xx responses and
    responses that are not a JSON object with a ``success`` field. Callers must not retry
    automatically: the reservation may already exist. Deliberately NOT a subclass of
    ReservationSubmissionError so ``except ReservationSubmissionError`` never treats it as a failure.
    """
