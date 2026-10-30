"""Read-only Student 360 workspace over the existing operational records."""
import math
from collections import Counter, defaultdict
from datetime import date
from flask import Blueprint, abort, render_template, request
from sqlalchemy import or_


from student_performance_schema import PERFORMANCE_CATEGORIES


def performance_totals(papers):
    numeric=[p for p in papers if p['percentage'] is not None]
    maximum=sum(p['total'] for p in numeric)
    obtained=sum(p['obtained'] for p in numeric)
    return dict(recorded=len(papers),numeric=len(numeric),absent=sum(p['state']=='A' for p in papers),leave=sum(p['state']=='L' for p in papers),unmarked=sum(p['obtained'] is None and not p['state'] for p in papers),maximum=maximum,obtained=obtained,percentage=round(obtained/maximum*100,2) if maximum else None)


def configure_student_overview(app, db, Student):
    bp = Blueprint('student_overview', __name__, url_prefix='/workspace/student-360')
    models = app.extensions['ops_models']
    rm = app.extensions['record_models']
    Bill, Receipt, Daily, Score, Workflow = (models[k] for k in ('bill','receipt','daily','score','workflow'))
    Plan = app.extensions['student_fee_plan_model']
    details = app.extensions['operation_helpers']['details']

    def period():
        try:
            start = date.fromisoformat(request.args.get('from',date.today().replace(month=1,day=1).isoformat()))
            end = date.fromisoformat(request.args.get('to',date.today().isoformat()))
        except (TypeError,ValueError):
            abort(422,description='Choose valid From and To dates.')
        if start > end or (end-start).days > 3660:
            abort(422,description='Choose an ordered date range of at most ten years.')
        return start,end

    @bp.get('')
    def index():
        query = Student.query
        term = request.args.get('q','').strip()[:200]
        status = request.args.get('status','')
        if term:
            # contains(autoescape=True) treats user % and _ as literal characters.
            query = query.filter(or_(Student.name.contains(term,autoescape=True),Student.admission_no.contains(term,autoescape=True),Student.father.contains(term,autoescape=True)))
        if status: query = query.filter(Student.status==status)
        try: page = int(request.args.get('page','1'))
        except ValueError: abort(422,description='Choose a valid page.')
        if page < 1: abort(422,description='Choose a valid page.')
        total = query.count()
        rows = query.order_by(Student.name,Student.id).offset((page-1)*25).limit(25).all()
        return render_template('student_360_list.html',title='Student 360°',rows=rows,total=total,page=page,pages=max(1,math.ceil(total/25)),details=details)

    @bp.get('/<int:sid>')
    def overview(sid):
        student = db.get_or_404(Student,sid)
        start,end = period()
        data = details(student)
        all_bills = Bill.query.filter_by(student_id=sid).order_by(Bill.month.desc(),Bill.id.desc()).all()
        bills = [b for b in all_bills if start.strftime('%Y-%m')<=b.month<=end.strftime('%Y-%m')]
        receipts = Receipt.query.filter(Receipt.student_id==sid,Receipt.voided==False,Receipt.day>=start,Receipt.day<=end).order_by(Receipt.day.desc(),Receipt.id.desc()).all()
        attendance = Daily.query.filter(Daily.kind=='student',Daily.person_id==sid,Daily.day>=start,Daily.day<=end).order_by(Daily.day.desc()).all()
        counts = Counter(row.status for row in attendance)
        # Expose counts of recorded days only; no assumed working-day or holiday calendar.
        attendance_months = defaultdict(Counter)
        for row in attendance: attendance_months[row.day.strftime('%Y-%m')][row.status]+=1
        attendance_statuses = sorted(counts)
        papers=[]
        scores = Score.query.filter_by(student_id=sid).order_by(Score.award_id.desc(),Score.paper).all()
        awards = {w.id:w for w in Workflow.query.filter(Workflow.id.in_({score.award_id for score in scores}),Workflow.kind=='awards').all()}
        for score in scores:
            award=awards.get(score.award_id)
            if not award or not 0<=score.paper<len(award.data.get('papers',[])): continue
            paper=award.data['papers'][score.paper]
            try: exam_day=date.fromisoformat(paper.get('date',''))
            except (ValueError,TypeError): continue
            if not start<=exam_day<=end: continue
            maximum=float(paper['total'])
            numeric=score.obtained is not None and not score.state
            papers.append(dict(category=award.data.get('assessment_category','') if award.data.get('assessment_category','') in PERFORMANCE_CATEGORIES else '',academic_session=award.data.get('academic_session',''),award_id=award.id,award=award.data.get('name','Exam'),subject=paper.get('subject','—'),day=exam_day,total=maximum,obtained=score.obtained if numeric else None,state=score.state,percentage=round(score.obtained/maximum*100,2) if numeric and maximum>0 else None))
        papers.sort(key=lambda x:(x['day'],x['award_id'],x['subject']),reverse=True)
        result = performance_totals(papers)
        performance=[]
        for category in PERFORMANCE_CATEGORIES:
            items=[p for p in papers if p['category']==category]
            groups=defaultdict(list)
            for p in items:
                if category=='Weekly':
                    iso=p['day'].isocalendar(); key=f'{iso.year} · Week {iso.week:02d}'
                elif category=='Monthly': key=p['day'].strftime('%Y-%m')
                else: key=p['academic_session'] or str(p['day'].year)
                groups[key].append(p)
            periods=[dict(label=key,**performance_totals(group)) for key,group in sorted(groups.items())]
            subjects=defaultdict(list)
            for p in items: subjects[p['subject']].append(p)
            performance.append(dict(category=category,totals=performance_totals(items),periods=periods,subjects=[dict(label=key,**performance_totals(group)) for key,group in sorted(subjects.items())]))
        unclassified=sum(not p['category'] for p in papers)
        plans = Plan.query.filter_by(student_id=sid).order_by(Plan.effective.desc()).all()
        current_plan = next((p for p in plans if p.effective<=date.today().strftime('%Y-%m')),None)
        own_detail=rm['student'].query.filter_by(student_id=sid).first()
        siblings=[]
        if own_detail and own_detail.family_id:
            related=rm['student'].query.filter_by(family_id=own_detail.family_id).all()
            siblings=Student.query.filter(Student.id.in_([r.student_id for r in related]),Student.id!=sid).order_by(Student.name).all()
        files=rm['file'].query.filter_by(owner_kind='student',owner_id=sid).all()
        photo=next((f for f in files if f.photo),None)
        events=rm['event'].query.filter_by(owner_kind='student',owner_id=sid).order_by(rm['event'].id.desc()).limit(20).all()
        return render_template('student_360.html',title=student.name+' · Student 360°',today_month=date.today().strftime('%Y-%m'),s=student,d=data,start=start,end=end,bills=bills,receipts=receipts,balance=sum(b.remaining for b in all_bills),billed=sum(b.total for b in bills),bill_paid=sum(b.paid for b in bills),bill_discount=sum(b.discount for b in bills),bill_remaining=sum(b.remaining for b in bills),received=sum(r.amount for r in receipts),receipt_discount=sum(r.discount for r in receipts),attendance=attendance,counts=counts,attendance_months=sorted(attendance_months.items(),reverse=True),attendance_statuses=attendance_statuses,papers=papers,result=result,performance=performance,unclassified=unclassified,plans=plans,current_plan=current_plan,siblings=siblings,files=[f for f in files if not f.photo],photo=photo,events=events)
    app.register_blueprint(bp)
