"""Database-backed pre-test reports. Unknown allocations are never fabricated."""
import calendar,csv,io
from collections import Counter,defaultdict
from datetime import date,timedelta
from decimal import Decimal,InvalidOperation
from flask import Blueprint,abort,redirect,render_template,request,url_for
from module_catalog import TITLES

FEE_REPORTS={'fee-report','daily-fees','class-fees','student-fees','defaulters','family-defaulters','monthly-defaulters','fee-reminder'}
ATTENDANCE_REPORTS={'combined-attendance','daily-attendance','individual-attendance','attendance-summary','absentees','attendance-sheet','staff-attendance-report'}

def configure_reports(app,db,Student,Employee):
    bp=Blueprint('reports',__name__,url_prefix='/workspace/reports')
    models=app.extensions['ops_models'];rm=app.extensions['record_models'];Bill=models['bill'];Receipt=models['receipt'];Daily=models['daily'];Workflow=models['workflow'];Score=models['score']
    details=app.extensions['operation_helpers']['details']
    def fail(message):abort(422,description=message)
    def parsedate(value):
        try:return date.fromisoformat(value)
        except (ValueError,TypeError):fail('Enter a valid date.')
    def bounds():
        start=request.args.get('from',date.today().replace(day=1).isoformat());end=request.args.get('to',date.today().isoformat())
        if len(start)==7:start+='-01'
        if len(end)==7:
            try:end+='-'+str(calendar.monthrange(int(end[:4]),int(end[5:7]))[1])
            except (ValueError,calendar.IllegalMonthError):fail('Enter a valid month.')
        a,b=parsedate(start),parsedate(end)
        if a>b:fail('From must precede To.')
        if (b-a).days>3660:fail('Choose a range of at most ten years.')
        return a,b
    def options(category):return [r.value for r in rm['settings'].query.filter_by(category=category).order_by(rm['settings'].value).all()]
    def match(person,kind='student'):
        d=details(person,kind)
        for key in ('campus','class_name','section','academic_session','gender','group_name'):
            value=request.args.get(key,'')
            actual=person.class_name if key=='class_name' and kind=='student' else d.get(key,'')
            if value and actual!=value:return False
        if request.args.get('enrolled')=='1' and person.status!='Active':return False
        if request.args.get('status') and person.status!=request.args['status']:return False
        if request.args.get('person_id') and str(person.id)!=request.args['person_id']:return False
        return True
    def export(headers,rows,name):
        stream=io.StringIO();writer=csv.writer(stream);writer.writerow(headers)
        for row in rows:writer.writerow(["'"+str(x) if str(x).lstrip().startswith(('=','+','-','@')) else str(x) for x in row])
        response=app.response_class('\ufeff'+stream.getvalue(),mimetype='text/csv');response.headers['Content-Disposition']=f'attachment; filename="schoolflow-{name}.csv"';return response
    def response(view,headers,rows,totals=None,**kw):
        if request.args.get('export')=='csv':return export(headers,rows,view)
        return render_template('reports.html',title=TITLES.get(view,view),view=view,headers=headers,rows=rows,totals=totals or {},options=options,today=date.today().isoformat(),period_type='month' if view in FEE_REPORTS and view!='daily-fees' else 'date',**kw)
    def cash(value):return f'{value/100:,.2f}'

    @bp.route('/fees/<view>')
    def fees(view):
        if view not in FEE_REPORTS:abort(404)
        start,end=bounds();students={s.id:s for s in Student.query.all() if match(s)};all_bills=Bill.query.filter(Bill.student_id.in_(students)).order_by(Bill.month,Bill.id).all()
        billing=[b for b in all_bills if start.strftime('%Y-%m')<=b.month<=end.strftime('%Y-%m')]
        receipts=Receipt.query.filter(Receipt.student_id.in_(students),Receipt.voided==False).all()
        if view=='daily-fees':
            rows=[];group=defaultdict(lambda:[0,0,0]);account=request.args.get('account','')
            for r in receipts:
                if start<=r.day<=end and (not account or r.account==account):
                    group[(str(r.day),r.account)][0]+=r.amount;group[(str(r.day),r.account)][1]+=r.discount;group[(str(r.day),r.account)][2]+=1
            for (day,account),values in sorted(group.items()):rows.append([day,account,values[2],cash(values[0]),cash(values[1])])
            return response(view,['Payment Date','Receiving Account','Receipts','Collected','Discount'],rows,dict(Collected=cash(sum(v[0] for v in group.values())),Discount=cash(sum(v[1] for v in group.values()))))
        if view=='class-fees':
            particular=app.extensions['fee_setup_helpers']['resolve'](request.args.get('particular',''));groups=defaultdict(lambda:[0,0,0,0,False])
            for b in billing:
                for line in b.lines:
                    if particular and line['particular']!=particular:continue
                    if request.args.get('defaulters') and b.remaining<=0:continue
                    key=(students[b.student_id].class_name or 'Unassigned',line['particular']);g=groups[key];g[0]+=line['amount'];g[3]+=1
                    if len(b.lines)==1:g[1]+=b.paid;g[2]+=b.discount
                    else:g[4]=True
            rows=[[cls,app.extensions['fee_setup_helpers']['label'](part),count,cash(billed),cash(paid) if not unknown else 'Allocation unavailable',cash(discount) if not unknown else 'Allocation unavailable',cash(billed-paid-discount) if not unknown else 'Allocation unavailable'] for (cls,part),(billed,paid,discount,count,unknown) in sorted(groups.items())]
            return response(view,['Class','Particular','Challans','Payable','Paid','Discount','Remaining'],rows,note='Payments on older multi-particular challans have no line allocation. Such values are explicitly unavailable, rather than estimated.')
        if view=='monthly-defaulters':
            groups=defaultdict(lambda:[0,0,0,0])
            for b in billing:
                if b.remaining<=0:continue
                key=(b.month,b.student_id);g=groups[key]
                for i,value in enumerate([b.total,b.discount,b.paid,b.remaining]):g[i]+=value
            rows=[[m,sid,students[sid].name,students[sid].class_name,*map(cash,values)] for (m,sid),values in sorted(groups.items())]
            return response(view,['Month','SID','Student','Class','Payable','Discount','Paid','Remaining'],rows)
        summary={sid:dict(payable=0,discount=0,paid=0,remaining=0,months=set(),bills=0,states=Counter()) for sid in students}
        for b in billing:
            g=summary[b.student_id];g['bills']+=1;g['payable']+=b.total;g['paid']+=b.paid;g['discount']+=b.discount;g['remaining']+=b.remaining;g['states'][b.state]+=1
            if b.remaining>0:g['months'].add(b.month)
        if view in ('defaulters','family-defaulters','fee-reminder') or request.args.get('defaulters'):summary={sid:g for sid,g in summary.items() if g['remaining']>0}
        minmonths=request.args.get('pending_months','0')
        if not minmonths.isdigit():fail('Pending-month count must be a non-negative integer.')
        summary={sid:g for sid,g in summary.items() if len(g['months'])>=int(minmonths)}
        totals={key.title():cash(sum(g[key] for g in summary.values())) for key in ('payable','discount','paid','remaining')}
        if view=='family-defaulters':
            families={}
            for sid,g in summary.items():
                d=details(students[sid]);number=d.get('family_no') or 'Individual '+str(sid);f=families.setdefault(number,dict(father=students[sid].father or '',students=[],payable=0,discount=0,paid=0,remaining=0))
                f['students'].append(students[sid].name)
                for key in ('payable','discount','paid','remaining'):f[key]+=g[key]
            rows=[[number,f['father'],', '.join(f['students']),*[cash(f[k]) for k in ('payable','discount','paid','remaining')]] for number,f in sorted(families.items())]
            return response(view,['Family No','Father','Students','Payable','Discount','Paid','Remaining'],rows,totals)
        if view=='fee-reminder':
            return render_template('fee_reminders.html',title='Fee Reminder',students=students,summary=summary,start=start,end=end,details=details)
        headers=['SID','Roll No','Student','Father','Campus','Class','Section','Session','Status','Challans','Payable','Discount','Paid','Remaining','Pending Months']
        if view=='student-fees':headers+=['Fully Paid','Partially Paid','Unpaid','No Challan']
        rows=[]
        for sid,g in summary.items():
            s=students[sid];d=details(s);row=[sid,d.get('roll_no',''),s.name,s.father or '',d.get('campus',''),s.class_name or '',d.get('section',''),d.get('academic_session',''),s.status,g['bills'],*[cash(g[k]) for k in ('payable','discount','paid','remaining')],len(g['months'])]
            if view=='student-fees':row+=[g['states']['Fully Paid'],g['states']['Partially Paid'],g['states']['Unpaid'],int(not g['bills'])]
            rows.append(row)
        sort=request.args.get('sort','sid');index={'sid':0,'roll':1,'class':5}.get(sort,0);rows.sort(key=lambda row:str(row[index]).casefold() if index else row[0])
        return response(view,headers,rows,totals,note='Amounts are lifetime payments/discounts against challans in the selected bill-month range. Day Wise Paid Challans instead filters by actual receipt date.')

    @bp.route('/attendance/<view>')
    def attendance(view):
        if view not in ATTENDANCE_REPORTS:abort(404)
        start,end=bounds();kind='staff' if view=='staff-attendance-report' else 'student';cls=Employee if kind=='staff' else Student;person_kind='employee' if kind=='staff' else 'student'
        persons={p.id:p for p in cls.query.all() if match(p,person_kind)}
        records=Daily.query.filter(Daily.kind==kind,Daily.day>=start,Daily.day<=end,Daily.person_id.in_(persons)).order_by(Daily.day,Daily.person_id).all()
        statuses=['Present','Absent','Late','Leave','Short Leave','Off Day','Death Leave','Paper Leave','Sandwich Leave']
        counts={id:Counter() for id in persons};byday=defaultdict(Counter);lookup={}
        for r in records:counts[r.person_id][r.status]+=1;byday[r.day][r.status]+=1;lookup[(r.person_id,r.day)]=r.status
        if view=='daily-attendance':
            rows=[[str(d),*[c[s] for s in statuses],sum(c.values()),max(0,len(persons)-sum(c.values()))] for d,c in sorted(byday.items())]
            return response(view,['Date',*statuses,'Marked','Unmarked'],rows)
        if view=='attendance-sheet':
            if (end-start).days>92:fail('Printable attendance sheet supports up to 93 days per sheet.')
            dates=[start+timedelta(days=i) for i in range((end-start).days+1)]
            if not request.args.get('saturday','1')=='1':dates=[d for d in dates if d.weekday()!=5]
            if not request.args.get('sunday','1')=='1':dates=[d for d in dates if d.weekday()!=6]
            abbreviations=dict(zip(statuses,['P','A','L','LV','SL','OD','DL','PL','SdL']))
            rows=[[id,details(p,person_kind).get('roll_no',''),p.name,*[abbreviations.get(lookup.get((id,d)),'—') for d in dates]] for id,p in persons.items()]
            return response(view,['ID','Roll No','Name',*[d.strftime('%d-%b') for d in dates]],rows)
        if view=='absentees':
            minimum=request.args.get('absence_count','1')
            if not minimum.isdigit() or int(minimum)<1:fail('Absence count must be a positive integer.')
            rows=[]
            for id,p in persons.items():
                dates=sorted(r.day for r in records if r.person_id==id and r.status=='Absent');longest=run=0;previous=None
                for d in dates:
                    run=run+1 if previous and (d-previous).days==1 else 1;longest=max(longest,run);previous=d
                count=longest if request.args.get('consecutive')=='1' else len(dates)
                if count>=int(minimum):rows.append([id,p.name,p.class_name if kind=='student' else p.role,len(dates),longest,', '.join(map(str,dates))])
            return response(view,['ID','Name','Class / Role','Absent Days','Longest Consecutive Calendar Days','Dates'],rows,note='Consecutive days means adjacent calendar dates. Holidays are not inferred without a configured school calendar.')
        if view=='attendance-summary':
            groups=defaultdict(Counter);strength=Counter(p.class_name or 'Unassigned' for p in persons.values())
            for r in records:groups[persons[r.person_id].class_name or 'Unassigned'][r.status]+=1
            rows=[];days=(end-start).days+1
            for group,n in strength.items():
                c=groups[group];marked=sum(c.values());rows.append([group,n,*[c[s] for s in statuses],marked,max(0,n*days-marked),f'{c["Present"]/marked*100:.1f}%' if marked else '—'])
            return response(view,['Class','Students',*statuses,'Marked Person-days','Unmarked Calendar Person-days','Present / Marked %'],rows,note='Summary covers saved records. Unmarked person-days use the selected calendar range; no working-day calendar is assumed.')
        if view=='individual-attendance':
            rows=[[str(r.day),r.person_id,persons[r.person_id].name,r.status] for r in records]
            return response(view,['Date','ID','Name','Status'],rows)
        rows=[[id,p.name,p.class_name if kind=='student' else p.role,*[counts[id][s] for s in statuses],sum(counts[id].values())] for id,p in persons.items()]
        return response(view,['ID','Name','Class / Designation',*statuses,'Marked'],rows)

    @bp.route('/teacher-performance')
    def teacher_performance():
        start,end=bounds()
        try:passmark=Decimal(request.args.get('pass_mark','40'))
        except InvalidOperation:fail('Pass mark must be numeric.')
        if not passmark.is_finite() or not 0<=passmark<=100:fail('Pass mark must be 0 to 100.')
        teachers={e.id:e for e in Employee.query.all() if 'teacher' in (e.role or '').lower()};groups=defaultdict(lambda:dict(appeared=0,absent=0,leave=0,passed=0,percentages=[],papers=set()))
        for award in Workflow.query.filter_by(kind='awards').all():
            if request.args.get('class_name') and award.data.get('class_name')!=request.args['class_name']:continue
            if request.args.get('campus') and award.data.get('campus')!=request.args['campus']:continue
            for score in Score.query.filter_by(award_id=award.id).all():
                if score.paper>=len(award.data['papers']):continue
                paper=award.data['papers'][score.paper];teacher=paper.get('teacher','')
                if not str(teacher).isdigit() or int(teacher) not in teachers:continue
                if not start<=parsedate(paper['date'])<=end:continue
                if request.args.get('subject') and paper['subject']!=request.args['subject']:continue
                if request.args.get('test_type') and paper['type']!=request.args['test_type']:continue
                if request.args.get('person_id') and teacher!=request.args['person_id']:continue
                g=groups[int(teacher)];g['papers'].add((award.id,score.paper))
                if score.state=='A':g['absent']+=1
                elif score.state=='L':g['leave']+=1
                elif score.obtained is not None:
                    percent=score.obtained/paper['total']*100;g['percentages'].append(percent);g['appeared']+=1;g['passed']+=percent>=float(passmark)
        ordered=sorted(groups.items(),key=lambda item:-(sum(item[1]['percentages'])/len(item[1]['percentages']) if item[1]['percentages'] else 0))
        rows=[];rank=0;previous=None
        for teacher,g in ordered:
            average=round(sum(g['percentages'])/len(g['percentages']),2) if g['percentages'] else 0
            if previous!=average:rank+=1;previous=average
            rows.append([rank,teachers[teacher].name,len(g['papers']),g['appeared'],g['absent'],g['leave'],g['passed'],g['appeared']-g['passed'],f'{average:.2f}%',f'{g["passed"]/g["appeared"]*100:.2f}%' if g['appeared'] else '—'])
        return response('teacher-performance',['Rank','Teacher','Papers','Appeared','Absent','Leave','Passed','Failed','Average','Pass Rate'],rows,note='Average is the mean percentage of saved numeric student-paper marks. A/L excluded; equal rounded averages share a dense rank. Improvement comparisons require a separately selected baseline and are not included here.')

    app.register_blueprint(bp)
