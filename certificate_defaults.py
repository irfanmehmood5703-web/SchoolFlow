"""Original editable SchoolFlow documents; no real reference pupil data is seeded."""
DOCUMENTS = [
 ('student-card-new','Student Card New','SCN','card',True),
 ('student-card','Student Card','SC','card',False),
 ('guardian-card','Guardian Card','GC','card',True),
 ('school-leaving','School Leaving Certificate','SLC','document',True),
 ('character','Student Character Certificate','CHAR','document',False),
 ('migration','Migration Slip Campus - Campus','MIG','document',False),
 ('rustication','Student Rustication Notice','SRN','document',False),
 ('warning','Student Warning Letter','SWL','document',True),
 ('trip','Student Trip Letter','TRIP','document',True),
 ('fee-clearance','Student Fee Clearance Certificate','FCC','document',True),
 ('admission-confirmation','Student Admission Confirmation Letter','SAC','document',True),
 ('envelope','Student Envelopes Tags','ENV','label',True),
 ('admitted-card','Student Admitted Card','AC','label',True),
 ('birth','Student Birth Certificate','BRC','document',True),
 ('appreciation','Appreciation Certificate','APP','document',True),
]
CATALOG={key:dict(name=name,prefix=prefix,layout=layout,captured=captured) for key,name,prefix,layout,captured in DOCUMENTS}

HEADER='''<table style="width:100%;border-bottom:3px solid #176b4a"><tr><td style="width:20%">[instLogo]</td><td style="width:60%;text-align:center"><h2>[instName]</h2><p>[instAddress]</p><p>[instContact] · [instEmail]</p></td><td style="width:20%;text-align:right">[stdPic]</td></tr></table>'''
FOOTER='''<table style="width:100%;margin-top:45px"><tr><td style="width:35%;text-align:center">____________________<br>ADMIN OFFICER</td><td style="width:30%;text-align:center">OFFICIAL STAMP</td><td style="width:35%;text-align:center">____________________<br>PRINCIPAL</td></tr></table>'''

