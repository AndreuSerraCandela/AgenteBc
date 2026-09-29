from __future__ import annotations

import json
from collections.abc import Callable

from flask import Flask, jsonify, redirect, render_template_string, request, url_for

from agentebc.document_types import DocumentTypeRegistry

from .odata_fields import (
    fetch_odata_sample_row,
    suggest_boolean_fields,
    suggest_contract_fields,
    suggest_date_fields,
    suggest_key_fields,
    infer_field_types,
    sample_field_values,
)
from .paths import WorkerPaths
from .preview import build_job_preview
from .skills import (
    SkillStore,
    WorkerSkill,
    report_fields_to_lines,
    skill_from_builder_form,
)
from .field_edits import DEFAULT_POSTING_DATE_FIELD_LABEL
from .job_spec import extra_odata_filters_to_lines
from agentebc.bc_client import BusinessCentralReadClient, BusinessCentralReadError
from agentebc.config import Settings

_EDITOR_PAGE = """
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <title>Editor de skills · AgenteBc Worker</title>
  <style>
    body { font-family: Segoe UI, sans-serif; max-width: 960px; margin: 24px auto; padding: 0 16px; }
    section { border: 1px solid #ccc; border-radius: 6px; padding: 16px; margin-bottom: 16px; }
    label { display: block; margin-top: 10px; font-weight: 600; }
    input, select, textarea { width: 100%; padding: 8px; box-sizing: border-box; }
    .hint { font-size: 13px; color: #555; font-weight: normal; }
    label.inline { display: flex; align-items: center; gap: 8px; font-weight: normal; }
    label.inline input { width: auto; }
    button { margin-top: 14px; padding: 10px 16px; background: #0067b8; color: #fff; border: 0; cursor: pointer; }
    .error { color: #a80000; }
    pre { background: #f4f4f4; padding: 12px; overflow: auto; white-space: pre-wrap; }
    a { color: #0067b8; }
  </style>
</head>
<body>
  <p><a href="/">← Volver al worker</a></p>
  <h1>Editor de skills</h1>
  <p>Cree un skill sin programar. Se guarda en su carpeta de usuario (no modifica el repo).</p>

  {% if error %}<p class="error">{{ error }}</p>{% endif %}
  {% if saved %}<p><strong>Guardado:</strong> {{ saved }}</p>{% endif %}

  <section>
    <h2>Skills instalados</h2>
    <ul>
      {% for s in skills %}
      <li>
        <strong>{{ s.label }}</strong> ({{ s.id }}) — {{ s.description or "Sin descripción" }}
        — <a href="{{ url_for('skill_editor', skill_id=s.id) }}">Editar</a>
      </li>
      {% else %}
      <li>No hay skills cargados.</li>
      {% endfor %}
    </ul>
  </section>

  <section>
    <h2>Nuevo / editar skill</h2>
    <form method="post" action="{{ url_for('skill_save') }}">
      <label>Identificador (id)</label>
      <input name="skill_id" value="{{ form.skill_id }}" placeholder="malla_publicidad_facturar_ventas">
      <label>Nombre visible</label>
      <input name="label" required value="{{ form.label }}" placeholder="Facturar ventas Malla Publicidad">
      <label>Descripción</label>
      <textarea name="description" rows="2">{{ form.description }}</textarea>
      <label>Empresa BC <span class="hint">(opcional si va en connection o la elige el usuario)</span></label>
      <input name="company" value="{{ form.company }}" placeholder="Malla Publicidad">
      <h3>Conexión BC en el skill <span class="hint">(reparto sin .env local)</span></h3>
      <label>OData base URL</label>
      <input name="conn_odata_base_url" value="{{ form.conn_odata_base_url }}"
             placeholder="http://servidor:7048/BC270/ODataV4">
      <label>Cliente web BC URL</label>
      <input name="conn_web_base_url" value="{{ form.conn_web_base_url }}"
             placeholder="http://servidor:8080/BC270">
      <label>Empresa por defecto (connection)</label>
      <input name="conn_company" value="{{ form.conn_company }}" placeholder="Opcional">
      <label>Tipo de documento</label>
      <select name="type_id" id="type_id" required>
        {% for t in document_types %}
        <option value="{{ t.id }}" data-odata-service="{{ t.odata_service }}"
          {% if form.type_id == t.id %}selected{% endif %}>{{ t.label }} ({{ t.id }})</option>
        {% endfor %}
      </select>
      <label>Servicio OData <span class="hint">(entity set; vacío = el del tipo en catálogo)</span></label>
      <input name="odata_service" id="odata_service" value="{{ form.odata_service }}"
             placeholder="salesDocuments">
      <p id="odata-service-hint" class="hint"></p>
      <label>Acción</label>
      <select name="action_id" required>
        {% for t in document_types %}
          {% for a in t.actions %}
        <option value="{{ a.id }}" data-type="{{ t.id }}"
          {% if form.action_id == a.id and form.type_id == t.id %}selected{% endif %}>
          {{ t.label }} → {{ a.label }} ({{ a.id }})
        </option>
          {% endfor %}
        {% endfor %}
      </select>
      <h3 style="margin-top:18px;background:#e8f4fc;padding:10px;border-radius:6px;">Antes de acción (ficha BC)</h3>
      <label><strong>Fecha registro</strong> en la ficha antes de ejecutar la acción</label>
      <select name="posting_date_before_register">
        <option value="" {% if not form.posting_date_before_register %}selected{% endif %}>No cambiar</option>
        <option value="today" {% if form.posting_date_before_register == 'today' %}selected{% endif %}>Poner fecha de hoy</option>
        <option value="end_of_month" {% if form.posting_date_before_register == 'end_of_month' %}selected{% endif %}>Poner fin de mes en curso</option>
      </select>
      <p class="hint">Útil cuando BC rechaza la serie (p. ej. V-FAC+) por fecha antigua. Valores dinámicos: <code>today</code>, <code>end_of_month</code>.</p>
      <label>Otras ediciones de campo <span class="hint">(opcional; una línea: Etiqueta BC | valor o today/end_of_month)</span></label>
      <textarea name="before_action_field_edits_lines" rows="2" spellcheck="false"
                placeholder="Fecha registro | today">{{ form.before_action_field_edits_lines }}</textarea>
      <label>Rango fecha registro (listado OData)</label>
      <select name="date_dynamic">
        <option value="month_to_today" {% if form.date_dynamic == 'month_to_today' %}selected{% endif %}>Mes en curso hasta hoy</option>
        <option value="current_month" {% if form.date_dynamic == 'current_month' %}selected{% endif %}>Mes en curso completo (hasta fin de mes)</option>
        <option value="current_year" {% if form.date_dynamic == 'current_year' %}selected{% endif %}>Año en curso</option>
      </select>
      <p class="hint">Indique el <strong>servicio OData</strong> (p. ej. FacturaVenta) y pulse cargar. Los desplegables se rellenan desde un documento de ejemplo en BC.</p>
      <button type="button" id="load-odata-fields" style="margin-top:0">Cargar campos OData desde BC</button>
      <p id="odata-status" class="hint"></p>
      <input type="hidden" name="odata_field_types_json" id="odata_field_types_json" value="">
      <label>Campo OData nº documento (clave) <span class="hint">(identifica cada fila y la automatización web)</span></label>
      <select name="document_key_odata" id="document_key_odata">
        {% if form.document_key_odata %}
        <option value="{{ form.document_key_odata }}" selected>{{ form.document_key_odata }}</option>
        {% endif %}
      </select>
      <label>Campo OData fecha</label>
      <select name="date_odata_field" id="date_odata_field">
        {% if form.date_odata_field %}
        <option value="{{ form.date_odata_field }}" selected>{{ form.date_odata_field }}</option>
        {% endif %}
      </select>
      <label>Añadir filtro OData <span class="hint">(elija campo y valor; no hace falta escribir nombres a mano)</span></label>
      <div style="display:flex;flex-wrap:wrap;gap:8px;align-items:flex-end">
        <div style="flex:2;min-width:200px">
          <span class="hint">Campo</span>
          <select id="filter_add_field" style="margin-top:4px"></select>
        </div>
        <div style="flex:1;min-width:160px">
          <span class="hint">Valor</span>
          <select id="filter_add_value_select" style="margin-top:4px;display:none"></select>
          <input id="filter_add_value_text" list="filter_value_suggestions" style="margin-top:4px" placeholder="valor">
          <datalist id="filter_value_suggestions"></datalist>
        </div>
        <button type="button" id="filter_add_btn" style="margin-top:0">Añadir filtro</button>
      </div>
      <p id="filter-field-hint" class="hint"></p>
      <label>Filtros activos <span class="hint">(se guardan al guardar el skill; puede editar las líneas)</span></label>
      <textarea name="extra_filter_lines" id="extra_filter_lines" rows="3" spellcheck="false"
                placeholder="Esperar_Orden_Cliente | No">{{ form.extra_filter_lines }}</textarea>
      <label>Añadir columna al informe <span class="hint">(mismo criterio que los filtros: elija campo y título)</span></label>
      <div style="display:flex;flex-wrap:wrap;gap:8px;align-items:flex-end">
        <div style="flex:2;min-width:200px">
          <span class="hint">Campo OData</span>
          <select id="report_add_field" style="margin-top:4px"></select>
        </div>
        <div style="flex:2;min-width:200px">
          <span class="hint">Título en informe</span>
          <input id="report_add_label" style="margin-top:4px" placeholder="p. ej. Nº contrato">
        </div>
        <button type="button" id="report_add_btn" style="margin-top:0">Añadir columna</button>
      </div>
      <p id="report-column-hint" class="hint">El nº documento usa el campo clave; no hace falta añadirlo aquí.</p>
      <label>Columnas del informe activas <span class="hint">(etiqueta | clave | campo OData; OData vacío si se rellena después de acción)</span></label>
      <textarea name="report_fields_lines" id="report_fields_lines" rows="4" spellcheck="false">{{ form.report_fields_lines }}</textarea>
      <h3 style="margin-top:18px;background:#f0f8e8;padding:10px;border-radius:6px;">Después de acción <span class="hint">(opcional)</span></h3>
      <p class="hint">Consulta OData tras la acción (p. ej. comprobar fila en
        <code>FacturasRegistradas</code>). Filtro con <code>{number}</code> = nº del documento del lote.
        Para volcar un valor al informe, defina antes la columna arriba y elija su <strong>clave</strong>.</p>
      <label>Servicio OData (paso después de acción)</label>
      <input name="after_odata_service" id="after_odata_service" value="{{ form.after_odata_service }}"
             placeholder="FacturasRegistradas">
      <button type="button" id="load-after-odata-fields" style="margin-top:8px">Cargar campos OData (después de acción)</button>
      <p id="after-odata-status" class="hint"></p>
      <label>Campo filtro OData + valor</label>
      <div style="display:flex;flex-wrap:wrap;gap:8px;">
        <select name="after_filter_field" id="after_filter_field" style="flex:1;min-width:160px">
          {% if form.after_filter_field %}
          <option value="{{ form.after_filter_field }}" selected>{{ form.after_filter_field }}</option>
          {% endif %}
        </select>
        <input name="after_filter_value" style="flex:1;min-width:160px"
               value="{{ form.after_filter_value }}" placeholder="{number}">
      </div>
      <label>Filtros extra del paso OData</label>
      <textarea name="after_extra_filter_lines" rows="2" spellcheck="false"
                placeholder="">{{ form.after_extra_filter_lines }}</textarea>
      <label>Guardar en informe <span class="hint">(opcional; columna ya definida arriba)</span></label>
      <div style="display:flex;flex-wrap:wrap;gap:8px;">
        <select name="after_save_odata_field" id="after_save_odata_field" style="flex:1;min-width:160px">
          {% if form.after_save_odata_field %}
          <option value="{{ form.after_save_odata_field }}" selected>{{ form.after_save_odata_field }}</option>
          {% else %}
          <option value="">— Campo OData a leer —</option>
          {% endif %}
        </select>
        <input name="after_save_report_key" style="flex:1;min-width:160px"
               value="{{ form.after_save_report_key }}" placeholder="Clave columna informe (p. ej. posted_no)">
      </div>
      <label>Correos informe <span class="hint">(separados por ; o ,)</span></label>
      <textarea name="notify_emails" rows="2">{{ form.notify_emails }}</textarea>
      <label>Límite documentos</label>
      <input name="limit" type="number" value="{{ form.limit }}" min="1" max="5000">
      <button type="submit">Guardar skill</button>
    </form>
    {% if form.skill_id %}
    <form method="post" action="{{ url_for('skill_share') }}" style="margin-top:12px;">
      <input type="hidden" name="skill_id" value="{{ form.skill_id }}">
      <label>Nota para el buzón (opcional)</label>
      <input name="share_note" placeholder="Para contabilidad Malla">
      <button type="submit">Enviar skill al buzón</button>
    </form>
    {% endif %}
    <form method="post" action="{{ url_for('skill_preview') }}" style="margin-top:8px">
      <input type="hidden" name="skill_id" value="{{ form.skill_id }}">
      <button type="submit" style="background:#555">Preview OData (skill guardado)</button>
    </form>
  </section>

  {% if preview_json %}
  <section>
    <h2>Vista previa</h2>
    <pre>{{ preview_json }}</pre>
  </section>
  {% endif %}
  <script>
    let odataFieldTypes = {};
    let odataSampleValues = {};
    let odataFieldList = [];
    const initialDocumentKey = {{ form.document_key_odata | tojson }};
    const initialDate = {{ form.date_odata_field | tojson }};
    const initialAfterFilter = {{ form.after_filter_field | tojson }};
    const initialAfterSaveOdata = {{ form.after_save_odata_field | tojson }};
    function fillSelect(selectId, fields, suggested, current, emptyLabel) {
      const sel = document.getElementById(selectId);
      sel.innerHTML = "";
      const empty = document.createElement("option");
      empty.value = "";
      empty.textContent = emptyLabel || "—";
      sel.appendChild(empty);
      const addGroup = (label, names) => {
        if (!names.length) return;
        const group = document.createElement("optgroup");
        group.label = label;
        for (const name of names) {
          const opt = document.createElement("option");
          opt.value = name;
          opt.textContent = name;
          if (name === current) opt.selected = true;
          group.appendChild(opt);
        }
        sel.appendChild(group);
      };
      const suggestedSet = new Set(suggested);
      const rest = fields.filter((f) => !suggestedSet.has(f));
      addGroup("Sugeridos", suggested);
      addGroup("Todos los campos", rest.length ? rest : fields);
      if (current && !fields.includes(current)) {
        const opt = document.createElement("option");
        opt.value = current;
        opt.textContent = current + " (guardado)";
        opt.selected = true;
        sel.insertBefore(opt, sel.firstChild.nextSibling);
      }
    }

    function updateFilterValueEditor() {
      const field = document.getElementById("filter_add_field").value;
      const hint = document.getElementById("filter-field-hint");
      const sel = document.getElementById("filter_add_value_select");
      const text = document.getElementById("filter_add_value_text");
      const datalist = document.getElementById("filter_value_suggestions");
      datalist.innerHTML = "";
      if (!field) {
        hint.textContent = "Cargue campos OData y elija un campo de filtro.";
        sel.style.display = "none";
        text.style.display = "";
        return;
      }
      const ftype = odataFieldTypes[field] || "string";
      const sample = odataSampleValues[field] ?? "";
      hint.textContent = "Tipo OData inferido: " + ftype
        + (sample !== "" ? " · ejemplo en BC: «" + sample + "»" : "");
      const addOpt = (v) => {
        const o = document.createElement("option");
        o.value = v;
        datalist.appendChild(o);
      };
      ["No", "Yes", "Sí", "Si", "(vacío)"].forEach(addOpt);
      if (sample) addOpt(sample);
      if (ftype === "boolean") {
        sel.innerHTML = "";
        for (const v of ["false", "true"]) {
          const o = document.createElement("option");
          o.value = v;
          o.textContent = v;
          sel.appendChild(o);
        }
        sel.style.display = "";
        text.style.display = "none";
        sel.value = sample === "true" ? "true" : "false";
      } else {
        sel.style.display = "none";
        text.style.display = "";
        text.value = sample === "No" || sample === "Yes" ? sample : (sample || "No");
      }
    }

    function upsertExtraFilterLine(field, value) {
      const ta = document.getElementById("extra_filter_lines");
      const lines = ta.value.split("\\n");
      const out = [];
      let replaced = false;
      for (const raw of lines) {
        const line = raw.trim();
        if (!line || line.startsWith("#")) {
          out.push(raw);
          continue;
        }
        const name = line.split("|")[0].trim();
        if (name === field) {
          out.push(field + " | " + value);
          replaced = true;
        } else {
          out.push(raw);
        }
      }
      if (!replaced) {
        out.push(field + " | " + value);
      }
      ta.value = out.join("\\n").trim();
    }

    function appendFilterFromPicker() {
      const field = document.getElementById("filter_add_field").value;
      if (!field) return;
      const ftype = odataFieldTypes[field] || "string";
      let value;
      if (ftype === "boolean") {
        value = document.getElementById("filter_add_value_select").value;
      } else {
        value = document.getElementById("filter_add_value_text").value.trim();
        if (value === "(vacío)") value = "(vacío)";
      }
      if (!value && value !== "") return;
      upsertExtraFilterLine(field, value);
    }

    async function fetchOdataFieldsFromBc(odataService) {
      const typeId = document.querySelector('[name="type_id"]').value;
      const company = document.querySelector('[name="company"]').value.trim();
      if (!company) {
        throw new Error("Indique la empresa BC antes de cargar campos.");
      }
      const qs = new URLSearchParams({ type_id: typeId, company });
      if (odataService) qs.set("odata_service", odataService);
      const response = await fetch("/api/odata-fields?" + qs.toString());
      const raw = await response.text();
      let data;
      try {
        data = JSON.parse(raw);
      } catch (_) {
        throw new Error(raw.slice(0, 240) || "Respuesta no JSON del servidor");
      }
      if (!response.ok) throw new Error(data.error || "No se pudieron cargar campos");
      return data;
    }

    async function loadOdataFields() {
      const status = document.getElementById("odata-status");
      status.textContent = "Cargando campos OData…";
      try {
        const odataService = document.getElementById("odata_service").value.trim();
        const data = await fetchOdataFieldsFromBc(odataService);
        odataFieldTypes = data.field_types || {};
        odataSampleValues = data.sample_values || {};
        odataFieldList = data.fields || [];
        document.getElementById("odata_field_types_json").value = JSON.stringify(odataFieldTypes);
        fillSelect(
          "document_key_odata",
          data.fields,
          data.suggested_key || [],
          document.getElementById("document_key_odata").value || initialDocumentKey,
          "— Catálogo: number —"
        );
        fillSelect(
          "date_odata_field",
          data.fields,
          data.suggested_date || [],
          document.getElementById("date_odata_field").value || initialDate,
          "— Catálogo: posting_date —"
        );
        fillSelect(
          "filter_add_field",
          data.fields,
          data.suggested_boolean || [],
          "",
          "— Elija campo —"
        );
        fillSelect(
          "report_add_field",
          data.fields,
          data.suggested_report || [],
          "",
          "— Elija campo —"
        );
        updateFilterValueEditor();
        updateReportColumnEditor();
        status.textContent = data.fields.length + " campos en «" + data.odata_service + "» (1 documento de ejemplo).";
        status.style.color = "#555";
      } catch (err) {
        status.textContent = "Error: " + (err.message || String(err));
        status.style.color = "#a80000";
      }
    }

    async function loadAfterOdataFields() {
      const status = document.getElementById("after-odata-status");
      const service = document.getElementById("after_odata_service").value.trim();
      if (!service) {
        status.textContent = "Indique el servicio OData del paso después de acción.";
        status.style.color = "#a80000";
        return;
      }
      status.textContent = "Cargando campos OData del paso después de acción…";
      status.style.color = "#555";
      try {
        const data = await fetchOdataFieldsFromBc(service);
        fillSelect(
          "after_filter_field",
          data.fields,
          data.suggested_key || [],
          document.getElementById("after_filter_field").value || initialAfterFilter,
          "— Campo filtro —"
        );
        fillSelect(
          "after_save_odata_field",
          data.fields,
          data.suggested_key || [],
          document.getElementById("after_save_odata_field").value || initialAfterSaveOdata,
          "— Campo OData a leer —"
        );
        status.textContent = data.fields.length + " campos en «" + data.odata_service + "» (paso después de acción).";
      } catch (err) {
        status.textContent = "Error: " + (err.message || String(err));
        status.style.color = "#a80000";
      }
    }

    function syncOdataServiceHint() {
      const sel = document.getElementById("type_id");
      const opt = sel.options[sel.selectedIndex];
      const catalog = opt ? opt.dataset.odataService : "";
      const input = document.getElementById("odata_service");
      const hint = document.getElementById("odata-service-hint");
      if (!input.value.trim() && catalog) {
        input.placeholder = catalog;
      }
      hint.textContent = catalog
        ? "Catálogo AgenteBc para este tipo: «" + catalog + "». Escriba otro servicio si publicó una API/page OData propia."
        : "";
    }

    function reportKeyFromOdata(odata) {
      return odata.replace(/[^a-zA-Z0-9_]+/g, "_").replace(/^_|_$/g, "").toLowerCase().slice(0, 40) || "field";
    }

    function reportLabelFromOdata(odata) {
      return odata.replace(/_x00BA__/gi, "º ").replace(/_/g, " ").trim()
        .replace(/^./, (c) => c.toUpperCase());
    }

    function updateReportColumnEditor() {
      const field = document.getElementById("report_add_field").value;
      const labelInput = document.getElementById("report_add_label");
      const hint = document.getElementById("report-column-hint");
      if (!field) {
        hint.textContent = "Cargue campos OData y elija una columna para el informe.";
        return;
      }
      const keyField = document.getElementById("document_key_odata").value.trim();
      if (field === keyField) {
        hint.textContent = "Este campo ya es la clave (nº documento); elija otra columna.";
      } else {
        const sample = odataSampleValues[field];
        hint.textContent = "Clave interna sugerida: «" + reportKeyFromOdata(field) + "»"
          + (sample !== undefined && sample !== "" ? " · ejemplo BC: «" + sample + "»" : "");
      }
      if (!labelInput.value.trim() || labelInput.dataset.auto === "1") {
        labelInput.value = reportLabelFromOdata(field);
        labelInput.dataset.auto = "1";
      }
    }

    function upsertReportColumnLine(label, key, odata) {
      const ta = document.getElementById("report_fields_lines");
      const lines = ta.value.split("\\n");
      const out = [];
      let replaced = false;
      const line = label + " | " + key + " | " + odata;
      for (const raw of lines) {
        const trimmed = raw.trim();
        if (!trimmed || trimmed.startsWith("#")) {
          out.push(raw);
          continue;
        }
        const parts = trimmed.split("|").map((p) => p.trim());
        const existingOdata = parts.length >= 3 ? parts[2] : parts[parts.length - 1];
        if (existingOdata === odata) {
          out.push(line);
          replaced = true;
        } else {
          out.push(raw);
        }
      }
      if (!replaced) {
        out.push(line);
      }
      ta.value = out.join("\\n").trim();
    }

    function appendReportFromPicker() {
      const odata = document.getElementById("report_add_field").value;
      if (!odata) return;
      const keyField = document.getElementById("document_key_odata").value.trim();
      if (odata === keyField) return;
      const label = document.getElementById("report_add_label").value.trim()
        || reportLabelFromOdata(odata);
      const key = reportKeyFromOdata(odata);
      upsertReportColumnLine(label, key, odata);
    }

    document.getElementById("report_add_btn").addEventListener("click", appendReportFromPicker);
    document.getElementById("report_add_field").addEventListener("change", () => {
      document.getElementById("report_add_label").dataset.auto = "1";
      updateReportColumnEditor();
    });
    document.getElementById("report_add_label").addEventListener("input", () => {
      document.getElementById("report_add_label").dataset.auto = "0";
    });
    document.getElementById("filter_add_btn").addEventListener("click", appendFilterFromPicker);
    document.getElementById("filter_add_field").addEventListener("change", updateFilterValueEditor);
    document.getElementById("load-odata-fields").addEventListener("click", () => {
      document.getElementById("odata-status").style.color = "#555";
      loadOdataFields();
    });
    document.getElementById("load-after-odata-fields").addEventListener("click", () => {
      loadAfterOdataFields();
    });
    document.getElementById("type_id").addEventListener("change", syncOdataServiceHint);
    window.addEventListener("load", () => {
      syncOdataServiceHint();
      const svc = document.getElementById("odata_service").value.trim();
      if (document.querySelector('[name="company"]').value.trim() && svc) {
        loadOdataFields();
      } else if (document.querySelector('[name="company"]').value.trim()) {
        document.getElementById("odata-status").textContent =
          "Escriba el servicio OData (p. ej. FacturaVenta) y pulse «Cargar campos OData desde BC».";
      }
      const afterSvc = document.getElementById("after_odata_service").value.trim();
      if (document.querySelector('[name="company"]').value.trim() && afterSvc) {
        loadAfterOdataFields();
      }
    });
  </script>
</body>
</html>
"""

