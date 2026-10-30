from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import date
import os

app=Flask(__name__); app.config['SECRET_KEY']=os.getenv('SECRET_KEY','schoolflow-dev-key')
app.config['SQLALCHEMY_DATABASE_URI']=os.getenv('DATABASE_URL','sqlite:///schoolflow.db').replace('postgres://','postgresql://',1)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS']=False
db=SQLAlchemy(app)

class Student(db.Model):
 id=db.Column(db.Integer,primary_key=True); admission_no=db.Column(db.String(30),unique=True,nullable=False); name=db.Column(db.String(120),nullable=False); father=db.Column(db.String(120)); class_name=db.Column(db.String(50)); phone=db.Column(db.String(30)); status=db.Column(db.String(20),default='Active')
class Attendance(db.Model):
 id=db.Column(db.Integer,primary_key=True); student_id=db.Column(db.Integer,db.ForeignKey('student.id'),nullable=False); day=db.Column(db.Date,default=date.today); status=db.Column(db.String(20),default='Present'); student=db.relationship('Student')
class ExamResult(db.Model):
 id=db.Column(db.Integer,primary_key=True); student_id=db.Column(db.Integer,db.ForeignKey('student.id'),nullable=False); exam=db.Column(db.String(80)); subject=db.Column(db.String(80)); total=db.Column(db.Float,default=100); obtained=db.Column(db.Float,default=0); student=db.relationship('Student')
class Employee(db.Model):
 id=db.Column(db.Integer,primary_key=True); employee_no=db.Column(db.String(30),unique=True,nullable=False); name=db.Column(db.String(120),nullable=False); role=db.Column(db.String(80)); phone=db.Column(db.String(30)); salary=db.Column(db.Float,default=0); status=db.Column(db.String(20),default='Active')

@app.route('/')
def dashboard():
 return render_template('dashboard.html', students=Student.query.count(), employees=Employee.query.count(), attendance=Attendance.query.filter_by(day=date.today()).count(), results=ExamResult.query.count())
@app.route('/admissions',methods=['GET','POST'])
def admissions():
 if request.method=='POST':
  try:
   db.session.add(Student(admission_no=request.form['admission_no'],name=request.form['name'],father=request.form.get('father'),class_name=request.form.get('class_name'),phone=request.form.get('phone'))); db.session.commit(); flash('Student admitted successfully.','success')
  except Exception: db.session.rollback(); flash('Admission number must be unique.','error')
  return redirect(url_for('admissions'))
 return render_template('admissions.html',rows=Student.query.order_by(Student.id.desc()).all())
@app.route('/attendance',methods=['GET','POST'])
def attendance():
 if request.method=='POST':
  db.session.add(Attendance(student_id=int(request.form['student_id']),status=request.form['status'])); db.session.commit(); flash('Attendance saved.','success'); return redirect(url_for('attendance'))
 return render_template('attendance.html',students=Student.query.all(),rows=Attendance.query.order_by(Attendance.id.desc()).limit(30).all())
@app.route('/exams',methods=['GET','POST'])
def exams():
 if request.method=='POST':
  db.session.add(ExamResult(student_id=int(request.form['student_id']),exam=request.form['exam'],subject=request.form['subject'],total=float(request.form['total']),obtained=float(request.form['obtained']))); db.session.commit(); flash('Result saved.','success'); return redirect(url_for('exams'))
 return render_template('exams.html',students=Student.query.all(),rows=ExamResult.query.order_by(ExamResult.id.desc()).all())
@app.route('/hrm',methods=['GET','POST'])
def hrm():
 if request.method=='POST':
  try:
   db.session.add(Employee(employee_no=request.form['employee_no'],name=request.form['name'],role=request.form.get('role'),phone=request.form.get('phone'),salary=float(request.form.get('salary') or 0))); db.session.commit(); flash('Employee added.','success')
  except Exception: db.session.rollback(); flash('Employee number must be unique.','error')
  return redirect(url_for('hrm'))
 return render_template('hrm.html',rows=Employee.query.order_by(Employee.id.desc()).all())
@app.route('/settings')
def settings(): return render_template('settings.html')

from records import configure_records
configure_records(app, db, Student, Employee)

def admissions_entry():
 return redirect(url_for('records.new_record' if request.method == 'POST' else 'records.record_list',kind='student'), code=307 if request.method == 'POST' else 302)
def employees_entry():
 return redirect(url_for('records.new_record' if request.method == 'POST' else 'records.record_list',kind='employee'), code=307 if request.method == 'POST' else 302)
app.view_functions['admissions'] = admissions_entry
app.view_functions['hrm'] = employees_entry

with app.app_context(): db.create_all()
if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.getenv('PORT',5000)),debug=os.getenv('FLASK_DEBUG') == '1')
