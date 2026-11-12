import os
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session
from .core import *
engine=engine_for()
SessionLocal=sessionmaker(engine,expire_on_commit=False)
@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    yield
app=FastAPI(title='NFPL Access Control',version='1.0',lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=os.getenv('CORS_ORIGINS','http://localhost:5173').split(','),allow_credentials=False,allow_methods=['*'],allow_headers=['*'])
def db_session():
    with SessionLocal() as db: yield db
def actor(x_actor_id:int=Header(...),db:Session=Depends(db_session)):
    # DEMO ONLY: identity via header, never expose as production authentication.
    u=db.get(User,x_actor_id)
    if not u or not u.active: raise HTTPException(401,'Unknown/inactive demo identity')
    return u
class CheckRequest(BaseModel):
    user_id:int; action:str; job_id:int|None=None
class GrantRequest(BaseModel):
    user_id:int; role_id:int; client_id:int|None=None; branch_id:int|None=None; direction:str|None=None; mode:str|None=None
class RoleRequest(BaseModel):
    name:str; actions:list[str]
class JobRequest(BaseModel):
    client_id:int; branch_id:int; direction:str; mode:str; owner_id:int|None=None
class TransitionRequest(BaseModel):
    action:str
class ReassignRequest(BaseModel):
    owner_id:int
class ExceptionRequest(BaseModel):
    action:str=Field(pattern='^(cancel|reopen)$'); justification:str=Field(min_length=12)
class ApprovalRequest(BaseModel):
    approve:bool; justification:str=Field(min_length=12)
class ParserUpdate(BaseModel):
    owner_id:int|None=None

def job_out(j): return {'id':j.id,'client_id':j.client_id,'branch_id':j.branch_id,'direction':j.direction,'mode':j.mode,'stage':j.stage,'owner_id':j.owner_id,'prepared_by':j.prepared_by,'checked_by':j.checked_by,'version':j.version}
@app.get('/health')
def health(): return {'status':'ok'}
@app.get('/api/meta')
def meta(db:Session=Depends(db_session)):
    return {'users':[{'id':u.id,'name':u.name,'kind':u.kind,'absent':u.absent} for u in db.scalars(select(User).order_by(User.id))],'clients':[{'id':c.id,'name':c.name} for c in db.scalars(select(Client))],'branches':[{'id':b.id,'name':b.name} for b in db.scalars(select(Branch))],'roles':[{'id':r.id,'name':r.name} for r in db.scalars(select(Role))]}
@app.post('/api/authorize')
def authorize(req:CheckRequest,who:User=Depends(actor),db:Session=Depends(db_session)):
    job=db.get(Job,req.job_id) if req.job_id else None
    if req.job_id and not job: raise HTTPException(404,'Job not found')
    if who.id!=req.user_id: require(db,who.id,'grant.manage')
    result=decision(db,req.user_id,req.action,job)
    audit(db,who.id,'access_checked',req.job_id,subject=req.user_id,action=req.action,result=result)
    db.commit()
    return result
@app.get('/api/jobs')
def jobs(page:int=Query(1,ge=1),size:int=Query(25,ge=1,le=100),stage:str|None=None,who:User=Depends(actor),db:Session=Depends(db_session)):
    stmt=select(Job)
    if stage: stmt=stmt.where(Job.stage==stage)
    # SQL scope prefilter; exact decision applied to results (no leaking total of hidden jobs).
    grants=db.scalars(select(Grant).join(Role).join(Permission).where(Grant.user_id==who.id,Permission.action=='job.view',Grant.revoked==False,Grant.valid_from<=now(),or_(Grant.valid_until==None,Grant.valid_until>now()))).all()
    if not grants: return {'items':[],'page':page,'has_more':False}
    scope=[]
    for g in grants:
        cond=[]
        if g.client_id is not None: cond.append(Job.client_id==g.client_id)
        if g.branch_id is not None: cond.append(Job.branch_id==g.branch_id)
        if g.direction is not None: cond.append(Job.direction==g.direction)
        if g.mode is not None: cond.append(Job.mode==g.mode)
        from sqlalchemy import and_
        scope.append(and_(*cond))
    stmt=stmt.where(or_(*scope)).order_by(Job.id).offset((page-1)*size).limit(size+1)
    items=[job_out(j) for j in db.scalars(stmt) if decision(db,who.id,'job.view',j)['allowed']]
    return {'items':items[:size],'page':page,'has_more':len(items)>size}
@app.get('/api/jobs/{job_id}')
def get_job(job_id:int,who:User=Depends(actor),db:Session=Depends(db_session)):
    j=db.get(Job,job_id)
    if not j: raise HTTPException(404,'Not found')
    require(db,who.id,'job.view',j)
    return job_out(j)
