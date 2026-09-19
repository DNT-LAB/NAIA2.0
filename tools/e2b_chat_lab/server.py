"""Run from the repository: venv/Scripts/python.exe tools/e2b_chat_lab/server.py"""
from __future__ import annotations
import argparse
import asyncio
from pathlib import Path
import sys
from contextlib import asynccontextmanager
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from tools.e2b_chat_lab.harness import Lab, Ollama, MODEL
from tools.e2b_chat_lab.assets import Assets


def create_app(lab):
    asset_state = {'loading': True}

    @asynccontextmanager
    async def lifespan(app):
        async def load():
            try:
                asset_state.update(await asyncio.to_thread(lab.assets.state))
            except Exception as exc:
                asset_state['error'] = str(exc)
            finally:
                asset_state['loading'] = False
        task = asyncio.create_task(load())
        yield
        await task

    app = FastAPI(docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.lab = lab

    @app.middleware('http')
    async def local_only(request, call_next):
        host = request.headers.get('host', '').split(':')[0]
        origin = request.headers.get('origin')
        if host not in {'127.0.0.1', 'localhost', 'testserver'}:
            return JSONResponse({'error': 'Local host only'}, status_code=403)
        if origin and urlparse(origin).netloc != request.headers.get('host'):
            return JSONResponse({'error': 'Same-origin requests only'}, status_code=403)
        if request.method == 'POST':
            if not request.headers.get('content-type', '').startswith('application/json'):
                return JSONResponse({'error': 'JSON required'}, status_code=415)
            raw = await request.body()
            if len(raw) > 20000:
                return JSONResponse({'error': 'Request too large'}, status_code=413)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        return response

    @app.get('/')
    def index():
        return FileResponse(Path(__file__).parent / 'web/index.html')

    @app.get('/app.js')
    def js():
        return FileResponse(Path(__file__).parent / 'web/app.js', media_type='text/javascript')

    @app.get('/style.css')
    def css():
        return FileResponse(Path(__file__).parent / 'web/style.css', media_type='text/css')

    @app.get('/api/state')
    def state():
        return lab.state() | {'assets': asset_state}

    @app.get('/api/model')
    def model():
        return lab.model.status()

    @app.post('/api/settings')
    async def settings(request: Request):
        try:
            data = await body(request)
            if set(data) != {'context_size'}:
                raise ValueError('context_size만 지정하세요.')
            lab.set_context_size(data['context_size'])
            return lab.state()
        except (ValueError, RuntimeError) as exc:
            return JSONResponse({'error': str(exc)}, status_code=409 if isinstance(exc, RuntimeError) else 400)

    async def body(request):
        try:
            data = await request.json()
            if not isinstance(data, dict):
                raise ValueError()
            return data
        except Exception:
            raise ValueError('JSON object required')

    @app.post('/api/chat')
    async def chat(request: Request):
        try:
            data = await body(request)
            run_id = lab.submit(data.get('message'), data.get('request_id'), data.get('session_id'))
            return {'run_id': run_id}
        except (ValueError, RuntimeError) as exc:
            return JSONResponse({'error': str(exc)}, status_code=409 if isinstance(exc, RuntimeError) else 400)

    @app.post('/api/new')
    def new():
        return lab.reset()

    @app.post('/api/cancel')
    def cancel():
        lab.cancel()
        return {'ok': True}

    @app.post('/api/preferences')
    async def preferences(request: Request):
        try:
            data = await body(request)
            lab.save_preferences(data.get('text'))
            return {'ok': True}
        except ValueError as exc:
            return JSONResponse({'error': str(exc)}, status_code=400)

    @app.get('/api/seek')
    def seek(query: str = '', round_id: int = 0):
        with lab.lock:
            return lab.seek({'query': query[:160], 'round_id': round_id, 'limit': 3}, full=True)

    return app


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--port', type=int, default=7362)
    p.add_argument('--ollama', default='http://127.0.0.1:11435')
    p.add_argument('--model', default=MODEL)
    p.add_argument('--user-data', type=Path)
    p.add_argument('--event-map', type=Path)
    p.add_argument('--glossary', type=Path)
    p.add_argument('--state-dir', type=Path, default=ROOT / 'codex_out/e2b_chat_lab/state')
    args = p.parse_args()
    import uvicorn
    lab = Lab(Ollama(args.ollama, args.model), Assets(ROOT, args.user_data, args.event_map, args.glossary), args.state_dir)
    uvicorn.run(create_app(lab), host='127.0.0.1', port=args.port, access_log=False)


if __name__ == '__main__':
    main()
