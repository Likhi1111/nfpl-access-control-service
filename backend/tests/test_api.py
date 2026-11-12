import os,tempfile
from fastapi.testclient import TestClient
from sqlalchemy import create_engine,select
from sqlalchemy.orm import Session
from app.core import Base,Job
from app.seed import seed
from app import main

def test_admin_self_escalation_and_two_person_exception(tmp_path):
    url='sqlite:///'+str(tmp_path/'api.db')
    engine=create_engine(url,connect_args={'check_same_thread':False})
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        seed(db)
        filed=db.scalar(select(Job).where(Job.stage=='Filed'))
        filed_id=filed.id
    original_engine,original_session=main.engine,main.SessionLocal
    from sqlalchemy.orm import sessionmaker
    main.engine=engine;main.SessionLocal=sessionmaker(engine,expire_on_commit=False)
    try:
        with TestClient(main.app) as c:
            h={'X-Actor-Id':'1'}
            r=c.post('/api/grants',headers=h,json={'user_id':1,'role_id':1})
            assert r.status_code==403
            r=c.post(f'/api/jobs/{filed_id}/exception-request',headers=h,json={'action':'cancel','justification':'Customer requests cancellation'})
            assert r.status_code==200
            r=c.post(f'/api/jobs/{filed_id}/exception-approve',headers=h,json={'approve':True,'justification':'Independent review approved'})
            assert r.status_code==403
            # No second approver seeded: grant approval power to a different user, by admin.
            with Session(engine) as db:
                from app.core import Role
                role=db.scalar(select(Role).where(Role.name=='Admin'))
                role_id=role.id
            assert c.post('/api/grants',headers=h,json={'user_id':8,'role_id':role_id}).status_code==200
            r=c.post(f'/api/jobs/{filed_id}/exception-approve',headers={'X-Actor-Id':'8'},json={'approve':True,'justification':'Independently checked request'})
            assert r.status_code==200
            assert r.json()['stage']=='Cancelled'
    finally:
        main.engine,main.SessionLocal=original_engine,original_session