@app.post('/api/jobs')
def create_job(req:JobRequest,who:User=Depends(actor),db:Session=Depends(db_session)):
    require(db,who.id,'job.create')
    if req.direction not in ('import','export') or req.mode not in ('air','FCL','LCL'): raise HTTPException(422,'Invalid direction or mode')
    j=Job(**req.model_dump()); db.add(j); db.flush(); audit(db,who.id,'job_created',j.id,after=job_out(j)); db.commit(); return job_out(j)
@app.post('/api/jobs/{job_id}/transition')
def transition(job_id:int,req:TransitionRequest,who:User=Depends(actor),db:Session=Depends(db_session)):
    j=db.get(Job,job_id)
    if not j: raise HTTPException(404,'Not found')
    if req.action not in WORKFLOW: raise HTTPException(422,'Invalid action')
    require(db,who.id,req.action,j)
    before=job_out(j); j.stage=WORKFLOW[req.action][1]; j.version+=1
    if req.action=='job.prepare': j.prepared_by=who.id
    if req.action=='job.check': j.checked_by=who.id
    audit(db,who.id,'job_transition',j.id,action=req.action,before=before,after=job_out(j)); db.commit(); return job_out(j)
@app.post('/api/jobs/{job_id}/reassign')
def reassign(job_id:int,req:ReassignRequest,who:User=Depends(actor),db:Session=Depends(db_session)):
    j=db.get(Job,job_id)
    if not j: raise HTTPException(404,'Not found')
    require(db,who.id,'job.reassign',j)
    target=db.get(User,req.owner_id)
    if not target or not target.active or target.absent or not decision(db,target.id,'job.view',j)['allowed']: raise HTTPException(422,'New owner must be active, present, and able to view job')
    previous=j.owner_id; j.owner_id=target.id; j.version+=1; audit(db,who.id,'job_reassigned',j.id,old_owner=previous,new_owner=target.id); db.commit(); return job_out(j)
@app.post('/api/grants')
def add_grant(req:GrantRequest,who:User=Depends(actor),db:Session=Depends(db_session)):
    require(db,who.id,'grant.manage')
    if who.id==req.user_id: raise HTTPException(403,'Admins cannot grant themselves permissions')
    if not db.get(User,req.user_id) or not db.get(Role,req.role_id): raise HTTPException(422,'Invalid user or role')
    if req.direction and req.direction not in ('import','export'): raise HTTPException(422,'Invalid direction')
    if req.mode and req.mode not in ('air','FCL','LCL'): raise HTTPException(422,'Invalid mode')
    g=Grant(**req.model_dump()); db.add(g); db.flush(); audit(db,who.id,'grant_created',target_user=req.user_id,grant_id=g.id,scope=req.model_dump()); db.commit(); return {'id':g.id}
@app.delete('/api/grants/{grant_id}')
def revoke(grant_id:int,who:User=Depends(actor),db:Session=Depends(db_session)):
    require(db,who.id,'grant.manage'); g=db.get(Grant,grant_id)
    if not g: raise HTTPException(404,'Not found')
    if g.user_id==who.id: raise HTTPException(403,'Admins cannot modify their own grants')
    g.revoked=True; g.valid_until=now(); audit(db,who.id,'grant_revoked',target_user=g.user_id,grant_id=g.id); db.commit(); return {'revoked':True}
@app.post('/api/roles')
def create_role(req:RoleRequest,who:User=Depends(actor),db:Session=Depends(db_session)):
    require(db,who.id,'role.manage')
    # Prevent role editing as an escalation bypass: privileged permission names are reserved.
    allowed={'job.view','job.prepare','job.check','job.file','job.reassign'}
    if not req.actions or any(a not in allowed for a in req.actions): raise HTTPException(403,'Role creation limited to nonprivileged permissions')
    if db.scalar(select(Role).where(Role.name==req.name)): raise HTTPException(409,'Role exists')
    r=Role(name=req.name); db.add(r); db.flush()
    for a in set(req.actions): db.add(Permission(role_id=r.id,action=a))
    audit(db,who.id,'role_created',role_id=r.id,actions=req.actions); db.commit(); return {'id':r.id,'name':r.name}
