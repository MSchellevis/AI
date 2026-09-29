# ailab-chat

Kleine Flask-app voor het AI-lab. Roept een Microsoft Foundry-model aan via de Responses API
met de **managed identity** van de host. Er staan geen sleutels in de code of in de
configuratie, dus deze repo mag openbaar zijn.

- **Dag 2**: draait op Azure App Service (code-deploy).
- **Dag 3**: RAG met Azure AI Search, en dezelfde code als container op Azure Container Apps.
- **Dag 4**: pagina `/agent` die een prompt agent in Foundry Agent Service aanroept, en een kleine
  fictieve gemeente-API (`/api/...` + `/openapi.json`) die de agent als OpenAPI-tool gebruikt.
- **Dag 5**: de gemeente-API vraagt header `x-api-key` zodra `GEMEENTE_API_KEY` is gezet (in Container Apps
  als Key Vault-referentie), de app legt guardrail-blokkades (HTTP 400 `content_filter`) uit, en
  testdossier `VBS-2026-0666` bevat een prompt injection om Prompt Shields op tool responses te testen.

## Instellingen (environment variables)

| Naam | Voorbeeld | Sinds |
|---|---|---|
| `AZURE_OPENAI_ENDPOINT` | `https://<foundry-resource>.openai.azure.com/openai/v1/` | dag 2 |
| `MODEL_DEPLOYMENTS` | `gpt-54-mini,gpt-54-nano` | dag 2 |
| `SCM_DO_BUILD_DURING_DEPLOYMENT` | `true` (alleen App Service) | dag 2 |
| `AZURE_SEARCH_ENDPOINT` | `https://<search-service>.search.windows.net` | dag 3 |
| `AZURE_SEARCH_INDEX` | `beleid` | dag 3 |
| `AZURE_SEARCH_SEMANTIC_CONFIG` | optioneel, standaard `<index>-semantic-configuration` | dag 3 |
| `APP_VERSION` | `v1` of `v2` (label bovenin, voor traffic splitting) | dag 3 |
| `FOUNDRY_PROJECT_ENDPOINT` | `https://<foundry>.services.ai.azure.com/api/projects/proj-ailab` | dag 4 |
| `AGENT_NAME` | `voorbeeldstad-assistent` | dag 4 |
| `PUBLIC_BASE_URL` | optioneel: publieke https-URL voor `/openapi.json` | dag 4 |
| `GEMEENTE_API_KEY` | `secretref:gemeente-api-key` (Key Vault-referentie, nooit de waarde zelf in Git) | dag 5 |
| `GEMEENTE_API_KEY_PREVIOUS` | optioneel: vorige sleutel, alleen tijdens een rotatie | dag 5 |

## Rechten voor de managed identity van de app

| Rol | Op | Waarvoor |
|---|---|---|
| Cognitive Services OpenAI User | Foundry-resource | het model aanroepen |
| Search Index Data Reader | Search-service | de index doorzoeken (dag 3) |
| AcrPull | Container registry | image ophalen (alleen Container Apps; zet het portal zelf) |
| Foundry Agent Consumer | Foundry-project | de agent aanroepen (dag 4) |
| Key Vault Secrets User | Key vault | de API-sleutel lezen via de Key Vault-referentie (dag 5) |

## Pagina's

- `/`: chat. Kies het model, de reasoning effort en de bron: alleen het model, of je documenten (RAG, met bronnen en scores)
- `/info`: configuratie, hosting en identiteit (zonder geheimen)
- `/agent`: gesprek met de Foundry-agent, met de tool-aanroepen per antwoord (dag 4)
- `/api/afvalkalender?postcode=1234AB` en `/api/aanvragen/VBS-2026-1234`: fictieve gemeente-API (dag 4)
- `/openapi.json`: OpenAPI 3-beschrijving van die API, om als tool in Foundry te plakken (dag 4)
- `/stress`: stuurt snel verzoeken zonder retries om quota-limieten (HTTP 429) te laten zien
- `/health`: health check (JSON)

## Container lokaal of in de cloud bouwen

```bash
# In de cloud, zonder Docker (ACR Tasks):
az acr build -r <acr-naam> -t ailab-chat:v5 .   # let op de punt
# Met Docker (bijv. in GitHub Codespaces):
docker build -t <acr-naam>.azurecr.io/ailab-chat:v5 . && docker push <acr-naam>.azurecr.io/ailab-chat:v5
```
De container luistert op poort **8000**.
