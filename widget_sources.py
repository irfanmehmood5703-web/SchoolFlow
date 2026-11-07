"""Read-only widget summaries with explicit dates, provenance and missing data."""
from collections import Counter,defaultdict
from datetime import date,timedelta
from decimal import Decimal
from widget_catalog import WIDGETS


def build_widgets(app,db,Student,Employee,keys,start,end,today,releases,tuition_head=''):
    out={}
    def add(key,value,unit,headers,rows,note,chart=None):
        if key in keys:out[key]=dict(value=value,unit=unit,headers=headers,rows=rows,note=note,chart=chart or [],chart_max=max([abs(float(v)) for _,v in (chart or [])]+[1]))
    def money(n):return f'{n/100:,.2f}'
    def parsed(raw):
        try:return date.fromisoformat(str(raw)[:10])
        except (ValueError,TypeError):return None
    def month_range(day,count):
        index=day.year*12+day.month-1
        return [f'{(index-i)//12:04d}-{(index-i)%12+1:02d}' for i in reversed(range(count))]
    month_keys=month_range(today,12)
    rm=app.extensions['record_models'];ops=app.extensions['ops_models'];D=rm['student']
    needed={group for key,group,_,_ in WIDGETS if key in keys}
    # Student JSON is projected to only the fields needed for these summaries.
    people=[]
    if needed & {'Admissions','Finance','Exam & Attendance','General'}:
        cols=[D.data[k].as_string() for k in ('campus','section','admission_date','leaving_date','birth_date')]
        for row in db.session.query(Student.id,Student.name,Student.class_name,Student.status,*cols).outerjoin(D,D.student_id==Student.id).all():
            people.append(dict(id=row[0],name=row[1],class_name=row[2] or 'Unassigned',status=row[3],campus=row[4] or '',section=row[5] or '',joined=parsed(row[6]),left=parsed(row[7]),born=parsed(row[8])))
    by_id={s['id']:s for s in people};active=[s for s in people if s['status']=='Active'];active_ids={s['id'] for s in active}
    work=[]
    if needed & {'Admissions','Exam & Attendance','HRM','General'}:
        kinds=set()
        if 'Admissions' in needed:kinds.add('queries')
        if 'Exam & Attendance' in needed:kinds.update(('awards','date-sheets'))
        if 'HRM' in needed:kinds.update(('salary-plans','increments','advances','leave-approvals'))
        if 'General' in needed:kinds.update(('complaints','suggestions','complaints-suggestions'))
        work=ops['workflow'].query.filter(ops['workflow'].kind.in_(kinds)).all()
    if 'Admissions' in needed:
        queries=[w for w in work if w.kind=='queries']
        add('admission-queries',len(queries),'records',['ID','Student','Class','Status','Follow-up'],[[w.id,w.data.get('name',''),w.data.get('class_name',''),w.status,w.data.get('follow_up','')] for w in queries],'All saved admission enquiries, not invented conversion counts.')
        rows=[[s['id'],s['name'],s['campus'],s['class_name'],s['section']] for s in active]
        classes=Counter(s['class_name'] for s in active)
        for k in ('active-students','student-strength','strength-chart'):
            add(k,len(active),'students',['SID','Student','Campus','Class','Section'],rows,'Currently Active student records in your permitted campus scope.',list(sorted(classes.items())))
        capacity=app.extensions['admission_capacity']['rows']() if 'admission-capacity' in keys else []
        add('admission-capacity',sum(r['occupied'] for r in capacity),'occupied seats',['Campus','Class','Session','Enrolled','Seats','Available'],[[r['campus'],r['class_name'],r['academic_session'],r['occupied'],r['seats'] if r['seats'] is not None else 'Unlimited',r['available'] if r['available'] is not None else 'Unlimited'] for r in capacity],'Only configured capacity rows are included; no capacity is invented.')
        for key,field in [('new-admissions','joined'),('inactive-students','left')]:
            filtered=[s for s in people if s[field] and s[field].strftime('%Y-%m') in month_keys and s[field]<=today and (key!='inactive-students' or s['status']!='Active')]
            counts=Counter(s[field].strftime('%Y-%m') for s in filtered)
            add(key,len(filtered),'in 12 months',['SID','Student','Date','Campus','Class'],[[s['id'],s['name'],str(s[field]),s['campus'],s['class_name']] for s in filtered],'Last 12 calendar months through today, using actual admission/leaving dates. Missing dates are excluded.',[(m,counts[m]) for m in month_keys])
    if 'Finance' in needed:
        bills=ops['bill'].query.all()
        selected=[b for b in bills if start.strftime('%Y-%m')<=b.month<=end.strftime('%Y-%m')]
        receipts=ops['receipt'].query.filter(ops['receipt'].voided==False,ops['receipt'].day>=start,ops['receipt'].day<=end).all()
        month_receipts=ops['receipt'].query.filter(ops['receipt'].voided==False,ops['receipt'].day>=today.replace(day=1),ops['receipt'].day<=today).all()
        receipt_total=sum(r.amount for r in month_receipts)
        def bill_rows(rows):
            return [[b.id,by_id.get(b.student_id,{}).get('name',''),b.month,str(b.due),money(b.total),money(b.paid),money(b.discount),money(b.remaining)] for b in rows]
        bh=['Challan','Student','Month','Due date','Payable','Paid','Discount','Remaining']
        add('paid-amount',receipt_total,'money',['Payment ID','Student','Date','Paid','Discount','Account'],[[r.id,by_id.get(r.student_id,{}).get('name',''),str(r.day),money(r.amount),money(r.discount),r.account] for r in month_receipts],'Non-voided cash receipts dated in the current month through today; includes earlier bill months. This card always uses this month.')
        paid=sum(b.paid for b in selected);payable=sum(b.total-b.discount for b in selected)
        add('fee-collection',paid,'money',bh,bill_rows(selected),f'Current paid balances on challans in the selected bill months; net payable Rs {money(payable)}. This is not a historical as-of balance.')
        unpaid=[b for b in selected if b.remaining>0]
        add('unpaid-challans',len(unpaid),'challans',bh,bill_rows(unpaid),'Current outstanding challans in the selected bill months; paid discounts reduce remaining.')
        add('unpaid-amount',sum(b.remaining for b in unpaid),'money',bh,bill_rows(unpaid),'Current outstanding amounts on selected bill months; not a reconstructed historical balance.')
        overdue=[b for b in bills if b.remaining>0 and b.due<today]
        ids={b.student_id for b in overdue}
        add('fee-defaulters',len(ids),'students',bh,bill_rows(overdue),'Distinct students with a positive balance past the actual due date today; excludes future-due bills.')
        annual=[b for b in bills if b.month.startswith(str(today.year)+'-') and b.month<=today.strftime('%Y-%m')]
        class_totals=defaultdict(lambda:[0,0,0,0]);month_totals=defaultdict(lambda:[0,0,0,0])
        for b in selected:
            key=by_id.get(b.student_id,{}).get('class_name','Unassigned')
            for i,v in enumerate((b.total,b.paid,b.discount,b.remaining)):class_totals[key][i]+=v
        for b in annual:
            for i,v in enumerate((b.total,b.paid,b.discount,b.remaining)):month_totals[b.month][i]+=v
        heads=['Payable','Paid','Discount','Remaining']
        add('class-fees',paid,'money',['Class',*heads],[[k,*map(money,v)] for k,v in sorted(class_totals.items())],'Current totals by the student’s current class for selected bill months.',[(k,v[1]) for k,v in sorted(class_totals.items())])
        for key in ('month-chart','month-report'):
            add(key,sum(b.paid for b in annual),'money',['Month',*heads],[[k,*map(money,v)] for k,v in sorted(month_totals.items())],'Calendar year-to-date current bill/paid/discount/remaining totals grouped by bill month; this card always uses the current calendar year.',[(k+' due',v[0]-v[2]) for k,v in sorted(month_totals.items())]+[(k+' paid',v[1]) for k,v in sorted(month_totals.items())]+[(k+' outstanding',v[3]) for k,v in sorted(month_totals.items())])
        P=app.extensions['student_fee_plan_model'];latest={}
        for p in P.query.filter(P.effective<=end.strftime('%Y-%m')).order_by(P.effective,P.id).all():
            if p.student_id in active_ids:latest[p.student_id]=p
        head_model=app.extensions['fee_setup_models']['head']
        if not tuition_head:
            candidates=[h.key for h in head_model.query.all() if ''.join(c for c in h.label.casefold() if c.isalnum()) in ('tuition','tuitionfee')]
            tuition_head=candidates[0] if len(candidates)==1 else ''
        tuition_rows=[]
        for sid,p in latest.items():
            lines=[l for l in p.data.get('lines',[]) if l.get('particular')==tuition_head]
            if lines:tuition_rows.append([sid,by_id.get(sid,{}).get('name',''),sum(int(l.get('actual',0))-int(l.get('discount',0)) for l in lines)])
        add('average-tuition',round(sum(r[2] for r in tuition_rows)/len(tuition_rows)) if tuition_rows else None,'money',['SID','Student','Net tuition'],[[sid,name,money(value)] for sid,name,value in tuition_rows],'Average discounted tuition from latest effective active-student fee plans. Choose the tuition particular in Permissions if no unique Tuition Fee particular exists.')
        discounts=Counter(p.data.get('discount_type_name') or 'No discount type' for p in latest.values())
        add('discount-types',len(latest),'students with a fee plan',['Discount type','Students'],list(sorted(discounts.items())),'Latest effective fee plan per currently Active student; no plan means no inferred discount category.',list(sorted(discounts.items())))
        particular=defaultdict(lambda:[0,0,0]);monthly=defaultdict(lambda:[0,0,0]);unknown=False
        for b in selected:
            for line in b.lines:
                label=app.extensions['fee_setup_helpers']['label'](line['particular'])
                for target,key in ((particular,label),(monthly,b.month+' · '+label)):
                    target[key][0]+=line['amount']
                    if len(b.lines)==1:target[key][1]+=b.paid;target[key][2]+=b.discount
                if len(b.lines)>1 and (b.paid or b.discount):unknown=True
        for key,groups in (('particular-fees',particular),('monthly-particular',monthly)):
            add(key,None if unknown else paid,'money',['Particular / Month','Payable','Allocated paid','Allocated discount'],[[k,money(v[0]),'Unavailable for mixed-head bills' if unknown else money(v[1]),'Unavailable for mixed-head bills' if unknown else money(v[2])] for k,v in sorted(groups.items())],'Bill line amounts are known. Payments on challans with multiple fee particulars do not record how the payment was split; allocated amounts are unavailable.')
        if set(keys)&{'income-expenses','daily-profit'}:
            J=app.extensions['ledger_models']['journal'];L=app.extensions['ledger_models']['line']
            grouped=defaultdict(lambda:[0,0])
            for day,snapshot,debit,credit in db.session.query(J.day,L.snapshot,L.debit,L.credit).join(L,L.journal_id==J.id).filter(J.day>=start,J.day<=end).all():
                typ=snapshot.get('account_class')
                if typ=='Income':grouped[str(day)][0]+=credit-debit
                elif typ=='Expense':grouped[str(day)][1]+=debit-credit
            income=sum(v[0] for v in grouped.values());expense=sum(v[1] for v in grouped.values())
            for key in ('income-expenses','daily-profit'):
                add(key,income-expense,'money',['Date','Income','Expense','Net'],[[d,money(v[0]),money(v[1]),money(v[0]-v[1])] for d,v in sorted(grouped.items())],f'Posted ledger lines use the Income/Expense category recorded at posting. Later account edits do not rewrite these totals. Income Rs {money(income)}, expense Rs {money(expense)}; unposted receipts are not silently counted.',[(d+' income',v[0]) for d,v in sorted(grouped.items())]+[(d+' expense',v[1]) for d,v in sorted(grouped.items())])
    if 'Exam & Attendance' in needed:
        daily=ops['daily'].query.filter_by(kind='student',day=today).all()
        active_marks=[r for r in daily if r.person_id in active_ids];absent=[r for r in active_marks if r.status=='Absent']
        counts=Counter(by_id[r.person_id]['class_name'] for r in absent)
        add('absent-class',len(absent),'absent today',['SID','Student','Class','Date','Status'],[[r.person_id,by_id[r.person_id]['name'],by_id[r.person_id]['class_name'],str(r.day),r.status] for r in absent],'Today’s saved Absent marks for currently Active students, by current class.',list(sorted(counts.items())))
        attendance=Counter(r.status for r in active_marks);attendance['Unmarked']=len(active_ids-{r.person_id for r in active_marks})
        add('attendance-donut',len(active_marks),'marked today',['Status','Students'],list(attendance.items()),'Today’s saved attendance plus actual Active students with no mark. Unmarked is never treated as absent.',list(attendance.items()))
        awards={w.id:w for w in work if w.kind=='awards'};per_student=defaultdict(lambda:[0,0]);upcoming=[]
        for w in work:
            if w.kind=='date-sheets':
                for paper in w.data.get('papers',[]):
                    day=parsed(paper.get('date'))
                    if day and day>=today:upcoming.append([w.data.get('name',''),w.data.get('class_name',''),paper.get('subject',''),str(day),paper.get('time','')])
        add('upcoming-exams',len(upcoming),'scheduled papers',['Date sheet','Class','Subject','Date','Time'],sorted(upcoming,key=lambda r:r[3]),'Future dated papers from saved date sheets; no dates are inferred.')
        for score in ops['score'].query.filter(ops['score'].obtained!=None).all():
            w=awards.get(score.award_id)
            if not w or score.student_id not in by_id or score.state in ('A','L','Absent','Leave'):continue
            papers=w.data.get('papers',[])
            if not 0<=score.paper<len(papers):continue
            paper=papers[score.paper];total=paper.get('total',0)
            day=parsed(paper.get('date')) or (w.created.date() if w.created else None)
            if paper.get('grading','Marks')!='Marks' or not total or not day or not start<=day<=end:continue
            key=(score.award_id,score.student_id,day.strftime('%Y-%m'));per_student[key][0]+=score.obtained;per_student[key][1]+=total
        result_rows=[[aid,sid,by_id[sid]['name'],by_id[sid]['class_name'],month,round(v[0]/v[1]*100,2)] for (aid,sid,month),v in per_student.items() if v[1]>0]
        average=round(sum(r[-1] for r in result_rows)/len(result_rows),2) if result_rows else None
        for key,pos in (('class-results',3),('month-results',4)):
            buckets=defaultdict(list)
            for row in result_rows:buckets[row[pos]].append(row[-1])
            add(key,average,'percent',['Award','SID','Student','Class','Month','Percentage'],result_rows,'Numeric marked papers in the selected period; absent/leave/direct grades are excluded. Paper dates are used, with award creation date only when absent.',[(k,round(sum(v)/len(v),2)) for k,v in sorted(buckets.items())])
        bands=Counter('80%+' if r[-1]>=80 else '60–79.99%' if r[-1]>=60 else '40–59.99%' if r[-1]>=40 else 'Below 40%' for r in result_rows)
        add('performance-bands',bands['80%+'],'results at 80%+',['Award','SID','Student','Class','Month','Percentage'],result_rows,'Bands count saved student/award/month numeric result groups, not missing or qualitative marks.',list(bands.items()))
    if 'HRM' in needed:
        employees=Employee.query.order_by(Employee.name).all();names={e.id:e.name for e in employees}
        statuses=Counter(e.status for e in employees)
        add('employee-status',sum(e.status=='Active' for e in employees),'active employees',['Employee ID','Name','Role','Status'],[[e.id,e.name,e.role,e.status] for e in employees],'Saved employee statuses; inactive records remain in the report.',list(statuses.items()))
        daily=ops['daily'].query.filter_by(kind='staff').filter(ops['daily'].day>=start,ops['daily'].day<=end).all();counts=Counter(r.status for r in daily);marked=[r for r in daily if r.status!='Off Day']
        value=round(sum(r.status in ('Present','Late') for r in marked)/len(marked)*100,2) if marked else None
        add('staff-attendance',value,'percent',['Employee','Date','Status'],[[names.get(r.person_id,'Unavailable'),str(r.day),r.status] for r in daily],'Present + Late as a percentage of saved non-Off-Day entries in the selected period; no unmarked staff are invented.',list(counts.items()))
        approvals=[w for w in work if w.kind in ('salary-plans','increments','advances')]
        pending=[w for w in approvals if w.status=='Pending'];counts=Counter(w.kind for w in pending)
        add('employee-approvals',len(pending),'pending requests',['ID','Kind','Employee ID','Status','Created'],[[w.id,w.kind,w.data.get('employee_id',''),w.status,str(w.created or '')] for w in approvals],'Pending salary-plan, increment and advance workflows. Creation dates are shown; missing decision dates are not guessed.',list(counts.items()))
        leaves=[w for w in work if w.kind=='leave-approvals' and w.status=='Approved' and parsed(w.data.get('from_date')) and parsed(w.data.get('to_date')) and parsed(w.data['from_date'])<=today<=parsed(w.data['to_date'])]
        add('staff-leave',len({w.data.get('employee_id') for w in leaves}),'staff on leave today',['Request','Employee ID','From','To','Type'],[[w.id,w.data.get('employee_id',''),w.data.get('from_date',''),w.data.get('to_date',''),w.data.get('type','')] for w in leaves],'Approved leave requests whose actual From/To dates cover today.')
    if 'General' in needed:
        birthday=[s for s in active if s['born'] and (s['born'].month,s['born'].day)==(today.month,today.day)]
        add('birthdays',len(birthday),'birthdays today',['SID','Student','Class'],[[s['id'],s['name'],s['class_name']] for s in birthday],'Today’s birthdays from actual saved dates of birth for Active students.')
        published=[r for r in releases if r['url']]
        add('mobile-apps',len(published),'published release links',['App','Version','Public link'],[[r['label'],r['version'],r['url']] for r in published],'SchoolFlow’s configured public release links; this does not infer device installs or native app usage.')
        complaints=[w for w in work if w.kind in ('complaints','suggestions','complaints-suggestions')]
        open_rows=[w for w in complaints if w.status not in ('Closed','Resolved','Solved')]
        add('complaints',len(open_rows),'open local records',['ID','Type','Status','Description'],[[w.id,w.kind,w.status,w.data.get('description',w.data.get('message',''))] for w in complaints],'Local saved complaint/suggestion workflows; disconnected parent submissions are not inferred.')
        six=month_range(today,6);complaint_months=Counter(w.created.strftime('%Y-%m') for w in complaints if w.created and w.created.date()<=today)
        add('complaints-chart',sum(complaint_months[m] for m in six),'records in 6 months',['Month','Records'],[[m,complaint_months[m]] for m in six],'Actual creation months of locally saved complaint/suggestion records.',[(m,complaint_months[m]) for m in six])
        add('updates',len(published),'published releases',['App','Version','Release notes'],[[r['label'],r['version'],r['notes']] for r in published],'Your configured SchoolFlow release versions and notes; no vendor announcements are copied.')
        requests=rm['communication'].query.filter(rm['communication'].created_at>=start,rm['communication'].created_at<end+timedelta(days=1)).all()
        add('sms',None,'SMS credit / sent telemetry unavailable',['Request','Student ID','Status','Created'],[[r.id,r.student_id,r.status,str(r.created_at)] for r in requests],f'{len(requests)} local communication requests in the selected period. No SIM/provider balance or delivery telemetry is connected; saved requests are not sent messages.')
    if 'attendance-donut' in out:
        summary=out['attendance-donut'];total=sum(value for _,value in summary['chart']);offset=0;segments=[]
        colors=['#177653','#bd4545','#bf861b','#2d6db1','#8974b6','#8a9690']
        for index,(label,value) in enumerate(summary['chart']):
            portion=value/total*251.327 if total else 0
            segments.append(dict(label=label,value=value,length=portion,offset=-offset,color=colors[index%len(colors)]));offset+=portion
        summary.update(segments=segments,chart_total=total)
    return out
