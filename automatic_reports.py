"""Owner-only scheduled report notices, derived from actual tenant records.

The existing inbox refreshes these reports when accessed; this is not a background
worker, SMS or WhatsApp transport. All amounts remain integer paisa.
"""
from datetime import datetime,timedelta
from collections import Counter
import re
from flask import Blueprint,abort,flash,g,redirect,render_template,request,session,url_for
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from school_clock import SCHOOL_TIMEZONE
from workspace_actor import csrf

REPORTS=(
    ('fee-received','Fee Collection','daily','14:00'),
    ('fee-due','Monthly Billed Fee & Outstanding','monthly','08:00'),
    ('student-attendance','Student Attendance Summary','daily','14:00'),
    ('staff-attendance','Staff Attendance & Absences','daily','14:00'),
    ('salary-due','Generated Salary Payable','monthly','08:00'),
    ('income-expense','Income & Expenses','daily','14:00'),
)
KEY='automatic-owner-reports'
def money(value):return 'Rs. {:,.2f}'.format(value/100)

def period(now,frequency,clock):
    today=now.date()
    start=today if frequency=='daily' else today-timedelta(days=today.weekday()) if frequency=='weekly' else today.replace(day=1)
    # Each new period is available after the selected local clock time.
    if now.strftime('%H:%M')<clock and today==start:return None
    return start,today

def configure_automatic_reports(app,db,Student,Employee):
    bp=Blueprint('automatic_reports',__name__,url_prefix='/workspace/core/automatic-reports')
    Setting=app.extensions['school_settings_models']['setting'];ops=app.extensions['ops_models']
    def owner():
        return bool(session.get('owner_id') and not session.get('staff_id') and not session.get('demo') and not getattr(g,'staff_principal',None) and getattr(g,'school_identity',None))
    def settings():
        row=db.session.get(Setting,KEY)
        data=row.data if row else {}
        return row,{k:{'enabled':False,'frequency':f,'time':t,**data.get(k,{})} for k,_,f,t in REPORTS}
    def summary(key,start,end):
        Bill=ops['bill'];Receipt=ops['receipt'];Daily=ops['daily'];Salary=ops['salary']
        if key=='fee-received':
            rows=Receipt.query.filter(Receipt.voided==False,Receipt.day>=start,Receipt.day<=end).all()
            return 'Received '+money(sum(r.amount for r in rows))+' · Discounts '+money(sum(r.discount for r in rows))+' · '+str(len(rows))+' receipts'
        if key=='fee-due':
            month=end.strftime('%Y-%m')
            rows=Bill.query.filter(Bill.month<=month).all();current=[r for r in rows if r.month==month]
            arrears=sum(max(0,r.remaining) for r in rows if r.month<month)
            return 'Generated challans '+money(sum(r.total for r in current))+' · Discounts '+money(sum(r.discount for r in current))+' · Paid '+money(sum(r.paid for r in current))+' · Current outstanding '+money(sum(max(0,r.remaining) for r in current))+' · Prior arrears '+money(arrears)+' (excludes ungenerated fees)'
        if key in ('student-attendance','staff-attendance'):
            kind='student' if key=='student-attendance' else 'staff'
            counts=Counter(r.status for r in Daily.query.filter(Daily.kind==kind,Daily.day>=start,Daily.day<=end).all())
            return 'Recorded attendance entries: '+(' · '.join(str(k)+' '+str(v) for k,v in sorted(counts.items())) if counts else 'None saved')+' (unmarked is not absent)'
        if key=='salary-due':
            rows=Salary.query.filter_by(month=end.strftime('%Y-%m')).all()
            return 'Generated payroll '+money(sum(r.net for r in rows))+' · Paid '+money(sum(r.paid for r in rows))+' · Outstanding '+money(sum(max(0,r.net-r.paid) for r in rows))+' · '+str(len(rows))+' generated salaries'
        J=app.extensions['ledger_models']['journal'];L=app.extensions['ledger_models']['line']
        income=expense=0
        for snapshot,debit,credit in db.session.query(L.snapshot,L.debit,L.credit).join(J,J.id==L.journal_id).filter(J.day>=start,J.day<=end):
            if snapshot.get('account_class')=='Income':income+=credit-debit
            elif snapshot.get('account_class')=='Expense':expense+=debit-credit
        return 'Income '+money(income)+' · Expenses '+money(expense)+' · Net '+money(income-expense)
    def events(now=None):
        if not owner():return []
        now=now or datetime.now(SCHOOL_TIMEZONE)
        _,rules=settings();out=[]
        for key,label,_,_ in REPORTS:
            rule=rules[key]
            if not rule['enabled']:continue
            dates=period(now,rule['frequency'],rule['time'])
            if not dates:continue
            start,end=dates
            out.append(dict(key='auto-report:'+key,revision=rule['frequency']+':'+str(start),title=label,detail=str(start)+' to '+str(end)+' · '+summary(key,start,end),url=url_for('automatic_reports.index')))
        return out
    @bp.route('',methods=['GET','POST'])
    def index():
        if not owner():abort(403)
        if request.method=='POST':
            csrf()
            app.extensions['admission_capacity']['lock']()
            row,rules=settings()
            if request.form.get('version')!=str(row.version if row else 0):abort(409,'Settings changed. Reload first.')
            for key,_,_,_ in REPORTS:
                freq=request.form.get(key+'_frequency','')
                clock=request.form.get(key+'_time','')
                if freq not in ('daily','weekly','monthly') or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',clock):abort(422,'Choose a valid report frequency and time.')
                rules[key]=dict(enabled=request.form.get(key+'_enabled')=='on',frequency=freq,time=clock)
            row=row or Setting(key=KEY);row.data=rules;db.session.add(row)
            db.session.add(ops['audit'](action='Save automatic report settings',data={'enabled':[k for k,v in rules.items() if v['enabled']]}))
            try:db.session.commit()
            except (IntegrityError,StaleDataError):db.session.rollback();abort(409,'Settings changed. Reload first.')
            flash('Automatic report settings saved.','success')
            return redirect(url_for('automatic_reports.index'))
        row,rules=settings()
        return render_template('automatic_reports.html',title='Automatic Reports & Notifications',catalog=REPORTS,rules=rules,version=row.version if row else 0,events=events())
    @bp.after_request
    def private(response):
        response.headers['Cache-Control']='no-store';return response
    app.extensions['automatic_report_events']=events
    app.register_blueprint(bp)
