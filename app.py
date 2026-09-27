"""AI-lab chat-app (dag 2 + dag 3).

Een kleine Flask-app die een Foundry-model aanroept via de Responses API,
met de managed identity van de host (App Service of Container Apps). Geen API-sleutels.
Dag 3 voegt RAG toe: de app zoekt eerst in een Azure AI Search-index (hybride +
semantisch) en laat het model antwoorden op basis van die bronnen, met bronvermelding.

Instellingen (App Service: Environment variables / Container Apps: Environment variables):
  AZURE_OPENAI_ENDPOINT        https://<foundry-resource>.openai.azure.com/openai/v1/
  MODEL_DEPLOYMENTS            gpt-54-mini,gpt-54-nano   (deploymentnamen, komma-gescheiden)
  AZURE_SEARCH_ENDPOINT        https://<search-service>.search.windows.net   (dag 3)
  AZURE_SEARCH_INDEX           beleid                                         (dag 3)
  AZURE_SEARCH_SEMANTIC_CONFIG (optioneel) standaard <index>-semantic-configuration
  RAG_TOP                      (optioneel) aantal bronnen, standaard 5
  APP_VERSION                  (optioneel) label dat bovenin de pagina staat, bijv. v1 / v2
  TOKEN_SCOPE                  (optioneel) standaard https://cognitiveservices.azure.com/.default
"""

import os
import time
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, render_template_string, request

app = Flask(__name__)

SCOPE = os.environ.get("TOKEN_SCOPE", "https://cognitiveservices.azure.com/.default")
EFFORTS = ["standaard", "low", "medium", "high"]


def endpoint() -> str:
    """Normaliseer het endpoint naar .../openai/v1/."""
    ep = os.environ.get("AZURE_OPENAI_ENDPOINT", "").strip().rstrip("/")
    if not ep:
        return ""
    if not ep.endswith("/openai/v1"):
        ep = ep + "/openai/v1"
    return ep + "/"


def deployments() -> list:
    raw = os.environ.get("MODEL_DEPLOYMENTS", "gpt-54-mini")
    return [d.strip() for d in raw.split(",") if d.strip()]


_token_provider = None


def token_provider():
    """DefaultAzureCredential vindt op App Service automatisch de managed identity."""
    global _token_provider
    if _token_provider is None:
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider
        _token_provider = get_bearer_token_provider(DefaultAzureCredential(), SCOPE)
    return _token_provider


def get_client(max_retries: int = 2):
    from openai import OpenAI
    return OpenAI(base_url=endpoint(), api_key=token_provider(), max_retries=max_retries)


def explain_error(exc: Exception) -> dict:
    """Vertaal fouten naar een leerzame uitleg (dat is de les van het lab)."""
    name = type(exc).__name__
    status = getattr(exc, "status_code", None)
    retry_after = None
    resp = getattr(exc, "response", None)
    if resp is not None and getattr(resp, "headers", None) is not None:
        retry_after = resp.headers.get("retry-after") or resp.headers.get("retry-after-ms")
    if name in ("CredentialUnavailableError", "ClientAuthenticationError") or "DefaultAzureCredential" in str(exc):
        hint = ("Geen identiteit gevonden. Staat de system-assigned managed identity van deze "
                "web-app aan (Settings > Identity)?")
    elif status in (401, 403):
        hint = ("Geen toegang (data plane). Heeft de managed identity van deze web-app de rol "
                "'Cognitive Services OpenAI User' op de Foundry-resource? Na toekennen kan het "
                "tot 5 minuten duren (RBAC-propagatie).")
    elif status == 404:
        hint = ("Niet gevonden. Klopt de deploymentnaam in MODEL_DEPLOYMENTS, en eindigt "
                "AZURE_OPENAI_ENDPOINT op .openai.azure.com/openai/v1/?")
    elif status == 429:
        hint = ("Rate limit bereikt: de deployment heeft zijn quota (tokens of requests per "
                "minuut) opgebruikt. Wacht, verhoog de TPM of spreid de load.")
    elif status == 400:
        hint = ("Ongeldig verzoek. Vaak een parameter die dit model niet ondersteunt "
                "(probeer reasoning effort op 'standaard').")
    elif name == "APIConnectionError":
        hint = "Endpoint onbereikbaar. Klopt AZURE_OPENAI_ENDPOINT (en het netwerk)?"
    else:
        hint = "Onverwachte fout, zie de melding."
    return {"type": name, "status": status, "retry_after": retry_after,
            "hint": hint, "message": str(exc)[:600]}


