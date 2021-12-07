#!/bin/bash
git-history file ca-fires.db ca-fires-history/incidents.json \
  --repo ca-fires-history \
  --id UniqueId \
  --convert 'json.loads(content)["Incidents"]'
