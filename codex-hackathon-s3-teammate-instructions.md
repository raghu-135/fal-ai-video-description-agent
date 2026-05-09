# Codex Hackathon S3 Access

Bucket:

```text
codex-hackathon-435073375463-20260509-4aaace60
```

Region:

```text
us-east-1
```

Temporary credentials file:

```text
codex-hackathon-s3-temp-credentials.json
```

These credentials expire at:

```text
2026-05-10T15:10:28Z
```

Set up your shell:

```bash
export AWS_ACCESS_KEY_ID="$(python3 -c 'import json; print(json.load(open("codex-hackathon-s3-temp-credentials.json"))["Credentials"]["AccessKeyId"])')"
export AWS_SECRET_ACCESS_KEY="$(python3 -c 'import json; print(json.load(open("codex-hackathon-s3-temp-credentials.json"))["Credentials"]["SecretAccessKey"])')"
export AWS_SESSION_TOKEN="$(python3 -c 'import json; print(json.load(open("codex-hackathon-s3-temp-credentials.json"))["Credentials"]["SessionToken"])')"
export AWS_DEFAULT_REGION="us-east-1"
```

List files:

```bash
aws s3 ls s3://codex-hackathon-435073375463-20260509-4aaace60/
```

Upload a file:

```bash
aws s3 cp ./local-file.txt s3://codex-hackathon-435073375463-20260509-4aaace60/
```

Download a file:

```bash
aws s3 cp s3://codex-hackathon-435073375463-20260509-4aaace60/local-file.txt .
```

Delete a file:

```bash
aws s3 rm s3://codex-hackathon-435073375463-20260509-4aaace60/local-file.txt
```

Treat the credentials JSON like a password. Anyone with the file can read, write, and delete objects in this bucket until the expiration time.
