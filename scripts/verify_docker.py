"""Build the image, run it, and prove it actually serves the judge contract.

Run this on the machine that will build and push the image. It is the difference between "the
image built" and "the image works":

1. builds the image;
2. starts a container with no credentials;
3. waits for ``/health`` to return the canonical readiness body;
4. posts a real public sample case;
5. checks the response either is a valid, replayable plan (when a model is configured) or is a
   *controlled* error (when one is not) — never a crash, never a leaked secret;
6. confirms the container runs as a non-root user and carries no baked-in credentials.

    python scripts/verify_docker.py
    python scripts/verify_docker.py --env-file .env      # include credentials, expect a 200
    python scripts/verify_docker.py --tag gridwise:1.0.0 --keep
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_TAG = "gridwise:verify"
HEALTH_TIMEOUT_SECONDS = 90
SAMPLE_CASES = REPO_ROOT / "public_cases" / "sample_cases.json"

# Environment variable names that must never appear baked into the image.
SECRET_ENV_NAMES = ("LLM_API_KEY", "BACKUP_LLM_API_KEY")


class VerificationError(RuntimeError):
    pass


def _run(command: list[str], *, capture: bool = True, check: bool = True) -> subprocess.CompletedProcess:
    print(f"$ {' '.join(command)}")
    result = subprocess.run(command, capture_output=capture, text=True, check=False)  # noqa: S603
    if check and result.returncode != 0:
        output = (result.stderr or result.stdout or "").strip()
        raise VerificationError(f"command failed ({result.returncode}): {output[-2000:]}")
    return result


def build_image(tag: str) -> None:
    print("\n=== 1. build ===")
    _run(["docker", "build", "-t", tag, str(REPO_ROOT)], capture=False)
    print(f"built {tag}")


def start_container(tag: str, port: int, env_file: str | None) -> str:
    print("\n=== 2. run ===")
    name = f"gridwise-verify-{uuid.uuid4().hex[:8]}"
    command = ["docker", "run", "-d", "--name", name, "-p", f"{port}:{port}", "-e", f"PORT={port}"]
    if env_file:
        command += ["--env-file", env_file]
    command.append(tag)
    container_id = _run(command).stdout.strip()
    print(f"started {name} ({container_id[:12]})")
    return name


def wait_for_health(port: int, container: str) -> None:
    print("\n=== 3. health ===")
    import httpx

    url = f"http://127.0.0.1:{port}/health"
    deadline = time.monotonic() + HEALTH_TIMEOUT_SECONDS
    last_error = ""
    while time.monotonic() < deadline:
        try:
            response = httpx.get(url, timeout=3.0)
            if response.status_code == 200 and response.json() == {"status": "ok"}:
                print(f"/health -> 200 {response.json()}")
                return
            last_error = f"status {response.status_code} body {response.text[:200]}"
        except Exception as exc:  # noqa: BLE001 - keep polling until the deadline
            last_error = f"{type(exc).__name__}: {exc}"
        time.sleep(1.0)

    logs = _run(["docker", "logs", "--tail", "50", container], check=False).stdout
    raise VerificationError(f"/health never became ready: {last_error}\ncontainer logs:\n{logs}")


def exercise_optimize(port: int, expect_success: bool) -> None:
    print("\n=== 4. optimize-energy ===")
    import httpx

    from app.schemas.request import OptimizeRequest
    from app.schemas.response import OptimizeResponse
    from app.validation.replay import replay

    case = json.loads(SAMPLE_CASES.read_text(encoding="utf-8"))["cases"][0]
    response = httpx.post(f"http://127.0.0.1:{port}/optimize-energy", json=case["input"], timeout=35.0)
    body = response.text

    for secret_marker in ("Traceback", "api_key", "Authorization", "Bearer "):
        if secret_marker in body:
            raise VerificationError(f"response leaked {secret_marker!r}")

    if response.status_code == 200:
        request = OptimizeRequest.model_validate(case["input"])
        parsed = OptimizeResponse.model_validate(response.json())
        report = replay(request, parsed.directive_interpretation, parsed)
        if not report.ok:
            raise VerificationError(f"returned plan failed replay: {report.messages}")
        print(f"200 OK, plan replays clean, cost {parsed.total_cost_bdt}")
        return

    if expect_success:
        raise VerificationError(
            f"expected 200 with credentials configured, got {response.status_code}: {body[:300]}"
        )

    payload = response.json()
    code = payload.get("error", {}).get("code")
    if response.status_code != 500 or code != "interpretation_unavailable":
        raise VerificationError(
            f"expected a controlled interpretation failure, got {response.status_code} {code}"
        )
    print(f"{response.status_code} {code} — controlled failure with no model configured (expected)")


def check_hardening(tag: str, container: str) -> None:
    print("\n=== 5. hardening ===")
    user = _run(["docker", "exec", container, "id", "-un"]).stdout.strip()
    if user == "root":
        raise VerificationError("container runs as root")
    print(f"runs as non-root user: {user}")

    config = _run(["docker", "image", "inspect", tag, "--format", "{{json .Config.Env}}"]).stdout
    baked = json.loads(config)
    for name in SECRET_ENV_NAMES:
        for entry in baked:
            if entry.startswith(f"{name}=") and entry.split("=", 1)[1]:
                raise VerificationError(f"image has a baked-in value for {name}")
    print("no credentials baked into the image environment")

    history = _run(["docker", "history", "--no-trunc", tag]).stdout
    if "LLM_API_KEY=" in history and "LLM_API_KEY=\n" not in history:
        raise VerificationError("image history mentions LLM_API_KEY; check for a build-arg leak")
    print("image history carries no credential build argument")


def cleanup(container: str) -> None:
    _run(["docker", "rm", "-f", container], check=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--tag", default=DEFAULT_TAG)
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--env-file", default=None, help="pass credentials; a 200 is then required")
    parser.add_argument("--keep", action="store_true", help="leave the container running afterwards")
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args(argv)

    container = ""
    try:
        if not args.skip_build:
            build_image(args.tag)
        container = start_container(args.tag, args.port, args.env_file)
        wait_for_health(args.port, container)
        exercise_optimize(args.port, expect_success=bool(args.env_file))
        check_hardening(args.tag, container)
    except VerificationError as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        return 1
    except FileNotFoundError:
        print("\nFAILED: docker is not installed or not on PATH", file=sys.stderr)
        return 1
    finally:
        if container and not args.keep:
            cleanup(container)

    print("\nAll checks passed. The image builds, serves /health, answers /optimize-energy")
    print("in a controlled way, runs as non-root, and carries no baked-in credentials.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
