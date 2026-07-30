from __future__ import annotations

from pathlib import PurePosixPath

from app.analysis.base import AnalysisContext, Analyzer, AnalyzerOutput, evidence


CODE_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".java",
    ".go",
    ".rs",
    ".rb",
    ".php",
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".sol",
}
TEST_MARKERS = {
    "Python": ("tests/", "test_", "_test.py"),
    "JavaScript": ("tests/", "__tests__/", ".test.", ".spec."),
    "TypeScript": ("tests/", "__tests__/", ".test.", ".spec."),
    "Java": ("src/test/", "test"),
    "Go": ("_test.go",),
    "Rust": ("tests/",),
}
DOCUMENT_NAMES = {
    "readme",
    "changelog",
    "contributing",
    "security",
    "architecture",
}
DEPENDENCY_FILES = {
    "pyproject.toml": "Python",
    "requirements.txt": "Python",
    "poetry.lock": "Python",
    "uv.lock": "Python",
    "package.json": "JavaScript/TypeScript",
    "package-lock.json": "JavaScript/TypeScript",
    "pnpm-lock.yaml": "JavaScript/TypeScript",
    "yarn.lock": "JavaScript/TypeScript",
    "go.mod": "Go",
    "go.sum": "Go",
    "cargo.toml": "Rust",
    "cargo.lock": "Rust",
    "gemfile": "Ruby",
    "gemfile.lock": "Ruby",
    "composer.json": "PHP",
    "composer.lock": "PHP",
}


def _normalized(filename: str) -> str:
    return filename.replace("\\", "/").lower()


def _is_code(filename: str) -> bool:
    return PurePosixPath(filename).suffix.lower() in CODE_EXTENSIONS


def _is_test(filename: str, languages: tuple[str, ...]) -> bool:
    normalized = _normalized(filename)
    generic = ("tests/", "test_", "_test.", ".test.", ".spec.", "__tests__/")
    markers = list(generic)
    for language in languages:
        markers.extend(TEST_MARKERS.get(language, ()))
    return any(marker in normalized for marker in markers)


def _is_documentation(filename: str) -> bool:
    normalized = _normalized(filename)
    path = PurePosixPath(normalized)
    stem = path.stem
    return (
        normalized.startswith("docs/")
        or "/docs/" in normalized
        or normalized.startswith("documentation/")
        or stem in DOCUMENT_NAMES
        or (path.suffix in {".md", ".rst", ".adoc"} and not _is_code(filename))
    )


def _matching_checks(context: AnalysisContext, terms: tuple[str, ...]) -> list[dict]:
    return [
        check
        for check in context.check_runs
        if any(term in str(check.get("name") or "").lower() for term in terms)
    ]


def _score_checks(
    checks: list[dict],
    *,
    unavailable_reason: str,
) -> AnalyzerOutput:
    if not checks:
        return AnalyzerOutput.unavailable(unavailable_reason)
    completed = [
        check for check in checks if str(check.get("status") or "").lower() == "completed"
    ]
    if not completed:
        return AnalyzerOutput.inconclusive(
            "Matching checks have not completed",
            evidence=[
                evidence(
                    "github_check",
                    "Check is still pending",
                    data={"name": check.get("name"), "status": check.get("status")},
                )
                for check in checks
            ],
        )
    successful = {
        "success",
        "neutral",
        "skipped",
    }
    success_count = sum(
        str(check.get("conclusion") or "").lower() in successful
        for check in completed
    )
    ratio = success_count / len(completed)
    score = 20 + (75 * ratio)
    return AnalyzerOutput.available(
        score,
        0.95,
        findings=[
            {
                "code": "CHECK_SUMMARY",
                "message": f"{success_count}/{len(completed)} checks passed or were neutral",
            }
        ],
        evidence=[
            evidence(
                "github_check",
                "GitHub check conclusion",
                data={
                    "name": check.get("name"),
                    "status": check.get("status"),
                    "conclusion": check.get("conclusion"),
                    "details_url": check.get("details_url"),
                },
            )
            for check in completed
        ],
    )