_DEFAULT_FORM = {
    "skill_id": "malla_publicidad_facturar_ventas",
    "label": "Facturar ventas Malla Publicidad",
    "description": "",
    "company": "Malla Publicidad",
    "type_id": "sales_invoice",
    "odata_service": "",
    "action_id": "registrar_factura",
    "date_dynamic": "month_to_today",
    "extra_filter_lines": "Esperar_Orden_Cliente | No",
    "odata_field_types_json": "",
    "date_odata_field": "",
    "document_key_odata": "",
    "report_fields_lines": "",
    "notify_emails": "andreuserra@malla.es; mauel@malla.es; julian@malla.es",
    "limit": "500",
    "posting_date_before_register": "today",
    "before_action_field_edits_lines": "",
    "conn_odata_base_url": "",
    "conn_web_base_url": "",
    "conn_company": "",
    "after_odata_service": "",
    "after_filter_field": "",
    "after_filter_value": "{number}",
    "after_extra_filter_lines": "",
    "after_save_odata_field": "",
    "after_save_report_key": "",
}

_INBOX_PAGE = """
<!doctype html>
<html lang="es"><head><meta charset="utf-8"><title>Buzón de skills</title></head>
<body style="font-family:Segoe UI,sans-serif;max-width:720px;margin:24px auto;padding:0 16px;">
<p><a href="/portal">← Modo usuario</a> · <a href="/skills">Editor</a></p>
<h1>Buzón de skills</h1>
{% if error %}<p style="color:#a80000;">{{ error }}</p>{% endif %}
{% if saved %}<p>{{ saved }}</p>{% endif %}
<ul>
{% for item in items %}
  <li>
    <strong>{{ item.skill.get('label', '?') }}</strong> ({{ item.skill.get('id', '?') }}) — {{ item.note or "Sin nota" }}
    <form method="post" action="{{ url_for('skill_inbox_install') }}" style="display:inline;">
      <input type="hidden" name="share_id" value="{{ item.id }}">
      <button type="submit">Instalar en este PC</button>
    </form>
  </li>
{% else %}
  <li>No hay skills pendientes en el buzón.</li>
{% endfor %}
</ul>
</body></html>
"""


