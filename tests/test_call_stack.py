from agentebc.call_stack import extract_call_stack_text, parse_call_stack_frames
from agentebc.diagnosis import DiagnosticService
from agentebc.models import Incident
from agentebc.source_index import SourceIndex


def test_parses_business_central_call_stack_frame() -> None:
    stack = (
        '"GestionFacturación"(Codeunit 50010).Crear_Facturas_Terminos line 634'
    )

    frames = parse_call_stack_frames(stack)

    assert len(frames) == 1
    assert frames[0].object_name == "GestionFacturación"
    assert frames[0].procedure == "Crear_Facturas_Terminos"
    assert frames[0].line == 634


def test_parses_unquoted_business_central_call_stack_frame() -> None:
    stack = (
        "ControldeEventosTables(CodeUnit 50016).Tabla36_EstadoOnValidate line 30 "
        "- Funciones by Grupo Malla"
    )

    frames = parse_call_stack_frames(stack)

    assert len(frames) == 1
    assert frames[0].object_name == "ControldeEventosTables"
    assert frames[0].procedure == "Tabla36_EstadoOnValidate"
    assert frames[0].line == 30


def test_extracts_call_stack_from_shared_details_text() -> None:
    details = (
        "Ya se han creado los borradores de facturas de este contrato.\n"
        "Compartir detalles\n"
        '"GestionFacturación"(Codeunit 50010).Crear_Facturas_Terminos line 634\n'
        "¿Le resultó útil esta información?"
    )

    stack = extract_call_stack_text(details)

    assert stack is not None
    assert "Crear_Facturas_Terminos line 634" in stack


def test_search_call_stack_prefers_exact_line(tmp_path) -> None:
    source = tmp_path / "Funciones" / "src" / "codeunit"
    source.mkdir(parents=True)
    file_path = source / "GestionFacturación.Al"
    file_path.write_text(
        "\n".join(
            [
                "codeunit 50010 GestionFacturación",
                "procedure Crear_Facturas_Terminos()",
                "begin",
                "    if Fra.FindFirst() then",
                "        ERROR(Text006);",
                "end;",
            ]
        ),
        encoding="utf-8",
    )

    matches = SourceIndex(tmp_path).search_call_stack(
        '"GestionFacturación"(Codeunit 50010).Crear_Facturas_Terminos line 5'
    )

    assert matches
    assert matches[0].path.endswith("GestionFacturación.Al")
    assert matches[0].line == 5


def test_search_call_stack_ignores_unrelated_files_at_same_line(tmp_path) -> None:
    decoy = tmp_path / "AiBc" / "src" / "buffer"
    decoy.mkdir(parents=True)
    (decoy / "PurchaseLineImportBuffer.Table.al").write_text(
        "\n".join(
            [
                "// table 50101",
                "// fields",
                "//     field(10; Type; Enum)",
                "//     {",
                "//         Caption = 'Tipo';",
                "//     }",
            ]
        ),
        encoding="utf-8",
    )

    source = tmp_path / "Funciones" / "src" / "codeunit"
    source.mkdir(parents=True)
    lines = [
        '/// Codeunit Gestion Facturación (ID 50001).',
        'codeunit 50001 "Gestion Facturación"',
        "{",
        "    PROCEDURE Crear_Facturas_Terminos();",
        "    BEGIN",
    ]
    lines.extend(f"        // paso {step}" for step in range(1, 13))
    lines.extend(
        [
            '        if (rCab."Creada su facturación") THEN',
            "            ERROR(Text006);",
            "    END;",
            "}",
        ]
    )
    (source / "GestionFacturación.Al").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    matches = SourceIndex(tmp_path).search_call_stack(
        '"Gestion Facturación"(CodeUnit 50001).Crear_Facturas_Terminos line 15'
    )

    assert matches
    assert matches[0].path.endswith("GestionFacturación.Al")
    assert matches[0].line == 19
    assert "ERROR(Text006)" in matches[0].excerpt
    assert all("PurchaseLineImportBuffer" not in match.path for match in matches)