class DiffSizeConcentrationAnalyzer(Analyzer):
    name = "diff_size_concentration"
    version = "1.0.0"
    category = "change_risk"

    def analyze(self, context: AnalysisContext) -> AnalyzerOutput:
        total_changes = sum(file.changes for file in context.files)
        changed_files = len(context.files)
        largest = max((file.changes for file in context.files), default=0)
        concentration = largest / total_changes if total_changes else 0

        if total_changes <= 50:
            volume_score = 95
        elif total_changes <= 200:
            volume_score = 85
        elif total_changes <= 500:
            volume_score = 70
        elif total_changes <= 1000:
            volume_score = 50
        elif total_changes <= 2500:
            volume_score = 30
        else:
            volume_score = 15
        concentration_penalty = 30 if concentration > 0.80 else 15 if concentration > 0.50 else 0
        breadth_penalty = 10 if changed_files > 50 else 0
        score = max(0, volume_score - concentration_penalty - breadth_penalty)
        return AnalyzerOutput.available(
            score,
            0.98,
            findings=[
                {
                    "code": "DIFF_FOOTPRINT",
                    "message": (
                        f"{total_changes} changed lines across {changed_files} files; "
                        f"largest-file concentration {concentration:.1%}"
                    ),
                }
            ],
            evidence=[
                evidence(
                    "diff_summary",
                    "Complete GitHub file snapshot statistics",
                    data={
                        "total_changes": total_changes,
                        "changed_files": changed_files,
                        "largest_file_changes": largest,
                        "largest_file_concentration": round(concentration, 6),
                    },
                )
            ],
        )


class TestFileChangesAnalyzer(Analyzer):
    name = "test_file_changes"
    version = "1.0.0"
    category = "tests"

    def analyze(self, context: AnalysisContext) -> AnalyzerOutput:
        code_files = [file for file in context.files if _is_code(file.filename)]
        if not code_files:
            return AnalyzerOutput.inconclusive(
                "No production code files changed; test expectations are policy-specific"
            )
        test_files = [
            file for file in context.files if _is_test(file.filename, context.languages)
        ]
        code_additions = sum(
            file.additions for file in code_files if file not in test_files
        )
        test_additions = sum(file.additions for file in test_files)
        test_deletions = sum(file.deletions for file in test_files)
        if not test_files:
            score = 20
            message = "Production code changed without a detected test-file change"
        else:
            ratio = test_additions / max(1, code_additions)
            deletion_penalty = min(20, test_deletions / max(1, test_additions) * 20)
            score = min(95, 55 + min(35, ratio * 50) - deletion_penalty)
            message = (
                f"{len(test_files)} test files changed with a "
                f"{test_additions}/{max(1, code_additions)} test-to-code addition ratio"
            )
        return AnalyzerOutput.available(
            score,
            0.90,
            findings=[{"code": "TEST_CHANGE_RATIO", "message": message}],
            evidence=[
                evidence(
                    "file_classification",
                    "Language-aware test-file classification",
                    data={
                        "languages": list(context.languages),
                        "production_code_files": len(code_files),
                        "test_files": [file.filename for file in test_files],
                        "code_additions": code_additions,
                        "test_additions": test_additions,
                        "test_deletions": test_deletions,
                    },
                )
            ],
        )


class DocumentationChangesAnalyzer(Analyzer):
    name = "documentation_changes"
    version = "1.0.0"
    category = "documentation"

    def analyze(self, context: AnalysisContext) -> AnalyzerOutput:
        docs = [file for file in context.files if _is_documentation(file.filename)]
        code = [file for file in context.files if _is_code(file.filename)]
        if docs:
            score = 95 if not code else 85
            message = f"{len(docs)} documentation files changed"
        elif code:
            score = 45
            message = "Code changed without a detected documentation-file change"
        else:
            score = 75
            message = "No code or documentation-sensitive files changed"
        return AnalyzerOutput.available(
            score,
            0.85,
            findings=[{"code": "DOCUMENTATION_CHANGE", "message": message}],
            evidence=[
                evidence(
                    "file_classification",
                    "Documentation file classification",
                    data={
                        "documentation_files": [file.filename for file in docs],
                        "code_file_count": len(code),
                    },
                )
            ],
        )


class LintResultsAnalyzer(Analyzer):
    name = "lint_results"
    version = "1.0.0"
    category = "correctness"

    def analyze(self, context: AnalysisContext) -> AnalyzerOutput:
        return _score_checks(
            _matching_checks(
                context,
                ("lint", "eslint", "ruff", "flake8", "pylint", "typecheck", "tsc"),
            ),
            unavailable_reason=(
                context.check_runs_error
                or "No recognized lint or type-check result was reported by GitHub"
            ),
        )


