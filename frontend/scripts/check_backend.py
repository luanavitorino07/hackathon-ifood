"""Valida fixtures e o fluxo HTTP contra o backend local, sem rede/compra real.
Na raiz: python frontend/scripts/check_backend.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from fastapi.testclient import TestClient
from backend.api.main import build_application
from backend.api import models as m

for event in json.loads((ROOT / 'frontend/src/mocks/events.json').read_text()):
    m.OfficeEvent.model_validate(event)
m.AgentCatalogResponse.model_validate_json((ROOT / 'frontend/src/mocks/agents.json').read_text())
with TestClient(build_application(runtime_mode='demo')) as client:
    admin = {'X-Demo-Role': 'admin'}
    assert client.get('/api/v1/agents').status_code == 403
    catalog = client.get('/api/v1/agents', headers=admin)
    assert catalog.status_code == 200
    m.AgentCatalogResponse.model_validate(catalog.json())
    created = client.post('/api/v1/sessions', json={'client_id': None, 'initial_context': None})
    assert created.status_code == 201
    session = m.SessionCreateResponse.model_validate(created.json())
    sid = session.session_id
    request = {'session_id': sid, 'client_message_id': 'frontend-smoke', 'text': 'Quero jantar para quatro pessoas até R$ 120, com uma opção vegetariana.', 'input_mode': 'text', 'transcription_id': None}
    assert client.post('/api/v1/chat/messages', json=request).status_code == 202
    assert client.post('/api/v1/chat/messages', json=request).status_code == 202
    buyer = m.SessionSnapshotResponse.model_validate(client.get(f'/api/v1/sessions/{sid}/snapshot').json())
    assert len([x for x in buyer.messages if x.role == 'customer']) == 1
    assert buyer.agents == []
    assert buyer.recommendations
    history = m.HistoryResponse.model_validate(client.get(f'/api/v1/sessions/{sid}/history?after_seq=0&limit=200', headers=admin).json())
    assert any(e.type == 'agent_message' for e in history.events)
    public_history = client.get(f'/api/v1/sessions/{sid}/history?after_seq=0&limit=200').json()
    assert all(e['visibility'] != 'admin' for e in public_history['events'])
    m.AdminOverviewResponse.model_validate(client.get('/api/v1/admin/overview', headers=admin).json())
    stt = client.post('/api/v1/audio/transcriptions', files={'audio': ('audio.webm', b'demo', 'audio/webm')}, data={'language': 'pt-BR'})
    assert stt.status_code == 503 and stt.json()['error']['code'] == 'STT_UNAVAILABLE'
    # O backend atual não tem dispatcher de pedidos configurado.
    order = client.post('/api/v1/orders/submit', json={'session_id': sid, 'recommendation_id': buyer.recommendations[0].recommendation_id, 'client_action_id': 'frontend-order', 'confirmed': True})
    assert order.status_code == 503 and order.json()['error']['code'] == 'ORDER_SUBMISSION_UNAVAILABLE'
print('OK: fixtures, catálogo, sessão, chat idempotente, recomendações, histórico, papéis, overview, STT indisponível e submissão indisponível.')
