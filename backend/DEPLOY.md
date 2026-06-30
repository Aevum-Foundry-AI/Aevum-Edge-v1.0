# Deploying the backend on Alibaba Cloud

You need the backend running on Alibaba Cloud for two reasons: the hackathon
requires it, and the public URL is your **Proof of Alibaba Cloud Deployment**.
Two routes - Function Compute is the quickest.

---

## Option A - Function Compute (recommended)

Serverless, cheap, and gives you a public HTTPS URL in minutes.

1. **Get a Qwen API key.** Alibaba Cloud Model Studio / DashScope -> create an
   API key. Keep it; it becomes the `DASHSCOPE_API_KEY` env var below.

2. **Create a web function.** Function Compute console -> *Create Function* ->
   *Web Function* -> runtime **Python 3.10+**.

3. **Upload the code.** Upload `app.py` and `requirements.txt` from this
   `backend/` folder (zip them together, or paste `app.py` and add the
   dependencies in the build step).

4. **Set the start command** so the platform launches the server on its port:
   ```
   uvicorn app:app --host 0.0.0.0 --port 9000
   ```
   (Function Compute web functions listen on port 9000 by default.)

5. **Set the environment variable** `DASHSCOPE_API_KEY` to your key.
   Optionally set `QWEN_MODEL` (default `qwen3.7-plus`) and `CONSENT_TOKEN`.

6. **Enable the HTTP trigger** and copy the public URL.

7. **Test it.** Open the URL in a browser:
   ```
   GET  https://<your-function-url>/
   ->   {"service":"aevum-edge-sentinel","status":"ok","model":"qwen3.7-plus"}
   ```
   That response is your deployment proof. Then point the firmware's
   `BACKEND_URL` at `https://<your-function-url>/assess`.

---

## Option B - ECS (a normal server)

1. Launch a small ECS instance (Ubuntu). In the security group, open the port
   you'll serve on (e.g. 9000, or 80 behind nginx).
2. On the instance:
   ```bash
   sudo apt update && sudo apt install -y python3-pip
   pip3 install -r requirements.txt
   export DASHSCOPE_API_KEY=your_key_here
   uvicorn app:app --host 0.0.0.0 --port 9000
   ```
3. (Optional) Put nginx in front for port 80 / TLS.
4. Test `http://<ecs-public-ip>:9000/` - same health JSON as above.

---

## Recording the deployment proof (~30-60s)

Screen-record this short sequence:

1. Open the public Alibaba Cloud URL `/` in a browser - show the health JSON.
2. (Optional but strong) Send one test request to `/assess` and show the
   structured wellbeing flag coming back, e.g.:
   ```bash
   curl -X POST https://<your-function-url>/assess \
     -H "Content-Type: application/json" \
     -d '{"consent_token":"demo-consent-granted","heart_rate_bpm":88,
          "motion_index":0.4,"skin_temp_c":34.6,"ambient_temp_c":22.1,
          "ambient_hum_pct":48,"baseline":{"heart_rate_bpm":64,"skin_temp_c":33.5}}'
   ```
3. Show the Function Compute (or ECS) console page proving it's hosted on
   Alibaba Cloud.

Link that recording, plus this repo file, in the submission's deployment field.
