# Deploy Superretometer 0.10.0 to emergent-mcp-test

## Target

- **Instance:** `i-0d2202177b8b93563` (`emergent-mcp-test`, Ubuntu 24.04)
- **Account:** `702167621728`
- **Access:** SSM via profile `rocom-deploy` (`rocom-ec2-deploy` role)
- **Cloudflare:** Tunnel `cb9ce0ea-6539-4dca-a8de-b3e79f2cd2b5`
  - Config: `/etc/cloudflared/config-ec2.yaml`
  - Route: `superretometer.techhappens.eu` → `http://127.0.0.1:3010`

## Prerequisites

- Go 1.26+ installed on the host (or available via `sudo`)
- Docker daemon running
- `sudo` access (SSM user `ssm-user` has passwordless sudo)
- Network access to `github.com` and `go.dev`

## Deploy Steps

```bash
# 1. Install Go 1.26 (if not present)
cd /tmp
sudo rm -rf /usr/local/go
curl -fsSL https://go.dev/dl/go1.26.11.linux-amd64.tar.gz -o go126.tar.gz
sudo tar -C /usr/local -xzf go126.tar.gz

# 2. Clone and checkout release commit
cd /tmp
rm -rf sr-build
git clone https://github.com/euthm/superretometer.git sr-build
cd /tmp/sr-build
git checkout dbc66570b9c60baf8570fc9406cab68d3c2ce4d0  # v0.10.0

# 3. Build binary
cd /tmp/sr-build/go
/usr/local/go/bin/go mod download
/usr/local/go/bin/go build -trimpath \
  -ldflags="-X main.revision=dbc66570b9c60baf8570fc9406cab68d3c2ce4d0" \
  -o /tmp/superretometer-new ./cmd/superretometer
/tmp/superretometer-new --version  # verify: superretometer 0.10.0 (dbc6657...)

# 4. Stop existing container
sudo docker stop superretometer-go 2>/dev/null || true

# 5. Build Docker image
cat > /tmp/Dockerfile.sr << 'DEOF'
FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl && rm -rf /var/lib/apt/lists/*
COPY superretometer-new /usr/local/bin/superretometer-go
RUN chmod 755 /usr/local/bin/superretometer-go
VOLUME ["/data"]
EXPOSE 3010
CMD ["/usr/local/bin/superretometer-go", "mcp", "--listen", "0.0.0.0:3010", "--state", "/data/snapshot.json", "--behind-proxy"]
DEOF

cd /tmp
sudo docker build -f Dockerfile.sr -t emergent-mcp/superretometer-go:0.10.0 .

# 6. Replace container
sudo docker rm -f superretometer-go 2>/dev/null || true
sudo docker volume create superretometer-data 2>/dev/null || true
sudo docker run -d \
  --name superretometer-go \
  --restart unless-stopped \
  -p 127.0.0.1:3010:3010 \
  -v superretometer-data:/data \
  emergent-mcp/superretometer-go:0.10.0

# 7. Verify
sleep 5
curl -sf http://127.0.0.1:3010/healthz  # {"status":"ok","version":"0.10.0",...}
sudo docker ps | grep superretometer
```

## Verify 29 Tools

```bash
# Initialize MCP session
SESSION=$(curl -s -D- http://127.0.0.1:3010/mcp \
  -X POST \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"v","version":"0.1"}}}' \
  | grep -i 'Mcp-Session-Id' | tr -d '\r' | sed 's/.*: //')

# List tools
curl -s http://127.0.0.1:3010/mcp \
  -X POST \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: $SESSION" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
  | grep 'data:' | sed 's/data: //' | python3 -c "
import sys,json
for line in sys.stdin:
    if not line.strip(): continue
    d = json.loads(line)
    tools = d.get('result',{}).get('tools',[])
    print(f'Tool count: {len(tools)}')
"
```

Expected output: `Tool count: 29`

## Cloudflare Tunnel Config

`/etc/cloudflared/config-ec2.yaml` (no secrets — tunnel credentials in `/etc/cloudflared/creds-ec2.json`):

```yaml
tunnel: cb9ce0ea-6539-4dca-a8de-b3e79f2cd2b5
credentials-file: /etc/cloudflared/creds-ec2.json

ingress:
  - hostname: memory.techhappens.eu
    service: http://127.0.0.1:3002

  - hostname: strategy.techhappens.eu
    service: http://127.0.0.1:8090

  - hostname: superretometer.techhappens.eu
    service: http://127.0.0.1:3010

  - service: http_status:404
```

## Rollback

Old binary backup: `/usr/local/bin/superretometer-go.old.bak`

To revert to old container image:

```bash
sudo docker stop superretometer-go
sudo docker rm superretometer-go
# Rebuild from old binary or tag
sudo docker build -f Dockerfile.sr -t emergent-mcp/superretometer-go:rollback .
sudo docker run -d \
  --name superretometer-go \
  --restart unless-stopped \
  -p 127.0.0.1:3010:3010 \
  -v superretometer-data:/data \
  emergent-mcp/superretometer-go:rollback
```

## Data

Docker volume `superretometer-data` → `/data` in container.
State file: `/data/snapshot.json`

To inspect:
```bash
sudo docker exec superretometer-go ls -la /data/
sudo docker exec superretometer-go wc -c /data/snapshot.json
```

## Future Upgrades

1. Update `git checkout` to new commit
2. Update `-ldflags` revision
3. Rebuild binary and Docker image
4. Stop/remove old container, start new
5. Verify healthz + 29 tools

The volume `superretometer-data` persists across container replacements.
