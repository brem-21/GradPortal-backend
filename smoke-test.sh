#!/usr/bin/env bash
# End-to-end validation. Signs in with the dev provider and exercises every
# service, so the app can be checked before Google/LinkedIn are registered.
#
#   ./smoke-test.sh                            # admin account
#   ./smoke-test.sh student@gradportal.example.com
set -uo pipefail
cd "$(dirname "$0")"

EMAIL="${1:-admin@gradportal.example.com}"
WEB="${WEB:-http://127.0.0.1:3000}"
CORE="${CORE:-http://127.0.0.1:8000}"
JAR="$(mktemp)"
trap 'rm -f "$JAR"' EXIT

pass=0; fail=0; skip=0
ok()   { printf "  \033[32m ok \033[0m %s\n" "$1"; pass=$((pass+1)); }
bad()  { printf "  \033[31mFAIL\033[0m %s — %s\n" "$1" "$2"; fail=$((fail+1)); }
warn() { printf "  \033[33mskip\033[0m %s — %s\n" "$1" "$2"; skip=$((skip+1)); }

check() { # name expected url [curl args...]
  local name="$1" expect="$2" url="$3"; shift 3
  local code; code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 45 "$@" "$url")
  [ "$code" = "$expect" ] && ok "$name" || bad "$name" "expected $expect, got $code"
}

echo
echo "── service health ─────────────────────────────────────────"
for entry in "core-api:8000" "doc:8001" "rag:8002" "eval:8003" "voice:8004"; do
  name="${entry%%:*}"; port="${entry##*:}"
  body=$(curl -s --max-time 5 "http://127.0.0.1:$port/health" 2>/dev/null)
  if [ -z "$body" ]; then bad "$name reachable" "no response on :$port"; continue; fi
  status=$(printf '%s' "$body" | python3 -c "import json,sys; print(json.load(sys.stdin).get('status','?'))" 2>/dev/null)
  case "$status" in
    healthy)  ok "$name healthy" ;;
    degraded) warn "$name degraded" "$(printf '%s' "$body" | python3 -c "
import json,sys
d=json.load(sys.stdin)
print(', '.join(f'{k}={v}' for k,v in d.get('checks',{}).items() if not str(v).startswith(('ok','configured'))))")" ;;
    *)        bad "$name health" "unexpected status '$status'" ;;
  esac
done

echo
echo "── public endpoints (no auth) ─────────────────────────────"
check "landing page"        200 "$WEB/"
check "sign-in page"        200 "$WEB/signin"
check "site media"          200 "$CORE/api/v1/site/media"
check "site stories"        200 "$CORE/api/v1/site/stories"
check "core-api docs"       200 "$CORE/docs"

echo
echo "── auth is enforced ───────────────────────────────────────"
check "portal redirects out"     307 "$WEB/overview"
check "api rejects no token"     401 "$CORE/api/v1/users/me"
check "doc rejects no token"     401 "http://127.0.0.1:8001/documents"
check "internal needs svc token" 403 "http://127.0.0.1:8001/internal/search" \
  -X POST -H 'Content-Type: application/json' -d '{"user_key":"x","query":"y"}'

echo
echo "── dev sign-in as $EMAIL ──────────────────────────────────"
CSRF=$(curl -s -c "$JAR" --max-time 20 "$WEB/api/auth/csrf" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['csrfToken'])" 2>/dev/null)
if [ -z "${CSRF:-}" ]; then
  bad "csrf token" "could not reach $WEB"
else
  code=$(curl -s -b "$JAR" -c "$JAR" -o /dev/null -w '%{http_code}' --max-time 30 \
    -X POST "$WEB/api/auth/callback/dev" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    --data-urlencode "csrfToken=$CSRF" --data-urlencode "email=$EMAIL" \
    --data-urlencode "callbackUrl=$WEB/overview" --data-urlencode "json=true")
  if [ "$code" = "302" ] || [ "$code" = "200" ]; then ok "signed in"
  else bad "sign in" "got $code (is ALLOW_DEV_SIGNIN=true?)"; fi
