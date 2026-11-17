#!/usr/bin/env bash
# Local dev PKI: one CA signing certs for Mosquitto (MQTT/TLS), NGINX (HTTPS) and Kafka (SASL_SSL).
# Production uses Azure Key Vault-managed certificates instead.
set -euo pipefail
cd "$(dirname "$0")/../certs"
[ -f ca.crt ] && { echo "certs already exist (delete certs/*.crt to regenerate)"; exit 0; }

openssl req -x509 -newkey rsa:2048 -nodes -days 365 -subj "/CN=SmartCity Dev CA" -keyout ca.key -out ca.crt

for name in mosquitto nginx kafka; do
  openssl req -newkey rsa:2048 -nodes -subj "/CN=${name}" -keyout ${name}.key -out ${name}.csr
  printf "subjectAltName=DNS:${name},DNS:localhost,IP:127.0.0.1\n" > ${name}.ext
  openssl x509 -req -in ${name}.csr -CA ca.crt -CAkey ca.key -CAcreateserial -days 365 -extfile ${name}.ext -out ${name}.crt
  rm ${name}.csr ${name}.ext
done

# Kafka (apache/kafka image) wants JKS keystores; build them with keytool inside a JDK container.
openssl pkcs12 -export -in kafka.crt -inkey kafka.key -certfile ca.crt -name kafka -passout pass:changeit -out kafka.p12
if command -v keytool >/dev/null; then KT="keytool"; else KT="docker run --rm -v $PWD:/c -w /c eclipse-temurin:21-jdk keytool"; fi
$KT -importkeystore -srckeystore kafka.p12 -srcstoretype PKCS12 -srcstorepass changeit \
    -destkeystore kafka.keystore.jks -deststorepass changeit -noprompt
$KT -importcert -alias ca -file ca.crt -keystore kafka.truststore.jks -storepass changeit -noprompt
echo changeit > kafka_creds
chmod 644 *.key *.jks kafka_creds   # dev-only: containers run as non-root
echo "certs written to $(pwd)"
