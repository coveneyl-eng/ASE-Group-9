# Flood Detector agent

An always-on container that consumes `flood.readings` (what `load_all.py` publishes), decides whether Dublin Port
has reached a CFRAM flood band, lists the infrastructure inside that flood extent, and publishes a `flood.impacts`
event. Each decision is also stored in the `agent_decisions` table. It's ported from Vaibhav's
`thin-slice/smartcity/agents/flood_detector.py` (plus his `bus.py` consume loop and `base.py` decision log), cut down to
this slice's message format and tables.

```
load_all.py (ingest) --flood.readings--> flood-agent --flood.impacts--> ...
                                              +--> readings, agent_decisions (Postgres)
```

## Run locally

```bash
cd flood-thin-slice
docker compose up -d                      # db + kafka
python load_all.py                        # loads the layers (cfram_nodes, flood_extent_coast, infrastructure ...)
docker build -t flood-agent agent
docker run --rm --network host flood-agent                                  # leave running
docker run --rm --network host flood-agent python flood_agent.py --send 2.9 # simulated flood reading
```

The agent logs `FLOOD Dublin Port 2.90 m >= 0.5% AEP level: N assets ...`, and the event appears on `flood.impacts`:

```bash
docker compose exec kafka /opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server localhost:9092 \
  --topic flood.impacts --from-beginning
```

## Azure (Container Instances)

Build and push it next to the ingest image:

```bash
docker build --platform linux/amd64 -t $ACR.azurecr.io/flood-agent:latest flood-thin-slice/agent
docker push $ACR.azurecr.io/flood-agent:latest
```

If Kafka runs as a container in the **same container group** as the ingest, add the agent to that group so it
reaches Kafka on `localhost:9092`. Kafka's default listener advertises `localhost`, so a separate container
group can't connect to it.

```yaml
  - name: flood-agent
    properties:
      image: $ACR_SERVER/flood-agent:latest
      resources: {requests: {cpu: 0.5, memoryInGB: 0.5}}
      environmentVariables:
      - name: DB_URL
        secureValue: "$DB_URL"          # same value as the ingest container
```

If Kafka is reachable from elsewhere, for example Event Hubs, set `KAFKA` and the `KAFKA_SASL_*` variables exactly
as for the ingest. Check that it's running with
`az container logs -g $RG -n $ACI --container-name flood-agent --follow`.

## Settings

The agent uses the same names as `load_all.py`: `DB_URL`, `KAFKA`, `KAFKA_TOPIC`, `KAFKA_SECURITY_PROTOCOL`,
`KAFKA_SASL_MECHANISM`, `KAFKA_SASL_USERNAME` and `KAFKA_SASL_PASSWORD`. These are specific to the agent:
`KAFKA_GROUP` (default `flood-agent`), `IMPACT_TOPIC` (default `flood.impacts`), `WATCH_STATION` (default
`Dublin Port`), `OFFSET_RESET` (default `earliest`) and `MAX_ASSETS` (default 200).
