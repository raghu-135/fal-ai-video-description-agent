# R2 Public Bucket

Public S3-compatible storage for the codex hackathon. No credentials needed.

## Base URL

```
https://r2-public.waqaas.workers.dev
```

## Usage

### Read a file
```bash
curl https://r2-public.waqaas.workers.dev/my-file.txt
```

### List files
```bash
curl "https://r2-public.waqaas.workers.dev/?list=1&prefix=autohdr-output&limit=100"
```

### Upload a file
```bash
curl -X PUT -H "Content-Type: video/mp4" --data-binary @video.mp4 \
  https://r2-public.waqaas.workers.dev/videos/my-video.mp4
```

### Upload JSON
```bash
curl -X PUT -H "Content-Type: application/json" \
  -d '{"key": "value"}' \
  https://r2-public.waqaas.workers.dev/data/output.json
```

### Delete a file
```bash
curl -X DELETE https://r2-public.waqaas.workers.dev/my-file.txt
```

### Python
```python
import requests

# Upload
requests.put(
    "https://r2-public.waqaas.workers.dev/results/output.json",
    json={"description": "a cat sitting on a table"},
    headers={"Content-Type": "application/json"}
)

# Download
resp = requests.get("https://r2-public.waqaas.workers.dev/results/output.json")
data = resp.json()
```

## Details

- CORS enabled (works from browser)
- No auth, no API keys
- Supports any file type
- Bucket name: `codex-hackathon-public`
- Backed by Cloudflare R2 (S3-compatible, zero egress fees)

## Deploy

```bash
npx wrangler deploy
```
