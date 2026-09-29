#!/usr/bin/env bash
# ailab-check.sh - controleert of alles van dag 1 t/m 4 nog werkt (zonder API Management).
# Draai in Azure Cloud Shell (Bash):   bash ailab-check.sh
# Het script LEEST alleen: het maakt en wijzigt niets. Het stelt via je app 4 korte vragen
# (model, RAG, agent 2x); dat kost een paar cent aan tokens.

# ---------- namen (uit ~/ailab.env, anders de vaste waarden) ----------
[ -f ~/ailab.env ] && source ~/ailab.env
RG=${RG:-rg-ailab-week}
SUB=38a67f6b-1aa5-434d-ae6d-51fd65497fcc
FOUNDRY=${FOUNDRY:-fdy-ailab-a46983}
PROJECT=${PROJECT:-proj-ailab}
SEARCH=${SEARCH:-srch-ailab-a4698}
INDEX=${INDEX:-beleid}
STORAGE=${STORAGE:-stailaba46983}
ACR=${ACR:-acrailaba46983}
ACA_ENV=${ACA_ENV:-cae-ailab}
ACA_CHAT=${ACA_CHAT:-ca-chat-a46983}
WEBAPP2=${WEBAPP2:-app-chat-a46983}
AGENT=${AGENT:-voorbeeldstad-assistent}

# ---------- hulpfuncties ----------
G=$'\e[32m'; Y=$'\e[33m'; R=$'\e[31m'; B=$'\e[1m'; N=$'\e[0m'
PASS=0; WARN=0; FAIL=0; FAILS=()
ok()   { echo "  ${G}OK  ${N} $1"; PASS=$((PASS+1)); }
warn() { echo "  ${Y}LET OP${N} $1"; WARN=$((WARN+1)); }
bad()  { echo "  ${R}FOUT${N} $1"; FAIL=$((FAIL+1)); FAILS+=("$1"); }
info() { echo "       $1"; }
kop()  { echo; echo "${B}$1${N}"; }

# Heeft principal $1 op scope $2 een rol die matcht met regex $3?
has_role() {
  az role assignment list --assignee "$1" --scope "$2" --include-inherited \
     --query "[].roleDefinitionName" -o tsv 2>/dev/null | grep -Eqi "$3"
}
check_role() {  # $1 omschrijving, $2 principal, $3 scope, $4 regex, $5 hint
  if [ -z "$2" ]; then bad "$1: geen managed identity gevonden"; return; fi
  if has_role "$2" "$3" "$4"; then ok "$1"; else bad "$1 ontbreekt. $5"; fi
}

# Haal het antwoord of de fout uit de HTML van de app (stdin)
parse_html() {
  python3 -c '
import sys, re, html
t = sys.stdin.read()
err = re.search(r"<div class=\"card err\"><b>(.*?)</b>\s*<p>(.*?)</p>", t, re.S)
ans = re.search(r"<div class=\"answer\">(.*?)</div>", t, re.S)
steps = re.findall(r"<tr><td><code>(.*?)</code></td><td>(.*?)</td>", t)
srcs = len(re.findall(r"<div class=\"src\">", t))
if err:
    print("ERR|" + html.unescape(re.sub("<.*?>", "", err.group(1))) + " - " + html.unescape(err.group(2))[:300])
elif ans:
    a = " ".join(html.unescape(ans.group(1)).split())
    print("ANS|" + a[:220] + "|" + ", ".join(f"{s[0]}:{s[1]}" for s in steps) + f"|{srcs}")
else:
    print("NONE|geen antwoord en geen foutmelding in de pagina")
'
}

echo "${B}AI-lab controle dag 1 t/m 4${N}  (resource group $RG)"
az account set --subscription $SUB 2>/dev/null || { echo "${R}Kan subscription niet selecteren. Ben je ingelogd (az login)?${N}"; exit 1; }

# =====================================================================
kop "Dag 1 - Foundry en modellen"
if [ "$(az group exists -n $RG)" = "true" ]; then ok "Resource group $RG bestaat"; else bad "Resource group $RG bestaat niet"; echo; exit 1; fi

FOUNDRY_ID=$(az cognitiveservices account show -n $FOUNDRY -g $RG --query id -o tsv 2>/dev/null)
if [ -n "$FOUNDRY_ID" ]; then
  ok "Foundry-resource $FOUNDRY bestaat"
  LOCAL=$(az cognitiveservices account show -n $FOUNDRY -g $RG --query properties.disableLocalAuth -o tsv)
  info "Sleutels (local auth) uitgeschakeld: ${LOCAL:-false}"
