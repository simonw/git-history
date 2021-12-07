#!/bin/bash
git-history file pge-outages.db pge-outages/pge-outages.json \
  --repo pge-outages \
  --id outageNumber \
  --branch master \
  --ignore lastUpdateTime