def default_content(key):
    name=CATALOG[key]['name']
    title=f'<h1 style="text-align:center;color:#176b4a">{name.upper()}</h1>'
    date='<table style="width:100%"><tr><td>Date: [todayDate]</td><td style="text-align:right">Ref: [reference]</td></tr></table>'
    identity='<p><b>[studentName]</b>, son / daughter of <b>[fatherName]</b>, Class <b>[className]</b>, Section <b>[sectionName]</b>.</p>'
    copy='<p>Certificate copy: [copyType]</p>'
    registration='<table style="width:100%"><tr><td>Registration No.: [regNo]</td><td>Date of Birth: [dob]</td><td>Session: [SessionName]</td></tr></table>'
    body={
      'school-leaving':identity+'<p>Was admitted on <b>[admissionDate]</b> in class <b>[admissionClass]</b> and left on <b>[leavingDate]</b> from class <b>[className]</b>.</p><p>Character: Good</p>'+registration+'<h3>Remarks</h3><p>________________________________________________________</p><h3>Head Teacher’s report on academic ability</h3><p>________________________________________________________</p><p>We wish the student success in future studies.</p>'+copy,
      'character':identity+'<p>This certificate records the student’s character and conduct during attendance at [instName].</p><p>Character / conduct: ____________________</p>'+registration+copy,
      'migration':identity+'<p>Migration from campus: [campusName]</p><p>Migration to campus: ____________________</p><p>Effective date: ____________________</p><p>Reason / remarks: ________________________________________</p>'+registration+copy,
      'rustication':identity+'<p>This notice records an administrative decision concerning the student’s enrolment.</p><p>Effective date: ____________________</p><p>Reason and supporting record: ______________________________</p><p>Parent / guardian acknowledgement: ________________________</p><p>This document does not change the student’s saved status.</p>'+copy,
      'warning':identity+'<h3>Subject: Attendance and academic progress</h3><p>Dear parent / guardian,</p><p>Please meet the school to discuss the student’s attendance, academic progress and agreed steps for improvement.</p><p>Areas requiring attention: ______________________________</p><p>Meeting date and time: _________________________________</p><p>Review date: _________________________________________</p><p>Sincerely,<br>Principal, [instName]</p>',
      'trip':'<h3>Educational and Recreational School Trip</h3><p>Respected Sir / Madam,</p><p>[instName] requests permission to arrange an educational visit to your venue.</p><p>Venue / destination: ______________________________</p><p>Trip date: ______________________________________</p><table style="width:100%"><tr><td>Total students: __________</td><td>Total staff: __________</td></tr></table><p>Regards,<br>Principal<br>[instName]<br>[instContact]</p>',
      'fee-clearance':identity+'<p>Fee position for the academic session [SessionName], as recorded on [todayDate]:</p><table style="width:100%"><tr><th>Decided Tuition Fee</th><td>[tuitionFee]</td></tr><tr><th>Current Month Payable</th><td>[currPayable]</td></tr><tr><th>Current Month Remaining</th><td>[curRemaining]</td></tr><tr><th>Total Outstanding</th><td>[totalRemPayable]</td></tr></table><p>This clearance is issued against the fee records held by the school.</p>'+copy,
      'admission-confirmation':identity+'<p>Admission at [instName] is recorded from [admissionDate].</p><h3>Basic Fee Plan</h3><table style="width:100%"><tr><th>Admission Fee</th><td>[admissionfee]</td></tr><tr><th>Tuition Fee</th><td>[tuitionFee]</td></tr></table><h3>Current Fee Status</h3><table style="width:100%"><tr><th>Payable</th><td>[currPayable]</td></tr><tr><th>Paid</th><td>[currentPaid]</td></tr><tr><th>Remaining</th><td>[curRemaining]</td></tr></table>'+copy,
      'birth':identity+'<p>Is studying at <b>[instName]</b>.</p>'+registration+'<p>The date of birth above is reproduced from the school’s admission record. This is a school-issued record certificate.</p>'+copy,
      'appreciation':identity+'<h3 style="text-align:center">Awarded for Excellence</h3><p>Has achieved position __________ in ____________________ examination / activity.</p><p>We recognise the student’s effort, participation and progress, and wish them continued success.</p>'+copy,
    }
    if key in ('student-card-new','student-card','guardian-card'):
        front='''<table style="width:100%;background-color:#176b4a;color:#ffffff"><tr><td style="text-align:center">[instLogo]<h3>[instName]</h3>[stdPhoto]<h3>[studentName]</h3><p>[fatherName]</p><p>Class: [className] · Section: [sectionName]</p><p>SID: [sid] · Roll: [rollNo]</p><p>Admission: [admissionDate]</p></td></tr></table>'''
        back='''<table style="width:100%"><tr><td style="text-align:center"><h3>STUDENT CARD</h3><p>Campus: [campusName]</p><p>Contact: [fatherMobile]</p><p>Session: [SessionName]</p>[qrCode]<p>If found, please return to:</p><p>[instName]<br>[instAddress]<br>[instContact]</p></td></tr></table>'''
        if key=='guardian-card':back='''<h2 style="text-align:center">GUARDIAN CARD</h2><p>For student pick-up and drop-off</p><h3>[fatherName]</h3><p>Mobile: [fatherMobile]</p><p>Student: [studentName]</p><p>Class: [className] · [sectionName]</p><p>Card expiry: __________________</p><p>If found, return to [instName], [instAddress], [instContact].</p>'''
        return dict(header='',body='<table style="width:100%;height:86mm"><tr><td style="width:50%;vertical-align:top">'+front+'</td><td style="width:50%;vertical-align:top">'+back+'</td></tr></table>',footer='')
    if key in ('envelope','admitted-card'):
        label='<table style="width:100%"><tr><td>[instLogo]</td><td><b>[instName]</b><br>[instAddress]</td></tr><tr><td colspan="2">SID: [sid] · Roll No.: [rollNo]</td></tr><tr><td colspan="2"><b>[studentName]</b> S/D/O [fatherName]<br>[className] · [sectionName] · [SessionName]</td></tr></table>'
        if key=='admitted-card':label+='<p>Admission Date: [admissionDate]</p><p>Admission Fee: [admissionfee] · Tuition Fee: [tuitionFee]</p><p>Payable: [totalPayable] · Paid: [totalPaidAmount] · Remaining: [curRemaining]</p><p>ACCOUNTANT SIGNATURE __________ PRINCIPAL SIGNATURE __________</p>'
        return dict(header='',body=label,footer='')
    return dict(header=HEADER,body=date+title+body[key],footer=FOOTER)