def usage_dict(resp) -> dict:
    u = getattr(resp, "usage", None)
    if u is None:
        return {}
    out_details = getattr(u, "output_tokens_details", None)
    in_details = getattr(u, "input_tokens_details", None)
    return {
        "input": getattr(u, "input_tokens", None),
        "cached": getattr(in_details, "cached_tokens", None) if in_details else None,
        "output": getattr(u, "output_tokens", None),
        "reasoning": getattr(out_details, "reasoning_tokens", None) if out_details else None,
        "total": getattr(u, "total_tokens", None),
    }


def ask(deployment: str, prompt: str, instructions: str = "", effort: str = "standaard",
        max_retries: int = 2) -> dict:
    kwargs = {"model": deployment, "input": prompt}
    if instructions:
        kwargs["instructions"] = instructions
    if effort and effort != "standaard":
        kwargs["reasoning"] = {"effort": effort}
    start = time.perf_counter()
    try:
        resp = get_client(max_retries=max_retries).responses.create(**kwargs)
        return {
            "ok": True,
            "text": resp.output_text,
            "model": getattr(resp, "model", None),
            "usage": usage_dict(resp),
            "seconds": round(time.perf_counter() - start, 2),
        }
    except Exception as exc:  # noqa: BLE001 - we tonen elke fout bewust
        return {"ok": False, "error": explain_error(exc),
                "seconds": round(time.perf_counter() - start, 2)}


# ---------------------------------------------------------------- dag 3: RAG
RAG_INSTRUCTIONS = (
    "Je bent een assistent voor de (fictieve) gemeente Voorbeeldstad. Beantwoord de vraag "
    "UITSLUITEND met de genummerde bronnen hieronder. Verwijs na elke bewering naar de bron "
    "als [1], [2] enz. Staat het antwoord niet in de bronnen, zeg dan letterlijk: "
    "'Dat staat niet in de documenten die ik kan raadplegen.' Verzin niets. Antwoord in het Nederlands."
)


def search_endpoint() -> str:
    return os.environ.get("AZURE_SEARCH_ENDPOINT", "").strip().rstrip("/")


def search_index() -> str:
    return os.environ.get("AZURE_SEARCH_INDEX", "").strip()


def semantic_config() -> str:
    return os.environ.get("AZURE_SEARCH_SEMANTIC_CONFIG", "").strip() or f"{search_index()}-semantic-configuration"


def rag_configured() -> bool:
    return bool(search_endpoint() and search_index())


def rag_top() -> int:
    try:
        return max(1, min(10, int(os.environ.get("RAG_TOP", "5"))))
    except ValueError:
        return 5


_credential = None


def credential():
    """Dezelfde managed identity, nu voor Azure AI Search (scope https://search.azure.com)."""
    global _credential
    if _credential is None:
        from azure.identity import DefaultAzureCredential
        _credential = DefaultAzureCredential()
    return _credential


def get_search_client():
    from azure.search.documents import SearchClient
    return SearchClient(endpoint=search_endpoint(), index_name=search_index(), credential=credential())