else
  bad "Foundry-resource $FOUNDRY niet gevonden"
fi
PROJ_ID=$FOUNDRY_ID/projects/$PROJECT
if az resource show --ids $PROJ_ID --api-version 2025-06-01 -o none 2>/dev/null; then ok "Project $PROJECT bestaat"; else bad "Project $PROJECT niet gevonden"; fi

DEPS=$(az cognitiveservices account deployment list -n $FOUNDRY -g $RG \
        --query "[].{n:name, s:sku.name, c:sku.capacity, st:properties.provisioningState}" -o tsv 2>/dev/null)
for d in gpt-54-mini gpt-5-mini text-embedding-3-small; do
  line=$(echo "$DEPS" | awk -v d="$d" '$1==d')
  if [ -z "$line" ]; then bad "Deployment $d ontbreekt"; continue; fi
  set -- $line
  if [ "$4" = "Succeeded" ]; then ok "Deployment $d ($2, ${3}K TPM)"; else warn "Deployment $d staat op $4"; fi
done

# =====================================================================
kop "Dag 2 - App Service (optioneel, mag al opgeruimd zijn)"
if az webapp show -n $WEBAPP2 -g $RG -o none 2>/dev/null; then
  HOST2=$(az webapp show -n $WEBAPP2 -g $RG --query defaultHostName -o tsv)
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 60 "https://$HOST2/health")
  [ "$code" = "200" ] && ok "Web-app $WEBAPP2 /health = 200" || warn "Web-app $WEBAPP2 /health = $code (F1 kan traag opstarten)"
else
  info "Web-app $WEBAPP2 bestaat niet (meer). Geen probleem: de Container App is de app van dag 3/4."
fi

# =====================================================================
kop "Dag 3 - AI Search, storage, registry en Container App"
SEARCH_ID=$(az search service show -n $SEARCH -g $RG --query id -o tsv 2>/dev/null)
if [ -n "$SEARCH_ID" ]; then
  st=$(az search service show -n $SEARCH -g $RG --query "[sku.name, status]" -o tsv | tr '\n' ' ')
  ok "Search-service $SEARCH bestaat ($st)"
  KEY=$(az search admin-key show --service-name $SEARCH -g $RG --query primaryKey -o tsv 2>/dev/null)
  if [ -n "$KEY" ]; then
    n=$(curl -s --max-time 30 -H "api-key: $KEY" "https://$SEARCH.search.windows.net/indexes/$INDEX/docs/\$count?api-version=2024-07-01" | tr -cd '0-9')
    if [ -n "$n" ] && [ "$n" -gt 0 ]; then ok "Index $INDEX bevat $n chunks"; else bad "Index $INDEX is leeg of bestaat niet"; fi
    kb=$(curl -s -o /dev/null -w "%{http_code}" --max-time 30 -H "api-key: $KEY" "https://$SEARCH.search.windows.net/knowledgebases/kb-beleid?api-version=2025-11-01-preview")
    if [ "$kb" = "200" ]; then ok "Knowledge base kb-beleid bestaat"; else warn "Knowledge base kb-beleid: HTTP $kb (API-versie kan afwijken; de agenttest hieronder is leidend)"; fi
    unset KEY
  else
    warn "Kon geen admin key ophalen (API access control op 'RBAC only'?). Index-telling overgeslagen."
  fi
  SEARCH_MI=$(az search service show -n $SEARCH -g $RG --query identity.principalId -o tsv 2>/dev/null)
  check_role "Search-MI: Cognitive Services User op Foundry" "$SEARCH_MI" "$FOUNDRY_ID" "^Cognitive Services (OpenAI )?User$" "Nodig voor vectorisatie en de knowledge base (dag 3 stap 9)."
  STORAGE_ID=$(az storage account show -n $STORAGE -g $RG --query id -o tsv 2>/dev/null)
  if [ -n "$STORAGE_ID" ]; then
    ok "Storage account $STORAGE bestaat"
    check_role "Search-MI: Storage Blob Data Reader op storage" "$SEARCH_MI" "$STORAGE_ID" "Storage Blob Data (Reader|Contributor|Owner)" "Nodig als je de indexer opnieuw draait."
  else
    warn "Storage account $STORAGE niet gevonden (alleen nodig om opnieuw te indexeren)"
  fi
else
  bad "Search-service $SEARCH niet gevonden (let op: de naam eindigt op a4698, zonder 3)"
fi

