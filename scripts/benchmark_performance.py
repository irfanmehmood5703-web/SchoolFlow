"""Repeatable local benchmark. Always uses a new in-memory fictional database.
Run from the checkout: python scripts/benchmark_performance.py --students 500
This is backend/test-client timing, not end-to-end browser or hosting wake-up time.
"""
import argparse,json,os,statistics,sys,time
from datetime import date
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ['DATABASE_URL']='sqlite:///:memory:'
from sqlalchemy import event
from app import app,db,Student,Employee


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--students',type=int,default=500);args=parser.parse_args()
    if app.config['SQLALCHEMY_DATABASE_URI']!='sqlite:///:memory:':raise SystemExit('Benchmark requires an isolated in-memory database.')
    if not 10<=args.students<=10000:raise SystemExit('Choose 10–10,000 fictional students.')
    app.config.update(TESTING=True,IDENTITY_ENFORCE_IN_TESTS=False)
    with app.app_context():
        rm=app.extensions['record_models'];ops=app.extensions['ops_models'];Plan=app.extensions['student_fee_plan_model']
        family=[]
        for i in range((args.students+1)//2):
            row=rm['family'](number=f'BENCH-F-{i}',data=dict(father=f'Fictional Guardian {i}',phone='00000000000'))
            db.session.add(row);family.append(row)
        db.session.flush()
        pupils=[]
        for i in range(args.students):
            pupil=Student(admission_no=f'BENCH-{i}',name=f'Fictional Pupil {i:05}',father='Fictional Guardian',class_name=f'Class {i%5}',phone='00000000000',status='Active')
            db.session.add(pupil);pupils.append(pupil)
        db.session.flush()
        for i,pupil in enumerate(pupils):
            db.session.add(rm['student'](student_id=pupil.id,family_id=family[i//2].id,data=dict(campus='Demo Campus',academic_session='2026-27',section='A',gender='Female',roll_no=str(i))))
            if i%2==0:db.session.add(Plan(student_id=pupil.id,effective='2026-01',data={'schedule':'Fictional Schedule','lines':[]}))
        for i in range(50):
            employee=Employee(employee_no=f'BENCH-E-{i}',name=f'Fictional Staff {i}',status='Active',role='Teacher');db.session.add(employee);db.session.flush()
            db.session.add(rm['employee'](employee_id=employee.id,data={'campus':'Demo Campus'}))
        db.session.add(rm['settings'](category='campus',value='Demo Campus',class_name=''))
        award=ops['workflow'](kind='awards',status='Active',data={'papers':[{'total':20},{'total':50}]});db.session.add(award);db.session.flush()
        for pupil in pupils:
            for index,marks in [(0,16),(1,45)]:db.session.add(ops['score'](award_id=award.id,student_id=pupil.id,paper=index,obtained=marks))
        db.session.commit();db.session.remove()
        client=app.test_client();counter=[0]
        def count(*args):counter[0]+=1
        event.listen(db.engine,'before_cursor_execute',count)
        results=[]
        try:
            for path in ['/workspace/dashboard','/records/student','/records/employee','/workspace/student-fee-plans?mode=update','/workspace/certificates?campus=Demo+Campus']:
                durations=[];queries=[];length=0
                for attempt in range(4):
                    db.session.remove();counter[0]=0;start=time.perf_counter()
                    response=client.get(path);elapsed=(time.perf_counter()-start)*1000
                    if response.status_code!=200:raise RuntimeError(f'Benchmark page failed: {path} ({response.status_code})')
                    if attempt:durations.append(elapsed);queries.append(counter[0])
                    length=len(response.data)
                results.append(dict(path=path,median_ms=round(statistics.median(durations),2),sql_statements=max(queries),response_bytes=length))
        finally:event.remove(db.engine,'before_cursor_execute',count)
        print(json.dumps(dict(fictional_students=args.students,numeric_scores=args.students*2,measurements=results),indent=2))

if __name__=='__main__':main()
