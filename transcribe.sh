#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://<HOST>:5152}"
API_KEY="${API_KEY:-}"
AUDIO_FILE="${1:-input.m4a}"
MODEL="${MODEL:-large}"
POLL_SECONDS="${POLL_SECONDS:-2}"

if [ -z "$API_KEY" ]; then
  echo "❌ API_KEY ontbreekt. Zet eerst: export API_KEY='<jouw-key>'"
  exit 1
fi

if [ ! -f "$AUDIO_FILE" ]; then
  echo "❌ Bestand niet gevonden: $AUDIO_FILE"
  exit 1
fi

json_get() {
  # Simpele JSON field extractor (string/number), zonder jq.
  # Gebruik: json_get "$json" "status"
  printf '%s' "$1" | sed -nE 's/.*"'$2'"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p' | head -n1
}

echo "Upload: $AUDIO_FILE"
RESP=$(curl -sS -X POST "$BASE_URL/transcriptions" \
  -H "X-API-Key: $API_KEY" \
  -F "file=@$AUDIO_FILE" \
  -F "model=$MODEL")

JOB_ID="$(json_get "$RESP" "transcription_job_id")"
[ -z "$JOB_ID" ] && JOB_ID="$(json_get "$RESP" "job_id")"
[ -z "$JOB_ID" ] && JOB_ID="$(json_get "$RESP" "id")"

if [ -z "$JOB_ID" ]; then
  echo "❌ Kon geen job id vinden. Response:"
  echo "$RESP"
  exit 1
fi

echo "Job gestart: $JOB_ID"

while true; do
  STATUS_RESP=$(curl -sS "$BASE_URL/transcriptions/$JOB_ID" \
    -H "Authorization: Bearer $API_KEY")

  STATUS="$(json_get "$STATUS_RESP" "status")"
  echo "Status: ${STATUS:-unknown}"

  case "$STATUS" in
    completed) break ;;
    failed)
      echo "❌ Transcriptie gefaald:"
      echo "$STATUS_RESP"
      exit 1
      ;;
    queued|running|"")
      sleep "$POLL_SECONDS"
      ;;
    *)
      echo "Onbekende status-respons:"
      echo "$STATUS_RESP"
      sleep "$POLL_SECONDS"
      ;;
  esac
done

OUT="transcript_${JOB_ID}.txt"
curl -sS "$BASE_URL/transcriptions/$JOB_ID/transcript" \
  -H "X-API-Key: $API_KEY" \
  -o "$OUT"

echo "✅ Klaar: $OUT"
echo "ℹ️ Na succesvolle download wordt de job verwijderd."