fi

echo
echo "── authenticated pages ────────────────────────────────────"
for route in /overview /opportunities /shortlist /dossier /committee \
             /mentors /mentorship /profile /settings /notifications; do
  body=$(curl -s -b "$JAR" --max-time 60 "$WEB$route")
  if printf '%s' "$body" | grep -q "Application error\|Internal Server Error\|Backend unreachable"; then
    bad "$route" "rendered an error"
  elif [ ${#body} -lt 2000 ]; then
    bad "$route" "suspiciously small response (${#body} bytes)"
  else
    ok "$route"
  fi
done

echo
echo "── admin pages ────────────────────────────────────────────"
for route in /admin/sources /admin/media /admin/stories /submit; do
  code=$(curl -s -b "$JAR" -o /dev/null -w '%{http_code}' --max-time 45 "$WEB$route")
  if [ "$code" = "200" ]; then ok "$route"
  elif [ "$code" = "307" ]; then warn "$route" "redirected — this account is not an admin"
  else bad "$route" "got $code"; fi
done

echo
echo "── core-api behaviour ─────────────────────────────────────"
TOKEN=$(cd backend && .venv/bin/python -m scripts.bootstrap token "$EMAIL" 2>/dev/null)
if [ -z "${TOKEN:-}" ]; then
  warn "api token" "could not mint one; skipping API checks"
else
  AUTH=(-H "Authorization: Bearer $TOKEN")
  check "GET /users/me"                200 "$CORE/api/v1/users/me" "${AUTH[@]}"
  check "GET /opportunities"           200 "$CORE/api/v1/opportunities" "${AUTH[@]}"
  check "GET /opportunities/facets"    200 "$CORE/api/v1/opportunities/facets" "${AUTH[@]}"
  check "GET /opportunities/freshness" 200 "$CORE/api/v1/opportunities/freshness" "${AUTH[@]}"
  check "region filter"                200 "$CORE/api/v1/opportunities?regions=europe" "${AUTH[@]}"
  check "GET /notifications"           200 "$CORE/api/v1/notifications" "${AUTH[@]}"
  check "GET /mentors"                 200 "$CORE/api/v1/mentors" "${AUTH[@]}"
  check "GET /saved"                   200 "$CORE/api/v1/saved" "${AUTH[@]}"
  check "doc: GET /documents"          200 "http://127.0.0.1:8001/documents" "${AUTH[@]}"
  check "rag: GET /conversations"      200 "http://127.0.0.1:8002/conversations" "${AUTH[@]}"
  check "eval: GET /evaluations"       200 "http://127.0.0.1:8003/evaluations" "${AUTH[@]}"
  check "eval: PhD CV rubric"          200 "http://127.0.0.1:8003/evaluations/rubrics/cv?track=phd" "${AUTH[@]}"
  check "admin: site media"            200 "$CORE/api/v1/admin/media" "${AUTH[@]}"
  check "admin: stories"               200 "$CORE/api/v1/admin/stories" "${AUTH[@]}"

  n=$(curl -s --max-time 20 "${AUTH[@]}" "$CORE/api/v1/opportunities?regions=europe" \
      | python3 -c "import json,sys; print(json.load(sys.stdin).get('total','?'))" 2>/dev/null)
  echo "         europe filter returns $n opportunity(ies)"
  n=$(curl -s --max-time 20 "$CORE/api/v1/site/media" \
      | python3 -c "import json,sys; d=json.load(sys.stdin); print(sum(len(s['slides']) for s in d['sets'].values()))" 2>/dev/null)
  echo "         site media has $n slide assignment(s)"
fi

echo
echo "───────────────────────────────────────────────────────────"
printf "  %d passed, %d failed, %d skipped\n\n" "$pass" "$fail" "$skip"
[ "$fail" -eq 0 ]