@app.get('/api/inbox')
def inbox(page:int=Query(1,ge=1),size:int=Query(20,ge=1,le=100),who:User=Depends(actor),db:Session=Depends(db_session)):
    # SQL stage/scope prefilter then the exact authorization engine determines membership.
    actions=['job.prepare','job.check','job.file']
    grants=db.execute(select(Grant,Permission.action).join(Permission,Permission.role_id==Grant.role_id).where(Grant.user_id==who.id,Grant.revoked==False,Grant.valid_from<=now(),or_(Grant.valid_until==None,Grant.valid_until>now()),Permission.action.in_(actions))).all()
    from sqlalchemy import and_
    clauses=[]
    for g,a in grants:
        expected=WORKFLOW[a][0]; terms=[Job.stage==expected]
        if g.client_id is not None: terms.append(Job.client_id==g.client_id)
        if g.branch_id is not None: terms.append(Job.branch_id==g.branch_id)
        if g.direction is not None: terms.append(Job.direction==g.direction)
        if g.mode is not None: terms.append(Job.mode==g.mode)
        clauses.append(and_(*terms))
    if not clauses or who.absent: return {'items':[],'page':page,'has_more':False}
    # keyset-friendly id ordering, with chunked authorization to preserve correct page sizes.
    last=0; matched=[]
    while len(matched)<size+1:
        chunk=db.scalars(select(Job).where(Job.id>last,or_(*clauses)).order_by(Job.id).limit(500)).all()
        if not chunk: break
        last=chunk[-1].id
        for j in chunk:
            allowed=[a for a in actions if decision(db,who.id,a,j)['allowed']]
            if allowed: matched.append({**job_out(j),'available_actions':allowed})
            if len(matched)>=page*size+1: break
        if len(matched)>=page*size+1: break
    start=(page-1)*size
    return {'items':matched[start:start+size],'page':page,'has_more':len(matched)>page*size}
@app.get('/api/jobs/{job_id}/history')
def history(job_id:int,who:User=Depends(actor),db:Session=Depends(db_session)):
    j=db.get(Job,job_id)
    if not j: raise HTTPException(404,'Not found')
    require(db,who.id,'job.view',j)
    return [{'id':a.id,'at':a.occurred_at,'actor_id':a.actor_id,'event':a.event,'details':a.details} for a in db.scalars(select(Audit).where(Audit.job_id==job_id).order_by(Audit.id.desc()).limit(100))]
@app.get('/api/audit')
def audit_log(limit:int=Query(50,ge=1,le=200),who:User=Depends(actor),db:Session=Depends(db_session)):
    require(db,who.id,'grant.manage')
    return [{'id':a.id,'at':a.occurred_at,'actor_id':a.actor_id,'job_id':a.job_id,'event':a.event,'details':a.details} for a in db.scalars(select(Audit).order_by(Audit.id.desc()).limit(limit))]
@app.post('/api/jobs/{job_id}/exception-request')
def exception_request(job_id:int,req:ExceptionRequest,who:User=Depends(actor),db:Session=Depends(db_session)):
    j=db.get(Job,job_id)
    if not j: raise HTTPException(404,'Not found')
    require(db,who.id,'job.request_'+req.action,j)
    if req.action=='cancel' and j.stage!='Filed': raise HTTPException(409,'This exceptional cancel applies only to Filed jobs')
    if req.action=='reopen' and j.stage not in ('Filed','Cancelled'): raise HTTPException(409,'Only Filed/Cancelled jobs may be reopened')
    audit(db,who.id,'exception_requested',j.id,action=req.action,justification=req.justification,job_version=j.version); db.commit()
    return {'requested':True,'job_id':j.id}
@app.post('/api/jobs/{job_id}/exception-approve')
def exception_approve(job_id:int,req:ApprovalRequest,who:User=Depends(actor),db:Session=Depends(db_session)):
    j=db.get(Job,job_id)
    if not j: raise HTTPException(404,'Not found')
    require(db,who.id,'job.approve_exception',j)
    pending=db.scalars(select(Audit).where(Audit.job_id==job_id,Audit.event=='exception_requested').order_by(Audit.id.desc())).all()
    approvals=db.scalars(select(Audit).where(Audit.job_id==job_id,Audit.event.in_(['exception_approved','exception_rejected']))).all()
    resolved={a.details.get('request_id') for a in approvals}
    request=next((a for a in pending if a.id not in resolved),None)
    if not request: raise HTTPException(409,'No pending request')
    if request.actor_id==who.id: raise HTTPException(403,'Requester cannot approve own exception')
    if request.details['job_version']!=j.version: raise HTTPException(409,'Job changed since request')
    action=request.details['action']
    if req.approve:
        j.stage='Cancelled' if action=='cancel' else 'Confirmed'; j.version+=1
        if action=='reopen': j.prepared_by=None; j.checked_by=None
    audit(db,who.id,'exception_approved' if req.approve else 'exception_rejected',j.id,request_id=request.id,action=action,justification=req.justification); db.commit(); return job_out(j)
@app.patch('/api/jobs/{job_id}/parser')
def parser_update(job_id:int,req:ParserUpdate,who:User=Depends(actor),db:Session=Depends(db_session)):
    j=db.get(Job,job_id)
    if not j: raise HTTPException(404,'Not found')
    require(db,who.id,'job.parser_update',j)
    if req.owner_id is not None and not db.get(User,req.owner_id): raise HTTPException(422,'Unknown owner')
    before=job_out(j); j.owner_id=req.owner_id; j.version+=1; audit(db,who.id,'parser_updated',j.id,before=before,after=job_out(j)); db.commit(); return job_out(j)
