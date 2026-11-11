"""Run diagnostic checks with a separate test database; never print connection strings."""
import argparse
import json
from pathlib import Path
import subprocess
from urllib.parse import urlsplit, urlunsplit

parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--select", default="")
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
container = "plane-quality-tests"
subprocess.run(["docker", "exec", container, "mkdir", "-p", "/diagnostic-pressure-149"], check=True, capture_output=True)
subprocess.run(["docker", "cp", str(root / "ProjectServer") + "/.", container + ":/diagnostic-pressure-149/"], check=True, capture_output=True)
config = json.loads(subprocess.check_output(["docker", "inspect", container]))[0]
env = dict(row.split("=", 1) for row in config["Config"]["Env"])
url = urlsplit(env["DATABASE_URL"])
env = {"DATABASE_URL": urlunsplit(url._replace(path="/diagnostic_pressure_149")),
       "PGDATABASE": "diagnostic_pressure_149", "POSTGRES_DB": "diagnostic_pressure_149",
       "REDIS_URL": "redis://plane-quality-test-redis:6379/14"}
command = ["docker", "exec", "-w", "/diagnostic-pressure-149"]
for key, value in env.items():
    command += ["-e", key + "=" + value]
command += [container, "python", "-m", "pytest", "--create-db", "plane/tests/contract/app/test_diagnostic_usage.py",
            "plane/tests/contract/app/test_diagnostic_deadlines.py", "plane/tests/contract/app/test_automatic_diagnostics.py",
            "plane/tests/contract/app/test_diagnostics.py", "plane/tests/contract/app/test_incident_diagnostics.py", "-q"]
if args.select:
    command += ["-k", args.select]
result = subprocess.run(command, text=True, capture_output=True)
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(result.stdout + result.stderr)
print((result.stdout + result.stderr)[-10000:])
raise SystemExit(result.returncode)
