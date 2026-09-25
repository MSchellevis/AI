# ailab-chat

Kleine Flask-app voor het AI-lab (dag 2): roept een Microsoft Foundry-model aan via de
Responses API met de **managed identity** van de Azure Web App. Er staan geen sleutels
in de code of in de configuratie. Daarom mag deze repo ook gewoon openbaar zijn.

## App settings (Azure-portal > Web App > Settings > Environment variables)

| Naam | Voorbeeld |
|---|---|
| `AZURE_OPENAI_ENDPOINT` | `https://<foundry-resource>.openai.azure.com/openai/v1/` |
| `MODEL_DEPLOYMENTS` | `gpt-54-mini,gpt-54-nano` |
| `SCM_DO_BUILD_DURING_DEPLOYMENT` | `true` |

## Rechten

De system-assigned managed identity van de web-app heeft de rol
**Cognitive Services OpenAI User** nodig op de Foundry-resource.

## Pagina's

- `/`: chat, met modelkeuze, reasoning effort, tijd en tokengebruik
- `/info`: configuratie en identiteit (zonder geheimen)
- `/stress`: stuurt snel verzoeken zonder retries om quota-limieten (HTTP 429) te laten zien
- `/health`: health check
