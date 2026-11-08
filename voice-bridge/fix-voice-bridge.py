"""Compatibility: visible verified control, no process-killing logic."""
from service_control.launch import main
if __name__ == "__main__":
    raise SystemExit(main(["--window"]))
