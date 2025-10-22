#!/bin/bash
# Test script for OpenAPI server

echo "Testing Whisper Recordings OpenAPI Server"
echo "=========================================="
echo ""

BASE_URL="http://localhost:8000"

echo "1. Testing root endpoint..."
curl -s "$BASE_URL/" | jq '.'
echo ""

echo "2. Testing health check..."
curl -s "$BASE_URL/health" | jq '.'
echo ""

echo "3. Getting all recordings..."
curl -s "$BASE_URL/recordings" | jq '.'
echo ""

echo "4. Getting first recording ID..."
RECORDING_ID=$(curl -s "$BASE_URL/recordings" | jq -r '.[0].id')
echo "First recording ID: $RECORDING_ID"
echo ""

if [ -n "$RECORDING_ID" ] && [ "$RECORDING_ID" != "null" ]; then
    echo "5. Getting details for recording $RECORDING_ID..."
    curl -s "$BASE_URL/recordings/$RECORDING_ID" | jq '.'
    echo ""

    echo "6. Getting transcription for recording $RECORDING_ID..."
    curl -s "$BASE_URL/recordings/$RECORDING_ID/transcription" | jq '.'
    echo ""

    echo "7. Testing title update for recording $RECORDING_ID..."
    NEW_TITLE="Test Title - $(date +%H:%M:%S)"
    curl -s -X PUT "$BASE_URL/recordings/$RECORDING_ID/title" \
        -H "Content-Type: application/json" \
        -d "{\"new_title\": \"$NEW_TITLE\"}" | jq '.'
    echo ""

    echo "8. Verifying title update..."
    curl -s "$BASE_URL/recordings/$RECORDING_ID" | jq '.name'
    echo ""
else
    echo "No recordings found, skipping detail tests"
fi

echo "=========================================="
echo "Testing complete!"
echo ""
echo "View API documentation at:"
echo "  Swagger UI: $BASE_URL/docs"
echo "  ReDoc:      $BASE_URL/redoc"
echo "  OpenAPI:    $BASE_URL/openapi.json"
