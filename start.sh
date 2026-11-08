#!/bin/sh
# The Cesium ion browser token is injected from the host's environment at startup, so it is never stored in the repo.
if [ -n "$VITE_CESIUM_ION_TOKEN" ]; then
  sed -i "s|__CESIUM_ION_TOKEN__|$VITE_CESIUM_ION_TOKEN|g" frontend_dist/assets/*.js
fi
# Seed the synthetic demo workspace (idempotent), then serve the API and the built frontend on one port.
python scripts/seed_demo_ops.py || echo "demo seed skipped"
exec uvicorn backend.ethnoharvest.api:app --host 0.0.0.0 --port ${PORT:-7860}
