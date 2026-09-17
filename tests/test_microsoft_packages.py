import io
import json
import zipfile
from pathlib import Path

from agentebc.diagnosis import DiagnosticService
from agentebc.microsoft_packages import (
    MicrosoftPackageIndex,
    resolve_alpackages_path,
)
from agentebc.models import Incident


def _write_microsoft_app(
    path: Path,
    *,
    entry_path: str,
    content: str,
) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(entry_path, content)
    path.write_bytes(buffer.getvalue())


def test_resolve_alpackages_path_from_funciones_default(tmp_path: Path) -> None:
    alpackages = tmp_path / "Funciones" / ".alpackages"
    alpackages.mkdir(parents=True)

    resolved = resolve_alpackages_path(tmp_path, None)

    assert resolved == alpackages.resolve()


def test_builds_cached_index_and_finds_stack_frame(tmp_path: Path) -> None:
    packages_dir = tmp_path / ".alpackages"
    cache_dir = tmp_path / "cache"
    packages_dir.mkdir()
    package_path = packages_dir / "Microsoft_Base Application_27.0.38460.40242.app"
    lines = [
        'codeunit 80 "Sales-Post"',
        "{",
        "    procedure CheckSalesDocument();",
        "    begin",
    ]
    lines.extend(f"        // paso {step}" for step in range(1, 20))
    lines.extend(
        [
            "        if GenJnlCheckLine.IsDateNotAllowed(SalesHeader.\"Posting Date\") then",
            "            ErrorMessageMgt.LogContextFieldError();",
            "    end;",
            "}",
        ]
    )
    _write_microsoft_app(
        package_path,
        entry_path="src/Sales/Posting/SalesPost.Codeunit.al",
        content="\n".join(lines),
    )

    index = MicrosoftPackageIndex(packages_dir, cache_dir=cache_dir)
    matches = index.search_call_stack(
        '"Sales-Post"(CodeUnit 80).CheckSalesDocument line 22 - Base Application '
        "by Microsoft version 27.0.38460.40242"
    )

    assert matches
    assert matches[0].path.endswith(
        "Microsoft_Base Application_27.0.38460.40242.app!"
        "src/Sales/Posting/SalesPost.Codeunit.al"
    )
    assert matches[0].line == 25
    assert "IsDateNotAllowed" in matches[0].excerpt

    cache_file = cache_dir / "microsoft-app-index.json"
    assert cache_file.is_file()
    payload = json.loads(cache_file.read_text(encoding="utf-8"))
    assert payload["objects"]["codeunit:80:salespost"]["entry"].endswith(
        "SalesPost.Codeunit.al"
    )

    index_again = MicrosoftPackageIndex(packages_dir, cache_dir=cache_dir)
    cached_matches = index_again.search_call_stack(
        '"Sales-Post"(CodeUnit 80).CheckSalesDocument line 22'
    )
    assert cached_matches[0].line == matches[0].line


def test_diagnosis_uses_microsoft_packages_before_subscribers(tmp_path: Path) -> None:
    source = tmp_path / "Funciones" / "src" / "codeunit"
    source.mkdir(parents=True)
    (source / "Eventos.Al").write_text(
        "\n".join(
            [
                "codeunit 50100 Eventos",
                "{",
                '    [EventSubscriber(ObjectType::Codeunit, Codeunit::"Sales-Post", OnBeforePostSalesDoc, \'\', false, false)]',
                "    procedure HandleSalesPost()",
                "    begin",
                "    end;",
                "}",
            ]
        ),
        encoding="utf-8",
    )

    packages_dir = tmp_path / "Funciones" / ".alpackages"
    packages_dir.mkdir(parents=True)
    package_path = packages_dir / "Microsoft_Base Application_27.0.38460.40242.app"
    _write_microsoft_app(
        package_path,
        entry_path="src/Sales/Posting/SalesPost.Codeunit.al",
        content="\n".join(
            [
                'codeunit 80 "Sales-Post"',
                "{",
                "    procedure CheckSalesDocument();",
                "    begin",
                "        ErrorMessageMgt.LogContextFieldError();",
                "    end;",
                "}",
            ]
        ),
    )

    report = DiagnosticService(tmp_path, cache_dir=tmp_path / "cache").diagnose(
        Incident(
            error_text=(
                "Fecha registro no está dentro del intervalo de fechas de "
                "registro permitidas."
            ),
            call_stack=(
                '"Sales-Post"(CodeUnit 80).CheckSalesDocument line 2 - Base '
                "Application by Microsoft version 27.0.38460.40242"
            ),
        )
    )

    assert report.confidence == "alta"
    assert "aplicación base Microsoft" in report.summary
    assert report.source_matches
    assert ".app!" in report.source_matches[0].path
    assert "Eventos.Al" not in report.source_matches[0].path
