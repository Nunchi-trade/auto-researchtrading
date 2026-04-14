#!/bin/bash
# Stitch 화면 생성 스크립트 (MCP 클라이언트 타임아웃 우회)
# Usage: ./generate_screen.sh <page_name> <prompt_file>

set -e

PAGE_NAME="${1:?page name required}"
PROMPT_FILE="${2:?prompt file required}"

PROJECT_ID=$(jq -r '.projectId' "$(dirname "$0")/../metadata.json")
API_KEY=$(jq -r '.mcpServers.stitch.headers["X-Goog-Api-Key"]' ~/.gemini/antigravity/mcp_config.json)

[ -z "$API_KEY" ] && { echo "ERROR: Stitch API key not found"; exit 1; }
[ ! -f "$PROMPT_FILE" ] && { echo "ERROR: prompt file not found: $PROMPT_FILE"; exit 1; }

PROMPT=$(cat "$PROMPT_FILE")
DESIGNS_DIR="$(dirname "$0")/../designs"
RESULT_FILE="/tmp/stitch_gen_${PAGE_NAME}.json"

mkdir -p "$DESIGNS_DIR"

echo "[$(date +%H:%M:%S)] Generating screen: $PAGE_NAME (project $PROJECT_ID)..."

curl -s -X POST "https://stitch.googleapis.com/mcp" \
  -H "X-Goog-Api-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d "$(jq -nc --arg p "$PROMPT" --arg pid "$PROJECT_ID" '{
    jsonrpc:"2.0", id:1, method:"tools/call",
    params:{
      name:"generate_screen_from_text",
      arguments:{projectId:$pid, prompt:$p, deviceType:"DESKTOP", modelId:"GEMINI_3_1_PRO"}
    }
  }')" \
  --max-time 240 > "$RESULT_FILE"

# 응답 파싱 및 자산 다운로드
python3 <<PY
import json, sys, urllib.request

with open("$RESULT_FILE") as f:
    rpc = json.load(f)

if rpc.get("result", {}).get("isError"):
    print(f"ERROR: {rpc['result']['content'][0]['text']}")
    sys.exit(1)

inner = json.loads(rpc["result"]["content"][0]["text"])
screen = None
for comp in inner["outputComponents"]:
    if "design" in comp:
        screen = comp["design"]["screens"][0]
        break

if not screen:
    print("ERROR: no screen in response")
    sys.exit(1)

cp = screen.get("canvasPosition", {})
width = cp.get("width", 1440)
html_url = screen["htmlCode"]["downloadUrl"]
png_url = screen["screenshot"]["downloadUrl"] + f"=w{width}"

urllib.request.urlretrieve(html_url, "$DESIGNS_DIR/${PAGE_NAME}.html")
urllib.request.urlretrieve(png_url, "$DESIGNS_DIR/${PAGE_NAME}.png")

# metadata.json 업데이트
meta_path = "$(dirname "$0")/../metadata.json"
with open(meta_path) as f:
    meta = json.load(f)

meta["screens"]["${PAGE_NAME}"] = {
    "id": screen["id"],
    "sourceScreen": screen["name"],
    "width": width,
    "height": cp.get("height", 900),
    "file": ".stitch/designs/${PAGE_NAME}.html"
}

with open(meta_path, "w") as f:
    json.dump(meta, f, indent=2)

# 텍스트 출력 및 제안
for comp in inner["outputComponents"]:
    if "text" in comp:
        print()
        print("=== AI 출력 ===")
        print(comp["text"][:500])
    if "suggestion" in comp:
        print(f"  제안: {comp['suggestion']}")

print()
print(f"✓ 다운로드 완료: {screen['id']}")
PY
