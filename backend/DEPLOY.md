# Deploying the Edge Sentinel backend on Alibaba Cloud

The hackathon requires the reasoning to run on the **hosted Qwen Cloud API** (base URL
`https://dashscope-intl.aliyuncs.com/compatible-mode/v1`, visible in `agent/client.py`) and demands
**Proof of Deployment**. Any of the three routes below satisfies it; pick one.

## Prerequisites
- A Qwen Cloud / Alibaba Cloud Model Studio API key (`DASHSCOPE_API_KEY`).
- This repo, public, with an MIT/Apache-2.0 licence file visible in the About section.

## Route A — Function Compute (serverless, cheapest)
1. Create a **Function Compute 3.0** service → **HTTP-triggered web function**, **custom runtime**, Python 3.10+.
2. Set the startup command to run the ASGI app:
   ```
   uvicorn app:app --host 0.0.0.0 --port 9000
   ```
   (listen port = the port FC injects, commonly 9000; read `$FC_SERVER_PORT` if set).
3. Upload the code (zip) with `requirements.txt`; enable build so deps install.
4. Set environment variables: `DASHSCOPE_API_KEY`, `CONSENT_SECRET`, `QWEN_MODEL`, `BASELINE_STORE=memory`
   (FC is stateless — for a persistent baseline use Table Store/Redis or the device-supplied-baseline mode).
5. Enable the **HTTP trigger**, copy the public URL. Visiting `/` returns the health JSON — **this is your proof-of-deployment URL.** Keep it reachable through judging (judges test live).

**Screenshot note (important):** the judges' examples show *instances* marked "Running" (ECS / Simple
Application Server). A serverless function won't show an instance, so make the FC screenshot unambiguous:
the **function overview + the HTTP trigger URL + the region + a recent successful invocation in the logs/metrics**.
If you want the exact "running resource" image with zero doubt, also stand up Route B or C and screenshot that.

## Route B — Elastic Compute Service (ECS) — clearest "running instance" screenshot
1. Launch a small ECS instance (Ubuntu). SSH in.
2. `git clone` the repo, `pip install -r requirements.txt`.
3. Export the env vars, then run behind a process manager:
   ```
   uvicorn app:app --host 0.0.0.0 --port 80
   ```
   (or gunicorn with uvicorn workers). Open port 80 in the security group.
4. Screenshot the ECS console showing the instance **Running** + hit `http://<public-ip>/` for the health JSON.

## Route C — Simple Application Server — same idea, simpler console
Same steps as ECS on a Simple Application Server instance; screenshot it **Running** and hit `/`.

## Verify
```
curl https://<your-deployment>/          # -> {"status":"ok","service":"aevum-edge-sentinel",...}
```

## The two proof-of-deployment artefacts to submit
1. **Code-file link:** `agent/client.py` — the `DASHSCOPE_BASE_URL` is visible, proving hosted Qwen Cloud use.
2. **Screenshot** (`qwen-proof.jpg`): the running resource per the note above.

## Local run (no cloud, no key)
```
pip install -r requirements.txt
FORCE_MOCK=1 uvicorn app:app --reload      # offline mock agent
# or with a real key:
export DASHSCOPE_API_KEY=sk-...  &&  uvicorn app:app --reload
```
