from pathlib import Path

from agentebc.source_index import SourceIndex


def test_finds_error_in_al_source(tmp_path: Path) -> None:
    source = tmp_path / "InvoicePosting.Codeunit.al"
    source.write_text(
        """
codeunit 50100 "Invoice Posting"
{
    procedure CheckProject()
    begin
        Error('El proyecto es obligatorio');
    end;
}
""",
        encoding="utf-8",
    )

    matches = SourceIndex(tmp_path).search("El proyecto es obligatorio")

    assert len(matches) == 1
    assert matches[0].path == "InvoicePosting.Codeunit.al"
    assert matches[0].score == 1.0
    assert "Error('El proyecto es obligatorio')" in matches[0].excerpt


def test_returns_no_matches_for_unrelated_error(tmp_path: Path) -> None:
    (tmp_path / "Code.al").write_text("procedure Example(); begin end;", encoding="utf-8")

    assert SourceIndex(tmp_path).search("No existe dimensión") == []
