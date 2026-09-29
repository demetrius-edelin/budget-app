"""Errors that the core raises. The web layer shows their messages to the owner."""


class SpendtrackError(Exception):
    """Base class for every core error."""


class ValidationError(SpendtrackError):
    """The input breaks a rule of the specification."""


class NotFoundError(SpendtrackError):
    """The row does not exist or is deleted."""


class MissingParameterError(SpendtrackError):
    """A metric parameter has no value in force on the given date."""

    def __init__(self, name: str, label: str) -> None:
        self.name = name
        self.label = label
        super().__init__(f"Setează mai întâi {label} în Setări.")
