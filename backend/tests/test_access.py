import pytest
from sqlalchemy import create_engine,select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.core import *
from app.seed import seed
@pytest.fixture
def db():
    e=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(e)
    with Session(e) as s:
        seed(s)
        yield s
    e.dispose()
def job(db,stage='Prepared',client=1,branch=1,direction='import',prepared=2):
    j=Job(client_id=client,branch_id=branch,direction=direction,mode='air',stage=stage,prepared_by=prepared)
    db.add(j);db.flush();return j
def test_maker_everywhere_checker_subset(db):
    assert decision(db,2,'job.prepare',job(db,'Confirmed',client=8))['allowed']
    assert decision(db,2,'job.check',job(db,client=1,prepared=4))['allowed']
    assert not decision(db,2,'job.check',job(db,client=8,prepared=4))['allowed']
def test_separation_of_duties(db):
    assert decision(db,2,'job.check',job(db,prepared=2))['reason_code']=='SEPARATION_OF_DUTIES'
def test_narrow_scope(db):
    assert decision(db,3,'job.check',job(db,prepared=4))['allowed']
    assert not decision(db,3,'job.check',job(db,direction='export',prepared=4))['allowed']
    assert not decision(db,3,'job.check',job(db,branch=2,prepared=4))['allowed']
def test_absent(db):
    assert decision(db,6,'job.prepare',job(db,'Confirmed',client=2))['reason_code']=='USER_ABSENT'
def test_revoked_immediately(db):
    j=job(db,'Confirmed',client=4);assert decision(db,2,'job.prepare',j)['allowed']
    for g in db.scalars(select(Grant).where(Grant.user_id==2)):g.revoked=True
    db.flush();assert not decision(db,2,'job.prepare',j)['allowed']
def test_filed_is_immutable(db):
    assert decision(db,2,'job.prepare',job(db,'Filed'))['reason_code']=='INVALID_STAGE'
def test_parser_restrictions(db):
    assert decision(db,20,'job.create')['allowed']
    assert decision(db,20,'job.parser_update',job(db,'Confirmed'))['allowed']
    assert not decision(db,20,'job.parser_update',job(db,'Filed'))['allowed']
    assert not decision(db,20,'job.check',job(db))['allowed']
def test_client_isolation(db):
    assert decision(db,19,'job.view',job(db,client=1))['allowed']
    assert not decision(db,19,'job.view',job(db,client=2))['allowed']
    assert not decision(db,19,'job.prepare',job(db,'Confirmed',client=1))['allowed']
def test_unknown_denied(db):
    assert not decision(db,999,'job.view',job(db))['allowed']
