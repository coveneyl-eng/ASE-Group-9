#!/usr/bin/env bash
# Deploy flood-thin-slice to Azure Container Instances.
# Run from the ROOT of the ASE-Group-9 repo, after `az login`.
#   chmod +x deploy-aci.sh && ./deploy-aci.sh
set -euo pipefail

# ---- settings: change these ----
RG=ase-group9-rg
LOCATION=belgiumcentral                  # one of your allowed regions
ACR_LOCATION=polandcentral               # registry region: must be allowed AND support ACR Tasks (Belgium Central does not)
SUFFIX=${SUFFIX:-$RANDOM}                # ACR and Postgres names must be globally unique; pass SUFFIX=... to reuse
ACR=asegroup9acr$SUFFIX                  # lowercase letters and digits only
PG=asegroup9-pg-$SUFFIX
PG_USER=flood
PG_PASS="${PG_PASS:-Flood-$(openssl rand -hex 8)}"   # pass PG_PASS=... to reuse; letters/digits/dash only, so no URL-encoding is needed in DB_URL
ACI=flood-thin-slice

echo "Postgres password: $PG_PASS   (save it)"

# ---- 1. resource group ----
az group create -n $RG -l $LOCATION -o none

# ---- 2. PostgreSQL with PostGIS ----
if az postgres flexible-server show -g $RG -n $PG -o none 2>/dev/null; then
  # re-run against an existing server: make sure its password matches PG_PASS
  az postgres flexible-server update -g $RG -n $PG --admin-password "$PG_PASS" -o none
else
az postgres flexible-server create -g $RG -n $PG -l $LOCATION \
  --admin-user $PG_USER --admin-password "$PG_PASS" \
  --tier Burstable --sku-name Standard_B1ms --storage-size 32 --version 16 \
  --public-access 0.0.0.0 --yes -o none   # 0.0.0.0 = allow Azure services (ACI IPs are not fixed)
fi
az postgres flexible-server db show -g $RG -s $PG -d flood -o none 2>/dev/null || \
  az postgres flexible-server db create -g $RG -s $PG -d flood -o none
az postgres flexible-server parameter set -g $RG -s $PG \
  --name azure.extensions --value POSTGIS,POSTGIS_RASTER,PGROUTING -o none
# Optional TimescaleDB (the script works without it):
#   az postgres flexible-server parameter set -g $RG -s $PG --name azure.extensions --value POSTGIS,POSTGIS_RASTER,PGROUTING,TIMESCALEDB
#   az postgres flexible-server parameter set -g $RG -s $PG --name shared_preload_libraries --value timescaledb
#   az postgres flexible-server restart -g $RG -n $PG

DB_URL="postgresql+psycopg://$PG_USER:$PG_PASS@$PG.postgres.database.azure.com:5432/flood?sslmode=require"

# ---- 3. container registry + images ----
az acr show -n $ACR -o none 2>/dev/null || \
  az acr create -g $RG -n $ACR -l $ACR_LOCATION --sku Basic --admin-enabled true -o none
# Azure for Students blocks ACR Tasks (TasksOperationsNotAllowed), so build locally by default; CLOUD_BUILD=1 to try az acr build.
if [ "${CLOUD_BUILD:-0}" = 1 ] && az acr build -r $ACR -t thin-slice:latest --platform linux/amd64 -f flood-thin-slice/Dockerfile .; then
  :
else
  docker pull -q python:3.12-slim >/dev/null || {
    echo "Local Docker cannot reach Docker Hub. If 'docker info' shows 'Ubuntu Core', the snap Docker owns the socket;"
    echo "  sudo snap disable docker && sudo systemctl restart docker.socket docker.service"
    exit 1; }
  # own Docker config, so the login works even when ~/.docker/config.json uses Docker Desktop's credsStore
  export DOCKER_CONFIG=$(mktemp -d); trap 'rm -rf "$DOCKER_CONFIG"' EXIT
  az acr login -n $ACR
  docker build --platform linux/amd64 -f flood-thin-slice/Dockerfile -t $ACR.azurecr.io/thin-slice:latest .
  docker push $ACR.azurecr.io/thin-slice:latest
fi
# Copy the sidecar images into ACR so ACI doesn't hit Docker Hub's anonymous pull limit
az acr import -n $ACR --source docker.io/library/eclipse-mosquitto:2 --image eclipse-mosquitto:2 --force
az acr import -n $ACR --source docker.io/apache/kafka:3.8.0 --image kafka:3.8.0 --force

ACR_SERVER=$(az acr show -n $ACR --query loginServer -o tsv)
ACR_PASS=$(az acr credential show -n $ACR --query "passwords[0].value" -o tsv)

# ---- 4. container group: thin slice + mosquitto + kafka sharing localhost ----
cat > aci.yaml <<EOF
apiVersion: 2023-05-01
type: Microsoft.ContainerInstance/containerGroups
name: $ACI
location: $LOCATION
properties:
  osType: Linux
  restartPolicy: Never
  imageRegistryCredentials:
  - server: $ACR_SERVER
    username: $ACR
    password: $ACR_PASS
  containers:
  - name: mosquitto
    properties:
      image: $ACR_SERVER/eclipse-mosquitto:2
      command: ["mosquitto", "-c", "/mosquitto-no-auth.conf"]
      resources: {requests: {cpu: 0.5, memoryInGB: 0.5}}
  - name: kafka
    properties:
      image: $ACR_SERVER/kafka:3.8.0
      resources: {requests: {cpu: 1, memoryInGB: 1.5}}
  - name: thin-slice
    properties:
      image: $ACR_SERVER/thin-slice:latest
      resources: {requests: {cpu: 2, memoryInGB: 4}}
      environmentVariables:
      - name: DB_URL
        secureValue: "$DB_URL"
      # - name: SIM_LEVEL       # uncomment to force a flood reading
      #   value: "2.9"
EOF

az container create -g $RG --file aci.yaml -o none
rm aci.yaml   # it contains secrets

echo
echo "Deployed. Follow the run with:"
echo "  az container logs -g $RG -n $ACI --container-name thin-slice --follow"
echo "When it has finished, stop billing with:"
echo "  az container delete -g $RG -n $ACI --yes"
echo "Remove everything (database, registry) with:"
echo "  az group delete -n $RG --yes"