ACR_ID=$(az acr show -n $ACR -g $RG --query id -o tsv 2>/dev/null)
if [ -n "$ACR_ID" ]; then
  tags=$(az acr repository show-tags -n $ACR --repository ailab-chat -o tsv 2>/dev/null | tr '\n' ' ')
  if [ -n "$tags" ]; then ok "Registry $ACR met image ailab-chat: $tags"; else warn "Registry $ACR bestaat, maar tags niet leesbaar (rechten of nog geen image)"; fi
else
  bad "Registry $ACR niet gevonden"
fi

APP_JSON=$(az containerapp show -n $ACA_CHAT -g $RG -o json 2>/dev/null)
if [ -n "$APP_JSON" ]; then
  FQDN=$(echo "$APP_JSON" | python3 -c 'import sys,json;print(json.load(sys.stdin)["properties"]["configuration"]["ingress"]["fqdn"])')
  echo "$APP_JSON" | python3 -c '
import sys, json
a = json.load(sys.stdin); p = a["properties"]; c = p["template"]["containers"][0]
print("       Status:", p.get("runningStatus"), "| revisie:", p.get("latestRevisionName"), "| image:", c["image"].split("/")[-1])
names = {e["name"] for e in c.get("env", [])}
need = ["AZURE_OPENAI_ENDPOINT","MODEL_DEPLOYMENTS","AZURE_SEARCH_ENDPOINT","AZURE_SEARCH_INDEX","FOUNDRY_PROJECT_ENDPOINT","AGENT_NAME"]
miss = [n for n in need if n not in names]
print("ENVMISS=" + ",".join(miss))
' > /tmp/aca.txt
  grep -v '^ENVMISS=' /tmp/aca.txt
  ok "Container App $ACA_CHAT bestaat (https://$FQDN)"
  miss=$(grep '^ENVMISS=' /tmp/aca.txt | cut -d= -f2)
  if [ -z "$miss" ]; then ok "Alle omgevingsvariabelen van dag 3/4 staan erin"; else bad "Omgevingsvariabelen ontbreken: $miss"; fi
  APP_MI=$(echo "$APP_JSON" | python3 -c 'import sys,json;print((json.load(sys.stdin).get("identity") or {}).get("principalId") or "")')
  [ -n "$APP_MI" ] && ok "System-assigned managed identity staat aan" || bad "Managed identity van $ACA_CHAT staat uit"
  check_role "App-MI: Cognitive Services OpenAI User op Foundry" "$APP_MI" "$FOUNDRY_ID" "Cognitive Services OpenAI User|Foundry User|Azure AI User" "Nodig om het model aan te roepen."
  [ -n "$SEARCH_ID" ] && check_role "App-MI: Search Index Data Reader op Search" "$APP_MI" "$SEARCH_ID" "Search Index Data (Reader|Contributor)" "Nodig voor RAG."
  [ -n "$ACR_ID" ] && check_role "App-MI: AcrPull op registry" "$APP_MI" "$ACR_ID" "AcrPull|Container Registry Repository Reader" "Nodig om een nieuwe revisie te starten."
else
  bad "Container App $ACA_CHAT niet gevonden"
fi

# =====================================================================
kop "Dag 4 - Agent, knowledge base en gemeente-API"
PROJ_MI=$(az resource show --ids $PROJ_ID --api-version 2025-06-01 --query identity.principalId -o tsv 2>/dev/null)
[ -n "$SEARCH_ID" ] && check_role "Project-MI: Search Index Data Reader op Search" "$PROJ_MI" "$SEARCH_ID" "Search Index Data (Reader|Contributor)" "Anders 403 op het MCP-endpoint van kb-beleid (dag 4 stap 3)."
[ -n "$APP_JSON" ] && check_role "App-MI: agentrol op het project" "$APP_MI" "$PROJ_ID" "Foundry Agent Consumer|Foundry User|Azure AI User|Azure AI Developer" "Geef Foundry Agent Consumer op proj-ailab (dag 4 stap 9)."

