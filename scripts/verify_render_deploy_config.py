from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def normalize_package(line: str) -> str:
    value = line.split("#", 1)[0].strip()
    if not value:
        return ""
    return re.split(r"[<>=!~\[]", value, maxsplit=1)[0].strip().lower()


def add_check(checks: list[dict[str, Any]], failures: list[str], ok: bool, message: str) -> None:
    checks.append({"ok": bool(ok), "message": message})
    if not ok:
        failures.append(message)


def get_service(render_yaml: dict[str, Any]) -> dict[str, Any]:
    services = render_yaml.get("services")
    if not isinstance(services, list):
        return {}
    for service in services:
        if isinstance(service, dict) and service.get("type") == "web":
            return service
    return {}


def env_map(service: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in service.get("envVars") or []:
        if isinstance(item, dict) and item.get("key"):
            result[str(item["key"])] = str(item.get("value", ""))
    return result


def verify(project_root: Path) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    failures: list[str] = []
    warnings: list[str] = []

    render_path = project_root / "render.yaml"
    dockerfile_path = project_root / "Dockerfile"
    dockerignore_path = project_root / ".dockerignore"
    requirements_path = project_root / "requirements.api.txt"

    for path in (render_path, dockerfile_path, dockerignore_path, requirements_path):
        add_check(checks, failures, path.exists(), f"{path.name} exists")

    render_yaml: dict[str, Any] = {}
    yaml_error = ""
    if render_path.exists():
        try:
            import yaml  # type: ignore

            loaded = yaml.safe_load(read_text(render_path))
            if isinstance(loaded, dict):
                render_yaml = loaded
            else:
                yaml_error = "render.yaml root is not a mapping"
        except Exception as exc:  # pragma: no cover - environment dependent
            yaml_error = str(exc)
    add_check(checks, failures, not yaml_error, f"render.yaml parses as YAML ({yaml_error or 'ok'})")

    service = get_service(render_yaml)
    env = env_map(service)
    add_check(checks, failures, bool(service), "render.yaml defines a web service")
    add_check(checks, failures, service.get("runtime") == "docker", "Render service uses docker runtime")
    add_check(checks, failures, service.get("dockerfilePath") == "./Dockerfile", "Render service points to ./Dockerfile")
    add_check(checks, failures, service.get("healthCheckPath") == "/health", "Render healthCheckPath is /health")
    add_check(checks, failures, env.get("FACTCHECK_CORS_ORIGINS") == "*", "Render CORS env allows phone clients")
    add_check(checks, failures, env.get("FACTCHECK_AI_IMAGE_MODEL") == "metadata_only", "Render AI image model is metadata_only")
    for key in ("FACTCHECK_MAX_SEARCH_RESULTS", "FACTCHECK_MAX_DOCUMENTS", "FACTCHECK_MAX_EVIDENCE"):
        add_check(checks, failures, key in env and env[key].isdigit(), f"Render env {key} is numeric")

    dockerfile = read_text(dockerfile_path) if dockerfile_path.exists() else ""
    add_check(checks, failures, "FROM python:3.11-slim" in dockerfile, "Dockerfile uses python:3.11-slim")
    add_check(checks, failures, "requirements.api.txt" in dockerfile, "Dockerfile installs requirements.api.txt")
    add_check(checks, failures, "pip install --no-cache-dir -r /app/requirements.api.txt" in dockerfile, "Dockerfile uses API-only requirements")
    add_check(checks, failures, "COPY . /app" in dockerfile, "Dockerfile copies deployment source into /app")
    add_check(checks, failures, "EXPOSE 8001" in dockerfile, "Dockerfile exposes fallback port 8001")
    add_check(checks, failures, "src.api_factcheck:app" in dockerfile, "Dockerfile starts src.api_factcheck:app")
    add_check(checks, failures, "--host 0.0.0.0" in dockerfile, "Dockerfile binds API to 0.0.0.0")
    add_check(checks, failures, "${PORT:-8001}" in dockerfile, "Dockerfile uses Render PORT with 8001 fallback")

    requirement_lines = read_text(requirements_path).splitlines() if requirements_path.exists() else []
    packages = [pkg for pkg in (normalize_package(line) for line in requirement_lines) if pkg]
    package_set = set(packages)
    required_packages = {
        "fastapi",
        "uvicorn",
        "python-multipart",
        "requests",
        "beautifulsoup4",
        "numpy",
        "pyyaml",
        "pillow",
        "rapidocr-onnxruntime",
    }
    for package in sorted(required_packages):
        add_check(checks, failures, package in package_set, f"requirements.api.txt includes {package}")
    forbidden_packages = {
        "flask",
        "matplotlib",
        "pandas",
        "pyqt5",
        "pyqt6",
        "pywebview",
        "scikit-learn",
        "sklearn",
        "streamlit",
        "tensorflow",
        "torch",
        "torchvision",
    }
    forbidden_present = sorted(package_set & forbidden_packages)
    add_check(
        checks,
        failures,
        not forbidden_present,
        "requirements.api.txt excludes desktop/training packages"
        + (f" ({', '.join(forbidden_present)})" if forbidden_present else ""),
    )

    dockerignore = read_text(dockerignore_path) if dockerignore_path.exists() else ""
    dockerignore_required = [
        ".venv/",
        "archive/",
        "apps/",
        "build/",
        "dist/",
        "docs/",
        "outputs/",
        "reports/",
        "tests/",
        "*.zip",
        "*.apk",
        "*.onnx",
    ]
    for pattern in dockerignore_required:
        add_check(checks, failures, pattern in dockerignore, f".dockerignore excludes {pattern}")

    if service.get("plan") == "free":
        warnings.append("Render plan is free; first request can be slow after sleep.")

    return {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "ok": not failures,
        "render": {
            "service_name": service.get("name", ""),
            "runtime": service.get("runtime", ""),
            "dockerfilePath": service.get("dockerfilePath", ""),
            "healthCheckPath": service.get("healthCheckPath", ""),
            "plan": service.get("plan", ""),
            "env": env,
        },
        "dockerfile": {
            "uses_api_app": "src.api_factcheck:app" in dockerfile,
            "uses_render_port": "${PORT:-8001}" in dockerfile,
            "uses_api_requirements": "requirements.api.txt" in dockerfile,
        },
        "requirements": {
            "packages": packages,
            "forbidden_present": forbidden_present,
        },
        "checks": checks,
        "failures": failures,
        "warnings": warnings,
    }


def write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# Verity Lens Render Deploy Config Verification",
        "",
        f"- Generated: `{report['generated_at']}`",
        f"- OK: `{report['ok']}`",
        f"- Service: `{report['render']['service_name']}`",
        f"- Runtime: `{report['render']['runtime']}`",
        f"- Dockerfile path: `{report['render']['dockerfilePath']}`",
        f"- Health check path: `{report['render']['healthCheckPath']}`",
        f"- Plan: `{report['render']['plan']}`",
        "",
        "## Checks",
        "",
    ]
    for check in report["checks"]:
        status = "OK" if check["ok"] else "FAIL"
        lines.append(f"- `{status}` {check['message']}")
    lines += ["", "## Failures", ""]
    if report["failures"]:
        lines.extend(f"- {item}" for item in report["failures"])
    else:
        lines.append("- None")
    lines += ["", "## Warnings", ""]
    if report["warnings"]:
        lines.extend(f"- {item}" for item in report["warnings"])
    else:
        lines.append("- None")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Render deployment configuration for Verity Lens.")
    parser.add_argument("--project-root", default=str(ROOT))
    parser.add_argument("--out-json", default="reports/render_deploy_config_latest.json")
    parser.add_argument("--out-markdown", default="reports/render_deploy_config_latest.md")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    report = verify(project_root)
    out_json = (project_root / args.out_json).resolve()
    out_markdown = (project_root / args.out_markdown).resolve()
    if not str(out_json).startswith(str(project_root)) or not str(out_markdown).startswith(str(project_root)):
        raise SystemExit("Output paths must stay inside the project root.")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_markdown.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    write_markdown(report, out_markdown)
    print(f"Render deploy config JSON: {out_json}")
    print(f"Render deploy config report: {out_markdown}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