def explain_search_error(exc: Exception) -> dict:
    name = type(exc).__name__
    status = getattr(exc, "status_code", None)
    if name in ("CredentialUnavailableError", "ClientAuthenticationError") and status is None:
        hint = "Geen identiteit gevonden. Staat de managed identity van deze app aan?"
    elif status in (401, 403):
        hint = ("Geen toegang tot de zoekindex. Twee oorzaken: (1) de managed identity van deze app mist "
                "de rol 'Search Index Data Reader' op de Search-service, of (2) de Search-service accepteert "
                "alleen API-sleutels: zet Settings > Keys > API access control op 'Both' of 'Role-based access "
                "control'. Na toekennen kan het tot 5-10 minuten duren.")
    elif status == 404:
        hint = "Index niet gevonden. Klopt AZURE_SEARCH_INDEX (de naam uit de Import data-wizard)?"
    elif status == 400:
        hint = ("Ongeldige zoekopdracht. Vaak een verkeerde naam van de semantische configuratie "
                "(AZURE_SEARCH_SEMANTIC_CONFIG), een index zonder vectorizer, of een index die niet door de "
                "Import data-wizard (RAG) is gemaakt: de app verwacht de velden title, chunk en text_vector.")
    elif name in ("ServiceRequestError", "ServiceRequestTimeoutError"):
        hint = "Search-endpoint onbereikbaar. Klopt AZURE_SEARCH_ENDPOINT (en het netwerk)?"
    else:
        hint = "Onverwachte fout bij het zoeken, zie de melding."
    return {"type": name, "status": status, "retry_after": None, "hint": hint,
            "message": str(exc)[:600], "stage": "zoeken (Azure AI Search)"}


def retrieve(question: str, top: int = 5) -> dict:
    """Hybride zoekopdracht (trefwoord + vector) met semantische herrangschikking.

    De vector voor de vraag maakt Azure AI Search zelf (integrated vectorization): de app
    stuurt alleen tekst. Mislukt de semantische stap (bijv. verkeerde configuratienaam),
    dan valt de app terug op gewoon hybride zoeken en meldt dat.
    """
    from azure.search.documents.models import VectorizableTextQuery
    start = time.perf_counter()
    client = get_search_client()
    vq = VectorizableTextQuery(text=question, k_nearest_neighbors=50, fields="text_vector")
    base = dict(search_text=question, vector_queries=[vq], top=top,
                select=["title", "chunk"])
    mode = "hybride + semantisch"
    try:
        results = list(client.search(query_type="semantic",
                                     semantic_configuration_name=semantic_config(), **base))
    except Exception as exc:  # noqa: BLE001
        if getattr(exc, "status_code", None) != 400:
            raise
        results = list(client.search(**base))
        mode = "hybride (semantisch mislukt: controleer AZURE_SEARCH_SEMANTIC_CONFIG)"
    sources = []
    for i, r in enumerate(results, start=1):
        sources.append({
            "n": i,
            "title": r.get("title") or "(zonder titel)",
            "chunk": (r.get("chunk") or "").strip(),
            "score": round(r.get("@search.score") or 0, 4),
            "reranker": (round(r["@search.reranker_score"], 2)
                         if r.get("@search.reranker_score") is not None else None),
        })
    return {"sources": sources, "mode": mode, "seconds": round(time.perf_counter() - start, 2)}


def rag_answer(deployment: str, question: str, effort: str = "standaard") -> dict:
    try:
        found = retrieve(question, rag_top())
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": explain_search_error(exc), "seconds": 0}
    if not found["sources"]:
        return {"ok": True, "text": "Geen bronnen gevonden in de index. Is de indexer klaar en gevuld?",
                "model": None, "usage": {}, "seconds": found["seconds"], "rag": found}
    context = "\n\n".join(f"[{s['n']}] (bron: {s['title']})\n{s['chunk']}" for s in found["sources"])
    prompt = f"Bronnen:\n{context}\n\nVraag: {question}"
    result = ask(deployment, prompt, RAG_INSTRUCTIONS, effort)
    result["rag"] = found
    if result.get("ok"):
        result["seconds"] = round(result["seconds"] + found["seconds"], 2)
    return result


def hosting() -> str:
    if os.environ.get("CONTAINER_APP_NAME"):
        rev = os.environ.get("CONTAINER_APP_REVISION", "?")
        return f"Container Apps ({os.environ['CONTAINER_APP_NAME']}, revisie {rev})"
    if os.environ.get("WEBSITE_SITE_NAME"):
        return f"App Service ({os.environ['WEBSITE_SITE_NAME']})"
    return "lokaal"


