# Áudio local para o MVP

Instale `ffmpeg` no sistema e, no ambiente Python da API:

```sh
pip install -r backend/integrations/requirements-stt.txt
APP_STT_PROVIDER=whisper APP_STT_MODEL=small python -m backend.api.run_local --real
```

O primeiro uso baixa o modelo público Whisper small; depois a inferência roda em CPU,
sem chave, sem cota Gemini e sem transmitir áudio ao iFood ou a serviço de transcrição.
Para preparar o modelo antes do pitch:

```sh
python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')"
```

Contrato HTTP existente preservado: `POST /api/v1/audio/transcriptions`, multipart com
`audio` e `language=pt-BR` opcional. Retorna `schema_version`, `transcription_id`, `text`,
`language` e `requires_confirmation=true`. A interface apresenta o texto para revisão
e só então envia `/api/v1/chat/messages` com `input_mode=audio` e o identificador recebido.
Transcrever não inicia agentes e não autoriza compra. Não há TTS.

Limites: 10 MiB, 120 segundos, uma inferência simultânea por processo. Arquivo inválido,
sem fala ou longo demais retorna erro padronizado 422; servidor ocupado retorna 429.
Falha do modelo retorna 503 sem detalhes internos. `APP_STT_PROVIDER=none` (padrão)
preserva STT_UNAVAILABLE. Modelo baixado fica no cache local; áudio não é salvo em arquivo.
O texto pode conter erros: confirmação humana é sempre exigida, especialmente para
valores, quantidades, restrições e pedidos. A confirmação visual pertence ao frontend.

Validação local: fala sintética em português transcrita pelo modelo real small em
14,43 segundos: “Eu quero uma pizza. Sem cebola. Para uma pessoa.” Silêncio retornou
422 STT_NO_SPEECH. O modelo base errou palavras nesse teste e não é o padrão escolhido.
Esse teste não substitui validação com gravação humana e microfone do navegador.

Implementação do motor: https://github.com/SYSTRAN/faster-whisper
