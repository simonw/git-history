#!/bin/bash
git-history file sf-bay-511.db 511-events-history/events.json \
  --repo 511-events-history \
  --id id \
  --convert '
data = json.loads(content)
if data.get("error"):
    # {"code": 500, "error": "Error accessing remote data..."}
    return
for event in data["Events"]:
    event["id"] = event["extension"]["event-reference"]["event-identifier"]
    # Remove noisy updated timestamp
    del event["updated"]
    # Drop extension block entirely
    del event["extension"]
    # "schedule" block is noisy but not interesting
    del event["schedule"]
    # Flatten nested subtypes
    event["event_subtypes"] = event["event_subtypes"]["event_subtype"]
    if not isinstance(event["event_subtypes"], list):
        event["event_subtypes"] = [event["event_subtypes"]]
    yield event
'