PAGE = """<!doctype html>
<html lang="nl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI-lab chat</title>
<style>
 body{font-family:Segoe UI,system-ui,sans-serif;max-width:860px;margin:24px auto;padding:0 16px;color:#201f1e;background:#faf9f8}
 h1{font-size:1.5rem;margin:0 0 4px} .sub{color:#605e5c;margin:0 0 18px}
 nav a{margin-right:14px;color:#0067b8}
 form,.card{background:#fff;border:1px solid #e1dfdd;border-radius:6px;padding:16px;margin:14px 0}
 label{display:block;font-weight:600;margin:10px 0 4px} textarea,select,input{width:100%;box-sizing:border-box;font:inherit;padding:8px;border:1px solid #c8c6c4;border-radius:4px}
 .row{display:flex;gap:12px} .row>div{flex:1}
 button{margin-top:12px;background:#0067b8;color:#fff;border:0;border-radius:4px;padding:9px 18px;font:inherit;cursor:pointer}
 .answer{white-space:pre-wrap} .err{border-color:#d13438;background:#fdf3f4} table{border-collapse:collapse;width:100%}
 td,th{border-bottom:1px solid #edebe9;text-align:left;padding:6px 4px;font-size:.92rem} .muted{color:#605e5c;font-size:.9rem}
 code{background:#f3f2f1;padding:1px 4px;border-radius:3px}
 .badge{background:#0067b8;color:#fff;border-radius:10px;padding:1px 9px;font-size:.8rem;margin-left:6px}
 .src{border-left:3px solid #0067b8;padding:4px 10px;margin:8px 0;background:#f7f9fc} .src p{margin:4px 0;font-size:.88rem;white-space:pre-wrap}
</style></head><body>
<h1>AI-lab chat</h1>
<p class="sub">{{ host }} &rarr; managed identity &rarr; Foundry{% if rag_ok %} + AI Search{% endif %}. Geen sleutels. <span class="badge">{{ version }}</span></p>
<nav><a href="/">Chat</a><a href="/info">Info</a><a href="/stress">Rate-limit test</a><a href="/health">Health</a></nav>
{% if not configured %}
<div class="card err"><b>Niet geconfigureerd.</b> Zet de app setting <code>AZURE_OPENAI_ENDPOINT</code> (en <code>MODEL_DEPLOYMENTS</code>).</div>
{% endif %}
<form method="post" action="/">
 <label for="instructions">Instructies (systeemrol)</label>
 <textarea id="instructions" name="instructions" rows="2">{{ instructions }}</textarea>
 <label for="prompt">Vraag</label>
 <textarea id="prompt" name="prompt" rows="5" required>{{ prompt }}</textarea>
 <div class="row">
  <div><label for="deployment">Deployment</label>
   <select id="deployment" name="deployment">{% for d in deps %}<option {% if d==deployment %}selected{% endif %}>{{ d }}</option>{% endfor %}</select></div>
  <div><label for="effort">Reasoning effort</label>
   <select id="effort" name="effort">{% for e in efforts %}<option {% if e==effort %}selected{% endif %}>{{ e }}</option>{% endfor %}</select></div>
  <div><label for="source">Bron</label>
   <select id="source" name="source"><option value="model" {% if bron=='model' %}selected{% endif %}>Alleen het model</option>
   <option value="rag" {% if bron=='rag' %}selected{% endif %} {% if not rag_ok %}disabled{% endif %}>Mijn documenten (RAG){% if not rag_ok %} - niet ingesteld{% endif %}</option></select></div>
 </div>
 {% if bron=='rag' %}<p class="muted">Bij RAG worden de instructies hierboven vervangen door vaste RAG-instructies: alleen antwoorden uit de bronnen, met [n]-verwijzingen.</p>{% endif %}
 <button type="submit">Verstuur</button>
</form>
{% if result %}
 {% if result.ok %}
 <div class="card"><div class="answer">{{ result.text }}</div></div>
 <div class="card"><table>
  <tr><th>Deployment</th><td>{{ deployment }}</td><th>Model (antwoord)</th><td>{{ result.model }}</td></tr>
  <tr><th>Tijd</th><td>{{ result.seconds }} s</td><th>Reasoning effort</th><td>{{ effort }}</td></tr>
  <tr><th>Input tokens</th><td>{{ result.usage.input }} (cached: {{ result.usage.cached }})</td><th>Output tokens</th><td>{{ result.usage.output }} (waarvan reasoning: {{ result.usage.reasoning }})</td></tr>
 </table><p class="muted">Reasoning tokens worden als output-tokens gerekend: ze kosten geld en tijd, ook al zie je ze niet.{% if result.rag %} Met RAG stijgen de input tokens: de bronnen gaan mee in de prompt.{% endif %}</p></div>
 {% endif %}
 {% if result.rag %}
 <div class="card"><b>Bronnen uit de index</b> <span class="muted">({{ result.rag.sources|length }} stuks, {{ result.rag.mode }}, zoektijd {{ result.rag.seconds }} s)</span>
  {% for s in result.rag.sources %}<div class="src"><b>[{{ s.n }}] {{ s.title }}</b> <span class="muted">score {{ s.score }}{% if s.reranker is not none %} &middot; semantisch {{ s.reranker }} (0-4){% endif %}</span>
  <p>{{ s.chunk[:600] }}{% if s.chunk|length > 600 %}&hellip;{% endif %}</p></div>{% endfor %}</div>
 {% endif %}
 {% if not result.ok %}
 <div class="card err"><b>{{ result.error.type }}{% if result.error.status %} (HTTP {{ result.error.status }}){% endif %}{% if result.error.stage %} bij {{ result.error.stage }}{% endif %}</b>
  <p>{{ result.error.hint }}</p>{% if result.error.retry_after %}<p>Retry-After: {{ result.error.retry_after }}</p>{% endif %}
  <p class="muted">{{ result.error.message }}</p></div>
 {% endif %}
{% endif %}
</body></html>"""

