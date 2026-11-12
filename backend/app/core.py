import os
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import create_engine, String, Integer, Boolean, DateTime, ForeignKey, Text, JSON, Index, select, func, or_
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session, sessionmaker

def now(): return datetime.now(timezone.utc)
class Base(DeclarativeBase): pass
class User(Base):
    __tablename__='users'
    id:Mapped[int]=mapped_column(primary_key=True)
    name:Mapped[str]=mapped_column(String(100)); kind:Mapped[str]=mapped_column(String(20),default='staff')
    active:Mapped[bool]=mapped_column(Boolean,default=True); absent:Mapped[bool]=mapped_column(Boolean,default=False)
class Client(Base):
    __tablename__='clients'
    id:Mapped[int]=mapped_column(primary_key=True); name:Mapped[str]=mapped_column(String(100),unique=True)
class Branch(Base):
    __tablename__='branches'
    id:Mapped[int]=mapped_column(primary_key=True); name:Mapped[str]=mapped_column(String(100),unique=True)
class Role(Base):
    __tablename__='roles'
    id:Mapped[int]=mapped_column(primary_key=True); name:Mapped[str]=mapped_column(String(60),unique=True)
class Permission(Base):
    __tablename__='permissions'
    id:Mapped[int]=mapped_column(primary_key=True); role_id:Mapped[int]=mapped_column(ForeignKey('roles.id'),index=True)
    action:Mapped[str]=mapped_column(String(60))
class Grant(Base):
    __tablename__='grants'
    id:Mapped[int]=mapped_column(primary_key=True); user_id:Mapped[int]=mapped_column(ForeignKey('users.id'),index=True)
    role_id:Mapped[int]=mapped_column(ForeignKey('roles.id'))
    client_id:Mapped[Optional[int]]=mapped_column(ForeignKey('clients.id'),nullable=True)
    branch_id:Mapped[Optional[int]]=mapped_column(ForeignKey('branches.id'),nullable=True)
    direction:Mapped[Optional[str]]=mapped_column(String(10),nullable=True)
    mode:Mapped[Optional[str]]=mapped_column(String(10),nullable=True)
    valid_from:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
    valid_until:Mapped[Optional[datetime]]=mapped_column(DateTime(timezone=True),nullable=True)
    revoked:Mapped[bool]=mapped_column(Boolean,default=False)
Index('ix_grant_scope','grants','user_id','role_id','client_id','branch_id')
class Job(Base):
    __tablename__='jobs'
    id:Mapped[int]=mapped_column(primary_key=True)
    client_id:Mapped[int]=mapped_column(ForeignKey('clients.id'))
    branch_id:Mapped[int]=mapped_column(ForeignKey('branches.id'))
    direction:Mapped[str]=mapped_column(String(10)); mode:Mapped[str]=mapped_column(String(10))
    stage:Mapped[str]=mapped_column(String(20),default='Confirmed')
    owner_id:Mapped[Optional[int]]=mapped_column(ForeignKey('users.id'),nullable=True)
    prepared_by:Mapped[Optional[int]]=mapped_column(ForeignKey('users.id'),nullable=True)
    checked_by:Mapped[Optional[int]]=mapped_column(ForeignKey('users.id'),nullable=True)
    version:Mapped[int]=mapped_column(Integer,default=1)
Index('ix_job_scope_stage','jobs','stage','client_id','branch_id','direction','mode')
class Audit(Base):
    __tablename__='audit'
    id:Mapped[int]=mapped_column(primary_key=True)
    occurred_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,index=True)
    actor_id:Mapped[Optional[int]]=mapped_column(Integer,nullable=True)
    job_id:Mapped[Optional[int]]=mapped_column(Integer,nullable=True,index=True)
    event:Mapped[str]=mapped_column(String(70)); details:Mapped[dict]=mapped_column(JSON,default=dict)

ROLE_ACTIONS={'Viewer':['job.view'],'Maker':['job.view','job.prepare'],'Checker':['job.view','job.check'],'Filer':['job.view','job.file'],'Supervisor':['job.view','job.reassign','job.request_reopen','job.request_cancel'],'Admin':['job.view','grant.manage','role.manage','job.reassign','job.request_reopen','job.request_cancel','job.approve_exception'],'ClientViewer':['job.view'],'Parser':['job.create','job.parser_update']}
WORKFLOW={'job.prepare':('Confirmed','Prepared'),'job.check':('Prepared','Checked'),'job.file':('Checked','Filed')}

