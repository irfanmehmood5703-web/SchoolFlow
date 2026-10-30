"""Saved salary and lecture-pay reports. Reports never recalculate posted payroll."""
import csv,io,re
from datetime import date
from flask import Blueprint,abort,render_template,request


def configure_hrm_reports(app,db,Employee):
    bp=Blueprint('hrm_reports',__name__,url_prefix='/workspace/hrm-reports')
    models=app.extensions['ops_models'];Salary=models['salary']
    details=app.extensions['operation_helpers']['details']

    def month(value):
        if not re.fullmatch(r'\d{4}-\d{2}',value or ''): abort(422,description='Enter a valid month.')
        try: date.fromisoformat(value+'-01')
        except ValueError: abort(422,description='Enter a valid month.')
        return value
    def state(row):return 'Paid' if row.paid>=row.net else ('Partially Paid' if row.paid else 'Unpaid')
    def cash(value):return f'{value/100:.2f}'
    def csv_response(headers,rows,name):
        stream=io.StringIO();writer=csv.writer(stream);writer.writerow(headers)
        for row in rows:writer.writerow(["'"+str(x) if str(x).lstrip().startswith(('=','+','-','@')) else str(x) for x in row])
        response=app.response_class('\ufeff'+stream.getvalue(),mimetype='text/csv')
        response.headers['Content-Disposition']=f'attachment; filename="schoolflow-{name}.csv"'
        return response
    @bp.get('/<view>')
    def report(view):
        if view not in ('salary-report','lecture-report'):abort(404)
        previous=date.fromordinal(date.today().replace(day=1).toordinal()-1).strftime('%Y-%m')
        start=month(request.args.get('from',previous));end=month(request.args.get('to',previous))
        if start>end or (int(end[:4])-int(start[:4]))*12+int(end[5:])-int(start[5:])>120:abort(422,description='Choose an ordered month range of at most ten years.')
        employees={e.id:e for e in Employee.query.order_by(Employee.name).all()}
        campus=request.args.get('campus','');employee_id=request.args.get('employee_id','');status=request.args.get('status','')
        if employee_id and (not employee_id.isdigit() or int(employee_id) not in employees):abort(422,description='Choose a valid employee.')
        if status not in ('','Paid','Unpaid','Partially Paid'):abort(422,description='Choose a valid payment status.')
        rows=Salary.query.filter(Salary.month>=start,Salary.month<=end).order_by(Salary.month.desc(),Salary.employee_id).all()
        rows=[r for r in rows if r.employee_id in employees and (not employee_id or str(r.employee_id)==employee_id) and (not campus or details(employees[r.employee_id],'employee').get('campus')==campus) and (not status or state(r)==status)]
        if view=='lecture-report':rows=[r for r in rows if r.detail.get('plan',{}).get('lecture_wise') or r.detail.get('lecture_pay')]
        groups={}
        for row in rows:
            g=groups.setdefault(row.employee_id,dict(employee=employees[row.employee_id],campus=details(employees[row.employee_id],'employee').get('campus',''),rows=[],net=0,paid=0,earnings=0,deductions=0))
            g['rows'].append(row)
            for key in ('net','paid','earnings','deductions'):g[key]+=getattr(row,key)
        groups=sorted(groups.values(),key=lambda g:(g['employee'].name,g['employee'].id))
        totals={key:sum(getattr(r,key) for r in rows) for key in ('net','paid','earnings','deductions')}
        def lecture_count(row):
            saved=row.detail.get('lecture_details')
            if saved is None:return None
            return sum(item['lectures'] for item in saved)
        if request.args.get('export')=='csv':
            if view=='salary-report':
                headers=['Code','Employee','Campus','Salary Months','Earnings','Deductions','Net','Paid','Remaining']
                data=[[g['employee'].employee_no,g['employee'].name,g['campus'],len(g['rows']),cash(g['earnings']),cash(g['deductions']),cash(g['net']),cash(g['paid']),cash(g['net']-g['paid'])] for g in groups]
            else:
                headers=['Month','Code','Teacher','Campus','Lectures','Lecture Amount','Net Salary','Paid','Remaining','Status']
                data=[[r.month,employees[r.employee_id].employee_no,employees[r.employee_id].name,details(employees[r.employee_id],'employee').get('campus',''),lecture_count(r) if lecture_count(r) is not None else 'Not captured',cash(r.detail.get('lecture_pay',0)),cash(r.net),cash(r.paid),cash(r.net-r.paid),state(r)] for r in rows]
            return csv_response(headers,data,view)
        return render_template('hrm_salary_reports.html',title='Employee Salary Report' if view=='salary-report' else 'Lecture-wise Salary Report',view=view,start=start,end=end,rows=rows,groups=groups,totals=totals,employees=employees,campuses=sorted({details(e,'employee').get('campus','') for e in employees.values()}-{''}),details=details,state=state,lecture_count=lecture_count)

    @bp.get('/salary/<int:sid>')
    def salary_detail(sid):
        row=db.get_or_404(Salary,sid);employee=db.get_or_404(Employee,row.employee_id)
        return render_template('hrm_salary_detail.html',title='Salary Details',row=row,employee=employee,state=state(row))
    app.register_blueprint(bp)