INFO = """<!doctype html><html lang="nl"><head><meta charset="utf-8"><title>Info</title>
<style>body{font-family:Segoe UI,system-ui,sans-serif;max-width:860px;margin:24px auto;padding:0 16px}td,th{text-align:left;padding:6px;border-bottom:1px solid #eee}a{color:#0067b8}</style></head>
<body><h1>Info (geen geheimen)</h1><p><a href="/">&larr; terug</a></p><table>
{% for k, v in rows %}<tr><th>{{ k }}</th><td>{{ v }}</td></tr>{% endfor %}
</table><p>Zie je hierboven <b>nergens een sleutel</b>? Klopt: de app gebruikt alleen zijn managed identity.</p></body></html>"""

STRESS = """<!doctype html><html lang="nl"><head><meta charset="utf-8"><title>Rate-limit test</title>
<style>body{font-family:Segoe UI,system-ui,sans-serif;max-width:860px;margin:24px auto;padding:0 16px}td,th{text-align:left;padding:5px;border-bottom:1px solid #eee}a{color:#0067b8}
select,input,button{font:inherit;padding:6px}button{background:#0067b8;color:#fff;border:0;border-radius:4px;padding:8px 16px}</style></head>
<body><h1>Rate-limit test</h1><p><a href="/">&larr; terug</a></p>
<p>Stuurt snel achter elkaar verzoeken <b>zonder automatische retries</b>, zodat je quota-limieten (HTTP 429) ziet. Zet de TPM van de deployment eerst laag (bijv. 1K).</p>
<form method="post"><label>Deployment <select name="deployment">{% for d in deps %}<option {% if d==deployment %}selected{% endif %}>{{ d }}</option>{% endfor %}</select></label>
<label> Aantal <input name="n" type="number" min="1" max="30" value="{{ n }}"></label> <button>Start</button></form>
{% if results %}<p><b>{{ ok }}</b> geslaagd, <b>{{ throttled }}</b> keer 429, <b>{{ other }}</b> andere fouten.</p>
<table><tr><th>#</th><th>Status</th><th>Tijd</th><th>Retry-After</th><th>Uitleg</th></tr>
{% for r in results %}<tr><td>{{ loop.index }}</td><td>{{ 'OK' if r.ok else r.error.status or r.error.type }}</td><td>{{ r.seconds }} s</td>
<td>{{ '' if r.ok else (r.error.retry_after or '') }}</td><td>{{ '' if r.ok else r.error.hint }}</td></tr>{% endfor %}</table>{% endif %}
</body></html>"""


