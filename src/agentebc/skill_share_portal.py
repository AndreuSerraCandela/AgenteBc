"""API del portal para compartir skills del worker (consultor → usuarios)."""
from __future__ import annotations

from flask import Flask, jsonify, request

from agentebc_worker.skill_share import SkillShareError, SkillShareStore
from agentebc_worker.skills import WorkerSkill

from .action_share import _auth_error, _json_error


def register_skill_share_routes(app: Flask) -> None:
    store = SkillShareStore()

    @app.post("/api/skills/share")
    def share_skill():
        auth_error = _auth_error()
        if auth_error is not None:
            return auth_error
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return _json_error("El cuerpo debe ser un objeto JSON", 400)
        skill_raw = payload.get("skill")
        if not isinstance(skill_raw, dict):
            return _json_error("Falta el objeto skill", 400)
        try:
            skill = WorkerSkill.from_dict(skill_raw)
            item = store.share(
                skill,
                from_user=str(payload.get("from_user") or ""),
                note=str(payload.get("note") or ""),
            )
        except (SkillShareError, ValueError, TypeError) as exc:
            return _json_error(str(exc), 400)
        except OSError as exc:
            return _json_error(f"No se pudo guardar el skill: {exc}", 500)
        return jsonify(item.as_dict()), 201

    @app.get("/api/skills/inbox")
    def skills_inbox():
        auth_error = _auth_error()
        if auth_error is not None:
            return auth_error
        status = (request.args.get("status") or "pending").strip()
        if status != "pending":
            return _json_error("Solo status=pending está soportado", 400)
        items = store.list_pending()
        return jsonify(
            {
                "items": [item.as_dict() for item in items],
                "count": len(items),
            }
        )

    @app.get("/api/skills/<share_id>")
    def get_shared_skill(share_id: str):
        auth_error = _auth_error()
        if auth_error is not None:
            return auth_error
        try:
            return jsonify(store.get(share_id).as_dict())
        except SkillShareError as exc:
            return _json_error(str(exc), 400)
        except KeyError:
            return _json_error("Skill compartido no encontrado", 404)

    @app.post("/api/skills/<share_id>/close")
    def close_shared_skill(share_id: str):
        auth_error = _auth_error()
        if auth_error is not None:
            return auth_error
        try:
            item = store.close(share_id)
        except SkillShareError as exc:
            return _json_error(str(exc), 400)
        except KeyError:
            return _json_error("Skill compartido no encontrado", 404)
        return jsonify(item.as_dict())
