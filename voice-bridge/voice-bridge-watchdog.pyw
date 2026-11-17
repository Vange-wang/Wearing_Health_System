"""Compatibility forwarder; the unified core is the only restarter."""
import sys
from service_control.launch import main
if __name__ == "__main__":
    raise SystemExit(main(["--check-once"] if "--check-once" in sys.argv[1:] else []))
