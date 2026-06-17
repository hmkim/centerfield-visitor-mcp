class CenterfieldError(Exception):
    pass


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
    pass
