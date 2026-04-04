#!/bin/bash
set -e

INSTALL_DIR="/opt/hermes-agent"

mkdir -p "$HERMES_HOME"/{cron,sessions,logs,hooks,memories,skills}
[ -f "$HERMES_HOME/.env" ]        || cp "$INSTALL_DIR/.env.example" "$HERMES_HOME/.env"

# Inject credentials into hermes .env (hermes reads this file, env vars alone aren't enough)
sed -i "s|^GLM_API_KEY=.*|GLM_API_KEY=$GLM_API_KEY|" "$HERMES_HOME/.env"
sed -i "s|^# GLM_BASE_URL=.*|GLM_BASE_URL=$GLM_BASE_URL|" "$HERMES_HOME/.env"
[ -f "$HERMES_HOME/config.yaml" ] || cp "$INSTALL_DIR/cli-config.yaml.example" "$HERMES_HOME/config.yaml"
[ -f "$HERMES_HOME/SOUL.md" ]     || cp "$INSTALL_DIR/docker/SOUL.md" "$HERMES_HOME/SOUL.md"
[ -d "$INSTALL_DIR/skills" ] && python3 "$INSTALL_DIR/tools/skills_sync.py"

# Patch config: model + MCP server
python3 -c "
import yaml, os
cfg_path = os.environ['HERMES_HOME'] + '/config.yaml'
with open(cfg_path) as f:
    cfg = yaml.safe_load(f)
cfg.setdefault('model', {})
cfg['model']['default'] = 'glm-4.7'
cfg['model']['provider'] = 'zai'
cfg.setdefault('agent', {})
cfg['agent']['reasoning_effort'] = 'low'
cfg['mcp_servers'] = {
    'social-awareness': {
        'command': 'python3',
        'args': ['/opt/social_awareness_server.py'],
        'env': {
            'MATRIX_HOMESERVER': os.environ['MATRIX_HOMESERVER'],
            'MATRIX_USER_ID': os.environ['MATRIX_USER_ID'],
            'MATRIX_ACCESS_TOKEN': os.environ['MATRIX_ACCESS_TOKEN'],
        },
    }
}
with open(cfg_path, 'w') as f:
    yaml.dump(cfg, f, default_flow_style=False)
"

cd "$INSTALL_DIR"

if [ $# -gt 0 ]; then
  exec hermes "$@"
else
  echo "Agent ready: $MATRIX_USER_ID"
  echo "Run: docker exec -it <container> hermes chat"
  exec sleep infinity
fi
