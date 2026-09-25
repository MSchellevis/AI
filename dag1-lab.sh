#!/usr/bin/env bash
# Dag 1 lab - stap 0 t/m 4 in Cloud Shell (vanaf stap 5 werk je in de portals)
# Bedoeld voor Azure Cloud Shell (Bash). Voer de stappen EEN VOOR EEN uit
# (kopieer per blok) - het leren zit in het lezen van de uitvoer.
# Zie het document Dag1_Landschap_AI_en_Hosting.docx voor uitleg per stap.


# Stap 0 - controle (Azure Cloud Shell, Bash)
az version --query '"azure-cli"' -o tsv          # moet 2.80.0 of hoger zijn
az account show --query "{naam:name, id:id}" -o table
# Meerdere subscriptions? Kies de juiste:
# az account set --subscription "<naam-of-id>"

# Stap 1 - variabelen voor de HELE week, bewaard in ~/ailab.env
SUFFIX=$(openssl rand -hex 3)          # uniek achtervoegsel, bv. 3f9a2c
cat > ~/ailab.env <<EOF
export LOC=swedencentral
export RG=rg-ailab-week
export SUFFIX=$SUFFIX
export FOUNDRY=fdy-ailab-$SUFFIX
export PROJECT=proj-ailab
export DEPLOY=gpt-54-mini
export ACA_ENV=cae-ailab
export ACA_APP=ca-hello-$SUFFIX
export ASP=asp-ailab-f1
export WEBAPP=app-hello-$SUFFIX
EOF
source ~/ailab.env
echo "Jouw suffix is: $SUFFIX  (schrijf deze op!)"
# Elke volgende dag / nieuwe Cloud Shell-sessie:  source ~/ailab.env

# Stap 2 - resource providers registreren (eenmalig per subscription)
for ns in Microsoft.CognitiveServices Microsoft.App Microsoft.OperationalInsights Microsoft.Web; do
  az provider register --namespace $ns
done
# Controle (herhaal tot alles 'Registered' is, duurt 1-3 min):
for ns in Microsoft.CognitiveServices Microsoft.App Microsoft.OperationalInsights Microsoft.Web; do
  echo "$ns: $(az provider show -n $ns --query registrationState -o tsv)"
done

# Stap 3 - resource group met tags (alles van deze week komt hierin)
az group create -n $RG -l $LOC \
  --tags purpose=interview-lab owner=mark cleanup=end-of-week
az group show -n $RG --query "{naam:name, regio:location, tags:tags}" -o json

# Stap 4 - budget + alerts: doe dit in de portal (Cost Management > Budgets), zie document.

# Vanaf stap 5: Foundry-portal (ai.azure.com) en Azure-portal. Na stap 5 eventueel:

# Na stap 5 (portal): klopt de naam van de Foundry-resource met ailab.env?
source ~/ailab.env
az cognitiveservices account list -g $RG --query "[].name" -o tsv   # de echte naam
# Wijkt die af van $FOUNDRY? Vul hieronder de echte naam in en voer uit:
# sed -i "s/^export FOUNDRY=.*/export FOUNDRY=<echte-naam>/" ~/ailab.env && source ~/ailab.env
echo "FOUNDRY in ailab.env: $FOUNDRY"
