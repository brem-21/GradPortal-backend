#!/usr/bin/env bash
# Show what is up and what is missing a key.
for entry in "core-api:8000" "doc:8001" "rag:8002" "eval:8003" "voice:8004"; do
  name="${entry%%:*}"; port="${entry##*:}"
  printf "  %-10s " "$name"
  curl -s --max-time 4 "http://127.0.0.1:$port/health" 2>/dev/null | python3 -c "
import json,sys
try: d=json.load(sys.stdin)
except Exception: print('down'); raise SystemExit
print(f\"{d.get('status','?'):<9}\", ' '.join(f'{k}={v}' for k,v in d.get('checks',{}).items()))
" 2>/dev/null || echo "down"
done
# The frontend lives in its own repo; check it only if it happens to be up.
printf "  %-10s " "frontend"
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 4 http://127.0.0.1:3000/ 2>/dev/null || echo 000)
[ "$code" = "200" ] && echo "healthy" || echo "not running (optional here)"
