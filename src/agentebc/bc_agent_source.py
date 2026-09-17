from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from .models import SourceMatch


@dataclass(frozen=True, slots=True)
class BcAgentSourceClient:
    base_url: str
    token: str
    timeout_seconds: float = 120.0

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Objetos-Agent-Token": self.token,
        }

    def _post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        url = f"{self.base_url.rstrip('/')}{path}"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(error_body)
            except json.JSONDecodeError:
                raise RuntimeError(
                    f"Agente BC respondió con HTTP {exc.code}: {error_body}"
                ) from exc
            raise RuntimeError(str(data.get("error") or error_body)) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"No se pudo conectar con el agente BC en {url}: {exc.reason}"
            ) from exc

        if not body.get("ok"):
            raise RuntimeError(str(body.get("error") or f"Respuesta inesperada: {body!r}"))
        return body

    def health(self) -> dict[str, object]:
        url = f"{self.base_url.rstrip('/')}/api/health"
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    def search_call_stack(
        self,
        call_stack: str,
        *,
        limit: int = 5,
    ) -> tuple[SourceMatch, ...]:
        data = self._post_json(
            "/api/search-call-stack",
            {"call_stack": call_stack, "limit": limit},
        )
        return tuple(
            _source_match_from_dict(item)
            for item in data.get("matches", [])
            if isinstance(item, dict)
        )

    def search_text(self, text: str, *, limit: int = 10) -> tuple[SourceMatch, ...]:
        data = self._post_json(
            "/api/search-text",
            {"text": text, "limit": limit},
        )
        return tuple(
            _source_match_from_dict(item)
            for item in data.get("matches", [])
            if isinstance(item, dict)
        )

    def source_excerpt(
        self,
        path: str,
        line: int,
        *,
        context: int = 2,
    ) -> SourceMatch:
        query = urllib.parse.urlencode(
            {"path": path, "line": line, "context": context}
        )
        url = f"{self.base_url.rstrip('/')}/api/source-excerpt?{query}"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "X-Objetos-Agent-Token": self.token,
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Agente BC respondió con HTTP {exc.code}: {error_body}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"No se pudo conectar con el agente BC en {url}: {exc.reason}"
            ) from exc
        if not body.get("ok"):
            raise RuntimeError(str(body.get("error") or f"Respuesta inesperada: {body!r}"))
        match = body.get("match")
        if not isinstance(match, dict):
            raise RuntimeError("Respuesta inesperada del agente para source-excerpt")
        return _source_match_from_dict(match)


def _source_match_from_dict(data: dict[str, object]) -> SourceMatch:
    return SourceMatch(
        path=str(data.get("path") or ""),
        line=int(data.get("line") or 0),
        excerpt=str(data.get("excerpt") or ""),
        score=float(data.get("score") or 0.0),
    )
