cd "$(dirname "$0")"

echo "Stopping Crowd Management Platform"

echo "Stopping Frontend UI..."
cd people-counter-frontend && docker compose down && cd ..

echo "Stopping Gateway..."
cd crowd-management-gateway && docker compose down && cd ..

echo "Stopping API Backend..."
cd crowd-management-api && docker compose down && cd ..

echo "Stopping Keycloak..."
cd keycloak-docker && docker compose down && cd ..

echo "Stopping MQTT Broker..."
cd mqtt-broker && docker compose down && cd ..

echo "========================================="
echo "All services stopped successfully!"
echo "========================================="