def register_skill_routes(
    app: Flask,
    *,
    worker_paths: WorkerPaths,
    registry: Callable[[], DocumentTypeRegistry],
    share_store: object | None = None,
) -> None:
    from .skill_share import SkillShareStore

    inbox = share_store if share_store is not None else SkillShareStore()
    def skill_store() -> SkillStore:
        return SkillStore(
            worker_paths.user_skills_dir,
            bundled_dirs=worker_paths.bundled_skills_dirs,
        )

    @app.get("/api/odata-fields")
    def api_odata_fields():
        type_id = request.args.get("type_id", "").strip()
        company = request.args.get("company", "").strip()
        odata_service = request.args.get("odata_service", "").strip()
        if not type_id:
            return jsonify({"error": "Falta type_id"}), 400
        try:
            settings = Settings.from_environment()
            if not company:
                company = (settings.company or "").strip()
            if not company:
                return jsonify({"error": "Indique empresa BC"}), 400
            definition = registry().get(type_id)
            client = BusinessCentralReadClient(settings)
            service, sample_row = fetch_odata_sample_row(
                client,
                definition,
                company,
                odata_service=odata_service or None,
            )
            fields = sorted(
                key
                for key in sample_row
                if isinstance(key, str) and not key.startswith("@")
            )
            field_types = infer_field_types(sample_row)
            sample_values = sample_field_values(sample_row)
            return jsonify(
                {
                    "type_id": type_id,
                    "company": company,
                    "odata_service": service,
                    "fields": list(fields),
                    "field_types": field_types,
                    "sample_values": sample_values,
                    "suggested_boolean": list(suggest_boolean_fields(fields)),
                    "suggested_date": list(suggest_date_fields(fields)),
                    "suggested_key": list(suggest_key_fields(fields)),
                    "suggested_report": list(suggest_contract_fields(fields)),
                }
            )
        except (ValueError, KeyError, BusinessCentralReadError) as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": f"Error interno al listar OData: {exc}"}), 500

    @app.get("/skills/")
    def skill_editor_slash():
        from flask import redirect

        return redirect(url_for("skill_editor"), code=302)

    @app.get("/skills")
    def skill_editor():
        skill_id = request.args.get("skill_id", "").strip()
        saved = request.args.get("saved", "").strip()
        err = request.args.get("error", "").strip()
        form_view: dict[str, object] = dict(_DEFAULT_FORM)
        if skill_id:
            try:
                form_view = _form_from_skill(skill_store().get(skill_id))
            except KeyError:
                err = err or f"Skill no encontrado: {skill_id}"
        return render_template_string(
            _EDITOR_PAGE,
            skills=skill_store().all(),
            document_types=registry().all(),
            form=form_view,
            error=err or None,
            saved=saved or None,
            preview_json=None,
        )

    @app.get("/skills/inbox")
    def skill_inbox():
        pending = inbox.list_pending()
        return render_template_string(
            _INBOX_PAGE,
            items=pending,
            error=request.args.get("error"),
            saved=request.args.get("saved"),
        )

    @app.post("/skills/inbox/install")
    def skill_inbox_install():
        share_id = request.form.get("share_id", "").strip()
        try:
            item = inbox.get(share_id)
            skill = WorkerSkill.from_dict(item.skill)
            path = skill_store().save(skill)
            inbox.close(share_id)
            return redirect(
                url_for("skill_editor", skill_id=skill.id, saved=str(path))
            )
        except Exception as exc:
            return redirect(url_for("skill_inbox", error=str(exc)))

    @app.post("/skills/share")
    def skill_share():
        skill_id = request.form.get("skill_id", "").strip()
        note = request.form.get("share_note", "").strip()
        try:
            skill = skill_store().get(skill_id)
            item = inbox.share(skill, note=note)
            return redirect(
                url_for(
                    "skill_editor",
                    skill_id=skill.id,
                    saved=f"Buzón: {item.id}",
                )
            )
        except Exception as exc:
            return redirect(
                url_for("skill_editor", skill_id=skill_id, error=str(exc))
            )

    @app.post("/skills/save")
    def skill_save():
        try:
            skill = skill_from_builder_form(request.form)
            path = skill_store().save(skill)
            return redirect(
                url_for(
                    "skill_editor",
                    skill_id=skill.id,
                    saved=str(path),
                )
            )
        except Exception as exc:
            return render_template_string(
                _EDITOR_PAGE,
                skills=skill_store().all(),
                document_types=registry().all(),
                form=_form_from_request(request.form),
                error=str(exc),
                saved=None,
                preview_json=None,
            )

    @app.post("/skills/preview")
    def skill_preview():
        err = None
        preview_json = None
        skill_id = request.form.get("skill_id", "").strip()
        try:
            skill = skill_store().get(skill_id)
            settings = Settings.from_environment()
            spec = skill.to_job_spec(dry_run=True)
            spec.validate_against_registry(registry())
            preview = build_job_preview(
                registry(),
                spec,
                client=BusinessCentralReadClient(settings),
            )
            payload = preview.as_dict()
            payload["skill_report_emails"] = list(skill.report.notify_emails)
            worker_paths.pending_preview_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            preview_json = json.dumps(payload, ensure_ascii=False, indent=2)
            form_view = _form_from_skill(skill)
        except Exception as exc:
            err = str(exc)
            form_view = _form_from_request(request.form)
        return render_template_string(
            _EDITOR_PAGE,
            skills=skill_store().all(),
            document_types=registry().all(),
            form=form_view,
            error=err,
            saved=None,
            preview_json=preview_json,
        )


