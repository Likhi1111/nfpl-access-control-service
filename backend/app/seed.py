import random, argparse
from sqlalchemy import select
from .core import *
NAMES=['Asha Mehta','Priya Shah','Rahul Desai','Arjun Rao','Neha Kulkarni','Vikram Joshi','Sana Khan','Dev Patel','Meera Iyer','Rohan Nair','Kavya Shah','Ishaan Gupta','Tara Menon','Kabir Sethi','Anaya Rao','Nikhil Jain','Zoya Ali','Om Prakash','Client Contact','Night Parser']
BRANCHES=['Mumbai','Delhi','Chennai','Kolkata','Bengaluru']
CLIENTS=['Acme Imports','Blue Ocean','Cedar Textiles','Delta Foods','Eastline Motors','Falcon Pharma','Global Metals','Horizon Retail','Indigo Chemicals','Jupiter Electronics']
def seed(db,users=20,jobs=320):
    if db.scalar(select(func.count()).select_from(User)): return
    for name in BRANCHES: db.add(Branch(name=name))
    for name in CLIENTS: db.add(Client(name=name))
    for i in range(users): db.add(User(name=NAMES[i] if i<len(NAMES) else f'Staff {i+1}',kind='client' if i==18 else 'service' if i==19 else 'staff',absent=i==5))
    db.flush()
    roles={}
    for name,actions in ROLE_ACTIONS.items():
        r=Role(name=name);db.add(r);db.flush();roles[name]=r.id
        for action in actions:db.add(Permission(role_id=r.id,action=action))
    def grant(u,r,c=None,b=None,d=None,m=None):db.add(Grant(user_id=u,role_id=roles[r],client_id=c,branch_id=b,direction=d,mode=m))
    grant(1,'Admin');grant(1,'Viewer')
    grant(2,'Maker');grant(2,'Checker',1);grant(2,'Checker',2)
    grant(3,'Checker',1,1,'import')
    grant(4,'Maker',1);grant(4,'Viewer')
    grant(5,'Checker');grant(5,'Viewer')
    grant(6,'Maker',2)
    grant(7,'Filer');grant(7,'Viewer')
    grant(8,'Supervisor');grant(8,'Viewer')
    grant(9,'Checker');grant(9,'Viewer')
    grant(10,'Maker');grant(10,'Viewer')
    grant(11,'Checker',3);grant(12,'Maker',4,2)
    grant(13,'Filer',1);grant(14,'Maker',5);grant(15,'Checker',5)
    grant(16,'Viewer');grant(17,'Maker',6);grant(18,'Supervisor');grant(18,'Viewer')
    grant(19,'ClientViewer',1);grant(20,'Parser')
    db.commit()
    stages=['Confirmed','Prepared','Checked','Filed','Cancelled']
    for i in range(jobs):
        stage=stages[i%5];client=(i%10)+1;branch=(i%5)+1
        j=Job(client_id=client,branch_id=branch,direction='import' if i%2==0 else 'export',mode=['air','FCL','LCL'][i%3],stage=stage,owner_id=6 if i%17==0 else 4,prepared_by=4 if stage in ('Prepared','Checked','Filed') else None,checked_by=3 if stage in ('Checked','Filed') else None)
        db.add(j)
        if i and i%2000==0: db.flush();db.expunge_all()
    audit(db,1,'seed_loaded',users=users,jobs=jobs)
    db.commit()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--scale',action='store_true');args=p.parse_args()
    e=engine_for();Base.metadata.create_all(e)
    with Session(e) as s:seed(s,500 if args.scale else 20,200000 if args.scale else 320)
    print('Seed complete')
