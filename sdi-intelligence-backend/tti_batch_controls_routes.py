"""Register alongside existing TTI routes after supplying verified host adapters."""
from typing import Literal
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt
from starlette.concurrency import run_in_threadpool
from tti_incremental import ReviewRequired

class TrackerRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    tracker_id: str = 'master'

class PreviewRequest(TrackerRequest):
    mode: Literal['next', 'rerun'] = 'next'
    count: StrictInt = Field(default=5, ge=1, le=50)
    start_row: StrictInt = Field(default=1, ge=1, le=1048576)
    row_ids: list[str] = Field(default_factory=list, max_length=50)
    reason: str = Field(default='', max_length=2000)

class RunRequest(TrackerRequest):
    plan_id: str
    confirm_replace: StrictBool = False

class ReviewRequest(TrackerRequest):
    plan_id: str
    outputs_checked: StrictBool = False
    costs_reviewed: StrictBool = False
    notes: str = Field(default='', max_length=4000)

def make_router(controls, *, check_key, allowed_trackers=('master',), prefix='/tti/batches'):
    router = APIRouter(prefix=prefix)
    async def call(req, key, fn, **kwargs):
        check_key(key)
        if req.tracker_id not in allowed_trackers:
            raise HTTPException(400, 'Unknown configured tracker')
        try:
            return await run_in_threadpool(fn, req.tracker_id, **kwargs)
        except ReviewRequired as e:
            raise HTTPException(409, str(e)) from None

    @router.post('/rows')
    async def rows(req: TrackerRequest, x_sdi_key: str = Header(default='')):
        return await call(req, x_sdi_key, controls.browse)

    @router.post('/preview')
    async def preview(req: PreviewRequest, x_sdi_key: str = Header(default='')):
        return await call(req, x_sdi_key, controls.preview, mode=req.mode, count=req.count,
                          start_row=req.start_row, row_ids=req.row_ids, reason=req.reason)

    @router.post('/run')
    async def run(req: RunRequest, x_sdi_key: str = Header(default='')):
        return await call(req, x_sdi_key, controls.run, plan_id=req.plan_id, confirm_replace=req.confirm_replace)

    @router.post('/review')
    async def review(req: ReviewRequest, x_sdi_key: str = Header(default='')):
        return await call(req, x_sdi_key, controls.review, plan_id=req.plan_id,
                          outputs_checked=req.outputs_checked, costs_reviewed=req.costs_reviewed, notes=req.notes)
    return router
