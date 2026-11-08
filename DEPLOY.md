# Deploying on a hosting platform

This is a **Python** project. It has no `package.json`, so **npm is never needed**.
If your log says `npm: not found`, the platform's *Build/Install command* or *Start command* is set to an npm command. Change them to:

| Setting | Value |
|---|---|
| Runtime / language | Python (3.10 or newer; 3.13 is fine) |
| Build / Install command | `pip install -r requirements.txt` |
| Start command | `python run.py` |
| Port | the platform's `PORT` variable is used automatically |

Environment variables (Settings > Environment Variables):

| Name | Value |
|---|---|
| `SMS_ENV` | `production` |
| `SECRET_KEY` | a random 32+ character string, e.g. from `python -c "import secrets; print(secrets.token_hex(32))"` |
| `SMS_DATA_DIR` | a folder on a **persistent volume**, e.g. `/data` |
| `SMS_TRUST_PROXY` | `1` (the platform sits behind a proxy that provides HTTPS) |

Upload the **contents** of the project so that `run.py`, `requirements.txt` and the `smsapp` folder are at the top level of the repository.

Open the site: the first screen creates the Super Administrator. Without a persistent volume, records are lost whenever the container restarts.