def test_parses_call_stack_with_spaced_object_name() -> None:
    stack = (
        '"Gestion Facturación"(CodeUnit 50001).Crear_Facturas_Terminos line 15'
    )

    frames = parse_call_stack_frames(stack)

    assert len(frames) == 1
    assert frames[0].object_name == "Gestion Facturación"
    assert frames[0].object_id == 50001
    assert frames[0].procedure == "Crear_Facturas_Terminos"
    assert frames[0].line == 15


def test_search_call_stack_ignores_pageextension_named_like_base_page(tmp_path) -> None:
    extensions = tmp_path / "Funciones" / "src" / "page" / "pageextension" / "Sales"
    extensions.mkdir(parents=True)
    (extensions / "SalesInvoice.al").write_text(
        "\n".join(
            [
                'pageextension 80140 SalesInvoice extends "Sales Invoice"',
                "{",
                "    layout",
                "    {",
                "    }",
                "}",
            ]
        ),
        encoding="utf-8",
    )
    table_ext = tmp_path / "EDI" / "Table" / "Tableextension"
    table_ext.mkdir(parents=True)
    (table_ext / "Tab112-Ext50212.SalesInvoiceHeader.al").write_text(
        "\n".join(
            [
                'tableextension 90212 "SalesInvoiceHeader" extends "Sales Invoice Header"',
                "{",
                "    fields",
                "    {",
                "    }",
                "}",
            ]
        ),
        encoding="utf-8",
    )

    stack = (
        '"Sales-Post"(CodeUnit 80).CheckSalesDocument line 22 - Base Application '
        'by Microsoft version 27.0.38460.40242'
        '"Sales Invoice"(Page 43).ShowPreview line 5 - Base Application '
        "by Microsoft version 27.0.38460.40242"
    )
    matches = SourceIndex(tmp_path).search_call_stack(stack)

    assert matches == []


def test_search_event_subscribers_for_base_application_object(tmp_path) -> None:
    codeunit = tmp_path / "Funciones" / "src" / "codeunit"
    codeunit.mkdir(parents=True)
    (codeunit / "Eventos.Al").write_text(
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

    frames = parse_call_stack_frames(
        '"Sales-Post"(CodeUnit 80).CheckSalesDocument line 22'
    )
    matches = SourceIndex(tmp_path).search_event_subscribers(frames[0])

    assert len(matches) == 1
    assert matches[0].path.endswith("Eventos.Al")
    assert "Sales-Post" in matches[0].excerpt


def test_diagnosis_uses_event_subscribers_when_base_app_has_no_sources(
    tmp_path,
) -> None:
    codeunit = tmp_path / "Funciones" / "src" / "codeunit"
    codeunit.mkdir(parents=True)
    (codeunit / "Eventos.Al").write_text(
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

    report = DiagnosticService(tmp_path).diagnose(
        Incident(
            error_text=(
                "Fecha registro no está dentro del intervalo de fechas de "
                "registro permitidas."
            ),
            call_stack=(
                '"Sales-Post"(CodeUnit 80).CheckSalesDocument line 22 - Base '
                "Application by Microsoft version 27.0.38460.40242"
            ),
        )
    )

    assert report.confidence == "media"
    assert "aplicación base" in report.summary.casefold()
    assert report.source_matches
    assert report.source_matches[0].path.endswith("Eventos.Al")


def test_diagnosis_uses_call_stack_when_available(tmp_path) -> None:
    source = tmp_path / "Funciones" / "src" / "codeunit"
    source.mkdir(parents=True)
    (source / "GestionFacturación.Al").write_text(
        "\n".join(
            [
                "codeunit 50010 GestionFacturación",
                "procedure Crear_Facturas_Terminos()",
                "begin",
                "    ERROR(Text006);",
                "end;",
            ]
        ),
        encoding="utf-8",
    )

    report = DiagnosticService(tmp_path).diagnose(
        Incident(
            error_text="Ya se han creado los borradores de facturas de este contrato.",
            call_stack=(
                '"GestionFacturación"(Codeunit 50010).Crear_Facturas_Terminos line 4'
            ),
        )
    )

    assert report.confidence == "alta"
    assert "pila de llamadas" in report.summary.casefold()
    assert report.source_matches
    assert report.source_matches[0].line == 4
