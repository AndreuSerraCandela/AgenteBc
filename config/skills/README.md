# Skills del worker

Un **skill** (`.skill.json`) empaqueta un trabajo de registro, filtros OData,
campos del informe y destinatarios de correo (mail e IA: próximas fases).

## Skill real: Malla Publicidad

`malla_publicidad_facturar_ventas.skill.json` refleja el criterio del usuario:

- Empresa: Malla Publicidad
- Facturas de venta → acción `registrar_factura`
- `esperarOrdenCliente eq false` (nombre OData a confirmar en vuestro BC)
- Fecha registro: mes en curso **hasta hoy** (`month_to_today`); use
  `current_month` en el editor si el cierre es **hasta fin de mes**

## Nombres OData

Si el listado OData falla, abra en el navegador (con sesión BC):

`http://localhost:7048/BC270/ODataV4/$metadata`

o pruebe en el skill los nombres de campo que exponga `salesDocuments`.

En **Editor de skills** puede indicar el **servicio OData** (entity set, p. ej.
`salesDocuments` o una API/page que publiquéis). Si lo deja vacío, usa el del
catálogo AgenteBc para el tipo de ficha.

**Cargar campos OData desde BC** rellena desplegables con las propiedades de
*ese* servicio (desde un documento de ejemplo).

Los **diálogos al registrar** (confirmar registro, «¿abrir factura registrada?» → No)
están en el catálogo `document_types.json` (acción `registrar_factura`), no en el
skill.

Con un **servicio OData distinto** al del catálogo (p. ej. `FacturaVenta`):

- No se aplican filtros del catálogo como `documentType=Invoice` (suelen no
  existir en APIs propias).
- Indique el **nombre OData real** del campo de fecha si no es `postingDate`.
- Elija **campo clave** (p. ej. `No` en APIs Malla), **fecha** y **columnas
  del informe** desde la lista OData cargada.
- **Filtros extra:** varias líneas `campo | valor`. En campos texto BC (Sí/No)
  use `No`, no `false`. Booleanos OData reales: `false`/`true` o `bool:false`.
- **Después de acción (opcional):** pasos tras la acción principal. Hoy: consulta
  OData (`after_action_steps` con `kind: odata_query`, `expect: at_least_one_row`).
  Filtro con `{number}` = nº del documento. Para volcar un valor al informe, defina
  la columna en el informe (`etiqueta | clave |` OData vacío) y en el paso
  `save_for_report: { odata_field, report_key }` (la clave debe existir en el informe).
  Skills antiguos con `odata_confirmation` se migran al cargar.
- **Informe:** igual que filtros — elija campo OData, título y «Añadir columna»;
  las líneas activas son editables (`etiqueta | clave | campo OData`).

Edite el skill con **Worker → Editor de skills** o el JSON en
`%LOCALAPPDATA%\AgenteBC\worker\skills\`.

## Reparto

Copie el `.skill.json` junto al `AgenteBcWorker.exe` o en la carpeta `skills`
del usuario. No hace falta recompilar el exe para cambiar un skill.