def _form_from_skill(skill: WorkerSkill) -> dict[str, object]:
    spec = skill.spec
    date_dynamic = "month_to_today"
    date_odata_field = ""
    if spec.date_filter:
        if spec.date_filter.dynamic:
            date_dynamic = spec.date_filter.dynamic
        date_odata_field = spec.date_filter.field or ""
    document_key = (spec.odata_key_field or "").strip()
    for field in skill.report.fields:
        if field.key == "number" and field.odata and not document_key:
            document_key = field.odata
    report_lines = report_fields_to_lines(skill.report.fields)
    if not report_lines.strip():
        report_lines = _report_lines_from_spec(spec)
    return {
        "skill_id": skill.id,
        "label": skill.label,
        "description": skill.description,
        "company": spec.company,
        "type_id": spec.type_id,
        "odata_service": spec.odata_service or "",
        "action_id": spec.action_id,
        "date_dynamic": date_dynamic,
        "extra_filter_lines": extra_odata_filters_to_lines(dict(spec.extra_odata_filters)),
        "odata_field_types_json": "",
        "date_odata_field": date_odata_field,
        "document_key_odata": document_key,
        "report_fields_lines": report_lines,
        "notify_emails": "; ".join(skill.report.notify_emails),
        "limit": str(spec.limit),
        "conn_odata_base_url": (
            skill.connection.odata_base_url if skill.connection else ""
        ) or "",
        "conn_web_base_url": (
            skill.connection.web_base_url if skill.connection else ""
        ) or "",
        "conn_company": (
            skill.connection.company if skill.connection else ""
        ) or "",
        **_posting_date_form_fields(spec),
        **_after_action_form_fields(spec),
    }


