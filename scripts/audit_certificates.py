"""Create local-only demo CA and separate mTLS identities; never overwrite keys."""

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def create(directory):
    directory = directory.resolve()
    if (ROOT / ".local").resolve() not in directory.parents:
        raise ValueError("Certificates must be private under .local")
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    directory.chmod(0o700)
    if any(directory.iterdir()):
        raise ValueError("Refusing to overwrite certificates")
    executable = shutil.which("openssl")
    if not executable:
        raise RuntimeError("openssl is required")

    def run(*args):
        subprocess.run(  # noqa: S603 - fixed executable and operator-owned certificate names
            [executable, *args],
            cwd=directory,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    run(
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-days",
        "30",
        "-subj",
        "/CN=Reference Audit Demo CA",
        "-keyout",
        "ca.key",
        "-out",
        "ca.crt",
    )
    for name, usage in [("collector", "serverAuth"), ("shipper", "clientAuth")]:
        (directory / f"{name}.ext").write_text(f"subjectAltName=DNS:audit-{name}\nextendedKeyUsage={usage}\n")
        run(
            "req",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-subj",
            f"/CN=audit-{name}",
            "-keyout",
            f"{name}.key",
            "-out",
            f"{name}.csr",
        )
        run(
            "x509",
            "-req",
            "-in",
            f"{name}.csr",
            "-CA",
            "ca.crt",
            "-CAkey",
            "ca.key",
            "-CAcreateserial",
            "-days",
            "30",
            "-extfile",
            f"{name}.ext",
            "-out",
            f"{name}.crt",
        )
    for key in directory.glob("*.key"):
        key.chmod(0o600)


if __name__ == "__main__":
    create(ROOT / ".local/audit-certs")
    print("Private demo mTLS certificates generated.")