class ComplexityDeltaAnalyzer(Analyzer):
    name = "complexity_delta"
    version = "1.0.0"
    category = "maintainability"

    def analyze(self, context: AnalysisContext) -> AnalyzerOutput:
        return _score_checks(
            _matching_checks(context, ("complexity", "radon", "cyclomatic")),
            unavailable_reason=context.check_runs_error
            or "Complexity delta requires a checked-out repository or a recognized CI result",
        )


class DuplicationDeltaAnalyzer(Analyzer):
    name = "duplication_delta"
    version = "1.0.0"
    category = "maintainability"

    def analyze(self, context: AnalysisContext) -> AnalyzerOutput:
        return _score_checks(
            _matching_checks(context, ("duplication", "jscpd", "copy/paste")),
            unavailable_reason=context.check_runs_error
            or "Duplication delta requires a checked-out repository or a recognized CI result",
        )


class FunctionSizeDeltaAnalyzer(Analyzer):
    name = "function_size_delta"
    version = "1.0.0"
    category = "maintainability"

    def analyze(self, context: AnalysisContext) -> AnalyzerOutput:
        return _score_checks(
            _matching_checks(context, ("function size", "method size", "long method")),
            unavailable_reason=context.check_runs_error
            or "Function-size delta requires language ASTs from a checked-out repository",
        )


class DependencyChangesAnalyzer(Analyzer):
    name = "dependency_changes"
    version = "1.0.0"
    category = "architecture"

    def analyze(self, context: AnalysisContext) -> AnalyzerOutput:
        dependency_files = [
            file
            for file in context.files
            if PurePosixPath(_normalized(file.filename)).name in DEPENDENCY_FILES
        ]
        if not dependency_files:
            score = 92
            message = "No dependency manifest or lockfile changed"
        else:
            manifest_changes = [
                file
                for file in dependency_files
                if not PurePosixPath(_normalized(file.filename)).name.endswith(
                    (".lock", "lock.json", "lock.yaml")
                )
                and PurePosixPath(_normalized(file.filename)).name
                not in {"go.sum", "cargo.lock", "gemfile.lock", "composer.lock"}
            ]
            additions = sum(file.additions for file in dependency_files)
            score = max(35, 78 - len(manifest_changes) * 12 - min(20, additions / 10))
            message = f"{len(dependency_files)} dependency files changed"
        return AnalyzerOutput.available(
            score,
            0.90,
            findings=[{"code": "DEPENDENCY_CHANGE", "message": message}],
            evidence=[
                evidence(
                    "dependency_manifest",
                    "Ecosystem dependency-file classification",
                    data={
                        "files": [
                            {
                                "filename": file.filename,
                                "ecosystem": DEPENDENCY_FILES.get(
                                    PurePosixPath(_normalized(file.filename)).name
                                ),
                                "status": file.status,
                                "additions": file.additions,
                                "deletions": file.deletions,
                            }
                            for file in dependency_files
                        ]
                    },
                )
            ],
        )


class SecurityScannerAnalyzer(Analyzer):
    name = "security_scanner_findings"
    version = "1.0.0"
    category = "security"

    def analyze(self, context: AnalysisContext) -> AnalyzerOutput:
        return _score_checks(
            _matching_checks(
                context,
                ("semgrep", "bandit", "codeql", "security", "snyk", "trivy"),
            ),
            unavailable_reason=context.check_runs_error
            or "No recognized security scanner result was reported by GitHub",
        )


class CICheckStatusAnalyzer(Analyzer):
    name = "ci_check_status"
    version = "1.0.0"
    category = "correctness"

    def analyze(self, context: AnalysisContext) -> AnalyzerOutput:
        return _score_checks(
            list(context.check_runs),
            unavailable_reason=context.check_runs_error
            or "No GitHub check runs were reported for the head SHA",
        )


DEFAULT_ANALYZERS: tuple[Analyzer, ...] = (
    DiffSizeConcentrationAnalyzer(),
    TestFileChangesAnalyzer(),
    DocumentationChangesAnalyzer(),
    LintResultsAnalyzer(),
    ComplexityDeltaAnalyzer(),
    DuplicationDeltaAnalyzer(),
    FunctionSizeDeltaAnalyzer(),
    DependencyChangesAnalyzer(),
    SecurityScannerAnalyzer(),
    CICheckStatusAnalyzer(),
)
