# vms/services/logging.py
from vms.models import LogEntry

def log_event(action, details="", level="INFO"):

    return LogEntry.objects.create(action=action, details=details, level=level)