def engine_for(url=None):
    from sqlalchemy.engine import URL

    if url is None:
        url = os.getenv("DATABASE_URL")

    if url is None and os.getenv("NFPL_DB_PASSWORD"):
        url = URL.create(
            drivername="postgresql+psycopg",
            username="nfpl_user",
            password=os.environ["NFPL_DB_PASSWORD"],
            host="127.0.0.1",
            port=5432,
            database="nfpl_dev",
        )

    if url is None:
        raise RuntimeError(
            "Database not configured. Set DATABASE_URL or NFPL_DB_PASSWORD."
        )

    is_sqlite = str(url).startswith("sqlite")

    return create_engine(
        url,
        connect_args={"check_same_thread": False} if is_sqlite else {},
        pool_pre_ping=True,
    )

def audit(db,actor,event,job=None,**details): db.add(Audit(actor_id=actor,event=event,job_id=job,details=details))

def decision(db:Session,user_id:int,action:str,job:Job|None=None,at:datetime|None=None):
    user=db.get(User,user_id)
    if not user or not user.active: return {'allowed':False,'reason_code':'INACTIVE_OR_UNKNOWN','explanation':'User does not exist or is inactive.'}
    if user.absent and action!='job.view': return {'allowed':False,'reason_code':'USER_ABSENT','explanation':'Absent users cannot perform work.'}
    if user.kind=='service' and action not in ('job.create','job.parser_update'): return {'allowed':False,'reason_code':'SERVICE_RESTRICTED','explanation':'Service identities cannot perform staff actions.'}
    if job is None and action not in ('grant.manage','role.manage','job.create'):
        return {'allowed':False,'reason_code':'JOB_REQUIRED','explanation':'A job is required for this action.'}
    if job is not None and action in WORKFLOW:
        expected,_=WORKFLOW[action]
        if job.stage!=expected: return {'allowed':False,'reason_code':'INVALID_STAGE','explanation':f'{action} requires {expected}; job is {job.stage}.'}
        if action=='job.check' and job.prepared_by==user_id: return {'allowed':False,'reason_code':'SEPARATION_OF_DUTIES','explanation':'The person who prepared the job cannot check it.'}
        if action=='job.file' and job.checked_by==user_id: return {'allowed':False,'reason_code':'SEPARATION_OF_DUTIES','explanation':'The person who checked the job cannot file it.'}
    if job is not None and action=='job.parser_update' and job.stage not in ('Confirmed','Prepared'):
        return {'allowed':False,'reason_code':'PARSER_STAGE_LOCK','explanation':'Parser cannot alter checked or filed jobs.'}
    moment=at or now()
    grants=db.execute(select(Grant,Role.name).join(Role,Grant.role_id==Role.id).join(Permission,Permission.role_id==Role.id).where(Grant.user_id==user_id,Permission.action==action,Grant.revoked==False,Grant.valid_from<=moment,or_(Grant.valid_until==None,Grant.valid_until>moment))).all()
    for grant,role in grants:
        if job is not None and ((grant.client_id is not None and grant.client_id!=job.client_id) or (grant.branch_id is not None and grant.branch_id!=job.branch_id) or (grant.direction is not None and grant.direction!=job.direction) or (grant.mode is not None and grant.mode!=job.mode)):
            continue
        if user.kind=='client' and (role!='ClientViewer' or grant.client_id is None): continue
        return {'allowed':True,'reason_code':'MATCHED_GRANT','explanation':f'{role} grant #{grant.id} matches the action and job scope.','matched_role':role,'grant_id':grant.id}
    return {'allowed':False,'reason_code':'NO_MATCHING_GRANT','explanation':'No active role grant covers this action and scope.'}

def require(db,user_id,action,job=None):
    from fastapi import HTTPException
    result=decision(db,user_id,action,job)
    if not result['allowed']: raise HTTPException(403,detail=result)
    return result
