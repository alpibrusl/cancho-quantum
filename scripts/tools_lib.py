"""Build and run the cancho tools (`tools/*.cho`) from the Python checks.

The tools are the product; the Python scripts that call them are tests. `apply` is what
`scripts/noise_profile.py` (the reference implementation) used to be for them.
"""
import json
import os
import subprocess
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DEN = 1_000_000
_built = {}


def tool(name, compiler=None):
    """Path of the built tool `name` (from tools/<name>.cho), built once per process."""
    if name not in _built:
        out = os.path.join(tempfile.mkdtemp(prefix=name + "-"), name)
        r = subprocess.run([compiler or os.environ.get("CANCHO", "cancho"), "build", os.path.join(ROOT, "tools", name + ".cho"), "--std", "-o", out],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"build of tools/{name}.cho failed:\n{r.stderr[-800:]}")
        _built[name] = out
    return _built[name]


def run(name, text):
    r = subprocess.run([tool(name)], input=text, capture_output=True, text=True)
    if r.returncode != 0:
        raise ValueError(r.stderr.strip() or f"{name} exited {r.returncode}")
    return r.stdout


def apply(profile, circuit=None):
    """`qprofile` on a profile (a dict) and optionally a circuit: the circuit with the operations after its header."""
    text = json.dumps(profile)
    return run("qprofile", text if circuit is None else text + "\n---\n" + circuit)


def operations(profile):
    return [l for l in apply(profile).splitlines() if l]