def _after_action_form_fields(spec: object) -> dict[str, str]:
    empty = {
        "after_odata_service": "",
        "after_filter_field": "",
        "after_filter_value": "{number}",
        "after_extra_filter_lines": "",
        "after_save_odata_field": "",
        "after_save_report_key": "",
    }
    steps = getattr(spec, "after_action_steps", ()) or ()
    if not steps:
        return empty
    step = steps[0]
    payload = {
        "after_odata_service": step.service,
        "after_filter_field": step.filter_field,
        "after_filter_value": step.filter_value,
        "after_extra_filter_lines": extra_odata_filters_to_lines(
            dict(step.extra_filters)
        ),
        "after_save_odata_field": "",
        "after_save_report_key": "",
    }
    if step.save_for_report:
        payload["after_save_odata_field"] = step.save_for_report.odata_field
        payload["after_save_report_key"] = step.save_for_report.report_key
    return payload


def _posting_date_form_fields(spec: object) -> dict[str, str]:
    edits = getattr(spec, "before_action_field_edits", ()) or ()
    posting_mode = ""
    extra_lines: list[str] = []
    for step in edits:
        if (
            step.field_label.casefold()
            == DEFAULT_POSTING_DATE_FIELD_LABEL.casefold()
            and step.value.casefold() in {"today", "hoy", "end_of_month", "fin_mes"}
        ):
            posting_mode = step.value.casefold()
            if posting_mode == "hoy":
                posting_mode = "today"
            if posting_mode == "fin_mes":
                posting_mode = "end_of_month"
        else:
            extra_lines.append(f"{step.field_label} | {step.value}")
    return {
        "posting_date_before_register": posting_mode,
        "before_action_field_edits_lines": "\n".join(extra_lines),
    }


def _report_lines_from_spec(spec: object) -> str:
    mapping = getattr(spec, "report_odata_fields", None) or {}
    lines: list[str] = []
    for key, odata in mapping.items():
        if key == "number" or not odata:
            continue
        lines.append(f"{key} | {key} | {odata}")
    return "\n".join(lines)


def _form_from_request(form: object) -> dict[str, object]:
    getter = getattr(form, "get", None)
    if not callable(getter):
        return dict(_DEFAULT_FORM)
    merged = dict(_DEFAULT_FORM)
    for key in merged:
        merged[key] = getter(key, merged.get(key, ""))
    return merged
