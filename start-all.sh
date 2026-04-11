cd "$(dirname "$0")"

echo "Starting Crowd Management Platform"

echo "Checking the existence of common network... "
docker network create crowd-management-network 2>/dev/null || true

echo "Starting MQTT Broker..."
cd mqtt-broker && docker compose up -d && cd ..


echo "Starting Keycloak (Database & App)..."
cd keycloak-docker && docker compose up -d && cd ..

echo "Waiting for Keycloak to finish starting (this usually takes 30-45 seconds)..."
echo "   (Checking health endpoint...)"
until [ "$(docker inspect -f '{{.State.Health.Status}}' keycloak-app 2>/dev/null)" == "healthy" ]; do
  printf "."
  sleep 4
done
echo -e "\nKeycloak is online and ready!"

echo "Starting API Backend (API, InfluxDB, Grafana)..."
cd crowd-management-api && docker compose up -d && cd ..

echo "Waiting 15 seconds for API to stabilize before starting the gateway..."
sleep 15

echo "Starting Cloud Gateway..."
cd crowd-management-gateway && docker compose up -d && cd ..

echo "Starting Frontend UI..."
cd people-counter-frontend && docker compose up -d && cd ..

echo "========================================="
echo "All services started successfully!"
echo "   Frontend:     http://localhost:5173"
echo "   Gateway:      http://localhost:8082"
echo "   Keycloak:     http://localhost:8080"
echo "   Grafana:      http://localhost:3000"
echo "========================================="
