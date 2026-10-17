"""Run a command and print its peak memory (max RSS of the child) to stderr as 'PEAK_MB=<n>'.
Usage: python -I scripts/peakmem.py <cmd> [args...]   (used by scripts/reproduce.sh for the per-step table)"""
import resource
import subprocess
import sys

rc = subprocess.call(sys.argv[1:])
kb = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
mb = kb / 1024 / (1024 if sys.platform == "darwin" else 1)  # macOS reports bytes, Linux kilobytes
print(f"PEAK_MB={mb:.0f}", file=sys.stderr)
sys.exit(rc)
