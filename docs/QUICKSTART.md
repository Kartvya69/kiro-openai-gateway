# Quick Start Guide

Get Kiro OpenAI Gateway running in under 5 minutes.

## Prerequisites

- Python 3.10 or higher
- Git
- A Kiro IDE account (logged in) or Kiro CLI with AWS SSO

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/Kartvya69/kiro-openai-gateway.git
cd kiro-openai-gateway
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Run the Application

```bash
python main.py
```

The server starts at `http://localhost:8000`. On first run, it will:
- Create `config.yml` from the example template
- Generate an API key automatically (saved to `api_keys.json`)

### 4. Access the Web UI

Open `http://localhost:8000/ui` in your browser and log in with the default secret key: `admin123`

From the Web UI you can:
- View and manage API keys
- Add Kiro accounts
- Configure settings
- Monitor usage

## Configuration

### Environment Variables (Optional)

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string for cloud deployments | Local JSON storage |
| `SECRET_KEY` | Web UI login password | `admin123` |
| `LOG_LEVEL` | Logging verbosity (DEBUG, INFO, WARNING, ERROR) | `INFO` |

### Database Storage

By default, the gateway uses local JSON files for storage (`api_keys.json`, `auth.json`).

For cloud platforms (Heroku, Railway, Render, etc.), set the `DATABASE_URL` environment variable:

```bash
export DATABASE_URL="postgresql://user:password@host:5432/dbname"
```

This enables PostgreSQL storage, which is recommended for:
- Multi-instance deployments
- Persistent storage on ephemeral filesystems
- Production environments

## Usage

### With curl

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{
    "model": "claude-sonnet-4-5",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

### With OpenAI Python SDK

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="YOUR_API_KEY"
)

response = client.chat.completions.create(
    model="claude-sonnet-4-5",
    messages=[{"role": "user", "content": "Hello!"}]
)

print(response.choices[0].message.content)
```

## Next Steps

- [Architecture Overview](en/ARCHITECTURE.md)
- [API Reference](../README.md#-api-reference)
- [Configuration Options](../README.md#%EF%B8%8F-configuration)
