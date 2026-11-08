"""Compatibility advertising with selected physical LAN and old-ad removal."""
import threading
from service_control.launch import parser, control_paths
from service_control.discovery import advertise
if __name__ == "__main__":
    advertise(control_paths(parser().parse_args([])), threading.Event())