@app.route("/", methods=["GET", "POST"])
def chat():
    deps = deployments()
    instructions = request.form.get("instructions",
                                    "Je bent een assistent voor een Nederlandse gemeente. Antwoord kort en helder in het Nederlands.")
    prompt = request.form.get("prompt", "")
    deployment = request.form.get("deployment", deps[0] if deps else "")
    effort = request.form.get("effort", "standaard")
    if effort not in EFFORTS:
        effort = "standaard"
    source = request.form.get("source", "model")
    if source not in ("model", "rag") or (source == "rag" and not rag_configured()):
        source = "model"
    result = None
    if request.method == "POST" and prompt.strip() and deployment in deps:
        if source == "rag":
            result = rag_answer(deployment, prompt.strip(), effort)
        else:
            result = ask(deployment, prompt.strip(), instructions.strip(), effort)
    return render_template_string(PAGE, deps=deps, instructions=instructions, prompt=prompt,
                                  deployment=deployment, effort=effort, efforts=EFFORTS,
                                  bron=source, rag_ok=rag_configured(), host=hosting(),
                                  version=os.environ.get("APP_VERSION", "v1"),
                                  result=result, configured=bool(endpoint()))


@app.route("/info")
def info():
    rows = [
        ("Endpoint", endpoint() or "(niet ingesteld)"),
        ("Deployments", ", ".join(deployments())),
        ("Token scope", SCOPE),
        ("Managed identity actief", "ja" if os.environ.get("IDENTITY_ENDPOINT") else "nee (zet Identity aan)"),
        ("Hosting", hosting()),
        ("APP_VERSION", os.environ.get("APP_VERSION", "v1")),
        ("Container (replica)", os.environ.get("HOSTNAME", "(onbekend)") if os.environ.get("CONTAINER_APP_NAME") else "(n.v.t.)"),
        ("App Service SKU", os.environ.get("WEBSITE_SKU", "(n.v.t.)")),
        ("Search-endpoint", search_endpoint() or "(niet ingesteld)"),
        ("Search-index", search_index() or "(niet ingesteld)"),
        ("Semantische configuratie", semantic_config() if rag_configured() else "(n.v.t.)"),
        ("Ingelogde gebruiker (Easy Auth)", request.headers.get("X-MS-CLIENT-PRINCIPAL-NAME", "(geen: authenticatie staat uit)")),
    ]
    return render_template_string(INFO, rows=rows)


@app.route("/stress", methods=["GET", "POST"])
def stress():
    deps = deployments()
    deployment = request.form.get("deployment", deps[-1] if deps else "")
    try:
        n = max(1, min(30, int(request.form.get("n", "12"))))
    except ValueError:
        n = 12
    results = []
    if request.method == "POST" and deployment in deps:
        prompt = "Schrijf een korte alinea (ongeveer 120 woorden) over waarom quota bestaan."
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: ask(deployment, prompt, max_retries=0), range(n)))
    ok = sum(1 for r in results if r["ok"])
    throttled = sum(1 for r in results if not r["ok"] and r["error"]["status"] == 429)
    return render_template_string(STRESS, deps=deps, deployment=deployment, n=n, results=results,
                                  ok=ok, throttled=throttled, other=len(results) - ok - throttled)


@app.route("/health")
def health():
    return {"status": "ok", "configured": bool(endpoint()), "rag": rag_configured(),
            "version": os.environ.get("APP_VERSION", "v1"), "hosting": hosting()}


if __name__ == "__main__":
    app.run(debug=True)
