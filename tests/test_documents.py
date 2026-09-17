from agentebc.documents import DocumentNotFoundError, DocumentReader


class FakeClient:
    def __init__(self, responses):
        self.responses = responses
        self.endpoints: list[str] = []

    def get(self, endpoint: str):
        self.endpoints.append(endpoint)
        return self.responses.pop(0)


def test_lists_companies() -> None:
    client = FakeClient(
        [{"value": [{"Name": "Malla"}, {"Name": "Piscis"}, {"Name": "Malla"}]}]
    )

    assert DocumentReader(client).list_companies() == ["Malla", "Piscis"]


def test_finds_sales_invoice_and_encodes_query() -> None:
    client = FakeClient(
        [
            {
                "value": [
                    {
                        "id": "id-1",
                        "number": "P4941",
                        "documentType": "Invoice",
                        "status": "Open",
                        "postingDate": "2024-11-01",
                    }
                ]
            }
        ]
    )

    document = DocumentReader(client).find_invoice(
        company="PISCIS DOS TRES HACHE, S.L.",
        kind="sales",
        number="P4941",
    )

    assert document.number == "P4941"
    assert document.kind == "sales"
    assert client.endpoints[0].startswith("salesDocuments?")
    assert "company=PISCIS+DOS+TRES+HACHE%2C+S.L." in client.endpoints[0]


def test_raises_when_invoice_does_not_exist() -> None:
    client = FakeClient([{"value": []}])

    try:
        DocumentReader(client).find_invoice(
            company="Malla",
            kind="purchase",
            number="X1",
        )
    except DocumentNotFoundError as exc:
        assert "X1" in str(exc)
    else:
        raise AssertionError("Debía indicar que la factura no existe")
