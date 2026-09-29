from agentebc.bc_client import BusinessCentralReadClient
from agentebc.config import Settings
from agentebc.documents import bc_urlencode

c = BusinessCentralReadClient(Settings.from_environment())
q = bc_urlencode(
    {
        "company": "Malla Publicidad",
        "$filter": "Posting_No ne ''",
        "$select": "No,Status,Posting_No,Esperar_Orden_Cliente",
        "$top": "3",
    }
)
rows = c.get(f"FacturaVenta?{q}").get("value", [])
for r in rows:
    print(r)
