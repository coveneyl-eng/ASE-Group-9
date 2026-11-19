#!/usr/bin/env bash
# Local dev PKI: one CA signing certs for Mosquitto (MQTT/TLS), NGINX (HTTPS) and Kafka (SASL_SSL).
# Production uses Azure Key Vault-managed certificates instead.
# Re-run safely: it only regenerates when a file is missing (use --force to rebuild everything).
set -euo pipefail
cd "$(dirname "$0")/../certs"

NEEDED="ca.crt mosquitto.crt mosquitto.key nginx.crt nginx.key kafka.keystore.jks kafka.truststore.jks kafka_creds"
missing=0
for f in $NEEDED; do [ -s "$f" ] || missing=1; done
if [ "$missing" = 0 ] && [ "${1:-}" != "--force" ]; then
  echo "certs already complete in $(pwd) (run with --force to regenerate)"
  exit 0
fi
rm -f ./*.crt ./*.key ./*.jks ./*.p12 ./*.srl kafka_creds

openssl req -x509 -newkey rsa:2048 -nodes -days 365 -subj "/CN=SmartCity Dev CA" -keyout ca.key -out ca.crt

for name in mosquitto nginx kafka; do
  openssl req -newkey rsa:2048 -nodes -subj "/CN=${name}" -keyout ${name}.key -out ${name}.csr
  printf "subjectAltName=DNS:${name},DNS:localhost,IP:127.0.0.1\n" > ${name}.ext
  openssl x509 -req -in ${name}.csr -CA ca.crt -CAkey ca.key -CAcreateserial -days 365 -extfile ${name}.ext -out ${name}.crt
  rm ${name}.csr ${name}.ext
done

# Kafka (apache/kafka image) wants JKS keystores, made with Java's keytool. macOS ships a /usr/bin/keytool stub
# that only says "install Java", so test that keytool really runs; otherwise borrow the JRE inside the Kafka
# image that docker compose already pulled (no extra download).
openssl pkcs12 -export -in kafka.crt -inkey kafka.key -certfile ca.crt -name kafka -passout pass:changeit -out kafka.p12
keytool_run() {
  if keytool -help >/dev/null 2>&1; then
    keytool "$@"
  else
    docker run --rm -v "$PWD:/c" -w /c --user "$(id -u):$(id -g)" --entrypoint sh apache/kafka:3.9.1 \
      -c 'exec "$(dirname "$(readlink -f "$(command -v java)")")/keytool" "$@"' keytool "$@"
  fi
}
keytool_run -importkeystore -srckeystore kafka.p12 -srcstoretype PKCS12 -srcstorepass changeit \
    -destkeystore kafka.keystore.jks -deststoretype JKS -deststorepass changeit -noprompt
keytool_run -importcert -alias ca -file ca.crt -keystore kafka.truststore.jks -storetype JKS \
    -storepass changeit -noprompt
echo changeit > kafka_creds
chmod 644 ./*.key ./*.jks kafka_creds   # dev-only: containers run as non-root
echo "certs written to $(pwd)"
