"""SchoolFlow pre-test application. Existing starter tables are retained."""
import os
import secrets
from datetime import date
from flask import Flask, redirect, request, url_for
from flask_sqlalchemy import SQLAlchemy
from identity import InstituteSession, configure_identity

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.getenv('SECRET_KEY') or secrets.token_hex(32),
    SQLALCHEMY_DATABASE_URI=os.getenv('DATABASE_URL','sqlite:///schoolflow.db').replace('postgres://','postgresql://',1),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SCHOOLFLOW_API_TOKEN=os.getenv('SCHOOLFLOW_API_TOKEN'),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=os.getenv('SESSION_COOKIE_SECURE', '1' if os.getenv('RENDER') else '0') == '1',
    PUBLIC_DEMO_ENABLED=os.getenv('PUBLIC_DEMO_ENABLED', '1') == '1',
    INSTITUTE_DATABASE_DIR=os.getenv('INSTITUTE_DATABASE_DIR'),
)
db=SQLAlchemy(app, session_options={'class_': InstituteSession})

class Student(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    admission_no=db.Column(db.String(30),unique=True,nullable=False)
    name=db.Column(db.String(120),nullable=False)
    father=db.Column(db.String(120))
    class_name=db.Column(db.String(50))
    phone=db.Column(db.String(30))
    status=db.Column(db.String(20),default='Active')

class Attendance(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    student_id=db.Column(db.Integer,db.ForeignKey('student.id'),nullable=False)
    day=db.Column(db.Date,default=date.today)
    status=db.Column(db.String(20),default='Present')
    student=db.relationship('Student')

class ExamResult(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    student_id=db.Column(db.Integer,db.ForeignKey('student.id'),nullable=False)
    exam=db.Column(db.String(80))
    subject=db.Column(db.String(80))
    total=db.Column(db.Float,default=100)
    obtained=db.Column(db.Float,default=0)
    student=db.relationship('Student')

class Employee(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    employee_no=db.Column(db.String(30),unique=True,nullable=False)
    name=db.Column(db.String(120),nullable=False)
    role=db.Column(db.String(80))
    phone=db.Column(db.String(30))
    salary=db.Column(db.Float,default=0)
    status=db.Column(db.String(20),default='Active')

from records import configure_records
from operations import configure_operations
configure_records(app,db,Student,Employee)
configure_operations(app,db,Student,Employee)
from reports import configure_reports
configure_reports(app,db,Student,Employee)
from student_fee_plans import configure_student_fee_plans
configure_student_fee_plans(app,db,Student)
from student_overview import configure_student_overview
configure_student_overview(app,db,Student)
from hrm_reports import configure_hrm_reports
configure_hrm_reports(app,db,Employee)
from certificates import configure_certificates
configure_certificates(app,db,Student)
configure_identity(app,db)
from dashboard import configure_dashboard
configure_dashboard(app,db)
from payroll_calendar import configure_payroll_calendar
configure_payroll_calendar(app,db)
from admission_capacity import configure_admission_capacity
configure_admission_capacity(app,db,Student)

@app.route('/')
def home():
    from flask import render_template
    return render_template('landing.html')

@app.route('/admissions',methods=['GET','POST'])
def admissions():
    return redirect(url_for('records.new_record' if request.method=='POST' else 'records.record_list',kind='student'),code=307 if request.method=='POST' else 302)

@app.route('/hrm',methods=['GET','POST'])
def hrm():
    return redirect(url_for('records.new_record' if request.method=='POST' else 'records.record_list',kind='employee'),code=307 if request.method=='POST' else 302)

@app.route('/attendance')
def attendance(): return redirect(url_for('ops.take_attendance',kind='student'))

@app.route('/exams')
def exams(): return redirect(url_for('ops.examination',kind='awards'))

@app.route('/settings')
def settings(): return redirect(url_for('records.settings'))

@app.route('/favicon.ico')
def favicon(): return '',204

@app.after_request
def headers(response):
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='same-origin'
    response.headers['X-Frame-Options']='SAMEORIGIN'
    if request.path.startswith(('/workspace','/records','/api','/auth')):
        response.headers['Cache-Control']='no-store'
    return response

with app.app_context():
    db.create_all()

if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.getenv('PORT',5000)),debug=False)
