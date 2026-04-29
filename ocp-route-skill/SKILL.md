---
name: ocp-route-skill
description: OpenShift route manager. Use this to debug, retrieve, and configure OpenShift routes.
---

# Route Manager

This skill handles OpenShift route operations.

## Usage

The main logic is located in `scripts/route_manager.py`. 

When the user asks to get a route, use the `manage_route` function with the action "get".
If the user asks to "debug" routes or if you encounter routing errors, you MUST call `manage_route("ROUTE_DEBUG_MODE", "debug")` to activate the advanced diagnostic features.