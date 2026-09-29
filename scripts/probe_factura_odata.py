"""Inspecciona campos OData de una factura en FacturaVenta."""
from __future__ import annotations

import json
import sys

from agentebc.bc_client import BusinessCentralReadClient
from agentebc.config import Settings
from agentebc.documents import bc_urlencode, _odata_literal


def main() -> None:
    number = sys.argv[1] if len(sys.argv) > 1 else "ML257397"
    client = BusinessCentralReadClient(Settings.from_environment())
    query = bc_urlencode(
        {
            "company": "Malla Publicidad",
            "$filter": f"No eq {_odata_literal(number)}",
            "$top": "1",
        }
    )
    data = client.get(f"FacturaVenta?{query}")
    rows = data.get("value", []) if isinstance(data, dict) else []
    if not rows:
        print("Sin filas")
        return
    row = rows[0]
    keys = ("No", "Status", "Posting_No", "Esperar_Orden_Cliente", "Posting_Date")
    slim = {k: row.get(k) for k in keys if k in row}
    print(json.dumps(slim or row, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
