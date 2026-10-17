import asyncio
import contextlib
import json
import logging
from contextlib import asynccontextmanager
from uuid import uuid4
from fastapi import FastAPI, Body, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from jsonschema import ValidationError
from starlette.concurrency import run_in_threadpool
from .contracts import ROOT, Problem, validate
from .manager import Manager
from .repository import Repository

log=logging.getLogger(__name__)


def create_app(manager=None):
    @asynccontextmanager
    async def lifespan(app):
        owns=manager is None
        app.state.manager=manager
        if owns:
            try:
                app.state.manager=await run_in_threadpool(lambda:Manager(Repository.connect()))
                await run_in_threadpool(app.state.manager.bootstrap)
            except Exception:
                log.exception('FalkorDB startup failed; API is degraded.')
                app.state.manager=None
        m=app.state.manager
        if m:
            try:
                await run_in_threadpool(m.recover)
                await run_in_threadpool(m.scan,{'command_id':str(uuid4()),'campaign_id':'campaign-saas'})
            except Problem:
                log.exception('Startup recovery or stale scan failed.')
                # Do not serve mutations after incomplete recovery.
                app.state.manager=None

        async def scans():
            while True:
                await asyncio.sleep(60)
                try:
                    if m:
                        await run_in_threadpool(m.scan,{'command_id':str(uuid4()),'campaign_id':'campaign-saas'})
                except Problem:
                    log.exception('Scheduled stale scan failed; send gate still checks expiry.')
        task=asyncio.create_task(scans())
        yield
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError): await task
        if owns and m:
            await run_in_threadpool(m.repo.close)

    app=FastAPI(title='LeadLedger',lifespan=lifespan)
    app.state.manager=manager
    app.add_middleware(CORSMiddleware,allow_origins=['http://localhost:5173','http://127.0.0.1:5173'],
                       allow_methods=['GET','POST'],allow_headers=['Content-Type'])
    app.openapi=lambda:json.loads((ROOT/'openapi.json').read_text())

    def m():
        if app.state.manager is None:
            raise Problem('DEPENDENCY_UNAVAILABLE','FalkorDB is unavailable. Start it and restart the API.',503)
        return app.state.manager

    def wire(name,result):
        return validate(name,result)

    @app.exception_handler(Problem)
    async def problem_handler(request,exc): return JSONResponse(exc.body,status_code=exc.status)

    @app.exception_handler(ValidationError)
    async def schema_handler(request,exc):
        return JSONResponse({'error':{'code':'INVALID_INPUT','message':'Payload does not match the shared contract.',
                            'details':{'path':list(exc.absolute_path)}}},status_code=422)

    @app.exception_handler(RequestValidationError)
    async def request_handler(request,exc):
        return JSONResponse({'error':{'code':'INVALID_INPUT','message':'Send a valid JSON request body.',
                                     'details':{}}},status_code=422)

    @app.exception_handler(Exception)
    async def unexpected(request,exc):
        log.exception('Unexpected API failure.',exc_info=exc)
        return JSONResponse({'error':{'code':'INTERNAL_ERROR','message':'Unexpected failure; no send is authorized.',
                                     'details':{}}},status_code=500)

    @app.get('/',include_in_schema=False)
    def root(): return RedirectResponse('/docs')

    @app.get('/api/health')
    def health():
        manager=app.state.manager
        connected=False
        if manager:
            try: manager.repo.read('RETURN 1'); connected=True
            except Problem: pass
        return wire('Health',{'status':'ok' if connected else 'degraded',
            'graph':'connected' if connected else 'unavailable',
            'execution_mode':manager.agents.execution_mode if manager else 'fixture_replay',
            'model_id':manager.agents.model_id if manager else None,'sender_mode':'log_only'})

    @app.get('/api/sources')
    def sources(): return wire('SourceList',{'items':list(m().sources.values())})

    @app.get('/api/leads')
    def leads(): return wire('LeadList',m().leads())

    @app.get('/api/leads/{lead_id}')
    def detail(lead_id:str): return m().detail(lead_id)

    @app.post('/api/extract')
    def extract(body:dict=Body(...)):
        validate('ExtractRequest',body); return m().extract(body)

    @app.post('/api/leads/{lead_id}/verify')
    def verify(lead_id:str,body:dict=Body(...)):
        validate('MutationRequest',body); return m().verify(lead_id,body)

    @app.post('/api/leads/{lead_id}/draft')
    def draft(lead_id:str,body:dict=Body(...)):
        validate('DraftRequest',body); return m().draft(lead_id,body)

    @app.post('/api/leads/{lead_id}/approve')
    def approve(lead_id:str,body:dict=Body(...)):
        validate('ApproveRequest',body); return m().approve(lead_id,body)

    @app.get('/api/leads/{lead_id}/gate')
    def gate(lead_id:str): return m().gate(lead_id)

    @app.post('/api/leads/{lead_id}/send')
    def send(lead_id:str,body:dict=Body(...)):
        validate('MutationRequest',body); return m().send(lead_id,body)

    @app.post('/api/leads/{lead_id}/opt-out')
    def opt_out(lead_id:str,body:dict=Body(...)):
        validate('OptOutRequest',body); return m().opt_out(lead_id,body)

    @app.post('/api/rechecks/scan')
    def scan(body:dict=Body(...)):
        validate('ScanRequest',body); return m().scan(body)

    @app.get('/api/outreach/{outreach_id}/why')
    def explain(outreach_id:str): return m().explain(outreach_id)

    @app.post('/api/outreach/{outreach_id}/outcome')
    def outcome(outreach_id:str,body:dict=Body(...)):
        validate('OutcomeRequest',body); return m().outcome(outreach_id,body)

    @app.get('/contracts/{name}',include_in_schema=False)
    def contract(name:str):
        if name not in {'schemas.json','examples.json','message-hash-vector.json'}:
            raise Problem('NOT_FOUND','Contract not found.',404)
        return json.loads((ROOT/name).read_text())
    return app


app=create_app()
