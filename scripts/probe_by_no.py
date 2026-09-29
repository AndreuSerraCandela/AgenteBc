from agentebc.bc_client import BusinessCentralReadClient
from agentebc.config import Settings
from agentebc.documents import bc_urlencode, _odata_literal
import json
import sys

n = sys.argv[1]
c = BusinessCentralReadClient(Settings.from_environment())
q = bc_urlencode(
    {
        "company": "Malla Publicidad",
        "$filter": f"No eq {_odata_literal(n)}",
        "$select": "No,Status",
        "$top": "1",
    }
)
rows = c.get(f"FacturaVenta?{q}").get("value", [])
print(json.dumps(rows, indent=2))
