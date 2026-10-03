"""Run the integration regressions in pinned images, offline and without keys."""

import subprocess

from verify_full_stack_config import DOCKER, ROOT, model


def run():
    config = model()["services"]
    shared = [
        ("apps/rag-assistant", "/reference/secure-rag"),
        ("ingestion", "/reference/ingestion"),
    ]
    suites = (
        (
            "litellm",
            "test_reference_gateway.py",
            [("gateway/reference_gateway.py", "/reference/reference_gateway.py")],
        ),
        (
            "open-webui",
            "test_openwebui_policy.py",
            [
                ("apps/open-webui/reference_filter.py", "/reference/reference_filter.py"),
                ("apps/open-webui/reference_rerank.py", "/reference/reference_rerank.py"),
            ],
        ),
    )
    for service, filename, mounts in suites:
        command = [
            DOCKER,
            "run",
            "--rm",
            "-i",
            "--network",
            "none",
            "--read-only",
            "--user",
            "1000:1000",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--tmpfs",
            "/tmp:size=256m,mode=1777",  # noqa: S108 - isolated container memory, not host temp files
            "--entrypoint",
            "python",
            "-e",
            "PYTHONPATH=/reference:/reference/secure-rag",
            "-e",
            "GLOBAL_LOG_LEVEL=ERROR",
        ]
        for source, target in [*shared, *mounts]:
            command.extend(["--mount", f"type=bind,src={ROOT / source},dst={target},readonly"])
        command.extend([config[service]["image"], "-", "-v"])
        subprocess.run(command, input=(ROOT / "tests" / filename).read_bytes(), check=True)  # noqa: S603


if __name__ == "__main__":
    run()