if [ -n "$FQDN" ]; then
  BASE="https://$FQDN"
  kop "Functionele tests via de app (eerste aanroep kan traag zijn: de app schaalt vanaf nul)"
  code=$(curl -s -o /tmp/health.json -w "%{http_code}" --max-time 120 "$BASE/health")
  if [ "$code" = "200" ]; then ok "/health = 200  $(cat /tmp/health.json)"; else bad "/health = $code (app start niet? Kijk bij Revisions and replicas en de log stream)"; fi

  code=$(curl -s -o /tmp/afval.json -w "%{http_code}" --max-time 60 "$BASE/api/afvalkalender?postcode=1234AB")
  if [ "$code" = "200" ]; then ok "Gemeente-API afvalkalender = 200"
  elif [ "$code" = "401" ]; then warn "Gemeente-API geeft 401: de API-sleutel van dag 5 staat al aan"
  else bad "Gemeente-API afvalkalender = $code"; fi
  srv=$(curl -s --max-time 60 "$BASE/openapi.json" | python3 -c 'import sys,json;print(json.load(sys.stdin)["servers"][0]["url"])' 2>/dev/null)
  if [[ "$srv" == https://* ]]; then ok "OpenAPI-spec: server-URL $srv"; else bad "OpenAPI-spec: server-URL '$srv' (moet met https:// beginnen)"; fi

  # 1. alleen het model
  r=$(curl -s --max-time 120 -X POST "$BASE/" --data-urlencode "prompt=Antwoord met precies het woord OK." \
        --data-urlencode "deployment=gpt-54-mini" --data-urlencode "effort=standaard" --data-urlencode "source=model" | parse_html)
  case "$r" in ANS*) ok "Model via managed identity: $(echo "$r" | cut -d'|' -f2)";; ERR*) bad "Model: ${r#ERR|}";; *) bad "Model: ${r#NONE|}";; esac

  # 2. RAG
  r=$(curl -s --max-time 120 -X POST "$BASE/" --data-urlencode "prompt=Wat kost een tweede parkeervergunning in zone B?" \
        --data-urlencode "deployment=gpt-54-mini" --data-urlencode "effort=standaard" --data-urlencode "source=rag" | parse_html)
  case "$r" in
    ANS*) a=$(echo "$r" | cut -d'|' -f2); n=$(echo "$r" | cut -d'|' -f4)
          if echo "$a" | grep -q "180"; then ok "RAG: $n bronnen, antwoord noemt € 180"; else warn "RAG werkt ($n bronnen), maar noemt geen 180: $a"; fi;;
    ERR*) bad "RAG: ${r#ERR|}";; *) bad "RAG: ${r#NONE|}";;
  esac

  # 3. agent met knowledge base
  r=$(curl -s --max-time 180 -X POST "$BASE/agent" --data-urlencode "q=Wat kost een tweede parkeervergunning in zone B?" | parse_html)
  case "$r" in
    ANS*) a=$(echo "$r" | cut -d'|' -f2); s=$(echo "$r" | cut -d'|' -f3)
          info "Tool-stappen: ${s:-geen}"
          if echo "$a" | grep -q "180"; then ok "Agent + knowledge base: antwoord noemt € 180"; else warn "Agent antwoordt, maar zonder 180 (knowledge base gebruikt?): $a"; fi;;
    ERR*) bad "Agent (kennis): ${r#ERR|}";; *) bad "Agent (kennis): ${r#NONE|}";;
  esac

  # 4. agent met OpenAPI-tool
  r=$(curl -s --max-time 180 -X POST "$BASE/agent" --data-urlencode "q=Wanneer wordt bij postcode 1234AB het restafval opgehaald?" | parse_html)
  case "$r" in
    ANS*) a=$(echo "$r" | cut -d'|' -f2); s=$(echo "$r" | cut -d'|' -f3)
          info "Tool-stappen: ${s:-geen}"
          if echo "$a" | grep -Eq "20[0-9]{2}-[0-9]{2}-[0-9]{2}|maandag|dinsdag|woensdag|donderdag|vrijdag|[0-9]{1,2} (januari|februari|maart|april|mei|juni|juli|augustus|september|oktober|november|december)"; then
            ok "Agent + gemeente-API: antwoord noemt een ophaaldag"
          else warn "Agent antwoordt, maar zonder datum (tool gebruikt?): $a"; fi;;
    ERR*) bad "Agent (API-tool): ${r#ERR|}";; *) bad "Agent (API-tool): ${r#NONE|}";;
  esac
else
  kop "Functionele tests overgeslagen: geen Container App gevonden"
fi

# =====================================================================
kop "Samenvatting"
echo "  ${G}$PASS OK${N}   ${Y}$WARN let op${N}   ${R}$FAIL fout${N}"
if [ $FAIL -eq 0 ]; then
  echo "  ${G}${B}Alles van dag 1 t/m 4 werkt. Je kunt aan dag 5 beginnen.${N}"
else
  echo "  Los eerst deze punten op:"; for f in "${FAILS[@]}"; do echo "   - $f"; done
  echo "  Rol net toegekend? Wacht 5-10 minuten en herstart de revisie van $ACA_CHAT."
fi
rm -f /tmp/aca.txt /tmp/health.json /tmp/afval.json
