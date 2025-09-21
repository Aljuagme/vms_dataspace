from vms.models import LogEntry


def log_event(action, details="", level="INFO"):
    """
    Create a LogEntry; details should be a string (JSON if structured).
    Keep messages clear for presentation in defense.
    """
    entry = LogEntry.objects.create(action=action, details=details, level=level)
    return entry
