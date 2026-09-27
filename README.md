# ailab-chat

Kleine Flask-app voor het AI-lab. Roept een Microsoft Foundry-model aan via de Responses API
met de **managed identity** van de host. Er staan geen sleutels in de code of in de
configuratie, dus deze repo mag openbaar zijn.

- **Dag 2**: draait op Azure App Service (code-deploy).
- **Dag 3**: RAG met Azure AI Search, en dezelfde code als container op Azure Container Apps.

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

## Rechten voor de managed identity van de app

| Rol | Op | Waarvoor |
|---|---|---|
| Cognitive Services OpenAI User | Foundry-resource | het model aanroepen |
| Search Index Data Reader | Search-service | de index doorzoeken (dag 3) |
| AcrPull | Container registry | image ophalen (alleen Container Apps; zet het portal zelf) |

## Pagina's

- `/`: chat. Kies het model, de reasoning effort en de bron: alleen het model, of je documenten (RAG, met bronnen en scores)
- `/info`: configuratie, hosting en identiteit (zonder geheimen)
- `/stress`: stuurt snel verzoeken zonder retries om quota-limieten (HTTP 429) te laten zien
- `/health`: health check (JSON)

## Container lokaal of in de cloud bouwen

```bash
# In de cloud, zonder Docker (ACR Tasks):
az acr build -r <acr-naam> -t ailab-chat:v1 .
# Met Docker (bijv. in GitHub Codespaces):
docker build -t <acr-naam>.azurecr.io/ailab-chat:v1 . && docker push <acr-naam>.azurecr.io/ailab-chat:v1
```
De container luistert op poort **8000**.
