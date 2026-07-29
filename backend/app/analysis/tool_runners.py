from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from app.analysis.base import AnalysisContext, Analyzer, AnalyzerOutput, evidence
from app.core.config import settings


class ToolRunStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    TIMED_OUT = "timed_out"
    TOOL_ERROR = "tool_error"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    version: str
    category: str
    languages: tuple[str, ...]
    command: tuple[str, ...]


TOOL_SPECS = (
    ToolSpec("ruff", "0.12", "correctness", ("Python",), ("ruff", "check", "--output-format=json", ".")),
    ToolSpec("mypy", "1.16", "correctness", ("Python",), ("mypy", "--no-error-summary", ".")),
    ToolSpec("radon", "6.0", "maintainability", ("Python",), ("radon", "cc", "-j", ".")),
    ToolSpec("bandit", "1.8", "security", ("Python",), ("bandit", "-r", ".", "-f", "json")),
    ToolSpec("eslint", "9", "correctness", ("JavaScript", "TypeScript"), ("eslint", ".", "-f", "json")),
    ToolSpec("tsc", "5", "correctness", ("TypeScript",), ("tsc", "--noEmit", "--pretty", "false")),
    # The pinned image must bundle its reviewed Semgrep rules at this path.
    ToolSpec(
        "semgrep",
        "1",
        "security",
        (),
        ("semgrep", "scan", "--config", "/opt/semgrep-rules", "--json", "."),
    ),
    ToolSpec("jscpd", "4", "maintainability", (), ("jscpd", "--reporters", "json", ".")),
    ToolSpec("pip_audit", "2", "security", ("Python",), ("pip-audit", "--format", "json")),
    ToolSpec("npm_audit", "11", "security", ("JavaScript", "TypeScript"), ("npm", "audit", "--json", "--ignore-scripts")),
    ToolSpec("osv_scanner", "2", "security", (), ("osv-scanner", "scan", "source", "--format", "json", ".")),
)


def configured_images() -> dict[str, str]:
    try:
        value = json.loads(settings.ANALYZER_IMAGES_JSON)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def run_tool(spec: ToolSpec, checkout_path: str) -> dict:
    image = str(configured_images().get(spec.name) or "")
    runtime = settings.ANALYZER_CONTAINER_RUNTIME
    if not image:
        return {
            "status": ToolRunStatus.UNAVAILABLE.value,
            "image": "",
            "command": list(spec.command),
            "exit_code": None,
            "stdout": "",
            "stderr": f"No pinned image is configured for {spec.name}",
            "duration_ms": 0,
        }
    if "@sha256:" not in image:
        return {
            "status": ToolRunStatus.UNAVAILABLE.value,
            "image": image,
            "command": list(spec.command),
            "exit_code": None,
            "stdout": "",
            "stderr": "Analyzer images must be pinned by digest",
            "duration_ms": 0,
        }
    if shutil.which(runtime) is None:
        return {
            "status": ToolRunStatus.UNAVAILABLE.value,
            "image": image,
            "command": list(spec.command),
            "exit_code": None,
            "stdout": "",
            "stderr": f"Container runtime {runtime!r} is unavailable",
            "duration_ms": 0,
        }
    command = [
        runtime,
        "run",
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--cpus",
        "1",
        "--memory",
        "768m",
        "--pids-limit",
        "128",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        "65534:65534",
        "--volume",
        f"{Path(checkout_path).resolve()}:/workspace:ro",
        "--workdir",
        "/workspace",
        image,
        *spec.command,
    ]
    started = time.perf_counter_ns()
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            timeout=settings.ANALYZER_TIMEOUT_SECONDS,
        )
        limit = settings.ANALYZER_MAX_OUTPUT_BYTES
        stdout = completed.stdout[:limit].decode("utf-8", errors="replace")
        stderr = completed.stderr[:limit].decode("utf-8", errors="replace")
        status = (
            ToolRunStatus.PASSED
            if completed.returncode == 0
            else ToolRunStatus.FAILED
            if completed.returncode == 1
            else ToolRunStatus.TOOL_ERROR
        )
        exit_code = completed.returncode
    except subprocess.TimeoutExpired as exc:
        limit = settings.ANALYZER_MAX_OUTPUT_BYTES
        stdout = (exc.stdout or b"")[:limit].decode("utf-8", errors="replace")
        stderr = (exc.stderr or b"")[:limit].decode("utf-8", errors="replace")
        status = ToolRunStatus.TIMED_OUT
        exit_code = None
    duration_ms = (time.perf_counter_ns() - started) // 1_000_000
    return {
        "status": status.value,
        "image": image,
        "command": list(spec.command),
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "duration_ms": duration_ms,
    }


class IsolatedToolAnalyzer(Analyzer):
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec
        self.name = f"isolated_{spec.name}"
        self.version = spec.version
        self.category = spec.category

    def supports(self, context: AnalysisContext) -> bool:
        return not self.spec.languages or bool(
            set(self.spec.languages) & set(context.languages)
        )

    def analyze(self, context: AnalysisContext) -> AnalyzerOutput:
        if not settings.EXTERNAL_ANALYZERS_ENABLED:
            return AnalyzerOutput.unavailable("Isolated analyzer runners are disabled")
        if not context.checkout_path:
            return AnalyzerOutput.unavailable(
                context.checkout_error or "Exact commit checkout is unavailable"
            )
        artifact = run_tool(self.spec, context.checkout_path)
        raw = json.dumps(artifact, sort_keys=True, separators=(",", ":"))
        artifact["output_hash"] = hashlib.sha256(raw.encode()).hexdigest()
        status = ToolRunStatus(artifact["status"])
        tool_evidence = evidence(
            "isolated_tool_run",
            f"{self.spec.name} ran in a network-disabled container",
            data={
                "tool_status": status.value,
                "image": artifact["image"],
                "exit_code": artifact["exit_code"],
                "output_hash": artifact["output_hash"],
                "_raw_artifact": artifact,
            },
        )
        if status == ToolRunStatus.PASSED:
            return AnalyzerOutput.available(100, 0.9, evidence=[tool_evidence])
        if status == ToolRunStatus.FAILED:
            return AnalyzerOutput.available(
                35,
                0.85,
                findings=[
                    {
                        "code": "TOOL_FINDINGS",
                        "message": f"{self.spec.name} reported findings",
                    }
                ],
                evidence=[tool_evidence],
            )
        if status == ToolRunStatus.UNAVAILABLE:
            return AnalyzerOutput.unavailable(
                artifact["stderr"], evidence=[tool_evidence]
            )
        if status == ToolRunStatus.TIMED_OUT:
            return AnalyzerOutput.inconclusive(
                f"{self.spec.name} exceeded its time limit",
                evidence=[tool_evidence],
            )
        return AnalyzerOutput.inconclusive(
            f"{self.spec.name} failed to execute: {artifact['stderr'][:500]}",
            evidence=[tool_evidence],
        )


EXTERNAL_ANALYZERS = tuple(IsolatedToolAnalyzer(spec) for spec in TOOL_SPECS)
