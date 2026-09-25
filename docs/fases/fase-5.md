# Fase 5: estabilización, demo y README

Fecha: 24 y 25 de septiembre de 2026. Un punto por commit, en el orden del encargo.

## 1. `latest_rejected` en `GET /tasks/{id}`

`GET /tasks/{id}` no pide token. Respuesta real de la tarea de la fase 4b (sin `raw_request`, `description`, `criteria` ni `examples`, que son la versión acordada y pública para el programador invitado):

```text
$ curl -s localhost:8000/tasks/3Pi1ubNJqZadIooQ
```

```json
{
 "task_id": "3Pi1ubNJqZadIooQ",
 "language": "python",
 "allowed_deps": [],
 "rules_hash": "391136734bc9e21ecfb9626ec4aa3eb5474d4c0995412043def8fd69c4f79c96",
 "amount": 5703368,
 "deadline_minutes": 5,
 "client_address": "GBGK4NLPUTTOTHR5SLSFPOWA74EYH727WGZQ5CKGVX2B4DGF3UVPD4FL",
 "freelancer_address": "GA7MXQO3OL6IMISROP3JJM3NBGOEDHPPK7B5Q2ASNIBNVAPVCE6FBEVJ",
 "submissions_used": 1,
 "max_submissions": 3,
 "onchain": {
  "amount": 5703368,
  "client": "GBGK4NLPUTTOTHR5SLSFPOWA74EYH727WGZQ5CKGVX2B4DGF3UVPD4FL",
  "deadline": 1790305827,
  "freelancer": null,
  "rules_hash": "391136734bc9e21ecfb9626ec4aa3eb5474d4c0995412043def8fd69c4f79c96",
  "status": "Refunded",
  "task_id": "3Pi1ubNJqZadIooQ"
 },
 "seconds_left": -3510,
 "onchain_error": null,
 "latest_code_hash": "3fed1d2950769ea6f4020b18721a2654b812bb48622711e51e5a96a4cb0a0c2d",
 "consented_code_hash": "3fed1d2950769ea6f4020b18721a2654b812bb48622711e51e5a96a4cb0a0c2d",
 "latest_rejected": true
}
```

`latest_rejected` ya es un booleano junto al `code_hash`: la vista pública no incluye `reason`, `comparison`, `trace`, `logic`, `analysis` ni el código. No hubo cambios de código. El veredicto completo solo sale por `POST /evaluate` (al programador) y `GET /tasks/{id}/verdicts` (con `X-Client-Token`).
